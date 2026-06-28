from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_HUB_FILE = Path("C:/Users/User/trading_knowledge_hub/data/knowledge_points.jsonl")

MOJIBAKE_MARKERS = [
    chr(0x5697),
    chr(0x875B),
    chr(0x7507),
    chr(0x7625),
    chr(0x929D),
    chr(0x6470),
    chr(0x61AD),
    chr(0x876C),
    chr(0x769C),
    "?" + chr(0x5557),
    "?" + chr(0x82B8),
    "?" + chr(0x822A),
    "?" + chr(0x5238),
    "?" + chr(0x7946),
    "?" + chr(0xF697),
]

SCAN_DIRS = [
    ".github",
    "docs",
    "scripts",
    "src",
    "tests",
]
SCAN_FILES = [
    "AGENTS.md",
    "README.md",
    "config.yaml",
    "main.py",
]
SCAN_SUFFIXES = {".bat", ".html", ".md", ".py", ".yaml", ".yml"}


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
            "stdout_tail": proc.stdout[-5000:],
            "stderr_tail": proc.stderr[-5000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "started_at": started,
            "ended_at": _now(),
            "exit_code": None,
            "ok": False,
            "stdout_tail": (exc.stdout or "")[-5000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": f"Timed out after {timeout}s",
        }


def _iter_scan_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for name in SCAN_FILES:
        path = root / name
        if path.exists():
            paths.append(path)
    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
                paths.append(path)
    return sorted(set(paths))


def scan_mojibake(root: Path) -> dict:
    hits: list[dict] = []
    for path in _iter_scan_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            hits.append(
                {
                    "path": str(path.relative_to(root)),
                    "line": 0,
                    "marker": "decode_error",
                    "snippet": str(exc),
                }
            )
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            marker = next((item for item in MOJIBAKE_MARKERS if item in line), None)
            if marker:
                hits.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": line_no,
                        "marker": marker,
                        "snippet": line.strip()[:180],
                    }
                )
    return {"ok": not hits, "hits": hits[:80], "hit_count": len(hits)}


def _knowledge_output_arg(path: Path | None) -> list[str]:
    if path is None:
        return []
    return ["--knowledge-output", str(path)]


def run_finalize(
    root: Path,
    *,
    output: Path,
    hub_file: Path | None,
    skip_tests: bool,
) -> dict:
    checks: dict[str, dict] = {}

    checks["compile"] = _run(
        [sys.executable, "-m", "compileall", "src", "tests", "main.py", "scripts"],
        cwd=root,
        timeout=120,
    )
    if not skip_tests:
        checks["tests"] = _run([sys.executable, "-m", "pytest", "-q"], cwd=root, timeout=240)

    checks["post_update"] = _run([sys.executable, "scripts/post_update_check.py"], cwd=root, timeout=120)
    checks["mojibake_scan"] = scan_mojibake(root)

    export_command = [sys.executable, "scripts/export_learning_to_knowledge_hub.py"]
    if hub_file is not None:
        export_command.extend(["--output", str(hub_file)])
    checks["knowledge_export"] = _run(export_command, cwd=root, timeout=90)

    verification_command = [
        sys.executable,
        "scripts/verification_loop.py",
        "--skip-dashboard-sync",
    ]
    verification_command.extend(_knowledge_output_arg(hub_file))
    checks["verification_loop"] = _run(verification_command, cwd=root, timeout=180)

    ok = all(item.get("ok", False) for item in checks.values())
    report = {
        "generated_at": _now(),
        "status": "ok" if ok else "bad",
        "hub_file": str(hub_file) if hub_file is not None else "auto",
        "checks": checks,
        "next_actions": _next_actions(checks),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _next_actions(checks: dict[str, dict]) -> list[str]:
    actions: list[str] = []
    if not checks.get("compile", {}).get("ok"):
        actions.append("修正 Python 語法或 import 錯誤。")
    if "tests" in checks and not checks["tests"].get("ok"):
        actions.append("查看 pytest 失敗項目，修正後重跑 post_optimization_finalize。")
    if not checks.get("post_update", {}).get("ok"):
        actions.append("打開 dashboard/post_update_check.json，先處理 critical 或資料銜接問題。")
    if not checks.get("mojibake_scan", {}).get("ok"):
        actions.append("修正 mojibake_scan 列出的亂碼檔案。")
    if not checks.get("knowledge_export", {}).get("ok"):
        actions.append("檢查交易智慧庫路徑或 export_learning_to_knowledge_hub.py。")
    if not checks.get("verification_loop", {}).get("ok"):
        actions.append("查看 dashboard/verification_loop.json，修正未通過的收尾檢查。")
    if not actions:
        actions.append("下一步可把本次新經驗納入選股規則，但仍需累積樣本再調整權重。")
    return actions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the required final checks after every tw-stock-ai optimization.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dashboard/post_optimization_finalize.json")
    parser.add_argument("--hub-file", default=str(DEFAULT_HUB_FILE))
    parser.add_argument("--auto-hub", action="store_true", help="Let export script choose the knowledge hub path.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest only for very small documentation-only edits.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    hub_file = None if args.auto_hub else Path(args.hub_file)
    report = run_finalize(root, output=output, hub_file=hub_file, skip_tests=args.skip_tests)
    print(f"post-optimization-finalize status={report['status']} output={output}")
    for name, check in report["checks"].items():
        print(f"[{'ok' if check.get('ok') else 'bad'}] {name}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
