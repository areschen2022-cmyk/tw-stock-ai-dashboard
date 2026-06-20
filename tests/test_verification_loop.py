from __future__ import annotations

import json

from scripts.verification_loop import _check_dashboard_sync, _check_action_freshness


def _write(path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_dashboard_sync_detects_mismatch(tmp_path) -> None:
    for folder in ["dashboard", "docs"]:
        for name in [
            "dashboard_data.json",
            "performance_data.json",
            "potential_data.json",
            "weekly_data.json",
            "theme_history.json",
            "debug_data.json",
            "post_update_check.json",
        ]:
            _write(tmp_path / folder / name, {"name": name})

    _write(tmp_path / "docs" / "weekly_data.json", {"name": "different"})

    result = _check_dashboard_sync(tmp_path)

    assert result["ok"] is False
    assert result["mismatches"] == ["weekly_data.json"]


def test_action_freshness_reads_dashboard_and_post_update(tmp_path) -> None:
    _write(tmp_path / "dashboard" / "dashboard_data.json", {"as_of": "2026-06-18"})
    _write(tmp_path / "dashboard" / "post_update_check.json", {"status": "ok", "counts": {"critical": 0}})

    result = _check_action_freshness(tmp_path)

    assert result["ok"] is True
    assert result["as_of"] == "2026-06-18"
    assert result["post_update_status"] == "ok"
