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
    weekly_payload = _read_json(root / "dashboard" / "weekly_review.json")

    rows: list[dict[str, Any]] = []
    if review_payload:
        rows.extend((review_payload.get("weak") or {}).get("segments") or [])
    if performance_payload:
        rows.extend((performance_payload.get("low_win_rate_breakdown") or {}).get("rows") or [])

    segments = _qualified_segments(rows)
    return {
        "active": bool(segments) or bool(_weekly_guardrails(weekly_payload)),
        "as_of": performance_payload.get("as_of") or review_payload.get("as_of") if (performance_payload or review_payload) else None,
        "risk_level": review_payload.get("risk_level") if review_payload else None,
        "segments": segments,
        "weekly": _weekly_guardrails(weekly_payload),
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
    pre_weekly_action = str(score.action or "")
    weekly_notes = _apply_weekly_guard(score, context.get("weekly") or {})
    _record_weekly_guardrail(score, context.get("weekly") or {}, weekly_notes, pre_weekly_action)
    if not matches:
        for note in weekly_notes:
            score.reasons.setdefault("backtest_guard", []).append(note)
            score.warnings.append(note)
        if weekly_notes and "週檢討降權" not in score.trigger_tags:
            score.trigger_tags.append("週檢討降權")
        return

    original_action = str(score.action or "")
    if original_action not in {"可追", "可追蹤突破"}:
        for note in weekly_notes:
            score.reasons.setdefault("backtest_guard", []).append(note)
            score.warnings.append(note)
        if weekly_notes and "週檢討降權" not in score.trigger_tags:
            score.trigger_tags.append("週檢討降權")
        return

    _record_guardrail(score, "backtest_weak_segment_downgrade", "matched realized weak segment")
    score.action = "等拉回"
    score.entry_decision = "等拉回"
    labels = "、".join(_segment_label(match) for match in matches[:3])
    note = f"回測保護：近期 {labels} 表現偏弱，先降為等拉回"
    score.reasons.setdefault("backtest_guard", []).append(note)
    score.warnings.append(note)
    if "回測保護" not in score.trigger_tags:
        score.trigger_tags.append("回測保護")
    for note in weekly_notes:
        score.reasons.setdefault("backtest_guard", []).append(note)
        score.warnings.append(note)
    if weekly_notes and "週檢討降權" not in score.trigger_tags:
        score.trigger_tags.append("週檢討降權")


def _weekly_guardrails(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    summary = payload.get("summary") or {}
    daily_completed = _num(summary.get("daily_completed"))
    daily_win_rate = summary.get("daily_win_rate_5d")
    actions = payload.get("next_week_actions") or []
    guard: dict[str, Any] = {
        "as_of": payload.get("as_of"),
        "daily_deweight": False,
        "entry_condition_caution": False,
        "notes": [],
    }
    for item in actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or "")
        target = str(item.get("target") or "")
        reason = str(item.get("reason") or "")
        if action_type == "deweight" and target == "每日可追訊號" and daily_completed >= MIN_COMPLETED:
            if daily_win_rate is None or _num(daily_win_rate) < 50:
                guard["daily_deweight"] = True
                guard["notes"].append(reason or "週檢討顯示每日可追勝率低於 50%，提高確認門檻。")
        elif target == "進場觸發條件":
            guard["entry_condition_caution"] = True
            guard["notes"].append(reason or "週檢討顯示進場條件需重新驗證。")
    return guard if guard["daily_deweight"] or guard["entry_condition_caution"] else {}


def _apply_weekly_guard(score: StockScore, guard: dict[str, Any]) -> list[str]:
    if not guard:
        return []
    notes: list[str] = []
    original_action = str(score.action or "")
    if guard.get("daily_deweight") and original_action in {"可追", "可追蹤突破"}:
        # Keep the strongest S/S+ names untouched, but require more confirmation
        # for A/B or borderline candidates after a weak weekly review.
        if int(score.total_score or 0) < 85:
            score.action = "等拉回"
            score.entry_decision = "等拉回"
            notes.append("週檢討降權：每日可追近週勝率低於 50%，A/B 邊界訊號先等拉回")
        else:
            notes.append("週檢討提醒：每日可追近週勝率偏低，S級以上仍須開盤量價確認")
    if guard.get("entry_condition_caution") and original_action in {"可追", "可追蹤突破"}:
        notes.append("週檢討提醒：進場觸發條件近期需重驗，避免開盤追價")
    return notes


def _record_weekly_guardrail(
    score: StockScore,
    guard: dict[str, Any],
    notes: list[str],
    original_action: str,
) -> None:
    if not guard or not notes:
        return
    joined = " | ".join(notes[:3])
    if guard.get("daily_deweight"):
        tag = "weekly_deweight_daily_chase" if str(score.action or "") != original_action else "weekly_warn_strong_chase"
        _record_guardrail(score, tag, joined)
    if guard.get("entry_condition_caution"):
        _record_guardrail(score, "weekly_entry_condition_caution", joined)


def _record_guardrail(score: StockScore, tag: str, note: str) -> None:
    if tag and tag not in score.guardrail_tags:
        score.guardrail_tags.append(tag)
    if note and note not in score.guardrail_notes:
        score.guardrail_notes.append(note)


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
