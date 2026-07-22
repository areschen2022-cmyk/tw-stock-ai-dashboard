from __future__ import annotations

import json

from scripts.export_learning_to_knowledge_hub import build_knowledge_points, build_weekly_review_points, upsert_jsonl


def _performance_payload() -> dict:
    return {
        "as_of": "2026-06-18",
        "signal_attribution": {
            "factor_rows": [
                {
                    "label": "AI agreement",
                    "signals": 12,
                    "completed": 6,
                    "win_rate_5d": 66.7,
                    "avg_return_5d": 3.2,
                    "sample_label": "small sample",
                }
            ]
        },
        "postmortem": {
            "failure_attribution": {
                "rows": [
                    {
                        "label": "overheated",
                        "count": 3,
                        "avg_return_5d": -4.5,
                        "stop_hit_rate": 33.3,
                        "lesson": "avoid chasing overextended names",
                    }
                ]
            }
        },
        "adaptive_feedback": [
            {
                "target": "AI agreement",
                "action": "raise threshold",
                "sample": 6,
                "avg_return_5d": 3.2,
                "reason": "small but positive sample",
            }
        ],
        "low_win_rate_breakdown": {
            "target_win_rate_5d": 50.0,
            "rows": [
                {
                    "group": "action",
                    "label": "chase",
                    "completed": 25,
                    "signals": 30,
                    "win_rate_5d": 36.0,
                    "avg_return_5d": -2.4,
                    "drag_score": 4.1,
                    "sample_label": "weak cohort",
                    "diagnosis": "bad risk/reward",
                    "recommended_action": "downgrade",
                }
            ],
        },
    }


def test_build_knowledge_points_from_performance_payload() -> None:
    points = build_knowledge_points(_performance_payload())

    assert len(points) == 4
    assert all(point["domain"] == "taiwan_stock" for point in points)
    assert any(point["topic"].startswith("Taiwan stock factor attribution") for point in points)
    assert any("Taiwan stock failure attribution" in point["topic"] for point in points)
    assert any("Taiwan stock adaptive feedback" in point["topic"] for point in points)
    assert any("Taiwan stock low win-rate breakdown" in point["topic"] for point in points)
    assert all(point["id"].startswith("kp_") for point in points)
    assert all("�" not in json.dumps(point, ensure_ascii=False) for point in points)


def test_upsert_jsonl_updates_existing_id(tmp_path) -> None:
    path = tmp_path / "knowledge_points.jsonl"
    points = build_knowledge_points(_performance_payload())

    first = upsert_jsonl(path, points)
    second = upsert_jsonl(path, points)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert first["inserted"] == len(points)
    assert second["updated"] == len(points)
    assert len(rows) == len(points)


def test_build_weekly_review_points() -> None:
    points = build_weekly_review_points(
        {
            "as_of": "2026-07-16",
            "risk_level": "needs_review",
            "next_week_actions": [
                {"type": "deweight", "target": "weak chase signals", "reason": "below 50% win rate"}
            ],
        }
    )

    assert len(points) == 1
    assert points[0]["topic"] == "Taiwan stock weekly review action: weak chase signals"
    assert "weekly_review" in points[0]["tags"]
