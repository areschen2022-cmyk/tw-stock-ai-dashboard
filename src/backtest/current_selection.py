from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
MIN_REFERENCE_SAMPLE = 10


def build_current_selection_backtest(dashboard_payload: dict, performance_payload: dict) -> dict:
    """Compare today's candidates with historical realized signals.

    This is intentionally an internal guardrail. It does not decide trades by
    itself; it gives the decision layer and knowledge hub a compact answer to:
    "Have similar signals worked before?"
    """

    rows = list(dashboard_payload.get("rows") or [])
    history = [
        item
        for item in (performance_payload.get("items") or [])
        if item.get("return_5d") is not None and item.get("signal_date") != dashboard_payload.get("as_of")
    ]
    candidates = [_candidate_row(row, history) for row in rows if _is_candidate(row)]
    candidates.sort(key=lambda row: (_action_priority(row), row.get("score", 0)), reverse=True)

    referenceable = [
        row
        for row in candidates
        if (row.get("historical_profile") or {}).get("completed", 0) >= MIN_REFERENCE_SAMPLE
    ]
    weak = [
        row
        for row in referenceable
        if _num((row.get("historical_profile") or {}).get("avg_return_5d")) < 0
        or _num((row.get("historical_profile") or {}).get("win_rate_5d")) < 42
    ]
    strong = [
        row
        for row in referenceable
        if _num((row.get("historical_profile") or {}).get("avg_return_5d")) > 1
        and _num((row.get("historical_profile") or {}).get("win_rate_5d")) >= 50
    ]

    return {
        "as_of": dashboard_payload.get("as_of"),
        "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "source": "dashboard_data + performance_data",
        "history_completed_5d": len(history),
        "candidate_count": len(candidates),
        "referenceable_count": len(referenceable),
        "strong_reference_count": len(strong),
        "weak_reference_count": len(weak),
        "method": {
            "matching": "same action + same grade + any shared theme, fallback to grade/action/theme components",
            "min_reference_sample": MIN_REFERENCE_SAMPLE,
            "note": "Today's exact outcome still requires future 3/5/10 trading days.",
        },
        "summary": _summary(referenceable),
        "strong_references": strong[:8],
        "weak_references": weak[:8],
        "candidates": candidates[:40],
    }


