from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.cloud_skill_route_check import check_routes


def _copy_project_bits(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    for name in ["config", "scripts", "src"]:
        source = root / name
        target = tmp_path / name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    dashboard = tmp_path / "dashboard"
    reports = tmp_path / "reports"
    data = tmp_path / "data"
    dashboard.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    for name in [
        "dashboard_data.json",
        "theme_history.json",
        "post_update_check.json",
        "potential_data.json",
    ]:
        (dashboard / name).write_text("{}", encoding="utf-8")
    (reports / "deepseek_strategy_review.json").write_text("{}", encoding="utf-8")
    (data / "us_stock_context.json").write_text("{}", encoding="utf-8")


def test_cloud_skill_route_check_maps_installed_skills_to_cloud_routes(tmp_path: Path) -> None:
    _copy_project_bits(tmp_path)

    payload = check_routes(tmp_path)

    assert payload["status"] == "ok"
    assert payload["summary"]["routes"] == 3
    assert payload["summary"]["active_routes"] == 2
    assert {row["skill"] for row in payload["routes"]} == {
        "market-research",
        "semantic-model-builder",
        "earnings-trade-analyzer",
    }
    assert payload["summary"]["metrics"] >= 5


def test_cloud_skill_route_check_reports_missing_implementation(tmp_path: Path) -> None:
    _copy_project_bits(tmp_path)
    routes_path = tmp_path / "config" / "cloud_skill_routes.json"
    payload = json.loads(routes_path.read_text(encoding="utf-8"))
    payload["routes"][0]["implemented_by"].append("missing/file.py")
    routes_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = check_routes(tmp_path)

    assert result["status"] == "bad"
    assert any(issue["severity"] == "critical" for issue in result["issues"])
