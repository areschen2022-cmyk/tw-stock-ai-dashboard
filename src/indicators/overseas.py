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
    stock_adjustments: dict[str, int] | None = None
    sector_impacts: list[dict] | None = None


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


def analyze_overseas_sentiment(
    bundle: dict[str, pd.DataFrame],
    sector_map: dict | None = None,
) -> OverseasSentiment:
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

    sector_impacts, stock_adjustments = _sector_impacts(bundle, sector_map or {})
    for impact in sector_impacts[:4]:
        reasons.append(
            f"{impact['symbol']} {impact['change_pct']:+.2f}% → {impact['sector']}（{impact['stocks']}）"
        )

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
    return OverseasSentiment(
        label,
        adjustment,
        semiconductor_adjustment,
        summary,
        reasons,
        stock_adjustments=stock_adjustments,
        sector_impacts=sector_impacts,
    )


def _sector_impacts(bundle: dict[str, pd.DataFrame], sector_map: dict) -> tuple[list[dict], dict[str, int]]:
    us_to_tw = sector_map.get("us_to_tw", {}) or {}
    tw_to_sector = _tw_to_sector(sector_map.get("sector_map", {}) or {})
    impacts: list[dict] = []
    stock_adjustments: dict[str, int] = {}
    for symbol, tw_stocks in us_to_tw.items():
        change = _pct_change(bundle.get(symbol.lower(), pd.DataFrame()))
        if change is None:
            change = _pct_change(bundle.get(symbol, pd.DataFrame()))
        if change is None:
            continue
        mapped_stocks = [str(stock_id) for stock_id in tw_stocks]
        sector_names = sorted({tw_to_sector.get(stock_id, "未分類") for stock_id in mapped_stocks})
        direction = 1 if change >= 2 else -1 if change <= -2 else 0
        if direction:
            for stock_id in mapped_stocks:
                stock_adjustments[stock_id] = stock_adjustments.get(stock_id, 0) + direction
        impacts.append(
            {
                "symbol": symbol,
                "change_pct": change,
                "sector": "/".join(sector_names),
                "stocks": ",".join(mapped_stocks[:6]),
            }
        )
    stock_adjustments = {
        stock_id: max(min(adj, 3), -3)
        for stock_id, adj in stock_adjustments.items()
    }
    impacts.sort(key=lambda item: abs(item["change_pct"]), reverse=True)
    return impacts, stock_adjustments


def _tw_to_sector(sector_map: dict[str, list[str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for sector, stocks in sector_map.items():
        for stock_id in stocks:
            result.setdefault(str(stock_id), sector)
    return result
