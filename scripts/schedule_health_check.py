from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
GITHUB_DASHBOARD_CRONS = {
    "30 20 * * 0-4": "04:30",
    "0 21 * * 0-4": "05:00",
}
GITHUB_TELEGRAM_CRONS = {
    "20 23 * * 0-4": "07:20",
    "35 23 * * 0-4": "07:35",
    "50 23 * * 0-4": "07:50",
}
CLOUDFLARE_TELEGRAM_CRONS = {
    "20 23 * * SUN-THU": "07:20",
    "35 23 * * SUN-THU": "07:35",
    "5 0 * * MON-FRI": "08:05",
}
CLOUDFLARE_DASHBOARD_CRONS = {
    "30 20 * * SUN-THU": "04:30",
    "0 21 * * SUN-THU": "05:00",
}
CORE_DASHBOARD_PAYLOADS = [
    "dashboard_data.json",
    "performance_data.json",
    "potential_data.json",
    "weekly_data.json",
]


def _issue(severity: str, area: str, message: str, suggestion: str) -> dict:
    return {
        "severity": severity,
        "area": area,
        "message": message,
        "suggestion": suggestion,
    }


def _read_text(path: Path, issues: list[dict], *, area: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        issues.append(
            _issue(
                "critical",
                area,
                f"Missing file: {path.as_posix()}",
                "Confirm the scheduler/config file exists in the repository.",
            )
        )
    except UnicodeDecodeError as exc:
        issues.append(
            _issue(
                "critical",
                area,
                f"Cannot read UTF-8 file: {path.as_posix()} ({exc})",
                "Save the file as UTF-8 and rerun the health check.",
            )
        )
    return ""


def _read_json(path: Path, issues: list[dict]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        issues.append(
            _issue(
                "critical",
                "dashboard_payload",
                f"Missing dashboard payload: {path.as_posix()}",
                "Run main.py and the dashboard writers before checking schedule health.",
            )
        )
    except json.JSONDecodeError as exc:
        issues.append(
            _issue(
                "critical",
                "dashboard_payload",
                f"Invalid dashboard JSON: {path.as_posix()} ({exc})",
                "Regenerate the dashboard payload and check the writer for partial output.",
            )
        )
    return {}


def _count_by_severity(issues: list[dict]) -> dict:
    return {
        "critical": sum(1 for item in issues if item.get("severity") == "critical"),
        "warning": sum(1 for item in issues if item.get("severity") == "warning"),
        "info": sum(1 for item in issues if item.get("severity") == "info"),
    }


def _is_trading_weekday(now: datetime) -> bool:
    return now.weekday() < 5


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TAIPEI)
    return parsed.astimezone(TAIPEI)


def check_workflow_config(root: Path, issues: list[dict]) -> dict:
    workflow_text = _read_text(root / ".github" / "workflows" / "daily.yml", issues, area="github_schedule")
    wrangler_text = _read_text(root / "cloudflare-worker" / "wrangler.toml", issues, area="cloudflare_schedule")
    found = {
        "github_dashboard": [],
        "github_telegram": [],
        "cloudflare_dashboard": [],
        "cloudflare_telegram": [],
    }
    for cron in GITHUB_DASHBOARD_CRONS:
        if cron in workflow_text:
            found["github_dashboard"].append(cron)
        else:
            issues.append(
                _issue(
                    "critical",
                    "github_schedule",
                    f"Missing dashboard cron in daily.yml: {cron}",
                    "Restore the 04:30/05:00 Asia/Taipei dashboard update schedules.",
                )
            )
    for cron in GITHUB_TELEGRAM_CRONS:
        if cron in workflow_text:
            found["github_telegram"].append(cron)
        else:
            issues.append(
                _issue(
                    "critical",
                    "github_schedule",
                    f"Missing Telegram fallback cron in daily.yml: {cron}",
                    "Restore the 07:20/07:35/07:50 Asia/Taipei GitHub fallback schedules.",
                )
            )
    for cron in CLOUDFLARE_DASHBOARD_CRONS:
        if cron in wrangler_text:
            found["cloudflare_dashboard"].append(cron)
        else:
            issues.append(
                _issue(
                    "critical",
                    "cloudflare_schedule",
                    f"Missing Cloudflare dashboard cron in wrangler.toml: {cron}",
                    "Deploy the Worker with the 04:30/05:00 Asia/Taipei dashboard schedules.",
                )
            )
    for cron in CLOUDFLARE_TELEGRAM_CRONS:
        if cron in wrangler_text:
            found["cloudflare_telegram"].append(cron)
        else:
            issues.append(
                _issue(
                    "critical",
                    "cloudflare_schedule",
                    f"Missing Cloudflare Telegram cron in wrangler.toml: {cron}",
                    "Deploy the Worker with the 07:20/07:35/08:05 Asia/Taipei Telegram fallback schedules.",
                )
            )
    if "5 0 * * 1-5" in workflow_text or "5 0 * * MON-FRI" in workflow_text:
        issues.append(
            _issue(
                "warning",
                "github_schedule",
                "08:05 Telegram cron also appears in GitHub Actions.",
                "Keep the 08:05 fallback owned by Cloudflare only, otherwise duplicate sends are more likely.",
            )
        )
    return found


def check_dashboard_payloads(root: Path, issues: list[dict], *, max_stale_days: int, now: datetime) -> dict:
    payloads = {name: _read_json(root / "dashboard" / name, issues) for name in CORE_DASHBOARD_PAYLOADS}
    dates: dict[str, str] = {}
    generated_at = ""
    for name, payload in payloads.items():
        as_of = str(payload.get("as_of") or "")
        if as_of:
            dates[name] = as_of
        if name == "dashboard_data.json":
            generated_at = str(payload.get("generated_at") or "")
    if "dashboard_data.json" not in dates:
        issues.append(
            _issue(
                "critical",
                "dashboard_payload",
                "dashboard_data.json has no as_of date.",
                "Fix date resolution in main.py before publishing the dashboard.",
            )
        )
    unique_dates = sorted(set(dates.values()))
    if len(unique_dates) > 1:
        issues.append(
            _issue(
                "warning",
                "dashboard_payload",
                f"Dashboard payload dates are not aligned: {dates}",
                "Regenerate all dashboard pages in one run before publishing.",
            )
        )
    generated_dt = _parse_datetime(generated_at)
    stale_days = None
    if generated_at and generated_dt is None:
        issues.append(
            _issue(
                "warning",
                "dashboard_freshness",
                f"Cannot parse dashboard generated_at: {generated_at}",
                "Write generated_at as an ISO timestamp with timezone.",
            )
        )
    elif generated_dt is not None:
        stale_days = max(0, (now.date() - generated_dt.date()).days)
        if stale_days > max_stale_days:
            issues.append(
                _issue(
                    "warning",
                    "dashboard_freshness",
                    f"Dashboard generated_at is {stale_days} days old.",
                    "Check whether GitHub Actions or Cloudflare dispatch has stopped running.",
                )
            )
    return {
        "dates": dates,
        "as_of": dates.get("dashboard_data.json", ""),
        "generated_at": generated_at,
        "stale_days": stale_days,
    }


def check_delivery_log(
    root: Path,
    issues: list[dict],
    *,
    delivery_date: str,
    now: datetime,
    strict_telegram: bool,
) -> dict:
    db_path = root / "data" / "tw_stock_ai.sqlite3"
    if not db_path.exists():
        issues.append(
            _issue(
                "critical" if strict_telegram else "warning",
                "telegram_delivery",
                "Missing SQLite database for delivery_log check.",
                "Confirm data/tw_stock_ai.sqlite3 is committed after scheduled runs.",
            )
        )
        return {"available": False, "delivered": False}
    try:
        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(delivery_log)").fetchall()}
            status_expr = "status" if "status" in columns else "'sent'"
            row = conn.execute(
                f"""
                SELECT sent_at, run_id, {status_expr} AS status
                FROM delivery_log
                WHERE channel = 'telegram'
                  AND delivery_date = ?
                  AND message_type = 'morning_report'
                LIMIT 1
                """,
                (delivery_date,),
            ).fetchone()
    except sqlite3.Error as exc:
        issues.append(
            _issue(
                "critical" if strict_telegram else "warning",
                "telegram_delivery",
                f"Cannot query delivery_log: {exc}",
                "Run SQLite schema migration by instantiating SQLiteStore once.",
            )
        )
        return {"available": False, "delivered": False}
    sent_at = row[0] if row else ""
    sent_dt = _parse_datetime(sent_at)
    latest_expected_dt = datetime.combine(datetime.fromisoformat(delivery_date).date(), time(8, 5), tzinfo=TAIPEI)
    on_time_deadline = datetime.combine(datetime.fromisoformat(delivery_date).date(), time(8, 30), tzinfo=TAIPEI)
    sent_in_future = bool(sent_dt and sent_dt > now + timedelta(minutes=2))
    delivered = bool(row and row[2] == "sent" and not sent_in_future)
    pending = bool(row and row[2] == "pending")
    delivery_delay_minutes = None
    if sent_dt:
        delivery_delay_minutes = round((sent_dt - latest_expected_dt).total_seconds() / 60, 1)
    if strict_telegram and _is_trading_weekday(now) and now.time() >= time(8, 30) and not delivered:
        issues.append(
            _issue(
                "critical",
                "telegram_delivery",
                f"No sent morning_report delivery_log row for {delivery_date} after 08:30 Asia/Taipei.",
                "Check GitHub fallback, Cloudflare Worker dispatch, and Telegram credentials.",
            )
        )
    elif pending:
        issues.append(
            _issue(
                "warning",
                "telegram_delivery",
                f"Telegram delivery is still pending for {delivery_date}.",
                "If this remains pending, clear stale claims or inspect the failed send run.",
            )
        )
    elif strict_telegram and delivered and sent_dt and sent_dt > on_time_deadline:
        issues.append(
            _issue(
                "warning",
                "telegram_delivery",
                f"Telegram morning_report for {delivery_date} was delivered late at {sent_dt.isoformat(timespec='seconds')}.",
                "Restore Cloudflare Worker dispatch so the report is sent before 08:30 Asia/Taipei even when GitHub schedule is delayed.",
            )
        )
    return {
        "available": True,
        "delivery_date": delivery_date,
        "delivered": delivered,
        "pending": pending,
        "sent_at": sent_at,
        "run_id": row[1] if row else "",
        "status": row[2] if row else "missing",
        "delivery_delay_minutes": delivery_delay_minutes,
        "on_time": bool(delivered and sent_dt and sent_dt <= on_time_deadline),
    }


def check_recent_github_runs(root: Path, issues: list[dict], *, repo: str) -> dict:
    command = [
        "gh",
        "run",
        "list",
        "--repo",
        repo,
        "--workflow",
        "daily.yml",
        "--limit",
        "5",
        "--json",
        "databaseId,status,conclusion,createdAt,displayTitle,event",
    ]
    proc = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False, timeout=30)
    if proc.returncode != 0:
        issues.append(
            _issue(
                "warning",
                "github_runs",
                "Cannot query recent GitHub Actions runs.",
                "Run gh auth status locally or inspect GitHub Actions in the browser.",
            )
        )
        return {"available": False, "stderr_tail": proc.stderr[-1000:]}
    try:
        runs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        issues.append(
            _issue(
                "warning",
                "github_runs",
                "GitHub CLI returned non-JSON output.",
                "Upgrade gh CLI or rerun the command manually.",
            )
        )
        return {"available": False, "stdout_tail": proc.stdout[-1000:]}
    failed = [run for run in runs if run.get("status") == "completed" and run.get("conclusion") not in {"success", "skipped"}]
    if failed:
        issues.append(
            _issue(
                "warning",
                "github_runs",
                f"Recent daily.yml failures found: {len(failed)}",
                "Open the latest failed run and inspect the failing job annotation.",
            )
        )
    return {"available": True, "failed_recent_runs": failed[:3], "runs": runs}


