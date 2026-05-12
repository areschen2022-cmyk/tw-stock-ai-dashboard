from __future__ import annotations

import pandas as pd


def _vol_display(shares: float) -> str:
    """Convert raw share volume to a human-readable 張 string (1 張 = 1,000 shares)."""
    zhang = shares / 1000
    if zhang >= 1:
        return f"{zhang:.0f} 張"
    return f"{shares:.0f} 股"


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

    # Moving averages
    ma5 = close.rolling(5).mean().iloc[-1]
    _ma20_series = close.rolling(20).mean()
    ma20_val = _ma20_series.iloc[-1] if len(close) >= 20 else None
    ma20 = float(ma20_val) if (ma20_val is not None and not pd.isna(ma20_val)) else float(ma5)

    # Volume stats
    avg_volume = float(volume.tail(20).mean()) if len(volume) >= 20 else float(volume.mean())

    # Stop reference: lowest of MA5, yesterday low, 3-day low
    low3 = float(low.tail(3).min())
    stop_ref = min(prev_low, low3, float(ma5))

    # ── 5-minute volume threshold ─────────────────────────────
    # Taiwan session = 270 min; natural 5-min pace ≈ avg * 1.85%
    # We target 2.7× natural pace (≈ 5% of daily avg) to confirm a "hot open"
    vol_5min = avg_volume * 0.05
    vol_str = _vol_display(vol_5min)

    # ── Setup-type detection ──────────────────────────────────
    near_recent_high = False
    if len(close) >= 21:
        recent_high_20 = float(close.iloc[-21:-1].max())
        near_recent_high = latest_close >= recent_high_20 * 0.99

    near_ma20 = abs(latest_close - ma20) / ma20 < 0.025 if ma20 > 0 else False

    # ── Gap limit by score tier ───────────────────────────────
    # Higher score = tighter gap tolerance (stock is already strong, no need to chase)
    if total_score >= 80:
        gap_pct, gap_label = 0.020, "+2%"
    elif total_score >= 70:
        gap_pct, gap_label = 0.025, "+2.5%"
    else:
        gap_pct, gap_label = 0.030, "+3%"
    gap_limit = latest_close * (1 + gap_pct)

    # ── Action & entry condition ──────────────────────────────
    has_chase_risk = any("追價" in r or "貼近" in r for r in risk_reasons)

    if total_score >= 80 and not has_chase_risk:
        action = "可追蹤突破"
        if near_recent_high:
            setup = f"突破型：昨收已貼近20日高，開盤確認站穩昨高 {prev_high:.2f}"
        else:
            setup = f"強勢型：開盤站穩昨高 {prev_high:.2f}"
        entry = (
            f"{setup}，跳空不追超過 {gap_limit:.2f}（{gap_label}）；"
            f"開盤前5分鐘量 >= {vol_str}（日均量5%）"
        )
        stop = (
            f"跌破 {stop_ref:.2f}（MA5 {ma5:.2f} / 昨低 {prev_low:.2f} / 近3日低 {low3:.2f} 三者取低）止損出場"
        )

    elif total_score >= 75:
        action = "等拉回"
        if near_ma20:
            pullback_note = f"目前已在 MA20（{ma20:.2f}）附近"
        else:
            pullback_note = f"等回測 MA20（{ma20:.2f}）或近3日低（{low3:.2f}）"
        entry = (
            f"{pullback_note}，量縮整理後出現放量（前5分鐘 >= {vol_str}）再進場；"
            f"不追超過 {gap_limit:.2f}（{gap_label}）"
        )
        stop = (
            f"收盤跌破 MA20（{ma20:.2f}）不回則止損，最寬參考 {stop_ref:.2f}"
        )

    elif total_score >= 65:
        action = "只觀察"
        entry = (
            f"觀察站穩 MA5（{ma5:.2f}）且開盤前5分鐘量 >= {vol_str}；"
            f"條件同時滿足再考慮，不追超過 {gap_limit:.2f}（{gap_label}）"
        )
        stop = f"跌破 {stop_ref:.2f} 不考慮進場"

    else:
        action = "避免追高"
        entry = (
            f"訊號偏弱，不建議進場；等 MA20（{ma20:.2f}）企穩、量能回升後重新評估"
        )
        stop = f"觀察支撐 {stop_ref:.2f}"

    return {
        "action": action,
        "entry": entry,
        "stop": stop,
        "stop_price": round(float(stop_ref), 2),
        "entry_limit_price": round(float(gap_limit), 2),
    }
