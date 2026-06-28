from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
REQUIRED_DASHBOARD_FILES = [
    "index.html",
    "dashboard_data.json",
    "performance.html",
    "performance_data.json",
    "potential.html",
    "potential_data.json",
    "weekly.html",
    "weekly_data.json",
    "debug_data.json",
]


def _issue(severity: str, area: str, message: str, suggestion: str) -> dict:
    return {
        "severity": severity,
        "area": area,
        "message": message,
        "suggestion": suggestion,
    }


def _read_json(path: Path, issues: list[dict]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        issues.append(
            _issue(
                "critical",
                "file",
                f"Missing required JSON: {path.as_posix()}",
                "Regenerate dashboard outputs and verify the docs copy step.",
            )
        )
    except json.JSONDecodeError as exc:
        issues.append(
            _issue(
                "critical",
                "json",
                f"Invalid JSON: {path.as_posix()} ({exc})",
                "Check the report writer that produced this file.",
            )
        )
    return {}


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count_by_severity(issues: list[dict]) -> dict:
    return {
        "critical": sum(1 for item in issues if item.get("severity") == "critical"),
        "warning": sum(1 for item in issues if item.get("severity") == "warning"),
        "info": sum(1 for item in issues if item.get("severity") == "info"),
    }


def _db_scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return _int(row[0] if row else 0)


def _check_files(root: Path, issues: list[dict]) -> dict[str, dict]:
    dashboard_dir = root / "dashboard"
    payloads = {}
    for name in REQUIRED_DASHBOARD_FILES:
        path = dashboard_dir / name
        if not path.exists():
            issues.append(
                _issue(
                    "critical",
                    "file",
                    f"Missing dashboard/{name}",
                    "Confirm the generator still writes every dashboard page and JSON payload.",
                )
            )
            continue
        if name.endswith(".json"):
            payloads[name] = _read_json(path, issues)
    return payloads


def _check_payloads(payloads: dict[str, dict], issues: list[dict]) -> dict:
    dashboard = payloads.get("dashboard_data.json") or {}
    weekly = payloads.get("weekly_data.json") or {}
    performance = payloads.get("performance_data.json") or {}
    potential = payloads.get("potential_data.json") or {}
    debug = payloads.get("debug_data.json") or {}

    as_of = str(dashboard.get("as_of") or "")
    weekly_as_of = str(weekly.get("as_of") or "")
    if not as_of:
        issues.append(
            _issue(
                "critical",
                "dashboard",
                "dashboard_data.json is missing as_of",
                "Check build_dashboard_payload and date handling.",
            )
        )
    if as_of and weekly_as_of and as_of != weekly_as_of:
        issues.append(
            _issue(
                "warning",
                "weekly",
                f"weekly_data.as_of({weekly_as_of}) differs from dashboard.as_of({as_of})",
                "Confirm weekly overview is written after the current run date is resolved.",
            )
        )

    summary = dashboard.get("summary") or {}
    if _int(summary.get("valid")) <= 0:
        issues.append(
            _issue(
                "critical",
                "scoring",
                "No valid scored stocks",
                "Check data source fallback and score_engine input rows.",
            )
        )

    rows = dashboard.get("rows") or []
    if not rows:
        issues.append(
            _issue(
                "critical",
                "dashboard",
                "dashboard rows are empty",
                "Check main.py result assembly before dashboard rendering.",
            )
        )

    action_summary = (dashboard.get("action_lists") or {}).get("summary") or {}
    chase = _int(action_summary.get("chase"))
    pullback = _int(action_summary.get("pullback"))
    if chase == 0 and pullback == 0:
        issues.append(
            _issue(
                "info",
                "decision",
                "No chase or pullback candidates today",
                "This can be normal. If repeated, review action thresholds.",
            )
        )

    quality_label = str((dashboard.get("data_quality") or {}).get("label_text") or "")
    if quality_label and quality_label not in {"\u9ad8", "high", "High"}:
        issues.append(
            _issue(
                "warning",
                "data_quality",
                f"Data quality is not high: {quality_label}",
                "Check fallback/retry attribution before treating this as a true data loss.",
            )
        )

    ai_health = (((dashboard.get("ai_council") or {}).get("status") or {}).get("health") or {})
    ai_label = str(ai_health.get("label") or "")
    unstable_ai_labels = {"\u672a\u555f\u7528", "\u4e0d\u7a69\u5b9a", "\u964d\u7d1a\u53ef\u7528"}
    if ai_label in unstable_ai_labels:
        issues.append(
            _issue(
                "info",
                "ai",
                f"AI council health: {ai_label}",
                "Keep AI as a secondary review signal and verify DEEPSEEK_API_KEY/OpenRouter settings.",
            )
        )

    perf_stats = performance.get("stats") or {}
    if _int(perf_stats.get("signals")) == 0:
        issues.append(
            _issue(
                "warning",
                "performance",
                "No watch signal records in performance data",
                "Check save_watch_candidates and update_forward_returns.",
            )
        )

    potential_stats = (potential.get("stats") or {}) or ((performance.get("potential_radar") or {}).get("stats") or {})
    if _int(potential_stats.get("signals")) == 0:
        issues.append(
            _issue(
                "info",
                "potential",
                "No potential radar records",
                "This can be normal on strict filters. Review only if it persists.",
            )
        )

    data_updates = weekly.get("data_updates") or []
    if not any(item.get("dataset") == "institutional_flow" for item in data_updates):
        issues.append(
            _issue(
                "warning",
                "weekly_data",
                "weekly_data.json lacks institutional_flow update status",
                "Confirm main.py records data_update_log for institutional flow.",
            )
        )
    if not any(item.get("dataset") == "tdcc_retail_holders" for item in data_updates):
        issues.append(
            _issue(
                "warning",
                "weekly_data",
                "weekly_data.json lacks TDCC retail-holder update status",
                "Confirm the scheduled weekly TDCC job ran. Push runs may intentionally skip it.",
            )
        )

    trace = debug.get("traceability") or {}
    diagnosis = trace.get("diagnosis") or []
    if diagnosis:
        issues.append(
            _issue(
                "info",
                "traceability",
                f"Traceability diagnosis contains {len(diagnosis)} item(s)",
                "Review dashboard/debug_data.json traceability.diagnosis.",
            )
        )

    return {
        "as_of": as_of,
        "weekly_as_of": weekly_as_of,
        "rows": len(rows),
        "valid": _int(summary.get("valid")),
        "chase": chase,
        "pullback": pullback,
        "data_updates": data_updates[:10],
    }


def _check_database(root: Path, as_of: str, issues: list[dict]) -> dict:
    db_path = root / "data" / "tw_stock_ai.sqlite3"
    if not db_path.exists():
        issues.append(
            _issue(
                "critical",
                "database",
                "Missing data/tw_stock_ai.sqlite3",
                "Confirm SQLiteStore created and the workflow preserved the DB artifact.",
            )
        )
        return {}

    with sqlite3.connect(db_path) as conn:
        daily_scores = _db_scalar(conn, "SELECT COUNT(*) FROM daily_scores WHERE as_of_date = ?", (as_of,))
        traceability = _db_scalar(conn, "SELECT COUNT(*) FROM traceability_runs WHERE run_date = ?", (as_of,))
        institutional = _db_scalar(
            conn,
            "SELECT COUNT(*) FROM data_update_log WHERE dataset = 'institutional_flow' AND source_date = ?",
            (as_of,),
        )
        tdcc_recent = _db_scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM data_update_log
            WHERE dataset = 'tdcc_retail_holders'
              AND status = 'ok'
              AND julianday(?) - julianday(update_date) <= 10
            """,
            (datetime.now(TAIPEI).date().isoformat(),),
        )

    if daily_scores <= 0:
        issues.append(
            _issue(
                "critical",
                "database",
                f"No daily_scores rows for {as_of}",
                "Check store.save_daily_score and scoring completion.",
            )
        )
    if traceability <= 0:
        issues.append(
            _issue(
                "warning",
                "database",
                f"No traceability_runs rows for {as_of}",
                "Check save_traceability_run after dashboard generation.",
            )
        )
    if institutional <= 0:
        issues.append(
            _issue(
                "warning",
                "database",
                f"No institutional_flow update log for {as_of}",
                "Check institutional flow data_update_log recording.",
            )
        )
    if tdcc_recent <= 0:
        issues.append(
            _issue(
                "warning",
                "database",
                "No recent TDCC retail-holder update log within 10 days",
                "Check the weekly TDCC schedule and source fetch status.",
            )
        )

    return {
        "daily_scores": daily_scores,
        "traceability_runs": traceability,
        "institutional_update_rows": institutional,
        "recent_tdcc_update_rows": tdcc_recent,
    }


def _next_optimizations(issues: list[dict], context: dict) -> list[str]:
    areas = {item.get("area") for item in issues}
    suggestions = []
    if "ai" in areas:
        suggestions.append("Stabilize AI review by using one paid primary model plus a cheap backup model.")
    if "weekly_data" in areas or "database" in areas:
        suggestions.append("Add a compact weekly data-source status summary to the internal check report.")
    if "potential" in areas:
        suggestions.append("Review potential-radar thresholds after collecting more completed 5-day outcomes.")
    if context.get("chase", 0) == 0:
        suggestions.append("Tune action thresholds only after checking whether zero chase candidates repeats for several days.")
    if not suggestions:
        suggestions.append("Next: compare decision-card outcomes by reason tag to identify which signals deserve more weight.")
    return suggestions[:5]


def run_check(root: Path, output: Path) -> dict:
    issues: list[dict] = []
    payloads = _check_files(root, issues)
    context = _check_payloads(payloads, issues)
    db_context = _check_database(root, context.get("as_of") or "", issues) if context.get("as_of") else {}
    counts = _count_by_severity(issues)
    status = "bad" if counts["critical"] else "warn" if counts["warning"] else "ok"
    result = {
        "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "status": status,
        "counts": counts,
        "context": context,
        "database": db_context,
        "issues": issues,
        "next_optimizations": _next_optimizations(issues, context),
        "note": "Internal post-update check. Not linked from the main dashboard UI.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run post-update checks for dashboard outputs.")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--output", default="dashboard/post_update_check.json", help="Output JSON path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    result = run_check(root, output)
    print(
        f"post-update-check status={result['status']} "
        f"critical={result['counts']['critical']} warning={result['counts']['warning']} "
        f"output={output}"
    )
    for issue in result["issues"]:
        print(f"[{issue['severity']}] {issue['area']}: {issue['message']}")
    return 1 if result["counts"]["critical"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
