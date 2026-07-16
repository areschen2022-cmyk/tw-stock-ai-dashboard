from __future__ import annotations

import json
from pathlib import Path

from scripts.deepseek_strategy_review import run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_strategy_review_runs_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _write_json(
        tmp_path / "dashboard" / "dashboard_data.json",
        {"as_of": "2026-07-16", "rows": [{"stock_id": "2330"}]},
    )
    _write_json(
        tmp_path / "dashboard" / "performance_data.json",
        {
            "as_of": "2026-07-16",
            "stats": {"signals": 10, "completed": 10, "win_rate_5d": 40.0},
            "entry_analysis": {
                "triggered": {"count": 25, "win_rate_5d": 30.0, "avg_return_5d": -1.0},
                "not_triggered": {"count": 25, "win_rate_5d": 60.0, "avg_return_5d": 2.0},
            },
            "theme_stats": [
                {
                    "label": "AI伺服器",
                    "signals": 30,
                    "completed": 25,
                    "win_rate_5d": 35.0,
                    "avg_return_5d": -2.0,
                }
            ],
        },
    )
    _write_json(
        tmp_path / "dashboard" / "research_backtest_5y.json",
        {
            "summary": {
                "overall_5d": {"signals": 100, "completed": 100, "win_rate": 43.0},
                "by_signal_type": [],
            },
            "method": {"limitations": ["research only"]},
        },
    )
    _write_json(tmp_path / "dashboard" / "backtest_review.json", {"status": "ok"})
    _write_json(tmp_path / "dashboard" / "potential_data.json", {"potential_radar": {}})

    payload = run(tmp_path, allow_api=True, max_tokens=100, timeout=1)

    assert payload["deepseek_review"]["status"] == "skipped"
    assert len(payload["local_review"]["precision_improvements"]) == 5
    assert payload["local_review"]["precision_gate_readiness"][0]["status"] == "ready"
    assert (tmp_path / "reports" / "deepseek_strategy_review.json").exists()
    assert (tmp_path / "reports" / "deepseek_strategy_review.md").exists()


def test_strategy_review_gating_terms_are_not_mojibake(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _write_json(tmp_path / "dashboard" / "dashboard_data.json", {"as_of": "2026-07-16", "rows": []})
    _write_json(tmp_path / "dashboard" / "performance_data.json", {})
    _write_json(tmp_path / "dashboard" / "research_backtest_5y.json", {})

    payload = run(tmp_path, allow_api=False, max_tokens=100, timeout=1)
    rules = "\n".join(payload["local_review"]["gating_rules"])
    report = (tmp_path / "reports" / "deepseek_strategy_review.md").read_text(encoding="utf-8")

    assert "可追" in rules
    assert "distribution risk" in rules
    assert "Precision Gate Readiness" in report
    bad_samples = [
        "?" + "\u822a" + "\u856d",
        "\u8751\uf424",
        "\u929d\u9903",
        "\u61bf\uf5fb",
    ]
    for bad in bad_samples:
        assert bad not in rules
        assert bad not in report
