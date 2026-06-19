from __future__ import annotations

import json

from scripts.export_learning_to_knowledge_hub import build_knowledge_points, upsert_jsonl


def _performance_payload() -> dict:
    return {
        "as_of": "2026-06-18",
        "signal_attribution": {
            "factor_rows": [
                {
                    "label": "題材:AI伺服器",
                    "signals": 12,
                    "completed": 6,
                    "win_rate_5d": 66.7,
                    "avg_return_5d": 3.2,
                    "sample_label": "累積中",
                }
            ]
        },
        "postmortem": {
            "failure_attribution": {
                "rows": [
                    {
                        "label": "題材過熱",
                        "count": 3,
                        "avg_return_5d": -4.5,
                        "stop_hit_rate": 33.3,
                        "lesson": "題材過熱時降低追價權重。",
                    }
                ]
            }
        },
        "adaptive_feedback": [
            {
                "target": "題材:AI伺服器",
                "action": "保留但等待量價確認",
                "sample": 6,
                "avg_return_5d": 3.2,
                "reason": "樣本顯示題材有效但仍需控風險。",
            }
        ],
    }


def test_build_knowledge_points_from_performance_payload() -> None:
    points = build_knowledge_points(_performance_payload())

    assert len(points) == 3
    assert all(point["domain"] == "taiwan_stock" for point in points)
    assert any(point["topic"].startswith("台股因素成效") for point in points)
    assert any("失敗歸因" in point["topic"] for point in points)
    assert all(point["id"].startswith("kp_") for point in points)


def test_upsert_jsonl_updates_existing_id(tmp_path) -> None:
    path = tmp_path / "knowledge.jsonl"
    points = build_knowledge_points(_performance_payload())

    first = upsert_jsonl(path, points)
    second = upsert_jsonl(path, points)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert first["inserted"] == len(points)
    assert second["updated"] == len(points)
    assert len(rows) == len(points)
