from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.scoring.score_engine import StockScore


TRUSTED_STATUSES = {"pending_validation", "backtest_supported", "live_supported", "adopted"}
NEGATIVE_TERMS = {
    "失敗",
    "風險",
    "過熱",
    "追高",
    "轉弱",
    "外資賣",
    "融資增",
    "散戶增",
    "散戶過熱",
    "量價背離",
    "跌破",
}
POSITIVE_TERMS = {
    "成功",
    "有效",
    "轉強",
    "籌碼乾淨",
    "散戶減",
    "法人同步",
    "放量長紅",
    "突破整理",
    "營收加速",
}
ACTION_DOWNGRADE = {
    "可追": "等拉回",
    "可追蹤突破": "等拉回",
}


def load_knowledge_context(root: Path, limit: int = 80) -> dict[str, Any]:
    """Load compact Trading Knowledge Hub context.

    Priority:
    1. data/trading_hub_context.json generated from the local MCP hub.
    2. data/knowledge_exports/taiwan_stock_learning.jsonl committed by automation.

    The loader is intentionally tolerant: malformed lines or legacy mojibake rows
    are skipped instead of blocking the daily report.
    """
    context_file = root / "data" / "trading_hub_context.json"
    if context_file.exists():
        try:
            payload = json.loads(context_file.read_text(encoding="utf-8"))
            rows = payload.get("rows") if isinstance(payload, dict) else []
            if isinstance(rows, list):
                payload["rows"] = rows[:limit]
                payload["source"] = "trading_hub_context"
                return payload
        except Exception:
            pass

    export_file = root / "data" / "knowledge_exports" / "taiwan_stock_learning.jsonl"
    rows: list[dict[str, Any]] = []
    if export_file.exists():
        parsed_rows: list[dict[str, Any]] = []
        for line in export_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                parsed_rows.append(item)
        rows = sorted(parsed_rows, key=_row_sort_key, reverse=True)[:limit]

    return {
        "ok": bool(rows),
        "source": "knowledge_export" if rows else "none",
        "rows": rows,
        "used_count": len(rows),
    }


def apply_knowledge_adjustment(score: StockScore, context: dict[str, Any] | None) -> None:
    """Use validated historical lessons to conservatively adjust operation action.

    This layer does not modify total_score or grade. It may downgrade the trading
    action when a high-confidence failure pattern is matched, and it records
    positive matches as notes only. This keeps the UI simple while preserving
    evidence for future postmortems.
    """
    rows = (context or {}).get("rows") or []
    if not rows:
        return

    features = _score_features(score)
    negative_matches: list[str] = []
    positive_matches: list[str] = []

    for row in rows:
        if not isinstance(row, dict) or not _is_usable(row):
            continue
        text = _row_text(row)
        if not _matches_score(text, row.get("tags") or [], features):
            continue
        topic = str(row.get("topic") or "智慧庫經驗")[:40]
        if _is_negative(row, text):
            negative_matches.append(topic)
        elif _is_positive(row, text):
            positive_matches.append(topic)

    if not negative_matches and not positive_matches:
        return

    original_action = score.action
    adjusted_action = original_action
    notes: list[str] = []

    if negative_matches:
        adjusted_action = ACTION_DOWNGRADE.get(original_action, original_action)
        notes.append(f"智慧庫風險命中：{_join_topics(negative_matches)}")
        if adjusted_action != original_action:
            notes.append(f"操作由 {original_action} 降為 {adjusted_action}")
            score.action = adjusted_action
    if positive_matches:
        notes.append(f"智慧庫正向經驗：{_join_topics(positive_matches)}")

    score.knowledge_notes = notes
    score.knowledge_adjustment = {
        "source": (context or {}).get("source", ""),
        "original_action": original_action,
        "adjusted_action": adjusted_action,
        "negative_matches": negative_matches[:5],
        "positive_matches": positive_matches[:5],
    }
    score.reasons.setdefault("knowledge", []).extend(notes)
    if "智慧庫修正" not in score.trigger_tags:
        score.trigger_tags.append("智慧庫修正")
    if negative_matches:
        score.warnings.append(notes[0])


def _score_features(score: StockScore) -> set[str]:
    values: list[str] = [
        score.action,
        score.entry_decision,
        score.trigger_summary,
        *score.trigger_tags,
        *score.pattern_tags,
        *score.pattern_risk_tags,
        *score.themes,
        *score.theme_tiers,
        *score.selection_quality_notes,
    ]
    for reason_rows in (score.reasons or {}).values():
        values.extend(str(item) for item in reason_rows)
    return {_normalize(item) for item in values if _normalize(item)}


def _is_usable(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "")
    confidence = _float(row.get("confidence"))
    return status in TRUSTED_STATUSES or confidence >= 0.65


def _row_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("topic"),
        row.get("claim"),
        row.get("evidence"),
        " ".join(str(tag) for tag in (row.get("tags") or [])),
    ]
    return " ".join(str(part) for part in parts if part)


def _row_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Prefer the newest exported lessons so recent postmortems are actually used."""
    return (
        str(row.get("updated_at") or ""),
        str(row.get("created_at") or ""),
        str(row.get("source_ref") or ""),
    )


def _matches_score(text: str, tags: list[Any], features: set[str]) -> bool:
    haystack = _normalize(text)
    if any(feature and feature in haystack for feature in features):
        return True
    for tag in tags:
        normalized = _normalize(str(tag))
        if normalized and normalized in features:
            return True
    return False


def _is_negative(row: dict[str, Any], text: str) -> bool:
    normalized = _normalize(text)
    if any(_normalize(term) in normalized for term in NEGATIVE_TERMS):
        return True
    return _avg_return(text) is not None and _avg_return(text) < 0


def _is_positive(row: dict[str, Any], text: str) -> bool:
    normalized = _normalize(text)
    if any(_normalize(term) in normalized for term in POSITIVE_TERMS):
        return True
    avg = _avg_return(text)
    return avg is not None and avg > 0


def _avg_return(text: str) -> float | None:
    patterns = [
        r"平均報酬\s*([+-]?\d+(?:\.\d+)?)%",
        r"avg_return_5d[=:]\s*([+-]?\d+(?:\.\d+)?)",
        r"5\s*日.*?([+-]?\d+(?:\.\d+)?)%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _float(match.group(1))
    return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _join_topics(items: list[str]) -> str:
    unique = list(dict.fromkeys(items))
    return "、".join(unique[:3])
