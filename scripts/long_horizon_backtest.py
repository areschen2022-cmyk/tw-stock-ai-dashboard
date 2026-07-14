from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage.sqlite_store import SQLiteStore


TAIPEI = ZoneInfo("Asia/Taipei")


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _days_for_years(years: int) -> int:
    return int(math.ceil(years * 365.25))


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


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _rate(flags: list[bool]) -> float | None:
    if not flags:
        return None
    return round(sum(1 for flag in flags if flag) / len(flags) * 100, 2)


def _return_stats(items: list[dict]) -> dict:
    returns = [_num(item.get("return_5d")) for item in items]
    values = [value for value in returns if value is not None]
    return {
        "signals": len(items),
        "completed": len(values),
        "win_rate_5d": _rate([value > 0 for value in values]),
        "avg_signal_return_5d": _avg(values),
        "best_return_5d": round(max(values), 4) if values else None,
        "worst_return_5d": round(min(values), 4) if values else None,
    }


def _date_range(items: list[dict]) -> dict:
    dates = sorted({item.get("signal_date") for item in items if item.get("signal_date")})
    if not dates:
        return {
            "actual_start": None,
            "actual_end": None,
            "actual_days": 0,
        }
    start = date.fromisoformat(dates[0])
    end = date.fromisoformat(dates[-1])
    return {
        "actual_start": dates[0],
        "actual_end": dates[-1],
        "actual_days": (end - start).days + 1,
    }


def _bucket_returns(items: list[dict], prefix_len: int) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        signal_date = item.get("signal_date")
        if not signal_date:
            continue
        buckets[signal_date[:prefix_len]].append(item)
    return [
        {"period": period, **_return_stats(rows)}
        for period, rows in sorted(buckets.items())
    ]


def _coverage_status(actual_days: int, requested_days: int) -> str:
    if actual_days <= 0:
        return "no_signal_data"
    if actual_days < requested_days * 0.5:
        return "partial_coverage"
    return "ok"


def _coverage_note(status: str, actual_days: int, requested_years: int) -> str:
    if status == "ok":
        return "資料覆蓋已接近要求視窗。"
    if status == "no_signal_data":
        return "目前沒有可驗證的訊號資料。"
    return (
        f"已用 {requested_years} 年視窗查詢，但資料庫實際只有 {actual_days} 天訊號；"
        "這不是完整 30 年回測。之後若匯入歷史訊號或每日持續累積，會自動延伸。"
    )


def build_long_horizon_backtest(root: Path, years: int = 30) -> dict:
    requested_days = _days_for_years(years)
    as_of = _latest_as_of(root)
    store = SQLiteStore(root / "data" / "tw_stock_ai.sqlite3")
    summary = store.performance_summary(as_of, days=requested_days)
    items = summary.get("items") or []
    coverage = _date_range(items)
    status = _coverage_status(int(coverage["actual_days"]), requested_days)

    return {
        "as_of": as_of.isoformat(),
        "generated_at": _now(),
        "status": status,
        "requested_years": years,
        "requested_days": requested_days,
        "coverage": coverage,
        "coverage_note": _coverage_note(status, int(coverage["actual_days"]), years),
        "method": {
            "signal_source": "watch_signals",
            "return_basis": "5 trading-day forward return after signal entry price",
            "monthly_return_basis": "Average 5D returns of completed signals grouped by signal month; this is signal performance, not portfolio P&L.",
            "costs": "No commission/slippage model in this summary.",
        },
        "overall": _return_stats(items),
        "monthly_returns": _bucket_returns(items, 7),
        "yearly_returns": _bucket_returns(items, 4),
        "score_bands": summary.get("score_bands") or [],
        "theme_stats": summary.get("theme_stats") or summary.get("top_themes") or [],
        "action_stats": summary.get("action_stats") or [],
        "data_quality": summary.get("data_quality") or {},
    }


def write_long_horizon_backtest(root: Path, output: Path, years: int = 30) -> dict:
    payload = build_long_horizon_backtest(root, years=years)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a long-horizon signal backtest summary.")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--years", type=int, default=30, help="Requested lookback years")
    parser.add_argument("--output", default="dashboard/backtest_30y.json", help="Output JSON path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    payload = write_long_horizon_backtest(root, output, years=args.years)
    overall = payload.get("overall") or {}
    coverage = payload.get("coverage") or {}
    print(
        "long_horizon_backtest "
        f"status={payload['status']} as_of={payload['as_of']} "
        f"coverage={coverage.get('actual_start')}..{coverage.get('actual_end')} "
        f"signals={overall.get('signals')} completed={overall.get('completed')} "
        f"win_rate_5d={overall.get('win_rate_5d')} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
