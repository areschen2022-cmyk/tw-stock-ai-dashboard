from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from main import (
    build_layered_stock_universe,
    bundle_coverage_report,
    default_as_of,
    delivery_date_for_run,
    select_theme_pools,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def test_default_as_of_uses_previous_friday_on_monday_morning() -> None:
    assert default_as_of(datetime(2026, 5, 18, 8, 8, tzinfo=TAIPEI)).isoformat() == "2026-05-15"


def test_default_as_of_uses_today_after_close() -> None:
    assert default_as_of(datetime(2026, 5, 18, 15, 0, tzinfo=TAIPEI)).isoformat() == "2026-05-18"


def test_default_as_of_uses_friday_on_weekend() -> None:
    assert default_as_of(datetime(2026, 5, 17, 9, 0, tzinfo=TAIPEI)).isoformat() == "2026-05-15"


def test_delivery_date_uses_scheduled_target(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULED_TARGET_TAIPEI", "2026-05-25T07:20:00+08:00")

    assert delivery_date_for_run(datetime(2026, 5, 25, 9, 0, tzinfo=TAIPEI)).isoformat() == "2026-05-25"


def test_delivery_date_falls_back_to_current_taipei_date(monkeypatch) -> None:
    monkeypatch.delenv("SCHEDULED_TARGET_TAIPEI", raising=False)

    assert delivery_date_for_run(datetime(2026, 5, 25, 9, 0, tzinfo=TAIPEI)).isoformat() == "2026-05-25"


def test_empty_active_themes_do_not_select_all_theme_pools() -> None:
    pools = {
        "memory": {"stocks": {"2408": "南亞科"}},
        "ai_server": {"stocks": {"2382": "廣達"}},
    }

    assert select_theme_pools(pools, set()) == {}
    assert select_theme_pools(pools, {"memory"}) == {"memory": pools["memory"]}


def test_bundle_coverage_report_measures_actual_rows() -> None:
    report = bundle_coverage_report(
        {
            "2330": {
                "prices": list(range(20)),
                "institutional": [1],
                "margin": [1],
                "revenue": list(range(15)),
            },
            "6510": {
                "prices": list(range(19)),
                "institutional": [],
                "margin": [1],
                "revenue": [1],
            },
        }
    )

    assert report["all_critical_complete"] is False
    assert report["datasets"]["prices"]["coverage_pct"] == 50.0
    assert report["datasets"]["institutional"]["missing"] == ["6510"]
    assert report["datasets"]["revenue"]["coverage_pct"] == 100.0
    assert report["datasets"]["revenue_15m"]["missing"] == ["6510"]


class _ThemeSignal:
    active_themes = ["memory"]


class _MarketProvider:
    def market_universe(self, as_of):
        return [
            {"stock_id": "3008", "name": "大立光", "market": "listed", "trade_value": 900},
            {"stock_id": "2408", "name": "南亞科", "market": "listed", "trade_value": 800},
            {"stock_id": "6510", "name": "精測", "market": "otc", "trade_value": 700},
        ]


def test_layered_universe_adds_active_themes_and_market_candidates() -> None:
    config = {
        "stocks": ["2330"],
        "stock_names": {"2330": "台積電"},
        "theme_pools": {
            "memory": {"stocks": {"2408": "南亞科"}},
            "ai_server": {"stocks": {"2382": "廣達"}},
        },
        "universe": {
            "enabled": True,
            "target_total_listed": 1056,
            "daily_market_limit": 2,
            "daily_theme_rotation_limit": 0,
            "max_daily_total": 10,
            "weekly_full_scan_weekday": 0,
        },
    }

    stock_ids, report = build_layered_stock_universe(
        config,
        _ThemeSignal(),
        {"memory": config["theme_pools"]["memory"]},
        _MarketProvider(),
        date(2026, 6, 2),  # Tuesday: normal daily scan
    )

    assert stock_ids == ["2330", "2408", "3008", "6510"]
    assert config["stock_names"]["3008"] == "大立光"
    assert report["mode"] == "daily_layered"
    assert report["core_count"] == 1
    assert report["active_theme_count"] == 1
    assert report["market_liquidity_count"] == 2
    assert report["market_universe_available"] == 3
    assert report["selected_count"] == 4


def test_weekly_layered_universe_can_include_theme_rotation() -> None:
    config = {
        "stocks": ["2330"],
        "theme_pools": {
            "memory": {"stocks": {"2408": "南亞科"}},
            "ai_server": {"stocks": {"2382": "廣達"}},
        },
        "universe": {
            "enabled": True,
            "target_total_listed": 1056,
            "weekly_market_limit": 0,
            "weekly_theme_rotation_limit": 2,
            "weekly_full_scan_weekday": 0,
        },
    }

    stock_ids, report = build_layered_stock_universe(
        config,
        _ThemeSignal(),
        {},
        _MarketProvider(),
        date(2026, 6, 1),  # Monday: weekly broader scan
    )

    assert stock_ids == ["2330", "2408", "2382"]
    assert report["mode"] == "weekly_full_scan"
    assert report["theme_rotation_count"] == 2
