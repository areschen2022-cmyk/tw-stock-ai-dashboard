from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage.sqlite_store import SQLiteStore


def _latest_as_of(root: Path) -> date:
    payload_path = root / "dashboard" / "dashboard_data.json"
    if payload_path.exists():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        return date.fromisoformat(payload["as_of"])
    with sqlite3.connect(root / "data" / "tw_stock_ai.sqlite3") as conn:
        row = conn.execute("SELECT MAX(as_of_date) FROM daily_scores").fetchone()
    if not row or not row[0]:
        raise RuntimeError("No dashboard JSON or daily_scores data found")
    return date.fromisoformat(row[0])


def _duplicate_count(conn: sqlite3.Connection, table: str, date_col: str, id_col: str) -> int:
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT {date_col}, {id_col}, COUNT(*) AS n
            FROM {table}
            GROUP BY {date_col}, {id_col}
            HAVING n > 1
        )
        """
    ).fetchone()
    return int(row[0] or 0)


def _extreme_return_count(items: list[dict], limit_pct: float) -> int:
    count = 0
    for item in items:
        for key in ("return_3d", "return_5d", "return_10d"):
            value = item.get(key)
            if value is None:
                continue
            if not math.isfinite(float(value)) or abs(float(value)) > limit_pct:
                count += 1
    return count


def run_check(root: Path, days: int, extreme_limit_pct: float) -> tuple[int, list[str]]:
    db_path = root / "data" / "tw_stock_ai.sqlite3"
    if not db_path.exists():
        return 1, [f"missing database: {db_path}"]

    as_of = _latest_as_of(root)
    store = SQLiteStore(db_path)
    summary = store.performance_summary(as_of, days=days)
    ai_summary = store.ai_council_summary(as_of, days=days)
    items = summary.get("items", [])
    completed = [item for item in items if item.get("return_5d") is not None]
    issues: list[str] = []

    with sqlite3.connect(db_path) as conn:
        daily_dupes = _duplicate_count(conn, "daily_scores", "as_of_date", "stock_id")
        watch_dupes = _duplicate_count(conn, "watch_signals", "signal_date", "stock_id")
        ai_dupes = _duplicate_count(conn, "ai_council_reviews", "review_date", "stock_id")
    if daily_dupes:
        issues.append(f"daily_scores duplicate groups: {daily_dupes}")
    if watch_dupes:
        issues.append(f"watch_signals duplicate groups: {watch_dupes}")
    if ai_dupes:
        issues.append(f"ai_council_reviews duplicate groups: {ai_dupes}")

    extreme = _extreme_return_count(items, extreme_limit_pct)
    if extreme:
        issues.append(f"extreme/non-finite forward returns: {extreme}")

    quality = summary.get("data_quality", {})
    if items and float(quality.get("completion_rate_5d") or 0) < 5:
        issues.append(f"5d completion rate too low: {quality.get('completion_rate_5d')}")

    print(f"as_of={as_of.isoformat()} days={days}")
    print(f"signals={len(items)} completed_5d={len(completed)}")
    print(f"win_rate_5d={summary.get('stats', {}).get('win_rate_5d')} avg_return_5d={summary.get('stats', {}).get('avg_return_5d')}")
    print(f"ai_signals={ai_summary.get('stats', {}).get('signals')} ai_completed={ai_summary.get('stats', {}).get('completed')}")
    if quality.get("pending_examples"):
        print("pending_examples=" + ", ".join(
            f"{item['signal_date']}:{item['stock_id']}" for item in quality["pending_examples"][:8]
        ))
    for note in summary.get("backtest_insights", {}).get("notes", []):
        print(f"note={note}")
    if issues:
        for issue in issues:
            print(f"ISSUE: {issue}")
        return 1, issues
    print("backtest_quality=ok")
    return 0, []


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate stored signal backtest data quality")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--extreme-limit-pct", type=float, default=80.0)
    args = parser.parse_args()
    code, _ = run_check(ROOT, args.days, args.extreme_limit_pct)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
