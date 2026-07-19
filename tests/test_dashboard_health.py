from __future__ import annotations

from datetime import date

from src.indicators.overseas import OverseasSentiment
from src.news.policy_signal import PolicySignal
from src.news.catalyst_confidence import CatalystConfidence
from src.news.web_theme import ThemeSignal
from src.report.dashboard import (
    build_dashboard_payload,
    build_traceability_diagnosis,
    build_traceability_summary,
    build_weekly_overview_payload,
    write_potential,
)
from src.scoring.score_engine import StockScore


def test_dashboard_payload_includes_health_and_decision_reason() -> None:
    score = StockScore(
        stock_id="2330",
        total_score=88,
        label="BUY_WATCH",
        price=100.0,
        technical_score=20,
        chip_score=20,
        fundamental_score=15,
        risk_score=15,
        market_adjustment=0,
        reasons={
            "technical": ["突破 20 日高點"],
            "chip": ["外資連 3 日買超"],
        },
        trigger_tags=["題材強共振", "外資買超", "技術突破"],
    )
    payload = build_dashboard_payload(
        [score],
        date(2026, 5, 18),
        "健康",
        None,
        {"stock_names": {"2330": "台積電"}, "theme_pools": {}},
        overseas=None,
        theme_signal=ThemeSignal(
            ["defense_policy"],
            "未偵測到明顯題材",
            [],
            {"defense_policy": 3},
            matched_headlines={"defense_policy": ["國防預算帶動軍工題材"]},
            quality={"defense_policy": "高：新聞含股票代號或公司名"},
            catalyst_confidence={
                "defense_policy": CatalystConfidence("A", "已確認", "政策事件佐證", 1)
            },
            discovered_themes=[
                {
                    "keyword": "石英元件",
                    "score": 11,
                    "mentions": 3,
                    "stock_hits": ["2330 台積電"],
                    "headlines": ["石英元件供應鏈升溫"],
                }
            ],
            source_count=2,
            failed_count=0,
            policy=PolicySignal(
                "US policy",
                {"defense_policy": 15},
                {},
                [{"event": "Defense bill / NDAA", "sensitivity": "high", "confidence": "confirmed"}],
            ),
        ),
        source_status={
            "label": "正常",
            "api": 1,
            "cache": 0,
            "quota": 0,
            "error": 0,
            "official_snapshots": {
                "institutional": {"date": "2026-05-18", "valid": True, "rows": 1000}
            },
            "events": [{"type": "empty", "dataset": "STOCK_DAY", "data_id": "2330", "period": "2026-05"}],
        },
    )

    assert payload["health"]["label"] == "正常"
    assert payload["generated_at"] == payload["health"]["generated_at"]
    assert payload["generated_date"] == payload["health"]["generated_date"]
    assert payload["health"]["website_schedule"] == "04:30 / 05:00"
    assert payload["health"]["telegram_schedule"] == "07:20 / 07:35 / 07:50 / 08:05"
    assert payload["health"]["news_sources"] == 2
    assert "突破 20 日高點" in payload["rows"][0]["decision_reason"]
    assert payload["action_lists"]["summary"]["chase"] == 0
    assert payload["data_quality"]["label"] in {"high", "medium", "low"}
    assert payload["data_quality"]["label_text"] in {"高", "中", "偏低"}
    assert payload["data_quality"]["details"][0]["dataset"] == "STOCK_DAY"
    assert payload["data_quality"]["recovery_status"]["retryable"] == 1
    assert payload["data_quality"]["official_valid"] == 1
    assert payload["data_source_health"]["label"] == "可用"
    assert payload["data_source_health"]["official_valid"] == 1
    assert payload["market_tide"]["label"]
    assert payload["decision_summary"]["market_tide_label"] == payload["market_tide"]["label"]
    assert payload["decision_summary"]["top_theme"] == "defense_policy"
    assert payload["themes"]["matched_headlines"]["defense_policy"] == ["國防預算帶動軍工題材"]
    assert payload["themes"]["quality"]["defense_policy"].startswith("高")
    assert payload["themes"]["catalyst_confidence"]["defense_policy"]["grade"] == "A"
    assert payload["themes"]["policy"]["us_events"][0]["event"] == "Defense bill / NDAA"
    assert payload["themes"]["discovery"][0]["keyword"] == "石英元件"


