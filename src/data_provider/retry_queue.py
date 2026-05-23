from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path
from typing import Any


def run_retry_queue(
    provider: Any,
    store: Any,
    *,
    as_of: date,
    lookback_start: date,
    limit: int = 8,
) -> dict:
    """Retry recoverable data gaps and persist the outcome."""
    attempted: list[dict] = []
    for item in store.pending_data_retries(limit=limit):
        dataset = str(item.get("dataset") or "")
        data_id = str(item.get("data_id") or "")
        period = str(item.get("period") or "")
        ok = False
        error = ""
        try:
            _purge_retry_cache(provider, dataset, data_id, period)
            if dataset in {"STOCK_DAY", "stock_prices"}:
                start, end = _retry_range(period, as_of, lookback_start)
                frame = provider.stock_prices(data_id, start, end)
                ok = frame is not None and not frame.empty
                if not ok:
                    error = "empty_after_retry"
            else:
                error = "unsupported_dataset"
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            error = exc.__class__.__name__
        store.record_retry_attempt(dataset, data_id, period, ok=ok, last_error=error)
        attempted.append({**item, "ok": ok, "last_error": error})

    summary = store.retry_queue_summary()
    summary["attempted"] = attempted
    return summary


def _retry_range(period: str, as_of: date, lookback_start: date) -> tuple[date, date]:
    if len(period) == 7 and period[4] == "-":
        year, month = (int(part) for part in period.split("-", 1))
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1)
        end = min(date(year, month, last_day), as_of)
        return start, end
    return lookback_start, as_of


def _purge_retry_cache(provider: Any, dataset: str, data_id: str, period: str) -> None:
    cache_path_fn = getattr(provider, "_cache_path", None)
    if not callable(cache_path_fn) or not period:
        return
    path = cache_path_fn("STOCK_DAY" if dataset == "stock_prices" else dataset, data_id, period)
    if not isinstance(path, Path) or not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        pass
