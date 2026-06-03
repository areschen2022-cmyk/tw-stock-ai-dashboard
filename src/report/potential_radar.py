from __future__ import annotations

from datetime import date


def build_potential_radar_candidates(rows: list[dict], as_of: date, limit: int = 12) -> list[dict]:
    """Build early-stage candidates from the already-enriched dashboard rows.

    The radar is intentionally not a buy list. It favors early confluence:
    improving holders, constructive candlesticks, live themes, and acceptable
    scores, while filtering out red-light risk rows and already overheated S+
    names.
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
        if score < 55 or score >= 95:
            continue

        points = 0
        tags: list[str] = []

        retail_text = f"{row.get('retail_context') or ''} {row.get('retail_context_reason') or ''}"
        if "籌碼轉乾淨" in retail_text:
            points += 3
            tags.append("散戶減少/籌碼轉乾淨")
        elif "觀察轉乾淨" in retail_text:
            points += 2
            tags.append("散戶觀察轉乾淨")
        if "散戶過熱" in retail_text:
            points -= 3
            tags.append("散戶過熱扣分")

        pattern_tags = list(row.get("pattern_tags") or [])
        pattern_risks = list(row.get("pattern_risk_tags") or [])
        if pattern_tags and not pattern_risks:
            points += 2
            tags.append(f"K線轉強:{pattern_tags[0]}")
        elif pattern_risks:
            points -= 2
            tags.append(f"K線風險:{pattern_risks[0]}")

        themes = list(row.get("themes") or [])
        if themes:
            points += 2 if _int(row.get("opportunity_score")) >= 5 else 1
            tags.append(f"題材升溫:{themes[0]}")

        if 75 <= score < 95:
            points += 2
            tags.append("分數已成形")
        elif 60 <= score < 75:
            points += 1
            tags.append("分數醞釀中")

        decision_text = f"{row.get('entry_decision') or ''} {row.get('action_context') or ''} {row.get('action_context_reason') or ''}"
        if "等拉回" in decision_text:
            points += 2
            tags.append("強勢但等拉回")
        elif "只觀察" in decision_text:
            points += 1
            tags.append("尚未正式進場")
        if "避免" in decision_text:
            points -= 3
            tags.append("操作避開扣分")

        if grade in {"A", "B"}:
            points += 1
            tags.append("非過熱強度")

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
                "themes": themes,
                "entry_price": row.get("price"),
                "return_3d": None,
                "return_5d": None,
                "entry_triggered": None,
                "tags": _dedupe(tags)[:8],
                "reason": _reason(points, tags),
            }
        )

    candidates.sort(
        key=lambda item: (
            int(item.get("potential_score") or 0),
            int(item.get("total_score") or 0),
            len(item.get("themes") or []),
        ),
        reverse=True,
    )
    return candidates[:limit]


def _reason(points: int, tags: list[str]) -> str:
    clean_tags = [tag for tag in _dedupe(tags) if "扣分" not in tag]
    if clean_tags:
        return f"潛力分 {points}：{' + '.join(clean_tags[:4])}"
    return f"潛力分 {points}：多項早期條件開始聚集"


def _int(value) -> int:
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
