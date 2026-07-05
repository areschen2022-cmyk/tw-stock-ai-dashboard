from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.current_selection import build_current_selection_backtest, write_current_selection_backtest


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build same-condition backtest for current dashboard candidates.")
    parser.add_argument("--dashboard", default="dashboard/dashboard_data.json")
    parser.add_argument("--performance", default="dashboard/performance_data.json")
    parser.add_argument("--output-dir", default="dashboard")
    args = parser.parse_args()

    dashboard_payload = _read_json(ROOT / args.dashboard)
    performance_path = ROOT / args.performance
    performance_payload = _read_json(performance_path)
    payload = build_current_selection_backtest(dashboard_payload, performance_payload)
    write_current_selection_backtest(payload, ROOT / args.output_dir)
    performance_payload["current_selection_backtest"] = payload
    performance_path.write_text(json.dumps(performance_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "current_selection_backtest "
        f"as_of={payload.get('as_of')} "
        f"candidates={payload.get('candidate_count')} "
        f"referenceable={payload.get('referenceable_count')} "
        f"strong={payload.get('strong_reference_count')} "
        f"weak={payload.get('weak_reference_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
