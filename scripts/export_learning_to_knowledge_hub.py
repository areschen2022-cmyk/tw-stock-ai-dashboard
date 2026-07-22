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


def _text(value, default: str = "unknown") -> str:
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
        "tags": [str(tag) for tag in tags if str(tag or "").strip()],
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
        label = _text(row.get("label"), "factor")
        avg_return = row.get("avg_return_5d")
        win_rate = row.get("win_rate_5d")
        claim = (
            f"Factor {label} has {completed} completed samples; "
            f"5-day win rate {_fmt_pct(win_rate)}, average return {_fmt_pct(avg_return)}."
        )
        evidence = f"signals={row.get('signals', 0)}, sample={row.get('sample_label', '')}"
        points.append(
            _knowledge(
                topic=f"Taiwan stock factor attribution: {label}",
                claim=claim,
                evidence=evidence,
                tags=["taiwan_stock", "factor_attribution", label],
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
        label = _text(row.get("label"), "failure")
        avg_return = row.get("avg_return_5d")
        claim = f"Failure factor {label} appeared in {count} losing samples; average return {_fmt_pct(avg_return)}."
        evidence = f"stop_hit_rate={_fmt_pct(row.get('stop_hit_rate'))}, lesson={row.get('lesson', '')}"
        points.append(
            _knowledge(
                topic=f"Taiwan stock failure attribution: {label}",
                claim=claim,
                evidence=evidence,
                tags=["taiwan_stock", "failure_attribution", label],
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
        target = _text(row.get("target"), "target")
        action = _text(row.get("action"), "review")
        claim = f"Adaptive feedback suggests {action} for {target} based on {sample} samples."
        evidence = f"avg_return_5d={_fmt_pct(row.get('avg_return_5d'))}, reason={row.get('reason', '')}"
        points.append(
            _knowledge(
                topic=f"Taiwan stock adaptive feedback: {target}",
                claim=claim,
                evidence=evidence,
                tags=["taiwan_stock", "adaptive_feedback", target, action],
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
        group = _text(row.get("group"), "group")
        label = _text(row.get("label"), "label")
        avg_return = row.get("avg_return_5d")
        win_rate = row.get("win_rate_5d")
        claim = (
            f"Low win-rate group {group}:{label} has {completed} samples; "
            f"5-day win rate {_fmt_pct(win_rate)} vs target {_fmt_pct(target_win_rate)}, "
            f"average return {_fmt_pct(avg_return)}."
        )
        evidence = (
            f"drag_score={row.get('drag_score')}, sample={row.get('sample_label')}, "
            f"diagnosis={row.get('diagnosis')}, recommended_action={row.get('recommended_action')}"
        )
        points.append(
            _knowledge(
                topic=f"Taiwan stock low win-rate breakdown: {group}:{label}",
                claim=claim,
                evidence=evidence,
                tags=["taiwan_stock", "low_win_rate", group, label],
                completed=completed,
                avg_return_5d=avg_return,
                win_rate_5d=win_rate,
                source_ref=source_ref,
            )
        )

    current_backtest = performance.get("current_selection_backtest") or {}
    for section, polarity in [("strong_references", "strong"), ("weak_references", "weak")]:
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
            topic_label = f"{stock_id} {name}".strip() or "candidate"
            claim = (
                f"Current candidate {topic_label} has {polarity} historical profile; "
                f"{completed} comparable samples, average 5-day return {_fmt_pct(avg_return)}, "
                f"5-day win rate {_fmt_pct(win_rate)}."
            )
            evidence = (
                f"grade={grade}, action={action}, match_type={profile.get('match_type')}, "
                f"same_profile_completed={profile.get('same_profile_completed')}, "
                f"interpretation={row.get('interpretation', '')}"
            )
            points.append(
                _knowledge(
                    topic=f"Taiwan stock current candidate profile: {topic_label}",
                    claim=claim,
                    evidence=evidence,
                    tags=["taiwan_stock", "current_candidate", polarity, grade, action, *theme_tags],
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
        target = _text(row.get("target"), "target")
        reason = _text(row.get("reason"), "")
        action_type = _text(row.get("type"), "review")
        claim = f"Weekly review action {action_type} for {target}: {reason}"
        points.append(
            _knowledge(
                topic=f"Taiwan stock weekly review action: {target}",
                claim=claim,
                evidence=f"risk_level={weekly_review.get('risk_level')}, action_type={action_type}",
                tags=["taiwan_stock", "weekly_review", action_type, target],
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
        name = _text(row.get("name"), "source")
        integration = _text(row.get("integration"), "research")
        risk_level = _text(row.get("risk_level"), "unknown")
        claim = (
            f"Research source {name} is marked {status}; integration={integration}; "
            f"risk_level={risk_level}."
        )
        evidence = f"decision_use={row.get('decision_use', '')}; score_use={row.get('score_use', '')}; url={row.get('url', '')}"
        points.append(
            _knowledge(
                topic=f"Taiwan stock research source review: {name}",
                claim=claim,
                evidence=evidence,
                tags=["taiwan_stock", "research_source", status, integration, risk_level],
                completed=20 if status == "adopted" else 5,
                avg_return_5d=None,
                win_rate_5d=None,
                source_ref=source_ref,
            )
        )
    return _dedupe_by_id(points)


def build_kronos_proxy_points(kronos_payload: dict) -> list[dict]:
    as_of = _text(kronos_payload.get("as_of"), "")
    source_ref = f"tw-stock-ai kronos_proxy_backtest.json {as_of}".strip()
    phase2 = kronos_payload.get("phase2") or {}
    summary = kronos_payload.get("summary") or {}
    overall = summary.get("overall_5d") or {}
    segments = summary.get("phase2_segments") or {}
    points: list[dict] = []

    completed = _int(overall.get("completed"))
    if completed > 0:
        status = _text(phase2.get("status"), "unknown")
        claim = (
            f"Kronos proxy overall validation status is {status}; "
            f"{completed} completed 5-day samples, win rate {_fmt_pct(overall.get('win_rate'))}, "
            f"average 5-day return {_fmt_pct(overall.get('avg_return'))}."
        )
        evidence = "; ".join(str(item) for item in (phase2.get("recommended_integration") or [])[:3])
        points.append(
            _knowledge(
                topic="Taiwan stock Kronos proxy overall validation",
                claim=claim,
                evidence=evidence,
                tags=["taiwan_stock", "Kronos", "proxy_backtest", "phase2", status],
                completed=completed,
                avg_return_5d=overall.get("avg_return"),
                win_rate_5d=overall.get("win_rate"),
                source_ref=source_ref,
            )
        )

    for row in summary.get("by_bias") or []:
        completed = _int(row.get("completed"))
        if completed <= 0:
            continue
        bias = _text(row.get("kronos_bias"), "unknown")
        claim = (
            f"Kronos proxy bias {bias} has 5-day win rate {_fmt_pct(row.get('win_rate'))} "
            f"and average 5-day return {_fmt_pct(row.get('avg_return'))}."
        )
        evidence = f"signals={row.get('signals')}, completed={completed}, median={row.get('median_return')}"
        points.append(
            _knowledge(
                topic=f"Taiwan stock Kronos proxy bias: {bias}",
                claim=claim,
                evidence=evidence,
                tags=["taiwan_stock", "Kronos", "proxy_backtest", bias],
                completed=completed,
                avg_return_5d=row.get("avg_return"),
                win_rate_5d=row.get("win_rate"),
                source_ref=source_ref,
            )
        )

    for bucket_name, tag in [("qualified_segments", "qualified"), ("weak_segments", "weak")]:
        for row in (segments.get(bucket_name) or [])[:10]:
            completed = _int(row.get("completed"))
            if completed <= 0:
                continue
            segment = _text(row.get("segment"), "unknown")
            value = _text(row.get("value"), "unknown")
            claim = (
                f"Kronos proxy segment {segment}={value} is {tag}; "
                f"{completed} completed samples, 5-day win rate {_fmt_pct(row.get('win_rate'))}, "
                f"average return {_fmt_pct(row.get('avg_return'))}, "
                f"edge vs baseline {row.get('edge_avg_return')} pct."
            )
            evidence = (
                f"baseline={segments.get('baseline')}; edge_win_rate={row.get('edge_win_rate')}; "
                f"min_completed={segments.get('min_completed')}"
            )
            points.append(
                _knowledge(
                    topic=f"Taiwan stock Kronos proxy segment {tag}: {segment}={value}",
                    claim=claim,
                    evidence=evidence,
                    tags=["taiwan_stock", "Kronos", "proxy_backtest", "segment", tag, segment, value],
                    completed=completed,
                    avg_return_5d=row.get("avg_return"),
                    win_rate_5d=row.get("win_rate"),
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
    parser.add_argument("--kronos-proxy", default="dashboard/kronos_proxy_backtest.json")
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
    kronos_path = Path(args.kronos_proxy)
    if kronos_path.exists():
        items.extend(build_kronos_proxy_points(json.loads(kronos_path.read_text(encoding="utf-8"))))
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
