from __future__ import annotations

import pandas as pd


def chip_score(institutional: pd.DataFrame, margin: pd.DataFrame, prices: pd.DataFrame) -> tuple[int, list[str]]:
    # FinMind institutional buy/sell and price volume are both share-based.
    # Recheck units before reusing this ratio with another data source.
    score = 0
    reasons: list[str] = []
    if not institutional.empty:
        df = institutional.copy().sort_values("date")
        df["net"] = df.get("buy", 0).astype(float) - df.get("sell", 0).astype(float)
        foreign = df[df["name"].str.contains("Foreign", case=False, na=False)].tail(3)["net"].sum()
        trust = df[df["name"].str.contains("Trust", case=False, na=False)].tail(3)["net"].sum()
        daily_total = df.groupby("date", as_index=False)["net"].sum().sort_values("date")
        total = daily_total.tail(3)["net"].sum()
        if foreign > 0:
            score += 8
            reasons.append("外資近 3 日買超")
        if trust > 0:
            score += 8
            reasons.append("投信近 3 日買超")
        if total > 0:
            score += 6
            reasons.append("整體法人近 3 日買超")
        avg_volume = prices["volume"].astype(float).tail(20).mean() if not prices.empty else 0
        if avg_volume and total / avg_volume >= 0.01:
            score += 4
            reasons.append("法人買超量相對成交量具參考性")
    if not margin.empty and len(margin) >= 3:
        m = margin.copy().sort_values("date")
        margin_bal = m["MarginPurchaseTodayBalance"].astype(float)
        if margin_bal.pct_change().tail(3).sum() > 0.10:
            score -= 6
            reasons.append("融資餘額短期增加過快")
    return max(min(score, 30), -6), reasons or ["籌碼面中性"]
