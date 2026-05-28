from __future__ import annotations

import pandas as pd

from src.indicators.candlestick import candlestick_patterns


def _prices(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": f"2026-05-{index + 1:02d}",
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row.get("volume", 1000),
            }
            for index, row in enumerate(rows)
        ]
    )


def test_candlestick_detects_volume_breakout() -> None:
    rows = [
        {"open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0, "volume": 1000}
        for _ in range(25)
    ]
    rows.append({"open": 10.0, "high": 13.1, "low": 9.9, "close": 13.0, "volume": 3000})

    tags, risk_tags = candlestick_patterns(_prices(rows))

    assert "放量長紅" in tags
    assert "突破整理" in tags
    assert risk_tags == []


def test_candlestick_detects_bullish_engulfing() -> None:
    rows = [
        {"open": 10.2, "high": 10.4, "low": 9.8, "close": 10.0, "volume": 1000}
        for _ in range(24)
    ]
    rows.append({"open": 10.4, "high": 10.5, "low": 9.5, "close": 9.7, "volume": 1000})
    rows.append({"open": 9.6, "high": 10.8, "low": 9.4, "close": 10.6, "volume": 1800})

    tags, _ = candlestick_patterns(_prices(rows))

    assert "陽包陰" in tags


def test_candlestick_detects_high_volume_stall_risk() -> None:
    rows = [
        {"open": 18.8, "high": 20.2, "low": 18.5, "close": 20.0, "volume": 1000}
        for _ in range(25)
    ]
    rows.append({"open": 19.7, "high": 22.0, "low": 19.5, "close": 19.8, "volume": 3000})

    _, risk_tags = candlestick_patterns(_prices(rows))

    assert "放量不漲" in risk_tags


def test_candlestick_ignores_short_or_incomplete_data() -> None:
    tags, risk_tags = candlestick_patterns(pd.DataFrame({"close": [1, 2, 3]}))

    assert tags == []
    assert risk_tags == []
