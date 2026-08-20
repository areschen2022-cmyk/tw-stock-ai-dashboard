from src.backtest.current_selection import build_current_selection_backtest, apply_current_selection_context
from src.scoring.versioning import DECISION_VERSION, SCORE_VERSION


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
                "return_10d": 12.0,
                "mfe_10d": 15.0,
                "mae_10d": -2.0,
                "score_version": SCORE_VERSION,
                "decision_version": DECISION_VERSION,
                "stop_hit": False,
            },
            {
                "signal_date": "2026-06-02",
                "stock_id": "B",
                "grade": "S+",
                "action": "開盤確認",
                "themes": ["電力能源/重電"],
                "return_5d": -1.0,
                "return_10d": -3.0,
                "mfe_10d": 2.0,
                "mae_10d": -5.0,
                "score_version": SCORE_VERSION,
                "decision_version": DECISION_VERSION,
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
    assert payload["rocket_metrics"]["scope"] == "tracked_signals_proxy"
    assert payload["rocket_metrics"]["score_version"] == SCORE_VERSION
    assert payload["rocket_metrics"]["precision_10d_10pct"] == 50.0
    assert payload["rocket_metrics"]["precision_10d_15pct"] == 50.0
    assert payload["rocket_metrics"]["mfe_10d_avg"] == 8.5


def test_current_selection_does_not_mix_v1_or_unversioned_history():
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
            }
        ],
    }
    performance = {
        "items": [
            {
                "signal_date": "2026-06-01",
                "stock_id": "OLD",
                "grade": "S+",
                "action": "開盤確認",
                "themes": ["電力能源/重電"],
                "return_5d": 20.0,
                "score_version": "v1",
                "decision_version": "v1",
            },
            {
                "signal_date": "2026-06-02",
                "stock_id": "UNVERSIONED",
                "grade": "S+",
                "action": "開盤確認",
                "themes": ["電力能源/重電"],
                "return_5d": 10.0,
            },
        ]
    }

    payload = build_current_selection_backtest(dashboard, performance)

    assert payload["history_completed_5d_all_versions"] == 2
    assert payload["history_completed_5d"] == 0
    profile = payload["candidates"][0]["historical_profile"]
    assert profile["completed"] == 0
    assert profile["match_type"] == "insufficient_v2_history"


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
