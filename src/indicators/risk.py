from __future__ import annotations

from datetime import date

import pandas as pd


def risk_score(prices: pd.DataFrame, dividend: pd.DataFrame, as_of: date, dividend_warning_days: int = 5) -> tuple[int, list[str]]:
    score = 20
    reasons: list[str] = []
    if not prices.empty and len(prices) >= 20:
        close = prices.sort_values("date")["close"].astype(float)
        distance = abs(close.iloc[-1] / close.rolling(20).mean().iloc[-1] - 1)
        if distance < 0.03:
            score -= 5
            reasons.append("價格貼近 MA20，追價空間較有限")
        vol20 = close.pct_change().tail(20).std()
        vol120 = close.pct_change().tail(120).std()
        if pd.notna(vol120) and vol120 > 0 and vol20 > vol120 * 1.5:
            score -= 5
            reasons.append("短期波動明顯升高")
    if not dividend.empty and "date" in dividend.columns:
        ex_dates = pd.to_datetime(dividend["date"], errors="coerce").dt.date.dropna()
        if any(0 <= (d - as_of).days <= dividend_warning_days for d in ex_dates):
            score -= 5
            reasons.append("近期有除息日期需留意")
    return max(score, 0), reasons or ["風險條件可接受"]
