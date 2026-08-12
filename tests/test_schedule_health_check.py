from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from scripts.schedule_health_check import TAIPEI, run_check


def _write(path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _prepare_project(root, *, delivered: bool = True, create_db: bool = True) -> None:
    _write(
        root / ".github" / "workflows" / "daily.yml",
        """
name: Taiwan Stock AI Daily
on:
  schedule:
    - cron: "30 20 * * 0-4"
    - cron: "0 21 * * 0-4"
    - cron: "20 23 * * 0-4"
    - cron: "35 23 * * 0-4"
    - cron: "50 23 * * 0-4"
""",
    )
    _write(
        root / "cloudflare-worker" / "wrangler.toml",
        """
name = "tw-stock-ai-scheduler"
main = "worker.js"
[triggers]
crons = ["5 0 * * MON-FRI"]
""",
    )
    for name in ["dashboard_data.json", "performance_data.json", "potential_data.json", "weekly_data.json"]:
        payload = {"as_of": "2026-06-18", "generated_at": "2026-06-18T07:00:00+08:00"}
        if name == "dashboard_data.json":
            payload["summary"] = {"valid": 3}
        _write(root / "dashboard" / name, payload)
    if not create_db:
        return
    data_dir = root / "data"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "tw_stock_ai.sqlite3") as conn:
        conn.execute(
            """
            CREATE TABLE delivery_log (
                channel TEXT NOT NULL,
                delivery_date TEXT NOT NULL,
                message_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'sent',
                PRIMARY KEY (channel, delivery_date, message_type)
            )
            """
        )
        if delivered:
            conn.execute(
                "INSERT INTO delivery_log VALUES (?, ?, ?, ?, ?, ?)",
                ("telegram", "2026-06-18", "morning_report", "2026-06-18T08:05:10+08:00", "run-1", "sent"),
            )


def _prepare_legacy_delivery_db(root) -> None:
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    with sqlite3.connect(data_dir / "tw_stock_ai.sqlite3") as conn:
        conn.execute(
            """
            CREATE TABLE delivery_log (
                channel TEXT NOT NULL,
                delivery_date TEXT NOT NULL,
                message_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (channel, delivery_date, message_type)
            )
            """
        )
        conn.execute(
            "INSERT INTO delivery_log VALUES (?, ?, ?, ?, ?)",
            ("telegram", "2026-06-18", "morning_report", "2026-06-18T08:05:10+08:00", "legacy-run"),
        )


def test_schedule_health_passes_with_expected_schedules_and_delivery(tmp_path) -> None:
    _prepare_project(tmp_path, delivered=True)

    result = run_check(
        tmp_path,
        tmp_path / "dashboard" / "schedule_health.json",
        now=datetime(2026, 6, 18, 8, 31, tzinfo=TAIPEI),
        strict_telegram=True,
    )

    assert result["status"] == "ok"
    assert result["counts"]["critical"] == 0
    assert result["telegram_delivery"]["delivered"] is True


def test_schedule_health_flags_missing_delivery_after_cutoff(tmp_path) -> None:
    _prepare_project(tmp_path, delivered=False)

    result = run_check(
        tmp_path,
        tmp_path / "dashboard" / "schedule_health.json",
        now=datetime(2026, 6, 18, 8, 31, tzinfo=TAIPEI),
        strict_telegram=True,
    )

    assert result["status"] == "bad"
    assert any(item["area"] == "telegram_delivery" for item in result["issues"])


def test_schedule_health_warns_when_github_owns_cloudflare_slot(tmp_path) -> None:
    _prepare_project(tmp_path, delivered=True)
    workflow = (tmp_path / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    _write(tmp_path / ".github" / "workflows" / "daily.yml", workflow + '\n    - cron: "5 0 * * MON-FRI"\n')

    result = run_check(
        tmp_path,
        tmp_path / "dashboard" / "schedule_health.json",
        now=datetime(2026, 6, 18, 7, 0, tzinfo=TAIPEI),
    )

    assert result["status"] == "warn"
    assert any("08:05" in item["message"] for item in result["issues"])


def test_schedule_health_accepts_legacy_delivery_log_without_status(tmp_path) -> None:
    _prepare_project(tmp_path, create_db=False)
    _prepare_legacy_delivery_db(tmp_path)

    result = run_check(
        tmp_path,
        tmp_path / "dashboard" / "schedule_health.json",
        now=datetime(2026, 6, 18, 8, 31, tzinfo=TAIPEI),
        strict_telegram=True,
    )

    assert result["status"] == "ok"
    assert result["telegram_delivery"]["status"] == "sent"
    assert result["telegram_delivery"]["run_id"] == "legacy-run"
