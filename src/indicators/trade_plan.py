from __future__ import annotations

import pandas as pd


def trade_plan(total_score: int, prices: pd.DataFrame, risk_reasons: list[str]) -> dict:
    if prices is None or prices.empty or len(prices) < 5:
        return {
            "action": "只觀察",
            "entry_decision": "資料不足",
            "entry_checklist": ["價格資料不足，今日不判斷進場"],
            "entry": "價格資料不足，不建立進場條件",
            "stop": "資料不足",
            "stop_price": None,
            "entry_limit_price": None,
            "vol_5min_threshold": None,
        }

    close = pd.to_numeric(prices["close"], errors="coerce")
    high = pd.to_numeric(prices.get("high", close), errors="coerce")
    low = pd.to_numeric(prices.get("low", close), errors="coerce")
    volume = pd.to_numeric(prices.get("volume", pd.Series(dtype=float)), errors="coerce")

    last_close = float(close.iloc[-1])
    prev_high = float(high.iloc[-2]) if len(high) >= 2 else last_close
    prev_low = float(low.iloc[-2]) if len(low) >= 2 else last_close
    ma5 = float(close.tail(5).mean())
    ma20 = float(close.tail(20).mean()) if len(close) >= 20 else float(close.mean())
    low3 = float(low.tail(3).min())
    recent_high20 = float(high.iloc[-21:-1].max()) if len(high) >= 21 else prev_high
    near_recent_high = last_close >= recent_high20 * 0.98
    near_ma20 = abs(last_close - ma20) / ma20 <= 0.03 if ma20 else False
    avg_daily_volume = float(volume.tail(20).mean()) if not volume.empty else 0.0
    vol_5min_threshold = avg_daily_volume * 0.05 if avg_daily_volume else None
    vol_str = f"{vol_5min_threshold / 1000:.0f} 張" if vol_5min_threshold else "日均量 5%"

    stop_ref = min(ma5, prev_low, low3)
    risk_text = " ".join(str(reason) for reason in risk_reasons)
    has_red_risk = any(term in risk_text for term in ("紅色警戒", "風險過高", "不得進場", "停止進場"))

    if has_red_risk:
        action = "避免"
        entry_decision = "風險過高"
        entry = "風險訊號偏高，今日不建立進場。"
        stop = f"若已持有，跌破 {stop_ref:.2f} 優先降風險"
        checklist = ["紅色風險未解除前不進場"]
        gap_limit = None
    elif total_score >= 80:
        action = "可追蹤突破"
        entry_decision = "開盤確認"
        gap_limit = round(last_close * 1.02, 2)
        gap_label = "+2%"
        setup = f"站穩昨高 {prev_high:.2f}"
        if near_recent_high:
            setup = f"近20日高點附近，{setup}"
        entry = (
            f"{setup}，跳空不超過 {gap_limit:.2f}（{gap_label}），"
            f"開盤前5分鐘量 >= {vol_str}"
        )
        stop = f"跌破 {stop_ref:.2f}（MA5 {ma5:.2f} / 昨低 {prev_low:.2f} / 近3日低 {low3:.2f} 三者取低）止損"
        checklist = [
            f"站穩昨高 {prev_high:.2f}",
            f"不追超過 {gap_limit:.2f}（{gap_label}）",
            f"前5分鐘量 >= {vol_str}",
            f"跌破 {stop_ref:.2f} 止損",
        ]
    elif total_score >= 75:
        action = "等拉回"
        entry_decision = "等拉回"
        gap_limit = round(last_close * 1.02, 2)
        gap_label = "+2%"
        pullback_note = f"靠近 MA20（{ma20:.2f}）可觀察承接" if near_ma20 else f"等回測 MA20（{ma20:.2f}）或近3日低點（{low3:.2f}）"
        entry = (
            f"{pullback_note}，轉強需同時看到開盤前5分鐘量 >= {vol_str}，"
            f"不接受跳空追高超過 {gap_limit:.2f}（{gap_label}）"
        )
        stop = f"收盤跌破 MA20（{ma20:.2f}）或跌破 {stop_ref:.2f} 就停止觀察"
        checklist = [
            f"回測 MA20 {ma20:.2f} 或近3日低 {low3:.2f}",
            f"轉強量 >= {vol_str}",
            f"開盤不超過 {gap_limit:.2f}（{gap_label}）",
        ]
    elif total_score >= 65:
        action = "只觀察"
        entry_decision = "條件未同時滿足"
        gap_limit = round(last_close * 1.03, 2)
        gap_label = "+3%"
        entry = (
            f"觀察是否站回 MA5（{ma5:.2f}）且開盤前5分鐘量 >= {vol_str}；"
            f"若跳空過高或量縮不追，價格上限 {gap_limit:.2f}（{gap_label}）"
        )
        stop = f"跌破 {stop_ref:.2f} 不再觀察"
        checklist = [
            f"站回 MA5 {ma5:.2f}",
            f"前5分鐘量 >= {vol_str}",
            "沒有放量前不進場",
            "價格與量能未同時滿足就取消",
        ]
    else:
        action = "避免"
        entry_decision = "避免"
        gap_limit = None
        entry = f"分數不足，等站回 MA20（{ma20:.2f}）且量能改善後再評估"
        stop = f"觀察跌破 {stop_ref:.2f}"
        checklist = ["分數不足，不進場"]

    return {
        "action": action,
        "entry_decision": entry_decision,
        "entry_checklist": checklist,
        "entry": entry,
        "stop": stop,
        "stop_price": round(float(stop_ref), 2) if stop_ref == stop_ref else None,
        "entry_limit_price": gap_limit,
        "vol_5min_threshold": round(float(vol_5min_threshold), 2) if vol_5min_threshold else None,
    }