def write_current_selection_backtest(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "current_selection_backtest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_current_selection_context(dashboard_payload: dict, current_backtest: dict) -> None:
    """Feed same-condition history back into the current dashboard decision layer.

    The adjustment is deliberately conservative:
    - Strong historical references only add context.
    - Weak historical references can downgrade a green/chase candidate to yellow
      confirmation, but they do not hide the stock or alter the numeric score.
    """

    candidates = {str(row.get("stock_id") or ""): row for row in current_backtest.get("candidates") or []}
    weak_ids = {str(row.get("stock_id") or "") for row in current_backtest.get("weak_references") or []}
    strong_ids = {str(row.get("stock_id") or "") for row in current_backtest.get("strong_references") or []}

    for row in dashboard_payload.get("rows") or []:
        stock_id = str(row.get("stock_id") or "")
        candidate = candidates.get(stock_id)
        if not candidate:
            continue
        profile = candidate.get("historical_profile") or {}
        row["historical_reference"] = {
            "label": _reference_label(candidate),
            "completed": profile.get("completed", 0),
            "win_rate_5d": profile.get("win_rate_5d"),
            "avg_return_5d": profile.get("avg_return_5d"),
            "confidence": profile.get("confidence"),
            "interpretation": candidate.get("interpretation"),
        }
        if stock_id in weak_ids:
            row["action_context_reason"] = _append_note(
                row.get("action_context_reason"),
                "同條件歷史偏弱，先降低追價衝動",
            )
            row["decision_light"] = "yellow"
            row["decision_light_label"] = "黃燈等確認"
            row["decision_light_reason"] = _append_note(
                row.get("decision_light_reason"),
                "同條件歷史偏弱",
            )
        elif stock_id in strong_ids:
            row["action_context_reason"] = _append_note(
                row.get("action_context_reason"),
                "同條件歷史偏正向",
            )

    _rebalance_action_lists(dashboard_payload, candidates, weak_ids, strong_ids)


def _candidate_row(row: dict, history: list[dict]) -> dict:
    action = str(row.get("action") or row.get("entry_decision") or "")
    grade = str(row.get("grade") or "")
    themes = [str(item) for item in (row.get("themes") or []) if item]

    same_profile = [
        item
        for item in history
        if str(item.get("grade") or "") == grade
        and str(item.get("action") or "") == action
        and _theme_overlap(themes, item.get("themes") or [])
    ]
    grade_items = [item for item in history if str(item.get("grade") or "") == grade]
    action_items = [item for item in history if str(item.get("action") or "") == action]
    theme_items = [item for item in history if _theme_overlap(themes, item.get("themes") or [])]
    fallback_pool = same_profile or _dedupe_items([*grade_items, *action_items, *theme_items])

    profile = _stats(same_profile if len(same_profile) >= MIN_REFERENCE_SAMPLE else fallback_pool)
    profile["match_type"] = "same_grade_action_theme" if len(same_profile) >= MIN_REFERENCE_SAMPLE else "component_fallback"
    profile["same_profile_completed"] = len(same_profile)

    return {
        "stock_id": str(row.get("stock_id") or ""),
        "name": row.get("name") or "",
        "score": row.get("score"),
        "grade": grade,
        "action": action,
        "entry_decision": row.get("entry_decision"),
        "decision_light": row.get("decision_light"),
        "themes": themes,
        "trigger_tags": row.get("trigger_tags") or [],
        "historical_profile": profile,
        "components": {
            "grade": _stats(grade_items),
            "action": _stats(action_items),
            "theme": _stats(theme_items),
        },
        "interpretation": _interpret(profile),
    }


def _is_candidate(row: dict) -> bool:
    grade = str(row.get("grade") or "")
    decision = str(row.get("entry_decision") or row.get("action") or "")
    light = str(row.get("decision_light") or "")
    actionable = {"開盤確認", "等拉回", "可追蹤突破", "可追"}
    return grade in {"S+", "S", "A", "B"} and (
        light in {"green", "yellow"} or any(label in decision for label in actionable)
    )


def _action_priority(row: dict) -> int:
    decision = str(row.get("entry_decision") or row.get("action") or "")
    if "開盤確認" in decision or "可追" in decision:
        return 3
    if "等拉回" in decision:
        return 2
    return 1


def _rebalance_action_lists(
    dashboard_payload: dict,
    candidates: dict[str, dict],
    weak_ids: set[str],
    strong_ids: set[str],
) -> None:
    action_lists = dashboard_payload.get("action_lists") or {}
    chase = list(action_lists.get("chase") or [])
    pullback = list(action_lists.get("pullback") or [])

    moved_to_pullback = []
    kept_chase = []
    for item in chase:
        stock_id = str(item.get("stock_id") or "")
        candidate = candidates.get(stock_id) or {}
        profile = candidate.get("historical_profile") or {}
        if profile and not item.get("historical_reference"):
            item = dict(item)
            item["historical_reference"] = {
                "label": _reference_label(candidate),
                "completed": profile.get("completed", 0),
                "win_rate_5d": profile.get("win_rate_5d"),
                "avg_return_5d": profile.get("avg_return_5d"),
                "confidence": profile.get("confidence"),
                "interpretation": candidate.get("interpretation"),
            }
        if stock_id in weak_ids:
            item = dict(item)
            item["decision_light"] = "yellow"
            item["decision_light_label"] = "黃燈等確認"
            item["decision_light_reason"] = _append_note(item.get("decision_light_reason"), "同條件歷史偏弱")
            item["action_context"] = "同條件偏弱，等確認"
            item["action_context_reason"] = _append_note(item.get("action_context_reason"), "先不追價")
            moved_to_pullback.append(item)
        else:
            kept_chase.append(item)

    def sort_key(item: dict) -> tuple[int, int, float, int]:
        stock_id = str(item.get("stock_id") or "")
        profile = (candidates.get(stock_id) or {}).get("historical_profile") or {}
        return (
            1 if stock_id in strong_ids else 0,
            0 if stock_id in weak_ids else 1,
            _num(profile.get("avg_return_5d")),
            int(item.get("score") or 0),
        )

    action_lists["chase"] = sorted(kept_chase, key=sort_key, reverse=True)[:5]
    action_lists["pullback"] = sorted([*moved_to_pullback, *pullback], key=sort_key, reverse=True)[:5]
    summary = action_lists.setdefault("summary", {})
    summary["chase"] = len(action_lists["chase"])
    summary["pullback"] = len(action_lists["pullback"])
    summary["historical_strong"] = len(strong_ids)
    summary["historical_weak"] = len(weak_ids)


def _theme_overlap(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return False
    normalized_left = {_normalize(item) for item in left}
    return any(_normalize(str(item)) in normalized_left for item in right)


def _dedupe_items(items: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    output = []
    for item in items:
        key = (str(item.get("signal_date") or ""), str(item.get("stock_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _stats(items: list[dict]) -> dict:
    returns = [_num(item.get("return_5d")) for item in items if item.get("return_5d") is not None]
    stop_values = [item.get("stop_hit") for item in items if item.get("stop_hit") is not None]
    completed = len(returns)
    return {
        "completed": completed,
        "win_rate_5d": _pct(sum(1 for value in returns if value > 0), completed),
        "avg_return_5d": round(sum(returns) / completed, 2) if completed else None,
        "stop_hit_rate": _pct(sum(1 for value in stop_values if value), len(stop_values)),
        "confidence": _confidence_label(completed),
    }


def _summary(rows: list[dict]) -> dict:
    profiles = [row.get("historical_profile") or {} for row in rows]
    returns = [_num(item.get("avg_return_5d")) for item in profiles if item.get("avg_return_5d") is not None]
    win_rates = [_num(item.get("win_rate_5d")) for item in profiles if item.get("win_rate_5d") is not None]
    return {
        "avg_reference_return_5d": round(sum(returns) / len(returns), 2) if returns else None,
        "avg_reference_win_rate_5d": round(sum(win_rates) / len(win_rates), 1) if win_rates else None,
        "note": "Reference quality is best when same-profile samples are available; otherwise component fallback is used.",
    }


def _interpret(profile: dict) -> str:
    completed = int(profile.get("completed") or 0)
    if completed < MIN_REFERENCE_SAMPLE:
        return "樣本不足，不直接影響決策；只作追蹤參考。"
    avg_return = _num(profile.get("avg_return_5d"))
    win_rate = _num(profile.get("win_rate_5d"))
    if avg_return > 1 and win_rate >= 50:
        return "同條件歷史偏正向，可以保留在優先觀察名單。"
    if avg_return < 0 or win_rate < 42:
        return "同條件歷史偏弱，避免開盤直接追價。"
    return "同條件歷史中性，仍以開盤價量確認為準。"


def _reference_label(candidate: dict) -> str:
    profile = candidate.get("historical_profile") or {}
    completed = int(profile.get("completed") or 0)
    if completed < MIN_REFERENCE_SAMPLE:
        return "樣本不足"
    avg_return = _num(profile.get("avg_return_5d"))
    win_rate = _num(profile.get("win_rate_5d"))
    if avg_return > 1 and win_rate >= 50:
        return "同條件偏強"
    if avg_return < 0 or win_rate < 42:
        return "同條件偏弱"
    return "同條件中性"


def _append_note(text: object, note: str) -> str:
    base = str(text or "").strip()
    if not base:
        return note
    if note in base:
        return base
    return f"{base}；{note}"


def _confidence_label(completed: int) -> str:
    if completed >= 30:
        return "高"
    if completed >= MIN_REFERENCE_SAMPLE:
        return "中"
    return "低"


def _pct(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return count / total * 100


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize(value: str) -> str:
    return "".join(str(value).split()).lower()
