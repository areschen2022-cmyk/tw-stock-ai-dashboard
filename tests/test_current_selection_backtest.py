from src.backtest.current_selection import build_current_selection_backtest, apply_current_selection_context


def test_current_selection_backtest_builds_reference_profile():
    dashboard = {
        "as_of": "2026-07-03",
        "rows": [
            {
                "stock_id": "1609",
                "name": "大亞",
                "score": 99,
                "grade": "S+",
                "action": "開盤確認",
                "entry_decision": "開盤確認",
                "decision_light": "green",
                "themes": ["電力能源/重電"],
                "trigger_tags": ["題材強共振"],
            }
        ],
    }
    performance = {
        "items": [
            {
                "signal_date": "2026-06-01",
                "stock_id": "A",
                "grade": "S+",
                "action": "開盤確認",
                "themes": ["電力能源/重電"],
                "return_5d": 3.0,
                "stop_hit": False,
            },
            {
                "signal_date": "2026-06-02",
                "stock_id": "B",
                "grade": "S+",
                "action": "開盤確認",
                "themes": ["電力能源/重電"],
                "return_5d": -1.0,
                "stop_hit": True,
            },
        ]
    }

    payload = build_current_selection_backtest(dashboard, performance)

    assert payload["candidate_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["stock_id"] == "1609"
    assert candidate["historical_profile"]["completed"] == 2
    assert candidate["historical_profile"]["avg_return_5d"] == 1.0
    assert candidate["historical_profile"]["win_rate_5d"] == 50.0


def test_current_selection_context_moves_weak_chase_to_pullback():
    dashboard = {
        "rows": [
            {
                "stock_id": "1609",
                "name": "大亞",
                "score": 88,
                "grade": "S",
                "action": "開盤確認",
                "entry_decision": "開盤確認",
                "decision_light": "green",
                "themes": ["電力能源/重電"],
                "action_context_reason": "題材共振",
            }
        ],
        "action_lists": {
            "chase": [
                {
                    "stock_id": "1609",
                    "name": "大亞",
                    "score": 88,
                    "decision_light": "green",
                    "action_context_reason": "題材共振",
                }
            ],
            "pullback": [],
            "watch": [],
            "summary": {"chase": 1, "pullback": 0},
        },
    }
    backtest = {
        "candidates": [
            {
                "stock_id": "1609",
                "historical_profile": {
                    "completed": 12,
                    "win_rate_5d": 33.3,
                    "avg_return_5d": -1.2,
                    "confidence": "中",
                },
                "interpretation": "同條件歷史偏弱，避免開盤直接追價。",
            }
        ],
        "weak_references": [
            {
                "stock_id": "1609",
                "historical_profile": {
                    "completed": 12,
                    "win_rate_5d": 33.3,
                    "avg_return_5d": -1.2,
                    "confidence": "中",
                },
            }
        ],
        "strong_references": [],
    }

    apply_current_selection_context(dashboard, backtest)

    row = dashboard["rows"][0]
    assert row["decision_light"] == "yellow"
    assert row["decision_light_label"] == "黃燈等確認"
    assert row["historical_reference"]["label"] == "同條件偏弱"
    assert len(dashboard["action_lists"]["chase"]) == 0
    assert len(dashboard["action_lists"]["pullback"]) == 1
    assert dashboard["action_lists"]["summary"]["historical_weak"] == 1
