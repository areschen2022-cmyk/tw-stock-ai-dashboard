from __future__ import annotations

import pandas as pd

TIER_BONUS = {
    "core": 6,
    "beneficiary": 4,
    "speculative": 2,
}


def opportunity_score(
    bundle: dict[str, pd.DataFrame],
    themes: list[str],
    theme_details: list[dict] | None = None,
) -> tuple[int, list[str]]:
    prices = bundle.get("prices", pd.DataFrame())
    institutional = bundle.get("institutional", pd.DataFrame())
    revenue = bundle.get("revenue", pd.DataFrame())
    score = 0
    reasons: list[str] = []

    if not prices.empty and len(prices) >= 25:
        df = prices.sort_values("date")
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)
        vol_ma20 = volume.rolling(20).mean().iloc[-1]
        if vol_ma20 > 0 and volume.iloc[-1] >= vol_ma20 * 2:
            score += 10
            reasons.append(f"成交量放大 {volume.iloc[-1] / vol_ma20:.1f} 倍")
        if close.iloc[-1] >= close.iloc[-21:-1].max():
            score += 8
            reasons.append("突破近 20 日高點")

    if not institutional.empty:
        df = institutional.copy().sort_values("date")
        df["net"] = df.get("buy", 0).astype(float) - df.get("sell", 0).astype(float)
        foreign = df[df["name"].str.contains("Foreign", case=False, na=False)].tail(3)["net"].sum()
        if foreign > 0:
            score += 7
            reasons.append("外資近 3 日轉買超")
        total = df.tail(9)["net"].sum()
        if total > 0:
            score += 5
            reasons.append("法人合計偏買")

    if not revenue.empty and len(revenue) >= 15:
        df = revenue.sort_values("date")
        latest = float(df.iloc[-1]["revenue"])
        year_ago = float(df.iloc[-13]["revenue"])
        yoy = (latest / year_ago - 1) * 100 if year_ago else 0
        if yoy >= 30:
            score += 8
            reasons.append(f"月營收年增 {yoy:.1f}%")
        elif yoy >= 10:
            score += 4
            reasons.append(f"月營收年增 {yoy:.1f}%")

    if theme_details:
        tier_bonus = sum(TIER_BONUS.get(item.get("tier", "beneficiary"), 3) for item in theme_details)
        score += min(tier_bonus, 8)
        labels = [
            f"{item.get('theme_name', '題材')}({item.get('tier_label', item.get('tier', '受惠'))})"
            for item in theme_details[:2]
        ]
        reasons.append(f"題材分層：{'/'.join(labels)}")
    elif themes:
        score += min(len(themes) * 3, 6)
        reasons.append(f"題材：{'/'.join(themes[:2])}")

    return min(score, 30), reasons or ["尚無明顯異常訊號"]
