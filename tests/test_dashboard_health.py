from __future__ import annotations

from datetime import date

from src.news.policy_signal import PolicySignal
from src.news.catalyst_confidence import CatalystConfidence
from src.news.web_theme import ThemeSignal
from src.report.dashboard import build_dashboard_payload
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
            "events": [{"type": "empty", "dataset": "STOCK_DAY", "data_id": "2330", "period": "2026-05"}],
        },
    )

    assert payload["health"]["label"] == "正常"
    assert payload["health"]["website_schedule"] == "04:30 / 05:00"
    assert payload["health"]["telegram_schedule"] == "07:20 / 07:35 / 07:50 / 08:05"
    assert payload["health"]["news_sources"] == 2
    assert "突破 20 日高點" in payload["rows"][0]["decision_reason"]
    assert payload["action_lists"]["summary"]["chase"] == 0
    assert payload["data_quality"]["label"] in {"high", "medium", "low"}
    assert payload["data_quality"]["label_text"] in {"高", "中", "偏低"}
    assert payload["data_quality"]["details"][0]["dataset"] == "STOCK_DAY"
    assert payload["data_quality"]["recovery_status"]["retryable"] == 1
    assert payload["decision_summary"]["top_theme"] == "defense_policy"
    assert payload["themes"]["matched_headlines"]["defense_policy"] == ["國防預算帶動軍工題材"]
    assert payload["themes"]["quality"]["defense_policy"].startswith("高")
    assert payload["themes"]["catalyst_confidence"]["defense_policy"]["grade"] == "A"
    assert payload["themes"]["policy"]["us_events"][0]["event"] == "Defense bill / NDAA"


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
