from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from src.config_loader import load_yaml, merge_theme_database
from src.data_provider.finmind_client import FinMindClient
from src.data_provider.tdcc_client import TdccClient, load_tdcc_csv, retail_holder_counts
from src.data_provider.twse_client import TwseClient
from src.report.retail_divergence import (
    SIGNAL_CLEAN,
    SIGNAL_CLEAN_WATCH,
    SIGNAL_NEUTRAL,
    SIGNAL_OVERHEATED,
    SIGNAL_OVERHEATED_WATCH,
    RetailDivergenceThresholds,
    enrich_retail_records,
)
from src.storage.sqlite_store import SQLiteStore


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update weekly retail-holder divergence signals")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--csv-path", help="Optional local TDCC CSV path for manual backfill/testing")
    parser.add_argument("--as-of-date", help="Optional cutoff date YYYY-MM-DD")
    parser.add_argument("--max-stocks", type=int, default=80, help="Max candidate stocks to enrich with price/volume")
    parser.add_argument("--tdcc-timeout", type=int, default=int(os.getenv("TDCC_TIMEOUT", "45")))
    parser.add_argument("--tdcc-retries", type=int, default=int(os.getenv("TDCC_RETRIES", "3")))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    config = merge_theme_database(load_yaml(args.config), ROOT)
    as_of = datetime.strptime(args.as_of_date, "%Y-%m-%d").date() if args.as_of_date else date.today()
    store = SQLiteStore(ROOT / "data" / "tw_stock_ai.sqlite3")
    run_id = os.getenv("GITHUB_RUN_ID", "")

    try:
        rows = (
            load_tdcc_csv(Path(args.csv_path))
            if args.csv_path
            else TdccClient(timeout=args.tdcc_timeout, retries=args.tdcc_retries).fetch_holding_rows()
        )
    except Exception as exc:
        logging.warning("TDCC retail divergence update skipped: %s", exc)
        if not args.dry_run:
            store.record_data_update(
                "tdcc_retail_holders",
                as_of,
                status="failed",
                message=str(exc),
                run_id=run_id,
            )
        return 0
    if not rows:
        logging.warning("TDCC retail divergence update skipped: empty CSV")
        if not args.dry_run:
            store.record_data_update(
                "tdcc_retail_holders",
                as_of,
                status="skipped",
                message="empty CSV",
                run_id=run_id,
            )
        return 0

    stock_names = _stock_universe(config)
    provider = TwseClient(fallback=FinMindClient())
    grouped = retail_holder_counts(rows, retail_levels={1, 2, 3})
    dates = sorted(value for value in grouped if value <= as_of)
    if not dates:
        logging.warning("TDCC retail divergence update skipped: no usable weekly snapshot")
        if not args.dry_run:
            store.record_data_update(
                "tdcc_retail_holders",
                as_of,
                status="skipped",
                message="no usable weekly snapshot",
                run_id=run_id,
            )
        return 0
    week_date = dates[-1]
    current_counts = grouped[week_date]
    previous_date, previous_counts = store.retail_holder_snapshot_before(week_date)
    signals, week_date = build_retail_signals(
        rows,
        stock_names,
        provider,
        as_of=as_of,
        max_stocks=args.max_stocks,
        previous_counts=previous_counts or None,
        previous_date=previous_date,
    )
    logging.info("TDCC retail divergence %s: %d signals", week_date, len(signals))
    if not args.dry_run:
        store.save_retail_holder_snapshot(current_counts, week_date, stock_names)
        if signals:
            store.save_retail_holder_signals(signals, week_date)
        store.record_data_update(
            "tdcc_retail_holders",
            as_of,
            status="ok",
            row_count=len(current_counts),
            source_date=week_date,
            message=f"{len(signals)} divergence signals; previous={previous_date.isoformat() if previous_date else '-'}",
            run_id=run_id,
        )
    return 0


