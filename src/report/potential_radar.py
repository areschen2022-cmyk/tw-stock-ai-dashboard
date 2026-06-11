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
        chase_risk = _chase_risk(row, score, grade)
        if chase_risk["level"] == "high":
            continue
        if chase_risk["level"] == "medium":
            points -= 2
            tags.append(chase_risk["label"])
        if points < 5:
            continue
        stage = _stage(row, score, grade, tags, chase_risk["level"])
        research = _research_filter(row, score, grade, tags, chase_risk["level"])
        stock_type = _stock_type(row, score, grade, tags, stage["key"])
        position = _position_hint(row, chase_risk["level"])
        tags.extend(
            [
                f"快篩:{research['label']}",
                f"類型:{stock_type['label']}",
                f"部位:{position['label']}",
            ]
        )

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
                "stage": stage["key"],
                "stage_label": stage["label"],
                "chase_risk": chase_risk["level"],
                "chase_risk_label": chase_risk["label"],
                "research_score": research["score"],
                "research_label": research["label"],
                "research_factors": research["factors"],
                "stock_type": stock_type["key"],
                "stock_type_label": stock_type["label"],
                "position_hint": position["key"],
                "position_hint_label": position["label"],
                "tags": _dedupe(tags)[:10],
                "reason": _reason(points, tags, stage["label"], chase_risk["label"]),
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


def _research_filter(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, Any]:
    """Compact version of the image-inspired 10-factor research checklist.

    The result is a research completeness signal, not a buy/sell rule. It is stored
    for later attribution so we can learn which factors actually helped.
    """
    text = _text(
        row.get("trigger_summary"),
        row.get("technical"),
        row.get("chip"),
        row.get("fundamental"),
        row.get("risk"),
        row.get("opportunity"),
        row.get("retail_context"),
        *(row.get("trigger_tags") or []),
        *tags,
    )
    factors = [
        _factor("market_strength", "市場/強度", score >= 75 or grade in {"S", "A"}, "分數或強度已到研究門檻"),
        _factor("theme", "產業題材", bool(row.get("themes")), "有明確題材或供應鏈位置"),
        _factor("catalyst", "催化劑", _int(row.get("opportunity_score")) >= 5 or _has_any(text, ["題材升溫", "題材強共振", "催化", "新產品", "訂單"]), "題材熱度或催化正在升溫"),
        _factor("revenue", "營收加速", _int(row.get("fundamental_score")) >= 12 or _has_any(text, ["營收", "年增", "月增", "新高", "加速"]), "營收或基本面有改善訊號"),
        _factor("valuation_risk", "估值風險", not _has_any(text, ["本益比過高", "估值過高", "風險偏高", "紅色警戒"]), "未出現明顯估值或風險警訊"),
        _factor("institutional", "法人籌碼", _int(row.get("chip_score")) >= 12 or _has_any(text, ["法人共振", "外資買超", "投信買超"]), "法人或籌碼面有支撐"),
        _factor("retail_clean", "散戶結構", _has_any(text, ["籌碼轉乾淨", "散戶減少", "觀察轉乾淨"]), "散戶籌碼沒有過熱"),
        _factor("technical", "技術型態", _int(row.get("technical_score")) >= 12 or bool(row.get("pattern_tags")), "技術面或 K 線型態轉強"),
        _factor("volume", "量能確認", _has_any(text, ["放量長紅", "突破整理", "技術突破", "量價開始轉強"]), "量價有初步確認"),
        _factor("overheat_guard", "過熱排除", chase_risk != "high" and not row.get("pattern_risk_tags") and score < 96, "未進入明顯追高或型態風險區"),
    ]
    passed = sum(1 for item in factors if item["passed"])
    if passed >= 7:
        label = "順風研究"
    elif passed >= 5:
        label = "正常篩選"
    elif passed >= 3:
        label = "降溫等待"
    else:
        label = "先停手"
    return {"score": passed, "label": label, "factors": factors}


def _factor(key: str, label: str, passed: bool, reason: str) -> dict[str, Any]:
    return {"key": key, "label": label, "passed": bool(passed), "reason": reason}


