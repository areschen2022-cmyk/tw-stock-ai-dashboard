from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.kronos_proxy import build_kronos_proxy_backtest, write_kronos_proxy_backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Kronos-style OHLCV proxy backtest before production model integration.")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--max-stocks", type=int, default=0, help="0 means no limit")
    parser.add_argument("--cost-bps", type=float, default=60.0)
    parser.add_argument("--online", action="store_true", help="Allow FinMind fetches when cache is missing")
    parser.add_argument("--output", default="dashboard/kronos_proxy_backtest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    payload = build_kronos_proxy_backtest(
        root=root,
        years=args.years,
        min_score=args.min_score,
        max_stocks=None if args.max_stocks == 0 else args.max_stocks,
        cost_bps=args.cost_bps,
        offline=not args.online,
    )
    output = (root / args.output).resolve()
    write_kronos_proxy_backtest(root, output, payload)
    overall = (payload.get("summary") or {}).get("overall_5d") or {}
    phase2 = payload.get("phase2") or {}
    print(
        "kronos_proxy_backtest "
        f"status={payload.get('status')} as_of={payload.get('as_of')} "
        f"signals={overall.get('signals')} completed={overall.get('completed')} "
        f"win_rate_5d={overall.get('win_rate')} "
        f"phase2={phase2.get('status')} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
