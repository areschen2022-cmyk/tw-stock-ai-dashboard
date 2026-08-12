from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


MIN_FEEDBACK_COMPLETED = 10
WEAK_FEEDBACK_WIN_RATE = 45.0
WEAK_FEEDBACK_AVG_RETURN = 0.0


def load_potential_feedback(root: Path) -> dict[str, Any]:
    path = root / "dashboard" / "potential_data.json"
    weekly_path = root / "dashboard" / "weekly_review.json"
    weak = _weekly_potential_feedback(weekly_path)
    if not path.exists():
        return {"active": _has_feedback(weak), "weak": weak, "as_of": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"active": _has_feedback(weak), "weak": weak, "as_of": None}

    radar = payload.get("potential_radar") if isinstance(payload, dict) else {}
    if not isinstance(radar, dict):
        return {"active": _has_feedback(weak), "weak": weak, "as_of": payload.get("as_of") if isinstance(payload, dict) else None}

    for group, rows in {
        "stage": radar.get("stage_stats") or [],
        "factor": radar.get("factor_stats") or [],
        "lifecycle": radar.get("lifecycle_stats") or [],
        "smart_money": radar.get("smart_money_stats") or [],
        "combo": radar.get("combo_stats") or [],
    }.items():
        weak.setdefault(group, {})
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "")
            completed = _int(row.get("completed"))
            win_rate = _float(row.get("win_rate_5d"))
            avg_return = _float(row.get("avg_return_5d"))
            if not label or completed < MIN_FEEDBACK_COMPLETED:
                continue
            if (win_rate is not None and win_rate < WEAK_FEEDBACK_WIN_RATE) or (avg_return is not None and avg_return < WEAK_FEEDBACK_AVG_RETURN):
                weak[group][label] = {"label": label, "completed": completed, "win_rate_5d": win_rate, "avg_return_5d": avg_return}

    return {"active": _has_feedback(weak), "as_of": payload.get("as_of") if isinstance(payload, dict) else None, "weak": weak}


def build_potential_radar_candidates(rows: list[dict], as_of: date, limit: int = 12, feedback: dict[str, Any] | None = None) -> list[dict]:
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
        smart_money = _smart_money_signal(row, score, tags, chase_risk["level"])
        if smart_money["key"] == "lead":
            points += 2
            tags.append("法人未跟上")
        elif smart_money["key"] == "sync":
            tags.append("法人開始同步")

        research = _research_filter(row, score, grade, tags, chase_risk["level"])
        stock_type = _stock_type(row, score, tags, stage["key"])
        position = _position_hint(row, chase_risk["level"])
        combo = _signal_combo(lifecycle["label"], smart_money["label"], tags)
        layer = _radar_layer(stage, lifecycle, smart_money, score, grade, points)
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

        tags.extend([
            f"生命週期:{lifecycle['label']}",
            f"資金同步:{smart_money['label']}",
            f"資金型態:{smart_money['label']}",
            f"訊號組合:{combo}",
            f"研究:{research['label']}",
            f"類型:{stock_type['label']}",
            f"部位:{position['label']}",
        ])
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
                "radar_layer": layer["key"],
                "radar_layer_label": layer["label"],
                "tags": _priority_tags(tags, limit=12),
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
    unique: list[dict] = []
    seen: set[str] = set()
    for item in candidates:
        sid = str(item.get("stock_id") or "")
        if sid in seen:
            continue
        seen.add(sid)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _weekly_potential_feedback(path: Path) -> dict[str, dict[str, Any]]:
    weak: dict[str, dict[str, Any]] = {"stage": {}, "factor": {}, "lifecycle": {}, "smart_money": {}, "combo": {}}
    if not path.exists():
        return weak
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return weak
    weak_stage = ((payload.get("weak") or {}).get("potential_stage") or {})
    if isinstance(weak_stage, dict):
        _add_weekly_row(weak["stage"], weak_stage, default_reason="週檢討指出此階段偏弱")
    for item in payload.get("next_week_actions") or []:
        if not isinstance(item, dict) or str(item.get("type") or "") != "deweight":
            continue
        target = str(item.get("target") or "")
        if not target.startswith("潛力階段"):
            continue
        label = target.split(":", 1)[-1].strip()
        if label:
            weak["stage"].setdefault(label, {"label": label, "completed": MIN_FEEDBACK_COMPLETED, "win_rate_5d": None, "avg_return_5d": -0.1, "reason": item.get("reason") or "週檢討降權"})
    return weak