def test_market_tide_guardrail_downgrades_chase_light_in_headwind() -> None:
    score = StockScore(
        stock_id="2408",
        total_score=92,
        label="BUY_WATCH",
        price=100.0,
        technical_score=25,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=0,
        reasons={"technical": ["突破整理"], "chip": ["法人共振"]},
        action="可追蹤突破",
        entry_decision="開盤確認",
        trigger_tags=["題材強共振", "法人共振", "技術突破"],
    )
    payload = build_dashboard_payload(
        [score],
        date(2026, 7, 17),
        "偏弱，指數跌破主要均線",
        "大盤轉弱",
        {"stock_names": {"2408": "南亞科"}, "theme_pools": {}},
        overseas=OverseasSentiment("偏空", -4, -5, "SOX -3.0%", ["SOX -3.0%"]),
        theme_signal=ThemeSignal([], "未偵測到明顯題材", [], {}, source_count=1, failed_count=0),
        source_status={"label": "正常", "api": 1, "cache": 0, "quota": 0, "error": 0},
        ai_picks=[
            {
                "stock_id": "2408",
                "consensus_action": "可追",
                "pick_agreement_count": 5,
                "model_count": 5,
                "reason": "strong setup",
            }
        ],
    )

    row = payload["rows"][0]
    assert payload["market_tide"]["risk_level"] == "headwind"
    assert row["decision_light"] == "yellow"
    assert row["decision_light_label"] == "黃燈等確認"
    assert row["tide_context"] == payload["market_tide"]["label"]


def test_weekly_overview_marks_recent_tdcc_failure_as_recovered() -> None:
    payload = build_weekly_overview_payload(
        date(2026, 7, 17),
        {
            "market": {},
            "overseas": {},
            "retail_divergence": {},
            "themes": {"names": {}, "scores": {}, "momentum": {}},
        },
        {"stats": {}, "selection_quality": {}},
        {},
        {},
        data_updates=[
            {
                "update_date": "2026-07-16",
                "dataset": "tdcc_retail_holders",
                "status": "failed",
                "row_count": 0,
                "source_date": "",
                "message": "Read timed out",
            },
            {
                "update_date": "2026-07-15",
                "dataset": "tdcc_retail_holders",
                "status": "ok",
                "row_count": 4003,
                "source_date": "2026-07-09",
                "message": "44 divergence signals",
            },
            {
                "update_date": "2026-07-17",
                "dataset": "institutional_flow",
                "status": "ok",
                "row_count": 79,
                "source_date": "2026-07-17",
                "message": "weekly flow",
            },
        ],
    )

    tdcc = payload["data_freshness"]["tdcc_retail_holders"]
    assert tdcc["status"] == "recovered"
    assert tdcc["status_label"] == "沿用前次成功"
    assert tdcc["latest_success_source_date"] == "2026-07-09"
    assert tdcc["latest_failure_message"] == "Read timed out"
    assert payload["data_freshness"]["institutional_flow"]["status"] == "ok"


