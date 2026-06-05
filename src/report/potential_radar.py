from __future__ import annotations

from datetime import date
from typing import Any


def build_potential_radar_candidates(rows: list[dict], as_of: date, limit: int = 12) -> list[dict]:
    """Build early-stage candidates from enriched dashboard rows.

    This is intentionally not a buy list. It looks for "not yet overheated"
    names where several early conditions are starting to align: cleaner retail
    structure, constructive candles, warming themes, initial institutional
    support, and acceptable but not exhausted strength.
    """
    candidates: list[dict] = []
    for row in rows:
        stock_id = str(row.get("stock_id") or "")
        if not stock_id or row.get("label") == "DATA_INSUFFICIENT":
            continue
        if str(row.get("decision_light") or "") == "red":
            continue

        score = _int(row.get("score"))
        grade = str(row.get("grade") or "")
        if score < 55 or score >= 96:
            continue

        points, tags = _score_row(row, score, grade)
        if points < 5:
            continue

        candidates.append(
            {
                "signal_date": as_of.isoformat(),
                "stock_id": stock_id,
                "name": row.get("name") or "",
                "grade": grade,
                "total_score": score,
                "potential_score": points,
                "action": row.get("entry_decision") or row.get("action") or "",
                "themes": list(row.get("themes") or []),
                "entry_price": row.get("price"),
                "return_3d": None,
                "return_5d": None,
                "entry_triggered": None,
                "tags": _dedupe(tags)[:10],
                "reason": _reason(points, tags),
            }
        )

    candidates.sort(
        key=lambda item: (
            int(item.get("potential_score") or 0),
            _early_bonus(item),
            int(item.get("total_score") or 0),
            len(item.get("themes") or []),
        ),
        reverse=True,
    )
    return candidates[:limit]


def _score_row(row: dict[str, Any], score: int, grade: str) -> tuple[int, list[str]]:
    points = 0
    tags: list[str] = []

    retail_text = _text(row.get("retail_context"), row.get("retail_context_reason"))
    if _has_any(retail_text, ["籌碼轉乾淨", "散戶減少", "人數減少"]):
        points += 3
        tags.append("散戶減少/籌碼轉乾淨")
    elif _has_any(retail_text, ["觀察轉乾淨", "散戶降溫"]):
        points += 2
        tags.append("觀察轉乾淨")
    if _has_any(retail_text, ["散戶過熱", "散戶增加", "人數增加"]):
        points -= 3
        tags.append("散戶過熱")

    pattern_tags = [str(tag) for tag in row.get("pattern_tags") or [] if tag]
    pattern_risks = [str(tag) for tag in row.get("pattern_risk_tags") or [] if tag]
    if pattern_tags and not pattern_risks:
        points += 2
        tags.append(f"K線轉強:{pattern_tags[0]}")
    elif pattern_risks:
        points -= 2
        tags.append(f"K線風險:{pattern_risks[0]}")

    themes = [str(theme) for theme in row.get("themes") or [] if theme]
    if themes:
        points += 2 if _int(row.get("opportunity_score")) >= 5 else 1
        tags.append(f"題材升溫:{themes[0]}")

    trigger_text = _text(row.get("trigger_summary"), *(row.get("trigger_tags") or []))
    if _has_any(trigger_text, ["法人共振", "投信買超", "外資買超"]):
        points += 2
        tags.append("法人開始同步")
    if _has_any(trigger_text, ["放量長紅", "突破整理", "技術突破"]):
        points += 2
        tags.append("量價開始轉強")
    if _has_any(trigger_text, ["放量不漲", "量能失衡"]):
        points -= 2
        tags.append("量價背離風險")

    if 75 <= score < 96:
        points += 2
        tags.append("分數已成形")
    elif 60 <= score < 75:
        points += 1
        tags.append("分數醞釀中")

    decision_text = _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    if _has_any(decision_text, ["等拉回", "等待拉回"]):
        points += 2
        tags.append("強勢但等拉回")
    elif _has_any(decision_text, ["只觀察", "觀察"]):
        points += 1
        tags.append("尚在低檔觀察")
    if _has_any(decision_text, ["避免", "避開", "不追"]):
        points -= 3
        tags.append("避開訊號")

    if grade in {"A", "B"}:
        points += 1
        tags.append("尚未過熱強度")
    elif grade == "S":
        points += 1
        tags.append("強度中高")

    if _has_any(_text(row.get("risk"), row.get("warnings")), ["風險偏高", "資料不足"]):
        points -= 1
        tags.append("風險需複核")

    return points, tags


def _reason(points: int, tags: list[str]) -> str:
    clean_tags = _dedupe([tag for tag in tags if tag])
    if clean_tags:
        return f"潛力分 {points}：{' + '.join(clean_tags[:5])}"
    return f"潛力分 {points}：多項早期條件開始聚集"


def _early_bonus(item: dict[str, Any]) -> int:
    tags = " ".join(item.get("tags") or [])
    bonus = 0
    if "尚未過熱強度" in tags or "分數醞釀中" in tags:
        bonus += 2
    if "強勢但等拉回" in tags or "尚在低檔觀察" in tags:
        bonus += 1
    if "量價背離風險" in tags or "散戶過熱" in tags:
        bonus -= 3
    return bonus


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _text(*values: Any) -> str:
    return " ".join(str(value) for value in values if value is not None)


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
