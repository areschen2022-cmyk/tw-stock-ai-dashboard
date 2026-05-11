from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class OverseasSentiment:
    label: str
    adjustment: int
    semiconductor_adjustment: int
    summary: str
    reasons: list[str]


def _pct_change(df: pd.DataFrame, column: str = "Close") -> float | None:
    if df.empty or column not in df.columns or len(df) < 2:
        return None
    series = df.sort_values("date")[column].astype(float).tail(2)
    previous = series.iloc[0]
    if previous == 0:
        return None
    return (series.iloc[1] / previous - 1) * 100


def _latest_tx_night(df: pd.DataFrame) -> tuple[float | None, str | None]:
    if df.empty:
        return None, None
    filtered = df[
        (df.get("trading_session") == "after_market")
        & (df.get("volume", 0).astype(float) > 0)
        & (~df.get("contract_date", "").astype(str).str.contains("/", regex=False))
    ].copy()
    if filtered.empty:
        return None, None
    latest_date = filtered["date"].max()
    latest = filtered[filtered["date"] == latest_date].sort_values("volume", ascending=False).iloc[0]
    return float(latest["spread_per"]), str(latest["contract_date"])


def analyze_overseas_sentiment(bundle: dict[str, pd.DataFrame]) -> OverseasSentiment:
    if not bundle:
        return OverseasSentiment("未啟用", 0, 0, "海外資料未啟用", ["未抓取海外資料"])

    changes = {
        "S&P500": _pct_change(bundle.get("sp500", pd.DataFrame())),
        "Nasdaq": _pct_change(bundle.get("nasdaq", pd.DataFrame())),
        "SOX": _pct_change(bundle.get("sox", pd.DataFrame())),
        "TSM ADR": _pct_change(bundle.get("tsm_adr", pd.DataFrame())),
    }
    us10y = _pct_change(bundle.get("us10y", pd.DataFrame()), column="value")
    tx_night, tx_contract = _latest_tx_night(bundle.get("tx_night", pd.DataFrame()))

    adjustment = 0
    semiconductor_adjustment = 0
    reasons: list[str] = []

    if changes["Nasdaq"] is not None:
        adjustment += -2 if changes["Nasdaq"] <= -1 else 1 if changes["Nasdaq"] >= 1 else 0
        reasons.append(f"Nasdaq {changes['Nasdaq']:+.2f}%")
    if changes["S&P500"] is not None:
        adjustment += -1 if changes["S&P500"] <= -1 else 1 if changes["S&P500"] >= 1 else 0
        reasons.append(f"S&P500 {changes['S&P500']:+.2f}%")
    if changes["SOX"] is not None:
        if changes["SOX"] <= -2:
            semiconductor_adjustment -= 5
        elif changes["SOX"] <= -1:
            semiconductor_adjustment -= 3
        elif changes["SOX"] >= 2:
            semiconductor_adjustment += 3
        elif changes["SOX"] >= 1:
            semiconductor_adjustment += 2
        reasons.append(f"SOX 半導體 {changes['SOX']:+.2f}%")
    if changes["TSM ADR"] is not None:
        if changes["TSM ADR"] <= -2:
            semiconductor_adjustment -= 4
        elif changes["TSM ADR"] <= -1:
            semiconductor_adjustment -= 2
        elif changes["TSM ADR"] >= 2:
            semiconductor_adjustment += 3
        elif changes["TSM ADR"] >= 1:
            semiconductor_adjustment += 1
        reasons.append(f"TSM ADR {changes['TSM ADR']:+.2f}%")
    if tx_night is not None:
        adjustment += -3 if tx_night <= -0.5 else 3 if tx_night >= 0.5 else 0
        reasons.append(f"台指期夜盤 {tx_contract} {tx_night:+.2f}%")
    if us10y is not None:
        adjustment += -1 if us10y >= 1 else 1 if us10y <= -1 else 0
        reasons.append(f"美債10年殖利率 {us10y:+.2f}%")

    adjustment = max(min(adjustment, 5), -6)
    semiconductor_adjustment = max(min(semiconductor_adjustment, 5), -7)
    total = adjustment + semiconductor_adjustment
    if total >= 4:
        label = "偏多"
    elif total <= -4:
        label = "偏空"
    else:
        label = "中性"
    summary = "；".join(reasons[:5]) if reasons else "海外資料不足"
    return OverseasSentiment(label, adjustment, semiconductor_adjustment, summary, reasons)
