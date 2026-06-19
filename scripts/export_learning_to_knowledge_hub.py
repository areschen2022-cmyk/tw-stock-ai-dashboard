from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_HUB_FILE = Path("C:/Users/User/trading_knowledge_hub/data/knowledge.jsonl")
DOMAIN = "taiwan_stock"


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _stable_id(topic: str, claim: str) -> str:
    digest = hashlib.sha1(f"{DOMAIN}|{topic}|{claim}".encode("utf-8")).hexdigest()[:14]
    return f"kp_{digest}"


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence(completed: int, avg_return_5d: float | None, win_rate_5d: float | None) -> float:
    sample_score = min(max(completed, 0) / 60, 1) * 0.35
    return_score = min(abs(_num(avg_return_5d)) / 10, 1) * 0.25
    win_score = min(abs(_num(win_rate_5d, 50) - 50) / 50, 1) * 0.2
    base = 0.2
    return round(min(base + sample_score + return_score + win_score, 0.9), 2)


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
    avg_return_5d: float | None = None,
    win_rate_5d: float | None = None,
    source_ref: str,
) -> dict:
    created = _now()
    item_id = _stable_id(topic, claim)
    return {
        "id": item_id,
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


def _fmt_pct(value) -> str:
    if value is None:
        return "NA"
    return f"{_num(value):.1f}%"


def build_knowledge_points(performance: dict) -> list[dict]:
    as_of = str(performance.get("as_of") or "")
    source_ref = f"tw-stock-ai performance_data.json {as_of}".strip()
    points: list[dict] = []

    attribution = performance.get("signal_attribution") or {}
    for row in (attribution.get("factor_rows") or [])[:12]:
        completed = int(row.get("completed") or 0)
        if completed <= 0:
            continue
        label = str(row.get("label") or "未命名因素")
        avg_return = row.get("avg_return_5d")
        win_rate = row.get("win_rate_5d")
        claim = (
            f"{label} 在目前樣本中 5 日平均報酬 {_fmt_pct(avg_return)}，"
            f"5 日勝率 {_fmt_pct(win_rate)}。"
        )
        evidence = f"signals={row.get('signals', 0)}, completed={completed}, sample={row.get('sample_label', '')}"
        points.append(
            _knowledge(
                topic=f"台股因素成效：{label}",
                claim=claim,
                evidence=evidence,
                tags=["台股", "因素歸因", label],
                completed=completed,
                avg_return_5d=avg_return,
                win_rate_5d=win_rate,
                source_ref=source_ref,
            )
        )

    postmortem = performance.get("postmortem") or {}
    failure_attr = (postmortem.get("failure_attribution") or {}).get("rows") or []
    for row in failure_attr[:10]:
        count = int(row.get("count") or 0)
        if count <= 0:
            continue
        label = str(row.get("label") or "未命名失敗原因")
        avg_return = row.get("avg_return_5d")
        claim = f"{label} 是目前失敗樣本中的常見風險，5 日平均報酬 {_fmt_pct(avg_return)}。"
        evidence = f"count={count}, stop_hit_rate={_fmt_pct(row.get('stop_hit_rate'))}, lesson={row.get('lesson', '')}"
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
        sample = int(row.get("sample") or 0)
        if sample <= 0:
            continue
        target = str(row.get("target") or "整體")
        action = str(row.get("action") or "持續觀察")
        claim = f"{target} 的建議調整為「{action}」。"
        evidence = f"sample={sample}, avg_return_5d={_fmt_pct(row.get('avg_return_5d'))}, reason={row.get('reason', '')}"
        points.append(
            _knowledge(
                topic=f"台股規則調整建議：{target}",
                claim=claim,
                evidence=evidence,
                tags=["台股", "規則調整", target],
                completed=sample,
                avg_return_5d=row.get("avg_return_5d"),
                win_rate_5d=None,
                source_ref=source_ref,
            )
        )

    return _dedupe_by_id(points)


def _dedupe_by_id(items: list[dict]) -> list[dict]:
    result: dict[str, dict] = {}
    for item in items:
        result[item["id"]] = item
    return list(result.values())


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


def upsert_jsonl(path: Path, items: list[dict]) -> dict:
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
    tmp.replace(path)
    return {"inserted": inserted, "updated": updated, "total": len(by_id), "exported": len(items)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export tw-stock-ai learning outcomes into trading knowledge hub JSONL.")
    parser.add_argument("--performance", default="dashboard/performance_data.json")
    parser.add_argument("--output", default=os.getenv("TRADING_KNOWLEDGE_HUB_FILE") or str(DEFAULT_HUB_FILE))
    parser.add_argument("--skip-missing", action="store_true", help="Exit cleanly when output file parent does not exist.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    performance_path = Path(args.performance)
    output = Path(args.output)

    if args.skip_missing and not output.parent.exists():
        print(f"knowledge export skipped: missing parent {output.parent}")
        return 0
    if not performance_path.exists():
        raise SystemExit(f"missing performance payload: {performance_path}")

    performance = json.loads(performance_path.read_text(encoding="utf-8"))
    items = build_knowledge_points(performance)
    summary = upsert_jsonl(output, items)
    print(
        "knowledge export "
        f"exported={summary['exported']} inserted={summary['inserted']} "
        f"updated={summary['updated']} total={summary['total']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