def test_build_traceability_summary_links_scoring_and_backtests() -> None:
    dashboard_payload = {
        "summary": {"scanned": 5, "valid": 4, "s_plus_grade": 1, "s_grade": 1, "a_grade": 2},
        "source_status": {"label": "正常", "api": 10, "cache": 2, "quota": 0, "error": 0},
        "data_quality": {"label": "high"},
        "data_retry": {"pending": 0, "recovered": 3, "failed": 0, "status_counts": {}},
        "ai_council": {
            "min_agree_count": 4,
            "status": {"requested_models": 5, "successful_models": 4, "health": {"label": "穩定", "score": 90}},
        },
    }
    performance_payload = {
        "stats": {"signals": 12, "completed": 8, "win_rate_5d": 62.5},
        "potential_radar": {"stats": {"signals": 7, "completed": 3, "win_rate_5d": 66.7}},
    }

    trace = build_traceability_summary(dashboard_payload, performance_payload)

    assert len(trace["steps"]) == 7
    assert trace["summary"]["valid"] == 4
    assert trace["summary"]["watch_signals"] == 12
    assert trace["summary"]["potential_signals"] == 7
    assert {step["key"] for step in trace["steps"]} == {
        "source",
        "score",
        "watch",
        "potential",
        "ai",
        "retry",
        "pages",
    }


def test_build_traceability_diagnosis_is_internal_for_non_ok_steps() -> None:
    dashboard_payload = {
        "summary": {"scanned": 5, "valid": 4},
        "source_status": {"label": "正常", "api": 10, "cache": 2, "quota": 0, "error": 0},
        "data_quality": {"label": "high"},
        "data_retry": {"pending": 1, "recovered": 3, "failed": 0, "status_counts": {}},
        "ai_council": {
            "status": {
                "requested_models": 5,
                "successful_models": 3,
                "failed_models": 1,
                "timed_out_models": 1,
                "health": {"label": "不穩定", "score": 50},
            }
        },
    }
    traceability = {
        "steps": [
            {"key": "source", "label": "資料源", "status": "ok", "note": "ok"},
            {"key": "ai", "label": "AI 複核", "status": "warn", "note": "3/5"},
            {"key": "retry", "label": "補抓佇列", "status": "warn", "note": "pending"},
        ]
    }

    diagnosis = build_traceability_diagnosis(traceability, dashboard_payload)

    assert [item["key"] for item in diagnosis] == ["ai", "retry"]
    assert "successful=3" in diagnosis[0]["evidence"]
    assert "pending=1" in diagnosis[1]["evidence"]


