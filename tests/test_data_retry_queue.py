from __future__ import annotations

from pathlib import Path

from src.data_provider.retry_queue import _purge_retry_cache
from src.storage.sqlite_store import SQLiteStore


class MonthlyCacheProvider:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _cache_path(self, dataset: str, data_id: str, year: int, month: int, current: bool = False) -> Path:
        suffix = f"{year}-{month:02d}-current" if current else f"{year}-{month:02d}"
        return self.root / f"{dataset}__{data_id}__{suffix}.json"


class DailyCacheProvider:
    def __init__(self, root: Path, fallback=None) -> None:
        self.root = root
        self.fallback = fallback

    def _cache_path(self, dataset: str, data_id: str, key: str) -> Path:
        return self.root / f"{dataset}__{data_id}__{key}.json"


def test_data_retry_queue_enqueues_and_records_success(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "retry.sqlite3")

    queued = store.enqueue_data_retry(
        [
            {"type": "empty", "dataset": "STOCK_DAY", "data_id": "2330", "period": "2026-05", "reason": "html"},
            {"type": "quota", "dataset": "STOCK_DAY", "data_id": "2317", "period": "2026-05", "reason": "quota"},
        ]
    )

    assert queued == 1
    pending = store.pending_data_retries()
    assert len(pending) == 1
    assert pending[0]["dataset"] == "STOCK_DAY"

    store.record_retry_attempt("STOCK_DAY", "2330", "2026-05", ok=True)
    summary = store.retry_queue_summary()

    assert summary["pending"] == 0
    assert summary["recovered"] == 1
    assert summary["items"][0]["status"] == "recovered"


def test_data_retry_queue_does_not_enqueue_fallback_recovered_items(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "retry.sqlite3")

    queued = store.enqueue_data_retry(
        [{"type": "fallback", "dataset": "STOCK_DAY", "data_id": "2330", "period": "2026-05"}]
    )
    summary = store.retry_queue_summary()

    assert queued == 0
    assert summary["pending"] == 0


def test_data_retry_queue_marks_failed_after_three_attempts(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "retry.sqlite3")
    store.enqueue_data_retry(
        [{"type": "error", "dataset": "STOCK_DAY", "data_id": "2330", "period": "2026-05", "reason": "fetch_failed"}]
    )

    for _ in range(3):
        store.record_retry_attempt("STOCK_DAY", "2330", "2026-05", ok=False, last_error="empty_after_retry")

    summary = store.retry_queue_summary()
    assert summary["failed"] == 1
    assert summary["items"][0]["last_error"] == "empty_after_retry"


def test_purge_retry_cache_supports_daily_and_monthly_cache_shapes(tmp_path) -> None:
    fallback = MonthlyCacheProvider(tmp_path)
    provider = DailyCacheProvider(tmp_path, fallback=fallback)
    paths = [
        provider._cache_path("STOCK_DAY", "2330", "2026-05"),
        fallback._cache_path("TaiwanStockPrice", "2330", 2026, 5),
        fallback._cache_path("TaiwanStockPrice", "2330", 2026, 5, current=True),
    ]
    for path in paths:
        path.write_text("[]", encoding="utf-8")

    _purge_retry_cache(provider, "STOCK_DAY", "2330", "2026-05")

    assert all(not path.exists() for path in paths)
