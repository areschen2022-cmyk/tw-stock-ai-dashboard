"""
scripts/intraday_confirm.py — 9:10 intraday open-condition runner

Fetches the first 9 minutes of minute data for every A/B-grade candidate
saved by today's morning screener, evaluates whether open conditions are
met, and sends a second Telegram notification.

Usage
-----
  python scripts/intraday_confirm.py                   # dry-run (print only)
  python scripts/intraday_confirm.py --send-telegram   # real Telegram push
  python scripts/intraday_confirm.py --as-of-date 2026-05-12
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# ── project root on sys.path ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from src.data_provider.finmind_client import FinMindClient
from src.intraday.open_confirm import check_candidates, format_telegram
from src.notifier.telegram import TelegramNotifier
from src.storage.sqlite_store import SQLiteStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Intraday open-condition confirmation (09:10 push)")
    parser.add_argument("--send-telegram", action="store_true", help="Actually send Telegram message")
    parser.add_argument("--as-of-date", help="Override trade date, format YYYY-MM-DD")
    parser.add_argument("--check-time", default="09:10", help="Label shown in Telegram message (default: 09:10)")
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(ROOT / "logs" / "intraday.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    args = parse_args()

    trade_date: date
    if args.as_of_date:
        trade_date = datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
    else:
        trade_date = date.today()

    dry_run = not args.send_telegram

    store = SQLiteStore(ROOT / "data" / "tw_stock_ai.sqlite3")
    candidates = store.watch_candidates_today(trade_date)

    if not candidates:
        logging.info("No A/B candidates found for %s — nothing to confirm.", trade_date)
        msg = (
            f"🔔 <b>盤中確認｜{args.check_time}</b>｜{trade_date.isoformat()}\n\n"
            "📭 今日早報無 A/B 級候選，無需開盤確認。\n\n"
            "⚠️ 僅供研究追蹤，不是投資建議。"
        )
        TelegramNotifier.from_env(dry_run=dry_run).send(msg)
        return 0

    logging.info("Checking %d A/B candidates for %s", len(candidates), trade_date)

    client = FinMindClient()
    results = check_candidates(
        candidates,
        intraday_fn=client.intraday_prices,
        trade_date=trade_date,
    )

    passed = sum(1 for r in results if r.passed)
    logging.info("Intraday confirm: %d/%d passed open conditions", passed, len(results))

    message = format_telegram(results, trade_date, check_time=args.check_time)
    TelegramNotifier.from_env(dry_run=dry_run).send(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
