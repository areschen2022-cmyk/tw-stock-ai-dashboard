from src.scoring.backtest_guard import apply_backtest_guard, load_backtest_guard
from src.scoring.score_engine import StockScore


def _score(action: str = "可追蹤突破", total: int = 98) -> StockScore:
    return StockScore(
        stock_id="2408",
        total_score=total,
        label="BUY_WATCH",
        price=100.0,
        technical_score=25,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=3,
        action=action,
        entry_decision="開盤確認",
        themes=["memory"],
        theme_tiers=["記憶體/HBM:核心"],
        reasons={"opportunity": ["記憶體/HBM 題材升溫"]},
        trigger_tags=["題材強共振", "技術突破"],
    )


def test_backtest_guard_downgrades_chase_when_recent_grade_is_weak() -> None:
    score = _score(total=98)
    context = {
        "active": True,
        "segments": [
            {
                "group": "grade",
                "label": "S+",
                "completed": 34,
                "win_rate_5d": 35.2,
                "avg_return_5d": -4.1,
            }
        ],
    }

    apply_backtest_guard(score, context)

    assert score.action == "等拉回"
    assert score.entry_decision == "等拉回"
    assert "回測保護" in score.trigger_tags
    assert "backtest_guard" in score.reasons


def test_backtest_guard_matches_weak_theme() -> None:
    score = _score(total=86)
    context = {
        "active": True,
        "segments": [
            {
                "group": "theme",
                "label": "記憶體/HBM",
                "completed": 24,
                "win_rate_5d": 20.8,
                "avg_return_5d": -5.3,
            }
        ],
    }

    apply_backtest_guard(score, context)

    assert score.action == "等拉回"


def test_backtest_guard_ignores_small_sample() -> None:
    score = _score(total=98)
    context = {
        "active": True,
        "segments": [
            {
                "group": "theme",
                "label": "記憶體/HBM",
                "completed": 3,
                "win_rate_5d": 0,
                "avg_return_5d": -10,
            }
        ],
    }

    apply_backtest_guard(score, context)

    assert score.action == "可追蹤突破"


def test_load_backtest_guard_filters_to_qualified_weak_segments(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "backtest_review.json").write_text(
        """
        {
          "as_of": "2026-06-26",
          "risk_level": "needs_review",
          "weak": {
            "segments": [
              {"group":"grade","label":"S+","completed":34,"win_rate_5d":35,"avg_return_5d":-4},
              {"group":"theme","label":"小樣本","completed":2,"win_rate_5d":0,"avg_return_5d":-9}
            ]
          }
        }
        """,
        encoding="utf-8",
    )

    context = load_backtest_guard(tmp_path)

    assert context["active"] is True
    assert len(context["segments"]) == 1
    assert context["segments"][0]["label"] == "S+"


def test_backtest_guard_loads_low_win_rate_breakdown_from_performance(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "performance_data.json").write_text(
        """
        {
          "as_of": "2026-07-16",
          "low_win_rate_breakdown": {
            "rows": [
              {
                "group": "題材",
                "label": "記憶體/HBM",
                "completed": 22,
                "win_rate_5d": 9.1,
                "avg_return_5d": -6.3,
                "diagnosis": "題材聲量沒有同步轉成買盤"
              },
              {
                "group": "進場條件",
                "label": "有觸發進場",
                "completed": 280,
                "win_rate_5d": 36.1,
                "avg_return_5d": -2.3
              }
            ]
          }
        }
        """,
        encoding="utf-8",
    )

    context = load_backtest_guard(tmp_path)

    assert context["active"] is True
    groups = {item["group"] for item in context["segments"]}
    assert "theme" in groups
    assert "entry_condition" in groups


def test_backtest_guard_downgrades_when_entry_condition_recently_failed() -> None:
    score = _score(action="可追蹤突破", total=98)
    context = {
        "active": True,
        "segments": [
            {
                "group": "進場條件",
                "label": "有觸發進場",
                "completed": 280,
                "win_rate_5d": 36.1,
                "avg_return_5d": -2.3,
            }
        ],
    }

    apply_backtest_guard(score, context)

    assert score.action == "等拉回"
    assert score.entry_decision == "等拉回"
    assert any("進場條件" in item for item in score.warnings)


def test_backtest_guard_loads_weekly_review_and_deweights_borderline_chase(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "weekly_review.json").write_text(
        """
        {
          "as_of": "2026-07-16",
          "summary": {"daily_completed": 42, "daily_win_rate_5d": 43.7},
          "next_week_actions": [
            {"type": "deweight", "target": "每日可追訊號", "reason": "5日勝率低於 50%"},
            {"type": "investigate", "target": "進場觸發條件", "reason": "進場條件需重驗"}
          ]
        }
        """,
        encoding="utf-8",
    )
    context = load_backtest_guard(tmp_path)
    score = _score(action="可追蹤突破", total=82)

    apply_backtest_guard(score, context)

    assert context["active"] is True
    assert score.action == "等拉回"
    assert "週檢討降權" in score.trigger_tags
    assert any("週檢討" in item for item in score.warnings)


def test_backtest_guard_weekly_review_keeps_strong_s_chase_but_warns(tmp_path) -> None:
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "weekly_review.json").write_text(
        """
        {
          "summary": {"daily_completed": 42, "daily_win_rate_5d": 43.7},
          "next_week_actions": [
            {"type": "deweight", "target": "每日可追訊號", "reason": "5日勝率低於 50%"}
          ]
        }
        """,
        encoding="utf-8",
    )
    context = load_backtest_guard(tmp_path)
    score = _score(action="可追蹤突破", total=90)

    apply_backtest_guard(score, context)

    assert score.action == "可追蹤突破"
    assert any("S級以上" in item for item in score.warnings)
