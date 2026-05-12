from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import requests

from src.storage.sqlite_store import SQLiteStore


MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
QUADRANTS = ("主動流入", "止跌承接", "主動砍倉", "量縮漲")


def classify_quadrant(rank_change: int, price_change_pct: float) -> str:
    if rank_change > 0 and price_change_pct > 0:
        return "主動流入"
    if rank_change > 0 and price_change_pct <= 0:
        return "止跌承接"
    if rank_change <= 0 and price_change_pct < 0:
        return "主動砍倉"
    return "量縮漲"


def summarize_themes(
    signals: list[dict],
    theme_map: dict[str, list[str]],
    top_n: int = 5,
    rank_limit: int = 300,
) -> list[dict]:
    stock_themes = _stock_theme_map(theme_map)
    buckets: dict[str, dict[str, int]] = {}
    for signal in signals:
        if int(signal.get("volume_rank") or 999999) > rank_limit:
            continue
        for theme in stock_themes.get(signal["stock_id"], []):
            row = buckets.setdefault(theme, {"theme": theme, **{name: 0 for name in QUADRANTS}})
            row[signal["quadrant"]] += 1
    return sorted(buckets.values(), key=lambda row: (-row["主動流入"], row["theme"]))[:top_n]


def build_watchlist(
    signals: list[dict],
    names: dict[str, str],
    max_items: int = 10,
) -> list[dict]:
    candidates = [
        signal
        for signal in signals
        if signal["quadrant"] in {"主動流入", "止跌承接"} and int(signal.get("volume_rank") or 999999) <= 20
    ]
    candidates.sort(key=lambda item: (-int(item.get("rank_change") or 0), int(item.get("volume_rank") or 999999)))
    watchlist = []
    for signal in candidates[:max_items]:
        reason = "量增上漲"
        if signal["quadrant"] == "止跌承接":
            reason = f"量增承接，{float(signal.get('price_change_pct') or 0):.1f}%"
        watchlist.append(
            {
                "stock_id": signal["stock_id"],
                "name": names.get(signal["stock_id"], signal.get("name", "")),
                "quadrant": signal["quadrant"],
                "reason": reason,
                "price_change_pct": signal.get("price_change_pct"),
            }
        )
    return watchlist


def build_telegram_message(
    trade_date: date,
    signals: list[dict],
    theme_summary: list[dict],
    watchlist: list[dict],
) -> str:
    counts = {name: sum(1 for signal in signals if signal["quadrant"] == name) for name in QUADRANTS}
    inflow = counts["主動流入"]
    selloff = counts["主動砍倉"]
    ratio = inflow / max(selloff, 1)
    if ratio >= 10:
        label = "極偏多"
    elif ratio >= 5:
        label = "偏多"
    elif ratio >= 2:
        label = "中性偏多"
    else:
        label = "中性或偏空"

    lines = [
        f"台股收盤資金流向｜{trade_date.isoformat()}",
        "",
        f"市場結構：{label}",
        f"主動流入 {inflow}｜主動砍倉 {selloff}｜比值 {ratio:.1f}:1",
    ]
    if theme_summary:
        themes = "、".join(row["theme"] for row in theme_summary[:5])
        lines.extend(["", "強勢族群：", themes])
    if watchlist:
        lines.extend(["", "明日優先追蹤："])
        for item in watchlist:
            lines.append(f"{item['stock_id']} {item['name']}｜{item['reason']}")
    lines.extend(["", "僅供研究追蹤，不是投資建議。"])
    return "\n".join(lines)


def run_capital_flow(
    trade_date: date,
    store: SQLiteStore,
    names: dict[str, str],
    theme_map: dict[str, list[str]],
    twse_client,
) -> str:
    today_date, today_rows = _fetch_latest_market_close(trade_date, twse_client)
    prev_date, prev_rows = _fetch_latest_market_close(today_date - timedelta(days=1), twse_client)
    signals = _build_signals(today_rows, prev_rows, theme_map)
    store.save_capital_flow(signals, today_date)
    theme_summary = summarize_themes(signals, theme_map)
    watchlist = build_watchlist(signals, names)
    return build_telegram_message(today_date, signals, theme_summary, watchlist)