def build_retail_signals(
    tdcc_rows,
    stock_names: dict[str, str],
    provider,
    *,
    as_of: date,
    max_stocks: int = 80,
    previous_counts: dict[str, int] | None = None,
    previous_date: date | None = None,
) -> tuple[list[dict], date | None]:
    grouped = retail_holder_counts(tdcc_rows, retail_levels={1, 2, 3})
    dates = sorted(value for value in grouped if value <= as_of)
    if not dates:
        return [], None
    week_date = dates[-1]
    current = grouped[week_date]
    if previous_counts and previous_date:
        previous = previous_counts
        prev_date = previous_date
    elif len(dates) >= 2:
        prev_date = dates[-2]
        previous = grouped[prev_date]
    else:
        return [], week_date
    raw_records = []
    for stock_id, name in stock_names.items():
        if stock_id not in current or stock_id not in previous:
            continue
        prev_holders = previous[stock_id]
        if not prev_holders:
            continue
        holder_count = current[stock_id]
        holder_change = holder_count - prev_holders
        holder_change_pct = holder_change / prev_holders * 100
        raw_records.append(
            {
                "week_date": week_date.isoformat(),
                "stock_id": stock_id,
                "name": name,
                "holder_count": holder_count,
                "prev_holder_count": prev_holders,
                "holder_change": holder_change,
                "holder_change_pct": holder_change_pct,
            }
        )

    raw_records.sort(key=lambda item: abs(float(item["holder_change_pct"])), reverse=True)
    enriched = []
    for item in raw_records[:max_stocks]:
        market = _market_snapshot(provider, item["stock_id"], prev_date, week_date)
        item.update(market)
        enriched.append(item)

    classified = enrich_retail_records(
        enriched,
        thresholds=RetailDivergenceThresholds(holder_change_pct=3.0, price_flat_pct=1.0, min_volume=1000.0),
    )
    signals = [item for item in classified if item["signal"] != SIGNAL_NEUTRAL]
    priority = {
        SIGNAL_CLEAN: 0,
        SIGNAL_OVERHEATED: 1,
        SIGNAL_CLEAN_WATCH: 2,
        SIGNAL_OVERHEATED_WATCH: 3,
    }
    signals.sort(key=lambda item: (priority.get(item["signal"], 9), -abs(float(item.get("holder_change_pct") or 0))))
    return signals, week_date


def _market_snapshot(provider, stock_id: str, prev_date: date, week_date: date) -> dict:
    start = prev_date - timedelta(days=5)
    try:
        prices = provider.stock_prices(stock_id, start, week_date)
    except Exception:
        return {"price_change_pct": None, "volume": None}
    if prices is None or prices.empty or "close" not in prices.columns:
        return {"price_change_pct": None, "volume": None}
    prices = prices.dropna(subset=["close"]).copy()
    if prices.empty:
        return {"price_change_pct": None, "volume": None}
    if "date" in prices.columns:
        prices["date"] = prices["date"].apply(lambda value: value.date() if hasattr(value, "date") else value)
        prev_rows = prices[prices["date"] <= prev_date]
        current_rows = prices[prices["date"] <= week_date]
    else:
        prev_rows = prices.iloc[:1]
        current_rows = prices
    if prev_rows.empty or current_rows.empty:
        return {"price_change_pct": None, "volume": None}
    prev_close = float(prev_rows.iloc[-1]["close"])
    current = current_rows.iloc[-1]
    current_close = float(current["close"])
    volume_shares = float(current.get("volume", 0) or 0)
    return {
        "price_change_pct": ((current_close - prev_close) / prev_close * 100) if prev_close else None,
        "volume": volume_shares / 1000,
    }


def _stock_universe(config: dict) -> dict[str, str]:
    names = dict(config.get("stock_names", {}))
    for theme in config.get("theme_pools", {}).values():
        for stock_id, name in (theme.get("stocks") or {}).items():
            names.setdefault(str(stock_id), str(name))
    return names


if __name__ == "__main__":
    raise SystemExit(main())
