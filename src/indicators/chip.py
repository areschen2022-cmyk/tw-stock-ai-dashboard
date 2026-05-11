from __future__ import annotations

import pandas as pd


def chip_score(institutional: pd.DataFrame, margin: pd.DataFrame, prices: pd.DataFrame) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if not institutional.empty:
        df = institutional.copy().sort_values("date")
        df["net"] = df.get("buy", 0).astype(float) - df.get("sell", 0).astype(float)
        by_name = df.groupby("name")["net"].tail(3).groupby(df.groupby("name").cumcount()).sum()
        foreign = df[df["name"].str.contains("Foreign", case=False, na=False)].tail(3)["net"].sum()
        trust = df[df["name"].str.contains("Trust", case=False, na=False)].tail(3)["net"].sum()
        total = df.tail(9)["net"].sum()
        if foreign > 0:
            score += 8
            reasons.append("外資近 3 日買超")
        if trust > 0:
            score += 8
            reasons.append("投信近 3 日買超")
        if total > 0:
            score += 6
            reasons.append("整體法人近 3 日買超")
        if not prices.empty and total > prices["volume"].astype(float).tail(20).mean() * 0.001:
            score += 4
            reasons.append("法人買超量相對成交量具參考性")
        _ = by_name
    if not margin.empty and len(margin) >= 3:
        m = margin.copy().sort_values("date")
        margin_bal = m["MarginPurchaseTodayBalance"].astype(float)
        short_bal = m["ShortSaleTodayBalance"].astype(float)
        if margin_bal.pct_change().tail(3).sum() > 0.10:
            score -= 6
            reasons.append("融資餘額短期增加過快")
        if short_bal.tail(3).sum() < 1:
            score -= 5
            reasons.append("融券餘額偏低，籌碼警訊不足以形成軋空條件")
    return max(min(score, 30), -11), reasons or ["籌碼面中性"]
