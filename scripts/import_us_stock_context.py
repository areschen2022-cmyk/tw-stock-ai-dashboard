from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_US_ROOT = Path("C:/Users/User/Documents/us-stock-ai")
ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _symbol_rows(rows: list[dict], limit: int = 20) -> list[dict]:
    output = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        output.append(
            {
                "symbol": symbol,
                "score": _num(row.get("score")),
                "grade": row.get("grade"),
                "rs_rating": _num(row.get("rs_rating")),
                "phase2": row.get("phase2"),
            }
        )
        if len(output) >= limit:
            break
    return output


def build_us_stock_context(source_root: Path) -> dict:
    dashboard = _read_json(source_root / "docs" / "dashboard_data.json")
    performance = _read_json(source_root / "docs" / "performance_data.json")
    hub = _read_json(source_root / "data" / "trading_hub_context.json")

    market = {
        key: _num(value)
        for key, value in (dashboard.get("market") or {}).items()
        if key in {"SPY", "QQQ", "SMH", "VIX", "TLT", "HYG", "IWM"}
    }
    overview = dashboard.get("overview") or {}
    strategy = dashboard.get("strategy") or {}
    divergence = strategy.get("divergence") or {}

    rows = []
    rows.extend(_symbol_rows(dashboard.get("highlights") or [], limit=10))
    rows.extend(_symbol_rows(dashboard.get("top10") or [], limit=10))
    rows.extend(_symbol_rows(dashboard.get("watchlist") or [], limit=10))
    deduped = {row["symbol"]: row for row in rows}

    status = "ok" if dashboard else "missing"
    return {
        "status": status,
        "source": source_root.name or "us-stock-ai",
        "generated_at": _now(),
        "source_generated_at": dashboard.get("generated_at"),
        "market": market,
        "overview": {
            "total_scored": overview.get("total_scored"),
            "grade_S": overview.get("grade_S"),
            "grade_A": overview.get("grade_A"),
            "grade_B": overview.get("grade_B"),
            "grade_C": overview.get("grade_C"),
            "grade_D": overview.get("grade_D"),
        },
        "regime": {
            "allow_new_entries": (strategy.get("regime") or {}).get("allow_new_entries"),
            "breadth_phase2_pct": _num((strategy.get("regime") or {}).get("breadth_phase2_pct")),
        },
        "divergence": {
            "n_compared": divergence.get("n_compared"),
            "avg_gap": _num(divergence.get("avg_gap")),
            "missed_strong": _symbol_rows(divergence.get("missed_strong") or [], limit=12),
        },
        "candidates": list(deduped.values())[:20],
        "performance": performance.get("stats") or {},
        "knowledge_rows": hub.get("used_count") or hub.get("count") or 0,
    }


def write_context(source_root: Path, output: Path) -> dict:
    context = build_us_stock_context(source_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    return context


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a compact US-stock context for Taiwan stock AI.")
    parser.add_argument("--source-root", default=str(DEFAULT_US_ROOT))
    parser.add_argument("--output", default=str(ROOT / "data" / "us_stock_context.json"))
    args = parser.parse_args()

    context = write_context(Path(args.source_root), Path(args.output))
    print(
        "us_stock_context "
        f"status={context['status']} "
        f"source_generated_at={context.get('source_generated_at')} "
        f"candidates={len(context.get('candidates') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
