from scripts.weekly_review import build_weekly_review


def test_weekly_review_builds_internal_action_items() -> None:
    review = build_weekly_review(
        {
            "as_of": "2026-07-16",
            "stats": {"signals": 10, "completed": 8, "win_rate_5d": 43.0, "avg_return_5d": -1.2},
            "entry_analysis": {
                "triggered": {"count": 30, "avg_return_5d": -2.0},
                "not_triggered": {"count": 20, "avg_return_5d": 3.0},
            },
        },
        {
            "stats": {"signals": 20, "completed": 12, "win_rate_5d": 49.0, "avg_return_5d": 0.4},
            "stage_stats": [
                {"label": "轉強初動", "completed": 12, "win_rate_5d": 58.0, "avg_return_5d": 3.0},
                {"label": "強勢等拉回", "completed": 15, "win_rate_5d": 40.0, "avg_return_5d": -1.0},
            ],
            "factor_stats": [
                {"label": "題材升溫", "completed": 11, "win_rate_5d": 55.0, "avg_return_5d": 2.0}
            ],
        },
        {"themes": [{"theme": "AI伺服器", "week_score": 77, "trend": "升溫", "today": 20}]},
        {
            "risk_level": "needs_review",
            "summary": {"completed": 8},
            "adaptive_feedback": [{"target": "追價", "action": "降低追價權重"}],
        },
    )

    assert review["status"] == "ok"
    assert review["risk_level"] == "needs_review"
    assert review["best"]["potential_stage"]["label"] == "轉強初動"
    assert review["weak"]["potential_stage"]["label"] == "強勢等拉回"
    assert any(item["target"] == "每日選股總體" for item in review["next_week_actions"])
    assert any(item["target"] == "進場觸發條件" for item in review["next_week_actions"])


def test_weekly_review_flags_ineffective_guardrails() -> None:
    review = build_weekly_review(
        {
            "as_of": "2026-07-16",
            "stats": {"signals": 10, "completed": 8, "win_rate_5d": 55.0, "avg_return_5d": 1.2},
            "guardrail_stats": [
                {
                    "tag": "weekly_deweight_daily_chase",
                    "signals": 22,
                    "completed": 14,
                    "win_rate_5d": 35.7,
                    "avg_return_5d": -2.1,
                    "stop_hit_rate": 28.6,
                },
                {
                    "tag": "weekly_require_ai_agreement",
                    "signals": 18,
                    "completed": 12,
                    "win_rate_5d": 58.3,
                    "avg_return_5d": 1.4,
                    "stop_hit_rate": 8.3,
                },
            ],
        },
        {"stats": {"signals": 20, "completed": 12, "win_rate_5d": 55.0, "avg_return_5d": 0.4}},
        {},
        {},
        {
            "guardrail_effectiveness": [
                {"tag": "weekly_deweight_daily_chase", "status": "needs_review"},
            ]
        },
    )

    guardrails = {row["tag"]: row for row in review["guardrail_effectiveness"]}
    weak = guardrails["weekly_deweight_daily_chase"]
    strong = guardrails["weekly_require_ai_agreement"]
    assert weak["status"] == "needs_review"
    assert weak["consecutive_review"] is True
    assert "連續兩週" in weak["recommended_action"]
    assert strong["status"] == "working"
    assert any(item["type"] == "review_guardrail" for item in review["next_week_actions"])


def test_weekly_review_audits_selection_logic_when_no_green_and_low_win_rate() -> None:
    review = build_weekly_review(
        {
            "as_of": "2026-08-12",
            "stats": {"signals": 40, "completed": 18, "win_rate_5d": 44.4, "avg_return_5d": -0.8},
            "current_selection_backtest": {"candidate_count": 3, "referenceable_count": 0},
        },
        {"stats": {"signals": 30, "completed": 15, "win_rate_5d": 48.0, "avg_return_5d": -0.2}},
        {},
        {
            "weak": {
                "segments": [
                    {"group": "theme", "label": "AI伺服器", "completed": 15, "win_rate_5d": 33.3}
                ]
            }
        },
        dashboard={"traffic_lights": {"counts": {"green": 0, "yellow": 4, "red": 6}}},
    )

    audit = review["selection_logic_audit"]
    assert audit["status"] == "needs_review"
    codes = {item["code"] for item in audit["issues"]}
    assert "no_green_with_watchlist" in codes
    assert "daily_signal_win_rate_below_50" in codes
    assert "potential_radar_win_rate_below_50" in codes
    assert any(item["type"] == "logic_audit" for item in review["next_week_actions"])


def test_weekly_review_includes_github_failure_summary() -> None:
    review = build_weekly_review(
        {"as_of": "2026-08-12", "stats": {"win_rate_5d": 55, "completed": 20}},
        {"stats": {"win_rate_5d": 55, "completed": 20}},
        {},
        {},
        github_failures={
            "status": "ok",
            "summary": {"failed_run_count": 1, "categories": {"syntax_error": 1}},
            "recent_failures": [
                {
                    "run_id": 123,
                    "workflow": "Taiwan Stock AI Daily",
                    "display_title": "daily",
                    "root_cause": "syntax_error",
                    "annotation_count": 2,
                    "url": "https://github.com/example/runs/123",
                }
            ],
        },
    )

    assert review["automation_failures"]["failed_run_count"] == 1
    assert review["automation_failures"]["top_categories"][0]["category"] == "syntax_error"
    assert any(item["type"] == "automation_failure" for item in review["next_week_actions"])
