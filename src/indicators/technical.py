from __future__ import annotations

import pandas as pd


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def technical_score(prices: pd.DataFrame) -> tuple[int, list[str]]:
    if prices.empty or len(prices) < 25:
        return 0, ["技術面資料不足"]
    df = prices.copy().sort_values("date")
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    ma5 = moving_average(close, 5).iloc[-1]
    ma20 = moving_average(close, 20).iloc[-1]
    vol_ma20 = moving_average(volume, 20).iloc[-1]
    rsi = rsi_wilder(close).iloc[-1]
    latest = close.iloc[-1]
    previous_high = close.iloc[-21:-1].max()
    score = 0
    reasons: list[str] = []
    if latest > ma20:
        score += 7
        reasons.append("收盤價站上 MA20")
    if ma5 > ma20:
        score += 7
        reasons.append("MA5 高於 MA20，短線趨勢偏多")
    if volume.iloc[-1] > vol_ma20 * 1.5:
        score += 6
        reasons.append("成交量明顯放大")
    if 50 <= rsi <= 70:
        score += 5
        reasons.append(f"RSI 位於健康區間（{rsi:.0f}）")
    if latest >= previous_high:
        score += 5
        reasons.append("突破近 20 日高點")
    return min(score, 30), reasons or ["技術面中性"]
