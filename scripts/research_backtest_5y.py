from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_yaml, merge_theme_database
from src.data_provider.finmind_client import FinMindClient


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_COST_BPS = 60.0


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _default_as_of() -> date:
    today = datetime.now(TAIPEI).date()
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    return today


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def build_universe(config: dict, mode: str, max_stocks: int | None) -> list[str]:
    core = [str(stock_id) for stock_id in config.get("stocks", [])]
    theme_ids: list[str] = []
    for pool in (config.get("theme_pools") or {}).values():
        theme_ids.extend(str(stock_id) for stock_id in (pool.get("stocks") or {}))
    if mode == "core":
        selected = _unique(core)
    elif mode == "theme":
        selected = _unique(theme_ids)
    else:
        selected = _unique(core + theme_ids)
    return selected[:max_stocks] if max_stocks else selected


def _num_series(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce")


def _clean_prices(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    out = out[out["close"] > 0].sort_values("date").drop_duplicates("date")
    return out.reset_index(drop=True)


def _safe_avg(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return round(mean(clean), 4) if clean else None


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags) * 100, 2) if flags else None


def _return_stats(rows: list[dict], key: str = "net_return_5d") -> dict:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return {
        "signals": len(rows),
        "completed": len(values),
        "win_rate": _rate([value > 0 for value in values]),
        "avg_return": _safe_avg(values),
        "median_return": round(float(pd.Series(values).median()), 4) if values else None,
        "best_return": round(max(values), 4) if values else None,
        "worst_return": round(min(values), 4) if values else None,
    }


def _monthly_stats(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[str(row["signal_date"])[:7]].append(row)
    return [
        {"month": month, **_return_stats(items)}
        for month, items in sorted(buckets.items())
    ]


def _signal_names(row: pd.Series) -> list[str]:
    names: list[str] = []
    if bool(row.get("breakout_volume")):
        names.append("breakout_volume")
    if bool(row.get("trend_volume")):
        names.append("trend_volume")
    if bool(row.get("pullback_reclaim")):
        names.append("pullback_reclaim")
    return names


def build_price_volume_signals(
    stock_id: str,
    name: str,
    prices: pd.DataFrame,
    cost_bps: float = DEFAULT_COST_BPS,
) -> list[dict]:
    df = _clean_prices(prices)
    if len(df) < 90:
        return []

    close = _num_series(df, "close")
    volume = _num_series(df, "volume")
    df["ma20"] = close.rolling(20, min_periods=20).mean()
    df["ma60"] = close.rolling(60, min_periods=60).mean()
    df["vol20"] = volume.rolling(20, min_periods=20).mean()
    df["prev_high60"] = close.shift(1).rolling(60, min_periods=60).max()
    df["prev_close"] = close.shift(1)
    df["prev_ma20"] = df["ma20"].shift(1)
    df["breakout_volume"] = (close > df["prev_high60"]) & (volume > df["vol20"] * 1.5)
    df["trend_volume"] = (close > df["ma20"]) & (df["ma20"] > df["ma60"]) & (volume > df["vol20"] * 1.2)
    df["pullback_reclaim"] = (close > df["ma20"]) & (df["prev_close"] <= df["prev_ma20"]) & (volume > df["vol20"])

    rows: list[dict] = []
    cost_pct = cost_bps / 100.0
    for idx in range(60, len(df) - 11):
        current = df.iloc[idx]
        signal_types = _signal_names(current)
        if not signal_types:
            continue
        entry_row = df.iloc[idx + 1]
        exit_5d = df.iloc[idx + 6]
        exit_10d = df.iloc[idx + 11]
        entry_price = float(entry_row["open"])
        if not entry_price or entry_price <= 0:
            continue
        gross_5d = (float(exit_5d["close"]) / entry_price - 1) * 100
        gross_10d = (float(exit_10d["close"]) / entry_price - 1) * 100
        rows.append(
            {
                "stock_id": stock_id,
                "name": name,
                "signal_date": current["date"].date().isoformat(),
                "entry_date": entry_row["date"].date().isoformat(),
                "signal_types": signal_types,
                "entry_price": round(entry_price, 4),
                "gross_return_5d": round(gross_5d, 4),
                "net_return_5d": round(gross_5d - cost_pct, 4),
                "gross_return_10d": round(gross_10d, 4),
                "net_return_10d": round(gross_10d - cost_pct, 4),
            }
        )
    return rows


def summarize_signals(rows: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        for signal_type in row.get("signal_types") or []:
            by_type[signal_type].append(row)
    return {
        "overall_5d": _return_stats(rows, "net_return_5d"),
        "overall_10d": _return_stats(rows, "net_return_10d"),
        "by_signal_type": [
            {"signal_type": signal_type, **_return_stats(items)}
            for signal_type, items in sorted(by_type.items())
        ],
        "monthly": _monthly_stats(rows),
        "recent_examples": rows[-20:],
    }


def build_research_backtest(
    root: Path,
    years: int,
    universe_mode: str,
    max_stocks: int | None,
    offline: bool,
    cost_bps: float,
) -> dict:
    load_dotenv(root / ".env")
    config = merge_theme_database(load_yaml(str(root / "config.yaml")), root)
    as_of = _default_as_of()
    start_date = as_of - timedelta(days=int(years * 365.25) + 90)
    universe = build_universe(config, universe_mode, max_stocks)
    names = {str(k): str(v) for k, v in (config.get("stock_names") or {}).items()}
    provider = FinMindClient(cache_dir=root / "data" / "cache")

    all_rows: list[dict] = []
    failures: list[dict] = []
    coverage: list[dict] = []
    for stock_id in universe:
        if offline:
            prices = provider.cached_only("TaiwanStockPrice", stock_id, start_date, as_of)
            if not prices.empty:
                prices = prices.rename(columns={"Trading_Volume": "volume", "max": "high", "min": "low"})
        else:
            prices = provider.stock_prices(stock_id, start_date, as_of)
        cleaned = _clean_prices(prices)
        coverage.append(
            {
                "stock_id": stock_id,
                "name": names.get(stock_id, ""),
                "rows": len(cleaned),
                "start": cleaned["date"].min().date().isoformat() if not cleaned.empty else None,
                "end": cleaned["date"].max().date().isoformat() if not cleaned.empty else None,
            }
        )
        if len(cleaned) < 90:
            failures.append({"stock_id": stock_id, "reason": "insufficient_price_history", "rows": len(cleaned)})
            continue
        all_rows.extend(build_price_volume_signals(stock_id, names.get(stock_id, ""), cleaned, cost_bps=cost_bps))

    status = "ok" if all_rows else "no_signals"
    if failures and len(failures) == len(universe):
        status = "no_usable_price_data"
    payload = {
        "as_of": as_of.isoformat(),
        "generated_at": _now(),
        "status": status,
        "method": {
            "name": "5-year price-volume research backtest",
            "years": years,
            "universe_mode": universe_mode,
            "universe_count": len(universe),
            "execution": "Signals are evaluated after daily close and entered at next trading day's open.",
            "cost_bps": cost_bps,
            "limitations": [
                "Price/volume only; historical news/theme context is not reconstructed.",
                "Universe uses current configured stocks, so survivorship bias remains.",
                "Use this for research direction, not as a standalone trading rule.",
            ],
        },
        "provider_status": provider.source_status(),
        "coverage": {
            "stocks_requested": len(universe),
            "stocks_with_usable_history": sum(1 for row in coverage if int(row["rows"]) >= 90),
            "failures": failures[:50],
            "sample": coverage[:30],
        },
        "summary": summarize_signals(all_rows),
    }
    return payload


def write_payload(root: Path, payload: dict, output: Path, mirror_docs: bool = True) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if mirror_docs and output.parts[-2] == "dashboard":
        docs = root / "docs" / output.name
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch five-year Taiwan stock prices and run a price-volume research backtest.")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--universe", choices=["core", "theme", "core-theme"], default="core-theme")
    parser.add_argument("--max-stocks", type=int, default=40, help="Limit stocks to protect API quota; 0 means no limit")
    parser.add_argument("--offline", action="store_true", help="Use existing FinMind cache only")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    parser.add_argument("--output", default="dashboard/research_backtest_5y.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    max_stocks = None if args.max_stocks == 0 else args.max_stocks
    payload = build_research_backtest(
        root=root,
        years=args.years,
        universe_mode=args.universe,
        max_stocks=max_stocks,
        offline=args.offline,
        cost_bps=args.cost_bps,
    )
    output = (root / args.output).resolve()
    write_payload(root, payload, output)
    summary = payload.get("summary", {}).get("overall_5d", {})
    coverage = payload.get("coverage", {})
    print(
        "research_backtest_5y "
        f"status={payload.get('status')} stocks={coverage.get('stocks_requested')} "
        f"usable={coverage.get('stocks_with_usable_history')} "
        f"signals={summary.get('signals')} completed={summary.get('completed')} "
        f"win_rate_5d={summary.get('win_rate')} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
