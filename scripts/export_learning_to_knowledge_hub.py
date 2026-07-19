from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
TAIPEI = ZoneInfo("Asia/Taipei")
DOMAIN = "taiwan_stock"

DEFAULT_HUB_ROOT = Path("C:/Users/User/trading_knowledge_hub")
DEFAULT_HUB_FILE = DEFAULT_HUB_ROOT / "data" / "knowledge_points.jsonl"
LEGACY_HUB_FILE = DEFAULT_HUB_ROOT / "data" / "knowledge.jsonl"
REPO_EXPORT_FILE = ROOT / "data" / "knowledge_exports" / "taiwan_stock_learning.jsonl"


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _default_output() -> Path:
    env_path = os.getenv("TRADING_KNOWLEDGE_HUB_FILE")
    if env_path:
        return Path(env_path)
    if DEFAULT_HUB_FILE.exists():
        return DEFAULT_HUB_FILE
    if LEGACY_HUB_FILE.exists():
        return LEGACY_HUB_FILE
    if DEFAULT_HUB_ROOT.exists():
        return DEFAULT_HUB_FILE
    return REPO_EXPORT_FILE


def _stable_id(topic: str, claim: str) -> str:
    digest = hashlib.sha1(f"{DOMAIN}|{topic}|{claim}".encode("utf-8")).hexdigest()[:14]
    return f"kp_{digest}"


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value, default: str = "未命名") -> str:
    text = str(value or default).strip()
    return text if text else default


def _fmt_pct(value) -> str:
    if value is None:
        return "NA"
    return f"{_num(value):.1f}%"


def _confidence(completed: int, avg_return_5d: float | None, win_rate_5d: float | None) -> float:
    sample_score = min(max(completed, 0) / 60, 1) * 0.35
    return_score = min(abs(_num(avg_return_5d)) / 10, 1) * 0.25
    win_score = min(abs(_num(win_rate_5d, 50) - 50) / 50, 1) * 0.20
    return round(min(0.20 + sample_score + return_score + win_score, 0.90), 2)


def _status(completed: int) -> str:
    if completed >= 60:
        return "backtest_supported"
    if completed >= 20:
        return "pending_validation"
    return "draft"


def _knowledge(
    *,
    topic: str,
    claim: str,
    evidence: str,
    tags: list[str],
    completed: int,
    avg_return_5d: float | None,
    win_rate_5d: float | None,
    source_ref: str,
) -> dict:
    created = _now()
    return {
        "id": _stable_id(topic, claim),
        "topic": topic,
        "claim": claim,
        "domain": DOMAIN,
        "status": _status(completed),
        "evidence": evidence,
        "source_type": "backtest",
        "source_ref": source_ref,
        "tags": tags,
        "confidence": _confidence(completed, avg_return_5d, win_rate_5d),
        "created_at": created,
        "updated_at": created,
    }


