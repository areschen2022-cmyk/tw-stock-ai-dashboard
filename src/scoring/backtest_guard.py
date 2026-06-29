from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.scoring.score_engine import StockScore


WEAK_GROUPS = {"grade", "theme", "action", "score_band"}
MIN_COMPLETED = 10
WEAK_WIN_RATE = 42.0
WEAK_AVG_RETURN = 0.0
HIGH_STOP_HIT = 45.0


def load_backtest_guard(root: Path) -> dict[str, Any]:
    """Load the latest recurring backtest review as a conservative guardrail.

    The guard intentionally reads the previous generated review from dashboard/.
    If it is missing or malformed, it returns an inactive context so the daily
    report is never blocked.
    """
    path = root / "dashboard" / "backtest_review.json"
    if not path.exists():
        return {"active": False, "reason": "missing_backtest_review", "segments": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"active": False, "reason": "invalid_backtest_review", "segments": []}

    weak = payload.get("weak") or {}
    segments = _qualified_segments(weak.get("segments") or [])
    return {
        "active": bool(segments),
        "as_of": payload.get("as_of"),
        "risk_level": payload.get("risk_level"),
        "segments": segments,
    }


def apply_backtest_guard(score: StockScore, context: dict[str, Any] | None) -> None:
    """Downgrade operation only when recent realized outcomes are weak.

    This guard does not change total_score or grade. It only changes execution
    posture from "可追/可追蹤突破" to "等拉回" when the stock matches a weak
    recent group with enough completed samples.
    """
    if not context or not context.get("active"):
        return

    segments = _qualified_segments(context.get("segments") or [])
    matches = _matches(score, segments)
    if not matches:
        return

    original_action = str(score.action or "")
    if original_action not in {"可追", "可追蹤突破"}:
        return

    score.action = "等拉回"
    score.entry_decision = "等拉回"
    labels = "、".join(match["label"] for match in matches[:3])
    note = f"回測保護：近期 {labels} 表現偏弱，先降為等拉回"
    score.reasons.setdefault("backtest_guard", []).append(note)
    score.warnings.append(note)
    if "回測保護" not in score.trigger_tags:
        score.trigger_tags.append("回測保護")


def _qualified_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qualified: list[dict[str, Any]] = []
    for row in rows:
        group = str(row.get("group") or "")
        label = str(row.get("label") or "")
        completed = _num(row.get("completed"))
        win_rate = row.get("win_rate_5d")
        avg_return = row.get("avg_return_5d")
        stop_hit = row.get("stop_hit_rate")
        if group not in WEAK_GROUPS or not label or completed < MIN_COMPLETED:
            continue
        weak_return = avg_return is not None and _num(avg_return) < WEAK_AVG_RETURN
        weak_win = win_rate is not None and _num(win_rate) < WEAK_WIN_RATE
        high_stop = stop_hit is not None and _num(stop_hit) >= HIGH_STOP_HIT
        if weak_return or weak_win or high_stop:
            qualified.append(
                {
                    "group": group,
                    "label": label,
                    "completed": int(completed),
                    "win_rate_5d": win_rate,
                    "avg_return_5d": avg_return,
                    "stop_hit_rate": stop_hit,
                }
            )
    return qualified


def _matches(score: StockScore, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feature_text = _feature_text(score)
    matched: list[dict[str, Any]] = []
    grade = _grade(score.total_score)
    for segment in segments:
        group = segment["group"]
        label = str(segment["label"])
        if group in {"grade", "score_band"} and _score_group_matches(label, grade, score.total_score):
            matched.append(segment)
        elif group == "action" and label in {str(score.action or ""), str(score.entry_decision or "")}:
            matched.append(segment)
        elif group == "theme" and _normalize(label) in feature_text:
            matched.append(segment)
    return matched


def _feature_text(score: StockScore) -> str:
    parts: list[str] = [
        *score.themes,
        *score.theme_tiers,
        *score.trigger_tags,
        *score.selection_quality_notes,
    ]
    for rows in (score.reasons or {}).values():
        parts.extend(str(item) for item in rows)
    return _normalize(" ".join(parts))


def _score_group_matches(label: str, grade: str, total_score: int) -> bool:
    if label == grade:
        return True
    if "-" in label:
        try:
            low, high = [int(part) for part in label.split("-", 1)]
        except ValueError:
            return False
        return low <= int(total_score) <= high
    return False


def _grade(score: int) -> str:
    if score >= 95:
        return "S+"
    if score >= 85:
        return "S"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    return "-"


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize(value: str) -> str:
    return "".join(str(value).split()).lower()
