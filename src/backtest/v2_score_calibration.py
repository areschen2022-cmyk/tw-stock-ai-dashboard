from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.scoring.versioning import DECISION_VERSION, SCORE_VERSION, UNIVERSE_VERSION


TAIPEI = ZoneInfo("Asia/Taipei")
THRESHOLDS = [50, 55, 60, 65, 75, 85]


def build_v2_score_calibration(db_path: Path, as_of: date, windows: tuple[int, ...] = (60, 120)) -> dict:
    payload = {
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "score_version": SCORE_VERSION,
        "decision_version": DECISION_VERSION,
        "universe_version": UNIVERSE_VERSION,
        "status": "ok",
        "windows": [],
        "suggested_thresholds": None,
        "note": "Production thresholds are not changed by this report. V1/unversioned rows are excluded.",
    }
    if not db_path.exists():
        payload["status"] = "missing_database"
        return payload
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_scores)").fetchall()}
        if "score_version" not in columns or "decision_version" not in columns:
            payload["status"] = "insufficient_v2_history"
            payload["reason"] = "daily_scores has no version columns yet"
            return payload
        for days in windows:
            since = (as_of - timedelta(days=days * 2)).isoformat()
            rows = conn.execute(
                """
                SELECT as_of_date, total_score
                FROM daily_scores
                WHERE as_of_date >= ?
                  AND as_of_date <= ?
                  AND score_version = ?
                  AND decision_version = ?
                """,
                (since, as_of.isoformat(), SCORE_VERSION, DECISION_VERSION),
            ).fetchall()
            scores = [int(row[1]) for row in rows if row[1] is not None]
            trade_dates = len({row[0] for row in rows})
            payload["windows"].append(_window_stats(days, trade_dates, scores))
    eligible = [row for row in payload["windows"] if row["trade_dates"] >= 20 and row["count"] >= 200]
    if not eligible:
        payload["status"] = "insufficient_v2_history"
        payload["reason"] = "Need at least 20 V2 trade dates and 200 scored rows before threshold suggestions are meaningful."
    else:
        best = eligible[-1]
        payload["suggested_thresholds"] = _suggest_thresholds(best)
    return payload


def write_v2_score_calibration(payload: dict, dashboard_dir: Path, reports_dir: Path) -> None:
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    (dashboard_dir / "v2_score_calibration.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (reports_dir / "v2_score_calibration.md").write_text(_markdown(payload), encoding="utf-8")


def _window_stats(days: int, trade_dates: int, scores: list[int]) -> dict:
    scores_sorted = sorted(scores)
    return {
        "window_days": days,
        "trade_dates": trade_dates,
        "count": len(scores_sorted),
        "max": max(scores_sorted) if scores_sorted else None,
        "p99": _percentile(scores_sorted, 99),
        "p95": _percentile(scores_sorted, 95),
        "p90": _percentile(scores_sorted, 90),
        "p75": _percentile(scores_sorted, 75),
        "median": _percentile(scores_sorted, 50),
        "counts": {f">={threshold}": sum(1 for score in scores_sorted if score >= threshold) for threshold in THRESHOLDS},
    }


def _suggest_thresholds(row: dict) -> dict:
    return {
        "watch": max(50, int(row.get("p75") or 50)),
        "a_candidate": max(60, int(row.get("p90") or 60)),
        "s_candidate": max(75, int(row.get("p95") or 75)),
        "note": "Suggested from V2 distribution only; review with realized returns before production changes.",
    }


def _percentile(values: list[int], pct: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    rank = (len(values) - 1) * pct / 100
    low = int(rank)
    high = min(low + 1, len(values) - 1)
    weight = rank - low
    return round(values[low] * (1 - weight) + values[high] * weight, 2)


def _markdown(payload: dict) -> str:
    def fmt(value) -> str:
        return "—" if value is None else str(value)

    lines = [
        "# V2 Score Calibration",
        "",
        f"- as_of: {payload.get('as_of')}",
        f"- status: {payload.get('status')}",
        f"- score_version: {payload.get('score_version')}",
        f"- note: {payload.get('note')}",
        "",
        "| Window | Trade Dates | Rows | Max | P99 | P95 | P90 | P75 | Median | >=65 | >=75 | >=85 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("windows") or []:
        counts = row.get("counts") or {}
        lines.append(
            f"| {row.get('window_days')} | {row.get('trade_dates')} | {row.get('count')} | {fmt(row.get('max'))} | "
            f"{fmt(row.get('p99'))} | {fmt(row.get('p95'))} | {fmt(row.get('p90'))} | {fmt(row.get('p75'))} | {fmt(row.get('median'))} | "
            f"{counts.get('>=65', 0)} | {counts.get('>=75', 0)} | {counts.get('>=85', 0)} |"
        )
    if payload.get("reason"):
        lines.extend(["", f"Reason: {payload['reason']}"])
    if payload.get("suggested_thresholds"):
        lines.extend(["", "Suggested thresholds:", "```json", json.dumps(payload["suggested_thresholds"], ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines) + "\n"
