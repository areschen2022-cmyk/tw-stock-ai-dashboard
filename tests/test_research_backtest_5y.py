from __future__ import annotations

import pandas as pd

from scripts.research_backtest_5y import (
    _return_stats,
    build_price_volume_signals,
    build_universe,
)


def test_build_universe_deduplicates_core_and_theme_ids() -> None:
    config = {
        "stocks": ["2330", "2408"],
        "theme_pools": {
            "memory": {"stocks": {"2408": "南亞科", "2344": "華邦電"}},
            "ai": {"stocks": {"2330": "台積電", "3231": "緯創"}},
        },
    }

    assert build_universe(config, "core-theme", None) == ["2330", "2408", "2344", "3231"]
    assert build_universe(config, "theme", 2) == ["2408", "2344"]


def test_price_volume_signals_enter_next_open_and_subtract_costs() -> None:
    dates = pd.date_range("2025-01-01", periods=95, freq="B")
    close = [100.0 + i * 0.1 for i in range(95)]
    volume = [1000.0 for _ in range(95)]
    close[80] = 120.0
    volume[80] = 3000.0
    open_prices = [value + 0.5 for value in close]
    close[86] = 126.0
    close[91] = 130.0
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": open_prices,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": volume,
        }
    )

    rows = build_price_volume_signals("TEST", "測試", prices, cost_bps=60)

    row = next(item for item in rows if item["signal_date"] == dates[80].date().isoformat())
    assert row["entry_date"] == dates[81].date().isoformat()
    assert "breakout_volume" in row["signal_types"]
    assert row["net_return_5d"] < row["gross_return_5d"]


def test_return_stats_reports_completed_and_win_rate() -> None:
    stats = _return_stats(
        [
            {"net_return_5d": 2.0},
            {"net_return_5d": -1.0},
            {"net_return_5d": None},
        ]
    )

    assert stats["signals"] == 3
    assert stats["completed"] == 2
    assert stats["win_rate"] == 50.0
    assert stats["avg_return"] == 0.5
