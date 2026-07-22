from __future__ import annotations

from typing import Any


ALLOWED_AI_PICK_ACTIONS = {"可追", "可追蹤突破", "等拉回", "只觀察", "避免"}
CHASE_ACTIONS = {"可追", "可追蹤突破"}
RED_ACTION = "避免"
PULLBACK_ACTION = "等拉回"


def normalize_ai_pick_action(value: Any, default: str = "可追") -> str:
    """Return a safe AI pick action even if config text was saved with bad encoding."""

    text = str(value or "").strip()
    if not text or "\ufffd" in text or text not in ALLOWED_AI_PICK_ACTIONS:
        return default
    return text


def apply_dashboard_decision_gates(
    payload: dict[str, Any],
    *,
    exit_risks: list[dict[str, Any]] | None = None,
    repeated_signal_context: dict[str, Any] | None = None,
    weak_themes: set[str] | None = None,
) -> dict[str, Any]:
    """Apply hard execution gates to dashboard rows.

    These gates intentionally do not change score or grade. They only change the
    execution posture shown in the morning decision layer so strong-but-risky
    names do not remain in the chase bucket.
    """

    rows = payload.get("rows") or []
    exit_lookup = {
        str(item.get("stock_id")): item
        for item in (exit_risks or payload.get("exit_risks") or [])
        if item.get("stock_id")
    }
    repeated_lookup = (repeated_signal_context or {}).get("by_stock") or {}
    weak_theme_set = {str(item) for item in (weak_themes or set()) if str(item)}

    changed = 0
    reasons_count: dict[str, int] = {}
    for row in rows:
        stock_id = str(row.get("stock_id") or "")
        original_action = str(row.get("action") or "")
        original_entry = str(row.get("entry_decision") or "")
        was_chase_like = _is_chase_like(row)
        gate_reasons: list[str] = []
        gate_tags: list[str] = []

        if stock_id in exit_lookup:
            _set_avoid(row, "紅色警戒，不得列入可追")
            gate_tags.append("紅色警戒禁追")
            gate_reasons.append("紅色警戒")

        if "等拉回" in original_action and "開盤確認" in original_entry:
            row["entry_decision"] = PULLBACK_ACTION
            row["decision_light"] = "yellow"
            row["decision_light_label"] = "黃燈等拉回"
            row["decision_light_reason"] = _join_note(row.get("decision_light_reason"), "操作已降為等拉回，不再使用開盤追價確認")
            gate_tags.append("進場觸發轉嚴格")
            gate_reasons.append("進場觸發嚴格化")

        if was_chase_like:
            repeated = repeated_lookup.get(stock_id) or {}
            recent_count = _int(repeated.get("recent_count"))
            if recent_count > 3:
                _downgrade_to_pullback(row, f"近60日重複訊號 {recent_count} 次，避免同股反覆追價")
                gate_tags.append("60日重複降權")
                gate_reasons.append("重複訊號過多")

        if was_chase_like and not _has_volume_confirmation(row):
            _downgrade_to_pullback(row, "缺少 1.5x 以上放量確認，先等開盤量能")
            gate_tags.append("量能未達硬門檻")
            gate_reasons.append("量能不足")

        if was_chase_like and not _has_consolidation_base(row):
            _downgrade_to_pullback(row, "突破前整理證據不足，避免追已噴出段")
            gate_tags.append("整理不足降權")
            gate_reasons.append("整理不足")

        if was_chase_like and _has_weak_theme(row, weak_theme_set) and not _has_non_theme_confirmation(row):
            _downgrade_to_pullback(row, "弱題材缺少法人、營收或供應鏈證據，不因題材升級")
            gate_tags.append("弱題材未確認")
            gate_reasons.append("弱題材")

        if gate_reasons:
            _append_unique(row, "trigger_tags", gate_tags)
            _append_unique(row, "warnings", [f"決策閘門：{'、'.join(dict.fromkeys(gate_reasons))}"])
            row["decision_gate"] = {
                "applied": True,
                "original_action": original_action,
                "original_entry_decision": original_entry,
                "action": row.get("action"),
                "entry_decision": row.get("entry_decision"),
                "reasons": list(dict.fromkeys(gate_reasons)),
                "tags": gate_tags,
            }
            row.pop("exit_plan", None)
            changed += 1
            for reason in set(gate_reasons):
                reasons_count[reason] = reasons_count.get(reason, 0) + 1
        else:
            row["decision_gate"] = {"applied": False}

    summary = {
        "applied": changed,
        "red_alert_blocked": reasons_count.get("紅色警戒", 0),
        "repeat_downgraded": reasons_count.get("重複訊號過多", 0),
        "volume_downgraded": reasons_count.get("量能不足", 0),
        "base_downgraded": reasons_count.get("整理不足", 0),
        "weak_theme_downgraded": reasons_count.get("弱題材", 0),
        "entry_strict_adjusted": reasons_count.get("進場觸發嚴格化", 0),
        "policy": (
            "紅色警戒不得可追；近60日重複>3次、缺放量、缺整理或弱題材無確認者降為等拉回；"
            "AI/DeepSeek 只複核不加分。"
        ),
    }
    payload["decision_gates"] = summary
    return summary


