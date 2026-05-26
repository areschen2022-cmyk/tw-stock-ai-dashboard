from __future__ import annotations

from datetime import date

from src.report.retail_divergence import (
    SIGNAL_CLEAN,
    SIGNAL_NEUTRAL,
    SIGNAL_OVERHEATED,
    classify_retail_divergence,
    enrich_retail_records,
    summarize_retail_divergence,
)
from src.storage.sqlite_store import SQLiteStore


def test_classify_retail_divergence() -> None:
    assert classify_retail_divergence(holder_change_pct=-4.2, price_change_pct=0.5, volume=1800)[0] == SIGNAL_CLEAN
    assert classify_retail_divergence(holder_change_pct=4.1, price_change_pct=0.2, volume=2500)[0] == SIGNAL_OVERHEATED
    assert classify_retail_divergence(holder_change_pct=-4.1, price_change_pct=0.5, volume=200)[0] == SIGNAL_NEUTRAL
    assert classify_retail_divergence(holder_change_pct=1.0, price_change_pct=3.0, volume=2000)[0] == SIGNAL_NEUTRAL


def test_summarize_retail_divergence_orders_buckets() -> None:
    rows = enrich_retail_records(
        [
            {"stock_id": "1111", "name": "乾淨一", "holder_change_pct": -3.2, "price_change_pct": 0.0, "volume": 1200},
            {"stock_id": "2222", "name": "過熱一", "holder_change_pct": 5.0, "price_change_pct": 0.2, "volume": 2000},
            {"stock_id": "3333", "name": "乾淨二", "holder_change_pct": -6.0, "price_change_pct": -0.5, "volume": 1800},
        ]
    )

    summary = summarize_retail_divergence(rows)

    assert summary["summary"]["clean"] == 2
    assert summary["summary"]["overheated"] == 1
    assert summary["clean"][0]["stock_id"] == "3333"
    assert summary["overheated"][0]["stock_id"] == "2222"


def test_save_and_load_retail_holder_signals(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    week_date = date(2026, 5, 22)
    rows = enrich_retail_records(
        [
            {
                "stock_id": "2408",
                "name": "南亞科",
                "holder_count": 10000,
                "prev_holder_count": 10600,
                "holder_change": -600,
                "holder_change_pct": -5.7,
                "price_change_pct": 0.8,
                "volume": 3000,
            }
        ]
    )

    store.save_retail_holder_signals(rows, week_date)
    loaded = store.latest_retail_holder_signals()

    assert len(loaded) == 1
    assert loaded[0]["stock_id"] == "2408"
    assert loaded[0]["signal"] == SIGNAL_CLEAN