def _add_weekly_row(target: dict[str, Any], row: dict[str, Any], default_reason: str) -> None:
    label = str(row.get("label") or "")
    completed = _int(row.get("completed"))
    win_rate = _float(row.get("win_rate_5d"))
    avg_return = _float(row.get("avg_return_5d"))
    if not label or completed < MIN_FEEDBACK_COMPLETED:
        return
    if (win_rate is not None and win_rate < WEAK_FEEDBACK_WIN_RATE) or (avg_return is not None and avg_return < WEAK_FEEDBACK_AVG_RETURN):
        target[label] = {"label": label, "completed": completed, "win_rate_5d": win_rate, "avg_return_5d": avg_return, "reason": row.get("reason") or default_reason}


def _has_feedback(weak: dict[str, dict[str, Any]]) -> bool:
    return any(bool(rows) for rows in weak.values())


def _feedback_adjustment(feedback: dict[str, Any] | None, *, stage_label: str, lifecycle_label: str, smart_money_label: str, combo: str, tags: list[str]) -> dict[str, Any]:
    if not feedback or not feedback.get("active"):
        return {"penalty": 0, "tags": [], "notes": []}
    weak = feedback.get("weak") or {}
    matches: list[dict[str, Any]] = []
    for group, label in [("stage", stage_label), ("lifecycle", lifecycle_label), ("smart_money", smart_money_label), ("combo", combo)]:
        item = (weak.get(group) or {}).get(label)
        if item:
            matches.append(item)
    for tag in tags:
        item = (weak.get("factor") or {}).get(_potential_factor_label(tag))
        if item:
            matches.append(item)
    rows = list({str(item.get("label") or ""): item for item in matches if item.get("label")}.values())
    if not rows:
        return {"penalty": 0, "tags": [], "notes": []}
    penalty = min(4, 2 + max(0, len(rows) - 1))
    notes = [
        f"{row['label']} 近30日樣本 {row.get('completed')} 筆，5日勝率 {_fmt_pct(row.get('win_rate_5d'))}，平均 {_fmt_pct(row.get('avg_return_5d'))}"
        for row in rows[:3]
    ]
    return {"penalty": penalty, "tags": [f"成效降權:{row['label']}" for row in rows[:2]], "notes": notes}


def _potential_factor_label(tag: str) -> str:
    if tag.startswith("成效降權:"):
        return "成效降權"
    for prefix in ("回測偏弱:", "K線型態:", "K線轉強:", "K線風險:", "題材升溫:", "題材:", "生命週期:", "資金同步:", "資金型態:", "訊號組合:", "組合:", "研究:", "類型:", "部位:", "階段:"):
        if tag.startswith(prefix):
            return tag.split(":", 1)[1]
    return tag

def _is_actionable_today(row: dict[str, Any]) -> bool:
    text = _text(row.get("entry_decision"), row.get("action"), row.get("action_context"), row.get("action_context_reason"), row.get("trigger_summary"))
    if _has_any(text, ["可追", "開盤確認", "綠燈可盯"]):
        return True
    return str(row.get("decision_light") or "") == "green" and _int(row.get("score")) >= 75


