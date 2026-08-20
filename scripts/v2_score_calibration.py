from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.v2_score_calibration import build_v2_score_calibration, write_v2_score_calibration
from src.storage.sqlite_store import SQLiteStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Build V2 score distribution calibration report.")
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of)
    SQLiteStore(ROOT / "data" / "tw_stock_ai.sqlite3")
    payload = build_v2_score_calibration(ROOT / "data" / "tw_stock_ai.sqlite3", as_of)
    write_v2_score_calibration(payload, ROOT / "dashboard", ROOT / "reports")
    print(f"status={payload.get('status')} windows={len(payload.get('windows') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