def test_dashboard_health_includes_schedule_delay(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULED_TARGET_TAIPEI", "2026-05-18T04:30:00+08:00")
    monkeypatch.setenv("SCHEDULED_BY", "cloudflare-worker")
    monkeypatch.setenv("SCHEDULED_TASK", "dashboard")
    monkeypatch.setenv("SCHEDULED_CRON", "30 20 * * 0-4")

    payload = build_dashboard_payload(
        [],
        date(2026, 5, 18),
        "健康",
        None,
        {"stock_names": {}, "theme_pools": {}},
        overseas=None,
        theme_signal=ThemeSignal([], "未偵測到明顯題材", [], {}, source_count=1, failed_count=0),
        source_status={"label": "正常", "api": 1, "cache": 0, "quota": 0, "error": 0},
    )

    assert payload["health"]["scheduler"] == "cloudflare-worker"
    assert payload["health"]["scheduled_task"] == "dashboard"
    assert payload["health"]["scheduled_cron"] == "30 20 * * 0-4"
    assert payload["health"]["scheduled_target_taipei"] == "2026-05-18T04:30:00+08:00"
    assert isinstance(payload["health"]["schedule_delay_minutes"], float)


def test_data_quality_does_not_penalize_recovered_fallback() -> None:
    score = StockScore(
        stock_id="2330",
        total_score=80,
        label="BUY_WATCH",
        price=100.0,
        technical_score=20,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=0,
    )
    payload = build_dashboard_payload(
        [score],
        date(2026, 5, 18),
        "健康",
        None,
        {"stock_names": {"2330": "台積電"}, "theme_pools": {}},
        overseas=None,
        theme_signal=ThemeSignal([], "未偵測到明顯題材", [], {}, source_count=1, failed_count=0),
        source_status={
            "label": "正常",
            "api": 0,
            "cache": 0,
            "fallback": 1,
            "quota": 0,
            "error": 0,
            "empty": 1,
            "events": [{"type": "fallback", "dataset": "STOCK_DAY", "data_id": "2330", "period": "2026-05"}],
        },
    )

    quality = payload["data_quality"]
    assert quality["label"] == "high"
    assert quality["recovered_fetches"] == 1
    assert quality["effective_empty"] == 0
    assert quality["recovery_status"]["retryable"] == 0
    assert quality["recovery_status"]["recovered"] == 1


def test_data_quality_hides_empty_events_recovered_by_stock_fallback() -> None:
    score = StockScore(
        stock_id="2330",
        total_score=80,
        label="BUY_WATCH",
        price=100.0,
        technical_score=20,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=0,
    )
    payload = build_dashboard_payload(
        [score],
        date(2026, 5, 18),
        "健康",
        None,
        {"stock_names": {"2330": "台積電"}, "theme_pools": {}},
        overseas=None,
        theme_signal=ThemeSignal([], "未偵測到明顯題材", [], {}, source_count=1, failed_count=0),
        source_status={
            "label": "正常",
            "api": 0,
            "cache": 0,
            "fallback": 1,
            "quota": 0,
            "error": 0,
            "empty": 1,
            "events": [
                {"type": "empty", "dataset": "STOCK_DAY", "data_id": "2330", "period": "2026-05"},
                {"type": "fallback", "dataset": "stock_prices", "data_id": "2330", "reason": "twse_month_missing"},
            ],
        },
    )

    quality = payload["data_quality"]
    assert quality["label"] == "high"
    assert quality["effective_empty"] == 0
    assert quality["recovery_status"]["retryable"] == 0
    assert quality["recovery_status"]["recovered"] == 2


def test_weekly_overview_payload_summarizes_existing_sections() -> None:
    dashboard_payload = {
        "market": {"summary": "market ok"},
        "overseas": {"label": "neutral", "summary": "overseas ok"},
        "retail_divergence": {"summary": {"clean": 1, "overheated": 2}},
        "themes": {
            "names": {"memory": "memory"},
            "scores": {"memory": 5},
            "momentum": {"memory": {"avg_3d": 2.5, "trend": "up"}},
        },
    }
    performance_payload = {
        "stats": {"signals": 3, "completed": 1, "win_rate_5d": 100},
        "top_themes": [],
        "score_bands": [],
        "selection_quality": {"sample_label": "small sample"},
    }
    payload = build_weekly_overview_payload(
        date(2026, 5, 29),
        dashboard_payload,
        performance_payload,
        {"memory": [{"date": "2026-05-29", "score": 5}, {"date": "2026-05-28", "score": 3}]},
        {"top_buy": [], "top_sell": []},
    )

    assert payload["as_of"] == "2026-05-29"
    assert payload["themes"][0]["name"] == "memory"
    assert payload["themes"][0]["week_score"] == 8
    assert payload["retail_divergence"]["summary"]["clean"] == 1


def test_write_potential_creates_dedicated_page(tmp_path) -> None:
    payload = {
        "as_of": "2026-05-29",
        "days": 30,
        "potential_radar": {
            "stats": {"signals": 1, "completed": 0, "pending": 1},
            "stage_stats": [
                {
                    "label": "低位醞釀",
                    "signals": 1,
                    "completed": 0,
                    "pending": 1,
                    "win_rate_5d": None,
                    "avg_return_5d": None,
                }
            ],
            "pending_candidates": [],
            "factor_stats": [],
        },
        "learning_center": {"potential_candidates": []},
    }

    write_potential(payload, tmp_path)

    html = (tmp_path / "potential.html").read_text(encoding="utf-8")
    data = (tmp_path / "potential_data.json").read_text(encoding="utf-8")
    assert "台股 AI 潛力雷達" in html
    assert "potential_data.json" in html
    assert "低位醞釀" in data