def _score_row(row: dict[str, Any], score: int, grade: str) -> tuple[int, list[str]]:
    points = 0
    tags: list[str] = []
    text = _text(row.get("trigger_summary"), row.get("technical"), row.get("chip"), row.get("fundamental"), row.get("risk"), row.get("retail_context"), row.get("retail_context_reason"), *(row.get("trigger_tags") or []))
    if _has_any(text, ["散戶轉乾淨", "籌碼轉乾淨", "散戶減少"]):
        points += 3
        tags.append("散戶減少/籌碼轉乾淨")
    elif _has_any(text, ["散戶過熱", "散戶增加"]):
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
    if _has_any(text, ["法人共振", "外資買", "投信買"]):
        points += 2
        tags.append("法人開始同步")
    if _has_any(text, ["營收加速", "營收成長", "月營收"]):
        points += 2
        tags.append("營收加速")
    if _has_any(text, ["追高", "過熱", "連漲", "高乖離"]):
        points -= 2
        tags.append("追價風險")
    if 75 <= score < 96:
        points += 2
        tags.append("強度中高")
    elif 60 <= score < 75:
        points += 1
        tags.append("低位醞釀")
    if grade in {"A", "B"}:
        points += 1
        tags.append("尚未過熱強度")
    elif grade == "S":
        points += 1
        tags.append("強度高")
    return points, tags


def _research_filter(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, Any]:
    text = _text(row.get("trigger_summary"), row.get("fundamental"), row.get("opportunity"), row.get("retail_context"), *(row.get("trigger_tags") or []), *tags)
    factors = [
        _factor("market_strength", "市場/強度", score >= 75 or grade in {"S", "A"}, "分數或級別達到研究門檻"),
        _factor("theme", "題材", bool(row.get("themes")), "有題材連結"),
        _factor("catalyst", "催化劑", _int(row.get("opportunity_score")) >= 5 or _has_any(text, ["政策", "新聞", "訂單", "升溫"]), "有事件或題材催化"),
        _factor("revenue", "營收", _int(row.get("fundamental_score")) >= 12 or _has_any(text, ["營收", "月增", "年增", "加速"]), "營收或基本面改善"),
        _factor("institutional", "法人", _int(row.get("chip_score")) >= 12 or _has_any(text, ["外資", "投信", "法人"]), "法人或籌碼有支撐"),
        _factor("technical", "技術", _int(row.get("technical_score")) >= 12 or bool(row.get("pattern_tags")), "技術或K線訊號成立"),
        _factor("volume", "量能", _has_any(text, ["放量", "量增", "成交量", "爆量"]), "量能有變化"),
        _factor("overheat_guard", "過熱防護", chase_risk != "high" and not row.get("pattern_risk_tags") and score < 96, "未達高追價風險"),
    ]
    passed = sum(1 for item in factors if item["passed"])
    label = "順風研究" if passed >= 7 else "通過研究" if passed >= 6 else "可研究" if passed >= 4 else "待觀察" if passed >= 2 else "暫不研究"
    return {"score": passed, "label": label, "factors": factors}


def _factor(key: str, label: str, passed: bool, reason: str) -> dict[str, Any]:
    return {"key": key, "label": label, "passed": bool(passed), "reason": reason}


def _stock_type(row: dict[str, Any], score: int, tags: list[str], stage_key: str) -> dict[str, str]:
    text = _text(row.get("trigger_summary"), row.get("fundamental"), row.get("opportunity"), *(row.get("themes") or []), *(row.get("theme_tiers") or []), *tags)
    if score >= 80 and _has_any(text, ["營收", "加速", "年增", "月增"]) and bool(row.get("themes")):
        return {"key": "growth_confirmed", "label": "成長確認"}
    if _has_any(text, ["受惠", "二階", "供應鏈"]):
        return {"key": "tier2_beneficiary", "label": "二階受惠"}
    if _has_any(text, ["低基期", "復甦", "庫存", "轉機", "循環", "景氣"]):
        return {"key": "cyclical_recovery", "label": "景氣反轉"}
    if stage_key == "early_turn" or _has_any(text, ["新品", "新客戶", "轉虧", "轉強"]):
        return {"key": "turnaround_confirmed", "label": "轉機確認"}
    return {"key": "research_watch", "label": "研究觀察"}


def _position_hint(row: dict[str, Any], chase_risk: str) -> dict[str, str]:
    atr = _float(row.get("atr_pct"))
    if chase_risk == "high":
        return {"key": "avoid_chase", "label": "避免追價"}
    if atr is None:
        return {"key": "unknown", "label": "部位未知"}
    if atr >= 8:
        return {"key": "small", "label": "小部位"}
    if atr >= 5:
        return {"key": "half", "label": "半部位"}
    return {"key": "normal", "label": "正常部位"}