def _fetch_latest_market_close(trade_date: date, twse_client, max_lookback_days: int = 7) -> tuple[date, list[dict]]:
    for offset in range(max_lookback_days + 1):
        target = trade_date - timedelta(days=offset)
        rows = fetch_market_close(target, twse_client)
        if rows:
            return target, rows
    raise RuntimeError(f"No TWSE MI_INDEX data near {trade_date.isoformat()}")


def fetch_market_close(trade_date: date, twse_client) -> list[dict]:
    params = {
        "response": "json",
        "type": "ALLBUT0999",
        "date": trade_date.strftime("%Y%m%d"),
    }
    response = requests.get(MI_INDEX_URL, params=params, headers=getattr(twse_client, "headers", None), timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("stat") != "OK":
        return []
    table = _daily_close_table(payload)
    if not table:
        return []
    return [_parse_mi_row(row) for row in table.get("data", []) if _is_common_stock(row[0])]


def _daily_close_table(payload: dict[str, Any]) -> dict | None:
    for table in payload.get("tables", []):
        fields = table.get("fields") or []
        if fields[:5] == ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額"]:
            return table
    return None


def _parse_mi_row(row: list[Any]) -> dict:
    close = _num(row[8])
    signed_change = _signed_change(row[9], row[10])
    prev_close = close - signed_change
    price_change_pct = (signed_change / prev_close * 100) if prev_close else 0.0
    return {
        "stock_id": str(row[0]).strip(),
        "name": str(row[1]).strip(),
        "volume": _num(row[2]),
        "volume_value": _num(row[4]) / 100_000_000,
        "open": _num(row[5]),
        "high": _num(row[6]),
        "low": _num(row[7]),
        "close": close,
        "price_change_pct": price_change_pct,
    }


def _build_signals(
    today_rows: list[dict],
    prev_rows: list[dict],
    theme_map: dict[str, list[str]],
    min_volume_value: float = 10.0,
) -> list[dict]:
    stock_themes = _stock_theme_map(theme_map)
    today_ranked = sorted(today_rows, key=lambda row: row["volume_value"], reverse=True)
    prev_ranked = sorted(prev_rows, key=lambda row: row["volume_value"], reverse=True)
    prev_ranks = {row["stock_id"]: index for index, row in enumerate(prev_ranked, start=1)}
    fallback_rank = len(prev_ranked) + 1
    signals = []
    for volume_rank, row in enumerate(today_ranked, start=1):
        if row["volume_value"] < min_volume_value:
            continue
        prev_rank = prev_ranks.get(row["stock_id"], fallback_rank)
        rank_change = prev_rank - volume_rank
        quadrant = classify_quadrant(rank_change, row["price_change_pct"])
        signals.append(
            {
                "stock_id": row["stock_id"],
                "name": row["name"],
                "quadrant": quadrant,
                "volume_rank": volume_rank,
                "prev_volume_rank": prev_rank,
                "rank_change": rank_change,
                "price_change_pct": row["price_change_pct"],
                "volume_value": row["volume_value"],
                "themes": stock_themes.get(row["stock_id"], []),
            }
        )
    return signals


def _stock_theme_map(theme_map: dict[str, list[str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for theme, stocks in theme_map.items():
        for stock_id in stocks:
            result.setdefault(str(stock_id), []).append(theme)
    return result


def _signed_change(sign_html: object, value: object) -> float:
    raw = str(sign_html)
    change = _num(value)
    if "green" in raw or "-" in raw:
        return -change
    if "red" in raw or "+" in raw:
        return change
    return 0.0


def _num(value: object) -> float:
    text = str(value).replace(",", "").strip()
    if text in {"", "--", "nan", "None"}:
        return 0.0
    return float(text)


def _is_common_stock(stock_id: object) -> bool:
    text = str(stock_id).strip()
    return len(text) == 4 and text.isdigit()
