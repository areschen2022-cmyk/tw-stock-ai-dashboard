from __future__ import annotations

import json

from scripts.export_learning_to_knowledge_hub import build_knowledge_points, upsert_jsonl


def _performance_payload() -> dict:
    return {
        "as_of": "2026-06-18",
        "signal_attribution": {
            "factor_rows": [
                {
                    "label": "題材升溫：AI伺服器",
                    "signals": 12,
                    "completed": 6,
                    "win_rate_5d": 66.7,
                    "avg_return_5d": 3.2,
                    "sample_label": "有效樣本",
                }
            ]
        },
        "postmortem": {
            "failure_attribution": {
                "rows": [
                    {
                        "label": "追高過熱",
                        "count": 3,
                        "avg_return_5d": -4.5,
                        "stop_hit_rate": 33.3,
                        "lesson": "過熱後續航不足，應等開盤量價確認。",
                    }
                ]
            }
        },
        "adaptive_feedback": [
            {
                "target": "題材升溫：AI伺服器",
                "action": "保留加權但提高開盤確認門檻",
                "sample": 6,
                "avg_return_5d": 3.2,
                "reason": "樣本仍少，但早期表現偏正向。",
            }
        ],
        "low_win_rate_breakdown": {
            "target_win_rate_5d": 50.0,
            "rows": [
                {
                    "group": "進場條件",
                    "label": "有觸發進場",
                    "completed": 25,
                    "signals": 30,
                    "win_rate_5d": 36.0,
                    "avg_return_5d": -2.4,
                    "drag_score": 4.1,
                    "sample_label": "觀察中",
                    "diagnosis": "進場確認後仍下跌。",
                    "recommended_action": "提高開盤確認門檻。",
                }
            ],
        },
    }


def test_build_knowledge_points_from_performance_payload() -> None:
    points = build_knowledge_points(_performance_payload())

    assert len(points) == 4
    assert all(point["domain"] == "taiwan_stock" for point in points)
    assert any(point["topic"].startswith("台股訊號因素：") for point in points)
    assert any("台股失敗歸因：" in point["topic"] for point in points)
    assert any("台股回測回饋：" in point["topic"] for point in points)
    assert any("台股低勝率拆解：" in point["topic"] for point in points)
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