def _reason(points: int, tags: list[str], stage_label: str = "", chase_label: str = "") -> str:
    clean_tags = _dedupe([tag for tag in tags if tag])
    prefix = f"{stage_label}：" if stage_label else ""
    suffix = f"；{chase_label}" if chase_label else ""
    if clean_tags:
        return f"{prefix}潛力分 {points}，{' + '.join(clean_tags[:5])}{suffix}"
    return f"{prefix}潛力分 {points}，條件正在累積{suffix}"


def _stage(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, str]:
    text = " ".join(tags) + " " + _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    if "等拉回" in text:
        return {"key": "pullback_watch", "label": "強勢等拉回"}
    if score >= 80 or grade in {"S", "A"}:
        return {"key": "early_turn", "label": "轉強初動"}
    if chase_risk == "medium":
        return {"key": "wait_cooldown", "label": "等待降溫"}
    return {"key": "low_base", "label": "低位醞釀"}


def _lifecycle_stage(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, str]:
    text = _text(row.get("trigger_summary"), row.get("technical"), row.get("risk"), *(row.get("trigger_tags") or []), *tags)
    if chase_risk == "high" or score >= 94 or grade == "S+" or _has_any(text, ["過熱", "連漲", "20日高", "高乖離"]):
        return {"key": "extended", "label": "成熟/延伸", "reason": "已有明顯漲幅或追價風險"}
    if score >= 80 or grade in {"A", "S"} or _has_any(text, ["轉強", "突破", "放量", "站穩"]):
        return {"key": "maturing", "label": "轉強中", "reason": "訊號逐步成形但尚未完全噴出"}
    return {"key": "fresh", "label": "早期", "reason": "條件剛開始累積"}


def _smart_money_signal(row: dict[str, Any], score: int, tags: list[str], chase_risk: str) -> dict[str, Any]:
    text = _text(row.get("trigger_summary"), row.get("chip"), row.get("technical"), row.get("retail_context"), row.get("retail_context_reason"), *(row.get("trigger_tags") or []), *tags)
    zscore = round(min(4.5, max(0.0, _int(row.get("opportunity_score")) / 4 + max(0, _int(row.get("technical_score")) - 10) / 12 + max(0, _int(row.get("chip_score"))) / 18)), 2)
    institutional_follow = _has_any(text, ["法人", "外資", "投信", "買超"]) or _int(row.get("chip_score")) >= 14
    retail_clean = _has_any(text, ["散戶轉乾淨", "籌碼轉乾淨"])
    price_ready = _has_any(text, ["突破", "站穩", "轉強", "放量", "量增"])
    if zscore >= 2.4 and not institutional_follow and chase_risk != "high":
        return {"key": "lead", "label": "法人未跟上", "score": int(round(zscore * 20 + (10 if retail_clean else 0))), "zscore": zscore, "institutional_follow": False, "reason": "題材與技術先行，法人尚未明顯同步"}
    if institutional_follow and (price_ready or score >= 80):
        return {"key": "sync", "label": "法人開始同步", "score": int(round(zscore * 15 + 20)), "zscore": zscore, "institutional_follow": True, "reason": "法人與價格訊號同步"}
    return {"key": "none", "label": "未同步", "score": int(round(zscore * 10)), "zscore": zscore, "institutional_follow": bool(institutional_follow), "reason": "資金訊號尚不完整"}


def _radar_layer(stage: dict[str, str], lifecycle: dict[str, str], smart_money: dict[str, Any], score: int, grade: str, points: int) -> dict[str, str]:
    if stage.get("key") == "pullback_watch" or smart_money.get("key") == "sync" or points >= 10:
        return {"key": "confirmed_wait", "label": "確認等待"}
    if lifecycle.get("key") == "extended" or score >= 90 or grade in {"S+", "S"}:
        return {"key": "extended_watch", "label": "延伸觀察"}
    return {"key": "early_potential", "label": "早期潛力"}


