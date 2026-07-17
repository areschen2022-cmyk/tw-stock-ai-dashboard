from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parent.parent
ROUTES_FILE = ROOT / "config" / "cloud_skill_routes.json"
METRICS_FILE = ROOT / "config" / "metric_catalog.json"
OUTPUT_FILE = ROOT / "dashboard" / "cloud_skill_routes_status.json"


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _path_status(root: Path, path_text: str) -> dict:
    if path_text == "dashboard/cloud_skill_routes_status.json":
        return {
            "path": path_text,
            "exists": True,
            "kind": "generated_by_this_check",
        }
    path = root / path_text
    return {
        "path": path_text,
        "exists": path.exists(),
        "kind": "dir" if path.is_dir() else "file" if path.is_file() else "missing",
    }


def check_routes(root: Path = ROOT) -> dict:
    routes_payload = _read_json(root / "config" / "cloud_skill_routes.json")
    metrics_payload = _read_json(root / "config" / "metric_catalog.json")

    issues: list[dict] = []
    route_results: list[dict] = []
    for route in routes_payload.get("routes", []):
        implemented = [_path_status(root, item) for item in route.get("implemented_by", [])]
        outputs = [_path_status(root, item) for item in route.get("outputs", [])]
        missing_impl = [item["path"] for item in implemented if not item["exists"]]
        missing_outputs = [item["path"] for item in outputs if not item["exists"]]

        if missing_impl:
            issues.append(
                {
                    "severity": "critical",
                    "skill": route.get("skill"),
                    "message": f"Missing implementation files: {', '.join(missing_impl)}",
                }
            )
        if route.get("cloud_status") == "active" and missing_outputs:
            issues.append(
                {
                    "severity": "warning",
                    "skill": route.get("skill"),
                    "message": f"Missing latest output files: {', '.join(missing_outputs)}",
                }
            )

        route_results.append(
            {
                "skill": route.get("skill"),
                "cloud_status": route.get("cloud_status"),
                "decision_use": route.get("decision_use"),
                "cloud_jobs": route.get("cloud_jobs", []),
                "implemented_by": implemented,
                "outputs": outputs,
                "quality_gate": route.get("quality_gate"),
            }
        )

    metrics = metrics_payload.get("metrics", [])
    required_metric_fields = {"name", "grain", "source_files", "calculation", "business_use", "caveats"}
    for metric in metrics:
        missing = sorted(required_metric_fields - set(metric))
        if missing:
            issues.append(
                {
                    "severity": "critical",
                    "metric": metric.get("name", "unknown"),
                    "message": f"Metric definition missing fields: {', '.join(missing)}",
                }
            )

    status = "bad" if any(item["severity"] == "critical" for item in issues) else "warn" if issues else "ok"
    return {
        "generated_at": _now(),
        "status": status,
        "summary": {
            "routes": len(route_results),
            "active_routes": sum(1 for item in route_results if item.get("cloud_status") == "active"),
            "delegated_routes": sum(1 for item in route_results if item.get("cloud_status") == "delegated"),
            "metrics": len(metrics),
        },
        "routes": route_results,
        "metrics": metrics,
        "issues": issues,
        "note": "Codex skills are not executed directly in GitHub Actions. These routes make their decision logic reproducible through repo scripts and scheduled jobs.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate cloud-executable routes for locally installed trading skills.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    payload = check_routes(root)
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"cloud-skill-route-check status={payload['status']} "
        f"routes={payload['summary']['routes']} metrics={payload['summary']['metrics']} "
        f"output={output}"
    )
    for issue in payload["issues"]:
        print(f"[{issue['severity']}] {issue.get('skill') or issue.get('metric')}: {issue['message']}")
    return 1 if payload["status"] == "bad" else 0


if __name__ == "__main__":
    raise SystemExit(main())
