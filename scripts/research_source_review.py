from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
REQUIRED_FIELDS = {
    "id",
    "name",
    "url",
    "source_type",
    "priority",
    "status",
    "integration",
    "decision_use",
    "score_use",
    "risks",
    "ui_policy",
}
STATUS_ORDER = {"adopted": 0, "candidate": 1, "watch": 2, "rejected": 3}
PRIORITY_WEIGHT = {"core": 100, "high": 70, "medium": 40, "low": 10}


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _read_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _risk_level(source: dict) -> str:
    risks = set(source.get("risks") or [])
    if "terms_of_use" in risks or "unknown_methodology" in risks:
        return "needs_manual_review"
    if source.get("source_type", "").startswith("official"):
        return "low"
    if "unofficial_source" in risks or "external_availability" in risks:
        return "medium"
    return "low"


def _score(source: dict) -> int:
    base = PRIORITY_WEIGHT.get(source.get("priority"), 0)
    status = source.get("status")
    if status == "adopted":
        base += 20
    if _risk_level(source) == "needs_manual_review":
        base -= 15
    return max(base, 0)


def build_review(registry: dict) -> dict:
    issues: list[dict] = []
    rows: list[dict] = []
    seen: set[str] = set()

    for index, source in enumerate(registry.get("sources") or [], start=1):
        missing = sorted(REQUIRED_FIELDS - set(source))
        source_id = str(source.get("id") or f"row_{index}")
        if source_id in seen:
            issues.append({"level": "critical", "source_id": source_id, "message": "duplicate source id"})
        seen.add(source_id)
        if missing:
            issues.append(
                {
                    "level": "critical",
                    "source_id": source_id,
                    "message": f"missing required fields: {', '.join(missing)}",
                }
            )
        if source.get("ui_policy") not in {"internal_only", "summary_only", "status_only"}:
            issues.append({"level": "warning", "source_id": source_id, "message": "unknown ui_policy"})

        rows.append(
            {
                "id": source_id,
                "name": source.get("name"),
                "status": source.get("status"),
                "priority": source.get("priority"),
                "integration": source.get("integration"),
                "risk_level": _risk_level(source),
                "score": _score(source),
                "ui_policy": source.get("ui_policy"),
                "decision_use": source.get("decision_use"),
                "score_use": source.get("score_use"),
                "url": source.get("url"),
            }
        )

    rows.sort(
        key=lambda row: (
            STATUS_ORDER.get(row.get("status"), 9),
            -int(row.get("score") or 0),
            str(row.get("id")),
        )
    )
    adopted = [row for row in rows if row.get("status") == "adopted"]
    candidates = [row for row in rows if row.get("status") == "candidate"]
    next_actions = [
        f"{row['name']} -> {row['integration']}"
        for row in candidates
        if row.get("risk_level") != "needs_manual_review"
    ][:5]
    manual_review = [row["name"] for row in rows if row.get("risk_level") == "needs_manual_review"]

    return {
        "generated_at": _now(),
        "status": "bad" if any(item["level"] == "critical" for item in issues) else "ok",
        "summary": {
            "total": len(rows),
            "adopted": len(adopted),
            "candidates": len(candidates),
            "manual_review": len(manual_review),
        },
        "rows": rows,
        "issues": issues,
        "next_actions": next_actions,
        "manual_review_sources": manual_review,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review external research sources before integrating them into scoring.")
    parser.add_argument("--registry", default="data/research_source_registry.json")
    parser.add_argument("--output", default="dashboard/research_source_review.json")
    parser.add_argument("--docs-output", default="docs/research_source_review.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry_path = Path(args.registry)
    output_path = Path(args.output)
    review = build_review(_read_registry(registry_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.docs_output:
        docs_path = Path(args.docs_output)
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "research-source-review "
        f"status={review['status']} total={review['summary']['total']} "
        f"adopted={review['summary']['adopted']} candidates={review['summary']['candidates']}"
    )
    return 0 if review["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
