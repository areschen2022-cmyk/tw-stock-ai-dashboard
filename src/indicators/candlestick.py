from __future__ import annotations

import pandas as pd

from src.indicators.technical import moving_average


def candlestick_patterns(prices: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Return concise candlestick helper tags and risk tags.

    These tags are for display and later backtesting only. They should not create a
    buy signal by themselves because candlestick patterns need position and volume
    confirmation.
    """
    required = {"open", "high", "low", "close", "volume"}
    if prices.empty or len(prices) < 25 or not required.issubset(set(prices.columns)):
        return [], []

    df = prices.copy().sort_values("date").tail(30)
    open_ = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    o0, h0, l0, c0, v0 = (open_.iloc[-1], high.iloc[-1], low.iloc[-1], close.iloc[-1], volume.iloc[-1])
    o1, c1 = open_.iloc[-2], close.iloc[-2]
    range0 = max(h0 - l0, 0.01)
    body0 = abs(c0 - o0)
    upper_shadow = h0 - max(c0, o0)
    lower_shadow = min(c0, o0) - l0
    vol_ma20 = moving_average(volume, 20).iloc[-1]
    previous_high20 = close.iloc[-21:-1].max()
    previous_low20 = close.iloc[-21:-1].min()
    high_position = c0 >= previous_high20 * 0.92
    low_position = c0 <= previous_low20 * 1.12
    volume_expanded = vol_ma20 > 0 and v0 >= vol_ma20 * 1.5
    volume_confirmed = vol_ma20 > 0 and v0 >= vol_ma20 * 1.2

    tags: list[str] = []
    risk_tags: list[str] = []

    if c0 > o0 and body0 / range0 >= 0.65 and volume_expanded:
        tags.append("放量長紅")

    if c1 < o1 and c0 > o0 and o0 <= c1 and c0 >= o1 and volume_confirmed:
        tags.append("陽包陰")

    if low_position and lower_shadow >= max(body0 * 2, range0 * 0.35) and upper_shadow <= max(body0 * 1.2, range0 * 0.25):
        tags.append("低位錘子線")

    if c0 >= previous_high20 and volume_confirmed:
        tags.append("突破整理")

    price_change = (c0 - c1) / c1 * 100 if c1 else 0
    if volume_expanded and price_change <= 1.0 and high_position:
        risk_tags.append("放量不漲")

    if high_position and c1 > o1 and c0 < o0 and o0 >= c1 and c0 <= o1:
        risk_tags.append("高位陰包陽")

    if high_position and upper_shadow >= max(body0 * 2, range0 * 0.35) and c0 <= o0:
        risk_tags.append("高位上影線")

    return _dedupe(tags), _dedupe(risk_tags)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
