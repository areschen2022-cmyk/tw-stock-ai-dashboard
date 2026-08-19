from __future__ import annotations

from typing import Any


ALLOWED_AI_PICK_ACTIONS = {"可追", "可追蹤突破", "等拉回", "只觀察", "避免"}
CHASE_ACTIONS = {"可追", "可追蹤突破"}
RED_ACTION = "避免"
PULLBACK_ACTION = "等拉回"


def normalize_ai_pick_action(value: Any, default: str = "可追") -> str:
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
            _set_avoid(row, "紅色警戒個股不得列入可追。")
            gate_tags.append("紅色警戒")
            gate_reasons.append("紅色警戒")
            was_chase_like = False

        if original_action == PULLBACK_ACTION and _is_open_confirm(original_entry):
            row["entry_decision"] = PULLBACK_ACTION
            row["decision_light"] = "yellow"
            row["decision_light_label"] = PULLBACK_ACTION
            row["decision_light_reason"] = _join_note(
                row.get("decision_light_reason"),
                "原本就是等拉回，不能用開盤確認包裝成追價。",
            )
            gate_tags.append("進場確認不足")
            gate_reasons.append("進場確認不足")

        if was_chase_like:
            repeated = repeated_lookup.get(stock_id) or {}
            recent_count = _int(repeated.get("recent_count"))
            if recent_count > 3 and _repeated_signal_is_weak(repeated):
                _downgrade_to_pullback(row, f"近 60 日重複出現 {recent_count} 次，先降權避免追高。")
                gate_tags.append("重複訊號降權")
                gate_reasons.append("重複訊號")

        if was_chase_like and not _has_volume_confirmation(row):
            _downgrade_to_pullback(row, "量能未確認大於 20 日均量 1.5 倍，不直接追價。")
            gate_tags.append("量能未確認")
            gate_reasons.append("量能未確認")

        if was_chase_like and not _has_consolidation_base(row):
            _downgrade_to_pullback(row, "突破前整理不足，避免已經噴一段後追價。")
            gate_tags.append("整理不足")
            gate_reasons.append("整理不足")

        if was_chase_like and _has_weak_theme(row, weak_theme_set) and not _has_non_theme_confirmation(row):
            _downgrade_to_pullback(row, "弱題材缺少法人、營收或供應鏈證據，不可升級可追。")
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
            if row.get("action") == RED_ACTION or row.get("entry_decision") == RED_ACTION:
                row.pop("exit_plan", None)
            changed += 1
            for reason in set(gate_reasons):
                reasons_count[reason] = reasons_count.get(reason, 0) + 1
        else:
            row["decision_gate"] = {"applied": False}
            if was_chase_like and str(row.get("action") or "") != RED_ACTION:
                if not row.get("decision_light"):
                    row["decision_light"] = "green"
                if not row.get("decision_light_label"):
                    row["decision_light_label"] = "可盯"
                if not row.get("decision_light_reason"):
                    row["decision_light_reason"] = "強度足夠且通過量能、整理、題材與風險閘門；等待開盤觸發。"

        _assign_decision_state(row)

    summary = {
        "applied": changed,
        "red_alert_blocked": reasons_count.get("紅色警戒", 0),
        "repeat_downgraded": reasons_count.get("重複訊號", 0),
        "volume_downgraded": reasons_count.get("量能未確認", 0),
        "base_downgraded": reasons_count.get("整理不足", 0),
        "weak_theme_downgraded": reasons_count.get("弱題材", 0),
        "entry_strict_adjusted": reasons_count.get("進場確認不足", 0),
        "policy": "紅色警戒不得可追；弱題材不得單靠題材升級；AI 只做複核不直接加分。",
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
    return any(item in action for item in CHASE_ACTIONS) or _is_open_confirm(entry) or "可追" in entry


def _is_open_confirm(value: str) -> bool:
    return "開盤確認" in str(value or "")


def _set_avoid(row: dict[str, Any], note: str) -> None:
    row["action"] = RED_ACTION
    row["entry_decision"] = RED_ACTION
    row["action_context"] = "風險過高"
    row["action_context_reason"] = note
    row["decision_light"] = "red"
    row["decision_light_label"] = "避開"
    row["decision_light_reason"] = note


def _downgrade_to_pullback(row: dict[str, Any], note: str) -> None:
    if str(row.get("action") or "") != RED_ACTION and str(row.get("entry_decision") or "") != RED_ACTION:
        row["action"] = PULLBACK_ACTION
        row["entry_decision"] = PULLBACK_ACTION
        row["decision_light"] = "yellow"
        row["decision_light_label"] = PULLBACK_ACTION
        row["decision_light_reason"] = _join_note(row.get("decision_light_reason"), note)


def _repeated_signal_is_weak(repeated: dict[str, Any]) -> bool:
    has_quality_metric = False
    for key in ("win_rate_5d", "success_rate_5d", "hit_rate_5d"):
        value = _float(repeated.get(key))
        if value is not None:
            has_quality_metric = True
            return value < 50
    for key in ("avg_return_5d", "return_5d"):
        value = _float(repeated.get(key))
        if value is not None:
            has_quality_metric = True
            return value < 0
    if repeated.get("weak") or repeated.get("is_weak"):
        return True
    return not has_quality_metric


def _has_volume_confirmation(row: dict[str, Any]) -> bool:
    tags = _structured_terms(row)
    if tags.intersection({"放量突破", "量能轉強", "量增整理", "突破整理"}):
        return True
    text = _row_text(row)
    if any(term in text for term in ("量能不漲", "量縮", "量能未確認", "放量不漲")):
        return False
    return any(term in text for term in ("放量", "爆量", "量增", "量能轉強", "1.5x", "長紅", "成交量", "突破整理"))


def _has_consolidation_base(row: dict[str, Any]) -> bool:
    tags = _structured_terms(row)
    if tags.intersection({"突破整理", "箱型整理", "收斂整理", "K線轉強:突破整理", "底部轉強"}):
        return True
    text = _row_text(row)
    if any(term in text for term in ("追高", "過熱", "急拉", "乖離", "已噴", "衝高")):
        return False
    return any(term in text for term in ("整理", "平台", "盤整", "突破整理", "箱型", "底部", "20日", "橫盤", "收斂"))


def _has_weak_theme(row: dict[str, Any], weak_themes: set[str]) -> bool:
    if not weak_themes:
        return False
    labels = {str(item).split(":")[0] for item in row.get("themes") or []}
    labels.update(str(item).split(":")[0] for item in row.get("theme_tiers") or [])
    return bool(labels.intersection(weak_themes))


def _has_non_theme_confirmation(row: dict[str, Any]) -> bool:
    text = _row_text(row)
    if any(term in text for term in ("法人共振", "投信買超", "外資買超", "營收加速", "營收創高", "供應鏈", "訂單", "月營收")):
        return True
    for item in row.get("theme_chain") or []:
        if item.get("chain_layer_label") or item.get("role") or item.get("beneficiary_label"):
            return True
    return False


def _assign_decision_state(row: dict[str, Any]) -> None:
    action = str(row.get("action") or "")
    entry = str(row.get("entry_decision") or "")
    light = str(row.get("decision_light") or "")

    if light == "red" or action == RED_ACTION or entry == RED_ACTION:
        row["decision_state"] = "blocked"
        row["decision_state_label"] = "風控擋下"
        return

    if "等拉回" in action or "等拉回" in entry or light == "yellow":
        row["decision_state"] = "pullback_wait"
        row["decision_state_label"] = "等拉回"
        return

    if _is_open_confirm(entry) or action in CHASE_ACTIONS or "可追" in action:
        row["decision_state"] = "ready_confirm"
        row["decision_state_label"] = "開盤確認"
        return

    if str(row.get("grade") or "") in {"S+", "S", "A", "B"}:
        row["decision_state"] = "discovery"
        row["decision_state_label"] = "潛力觀察"
        return

    row["decision_state"] = "watch"
    row["decision_state_label"] = "只觀察"


def _structured_terms(row: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for key in ("trigger_tags", "pattern_tags", "selection_quality_notes", "guardrail_tags"):
        terms.update(str(item).strip() for item in row.get(key) or [] if str(item).strip())
    return terms


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
        "action_context",
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


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
