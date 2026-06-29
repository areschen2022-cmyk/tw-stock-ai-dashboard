from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(rows: list[dict], key: str, reverse: bool = True) -> dict | None:
    usable = [row for row in rows if row.get(key) is not None]
    if not usable:
        return None
    return sorted(usable, key=lambda row: _num(row.get(key)), reverse=reverse)[0]


def _row_summary(row: dict | None, label_key: str = "label") -> dict:
    if not row:
        return {}
    return {
        "label": row.get(label_key) or row.get("label") or row.get("theme") or row.get("action") or row.get("grade"),
        "signals": row.get("signals"),
        "completed": row.get("completed"),
        "win_rate_5d": row.get("win_rate_5d"),
        "avg_return_5d": row.get("avg_return_5d"),
        "stop_hit_rate": row.get("stop_hit_rate"),
    }


def _qualified_weak_segments(rows: list[dict], min_completed: int = 10) -> list[dict]:
    output = []
    for row in rows:
        completed = int(_num(row.get("completed")))
        avg_return = row.get("avg_return_5d")
        win_rate = row.get("win_rate_5d")
        stop_hit = row.get("stop_hit_rate")
        if completed < min_completed:
            continue
        weak_return = avg_return is not None and _num(avg_return) < 0
        weak_win = win_rate is not None and _num(win_rate) < 42
        high_stop = stop_hit is not None and _num(stop_hit) >= 45
        if weak_return or weak_win or high_stop:
            output.append(row)
    return output


def _why_win_rate_not_higher(
    *,
    stats: dict,
    score_bands: list[dict],
    theme_stats: list[dict],
    action_stats: list[dict],
    weak_segments: list[dict],
    postmortem: dict,
) -> dict:
    overall_win = _num(stats.get("win_rate_5d"))
    overall_avg = _num(stats.get("avg_return_5d"))
    notes: list[str] = []

    weak_score = _first(score_bands, "avg_return_5d", reverse=False)
    if weak_score and _num(weak_score.get("completed")) >= 20:
        notes.append(
            f"{weak_score.get('label')} 分區拖累："
            f"完成 {int(_num(weak_score.get('completed')))} 筆，"
            f"5日勝率 {_num(weak_score.get('win_rate_5d')):.1f}%，"
            f"平均 {_num(weak_score.get('avg_return_5d')):.1f}%。"
        )

    weak_theme = _first(theme_stats, "avg_return_5d", reverse=False)
    if weak_theme and _num(weak_theme.get("completed")) >= 10:
        notes.append(
            f"弱題材集中：{weak_theme.get('label') or weak_theme.get('theme')} "
            f"5日平均 {_num(weak_theme.get('avg_return_5d')):.1f}%，"
            f"停損率 {_num(weak_theme.get('stop_hit_rate')):.1f}%。"
        )

    weak_action = _first(action_stats, "avg_return_5d", reverse=False)
    if weak_action and _num(weak_action.get("completed")) >= 5:
        notes.append(
            f"操作型態拖累：{weak_action.get('label') or weak_action.get('action')} "
            f"5日平均 {_num(weak_action.get('avg_return_5d')):.1f}%。"
        )

    failure_rows = ((postmortem.get("failure_attribution") or {}).get("rows") or [])
    if failure_rows:
        top_failure = failure_rows[0]
        notes.append(
            f"主要失敗歸因：{top_failure.get('label')} "
            f"{top_failure.get('count')} 筆，"
            f"5日平均 {_num(top_failure.get('avg_return_5d')):.1f}%。"
        )

    if not notes:
        if overall_win < 50 or overall_avg < 0:
            notes.append("近期整體勝率或平均報酬偏弱，但尚未形成足夠集中的可歸因區塊。")
        else:
            notes.append("近期勝率不高但平均報酬仍為正，代表少數強勢股彌補部分失敗訊號。")

    return {
        "headline": (
            f"近期 5 日勝率 {overall_win:.1f}%，平均報酬 {overall_avg:.1f}%；"
            "需降低高分追價與弱題材追高。"
        ),
        "root_causes": notes[:6],
        "guard_segments": _qualified_weak_segments(weak_segments)[:8],
    }


