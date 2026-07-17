from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


MIN_FEEDBACK_COMPLETED = 10
WEAK_FEEDBACK_WIN_RATE = 45.0
WEAK_FEEDBACK_AVG_RETURN = 0.0


def load_potential_feedback(root: Path) -> dict[str, Any]:
    """Load prior potential-radar outcomes as internal-only calibration.

    The feedback is intentionally conservative: only buckets with enough
    completed outcomes can reduce candidate priority. It never promotes a stock
    and never blocks the daily report when the file is missing or malformed.
    """
    path = root / "dashboard" / "potential_data.json"
    if not path.exists():
        return {"active": False, "weak": {}, "as_of": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"active": False, "weak": {}, "as_of": None}
    radar = payload.get("potential_radar") if isinstance(payload, dict) else {}
    if not isinstance(radar, dict):
        return {"active": False, "weak": {}, "as_of": payload.get("as_of") if isinstance(payload, dict) else None}

    weak: dict[str, dict[str, dict[str, Any]]] = {
        "stage": {},
        "factor": {},
        "lifecycle": {},
        "smart_money": {},
        "combo": {},
    }
    sources = {
        "stage": radar.get("stage_stats") or [],
        "factor": radar.get("factor_stats") or [],
        "lifecycle": radar.get("lifecycle_stats") or [],
        "smart_money": radar.get("smart_money_stats") or [],
        "combo": radar.get("combo_stats") or [],
    }
    for group, rows in sources.items():
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "")
            completed = _int(row.get("completed"))
            win_rate = _float(row.get("win_rate_5d"))
            avg_return = _float(row.get("avg_return_5d"))
            if not label or completed < MIN_FEEDBACK_COMPLETED:
                continue
            if (
                (win_rate is not None and win_rate < WEAK_FEEDBACK_WIN_RATE)
                or (avg_return is not None and avg_return < WEAK_FEEDBACK_AVG_RETURN)
            ):
                weak[group][label] = {
                    "label": label,
                    "completed": completed,
                    "win_rate_5d": win_rate,
                    "avg_return_5d": avg_return,
                }

    return {
        "active": any(weak[group] for group in weak),
        "as_of": payload.get("as_of") if isinstance(payload, dict) else None,
        "weak": weak,
    }