def _signal_combo(lifecycle_label: str, smart_money_label: str, tags: list[str]) -> str:
    factors: list[str] = []
    if any("題材" in tag for tag in tags):
        factors.append("題材")
    if any("量" in tag for tag in tags):
        factors.append("量能")
    if any("K線" in tag for tag in tags):
        factors.append("K線")
    if smart_money_label in {"法人未跟上", "法人開始同步"}:
        factors.append(smart_money_label)
    if not factors:
        factors.append("基本")
    return f"{lifecycle_label}|" + "+".join(_dedupe(factors)[:4])


def _chase_risk(row: dict[str, Any], score: int, grade: str) -> dict[str, str]:
    text = _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"), row.get("trigger_summary"), *(row.get("trigger_tags") or []))
    price = _float(row.get("price"))
    entry_limit = _float(row.get("entry_limit_price"))
    if price is not None and entry_limit is not None and price > entry_limit:
        return {"level": "high", "label": f"高於進場上限 {entry_limit:g}"}
    if grade == "S+" or score >= 96:
        return {"level": "high", "label": "強度過熱"}
    if _has_any(text, ["避免追高", "追價", "跳空過大"]):
        return {"level": "high", "label": "追價風險高"}
    if score >= 90 and _has_any(text, ["20日高", "連漲"]):
        return {"level": "medium", "label": "延伸偏高"}
    return {"level": "low", "label": "追價風險低"}


def _early_bonus(item: dict[str, Any]) -> int:
    tags = " ".join(item.get("tags") or [])
    bonus = 0
    if "法人未跟上" in tags or "低位醞釀" in tags:
        bonus += 2
    if "轉強中" in tags:
        bonus += 1
    if "成熟" in tags or "追價風險" in tags:
        bonus -= 3
    return bonus