def build_review(performance: dict) -> dict:
    stats = performance.get("stats") or {}
    quality = performance.get("data_quality") or {}
    postmortem = performance.get("postmortem") or {}
    learning = performance.get("learning_center") or {}
    potential = performance.get("potential_radar") or {}
    ai = performance.get("ai_council") or {}

    score_bands = performance.get("score_bands") or []
    theme_stats = performance.get("theme_stats") or performance.get("top_themes") or []
    action_stats = performance.get("action_stats") or []
    source_rows = ((performance.get("signal_attribution") or {}).get("source_layer") or [])
    factor_rows = ((performance.get("signal_attribution") or {}).get("factor_layer") or [])

    weak_segments = (performance.get("backtest_insights") or {}).get("weak_segments") or []
    best_segments = (performance.get("backtest_insights") or {}).get("best_segments") or []
    calibration = performance.get("calibration_advice") or []
    adaptive = performance.get("adaptive_feedback") or []

    completed = _num(stats.get("completed"))
    win_rate = _num(stats.get("win_rate_5d"))
    avg_return = _num(stats.get("avg_return_5d"))
    data_completion = _num(quality.get("completion_rate_5d"))

    risk_level = "normal"
    if completed < 30:
        risk_level = "sample_too_small"
    elif win_rate < 50 or avg_return < 0:
        risk_level = "needs_review"
    elif win_rate >= 52 and avg_return > 0:
        risk_level = "constructive"

    return {
        "as_of": performance.get("as_of"),
        "generated_at": _now(),
        "status": "ok",
        "risk_level": risk_level,
        "summary": {
            "signals": stats.get("signals"),
            "completed": stats.get("completed"),
            "win_rate_5d": stats.get("win_rate_5d"),
            "avg_return_5d": stats.get("avg_return_5d"),
            "stop_hit_rate": stats.get("stop_hit_rate"),
            "data_completion_rate_5d": quality.get("completion_rate_5d"),
            "ai_win_rate_5d": ((ai.get("stats") or {}).get("win_rate_5d")),
            "potential_win_rate_5d": ((potential.get("stats") or {}).get("win_rate_5d")),
        },
        "best": {
            "score_band": _row_summary(_first(score_bands, "avg_return_5d"), "label"),
            "theme": _row_summary(_first(theme_stats, "avg_return_5d"), "theme"),
            "action": _row_summary(_first(action_stats, "avg_return_5d"), "action"),
            "source_layer": _row_summary(_first(source_rows, "avg_return_5d"), "label"),
            "factor_layer": _row_summary(_first(factor_rows, "avg_return_5d"), "label"),
            "segments": best_segments[:5],
        },
        "weak": {
            "score_band": _row_summary(_first(score_bands, "avg_return_5d", reverse=False), "label"),
            "theme": _row_summary(_first(theme_stats, "avg_return_5d", reverse=False), "theme"),
            "action": _row_summary(_first(action_stats, "avg_return_5d", reverse=False), "action"),
            "source_layer": _row_summary(_first(source_rows, "avg_return_5d", reverse=False), "label"),
            "factor_layer": _row_summary(_first(factor_rows, "avg_return_5d", reverse=False), "label"),
            "segments": weak_segments[:5],
            "failure_attribution": ((postmortem.get("failure_attribution") or {}).get("rows") or [])[:8],
        },
        "learning": {
            "success_factors": (learning.get("success_factors") or [])[:8],
            "failure_factors": (learning.get("failure_factors") or [])[:8],
            "notes": learning.get("notes") or [],
        },
        "why_win_rate_not_higher": _why_win_rate_not_higher(
            stats=stats,
            score_bands=score_bands,
            theme_stats=theme_stats,
            action_stats=action_stats,
            weak_segments=weak_segments,
            postmortem=postmortem,
        ),
        "review_actions": calibration[:8],
        "adaptive_feedback": adaptive[:8],
        "quality_gates": {
            "min_completed_5d": 30,
            "min_completion_rate_5d": 5,
            "passed": completed >= 30 and data_completion >= 5,
        },
    }


def write_review(root: Path, output: Path) -> dict:
    performance_path = root / "dashboard" / "performance_data.json"
    performance = _read_json(performance_path)
    review = build_review(performance)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact recurring backtest review from performance_data.json.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dashboard/backtest_review.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    review = write_review(root, output)
    print(
        "backtest_review "
        f"status={review['status']} as_of={review.get('as_of')} "
        f"risk_level={review.get('risk_level')} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
