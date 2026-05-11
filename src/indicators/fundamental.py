from __future__ import annotations

import pandas as pd


def fundamental_score(revenue: pd.DataFrame) -> tuple[int, list[str]]:
    if revenue.empty or len(revenue) < 15:
        return 0, ["月營收資料不足"]
    df = revenue.copy().sort_values("date")
    latest = float(df.iloc[-1]["revenue"])
    previous = float(df.iloc[-2]["revenue"])
    year_ago = float(df.iloc[-13]["revenue"])
    yoy = (latest / year_ago - 1) * 100 if year_ago else 0
    mom = (latest / previous - 1) * 100 if previous else 0
    score = 0
    reasons: list[str] = []
    if yoy > 10:
        score += 6
        reasons.append(f"最新月營收年增 {yoy:.1f}%")
    if yoy > 20:
        score += 4
        reasons.append("最新月營收年增超過 20%")
    if mom > 0:
        score += 4
        reasons.append(f"最新月營收月增 {mom:.1f}%")
    recent_yoy = []
    for offset in range(1, 4):
        current = float(df.iloc[-offset]["revenue"])
        prior = float(df.iloc[-offset - 12]["revenue"])
        recent_yoy.append(current > prior)
    if all(recent_yoy):
        score += 6
        reasons.append("近 3 個月營收皆優於去年同期")
    return min(score, 20), reasons or ["基本面中性"]
