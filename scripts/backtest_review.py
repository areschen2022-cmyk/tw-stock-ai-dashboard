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


def _month_key(value: str | None) -> str:
    if not value or len(value) < 7:
        return "unknown"
    return value[:7]


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _rate(flags: list[bool]) -> float | None:
    if not flags:
        return None
    return sum(1 for flag in flags if flag) / len(flags) * 100


def _monthly_returns(items: list[dict], max_months: int = 12) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        value = item.get("return_5d")
        if value is None:
            continue
        buckets.setdefault(_month_key(item.get("signal_date")), []).append(item)

    rows = []
    for month, month_items in sorted(buckets.items()):
        returns = [_num(item.get("return_5d")) for item in month_items]
        rows.append(
            {
                "month": month,
                "signals": len(month_items),
                "win_rate_5d": _rate([value > 0 for value in returns]),
                "avg_return_5d": _avg(returns),
                "best_return_5d": max(returns) if returns else None,
                "worst_return_5d": min(returns) if returns else None,
            }
        )
    return rows[-max_months:]


def _weak_summary(row: dict | None, label_key: str = "label", reason: str = "") -> dict | None:
    if not row:
        return None
    completed = int(_num(row.get("completed") or row.get("count")))
    if completed <= 0:
        return None
    return {
        "label": row.get(label_key) or row.get("label") or row.get("theme") or row.get("action") or row.get("grade"),
        "sample": completed,
        "win_rate_5d": row.get("win_rate_5d"),
        "avg_return_5d": row.get("avg_return_5d"),
        "stop_hit_rate": row.get("stop_hit_rate"),
        "reason": reason,
    }


def _win_rate_diagnosis(
    *,
    stats: dict,
    score_bands: list[dict],
    theme_stats: list[dict],
    action_stats: list[dict],
    postmortem: dict,
) -> dict:
    overall_win = _num(stats.get("win_rate_5d"))
    failure_rows = ((postmortem.get("failure_attribution") or {}).get("rows") or [])
    candidates: list[dict] = []

    weak_score = _weak_summary(
        _first(score_bands, "avg_return_5d", reverse=False),
        reason="分數區間報酬偏弱，可能代表高分仍有追價或樣本偏誤。",
    )
    weak_theme = _weak_summary(
        _first(theme_stats, "avg_return_5d", reverse=False),
        reason="題材表現拖累，短期不宜只因新聞熱度加分。",
    )
    weak_action = _weak_summary(
        _first(action_stats, "avg_return_5d", reverse=False),
        reason="操作型態表現偏弱，需調整進場條件或降低優先度。",
    )
    for row in (weak_score, weak_theme, weak_action):
        if row:
            candidates.append(row)

    for row in failure_rows[:3]:
        candidates.append(
            {
                "label": row.get("label"),
                "sample": row.get("count"),
                "win_rate_5d": None,
                "avg_return_5d": row.get("avg_return_5d"),
                "stop_hit_rate": row.get("stop_hit_rate"),
                "reason": row.get("lesson") or "失敗歸因集中，應轉成降權或開盤確認條件。",
            }
        )

    actions: list[str] = []
    for row in candidates[:5]:
        label = row.get("label")
        avg_return = _num(row.get("avg_return_5d"))
        stop_hit = _num(row.get("stop_hit_rate"))
        sample = int(_num(row.get("sample")))
        if sample >= 20 and avg_return < 0:
            actions.append(f"{label}：樣本 {sample} 且 5日平均為負，先降權或改列觀察。")
        elif sample >= 10 and stop_hit >= 40:
            actions.append(f"{label}：停損率偏高，需更嚴格開盤量價確認。")

    if not actions and overall_win < 50:
        actions.append("整體勝率低於 50%，但尚未有單一穩定拖累因子；先維持小部位並累積樣本。")
    elif not actions:
        actions.append("目前沒有明確需要降權的弱因子，持續觀察月度勝率是否改善。")

    return {
        "triggered": overall_win < 50,
        "headline": f"5日勝率 {overall_win:.1f}%，{'低於' if overall_win < 50 else '高於或等於'} 50% 門檻。",
        "likely_causes": candidates[:6],
        "recommended_actions": actions[:6],
    }


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
    items = performance.get("items") or []

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
        "win_rate_diagnosis": _win_rate_diagnosis(
            stats=stats,
            score_bands=score_bands,
            theme_stats=theme_stats,
            action_stats=action_stats,
            postmortem=postmortem,
        ),
        "monthly_returns": _monthly_returns(items),
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
