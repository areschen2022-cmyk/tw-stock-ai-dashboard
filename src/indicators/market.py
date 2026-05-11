from __future__ import annotations

import pandas as pd


def market_adjustment(prices: pd.DataFrame, ma_short: int = 20, ma_long: int = 60) -> tuple[int, str, str | None]:
    if prices.empty or len(prices) < ma_long:
        return 0, "大盤資料不足", "大盤調整略過：指數資料不足"
    close = prices.sort_values("date")["close"].astype(float)
    latest = close.iloc[-1]
    short = close.rolling(ma_short).mean().iloc[-1]
    long = close.rolling(ma_long).mean().iloc[-1]
    if latest < short and short < long:
        return -10, "偏空：指數跌破 MA20，且 MA20 低於 MA60", None
    if latest < long:
        return -5, "偏弱：指數位於 MA60 下方", None
    return 0, "健康：指數維持在主要均線上方", None