def build_knowledge_points(performance: dict) -> list[dict]:
    as_of = _text(performance.get("as_of"), "")
    source_ref = f"tw-stock-ai performance_data.json {as_of}".strip()
    points: list[dict] = []

    attribution = performance.get("signal_attribution") or {}
    for row in (attribution.get("factor_rows") or [])[:12]:
        completed = _int(row.get("completed"))
        if completed <= 0:
            continue
        label = _text(row.get("label"), "未命名因素")
        avg_return = row.get("avg_return_5d")
        win_rate = row.get("win_rate_5d")
        claim = (
            f"{label} 在已完成樣本中，5 日平均報酬 {_fmt_pct(avg_return)}，"
            f"5 日勝率 {_fmt_pct(win_rate)}。"
        )
        evidence = (
            f"signals={row.get('signals', 0)}, completed={completed}, "
            f"sample={row.get('sample_label', '')}"
        )
        points.append(
            _knowledge(
                topic=f"台股訊號因素：{label}",
                claim=claim,
                evidence=evidence,
                tags=["台股", "訊號歸因", label],
                completed=completed,
                avg_return_5d=avg_return,
                win_rate_5d=win_rate,
                source_ref=source_ref,
            )
        )

    failure_rows = ((performance.get("postmortem") or {}).get("failure_attribution") or {}).get("rows") or []
    for row in failure_rows[:10]:
        count = _int(row.get("count"))
        if count <= 0:
            continue
        label = _text(row.get("label"), "未命名失敗因素")
        avg_return = row.get("avg_return_5d")
        claim = f"{label} 常出現在失敗樣本，5 日平均報酬 {_fmt_pct(avg_return)}。"
        evidence = (
            f"count={count}, stop_hit_rate={_fmt_pct(row.get('stop_hit_rate'))}, "
            f"lesson={row.get('lesson', '')}"
        )
        points.append(
            _knowledge(
                topic=f"台股失敗歸因：{label}",
                claim=claim,
                evidence=evidence,
                tags=["台股", "失敗歸因", label],
                completed=count,
                avg_return_5d=avg_return,
                win_rate_5d=None,
                source_ref=source_ref,
            )
        )

    for row in performance.get("adaptive_feedback") or []:
        sample = _int(row.get("sample"))
        if sample <= 0:
            continue
        target = _text(row.get("target"), "未命名目標")
        action = _text(row.get("action"), "持續觀察")
        claim = f"{target} 的回測回饋建議為「{action}」。"
        evidence = (
            f"sample={sample}, avg_return_5d={_fmt_pct(row.get('avg_return_5d'))}, "
            f"reason={row.get('reason', '')}"
        )
        points.append(
            _knowledge(
                topic=f"台股回測回饋：{target}",
                claim=claim,
                evidence=evidence,
                tags=["台股", "回測回饋", target],
                completed=sample,
                avg_return_5d=row.get("avg_return_5d"),
                win_rate_5d=None,
                source_ref=source_ref,
            )
        )

    low_win = performance.get("low_win_rate_breakdown") or {}
    target_win_rate = low_win.get("target_win_rate_5d", 50)
    for row in low_win.get("rows") or []:
        completed = _int(row.get("completed"))
        if completed <= 0:
            continue
        group = _text(row.get("group"), "低勝率區塊")
        label = _text(row.get("label"), "未命名")
        avg_return = row.get("avg_return_5d")
        win_rate = row.get("win_rate_5d")
        claim = (
            f"{group}「{label}」拖累近期勝率："
            f"完成 {completed} 筆，5 日勝率 {_fmt_pct(win_rate)}，"
            f"低於基準 {_fmt_pct(target_win_rate)}，5 日平均報酬 {_fmt_pct(avg_return)}。"
        )
        evidence = (
            f"drag_score={row.get('drag_score')}, sample={row.get('sample_label')}, "
            f"diagnosis={row.get('diagnosis')}, recommended_action={row.get('recommended_action')}"
        )
        points.append(
            _knowledge(
                topic=f"台股低勝率拆解：{group}:{label}",
                claim=claim,
                evidence=evidence,
                tags=["台股", "低勝率拆解", group, label],
                completed=completed,
                avg_return_5d=avg_return,
                win_rate_5d=win_rate,
                source_ref=source_ref,
            )
        )

    current_backtest = performance.get("current_selection_backtest") or {}
    for section, polarity in [("strong_references", "正向"), ("weak_references", "偏弱")]:
        for row in (current_backtest.get(section) or [])[:8]:
            profile = row.get("historical_profile") or {}
            completed = _int(profile.get("completed"))
            if completed <= 0:
                continue
            name = _text(row.get("name"), "")
            stock_id = _text(row.get("stock_id"), "")
            action = _text(row.get("action"), "")
            grade = _text(row.get("grade"), "")
            avg_return = profile.get("avg_return_5d")
            win_rate = profile.get("win_rate_5d")
            theme_tags = [_text(theme, "") for theme in (row.get("themes") or []) if theme]
            topic_label = f"{stock_id} {name}".strip() or "候選股"
            claim = (
                f"{topic_label} 的今日條件歷史參考為{polarity}："
                f"{completed} 筆樣本，5 日平均報酬 {_fmt_pct(avg_return)}，"
                f"5 日勝率 {_fmt_pct(win_rate)}。"
            )
            evidence = (
                f"grade={grade}, action={action}, match_type={profile.get('match_type')}, "
                f"same_profile_completed={profile.get('same_profile_completed')}, "
                f"interpretation={row.get('interpretation', '')}"
            )
            points.append(
                _knowledge(
                    topic=f"今日候選股同條件回測：{topic_label}",
                    claim=claim,
                    evidence=evidence,
                    tags=["今日候選股", "同條件回測", polarity, grade, action, *theme_tags],
                    completed=completed,
                    avg_return_5d=avg_return,
                    win_rate_5d=win_rate,
                    source_ref=source_ref,
                )
            )

    return _dedupe_by_id(points)


