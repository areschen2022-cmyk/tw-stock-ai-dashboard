from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.scoring.score_engine import StockScore


WEAK_GROUPS = {"grade", "theme", "action", "score_band", "entry_condition"}
GROUP_ALIASES = {
    "強度": "grade",
    "等級": "grade",
    "題材": "theme",
    "主題": "theme",
    "操作": "action",
    "操作建議": "action",
    "分數區間": "score_band",
    "進場條件": "entry_condition",
}
MIN_COMPLETED = 10
WEAK_WIN_RATE = 42.0
WEAK_AVG_RETURN = 0.0
HIGH_STOP_HIT = 45.0


def load_backtest_guard(root: Path) -> dict[str, Any]:
    """Load realized weak segments as a conservative guardrail.

    Sources:
    1. dashboard/backtest_review.json weak segments.
    2. dashboard/performance_data.json low_win_rate_breakdown rows.

    If either source is missing or malformed, the daily report is never blocked.
    """
    review_payload = _read_json(root / "dashboard" / "backtest_review.json")
    performance_payload = _read_json(root / "dashboard" / "performance_data.json")

    rows: list[dict[str, Any]] = []
    if review_payload:
        rows.extend((review_payload.get("weak") or {}).get("segments") or [])
    if performance_payload:
        rows.extend((performance_payload.get("low_win_rate_breakdown") or {}).get("rows") or [])

    segments = _qualified_segments(rows)
    return {
        "active": bool(segments),
        "as_of": performance_payload.get("as_of") or review_payload.get("as_of") if (performance_payload or review_payload) else None,
        "risk_level": review_payload.get("risk_level") if review_payload else None,
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
    labels = "、".join(_segment_label(match) for match in matches[:3])
    note = f"回測保護：近期 {labels} 表現偏弱，先降為等拉回"
    score.reasons.setdefault("backtest_guard", []).append(note)
    score.warnings.append(note)
    if "回測保護" not in score.trigger_tags:
        score.trigger_tags.append("回測保護")


def _qualified_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qualified: list[dict[str, Any]] = []
    for row in rows:
        group = _normalize_group(str(row.get("group") or ""))
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
                    "diagnosis": row.get("diagnosis"),
                    "recommended_action": row.get("recommended_action"),
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
        elif group == "entry_condition" and _entry_condition_matches(score, label):
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


def _entry_condition_matches(score: StockScore, label: str) -> bool:
    if label not in {"有觸發進場", "進場觸發", "entry_triggered"}:
        return False
    action_text = f"{score.action} {score.entry_decision}"
    return any(term in action_text for term in ["可追", "可追蹤突破", "開盤確認"])


def _normalize_group(group: str) -> str:
    return GROUP_ALIASES.get(group, group)


def _segment_label(segment: dict[str, Any]) -> str:
    group = str(segment.get("group") or "")
    label = str(segment.get("label") or "")
    if group == "entry_condition":
        return f"進場條件:{label}"
    return label


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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
