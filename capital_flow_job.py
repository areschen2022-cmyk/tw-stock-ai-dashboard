from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from src.config_loader import load_yaml, merge_theme_database
from src.data_provider.finmind_client import FinMindClient
from src.data_provider.twse_client import TwseClient
from src.notifier.telegram import TelegramNotifier
from src.report.capital_flow import run_capital_flow
from src.storage.sqlite_store import SQLiteStore


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Taiwan stock closing capital flow report")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--as-of-date", help="Override trade date, format YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Print notification instead of sending Telegram")
    parser.add_argument("--send-telegram", action="store_true", help="Force real Telegram delivery")
    return parser.parse_args()


def _resolve_date(value: str | None) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return date.today()


def _theme_map(config: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for theme_cfg in config.get("theme_pools", {}).values():
        theme_name = theme_cfg.get("name", "")
        if not theme_name:
            continue
        for stock_id in theme_cfg.get("stocks", {}):
            result.setdefault(theme_name, []).append(str(stock_id))
    return result


def main() -> int:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    config = merge_theme_database(load_yaml(args.config), ROOT)
    trade_date = _resolve_date(args.as_of_date)
    store = SQLiteStore(ROOT / "data" / "tw_stock_ai.sqlite3")
    provider = TwseClient(fallback=FinMindClient())

    message = run_capital_flow(
        trade_date,
        store,
        config.get("stock_names", {}),
        _theme_map(config),
        provider,
    )
    dry_run = False if args.send_telegram else args.dry_run or bool(config.get("runtime", {}).get("dry_run", True))
    TelegramNotifier.from_env(dry_run=dry_run).send(message)
    logging.info("Capital flow report generated for %s", trade_date.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