def weak_themes_from_backtest_guard(context: dict[str, Any] | None) -> set[str]:
    themes: set[str] = set()
    for row in (context or {}).get("segments") or []:
        group = str(row.get("group") or row.get("type") or "")
        if group == "theme":
            label = str(row.get("label") or row.get("theme") or "")
            if label:
                themes.add(label)
    return themes


def _is_chase_like(row: dict[str, Any]) -> bool:
    action = str(row.get("action") or "")
    entry = str(row.get("entry_decision") or "")
    return any(item in action for item in CHASE_ACTIONS) or "開盤確認" in entry or "可追" in entry


def _set_avoid(row: dict[str, Any], note: str) -> None:
    row["action"] = RED_ACTION
    row["entry_decision"] = RED_ACTION
    row["action_context"] = "未列入今日操作"
    row["action_context_reason"] = note
    row["decision_light"] = "red"
    row["decision_light_label"] = "紅燈控風險"
    row["decision_light_reason"] = note


def _downgrade_to_pullback(row: dict[str, Any], note: str) -> None:
    if str(row.get("action") or "") != RED_ACTION and str(row.get("entry_decision") or "") != RED_ACTION:
        row["action"] = PULLBACK_ACTION
        row["entry_decision"] = PULLBACK_ACTION
        row["decision_light"] = "yellow"
        row["decision_light_label"] = "黃燈等拉回"
        row["decision_light_reason"] = _join_note(row.get("decision_light_reason"), note)


def _has_volume_confirmation(row: dict[str, Any]) -> bool:
    text = _row_text(row)
    return "放量長紅" in text or "量能確認" in text or "成交量放大" in text or "1.5x" in text


def _has_consolidation_base(row: dict[str, Any]) -> bool:
    text = _row_text(row)
    return "突破整理" in text or "分數已成形" in text or "箱型整理" in text or "整理" in text


def _has_weak_theme(row: dict[str, Any], weak_themes: set[str]) -> bool:
    if not weak_themes:
        return False
    labels = {str(item).split(":")[0] for item in row.get("themes") or []}
    labels.update(str(item).split(":")[0] for item in row.get("theme_tiers") or [])
    return bool(labels.intersection(weak_themes))


def _has_non_theme_confirmation(row: dict[str, Any]) -> bool:
    text = _row_text(row)
    if any(term in text for term in ("法人共振", "營收加速", "投信買超", "外資買超")):
        return True
    for item in row.get("theme_chain") or []:
        if item.get("chain_layer_label") or item.get("role") or item.get("beneficiary_label"):
            return True
    return False


def _append_unique(row: dict[str, Any], key: str, values: list[str]) -> None:
    existing = [str(item) for item in row.get(key) or []]
    for value in values:
        if value and value not in existing:
            existing.append(value)
    row[key] = existing


def _row_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "action",
        "entry_decision",
        "trigger_summary",
        "decision_reason",
        "technical",
        "chip",
        "fundamental",
        "opportunity",
        "chain_summary",
    ):
        parts.append(str(row.get(key) or ""))
    for key in ("trigger_tags", "pattern_tags", "selection_quality_notes", "entry_checklist"):
        parts.extend(str(item) for item in row.get(key) or [])
    return " ".join(parts)


def _join_note(current: Any, note: str) -> str:
    text = str(current or "").strip()
    if not text:
        return note
    if note in text:
        return text
    return f"{text}；{note}"


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
