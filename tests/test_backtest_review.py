from scripts.backtest_review import build_review


def test_build_backtest_review_extracts_core_sections():
    review = build_review(
        {
            "as_of": "2026-06-26",
            "stats": {
                "signals": 10,
                "completed": 6,
                "win_rate_5d": 46.7,
                "avg_return_5d": 2.1,
                "stop_hit_rate": 10.0,
            },
            "data_quality": {"completion_rate_5d": 60.0},
            "score_bands": [
                {"label": "85-94", "signals": 4, "completed": 3, "avg_return_5d": 3.0},
                {"label": "95-100", "signals": 6, "completed": 3, "avg_return_5d": -1.0},
            ],
            "action_stats": [
                {"action": "可追蹤突破", "signals": 5, "completed": 3, "avg_return_5d": 1.5}
            ],
            "postmortem": {
                "failure_attribution": {
                    "rows": [
                        {
                            "label": "進場後轉弱",
                            "count": 20,
                            "avg_return_5d": -4.2,
                            "stop_hit_rate": 45.0,
                            "lesson": "開盤後沒有量價延續就降級。",
                        }
                    ]
                }
            },
            "items": [
                {"signal_date": "2026-06-03", "return_5d": 2.0},
                {"signal_date": "2026-06-04", "return_5d": -1.0},
                {"signal_date": "2026-07-01", "return_5d": 4.0},
            ],
            "calibration_advice": [{"priority": "檢討", "group": "分數區間", "label": "S+"}],
            "adaptive_feedback": [{"source": "失敗歸因", "target": "追高", "action": "降級觀察"}],
        }
    )

    assert review["as_of"] == "2026-06-26"
    assert review["status"] == "ok"
    assert review["risk_level"] == "sample_too_small"
    assert review["summary"]["signals"] == 10
    assert review["best"]["score_band"]["label"] == "85-94"
    assert review["weak"]["score_band"]["label"] == "95-100"
    assert review["review_actions"][0]["label"] == "S+"
    assert review["adaptive_feedback"][0]["target"] == "追高"
    assert review["why_win_rate_not_higher"]["root_causes"]
    assert review["win_rate_diagnosis"]["triggered"] is True
    assert review["win_rate_diagnosis"]["likely_causes"][0]["label"]
    assert review["monthly_returns"][-1]["month"] == "2026-07"
    assert review["monthly_returns"][0]["avg_return_5d"] == 0.5