def build_weekly_review_points(weekly_review: dict) -> list[dict]:
    as_of = _text(weekly_review.get("as_of"), "")
    source_ref = f"tw-stock-ai weekly_review.json {as_of}".strip()
    points: list[dict] = []
    for row in weekly_review.get("next_week_actions") or []:
        target = _text(row.get("target"), "未命名檢討項")
        reason = _text(row.get("reason"), "")
        action_type = _text(row.get("type"), "review")
        claim = f"每週檢討建議下週對「{target}」採取 {action_type}：{reason}"
        points.append(
            _knowledge(
                topic=f"台股每週檢討：{target}",
                claim=claim,
                evidence=f"risk_level={weekly_review.get('risk_level')}, action_type={action_type}",
                tags=["台股", "每週檢討", action_type, target],
                completed=20,
                avg_return_5d=None,
                win_rate_5d=None,
                source_ref=source_ref,
            )
        )
    return _dedupe_by_id(points)


def build_research_source_points(research_review: dict) -> list[dict]:
    source_ref = "tw-stock-ai research_source_review.json"
    points: list[dict] = []
    for row in research_review.get("rows") or []:
        status = _text(row.get("status"), "candidate")
        if status not in {"adopted", "candidate"}:
            continue
        name = _text(row.get("name"), "未命名來源")
        integration = _text(row.get("integration"), "research")
        risk_level = _text(row.get("risk_level"), "unknown")
        claim = (
            f"{name} 可作為台股系統的 {integration} 參考來源；"
            f"目前狀態為 {status}，風險層級 {risk_level}。"
        )
        evidence = (
            f"decision_use={row.get('decision_use', '')}; "
            f"score_use={row.get('score_use', '')}; url={row.get('url', '')}"
        )
        points.append(
            _knowledge(
                topic=f"台股外部資料源：{name}",
                claim=claim,
                evidence=evidence,
                tags=["台股", "外部資料源", status, integration, risk_level],
                completed=20 if status == "adopted" else 5,
                avg_return_5d=None,
                win_rate_5d=None,
                source_ref=source_ref,
            )
        )
    return _dedupe_by_id(points)


def _dedupe_by_id(items: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for item in items:
        by_id[item["id"]] = item
    return list(by_id.values())


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def upsert_jsonl(path: Path, items: list[dict], *, replace_retries: int = 5, retry_delay: float = 0.4) -> dict:
    existing = _read_jsonl(path)
    by_id = {str(item.get("id")): item for item in existing if item.get("id")}
    inserted = 0
    updated = 0

    for item in items:
        item_id = item["id"]
        old = by_id.get(item_id)
        if old:
            item["created_at"] = old.get("created_at") or item["created_at"]
            updated += 1
        else:
            inserted += 1
        item["updated_at"] = _now()
        by_id[item_id] = item

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in by_id.values()) + "\n",
        encoding="utf-8",
    )
    last_error: PermissionError | None = None
    for attempt in range(max(1, replace_retries)):
        try:
            tmp.replace(path)
            last_error = None
            break
        except PermissionError as exc:
            last_error = exc
            time.sleep(retry_delay * (attempt + 1))
    if last_error is not None:
        raise last_error
    return {"inserted": inserted, "updated": updated, "total": len(by_id), "exported": len(items)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export tw-stock-ai learning outcomes into Trading Knowledge Hub JSONL.")
    parser.add_argument("--performance", default="dashboard/performance_data.json")
    parser.add_argument("--weekly-review", default="dashboard/weekly_review.json")
    parser.add_argument("--research-source-review", default="dashboard/research_source_review.json")
    parser.add_argument("--output", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Exit cleanly only when an explicitly requested external output parent is missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    performance_path = Path(args.performance)
    output = Path(args.output) if args.output else _default_output()

    if args.skip_missing and args.output and not output.parent.exists():
        print(f"knowledge export skipped: missing parent {output.parent}")
        return 0
    if not performance_path.exists():
        raise SystemExit(f"missing performance payload: {performance_path}")

    performance = json.loads(performance_path.read_text(encoding="utf-8"))
    items = build_knowledge_points(performance)
    weekly_review_path = Path(args.weekly_review)
    if weekly_review_path.exists():
        items.extend(build_weekly_review_points(json.loads(weekly_review_path.read_text(encoding="utf-8"))))
        items = _dedupe_by_id(items)
    research_review_path = Path(args.research_source_review)
    if research_review_path.exists():
        items.extend(build_research_source_points(json.loads(research_review_path.read_text(encoding="utf-8"))))
        items = _dedupe_by_id(items)
    if args.dry_run:
        print(json.dumps({"exported": len(items), "output": str(output), "sample": items[:3]}, ensure_ascii=False, indent=2))
        return 0

    summary = upsert_jsonl(output, items)
    print(
        "knowledge export "
        f"exported={summary['exported']} inserted={summary['inserted']} "
        f"updated={summary['updated']} total={summary['total']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