def _stock_type(row: dict[str, Any], score: int, grade: str, tags: list[str], stage_key: str) -> dict[str, str]:
    text = _text(
        row.get("trigger_summary"),
        row.get("fundamental"),
        row.get("opportunity"),
        *(row.get("themes") or []),
        *(row.get("theme_tiers") or []),
        *tags,
    )
    theme_tiers = {str(item) for item in row.get("theme_tiers") or []}
    themes = " ".join(str(item) for item in row.get("themes") or [])
    if (
        score >= 80
        and _has_any(text, ["營收", "年增", "新高", "營收加速", "最新月營收"])
        and bool(row.get("themes"))
    ):
        return {"key": "growth_confirmed", "label": "成長確認型"}
    if theme_tiers.intersection({"beneficiary", "speculative"}) or _has_any(text, ["二階", "受惠", "供應鏈"]):
        return {"key": "tier2_beneficiary", "label": "二階受惠型"}
    if _has_any(themes + " " + text, ["記憶體", "面板", "原物料", "低基期", "景氣", "塑膠", "鋼鐵", "水泥"]):
        return {"key": "cyclical_recovery", "label": "景氣反轉型"}
    if stage_key == "early_turn" or _has_any(text, ["轉機", "復甦", "改善", "突破整理", "技術突破"]):
        return {"key": "turnaround_confirmed", "label": "轉機確認型"}
    return {"key": "research_watch", "label": "研究觀察型"}


def _position_hint(row: dict[str, Any], chase_risk: str) -> dict[str, str]:
    atr = _float(row.get("atr_pct"))
    if chase_risk == "high":
        return {"key": "avoid_chase", "label": "不追價"}
    if atr is None:
        return {"key": "unknown", "label": "部位未定"}
    if atr >= 8:
        return {"key": "small", "label": "小部位"}
    if atr >= 5:
        return {"key": "half", "label": "半部位"}
    return {"key": "normal", "label": "正常部位"}


def _reason(points: int, tags: list[str], stage_label: str = "", chase_label: str = "") -> str:
    clean_tags = _dedupe([tag for tag in tags if tag])
    prefix = f"{stage_label}｜" if stage_label else ""
    suffix = f"；{chase_label}" if chase_label else ""
    if clean_tags:
        return f"{prefix}潛力分 {points}：{' + '.join(clean_tags[:5])}{suffix}"
    return f"{prefix}潛力分 {points}：多項早期條件開始聚集{suffix}"


def _stage(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, str]:
    tag_text = " ".join(tags)
    decision_text = _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    if _has_any(tag_text, ["強勢但等拉回"]) or _has_any(decision_text, ["等拉回", "等待拉回"]):
        return {"key": "pullback_watch", "label": "強勢等拉回"}
    if score >= 80 or grade in {"S", "A"}:
        return {"key": "early_turn", "label": "轉強初動"}
    if chase_risk == "medium":
        return {"key": "wait_cooldown", "label": "降溫觀察"}
    return {"key": "low_base", "label": "低位醞釀"}


def _chase_risk(row: dict[str, Any], score: int, grade: str) -> dict[str, str]:
    decision_text = _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    trigger_text = _text(row.get("trigger_summary"), *(row.get("trigger_tags") or []))
    price = _float(row.get("price"))
    entry_limit = _float(row.get("entry_limit_price"))

    if price is not None and entry_limit is not None and price > entry_limit:
        return {"level": "high", "label": f"價格已高於進場上限 {entry_limit:g}"}
    if grade == "S+" or score >= 96:
        return {"level": "high", "label": "已屬高強度追價區"}
    if _has_any(decision_text, ["避免追高", "不追", "避開"]):
        return {"level": "high", "label": "操作結論避免追高"}
    if score >= 90 and _has_any(trigger_text, ["放量長紅", "突破整理"]):
        return {"level": "medium", "label": "追高風險：強勢放量後需等拉回"}
    return {"level": "low", "label": "尚未過熱"}


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


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
