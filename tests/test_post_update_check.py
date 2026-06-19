from __future__ import annotations

import json
import sqlite3
from datetime import date

from scripts.post_update_check import run_check


def _write_json(path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _prepare_dashboard_files(root, *, include_weekly: bool = True) -> None:
    dashboard = root / "dashboard"
    dashboard.mkdir()
    for name in ["index.html", "performance.html", "potential.html", "weekly.html"]:
        (dashboard / name).write_text("<html></html>", encoding="utf-8")
    _write_json(
        dashboard / "dashboard_data.json",
        {
            "as_of": "2026-06-18",
            "summary": {"valid": 3},
            "rows": [{"stock_id": "2330"}],
            "action_lists": {"summary": {"chase": 1, "pullback": 0}},
            "data_quality": {"label_text": "high"},
            "ai_council": {"status": {"health": {"label": "stable"}}},
        },
    )
    _write_json(dashboard / "performance_data.json", {"stats": {"signals": 1}})
    _write_json(dashboard / "potential_data.json", {"stats": {"signals": 1}})
    _write_json(dashboard / "debug_data.json", {"traceability": {"diagnosis": []}})
    if include_weekly:
        _write_json(
            dashboard / "weekly_data.json",
            {
                "as_of": "2026-06-18",
                "data_updates": [
                    {"dataset": "institutional_flow", "source_date": "2026-06-18", "status": "ok"},
                    {"dataset": "tdcc_retail_holders", "source_date": "2026-06-18", "status": "ok"},
                ],
            },
        )


def _prepare_db(root) -> None:
    data = root / "data"
    data.mkdir()
    with sqlite3.connect(data / "tw_stock_ai.sqlite3") as conn:
        conn.execute("CREATE TABLE daily_scores (as_of_date TEXT)")
        conn.execute("CREATE TABLE traceability_runs (run_date TEXT)")
        conn.execute(
            """
            CREATE TABLE data_update_log (
                update_date TEXT, dataset TEXT, status TEXT, row_count INTEGER,
                source_date TEXT, message TEXT, run_id TEXT, created_at TEXT
            )
            """
        )
        conn.execute("INSERT INTO daily_scores VALUES ('2026-06-18')")
        conn.execute("INSERT INTO traceability_runs VALUES ('2026-06-18')")
        conn.execute(
            "INSERT INTO data_update_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (date.today().isoformat(), "institutional_flow", "ok", 3, "2026-06-18", "", "", ""),
        )
        conn.execute(
            "INSERT INTO data_update_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (date.today().isoformat(), "tdcc_retail_holders", "ok", 3992, "2026-06-18", "", "", ""),
        )


def test_post_update_check_passes_with_complete_outputs(tmp_path) -> None:
    _prepare_dashboard_files(tmp_path)
    _prepare_db(tmp_path)

    result = run_check(tmp_path, tmp_path / "dashboard" / "post_update_check.json")

    assert result["status"] == "ok"
    assert result["counts"]["critical"] == 0
    assert (tmp_path / "dashboard" / "post_update_check.json").exists()


def test_post_update_check_reports_missing_weekly_json(tmp_path) -> None:
    _prepare_dashboard_files(tmp_path, include_weekly=False)
    _prepare_db(tmp_path)

    result = run_check(tmp_path, tmp_path / "dashboard" / "post_update_check.json")

    assert result["status"] == "bad"
    assert result["counts"]["critical"] >= 1
    assert any("weekly_data.json" in item["message"] for item in result["issues"])