def run_check(
    root: Path,
    output: Path,
    *,
    now: datetime | None = None,
    max_stale_days: int = 3,
    strict_telegram: bool = False,
    with_github: bool = False,
    repo: str = "areschen2022-cmyk/tw-stock-ai-dashboard",
) -> dict:
    now = now.astimezone(TAIPEI) if now else datetime.now(TAIPEI)
    issues: list[dict] = []
    schedules = check_workflow_config(root, issues)
    payload = check_dashboard_payloads(root, issues, max_stale_days=max_stale_days, now=now)
    delivery_date = payload.get("as_of") or now.date().isoformat()
    delivery = check_delivery_log(
        root,
        issues,
        delivery_date=delivery_date,
        now=now,
        strict_telegram=strict_telegram,
    )
    github_runs = check_recent_github_runs(root, issues, repo=repo) if with_github else {"available": False}
    counts = _count_by_severity(issues)
    status = "bad" if counts["critical"] else "warn" if counts["warning"] else "ok"
    result = {
        "generated_at": now.isoformat(timespec="seconds"),
        "status": status,
        "counts": counts,
        "schedules": schedules,
        "dashboard": payload,
        "telegram_delivery": delivery,
        "github_runs": github_runs,
        "issues": issues,
        "next_actions": _next_actions(issues),
        "note": "Internal schedule health check; main UI may summarize this but should not expose noisy details.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _next_actions(issues: list[dict]) -> list[str]:
    areas = {item.get("area") for item in issues}
    actions = []
    if "github_schedule" in areas:
        actions.append("Fix .github/workflows/daily.yml dashboard/Telegram schedules.")
    if "cloudflare_schedule" in areas:
        actions.append("Fix cloudflare-worker/wrangler.toml, then redeploy the Worker.")
    if "dashboard_payload" in areas or "dashboard_freshness" in areas:
        actions.append("Confirm main.py writes fresh dashboard JSON, then check Pages deployment.")
    if "telegram_delivery" in areas:
        actions.append("Check delivery_log, Cloudflare dispatch, GitHub fallback, and Telegram secrets.")
    if not actions:
        actions.append("Schedule health check passed; next step can archive failed-run annotations into weekly review.")
    return actions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check schedule, dashboard freshness, and Telegram delivery health.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dashboard/schedule_health.json")
    parser.add_argument("--max-stale-days", type=int, default=3)
    parser.add_argument("--strict-telegram", action="store_true")
    parser.add_argument("--with-github", action="store_true")
    parser.add_argument("--repo", default="areschen2022-cmyk/tw-stock-ai-dashboard")
    parser.add_argument("--now", default="", help="Override current Asia/Taipei time with an ISO timestamp.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    now = _parse_datetime(args.now) if args.now else None
    result = run_check(
        root,
        output,
        now=now,
        max_stale_days=args.max_stale_days,
        strict_telegram=args.strict_telegram,
        with_github=args.with_github,
        repo=args.repo,
    )
    print(
        f"schedule-health status={result['status']} "
        f"critical={result['counts']['critical']} warning={result['counts']['warning']} "
        f"output={output}"
    )
    for issue in result["issues"]:
        print(f"[{issue['severity']}] {issue['area']}: {issue['message']}")
    return 1 if result["counts"]["critical"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
