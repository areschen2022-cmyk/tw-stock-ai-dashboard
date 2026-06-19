from __future__ import annotations

import sqlite3
from datetime import date

from src.storage.sqlite_store import SQLiteStore


def test_delivery_log_records_once(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    delivery_date = date(2026, 5, 21)

    assert not store.has_delivered_today("telegram", delivery_date, "morning_report")
    pending = store.delivery_status("telegram", delivery_date, "morning_report")
    assert pending["delivered"] is False
    assert pending["delivery_date"] == delivery_date.isoformat()

    store.record_delivery("telegram", delivery_date, "morning_report", run_id="run-1")
    store.record_delivery("telegram", delivery_date, "morning_report", run_id="run-2")

    assert store.has_delivered_today("telegram", delivery_date, "morning_report")
    delivered = store.delivery_status("telegram", delivery_date, "morning_report")
    assert delivered["delivered"] is True
    assert delivered["run_id"] == "run-1"
    with sqlite3.connect(tmp_path / "test.sqlite3") as conn:
        rows = conn.execute(
            "SELECT run_id FROM delivery_log WHERE channel = ? AND delivery_date = ? AND message_type = ?",
            ("telegram", delivery_date.isoformat(), "morning_report"),
        ).fetchall()

    assert rows == [("run-1",)]


def test_data_update_log_records_latest_status(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    update_date = date(2026, 6, 19)

    store.record_data_update(
        "tdcc_retail_holders",
        update_date,
        status="failed",
        message="timeout",
        run_id="run-1",
    )
    store.record_data_update(
        "tdcc_retail_holders",
        update_date,
        status="ok",
        row_count=3992,
        source_date=date(2026, 6, 18),
        message="3 divergence signals",
        run_id="run-2",
    )

    updates = store.latest_data_updates(limit=5)

    assert updates[0]["dataset"] == "tdcc_retail_holders"
    assert updates[0]["status"] == "ok"
    assert updates[0]["row_count"] == 3992
    assert updates[0]["source_date"] == "2026-06-18"
    assert updates[0]["run_id"] == "run-2"
