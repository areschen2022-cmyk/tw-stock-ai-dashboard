from src.backtest.current_selection import build_current_selection_backtest


def test_current_selection_backtest_builds_reference_profile():
    dashboard = {
        "as_of": "2026-07-03",
        "rows": [
            {
                "stock_id": "1609",
                "name": "大亞",
                "score": 99,
                "grade": "S+",
                "action": "可追蹤突破",
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
                "action": "可追蹤突破",
                "themes": ["電力能源/重電"],
                "return_5d": 3.0,
                "stop_hit": False,
            },
            {
                "signal_date": "2026-06-02",
                "stock_id": "B",
                "grade": "S+",
                "action": "可追蹤突破",
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
