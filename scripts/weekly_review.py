from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_sorted(rows: list[dict], key: str, *, reverse: bool = True, min_completed: int = 0) -> dict:
    usable = [row for row in rows if row.get(key) is not None and int(_num(row.get("completed"))) >= min_completed]
    if not usable:
        return {}
    return sorted(usable, key=lambda row: _num(row.get(key)), reverse=reverse)[0]


def _label(row: dict) -> str:
    return str(row.get("label") or row.get("theme") or row.get("action") or row.get("stage") or "-")


def _compact_stat(row: dict) -> dict:
    if not row:
        return {}
    return {
        "label": _label(row),
        "signals": row.get("signals") or row.get("count"),
        "completed": row.get("completed"),
        "win_rate_5d": row.get("win_rate_5d"),
        "avg_return_5d": row.get("avg_return_5d"),
        "stop_hit_rate": row.get("stop_hit_rate"),
    }


def _guardrail_status(row: dict, *, min_completed: int = 10) -> str:
    completed = int(_num(row.get("completed")))
    win_rate = row.get("win_rate_5d")
    avg_return = row.get("avg_return_5d")
    if completed < min_completed or win_rate is None or avg_return is None:
        return "needs_more_samples"
    if _num(win_rate) < 45 or _num(avg_return) < 0:
        return "needs_review"
    if _num(win_rate) >= 52 and _num(avg_return) >= 0:
        return "working"
    return "neutral"


def _previous_guardrail_status(previous_review: dict | None) -> dict[str, str]:
    if not isinstance(previous_review, dict):
        return {}
    return {
        str(row.get("tag")): str(row.get("status"))
        for row in previous_review.get("guardrail_effectiveness") or []
        if row.get("tag")
    }


def _guardrail_effectiveness(performance: dict, previous_review: dict | None = None) -> list[dict]:
    previous = _previous_guardrail_status(previous_review)
    rows: list[dict] = []
    for row in performance.get("guardrail_stats") or []:
        tag = str(row.get("tag") or "")
        if not tag:
            continue
        status = _guardrail_status(row)
        previous_status = previous.get(tag)
        consecutive_review = status == "needs_review" and previous_status == "needs_review"
        if consecutive_review:
            recommended_action = "連續兩週無效，暫停或調整這條降權規則。"
        elif status == "needs_review":
            recommended_action = "下週降權規則需觀察；若再無效就暫停或改門檻。"
        elif status == "working":
            recommended_action = "保留規則，持續累積樣本。"
        elif status == "neutral":
            recommended_action = "暫不調整，等待方向更明確。"
        else:
            recommended_action = "樣本不足，先不改規則。"
        rows.append(
            {
                "tag": tag,
                "label": tag,
                "signals": row.get("signals"),
                "completed": row.get("completed"),
                "win_rate_5d": row.get("win_rate_5d"),
                "avg_return_5d": row.get("avg_return_5d"),
                "stop_hit_rate": row.get("stop_hit_rate"),
                "status": status,
                "previous_status": previous_status,
                "consecutive_review": consecutive_review,
                "recommended_action": recommended_action,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            0 if item["consecutive_review"] else 1,
            0 if item["status"] == "needs_review" else 1,
            -int(_num(item.get("completed"))),
            str(item.get("tag")),
        ),
    )


def _potential_rows(potential: dict, key: str) -> list[dict]:
    value = potential.get(key)
    if value is None and isinstance(potential.get("potential_radar"), dict):
        value = potential["potential_radar"].get(key)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("rows") or []
    return []


def _weekly_themes(weekly: dict, max_items: int = 5) -> list[dict]:
    return [
        {
            "theme": row.get("theme") or row.get("label") or row.get("name"),
            "week_score": row.get("week_score"),
            "trend": row.get("trend"),
            "today": row.get("today"),
        }
        for row in (weekly.get("themes") or [])[:max_items]
    ]