def _fmt_pct(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


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


def _priority_tags(items: list[str], limit: int = 12) -> list[str]:
    tags = _dedupe(items)
    priority_prefixes = ("成效降權:", "回測偏弱:", "散戶", "K線", "題材")
    priority = [tag for tag in tags if tag.startswith(priority_prefixes)]
    rest = [tag for tag in tags if tag not in priority]
    return _dedupe(priority + rest)[:limit]


# Clean UTF-8 overrides. The original block above was generated before the
# project standardized on UTF-8 and may contain mojibake on some machines.
def _priority_tags(items: list[str], limit: int = 12) -> list[str]:
    tags = _dedupe(items)
    priority_prefixes = ("成效降權:", "回測偏弱:", "散戶", "K線", "題材")
    priority = [tag for tag in tags if tag.startswith(priority_prefixes)]
    rest = [tag for tag in tags if tag not in priority]
    return _dedupe(priority + rest)[:limit]


def _score_row(row: dict[str, Any], score: int, grade: str) -> tuple[int, list[str]]:
    points = 0
    tags: list[str] = []
    text = _text(
        row.get("trigger_summary"),
        row.get("technical"),
        row.get("chip"),
        row.get("fundamental"),
        row.get("risk"),
        row.get("retail_context"),
        row.get("retail_context_reason"),
        *(row.get("trigger_tags") or []),
    )
    if _has_any(text, ["散戶減少", "籌碼轉乾淨", "散戶籌碼改善"]):
        points += 3
        tags.append("散戶減少/籌碼轉乾淨")
    elif _has_any(text, ["散戶過熱", "散戶增加"]):
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
    if _has_any(text, ["法人共振", "外資買", "投信買", "法人開始同步"]):
        points += 2
        tags.append("法人開始同步")
    if _has_any(text, ["營收加速", "營收創高", "營收年增"]):
        points += 2
        tags.append("營收加速")
    if _has_any(text, ["風險", "過熱", "追高", "偏弱"]):
        points -= 2
        tags.append("風險仍需確認")
    if 75 <= score < 96:
        points += 2
        tags.append("分數已成形")
    elif 60 <= score < 75:
        points += 1
        tags.append("低位累積")
    if grade in {"A", "B"}:
        points += 1
        tags.append("尚未過熱強度")
    elif grade == "S":
        points += 1
        tags.append("強度中高")
    return points, tags


def _research_filter(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, Any]:
    text = _text(row.get("trigger_summary"), row.get("fundamental"), row.get("opportunity"), row.get("retail_context"), *(row.get("trigger_tags") or []), *tags)
    factors = [
        _factor("market_strength", "市場/強度", score >= 75 or grade in {"S", "A"}, "分數與強度已達研究門檻。"),
        _factor("theme", "題材", bool(row.get("themes")), "有題材或供應鏈映射。"),
        _factor("catalyst", "催化", _int(row.get("opportunity_score")) >= 5 or _has_any(text, ["催化", "題材升溫", "政策", "新訂單"]), "有題材催化或異常訊號。"),
        _factor("revenue", "營收加速", _int(row.get("fundamental_score")) >= 12 or _has_any(text, ["營收", "年增", "創高", "加速"]), "營收或基本面有支撐。"),
        _factor("institutional", "法人", _int(row.get("chip_score")) >= 12 or _has_any(text, ["法人", "外資", "投信"]), "法人或籌碼有同步。"),
        _factor("technical", "技術", _int(row.get("technical_score")) >= 12 or bool(row.get("pattern_tags")), "技術或K線型態轉強。"),
        _factor("volume", "量能", _has_any(text, ["放量", "量增", "爆量", "成交"]), "量能開始放大。"),
        _factor("overheat_guard", "過熱防護", chase_risk != "high" and not row.get("pattern_risk_tags") and score < 96, "尚未進入明顯追高區。"),
    ]
    passed = sum(1 for item in factors if item["passed"])
    label = "順風研究" if passed >= 7 else "完整研究" if passed >= 6 else "照流程篩選" if passed >= 4 else "先觀察" if passed >= 2 else "暫不研究"
    return {"score": passed, "label": label, "factors": factors}


def _stock_type(row: dict[str, Any], score: int, tags: list[str], stage_key: str) -> dict[str, str]:
    text = _text(row.get("trigger_summary"), row.get("fundamental"), row.get("opportunity"), *(row.get("themes") or []), *(row.get("theme_tiers") or []), *tags)
    if score >= 80 and _has_any(text, ["營收", "營收加速", "創高", "年增"]) and bool(row.get("themes")):
        return {"key": "growth_confirmed", "label": "成長確認型"}
    if _has_any(text, ["二階", "受惠", "上游", "供應鏈", "材料", "設備"]):
        return {"key": "tier2_beneficiary", "label": "二階受惠型"}
    if _has_any(text, ["景氣反轉", "復甦", "低基期", "轉機", "落底", "循環"]):
        return {"key": "cyclical_recovery", "label": "景氣反轉型"}
    if stage_key == "early_turn" or _has_any(text, ["轉強", "轉折", "突破", "底部"]):
        return {"key": "turnaround_confirmed", "label": "轉機確認型"}
    return {"key": "research_watch", "label": "研究觀察型"}


def _position_hint(row: dict[str, Any], chase_risk: str) -> dict[str, str]:
    atr = _float(row.get("atr_pct"))
    if chase_risk == "high":
        return {"key": "avoid_chase", "label": "避免追價"}
    if atr is None:
        return {"key": "unknown", "label": "部位待確認"}
    if atr >= 8:
        return {"key": "small", "label": "小部位"}
    if atr >= 5:
        return {"key": "half", "label": "半部位"}
    return {"key": "normal", "label": "正常部位"}


def _reason(points: int, tags: list[str], stage_label: str = "", chase_label: str = "") -> str:
    clean_tags = _dedupe([tag for tag in tags if tag])
    prefix = f"{stage_label}｜" if stage_label else ""
    suffix = f"，{chase_label}" if chase_label else ""
    if clean_tags:
        return f"{prefix}潛力分 {points}，" + " + ".join(clean_tags[:5]) + suffix
    return f"{prefix}潛力分 {points}，條件仍需累積{suffix}"


def _stage(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, str]:
    text = " ".join(tags) + " " + _text(row.get("entry_decision"), row.get("action_context"), row.get("action_context_reason"))
    if "等拉回" in text:
        return {"key": "pullback_watch", "label": "強勢等拉回"}
    if score >= 80 or grade in {"S", "A"}:
        return {"key": "early_turn", "label": "轉強初動"}
    if chase_risk == "medium":
        return {"key": "wait_cooldown", "label": "降溫觀察"}
    return {"key": "low_base", "label": "低位醞釀"}


def _lifecycle_stage(row: dict[str, Any], score: int, grade: str, tags: list[str], chase_risk: str) -> dict[str, str]:
    text = _text(row.get("trigger_summary"), row.get("technical"), row.get("risk"), *(row.get("trigger_tags") or []), *tags)
    if chase_risk == "high" or score >= 94 or grade == "S+" or _has_any(text, ["過熱", "高乖離", "20日高", "追高"]):
        return {"key": "extended", "label": "延伸/過熱", "reason": "已經有一段漲幅，需避免追高。"}
    if score >= 80 or grade in {"A", "S"} or _has_any(text, ["轉強", "突破", "放量", "站上"]):
        return {"key": "maturing", "label": "轉強中", "reason": "條件正在成形，適合等待開盤確認。"}
    return {"key": "fresh", "label": "早期", "reason": "訊號剛開始累積，偏向觀察。"}


def _smart_money_signal(row: dict[str, Any], score: int, tags: list[str], chase_risk: str) -> dict[str, Any]:
    text = _text(row.get("trigger_summary"), row.get("chip"), row.get("technical"), row.get("retail_context"), row.get("retail_context_reason"), *(row.get("trigger_tags") or []), *tags)
    zscore = round(min(4.5, max(0.0, _int(row.get("opportunity_score")) / 4 + max(0, _int(row.get("technical_score")) - 10) / 12 + max(0, _int(row.get("chip_score"))) / 18)), 2)
    institutional_follow = _has_any(text, ["法人", "外資", "投信", "買超"]) or _int(row.get("chip_score")) >= 14
    retail_clean = _has_any(text, ["散戶減少", "籌碼轉乾淨"])
    price_ready = _has_any(text, ["突破", "站上", "轉強", "放量", "整理"])
    if zscore >= 2.4 and not institutional_follow and chase_risk != "high":
        return {"key": "lead", "label": "法人前導不足", "score": int(round(zscore * 20 + (10 if retail_clean else 0))), "zscore": zscore, "institutional_follow": False, "reason": "題材與技術先動，法人尚未明顯同步。"}
    if institutional_follow and (price_ready or score >= 80):
        return {"key": "sync", "label": "法人開始同步", "score": int(round(zscore * 15 + 20)), "zscore": zscore, "institutional_follow": True, "reason": "法人與價格條件開始同步。"}
    return {"key": "none", "label": "尚未同步", "score": int(round(zscore * 10)), "zscore": zscore, "institutional_follow": bool(institutional_follow), "reason": "資金條件仍未明朗。"}


def _radar_layer(stage: dict[str, str], lifecycle: dict[str, str], smart_money: dict[str, Any], score: int, grade: str, points: int) -> dict[str, str]:
    if stage.get("key") == "pullback_watch" or smart_money.get("key") == "sync" or points >= 10:
        return {"key": "confirmed_wait", "label": "已轉強等回測"}
    if lifecycle.get("key") == "extended" or score >= 90 or grade in {"S+", "S"}:
        return {"key": "extended_watch", "label": "延伸觀察"}
    return {"key": "early_potential", "label": "早期潛力"}


def _signal_combo(lifecycle_label: str, smart_money_label: str, tags: list[str]) -> str:
    factors: list[str] = []
    if any("題材" in tag for tag in tags):
        factors.append("題材")
    if any("量" in tag for tag in tags):
        factors.append("量能")
    if any("K線" in tag for tag in tags):
        factors.append("K線")
    if smart_money_label in {"法人前導不足", "法人開始同步"}:
        factors.append(smart_money_label)
    if not factors:
        factors.append(lifecycle_label)
    return "+".join(_dedupe(factors[:4]))
