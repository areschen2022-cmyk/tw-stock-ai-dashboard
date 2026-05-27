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