def _action_items(performance: dict, potential: dict, backtest: dict, guardrails: list[dict] | None = None) -> list[dict]:
    actions: list[dict] = []

    win_rate = _num((performance.get("stats") or {}).get("win_rate_5d"))
    if win_rate < 50:
        actions.append(
            {
                "type": "deweight",
                "target": "每日可追訊號",
                "reason": f"5日勝率 {win_rate:.1f}% 低於 50%，下週需提高開盤量價確認門檻。",
            }
        )

    entry = performance.get("entry_analysis") or {}
    triggered = entry.get("triggered") or {}
    not_triggered = entry.get("not_triggered") or {}
    if _num(triggered.get("completed") or triggered.get("count")) >= 20 and _num(triggered.get("avg_return_5d")) < _num(
        not_triggered.get("avg_return_5d"), -999
    ):
        actions.append(
            {
                "type": "investigate",
                "target": "進場觸發條件",
                "reason": "有觸發進場的樣本報酬低於未觸發樣本，需檢討是否追價或開盤條件太寬。",
            }
        )

    weak_stage = _first_sorted(_potential_rows(potential, "stage_stats"), "avg_return_5d", reverse=False, min_completed=10)
    if weak_stage and _num(weak_stage.get("avg_return_5d")) < 0:
        actions.append(
            {
                "type": "deweight",
                "target": f"潛力雷達：{_label(weak_stage)}",
                "reason": f"完成 {int(_num(weak_stage.get('completed')))} 筆但 5日平均 {_num(weak_stage.get('avg_return_5d')):.1f}%，下週只列觀察或降權。",
            }
        )

    for item in (backtest.get("adaptive_feedback") or [])[:3]:
        target = item.get("target") or item.get("label")
        action = item.get("action")
        if target and action:
            actions.append({"type": "carry_forward", "target": target, "reason": action})

    for row in guardrails or []:
        if row.get("status") != "needs_review":
            continue
        actions.append(
            {
                "type": "review_guardrail",
                "target": f"降權規則：{row.get('tag')}",
                "reason": row.get("recommended_action"),
            }
        )

    return actions[:8]


def build_weekly_review(
    performance: dict,
    potential: dict,
    weekly: dict,
    backtest: dict,
    previous_review: dict | None = None,
) -> dict:
    perf_stats = performance.get("stats") or {}
    pot_stats = potential.get("stats") or (potential.get("potential_radar") or {}).get("stats") or {}
    stage_rows = _potential_rows(potential, "stage_stats")
    factor_rows = _potential_rows(potential, "factor_stats")
    backtest_summary = backtest.get("summary") or {}

    daily_win = _num(perf_stats.get("win_rate_5d"))
    potential_win = _num(pot_stats.get("win_rate_5d"))
    risk_level = "normal"
    if daily_win < 50 or potential_win < 50 or backtest.get("risk_level") in {"needs_review", "sample_too_small"}:
        risk_level = "needs_review"
    if daily_win < 45 and potential_win < 45:
        risk_level = "high_review"

    guardrail_rows = _guardrail_effectiveness(performance, previous_review)

    return {
        "as_of": performance.get("as_of") or weekly.get("as_of") or backtest.get("as_of"),
        "generated_at": _now(),
        "status": "ok",
        "risk_level": risk_level,
        "summary": {
            "daily_signals": perf_stats.get("signals"),
            "daily_completed": perf_stats.get("completed"),
            "daily_win_rate_5d": perf_stats.get("win_rate_5d"),
            "daily_avg_return_5d": perf_stats.get("avg_return_5d"),
            "potential_signals": pot_stats.get("signals"),
            "potential_completed": pot_stats.get("completed"),
            "potential_win_rate_5d": pot_stats.get("win_rate_5d"),
            "potential_avg_return_5d": pot_stats.get("avg_return_5d"),
            "backtest_risk_level": backtest.get("risk_level"),
            "backtest_completed": backtest_summary.get("completed"),
        },
        "best": {
            "potential_stage": _compact_stat(_first_sorted(stage_rows, "avg_return_5d", min_completed=10)),
            "potential_factor": _compact_stat(_first_sorted(factor_rows, "avg_return_5d", min_completed=10)),
            "weekly_themes": _weekly_themes(weekly),
        },
        "weak": {
            "potential_stage": _compact_stat(_first_sorted(stage_rows, "avg_return_5d", reverse=False, min_completed=10)),
            "potential_factor": _compact_stat(_first_sorted(factor_rows, "avg_return_5d", reverse=False, min_completed=10)),
            "backtest_segments": ((backtest.get("weak") or {}).get("segments") or [])[:5],
            "failure_attribution": ((backtest.get("weak") or {}).get("failure_attribution") or [])[:5],
        },
        "guardrail_effectiveness": guardrail_rows,
        "next_week_actions": _action_items(performance, potential, backtest, guardrail_rows),
        "rules": [
            "每週檢討只調整下週觀察與降權，不直接產生買賣建議。",
            "樣本低於 10 筆只列觀察，不做正式降權。",
            "每日進場仍以今日監控的開盤價量、停損與風險名單為準。",
            "降權規則若連續兩週無效，標記為需調整或暫停。",
        ],
    }


def write_weekly_review(root: Path, output: Path) -> dict:
    dashboard = root / "dashboard"
    previous_review = _read_json(output)
    review = build_weekly_review(
        _read_json(dashboard / "performance_data.json"),
        _read_json(dashboard / "potential_data.json"),
        _read_json(dashboard / "weekly_data.json"),
        _read_json(dashboard / "backtest_review.json"),
        previous_review,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly review summary for internal learning and next-week guardrails.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dashboard/weekly_review.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    review = write_weekly_review(root, output)
    print(f"weekly_review status={review['status']} risk_level={review['risk_level']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
