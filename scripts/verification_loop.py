from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _run(command: list[str], *, cwd: Path, timeout: int) -> dict:
    started = _now()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "started_at": started,
            "ended_at": _now(),
            "exit_code": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "started_at": started,
            "ended_at": _now(),
            "exit_code": None,
            "ok": False,
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": f"Timed out after {timeout}s",
        }


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _check_dashboard_sync(root: Path) -> dict:
    names = [
        "dashboard_data.json",
        "performance_data.json",
        "potential_data.json",
        "weekly_data.json",
        "theme_history.json",
        "debug_data.json",
        "backtest_review.json",
        "post_update_check.json",
        "research_source_review.json",
    ]
    mismatches = []
    missing = []
    for name in names:
        dash = root / "dashboard" / name
        docs = root / "docs" / name
        if not dash.exists() or not docs.exists():
            missing.append(name)
            continue
        if dash.read_bytes() != docs.read_bytes():
            mismatches.append(name)
    return {
        "ok": not mismatches and not missing,
        "missing": missing,
        "mismatches": mismatches,
    }


def _sync_post_update_check(root: Path) -> None:
    source = root / "dashboard" / "post_update_check.json"
    target = root / "docs" / "post_update_check.json"
    if source.exists() and target.parent.exists():
        target.write_bytes(source.read_bytes())


def _check_action_freshness(root: Path) -> dict:
    dashboard = _read_json(root / "dashboard" / "dashboard_data.json")
    post = _read_json(root / "dashboard" / "post_update_check.json")
    return {
        "ok": bool(dashboard.get("as_of")) and (post.get("status") in {"ok", "warn"}),
        "as_of": dashboard.get("as_of"),
        "post_update_status": post.get("status"),
        "post_update_counts": post.get("counts") or {},
    }


def _check_knowledge_hub(root: Path, output: str | None) -> dict:
    command = [
        sys.executable,
        "scripts/export_learning_to_knowledge_hub.py",
        "--skip-missing",
    ]
    if output:
        command.extend(["--output", output])
    result = _run(command, cwd=root, timeout=60)
    return {
        "ok": result["ok"],
        "command": result["command"],
        "exit_code": result["exit_code"],
        "stdout_tail": result["stdout_tail"],
        "stderr_tail": result["stderr_tail"],
    }


def _check_github_runs(root: Path, repo: str) -> dict:
    result = _run(["gh", "run", "list", "--repo", repo, "--limit", "5"], cwd=root, timeout=30)
    if not result["ok"]:
        return {
            "ok": False,
            "available": False,
            "exit_code": result["exit_code"],
            "stderr_tail": result["stderr_tail"],
        }
    failed_lines = [
        line
        for line in result["stdout_tail"].splitlines()
        if line.startswith("completed\tfailure") or line.startswith("completed\tcancelled")
    ]
    return {
        "ok": not failed_lines,
        "available": True,
        "failed_recent_runs": failed_lines,
        "stdout_tail": result["stdout_tail"],
    }


def run_loop(
    root: Path,
    *,
    output: Path,
    run_tests: bool,
    with_github: bool,
    repo: str,
    knowledge_output: str | None,
    skip_dashboard_sync: bool = False,
) -> dict:
    checks: dict[str, dict] = {}

    checks["compile"] = _run([sys.executable, "-m", "compileall", "src", "tests", "main.py", "scripts"], cwd=root, timeout=120)
    if run_tests:
        checks["tests"] = _run([sys.executable, "-m", "pytest", "-q"], cwd=root, timeout=180)

    checks["post_update"] = _run([sys.executable, "scripts/post_update_check.py"], cwd=root, timeout=120)
    if not skip_dashboard_sync:
        _sync_post_update_check(root)
        checks["dashboard_sync"] = _check_dashboard_sync(root)
    checks["freshness"] = _check_action_freshness(root)
    checks["knowledge_hub"] = _check_knowledge_hub(root, knowledge_output)
    if with_github:
        checks["github_runs"] = _check_github_runs(root, repo)

    ok = all(item.get("ok", False) for item in checks.values())
    report = {
        "generated_at": _now(),
        "status": "ok" if ok else "bad",
        "checks": checks,
        "next_actions": _next_actions(checks),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _next_actions(checks: dict[str, dict]) -> list[str]:
    actions = []
    if not checks.get("compile", {}).get("ok"):
        actions.append("Fix Python syntax/import errors before changing behavior.")
    if "tests" in checks and not checks["tests"].get("ok"):
        actions.append("Inspect pytest failures and add a regression test for the failing path.")
    if not checks.get("post_update", {}).get("ok"):
        actions.append("Open dashboard/post_update_check.json and fix critical dashboard/data issues.")
    sync = checks.get("dashboard_sync", {})
    if sync and not sync.get("ok"):
        actions.append("Sync dashboard JSON/HTML outputs into docs before deploying Pages.")
    if not checks.get("knowledge_hub", {}).get("ok"):
        actions.append("Check trading knowledge hub path and export_learning_to_knowledge_hub.py output.")
    if not actions:
        actions.append("Next optimization: feed knowledge-hub findings back into candidate scoring as internal-only context.")
    return actions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local verification loop after dashboard/code updates.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dashboard/verification_loop.json")
    parser.add_argument("--run-tests", action="store_true", help="Run pytest as part of the loop.")
    parser.add_argument("--with-github", action="store_true", help="Check recent GitHub Actions runs with gh.")
    parser.add_argument("--repo", default="areschen2022-cmyk/tw-stock-ai-dashboard")
    parser.add_argument("--knowledge-output", default=None, help="Optional knowledge hub JSONL output path.")
    parser.add_argument("--skip-dashboard-sync", action="store_true", help="Skip dashboard/docs sync check when docs copy has not happened yet.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    report = run_loop(
        root,
        output=output,
        run_tests=args.run_tests,
        with_github=args.with_github,
        repo=args.repo,
        knowledge_output=args.knowledge_output,
        skip_dashboard_sync=args.skip_dashboard_sync,
    )
    print(f"verification-loop status={report['status']} output={output}")
    for name, check in report["checks"].items():
        print(f"[{'ok' if check.get('ok') else 'bad'}] {name}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
