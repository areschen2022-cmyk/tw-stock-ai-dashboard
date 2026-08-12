from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_REPO = "areschen2022-cmyk/tw-stock-ai-dashboard"
DEFAULT_WORKFLOW = "daily.yml"


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _run_gh(args: list[str], *, cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["gh", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _load_json(text: str, default):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def classify_failure(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ["syntaxerror", "unterminated string", "invalid syntax"]):
        return "syntax_error"
    if any(token in lower for token in ["modulenotfounderror", "importerror", "no module named"]):
        return "dependency_or_import"
    if any(token in lower for token in ["unauthorized", "401", "bad credentials", "secret", "token"]):
        return "secret_or_auth"
    if any(token in lower for token in ["push", "non-fast-forward", "fetch first", "failed to push"]):
        return "git_push_conflict"
    if any(token in lower for token in ["pages", "artifact", "deploy"]):
        return "pages_deploy"
    if any(token in lower for token in ["rate limit", "too many requests", "429", "limit exceeded"]):
        return "rate_limit"
    if any(token in lower for token in ["timeout", "timed out", "cancelled"]):
        return "timeout_or_cancelled"
    if any(token in lower for token in ["curl", "http", "connection", "dns", "network"]):
        return "network_or_source"
    return "unknown"


def _annotation_text(annotation: dict) -> str:
    parts = [
        annotation.get("title"),
        annotation.get("message"),
        annotation.get("raw_details"),
        annotation.get("path"),
    ]
    return " ".join(str(part) for part in parts if part)


def _compact_annotation(annotation: dict) -> dict:
    return {
        "level": annotation.get("annotation_level") or annotation.get("level"),
        "path": annotation.get("path"),
        "line": annotation.get("start_line") or annotation.get("line"),
        "title": annotation.get("title"),
        "message": str(annotation.get("message") or "")[:500],
        "category": classify_failure(_annotation_text(annotation)),
    }


def _run_text(row: dict, annotations: list[dict]) -> str:
    chunks = [row.get("displayTitle"), row.get("name"), row.get("conclusion"), row.get("status")]
    chunks.extend(_annotation_text(annotation) for annotation in annotations)
    return " ".join(str(chunk) for chunk in chunks if chunk)


def _fetch_run_detail(root: Path, repo: str, run_id: int) -> dict:
    fields = "databaseId,status,conclusion,createdAt,displayTitle,event,url,workflowName,annotations,jobs"
    code, stdout, stderr = _run_gh(["run", "view", str(run_id), "--repo", repo, "--json", fields], cwd=root)
    if code == 0:
        return _load_json(stdout, {})

    fallback_fields = "databaseId,status,conclusion,createdAt,displayTitle,event,url,workflowName,jobs"
    code, stdout, _ = _run_gh(["run", "view", str(run_id), "--repo", repo, "--json", fallback_fields], cwd=root)
    if code == 0:
        detail = _load_json(stdout, {})
        detail["annotations_unavailable"] = stderr[-500:]
        return detail
    return {"databaseId": run_id, "detail_error": stderr[-1000:]}


def _collect_annotations(detail: dict) -> list[dict]:
    annotations = []
    for annotation in detail.get("annotations") or []:
        annotations.append(annotation)
    for job in detail.get("jobs") or []:
        for annotation in job.get("annotations") or []:
            item = dict(annotation)
            item.setdefault("job_name", job.get("name"))
            annotations.append(item)
    return annotations


def build_failure_review(runs: list[dict], details: dict[int, dict]) -> dict:
    failures: list[dict] = []
    categories: dict[str, int] = {}

    for row in runs:
        run_id = int(row.get("databaseId") or row.get("run_id") or 0)
        detail = details.get(run_id, {})
        annotations = [_compact_annotation(item) for item in _collect_annotations(detail)]
        root_cause = classify_failure(_run_text(row | detail, annotations))
        categories[root_cause] = categories.get(root_cause, 0) + 1
        annotation_categories: dict[str, int] = {}
        for annotation in annotations:
            category = str(annotation.get("category") or "unknown")
            annotation_categories[category] = annotation_categories.get(category, 0) + 1
        failures.append(
            {
                "run_id": run_id,
                "workflow": row.get("workflowName") or detail.get("workflowName"),
                "display_title": row.get("displayTitle") or detail.get("displayTitle"),
                "status": row.get("status") or detail.get("status"),
                "conclusion": row.get("conclusion") or detail.get("conclusion"),
                "created_at": row.get("createdAt") or detail.get("createdAt"),
                "event": row.get("event") or detail.get("event"),
                "url": row.get("url") or detail.get("url"),
                "root_cause": root_cause,
                "annotation_count": len(annotations),
                "annotation_categories": annotation_categories,
            }
        )

    return {
        "status": "ok",
        "generated_at": _now(),
        "summary": {
            "failed_run_count": len(failures),
            "categories": categories,
        },
        "recent_failures": failures,
    }


def collect_github_failure_review(root: Path, repo: str, workflow: str, limit: int) -> dict:
    fields = "databaseId,status,conclusion,createdAt,displayTitle,event,url,workflowName"
    code, stdout, stderr = _run_gh(
        ["run", "list", "--repo", repo, "--workflow", workflow, "--limit", str(limit), "--json", fields],
        cwd=root,
    )
    if code != 0:
        return {
            "status": "unavailable",
            "generated_at": _now(),
            "summary": {"failed_run_count": 0, "categories": {}},
            "recent_failures": [],
            "error": stderr[-1200:],
        }

    runs = _load_json(stdout, [])
    failures = [
        row
        for row in runs
        if row.get("conclusion") not in {None, "", "success", "skipped"}
        and row.get("status") in {None, "", "completed"}
    ]
    details: dict[int, dict] = {}
    for row in failures[: min(8, limit)]:
        run_id = int(row.get("databaseId") or 0)
        if run_id:
            details[run_id] = _fetch_run_detail(root, repo, run_id)

    return build_failure_review(failures, details)


def write_review(root: Path, output: Path, repo: str, workflow: str, limit: int) -> dict:
    payload = collect_github_failure_review(root, repo, workflow, limit)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect recent GitHub Actions failures for weekly review diagnostics.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="data/internal/github_failure_review.json")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    payload = write_review(root, output, args.repo, args.workflow, args.limit)
    print(
        "github_failure_review "
        f"status={payload.get('status')} "
        f"failed={payload.get('summary', {}).get('failed_run_count', 0)} "
        f"output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