def build_potential_radar_candidates(
    rows: list[dict],
    as_of: date,
    limit: int = 12,
    feedback: dict[str, Any] | None = None,
) -> list[dict]:
    """Build early-stage candidates from enriched dashboard rows.

    The potential radar is a research queue, not a buy list. It intentionally
    excludes names that are already actionable on today's decision card, then
    looks for early accumulation, constructive K-line signals, warming themes,
    and acceptable but not exhausted strength.
    """
    candidates: list[dict] = []
    for row in rows:
        stock_id = str(row.get("stock_id") or "")
        if not stock_id or row.get("label") == "DATA_INSUFFICIENT":
            continue
        if str(row.get("decision_light") or "") == "red":
            continue
        if _is_actionable_today(row):
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
        lifecycle = _lifecycle_stage(row, score, grade, tags, chase_risk["level"])
        smart_money = _smart_money_signal(row, score, grade, tags, chase_risk["level"])
        if smart_money["key"] == "lead":
            points += 2
            tags.append("主力先行")
        elif smart_money["key"] == "sync":
            tags.append("法人同步")

        research = _research_filter(row, score, grade, tags, chase_risk["level"])
        stock_type = _stock_type(row, score, grade, tags, stage["key"])
        position = _position_hint(row, chase_risk["level"])
        combo = _signal_combo(lifecycle["label"], smart_money["label"], tags)
        feedback_result = _feedback_adjustment(
            feedback,
            stage_label=stage["label"],
            lifecycle_label=lifecycle["label"],
            smart_money_label=smart_money["label"],
            combo=combo,
            tags=tags,
        )
        points -= feedback_result["penalty"]
        tags.extend(feedback_result["tags"])
        if points < 5:
            continue
        tags.extend(
            [
                f"生命週期:{lifecycle['label']}",
                f"資金型態:{smart_money['label']}",
                f"訊號組合:{combo}",
                f"研究快篩:{research['label']}",
                f"股票類型:{stock_type['label']}",
                f"部位提示:{position['label']}",
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
                "feedback_penalty": feedback_result["penalty"],
                "feedback_notes": feedback_result["notes"],
                "lifecycle_stage": lifecycle["key"],
                "lifecycle_stage_label": lifecycle["label"],
                "lifecycle_reason": lifecycle["reason"],
                "smart_money": smart_money["key"],
                "smart_money_label": smart_money["label"],
                "smart_money_reason": smart_money["reason"],
                "smart_money_score": smart_money["score"],
                "branch_zscore_proxy": smart_money["zscore"],
                "institutional_follow": smart_money["institutional_follow"],
                "signal_combo": combo,
                "tags": _dedupe(tags)[:12],
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


def _feedback_adjustment(
    feedback: dict[str, Any] | None,
    *,
    stage_label: str,
    lifecycle_label: str,
    smart_money_label: str,
    combo: str,
    tags: list[str],
) -> dict[str, Any]:
    if not feedback or not feedback.get("active"):
        return {"penalty": 0, "tags": [], "notes": []}
    weak = feedback.get("weak") or {}
    matches: list[dict[str, Any]] = []
    checks = [
        ("stage", stage_label),
        ("lifecycle", lifecycle_label),
        ("smart_money", smart_money_label),
        ("combo", combo),
    ]
    for group, label in checks:
        item = (weak.get(group) or {}).get(label)
        if item:
            matches.append(item)
    for tag in tags:
        label = _potential_factor_label(tag)
        item = (weak.get("factor") or {}).get(label)
        if item:
            matches.append(item)

    unique: dict[str, dict[str, Any]] = {}
    for item in matches:
        unique[str(item.get("label") or "")] = item
    rows = [item for item in unique.values() if item.get("label")]
    if not rows:
        return {"penalty": 0, "tags": [], "notes": []}

    penalty = min(4, 2 + max(0, len(rows) - 1))
    notes = [
        (
            f"{row['label']} 近30日完成 {row.get('completed')} 筆，"
            f"5日勝率 {_fmt_pct(row.get('win_rate_5d'))}，"
            f"平均 {_fmt_pct(row.get('avg_return_5d'))}"
        )
        for row in rows[:3]
    ]
    return {
        "penalty": penalty,
        "tags": [f"成效降權:{row['label']}" for row in rows[:2]],
        "notes": notes,
    }


def _potential_factor_label(tag: str) -> str:
    if tag.startswith("題材升溫:"):
        return "題材升溫"
    if tag.startswith("K線轉強:"):
        return "K線轉強"
    if tag.startswith("K線風險:"):
        return "K線風險"
    if tag.startswith("追高檢查:"):
        return tag
    if tag.startswith("研究快篩:"):
        return tag.split(":", 1)[1]
    if tag.startswith("股票類型:"):
        return tag.split(":", 1)[1]
    if tag.startswith("部位提示:"):
        return tag.split(":", 1)[1]
    if tag.startswith("生命週期:"):
        return tag.split(":", 1)[1]
    if tag.startswith("資金型態:"):
        return tag.split(":", 1)[1]
    if tag.startswith("訊號組合:"):
        return tag.split(":", 1)[1]
    return tag


def _fmt_pct(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _is_actionable_today(row: dict[str, Any]) -> bool:
    text = _text(
        row.get("entry_decision"),
        row.get("action"),
        row.get("action_context"),
        row.get("action_context_reason"),
        row.get("trigger_summary"),
    )
    if _has_any(text, ["可追", "開盤確認", "綠燈可盯"]):
        return True
    return str(row.get("decision_light") or "") == "green" and _int(row.get("score")) >= 85


def _score_row(row: dict[str, Any], score: int, grade: str) -> tuple[int, list[str]]:
    points = 0
    tags: list[str] = []

    retail_text = _text(row.get("retail_context"), row.get("retail_context_reason"))
    if _has_any(retail_text, ["散戶減少", "籌碼轉乾淨", "持股人數減少"]):
        points += 3
        tags.append("散戶減少/籌碼轉乾淨")
    elif _has_any(retail_text, ["散戶轉乾淨", "籌碼改善"]):
        points += 2
        tags.append("籌碼改善")
    if _has_any(retail_text, ["散戶增加", "散戶過熱", "持股人數增加"]):
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
    if _has_any(trigger_text, ["法人共振", "外資買超", "投信買超"]):
        points += 2
        tags.append("法人開始同步")
    if _has_any(trigger_text, ["放量長紅", "突破整理", "量能轉強"]):
        points += 2
        tags.append("量價開始轉強")
    if _has_any(trigger_text, ["放量不漲", "量縮背離"]):
        points -= 2
        tags.append("量能無承接")

    if 75 <= score < 96:
        points += 2
        tags.append("強度中高")
    elif 60 <= score < 75:
        points += 1
        tags.append("分數初成形")

    decision_text = _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    if _has_any(decision_text, ["等拉回", "等待拉回"]):
        points += 2
        tags.append("強勢但等拉回")
    elif _has_any(decision_text, ["觀察", "等待"]):
        points += 1
        tags.append("仍在觀察")
    if _has_any(decision_text, ["避開", "避免", "不建議"]):
        points -= 3
        tags.append("暫不研究")

    if grade in {"A", "B"}:
        points += 1
        tags.append("尚未過熱強度")
    elif grade == "S":
        points += 1
        tags.append("強度已成形")

    if _has_any(_text(row.get("risk"), row.get("warnings")), ["風險偏高", "資料不足"]):
        points -= 1
        tags.append("風險條件待確認")

    return points, tags


def _research_filter(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, Any]:
    """Compact 10-factor checklist inspired by the user's research notes."""
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
        _factor("theme", "產業題材", bool(row.get("themes")), "公司已對應到題材或供應鏈"),
        _factor("catalyst", "催化劑", _int(row.get("opportunity_score")) >= 5 or _has_any(text, ["題材升溫", "題材強共振", "催化", "新產品", "訂單"]), "題材熱度或催化正在升溫"),
        _factor("revenue", "營收加速", _int(row.get("fundamental_score")) >= 12 or _has_any(text, ["營收", "年增", "月增", "新高", "加速"]), "營收或基本面有改善訊號"),
        _factor("valuation_risk", "估值風險", not _has_any(text, ["本益比過高", "估值過高", "風險偏高", "紅色警戒"]), "未出現明顯估值或風險警訊"),
        _factor("institutional", "法人籌碼", _int(row.get("chip_score")) >= 12 or _has_any(text, ["法人共振", "外資買超", "投信買超"]), "法人或籌碼面有支撐"),
        _factor("retail_clean", "散戶籌碼", _has_any(text, ["散戶減少", "籌碼轉乾淨", "散戶轉乾淨"]), "散戶籌碼未明顯過熱"),
        _factor("technical", "技術型態", _int(row.get("technical_score")) >= 12 or bool(row.get("pattern_tags")), "技術面或 K 線型態轉強"),
        _factor("volume", "量能活躍", _has_any(text, ["放量長紅", "突破整理", "量能轉強", "量價開始轉強"]), "成交量有放大跡象"),
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
        label = "資料不足"
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
    if theme_tiers.intersection({"beneficiary", "speculative"}) or _has_any(text, ["受惠", "二階", "供應鏈"]):
        return {"key": "tier2_beneficiary", "label": "二階受惠型"}
    if _has_any(themes + " " + text, ["景氣", "循環", "原物料", "面板", "塑化", "鋼鐵", "航運", "水泥"]):
        return {"key": "cyclical_recovery", "label": "景氣反轉型"}
    if stage_key == "early_turn" or _has_any(text, ["轉強", "落底", "初動", "突破整理", "量能轉強"]):
        return {"key": "turnaround_confirmed", "label": "轉機確認型"}
    return {"key": "research_watch", "label": "研究觀察型"}


def _position_hint(row: dict[str, Any], chase_risk: str) -> dict[str, str]:
    atr = _float(row.get("atr_pct"))
    if chase_risk == "high":
        return {"key": "avoid_chase", "label": "避免追價"}
    if atr is None:
        return {"key": "unknown", "label": "部位待估"}
    if atr >= 8:
        return {"key": "small", "label": "小部位"}
    if atr >= 5:
        return {"key": "half", "label": "半部位"}
    return {"key": "normal", "label": "正常部位"}


def _reason(points: int, tags: list[str], stage_label: str = "", chase_label: str = "") -> str:
    clean_tags = _dedupe([tag for tag in tags if tag])
    prefix = f"{stage_label}｜" if stage_label else ""
    suffix = f"｜{chase_label}" if chase_label else ""
    if clean_tags:
        return f"{prefix}潛力分 {points}｜{' + '.join(clean_tags[:5])}{suffix}"
    return f"{prefix}潛力分 {points}｜條件正在累積{suffix}"


def _stage(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, str]:
    tag_text = " ".join(tags)
    decision_text = _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    if _has_any(tag_text, ["強勢但等拉回"]) or _has_any(decision_text, ["等拉回", "等待拉回"]):
        return {"key": "pullback_watch", "label": "強勢等拉回"}
    if score >= 80 or grade in {"S", "A"}:
        return {"key": "early_turn", "label": "轉強初動"}
    if chase_risk == "medium":
        return {"key": "wait_cooldown", "label": "降溫等待"}
    return {"key": "low_base", "label": "低位醞釀"}


def _lifecycle_stage(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, str]:
    text = _text(
        row.get("trigger_summary"),
        row.get("technical"),
        row.get("risk"),
        *(row.get("trigger_tags") or []),
        *tags,
    )
    if chase_risk == "high" or score >= 94 or grade == "S+" or _has_any(text, ["過熱", "追高", "20日高", "漲停"]):
        return {"key": "extended", "label": "過熱/延伸", "reason": "分數或價格位置已偏高，僅追蹤不作為早期訊號。"}
    if score >= 80 or grade in {"A", "S"} or _has_any(text, ["突破", "站上", "法人", "外資"]):
        return {"key": "maturing", "label": "成熟", "reason": "訊號已成形，需等待開盤價量或回測驗證。"}
    return {"key": "fresh", "label": "初動", "reason": "題材或籌碼開始靠攏，但分數尚未完全反映。"}


def _smart_money_signal(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, Any]:
    text = _text(
        row.get("trigger_summary"),
        row.get("chip"),
        row.get("technical"),
        row.get("retail_context"),
        row.get("retail_context_reason"),
        *(row.get("trigger_tags") or []),
        *tags,
    )
    opportunity = _int(row.get("opportunity_score"))
    chip = _int(row.get("chip_score"))
    technical = _int(row.get("technical_score"))
    zscore = round(min(4.5, max(0.0, opportunity / 4 + max(0, technical - 10) / 12 + max(0, chip) / 18)), 2)
    institutional_follow = _has_any(text, ["外資", "投信", "法人買", "法人共振", "外資買超", "投信買超"]) or chip >= 14
    retail_clean = _has_any(text, ["散戶減少", "籌碼轉乾淨", "散戶轉乾淨"])
    price_ready = _has_any(text, ["突破", "站上", "放量", "量能", "轉強"])

    if zscore >= 2.4 and not institutional_follow and chase_risk != "high":
        return {
            "key": "lead",
            "label": "主力先行",
            "score": int(round(zscore * 20 + (10 if retail_clean else 0))),
            "zscore": zscore,
            "institutional_follow": False,
            "reason": "量價或籌碼先動，但法人尚未明確追上；適合列為提前觀察。",
        }
    if institutional_follow and (price_ready or score >= 80):
        return {
            "key": "sync",
            "label": "法人同步",
            "score": int(round(zscore * 15 + 20)),
            "zscore": zscore,
            "institutional_follow": True,
            "reason": "法人訊號已跟上，較偏確認型訊號。",
        }
    return {
        "key": "none",
        "label": "資金待確認",
        "score": int(round(zscore * 10)),
        "zscore": zscore,
        "institutional_follow": bool(institutional_follow),
        "reason": "尚未看出主力先行或法人同步，維持觀察。",
    }


def _signal_combo(lifecycle_label: str, smart_money_label: str, tags: list[str]) -> str:
    factors: list[str] = []
    if any("題材升溫" in tag for tag in tags):
        factors.append("題材")
    if any("籌碼轉乾淨" in tag or "散戶減少" in tag for tag in tags):
        factors.append("散戶")
    if any("K線轉強" in tag for tag in tags):
        factors.append("K線")
    if smart_money_label in {"主力先行", "法人同步"}:
        factors.append(smart_money_label)
    if not factors:
        factors.append("一般")
    return f"{lifecycle_label}|" + "+".join(_dedupe(factors)[:4])


def _chase_risk(row: dict[str, Any], score: int, grade: str) -> dict[str, str]:
    decision_text = _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    trigger_text = _text(row.get("trigger_summary"), *(row.get("trigger_tags") or []))
    price = _float(row.get("price"))
    entry_limit = _float(row.get("entry_limit_price"))

    if price is not None and entry_limit is not None and price > entry_limit:
        return {"level": "high", "label": f"價格已高於進場上限 {entry_limit:g}"}
    if grade == "S+" or score >= 96:
        return {"level": "high", "label": "分數過熱"}
    if _has_any(decision_text, ["避免追高", "不建議", "避開"]):
        return {"level": "high", "label": "操作建議避免追價"}
    if score >= 90 and _has_any(trigger_text, ["放量長紅", "突破整理"]):
        return {"level": "medium", "label": "追高風險，等回測確認"}
    return {"level": "low", "label": "尚未過熱"}


def _early_bonus(item: dict[str, Any]) -> int:
    tags = " ".join(item.get("tags") or [])
    bonus = 0
    if "尚未過熱強度" in tags or "分數初成形" in tags:
        bonus += 2
    if "強勢但等拉回" in tags or "仍在觀察" in tags:
        bonus += 1
    if "量能無承接" in tags or "散戶過熱" in tags:
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
