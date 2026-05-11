from __future__ import annotations

import pandas as pd


def trade_plan(total_score: int, prices: pd.DataFrame, risk_reasons: list[str]) -> dict:
    if prices.empty or len(prices) < 5:
        return {
            "action": "只觀察",
            "entry": "價格資料不足，暫不設進場條件",
            "stop": "價格資料不足",
            "stop_price": None,
            "entry_limit_price": None,
        }

    df = prices.sort_values("date")
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series([0] * len(df))

    latest_close = close.iloc[-1]
    prev_high = high.iloc[-1]
    prev_low = low.iloc[-1]
    ma5 = close.rolling(5).mean().iloc[-1]
    avg_volume = volume.tail(20).mean() if len(volume) >= 20 else volume.mean()
    stop_ref = min(prev_low, low.tail(3).min(), ma5)
    gap_limit = latest_close * 1.03

    has_chase_risk = any("追價" in reason or "貼近" in reason for reason in risk_reasons)
    if total_score >= 80 and not has_chase_risk:
        action = "可追蹤突破"
    elif total_score >= 75:
        action = "等拉回"
    elif total_score >= 65:
        action = "只觀察"
    else:
        action = "避免追高"

    entry = (
        f"開盤不高於 {gap_limit:.2f}（+3%），量能延續，且站穩昨高 {prev_high:.2f}"
    )
    stop = f"跌破 MA5/昨低/近3日低點中較低值 {stop_ref:.2f}，先退出觀察"
    if avg_volume and avg_volume > 0:
        entry += f"，成交量需接近20日均量"
    return {
        "action": action,
        "entry": entry,
        "stop": stop,
        "stop_price": round(float(stop_ref), 2),
        "entry_limit_price": round(float(gap_limit), 2),
    }
