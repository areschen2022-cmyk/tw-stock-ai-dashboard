from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.indicators.overseas import OverseasSentiment
from src.news.web_theme import ThemeSignal
from src.report.retail_divergence import empty_retail_divergence
from src.scoring.grade import grade_label
from src.scoring.score_engine import StockScore

TAIPEI = ZoneInfo("Asia/Taipei")


def _scheduled_metadata(generated_at: datetime) -> dict:
    target_raw = os.getenv("SCHEDULED_TARGET_TAIPEI", "").strip()
    target_dt = None
    delay_minutes = None
    if target_raw:
        try:
            target_dt = datetime.fromisoformat(target_raw)
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=TAIPEI)
            target_dt = target_dt.astimezone(TAIPEI)
            delay_minutes = round((generated_at - target_dt).total_seconds() / 60, 1)
        except ValueError:
            target_dt = None

    return {
        "scheduler": os.getenv("SCHEDULED_BY", "") or os.getenv("GITHUB_EVENT_NAME", "local"),
        "scheduled_task": os.getenv("SCHEDULED_TASK", ""),
        "scheduled_cron": os.getenv("SCHEDULED_CRON", ""),
        "scheduled_target_taipei": target_dt.isoformat(timespec="seconds") if target_dt else target_raw,
        "schedule_delay_minutes": delay_minutes,
    }


def _status_text(label: str) -> str:
    return {
        "BUY_WATCH": "買進觀察",
        "WAIT": "等待",
        "AVOID": "避開",
        "DATA_INSUFFICIENT": "資料不足",
    }.get(label, label)


def _grade(score: int) -> str:
    return grade_label(score)


def _first(reasons: list[str]) -> str:
    return reasons[0] if reasons else "無明顯訊號"


def _theme_chain_details(stock_id: str, themes: list[str], config: dict) -> list[dict]:
    stock_meta = (config.get("theme_stock_meta") or {}).get(str(stock_id), {}) or {}
    wanted = set(themes or [])
    details = []
    for theme_key, meta in stock_meta.items():
        theme_name = meta.get("theme_name", theme_key)
        if wanted and theme_key not in wanted and theme_name not in wanted:
            continue
        details.append(
            {
                "theme_key": theme_key,
                "theme_name": theme_name,
                "tier": meta.get("tier", ""),
                "tier_label": meta.get("tier_label", ""),
                "role": meta.get("role", ""),
                "chain_layer": meta.get("chain_layer", "unknown"),
                "chain_layer_label": meta.get("chain_layer_label", "未分類"),
                "beneficiary_order": meta.get("beneficiary_order"),
                "beneficiary_label": meta.get("beneficiary_label", ""),
                "chain_role": meta.get("chain_role") or meta.get("role", ""),
                "lead_lag": meta.get("lead_lag", ""),
            }
        )
    return sorted(
        details,
        key=lambda item: (
            item.get("beneficiary_order") or 9,
            str(item.get("theme_name") or ""),
            str(item.get("chain_layer") or ""),
        ),
    )


def _chain_summary(details: list[dict], limit: int = 2) -> list[str]:
    summary = []
    for item in details[:limit]:
        theme = item.get("theme_name") or item.get("theme_key") or "題材"
        layer = item.get("chain_layer_label") or "未分類"
        beneficiary = item.get("beneficiary_label") or item.get("tier_label") or ""
        role = item.get("chain_role") or ""
        role_text = f"｜{role}" if role else ""
        summary.append(f"{theme}：{layer}/{beneficiary}{role_text}")
    return summary


def _theme_chain_payload(config: dict) -> dict:
    theme_pools = config.get("theme_pools", {}) or {}
    payload = {}
    for key, chain in (config.get("theme_chain_map", {}) or {}).items():
        payload[key] = {
            "name": theme_pools.get(key, {}).get("name", key),
            "stage": chain.get("stage", ""),
            "stage_reason": chain.get("stage_reason", ""),
            "lead_lag": chain.get("lead_lag", ""),
        }
    return payload


def _decision_reason(item: StockScore) -> str:
    parts = [item.trigger_summary]
    for key in ("technical", "chip", "fundamental", "risk", "opportunity"):
        reason = _first(item.reasons.get(key, []))
        if reason != "無明顯訊號" and reason not in parts:
            parts.append(reason)
        if len(parts) >= 4:
            break
    return "；".join(parts)


def _ai_review_label(review: dict | None) -> str:
    if not review:
        return "未複核"
    action = str(review.get("consensus_action") or "")
    if action == "可追":
        return "AI 同意"
    if action == "等拉回":
        return "AI 保留"
    if action in {"避免", "只觀察"}:
        return "AI 不建議" if action == "避免" else "AI 保留"
    return "AI 無共識"


def _ai_review_reason(review: dict | None) -> str:
    if not review:
        return ""
    return str(review.get("reason") or "").strip()


def _retail_signal_lookup(retail_divergence: dict | None) -> dict[str, dict]:
    data = retail_divergence or {}
    lookup: dict[str, dict] = {}
    for key in ("clean", "watch_clean", "overheated", "watch_overheated"):
        for item in data.get(key, []) or []:
            stock_id = str(item.get("stock_id") or "")
            if stock_id and stock_id not in lookup:
                lookup[stock_id] = item
    return lookup


def _retail_context(row: dict, retail_lookup: dict[str, dict]) -> tuple[str, str]:
    item = retail_lookup.get(str(row.get("stock_id") or ""))
    if not item:
        return "散戶：無明顯背離", ""
    signal = str(item.get("signal") or "")
    reason = str(item.get("reason") or "")
    if "籌碼轉乾淨" in signal:
        return "散戶：籌碼轉乾淨", reason
    if "散戶過熱" in signal:
        return "散戶：過熱警示", reason
    return f"散戶：{signal or '觀察'}", reason


def _as_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _exit_plan(row: dict) -> dict:
    price = _as_float(row.get("price"))
    entry_limit = _as_float(row.get("entry_limit_price")) or price
    stop_price = _as_float(row.get("stop_price"))
    atr_pct = _as_float(row.get("atr_pct"))
    grade = str(row.get("grade") or "")
    entry_decision = str(row.get("entry_decision") or row.get("action") or "")
    risk_per_share = None
    if entry_limit is not None and stop_price is not None and entry_limit > stop_price:
        risk_per_share = entry_limit - stop_price

    if risk_per_share:
        take_profit_1 = entry_limit + risk_per_share
        take_profit_2 = entry_limit + risk_per_share * 2
    elif entry_limit is not None:
        take_profit_1 = entry_limit * 1.06
        take_profit_2 = entry_limit * 1.12
    else:
        take_profit_1 = None
        take_profit_2 = None

    if stop_price is None:
        hard_stop = "資料不足，暫不建立持倉"
    else:
        hard_stop = f"跌破 {stop_price:.2f} 退出，不攤平"

    if "等拉回" in entry_decision:
        plan_type = "等拉回型"
        rule = "未回到進場區前不追價；進場後先守停損，站穩再提高停利。"
    elif grade in {"S+", "S"}:
        plan_type = "強勢延伸型"
        rule = "第一段停利後，剩餘部位用 MA5 或前一日低點移動停利；跌破 MA10 先降部位。"
    else:
        plan_type = "標準控風險"
        rule = "達第一段先保護獲利，未突破前高或量能退潮時不加碼。"

    if atr_pct is not None and atr_pct >= 7:
        plan_type = "高波動控倉"
        rule = "波動偏大，部位降一級；爆量長黑、跌破前低或跌破停損先退出。"

    checklist = [
        hard_stop,
        "達第一段停利可先減碼 1/3 到 1/2",
        "達第二段停利後改用移動停利保護",
        "若進入危險名單、散戶過熱或法人連賣，停止加碼並提高停利",
    ]

    return {
        "plan_type": plan_type,
        "hard_stop": hard_stop,
        "take_profit_1": _round_price(take_profit_1),
        "take_profit_2": _round_price(take_profit_2),
        "risk_per_share": _round_price(risk_per_share),
        "trailing_rule": rule,
        "checklist": checklist,
    }


def _action_lists(rows: list[dict], ai_picks: list[dict] | None = None, exit_risks: list[dict] | None = None) -> dict:
    ai_reviews = {str(item.get("stock_id")): item for item in ai_picks or []}
    exit_ids = {str(item.get("stock_id")) for item in exit_risks or []}
    ranked = sorted(rows, key=lambda row: (int(row.get("score") or 0), str(row.get("stock_id") or "")), reverse=True)

    def _compact(row: dict, reason: str = "") -> dict:
        ai_review = row.get("ai_review") or ai_reviews.get(str(row.get("stock_id")))
        return {
            "stock_id": row.get("stock_id"),
            "name": row.get("name"),
            "score": row.get("score"),
            "grade": row.get("grade"),
            "action": row.get("action"),
            "entry_decision": row.get("entry_decision"),
            "entry_checklist": row.get("entry_checklist", []),
            "reason": reason or row.get("trigger_summary") or row.get("decision_reason") or "",
            "entry_limit_price": row.get("entry_limit_price"),
            "stop_price": row.get("stop_price"),
            "exit_plan": row.get("exit_plan") or _exit_plan(row),
            "themes": row.get("themes", []),
            "pattern_tags": row.get("pattern_tags", []),
            "pattern_risk_tags": row.get("pattern_risk_tags", []),
            "ai_review": ai_review,
            "ai_label": _ai_review_label(ai_review),
            "ai_reason": row.get("ai_reason") or _ai_review_reason(ai_review),
            "decision_light": row.get("decision_light"),
            "decision_light_label": row.get("decision_light_label"),
            "decision_light_reason": row.get("decision_light_reason"),
            "retail_context": row.get("retail_context"),
            "retail_context_reason": row.get("retail_context_reason"),
            "action_context": row.get("action_context"),
            "action_context_reason": row.get("action_context_reason"),
            "stability": row.get("stability"),
            "stability_label": row.get("stability_label"),
            "stability_reason": row.get("stability_reason"),
        }

    chase = [
        _compact(row)
        for row in ranked
        if row.get("grade") in {"S+", "S", "A"}
        and "可追" in str(row.get("action") or "")
        and str(row.get("stock_id")) not in exit_ids
    ][:5]
    pullback = [
        _compact(row)
        for row in ranked
        if row.get("grade") in {"S+", "S", "A", "B"} and "等拉回" in str(row.get("action") or "")
    ][:5]
    observe_count = sum(1 for row in rows if "只觀察" in str(row.get("action") or ""))
    avoid_count = sum(
        1
        for row in rows
        if "避免" in str(row.get("action") or "") or str(row.get("stock_id")) in exit_ids
    )
    risk = [
        {
            "stock_id": item.get("stock_id"),
            "name": item.get("name"),
            "level": item.get("level"),
            "risk_score": item.get("risk_score"),
            "reason": "、".join((item.get("reasons") or [])[:2]),
            "action": item.get("action"),
        }
        for item in (exit_risks or [])[:5]
    ]
    return {
        "chase": chase,
        "pullback": pullback,
        "risk": risk,
        "summary": {
            "chase": len(chase),
            "pullback": len(pullback),
            "observe": observe_count,
            "avoid": avoid_count,
            "ai_agree": sum(1 for row in rows if _ai_review_label(row.get("ai_review")) == "AI 同意"),
            "ai_hold": sum(1 for row in rows if _ai_review_label(row.get("ai_review")) == "AI 保留"),
            "ai_avoid": sum(1 for row in rows if _ai_review_label(row.get("ai_review")) == "AI 不建議"),
            "ai_reviewed": sum(1 for row in rows if row.get("ai_review")),
            "risk": len(risk),
            "strong": sum(1 for row in rows if row.get("grade") in {"S+", "S"}),
        },
    }


def _annotate_action_context(
    rows: list[dict],
    action_lists: dict,
    exit_risks: list[dict] | None = None,
    retail_divergence: dict | None = None,
) -> None:
    chase_ids = {str(item.get("stock_id")) for item in action_lists.get("chase", [])}
    pullback_ids = {str(item.get("stock_id")) for item in action_lists.get("pullback", [])}
    risk_ids = {str(item.get("stock_id")) for item in exit_risks or []}
    retail_lookup = _retail_signal_lookup(retail_divergence)

    for row in rows:
        stock_id = str(row.get("stock_id") or "")
        grade = str(row.get("grade") or "")
        action = str(row.get("action") or "")
        entry_decision = str(row.get("entry_decision") or "")
        ai_label = str(row.get("ai_label") or "未複核")
        retail_label, retail_reason = _retail_context(row, retail_lookup)
        pattern_risks = row.get("pattern_risk_tags") or []

        if stock_id in chase_ids:
            context = "已列入今日可追"
            reason = "符合強度與操作條件"
        elif stock_id in pullback_ids:
            context = "已列入等拉回"
            reason = "強度夠，但進場條件偏向等待回測"
        elif stock_id in risk_ids:
            context = "未列入今日操作"
            reason = "危險名單，先避開"
        elif grade not in {"S+", "S", "A", "B"}:
            context = "未列入今日操作"
            reason = "強度未達操作觀察門檻"
        elif "等拉回" in action or "等拉回" in entry_decision:
            context = "未列入今日操作"
            reason = "等拉回，未進前5檔"
        elif "可追" in action:
            context = "未列入今日操作"
            reason = "可追候選，但未進前5檔"
        elif "避免" in action or "避免" in entry_decision:
            context = "未列入今日操作"
            reason = "操作結論偏保守"
        elif "量價不確認" in entry_decision:
            context = "未列入今日操作"
            reason = "量價條件尚未確認"
        else:
            context = "未列入今日操作"
            reason = "只追蹤，不作為今日進場候選"

        if ai_label in {"AI 不建議", "未複核", "AI 無共識"} and context.startswith("未列入"):
            reason = f"{reason}；{ai_label}"

        row["action_context"] = context
        row["action_context_reason"] = reason
        row["retail_context"] = retail_label
        row["retail_context_reason"] = retail_reason
        row["ai_reason"] = _ai_review_reason(row.get("ai_review"))

        if stock_id in risk_ids or "避免" in action or "避免" in entry_decision:
            light = "red"
            light_label = "紅燈控風險"
            light_reason = "危險名單或操作結論偏保守"
        elif "散戶過熱" in retail_label:
            light = "red"
            light_label = "紅燈控風險"
            light_reason = retail_reason or "散戶過熱，先降低追價意願"
        elif pattern_risks:
            light = "yellow"
            light_label = "黃燈等確認"
            light_reason = f"K線風險：{'、'.join(pattern_risks[:2])}"
        elif stock_id in chase_ids and ai_label == "AI 同意":
            light = "green"
            light_label = "綠燈可盯"
            light_reason = "列入可追且 AI 同意，仍需開盤價量確認"
        elif stock_id in chase_ids:
            light = "yellow"
            light_label = "黃燈等確認"
            light_reason = f"列入可追，但 {ai_label}"
        elif stock_id in pullback_ids:
            light = "yellow"
            light_label = "黃燈等拉回"
            light_reason = "強度足夠，但進場位置要等回測"
        elif "籌碼轉乾淨" in retail_label and grade in {"S+", "S", "A", "B"}:
            light = "yellow"
            light_label = "黃燈觀察"
            light_reason = retail_reason or "籌碼轉乾淨，但尚未列入今日操作"
        else:
            light = "gray"
            light_label = "灰燈追蹤"
            light_reason = "尚未形成今日操作條件"

        row["decision_light"] = light
        row["decision_light_label"] = light_label
        row["decision_light_reason"] = light_reason


def _data_recovery_status(details: list[dict]) -> dict:
    if not details:
        return {"label": "clean", "retryable": 0, "blocked": 0, "items": []}
    retryable = []
    blocked = []
    recovered = []
    recovered_ids = {
        str(item.get("data_id") or "")
        for item in details
        if item.get("type") == "fallback" and item.get("data_id")
    }
    for item in details:
        reason = str(item.get("reason") or "")
        data_id = str(item.get("data_id") or "")
        row = {
            "dataset": item.get("dataset"),
            "data_id": item.get("data_id"),
            "period": item.get("period"),
            "type": item.get("type"),
            "next_step": "retry_range",
        }
        if item.get("type") == "fallback":
            row["next_step"] = "recovered_by_fallback"
            recovered.append(row)
        elif data_id and data_id in recovered_ids:
            row["next_step"] = "recovered_by_fallback"
            recovered.append(row)
        elif item.get("type") in {"empty", "error"} and "quota" not in reason.lower():
            retryable.append(row)
        else:
            row["next_step"] = "wait_or_manual_check"
            blocked.append(row)
    if not retryable and not blocked:
        label = "clean"
    elif blocked and not retryable:
        label = "manual_check"
    elif retryable:
        label = "retry_ready"
    else:
        label = "clean"
    return {
        "label": label,
        "retryable": len(retryable),
        "blocked": len(blocked),
        "recovered": len(recovered),
        "items": (retryable + blocked + recovered)[:6],
    }


def _data_quality(
    source_status: dict | None,
    rows: list[dict],
    ai_status: dict | None = None,
    retry_summary: dict | None = None,
) -> dict:
    status = source_status or {}
    api = int(status.get("api") or 0)
    cache = int(status.get("cache") or 0)
    quota = int(status.get("quota") or 0)
    error = int(status.get("error") or 0)
    empty = int(status.get("empty") or 0)
    fallback = int(status.get("fallback") or 0)
    official_snapshots = dict(status.get("official_snapshots") or {})
    official_valid = sum(1 for item in official_snapshots.values() if item.get("valid"))
    official_invalid = sum(1 for item in official_snapshots.values() if not item.get("valid"))
    retry_recovered = int((retry_summary or {}).get("recovered") or 0)
    recovered = fallback + retry_recovered
    effective_empty = max(0, empty - recovered)
    recovered_after_empty = max(0, recovered - empty)
    effective_error = max(0, error - recovered_after_empty)
    usable = api + cache + recovered
    total_fetches = usable + quota + effective_error + effective_empty
    source_score = 100 if total_fetches == 0 else round(max(0, min(100, usable / total_fetches * 100 - quota * 3 - effective_error * 5)))
    scored_rows = [row for row in rows if row.get("price") is not None and row.get("score") is not None]
    coverage = round(len(scored_rows) / len(rows) * 100, 1) if rows else 0
    ai_health = (ai_status or {}).get("health") or {}
    score = round(source_score * 0.65 + coverage * 0.25 + float(ai_health.get("score", 0)) * 0.10)
    if score >= 85:
        label = "high"
    elif score >= 65:
        label = "medium"
    else:
        label = "low"
    label_text = {"high": "高", "medium": "中", "low": "偏低"}[label]
    warnings = []
    if quota:
        warnings.append(f"資料源限流 {quota} 次")
    if official_invalid:
        warnings.append(f"官方快照未通過日期/內容檢查 {official_invalid} 項")
    if effective_error:
        warnings.append(f"資料源錯誤 {effective_error} 次")
    if recovered:
        warnings.append(f"已由備援/補抓補回 {recovered} 次")
    if coverage < 90 and rows:
        warnings.append(f"股票資料覆蓋率 {coverage}%")
    if ai_health and ai_health.get("label") in {"降級可用", "不穩定"}:
        warnings.append(f"AI 模型{ai_health.get('label')}")
    events = list(status.get("events") or [])[-10:]
    event_summary: dict[str, int] = {}
    for event in events:
        key = str(event.get("type") or "unknown")
        event_summary[key] = event_summary.get(key, 0) + 1
    details = []
    for event in events[-6:]:
        dataset = event.get("dataset") or "unknown"
        data_id = event.get("data_id") or "-"
        period = event.get("period") or event.get("start_date") or event.get("year") or ""
        reason = event.get("reason") or event.get("status_code") or ""
        details.append(
            {
                "type": event.get("type"),
                "dataset": dataset,
                "data_id": data_id,
                "period": period,
                "reason": reason,
            }
        )
    recovery_status = _data_recovery_status(details)
    return {
        "label": label,
        "label_text": label_text,
        "score": score,
        "source_score": source_score,
        "coverage": coverage,
        "recovered_fetches": recovered,
        "effective_error": effective_error,
        "effective_empty": effective_empty,
        "warnings": warnings,
        "event_summary": event_summary,
        "details": details,
        "recovery_status": recovery_status,
        "official_snapshots": official_snapshots,
        "official_valid": official_valid,
        "official_invalid": official_invalid,
    }


def _decision_summary(rows: list[dict], action_lists: dict, data_quality: dict, health: dict, theme_signal: ThemeSignal | None) -> dict:
    risk_count = int((action_lists.get("summary") or {}).get("risk") or 0)
    chase_count = int((action_lists.get("summary") or {}).get("chase") or 0)
    pullback_count = int((action_lists.get("summary") or {}).get("pullback") or 0)
    s_count = sum(1 for row in rows if row.get("grade") in {"S+", "S"})
    quality_label = str(data_quality.get("label") or "")
    health_label = str(health.get("label") or "")
    if health_label in {"正常"} and quality_label in {"高", "high"} and chase_count:
        posture = "active_watch"
    elif risk_count or quality_label in {"偏低", "low"}:
        posture = "risk_control"
    else:
        posture = "selective_watch"
    return {
        "posture": posture,
        "watch_count": chase_count,
        "pullback_count": pullback_count,
        "risk_count": risk_count,
        "strong_grade_count": s_count,
        "data_quality": data_quality.get("label"),
        "ai_status": "available",
        "top_theme": (theme_signal.active_themes[0] if theme_signal and theme_signal.active_themes else ""),
        "notes": [
            f"watch={chase_count}",
            f"pullback={pullback_count}",
            f"risk={risk_count}",
            f"data_quality={data_quality.get('label')}",
        ],
    }


def _data_source_health(source_status: dict | None, data_quality: dict | None, retry_summary: dict | None = None) -> dict:
    status = source_status or {}
    quality = data_quality or {}
    retry = retry_summary or {}
    pending = _retry_status_count(retry, "pending")
    failed = _retry_status_count(retry, "failed")
    recovered = _retry_status_count(retry, "recovered")
    official = quality.get("official_snapshots") or status.get("official_snapshots") or {}
    invalid = int(quality.get("official_invalid") or 0)
    effective_error = int(quality.get("effective_error") or 0)
    effective_empty = int(quality.get("effective_empty") or 0)
    active_blocking = invalid + effective_error
    failed_ratio = failed / max(1, failed + recovered)
    historical_blocking = failed if failed and recovered == 0 else 0
    blocked = active_blocking + historical_blocking
    if blocked:
        label = "需檢查"
    elif failed or pending:
        label = "可用但待補"
    else:
        label = "可用"
    return {
        "label": label,
        "blocking_count": blocked,
        "historical_failed_count": failed,
        "failed_recovered_ratio": round(failed_ratio, 4),
        "pending_count": pending,
        "failed_count": failed,
        "recovered_count": recovered,
        "effective_error": effective_error,
        "effective_empty": effective_empty,
        "official_valid": int(quality.get("official_valid") or 0),
        "official_invalid": invalid,
        "official_snapshots": official,
        "retry_diagnosis": retry.get("diagnosis", []),
        "recovered_by_dataset": retry.get("recovered_by_dataset", []),
        "note": "已補回成功與少量歷史補抓失敗不列為阻塞；只把官方快照無效、有效錯誤、或完全沒有補回的失敗列入需檢查。",
    }


def _retry_status_count(retry: dict, status: str) -> int:
    status_counts = retry.get("status_counts") or {}
    if status in status_counts:
        return int(status_counts.get(status) or 0)
    return int(retry.get(status) or 0)


def _build_health_status(
    as_of: date,
    source_status: dict | None,
    theme_signal: ThemeSignal | None,
) -> dict:
    generated_at = datetime.now(TAIPEI)
    provider_label = str((source_status or {}).get("label", "未知"))
    news_sources = theme_signal.source_count if theme_signal else 0
    news_failed = theme_signal.failed_count if theme_signal else 0
    schedule_meta = _scheduled_metadata(generated_at)
    delay_minutes = schedule_meta.get("schedule_delay_minutes")

    if delay_minutes is None:
        schedule_label = "未記錄"
    elif float(delay_minutes) <= 15:
        schedule_label = "正常"
    else:
        schedule_label = "延遲"

    if provider_label in {"錯誤", "無資料"} or news_sources == 0:
        data_source_label = "錯誤"
    elif provider_label in {"部分限流", "限流"} or news_failed > 0:
        data_source_label = "部分限流"
    else:
        data_source_label = "正常"

    if data_source_label == "錯誤":
        label = "異常"
    elif schedule_label == "延遲" or data_source_label == "部分限流":
        label = "部分延遲"
    else:
        label = "正常"

    return {
        "label": label,
        "schedule_label": schedule_label,
        "data_source_label": data_source_label,
        "news_label": "正常" if news_failed == 0 and news_sources > 0 else "部分失敗",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "generated_date": generated_at.date().isoformat(),
        "data_date": as_of.isoformat(),
        "website_schedule": "04:30 / 05:00",
        "telegram_schedule": "07:20 / 07:35 / 07:50 / 08:05",
        "provider_label": provider_label,
        "news_sources": news_sources,
        "news_failed": news_failed,
        "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
        "github_event": os.getenv("GITHUB_EVENT_NAME", "local"),
        **schedule_meta,
    }


def build_dashboard_payload(
    scores: list[StockScore],
    as_of: date,
    market_summary: str,
    market_warning: str | None,
    config: dict,
    overseas: OverseasSentiment | None,
    theme_signal: ThemeSignal | None,
    source_status: dict | None = None,
    alerts: list[str] | None = None,
    watch_reviews: list[dict] | None = None,
    exit_risks: list[dict] | None = None,
    ai_picks: list[dict] | None = None,
    ai_status: dict | None = None,
    retail_divergence: dict | None = None,
) -> dict:
    stock_names = config.get("stock_names", {})
    ai_reviews = {str(item.get("stock_id")): item for item in ai_picks or []}
    rows = []
    for item in sorted(scores, key=lambda score: score.total_score, reverse=True):
        ai_review = ai_reviews.get(item.stock_id)
        theme_chain = _theme_chain_details(item.stock_id, item.themes, config)
        row = {
            "stock_id": item.stock_id,
            "name": stock_names.get(item.stock_id, "名稱未設定"),
            "score": item.total_score,
            "grade": _grade(item.total_score),
            "label": item.label,
            "label_text": _status_text(item.label),
            "price": item.price,
            "technical": _first(item.reasons.get("technical", [])),
            "chip": _first(item.reasons.get("chip", [])),
            "fundamental": _first(item.reasons.get("fundamental", [])),
            "risk": _first(item.reasons.get("risk", [])),
            "opportunity": _first(item.reasons.get("opportunity", [])),
            "technical_score": item.technical_score,
            "chip_score": item.chip_score,
            "fundamental_score": item.fundamental_score,
            "risk_score": item.risk_score,
            "action": item.action or "只觀察",
            "entry_condition": item.entry_condition or "資料不足，暫不設進場條件",
            "stop_reference": item.stop_reference or "資料不足，暫不設停損參考",
            "stop_price": item.stop_price,
            "entry_limit_price": item.entry_limit_price,
            "themes": item.themes,
            "theme_tiers": item.theme_tiers,
            "theme_chain": theme_chain,
            "chain_summary": _chain_summary(theme_chain),
            "entry_decision": item.entry_decision,
            "entry_checklist": item.entry_checklist,
            "overseas_adjustment": item.overseas_adjustment,
            "opportunity_score": item.opportunity_score,
            "warnings": item.warnings,
            "trigger_tags": item.trigger_tags,
            "pattern_tags": item.pattern_tags,
            "pattern_risk_tags": item.pattern_risk_tags,
            "atr_pct": item.atr_pct,
            "trigger_summary": item.trigger_summary,
            "decision_reason": _decision_reason(item),
            "retail_signal": item.retail_signal,
            "selection_quality_adjustment": item.selection_quality_adjustment,
            "selection_quality_notes": item.selection_quality_notes,
            "ai_review": ai_review,
            "ai_label": _ai_review_label(ai_review),
        }
        row["exit_plan"] = _exit_plan(row)
        rows.append(row)
    valid = [row for row in rows if row["label"] != "DATA_INSUFFICIENT"]
    action_lists = _action_lists(rows, ai_picks=ai_picks, exit_risks=exit_risks)
    _annotate_action_context(rows, action_lists, exit_risks=exit_risks, retail_divergence=retail_divergence)
    action_lists = _action_lists(rows, ai_picks=ai_picks, exit_risks=exit_risks)
    data_quality = _data_quality(source_status, rows, ai_status=ai_status)
    health = _build_health_status(as_of, source_status, theme_signal)
    return {
        "as_of": as_of.isoformat(),
        "generated_at": health.get("generated_at"),
        "generated_date": health.get("generated_date"),
        "market": {"summary": market_summary, "warning": market_warning},
        "overseas": {
            "label": overseas.label if overseas else "未納入",
            "summary": overseas.summary if overseas else "未納入",
            "reasons": overseas.reasons if overseas else [],
            "sector_impacts": overseas.sector_impacts if overseas else [],
        },
        "themes": {
            "summary": theme_signal.summary if theme_signal else "未納入",
            "active": theme_signal.active_themes if theme_signal else [],
            "headlines": theme_signal.headlines[:8] if theme_signal else [],
            "scores": theme_signal.scores if theme_signal else {},
            "matched_headlines": theme_signal.matched_headlines if theme_signal else {},
            "quality": theme_signal.quality if theme_signal else {},
            "catalyst_confidence": {
                key: {
                    "grade": value.grade,
                    "label": value.label,
                    "reason": value.reason,
                    "evidence_count": value.evidence_count,
                }
                for key, value in (theme_signal.catalyst_confidence or {}).items()
            } if theme_signal else {},
            "names": {key: value.get("name", key) for key, value in config.get("theme_pools", {}).items()},
            "pool_counts": {
                key: len(value.get("stocks", {}))
                for key, value in config.get("theme_pools", {}).items()
            },
            "momentum": {
                key: {
                    "today": mom.today,
                    "avg_3d": round(mom.avg_3d, 1),
                    "trend": mom.trend,
                    "history": mom.history[:7],
                }
                for key, mom in (theme_signal.momentum or {}).items()
            } if theme_signal else {},
            "policy": {
                "summary": theme_signal.policy.summary,
                "theme_boosts": theme_signal.policy.theme_boosts,
                "matched_headlines": theme_signal.policy.matched_headlines,
                "us_events": theme_signal.policy.us_events,
            } if theme_signal and theme_signal.policy else {
                "summary": "未納入",
                "theme_boosts": {},
                "matched_headlines": {},
                "us_events": [],
            },
            "discovery": theme_signal.discovered_themes if theme_signal else [],
            "chain_map": _theme_chain_payload(config),
        },
        "source_status": source_status or {"label": "未知"},
        "health": health,
        "alerts": alerts or [],
        "watch_reviews": watch_reviews or [],
        "exit_risks": exit_risks or [],
        "retail_divergence": retail_divergence or empty_retail_divergence(as_of),
        "action_lists": action_lists,
        "data_quality": data_quality,
        "data_source_health": _data_source_health(source_status, data_quality),
        "decision_summary": _decision_summary(rows, action_lists, data_quality, health, theme_signal),
        "summary": {
            "scanned": len(rows),
            "valid": len(valid),
            "s_plus_grade": sum(1 for row in valid if row["grade"] == "S+"),
            "s_grade": sum(1 for row in valid if row["grade"] == "S"),
            "a_grade": sum(1 for row in valid if row["grade"] == "A"),
            "b_grade": sum(1 for row in valid if row["grade"] == "B"),
            "data_insufficient": len(rows) - len(valid),
        },
        "rows": rows,
    }


def enrich_dashboard_payload(
    payload: dict,
    *,
    source_status: dict | None = None,
    ai_picks: list[dict] | None = None,
    ai_status: dict | None = None,
    exit_risks: list[dict] | None = None,
    retry_summary: dict | None = None,
    recommendation_stability: dict | None = None,
) -> dict:
    rows = payload.get("rows", [])
    ai_reviews = {str(item.get("stock_id")): item for item in ai_picks or []}
    stability_by_stock = (recommendation_stability or payload.get("recommendation_stability") or {}).get("by_stock", {})
    for row in rows:
        review = ai_reviews.get(str(row.get("stock_id")))
        stability = stability_by_stock.get(str(row.get("stock_id"))) or {}
        row["ai_review"] = review
        row["ai_label"] = _ai_review_label(review)
        row["stability"] = stability
        row["stability_label"] = stability.get("stability_label") or "新進名單"
        row["stability_reason"] = stability.get("stability_reason") or "近期尚無連續推薦紀錄。"
    if recommendation_stability is not None:
        payload["recommendation_stability"] = recommendation_stability
    payload["action_lists"] = _action_lists(
        rows,
        ai_picks=ai_picks,
        exit_risks=exit_risks if exit_risks is not None else payload.get("exit_risks", []),
    )
    _annotate_action_context(
        rows,
        payload.get("action_lists", {}),
        exit_risks=exit_risks if exit_risks is not None else payload.get("exit_risks", []),
        retail_divergence=payload.get("retail_divergence", {}),
    )
    payload["action_lists"] = _action_lists(
        rows,
        ai_picks=ai_picks,
        exit_risks=exit_risks if exit_risks is not None else payload.get("exit_risks", []),
    )
    payload["data_quality"] = _data_quality(
        source_status if source_status is not None else payload.get("source_status", {}),
        rows,
        ai_status=ai_status,
        retry_summary=retry_summary if retry_summary is not None else payload.get("data_retry", {}),
    )
    payload["data_source_health"] = _data_source_health(
        source_status if source_status is not None else payload.get("source_status", {}),
        payload.get("data_quality", {}),
        retry_summary if retry_summary is not None else payload.get("data_retry", {}),
    )
    previous_top_theme = (payload.get("decision_summary") or {}).get("top_theme")
    payload["decision_summary"] = _decision_summary(
        rows,
        payload.get("action_lists", {}),
        payload.get("data_quality", {}),
        payload.get("health", {}),
        None,
    )
    if previous_top_theme and not payload["decision_summary"].get("top_theme"):
        payload["decision_summary"]["top_theme"] = previous_top_theme
    return payload


def write_dashboard(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "dashboard_data.json").write_text(json_text, encoding="utf-8")
    # Embed data inline so the file works when opened via file:// without a server
    safe_json = json_text.replace("</script>", r"<\/script>")
    inline_script = f"window.__DASHBOARD_DATA__ = {safe_json};"
    html = _html().replace(
        "/* __INLINE_DATA_SENTINEL__ */",
        inline_script,
    )
    html = _apply_quant_ui(html)
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def write_performance(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "performance_data.json").write_text(json_text, encoding="utf-8")
    # Embed data inline so the file works when opened via file:// without a server
    safe_json = json_text.replace("</script>", r"<\/script>")
    inline_script = f"window.__PERFORMANCE_DATA__ = {safe_json};"
    html = _performance_html().replace(
        "/* __INLINE_PERF_SENTINEL__ */",
        inline_script,
    )
    html = _apply_quant_ui(html)
    (output_dir / "performance.html").write_text(html, encoding="utf-8")


def write_potential(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    potential_payload = {
        "as_of": payload.get("as_of"),
        "days": payload.get("days"),
        "potential_radar": payload.get("potential_radar", {}),
        "learning_center": payload.get("learning_center", {}),
    }
    json_text = json.dumps(potential_payload, ensure_ascii=False, indent=2)
    (output_dir / "potential_data.json").write_text(json_text, encoding="utf-8")
    safe_json = json_text.replace("</script>", r"<\/script>")
    inline_script = f"window.__POTENTIAL_DATA__ = {safe_json};"
    html = _potential_html().replace(
        "/* __INLINE_POTENTIAL_SENTINEL__ */",
        inline_script,
    )
    html = _apply_quant_ui(html)
    (output_dir / "potential.html").write_text(html, encoding="utf-8")


def write_theme_history(payload: dict[str, list[dict]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "theme_history.json").write_text(json_text, encoding="utf-8")


def _apply_quant_ui(html: str) -> str:
    """Apply the shared command-center visual layer without touching data logic."""

    return html.replace("</style>", _quant_ui_css() + "\n  </style>", 1)


def _quant_ui_css() -> str:
    return r"""

    /* Quant workstation visual refresh */
    :root {
      --q-bg:#edf2f8;
      --q-bg-deep:#09111f;
      --q-panel:#ffffff;
      --q-panel-soft:#f8fbff;
      --q-ink:#132033;
      --q-muted:#60708a;
      --q-line:#d8e2ef;
      --q-blue:#1557b0;
      --q-blue-2:#4f8cff;
      --q-cyan:#17b7b2;
      --q-good:#07845a;
      --q-warn:#a66a00;
      --q-bad:#c03221;
      --q-shadow:0 18px 46px rgba(15,23,42,.10);
      --q-shadow-sm:0 8px 22px rgba(15,23,42,.07);
    }
    body {
      color:var(--q-ink);
      background:
        radial-gradient(circle at 18% -12%, rgba(79,140,255,.26), transparent 34%),
        linear-gradient(180deg,#0a1220 0,#122238 164px,#edf2f8 165px,#f6f8fb 100%);
      -webkit-font-smoothing:antialiased;
      text-rendering:optimizeLegibility;
    }
    header {
      max-width:1660px;
      margin:0 auto;
      padding:24px 24px 18px;
      background:transparent !important;
      border-bottom:0 !important;
      box-shadow:none !important;
    }
    header h1 {
      font-size:clamp(24px,2.4vw,34px);
      font-weight:900;
      letter-spacing:0;
    }
    header .sub {
      color:#c6d3e6 !important;
    }
    main {
      max-width:1660px;
      padding-top:0;
    }
    .nav-tabs {
      top:0;
      margin:0 0 18px;
      padding:10px;
      border:1px solid rgba(148,163,184,.24);
      border-radius:16px;
      background:rgba(8,17,32,.88) !important;
      box-shadow:0 18px 44px rgba(8,17,32,.22);
      backdrop-filter:blur(18px);
    }
    .nav-tab {
      min-height:42px;
      padding:9px 16px;
      border-radius:12px;
      border:1px solid rgba(203,213,225,.18);
      background:rgba(255,255,255,.08);
      color:#dbeafe !important;
      font-weight:900;
      box-shadow:none;
      transition:background .16s ease, transform .16s ease, border-color .16s ease;
    }
    .nav-tab:hover {
      transform:translateY(-1px);
      background:rgba(255,255,255,.14);
      text-decoration:none;
    }
    .nav-tab.active {
      color:#04111f !important;
      border-color:transparent !important;
      background:linear-gradient(135deg,#67e8f9 0,#60a5fa 54%,#93c5fd 100%) !important;
      box-shadow:0 10px 26px rgba(96,165,250,.28);
    }
    section, details.panel, .metric, .quality-card, .trace-card, .decision-card,
    .temperature-card, .decision-summary-compact, .toolbar, .stock-drawer,
    table, tr {
      border-color:var(--q-line) !important;
      box-shadow:var(--q-shadow-sm);
    }
    section, details.panel, .metric, .quality-card, .trace-card, .decision-card,
    .temperature-card, .decision-summary-compact {
      background:linear-gradient(180deg,#ffffff 0,#fbfdff 100%) !important;
      border-radius:16px !important;
    }
    section, details.panel {
      padding:16px;
    }
    h2 {
      color:#0f1d33;
      font-weight:900;
      letter-spacing:0;
    }
    .metrics, .summary-grid {
      gap:12px;
    }
    .metric {
      position:relative;
      overflow:hidden;
      min-height:82px;
      padding:14px 16px;
      border-top:0 !important;
    }
    .metric::before {
      content:"";
      position:absolute;
      inset:0 0 auto 0;
      height:3px;
      background:linear-gradient(90deg,var(--q-blue-2),var(--q-cyan));
    }
    .metric b {
      color:#07172c;
      font-weight:950;
    }
    .metric span, .sub, .small, .line, .note {
      letter-spacing:0;
    }
    .dashboard-layout, .content-grid, .grid, .analysis-grid {
      gap:16px;
    }
    .side-stack {
      top:78px;
    }
    .action-panel {
      border-top:0 !important;
      border-left:5px solid var(--q-good) !important;
      box-shadow:var(--q-shadow);
    }
    .risk-panel {
      border-top:0 !important;
      border-left:5px solid var(--q-bad) !important;
    }
    .theme-panel, .wide-panel {
      box-shadow:var(--q-shadow-sm);
    }
    .decision-card {
      padding:14px;
      border-radius:16px !important;
    }
    .decision-card.chase { border-left:5px solid var(--q-good) !important; }
    .decision-card.pullback { border-left:5px solid var(--q-warn) !important; }
    .decision-card.avoid { border-left:5px solid var(--q-bad) !important; }
    .decision-card-title, a.stock-link, .stock-link {
      color:#004a98 !important;
      font-weight:950;
    }
    .decision-badge, .grade, .tag, .stage {
      letter-spacing:0;
      white-space:nowrap;
      word-break:keep-all;
    }
    .decision-price, .decision-exit div, .decision-note, .brief-row,
    .decision-pill, .drawer-section, .drawer-kv div {
      border-color:#e1e9f4 !important;
      background:#f8fbff !important;
      border-radius:12px !important;
    }
    table {
      border-collapse:separate !important;
      border-spacing:0;
      border-radius:16px !important;
      overflow:hidden;
    }
    th {
      background:#e9eef5 !important;
      color:#334155 !important;
      font-weight:900;
      letter-spacing:0;
      position:static !important;
      top:auto !important;
      z-index:auto !important;
    }
    td {
      background:#fff;
    }
    tbody tr:hover td {
      background:#f7fbff;
    }
    input, select {
      border-radius:12px !important;
      border-color:var(--q-line) !important;
    }
    .toolbar {
      top:72px;
      border-radius:16px !important;
      background:rgba(255,255,255,.88) !important;
      backdrop-filter:blur(16px);
    }
    .theme-panel #themes,
    .theme-table-wrap {
      max-height:none !important;
      overflow:visible !important;
      padding-right:0 !important;
    }
    .theme-panel .chart-wrap {
      height:clamp(140px,18vw,220px) !important;
      min-height:140px;
    }
    .theme-panel canvas {
      max-width:100%;
    }
    .page-potential main,
    .page-weekly main,
    .page-performance main {
      max-width:1440px;
    }
    .page-potential .grid {
      grid-template-columns:minmax(0,1.08fr) minmax(360px,.72fr) !important;
      gap:16px !important;
    }
    .page-potential section {
      border-radius:18px !important;
    }
    .page-potential .stage {
      min-width:84px;
      min-height:28px;
      justify-content:center;
      font-weight:900;
    }
    .page-potential .metric {
      min-height:88px;
    }
    .page-potential td,
    .page-potential th {
      line-height:1.5;
    }
    .jump-nav a, .detail-button {
      min-height:36px;
      border-radius:12px;
      font-weight:900;
    }
    .stage {
      min-width:76px;
      padding-inline:10px;
    }
    .stock-link {
      display:inline-block;
      white-space:nowrap;
    }
    @media (max-width:1180px) {
      header, main { max-width:100%; }
      .side-stack { top:auto; }
      .nav-tabs { border-radius:14px; }
      .page-potential .grid { grid-template-columns:1fr !important; }
    }
    @media (max-width:720px) {
      body {
        background:linear-gradient(180deg,#0a1220 0,#122238 128px,#edf2f8 129px,#f6f8fb 100%);
      }
      header {
        padding-top:18px;
      }
      .nav-tabs {
        overflow-x:auto;
        flex-wrap:nowrap;
        scrollbar-width:none;
      }
      .nav-tabs::-webkit-scrollbar { display:none; }
      .nav-tab {
        flex:0 0 auto;
      }
      section, details.panel {
        padding:14px;
      }
      tr {
        box-shadow:var(--q-shadow-sm);
      }
    }
"""


def build_debug_payload(dashboard_payload: dict, performance_payload: dict | None = None) -> dict:
    """Build an internal data-chain snapshot for troubleshooting daily runs."""

    source_status = dashboard_payload.get("source_status") or {}
    data_quality = dashboard_payload.get("data_quality") or {}
    data_retry = dashboard_payload.get("data_retry") or {}
    traceability = dashboard_payload.get("traceability") or {}
    ai_status = (dashboard_payload.get("ai_council") or {}).get("status") or {}
    performance = performance_payload or {}
    bundle_coverage = source_status.get("bundle_coverage") or {}
    universe = source_status.get("universe") or {}
    return {
        "as_of": dashboard_payload.get("as_of"),
        "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "dashboard_generated_at": dashboard_payload.get("generated_at"),
        "source_status": {
            "label": source_status.get("label"),
            "api": source_status.get("api", 0),
            "cache": source_status.get("cache", 0),
            "fallback": source_status.get("fallback", 0),
            "quota": source_status.get("quota", 0),
            "error": source_status.get("error", 0),
            "empty": source_status.get("empty", 0),
            "official_snapshots": source_status.get("official_snapshots", {}),
            "market_snapshots": source_status.get("market_snapshots", {}),
        },
        "data_quality": data_quality,
        "data_source_health": dashboard_payload.get("data_source_health", {}),
        "bundle_coverage": bundle_coverage,
        "universe": universe,
        "retry": {
            "status_counts": data_retry.get("status_counts", {}),
            "pending": data_retry.get("pending", 0),
            "failed": data_retry.get("failed", 0),
            "recovered": data_retry.get("recovered", 0),
            "diagnosis": data_retry.get("diagnosis", []),
            "recovered_by_dataset": data_retry.get("recovered_by_dataset", []),
            "recent_items": data_retry.get("items", []),
        },
        "traceability": {
            "steps": traceability.get("steps", []),
            "summary": traceability.get("summary", {}),
            "diagnosis": build_traceability_diagnosis(traceability, dashboard_payload),
            "history": traceability.get("history", []),
        },
        "ai": {
            "health": ai_status.get("health", {}),
            "requested_models": ai_status.get("requested_models", 0),
            "successful_models": ai_status.get("successful_models", 0),
            "failed_model_names": ai_status.get("failed_model_names", []),
            "success_model_names": ai_status.get("success_model_names", []),
        },
        "performance": {
            "stats": performance.get("stats", {}),
            "potential_radar": (performance.get("potential_radar") or {}).get("stats", {}),
        },
        "note": "Internal diagnostics only. It contains no secrets and is not linked from the dashboard UI.",
    }


def write_debug(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "debug_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_traceability_summary(dashboard_payload: dict, performance_payload: dict | None = None) -> dict:
    """Build a compact end-to-end health map for the dashboard."""

    performance = performance_payload or {}
    summary = dashboard_payload.get("summary") or {}
    source_status = dashboard_payload.get("source_status") or {}
    data_quality = dashboard_payload.get("data_quality") or {}
    data_source_health = dashboard_payload.get("data_source_health") or {}
    retry = dashboard_payload.get("data_retry") or {}
    perf_stats = performance.get("stats") or {}
    potential_stats = (performance.get("potential_radar") or {}).get("stats") or {}
    ai_status = (dashboard_payload.get("ai_council") or {}).get("status") or {}
    ai_health = ai_status.get("health") or {}
    bundle_coverage = source_status.get("bundle_coverage") or {}
    universe = source_status.get("universe") or {}

    def _pct(value) -> str:
        if value is None:
            return "-"
        try:
            return f"{float(value):.1f}%"
        except (TypeError, ValueError):
            return "-"

    def _count(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    source_label = str(source_status.get("label") or "unknown")
    health_label = str(data_source_health.get("label") or "")
    source_problem = (
        source_label in {"錯誤", "限流"}
        or _count(source_status.get("error")) > 0
        or health_label == "需檢查"
    )
    source_warn = (
        source_problem
        or _count(source_status.get("quota")) > 0
        or str(data_quality.get("label")) == "low"
        or health_label == "可用但待補"
    )
    source_step_status = "bad" if source_problem else "warn" if source_warn else "ok"

    scanned = _count(summary.get("scanned"))
    valid = _count(summary.get("valid"))
    watch_total = _count(perf_stats.get("signals"))
    watch_completed = _count(perf_stats.get("completed"))
    potential_total = _count(potential_stats.get("signals"))
    potential_completed = _count(potential_stats.get("completed"))
    retry_pending = _retry_status_count(retry, "pending")
    retry_failed = _retry_status_count(retry, "failed")
    retry_recovered = _retry_status_count(retry, "recovered")
    ai_score = _count(ai_health.get("score"))

    steps = [
        {
            "key": "source",
            "label": "資料源",
            "status": source_step_status,
            "value": source_status.get("label") or "-",
            "note": f"API {source_status.get('api', 0)} | 快取 {source_status.get('cache', 0)} | 限流 {source_status.get('quota', 0)}",
        },
        {
            "key": "score",
            "label": "每日評分",
            "status": "ok" if valid > 0 else "bad",
            "value": f"{valid}/{scanned} 檔",
            "note": f"S+ {summary.get('s_plus_grade', 0)} | S {summary.get('s_grade', 0)} | A {summary.get('a_grade', 0)}",
        },
        {
            "key": "watch",
            "label": "進場追蹤",
            "status": "ok" if watch_total > 0 else "warn",
            "value": f"{watch_total} 筆",
            "note": f"完成 {watch_completed} | 5日勝率 {_pct(perf_stats.get('win_rate_5d'))}",
        },
        {
            "key": "potential",
            "label": "潛力雷達",
            "status": "ok" if potential_total > 0 else "warn",
            "value": f"{potential_total} 筆",
            "note": f"完成 {potential_completed} | 5日勝率 {_pct(potential_stats.get('win_rate_5d'))}",
        },
        {
            "key": "ai",
            "label": "AI 複核",
            "status": "ok" if ai_score >= 70 else "warn" if ai_score > 0 else "warn",
            "value": ai_health.get("label") or "-",
            "note": f"模型 {ai_status.get('successful_models', 0)}/{ai_status.get('requested_models', 0)} | 同意門檻 {dashboard_payload.get('ai_council', {}).get('min_agree_count', '-')}",
        },
        {
            "key": "retry",
            "label": "補抓佇列",
            "status": "warn" if (retry_failed or retry_pending) else "ok",
            "value": f"待補 {retry_pending}",
            "note": f"已補 {retry_recovered} | 失敗 {retry_failed}",
        },
        {
            "key": "pages",
            "label": "頁面輸出",
            "status": "ok",
            "value": "4 頁",
            "note": "今日監控 | 訊號成效 | 潛力雷達 | 每週總覽",
        },
    ]
    return {
        "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "steps": steps,
        "summary": {
            "scanned": scanned,
            "valid": valid,
            "watch_signals": watch_total,
            "watch_completed": watch_completed,
            "potential_signals": potential_total,
            "potential_completed": potential_completed,
            "data_coverage": {
                "bundle_stocks": bundle_coverage.get("stocks", 0),
                "all_critical_complete": bool(bundle_coverage.get("all_critical_complete", False)),
                "datasets": {
                    key: {
                        "coverage_pct": row.get("coverage_pct"),
                        "missing_count": len(row.get("missing") or []),
                    }
                    for key, row in (bundle_coverage.get("datasets") or {}).items()
                },
            },
            "universe": {
                "mode": universe.get("mode"),
                "selected_count": universe.get("selected_count"),
                "target_total_listed": universe.get("target_total_listed"),
                "coverage_pct": universe.get("coverage_pct"),
                "market_universe_available": universe.get("market_universe_available"),
            },
        },
    }


def build_traceability_diagnosis(traceability: dict, dashboard_payload: dict) -> list[dict]:
    """Build internal-only root-cause notes for non-OK data chain steps."""

    retry = dashboard_payload.get("data_retry") or {}
    source_status = dashboard_payload.get("source_status") or {}
    data_quality = dashboard_payload.get("data_quality") or {}
    summary = dashboard_payload.get("summary") or {}
    ai_council = dashboard_payload.get("ai_council") or {}
    ai_status = ai_council.get("status") or {}

    def _count(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _step_value(key: str, field: str = "status") -> str:
        for step in traceability.get("steps") or []:
            if str(step.get("key") or "") == key:
                return str(step.get(field) or "")
        return ""

    def _retry_count(key: str) -> int:
        return _count(retry.get(key)) + _count((retry.get("status_counts") or {}).get(key))

    def _metric_count(value) -> int:
        if isinstance(value, (list, tuple, set)):
            return len(value)
        return _count(value)

    diagnosis: list[dict] = []
    for step in traceability.get("steps") or []:
        key = str(step.get("key") or "")
        status = str(step.get("status") or "")
        if status == "ok":
            continue

        item = {
            "key": key,
            "status": status,
            "label": step.get("label") or key,
            "reason": "",
            "evidence": step.get("note") or step.get("value") or "",
            "next_action": "",
        }
        if key == "source":
            item.update(
                {
                    "reason": "資料源狀態或資料品質低於正常門檻。",
                    "evidence": (
                        f"source={source_status.get('label', '-')}; "
                        f"quality={data_quality.get('label', '-')}; "
                        f"api={source_status.get('api', 0)}; cache={source_status.get('cache', 0)}; "
                        f"quota={source_status.get('quota', 0)}; error={source_status.get('error', 0)}"
                    ),
                    "next_action": "優先確認 TWSE/TPEX 官方資料、fallback 與快取是否成功補回。",
                }
            )
        elif key == "score":
            item.update(
                {
                    "reason": "本次掃描沒有足夠有效評分標的。",
                    "evidence": f"valid={summary.get('valid', 0)}; scanned={summary.get('scanned', 0)}",
                    "next_action": "檢查行情資料、股票池與評分輸入是否缺漏。",
                }
            )
        elif key == "watch":
            item.update(
                {
                    "reason": "本次沒有產生可追蹤的進場訊號。",
                    "evidence": _step_value("watch", "note"),
                    "next_action": "檢查 BUY_WATCH 門檻、操作結論與 watch_signals 寫入流程。",
                }
            )
        elif key == "potential":
            item.update(
                {
                    "reason": "潛力雷達沒有產生可追蹤訊號。",
                    "evidence": _step_value("potential", "note"),
                    "next_action": "檢查潛力雷達條件是否過嚴，或題材/籌碼/K 線資料是否缺漏。",
                }
            )
        elif key == "ai":
            item.update(
                {
                    "reason": "AI 複核模型未完全穩定或成功數不足。",
                    "evidence": (
                        f"successful={_metric_count(ai_status.get('successful_models'))}; "
                        f"requested={_metric_count(ai_status.get('requested_models'))}; "
                        f"failed={_metric_count(ai_status.get('failed_models'))}; "
                        f"timed_out={_metric_count(ai_status.get('timed_out_models'))}"
                    ),
                    "next_action": "確認 DeepSeek/OpenRouter Secret、模型名稱、timeout 與回傳 JSON 格式。",
                }
            )
        elif key == "retry":
            item.update(
                {
                    "reason": "補抓佇列仍有待補或失敗紀錄。",
                    "evidence": (
                        f"pending={_retry_count('pending')}; "
                        f"recovered={_retry_count('recovered')}; "
                        f"failed={_retry_count('failed')}"
                    ),
                    "next_action": "若資料品質仍為 high 可先觀察；連續多日 failed 才調整資料源或清理佇列。",
                }
            )
        elif key == "pages":
            item.update(
                {
                    "reason": "Dashboard 或 GitHub Pages 輸出流程異常。",
                    "evidence": _step_value("pages", "note"),
                    "next_action": "檢查 dashboard/docs 檔案是否同步，以及 Pages workflow 是否成功。",
                }
            )
        else:
            item.update(
                {
                    "reason": "未知資料鏈步驟出現非正常狀態。",
                    "next_action": "檢查 traceability steps 原始紀錄。",
                }
            )
        diagnosis.append(item)
    return diagnosis


def build_weekly_overview_payload(
    as_of: date,
    dashboard_payload: dict,
    performance_payload: dict,
    theme_history: dict[str, list[dict]],
    institutional_summary: dict,
    data_updates: list[dict] | None = None,
) -> dict:
    themes = dashboard_payload.get("themes", {})
    theme_names = themes.get("names", {})
    theme_scores = themes.get("scores", {})
    theme_momentum = themes.get("momentum", {})
    theme_rows = []
    for key, history in theme_history.items():
        recent = list(history or [])[:7]
        score_sum = sum(int(item.get("score") or 0) for item in recent)
        if score_sum <= 0 and int(theme_scores.get(key) or 0) <= 0:
            continue
        theme_rows.append(
            {
                "key": key,
                "name": theme_names.get(key, key),
                "today": int(theme_scores.get(key) or 0),
                "week_score": score_sum,
                "avg_3d": (theme_momentum.get(key) or {}).get("avg_3d"),
                "trend": (theme_momentum.get(key) or {}).get("trend"),
                "history": recent,
            }
        )
    theme_rows.sort(key=lambda item: (item["week_score"], item["today"]), reverse=True)
    return {
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "market": dashboard_payload.get("market", {}),
        "overseas": dashboard_payload.get("overseas", {}),
        "retail_divergence": dashboard_payload.get("retail_divergence", {}),
        "institutional": institutional_summary,
        "data_updates": data_updates or [],
        "themes": theme_rows[:12],
        "performance": {
            "stats": performance_payload.get("stats", {}),
            "top_themes": performance_payload.get("top_themes", []),
            "score_bands": performance_payload.get("score_bands", []),
            "selection_quality": performance_payload.get("selection_quality", {}),
        },
    }


def write_weekly_overview(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "weekly_data.json").write_text(json_text, encoding="utf-8")
    safe_json = json_text.replace("</script>", r"<\/script>")
    inline_script = f"window.__WEEKLY_DATA__ = {safe_json};"
    html = _weekly_html().replace(
        "/* __INLINE_WEEKLY_SENTINEL__ */",
        inline_script,
    )
    html = _apply_quant_ui(html)
    (output_dir / "weekly.html").write_text(html, encoding="utf-8")


def _html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 開盤前監控</title>
  <style>
    :root { color-scheme: light; --ink:#172033; --muted:#64748b; --line:#d6deea; --bg:#eef3f8; --panel:#fff; --panel2:#f8fafc; --good:#0f7b4f; --warn:#9a6700; --bad:#b42318; --terminal:#0b1220; --terminal2:#111827; --blue:#0b4a8b; --soft:#f8fafc; --shadow:0 10px 28px rgba(15,23,42,.08); --shadow-sm:0 2px 8px rgba(15,23,42,.06); }
    * { box-sizing: border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; font-family: "Segoe UI", Arial, sans-serif; color:var(--ink); background:linear-gradient(180deg,#e8eef6 0,#f3f6fa 220px,#eef3f8 100%); line-height:1.45; }
    header { padding:20px 24px 16px; border-bottom:1px solid rgba(255,255,255,.08); background:linear-gradient(120deg,#07111f 0,#0b1220 62%,#10233b 100%); color:#fff; box-shadow:0 14px 30px rgba(15,23,42,.18); }
    h1 { margin:0 0 8px; font-size:24px; letter-spacing:0; }
    .sub { color:#cbd5e1; font-size:14px; }
    main { padding:16px 22px 36px; max-width:1660px; margin:auto; }
    .jump-nav { display:flex; gap:6px; flex-wrap:wrap; margin:-6px 0 14px; }
    .jump-nav a { display:inline-flex; align-items:center; min-height:30px; padding:5px 10px; border:1px solid #cfd7e6; border-radius:999px; background:rgba(255,255,255,.86); color:#0b4a8b; text-decoration:none; font-size:12px; font-weight:800; box-shadow:0 1px 3px rgba(15,23,42,.05); }
    .jump-nav a:hover { background:#fff; border-color:#93b4d8; }
    .metrics { display:grid; grid-template-columns: repeat(5, minmax(112px,1fr)); gap:8px; margin-bottom:10px; }
    .metric { background:linear-gradient(180deg,#fff,#fbfdff); border:1px solid var(--line); border-top:3px solid #dbeafe; border-radius:10px; padding:10px 12px; min-height:64px; box-shadow:var(--shadow-sm); }
    .metric.is-good { border-top-color:#86efac; }
    .metric.is-warn { border-top-color:#facc15; }
    .metric.is-bad { border-top-color:#fda4af; }
    .metric b { display:block; font-size:clamp(17px, 4vw, 21px); margin-bottom:2px; overflow-wrap:anywhere; }
    .metric span { color:var(--muted); font-size:13px; }
    .dashboard-layout { display:grid; grid-template-columns:minmax(0,1.65fr) minmax(360px,.65fr); gap:14px; margin-bottom:16px; align-items:start; }
    .main-stack, .side-stack { display:grid; gap:12px; }
    .side-stack { position:sticky; top:12px; }
    .market-theme-grid { display:grid; grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr); gap:12px; }
    .detail-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; grid-column:1 / -1; }
    section, details.panel { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; box-shadow:var(--shadow-sm); }
    details.panel summary { cursor:pointer; font-weight:700; font-size:16px; list-style:none; }
    details.panel summary::-webkit-details-marker { display:none; }
    details.panel summary::after { content:"＋"; float:right; color:var(--muted); }
    details.panel[open] summary::after { content:"－"; }
    .section-note { color:var(--muted); font-size:12px; margin-top:-4px; margin-bottom:8px; }
    .status-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px; }
    .trace-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:8px; }
    .trace-card { border:1px solid var(--line); border-radius:10px; padding:9px; background:#fbfcfe; min-height:74px; }
    .trace-card.ok { border-left:4px solid var(--good); }
    .trace-card.warn { border-left:4px solid var(--warn); }
    .trace-card.bad { border-left:4px solid var(--bad); }
    .trace-card b { display:block; font-size:13px; margin-bottom:3px; }
    .trace-value { font-size:17px; font-weight:800; line-height:1.25; }
    .trace-note { color:var(--muted); font-size:11px; line-height:1.35; margin-top:3px; }
    .trace-history { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
    .trace-day { border:1px solid var(--line); border-radius:999px; padding:4px 8px; font-size:11px; background:#fff; }
    .trace-day.ok { color:var(--good); border-color:#abefc6; }
    .trace-day.warn { color:var(--warn); border-color:#f6d365; }
    .trace-day.bad { color:var(--bad); border-color:#fecdd6; }
    .action-panel { border:1px solid #b7e4cf; border-top:4px solid var(--good); padding:16px; box-shadow:0 12px 30px rgba(15,118,73,.08); scroll-margin-top:82px; }
    .action-head { display:grid; grid-template-columns:minmax(300px,.86fr) minmax(320px,.64fr); gap:14px; align-items:start; margin-bottom:10px; }
    .action-title h2 { font-size:19px; margin-bottom:4px; }
    .action-title .line { margin:0; }
    .decision-brief { display:grid; gap:8px; margin-top:12px; }
    .brief-row { display:grid; grid-template-columns:104px minmax(0,1fr); gap:10px; align-items:start; border:1px solid #dfe7f1; border-radius:10px; background:#fff; padding:9px 10px; }
    .brief-row b { color:#0b4a8b; font-size:13px; }
    .brief-row span { color:#334155; font-size:13px; }
    .action-overview { display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 10px; }
    .action-chip { display:inline-flex; align-items:center; min-height:32px; padding:5px 10px; border:1px solid var(--line); border-radius:999px; background:#fff; font-size:13px; font-weight:800; }
    .action-chip.good { color:var(--good); border-color:#abefc6; background:#f0fdf4; }
    .action-chip.warn { color:var(--warn); border-color:#f6d365; background:#fffbeb; }
    .action-group { margin-top:10px; }
    .action-group-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin:4px 0 6px; }
    .action-group-head b { font-size:14px; }
    .action-group-head span { color:var(--muted); font-size:12px; }
    #actionLists > .line.good, #actionLists > .line.warn {
      display:flex; align-items:center; justify-content:space-between; gap:8px;
      margin:14px 0 8px; padding:8px 11px; border-radius:10px; font-weight:800;
    }
    #actionLists > .line.good { background:#f0fdf4; border:1px solid #abefc6; }
    #actionLists > .line.warn { background:#fffbeb; border:1px solid #f6d365; }
    .decision-summary-compact { border:1px solid var(--line); border-radius:12px; padding:10px; background:#fbfcfe; box-shadow:inset 0 1px 0 rgba(255,255,255,.8); }
    .decision-summary-compact .temperature-card { margin-bottom:7px; }
    .decision-strip { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; margin:6px 0 8px; }
    .decision-pill { border:1px solid var(--line); border-radius:10px; padding:8px 9px; background:#fff; min-height:56px; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .decision-pill b { display:block; font-size:18px; line-height:1.2; }
    .decision-pill span { color:var(--muted); font-size:12px; }
    .decision-pill.good { border-left:4px solid var(--good); }
    .decision-pill.warn { border-left:4px solid var(--warn); }
    .decision-pill.bad { border-left:4px solid var(--bad); }
    .temperature-card { border:1px solid var(--line); border-radius:10px; padding:10px; background:#fbfcfe; margin-bottom:10px; }
    .temperature-card.good { border-left:4px solid var(--good); }
    .temperature-card.warn { border-left:4px solid var(--warn); }
    .temperature-card.bad { border-left:4px solid var(--bad); }
    .temperature-card b { display:block; font-size:20px; margin-bottom:4px; }
    .decision-card-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr)); gap:10px; margin:8px 0 10px; }
    .decision-card { border:1px solid var(--line); border-radius:12px; padding:12px; background:linear-gradient(180deg,#fff,#fbfdff); min-height:132px; box-shadow:var(--shadow-sm); transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease; }
    .decision-card:hover { transform:translateY(-1px); box-shadow:var(--shadow); border-color:#b6c7dc; }
    .decision-card.chase { border-left:4px solid var(--good); }
    .decision-card.pullback { border-left:4px solid var(--warn); }
    .decision-card.avoid { border-left:4px solid var(--bad); }
    .decision-card-head { display:flex; gap:8px; justify-content:space-between; align-items:flex-start; }
    .decision-card-actions { display:flex; align-items:center; gap:6px; flex-shrink:0; }
    .decision-card-title { font-weight:800; line-height:1.25; }
    .decision-light { display:inline-flex; align-items:center; gap:4px; margin-top:3px; font-size:12px; font-weight:800; }
    .decision-dot { width:9px; height:9px; border-radius:999px; display:inline-block; background:#94a3b8; }
    .decision-light.green .decision-dot { background:var(--good); }
    .decision-light.yellow .decision-dot { background:var(--warn); }
    .decision-light.red .decision-dot { background:var(--bad); }
    .decision-light.gray .decision-dot { background:#94a3b8; }
    .decision-note-grid { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:6px; }
    .decision-note { background:#f8fafc; border:1px solid #eef1f5; border-radius:8px; padding:7px; font-size:12px; line-height:1.35; color:var(--muted); }
    .decision-note b { color:var(--ink); }
    .decision-badge { display:inline-flex; align-items:center; min-height:22px; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:800; white-space:nowrap; }
    .decision-badge.chase { color:#fff; background:var(--good); }
    .decision-badge.pullback { color:#3b2f00; background:#f6d365; }
    .decision-badge.avoid { color:#fff; background:var(--bad); }
    .decision-prices { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin:7px 0; }
    .decision-price { border:1px solid #e6edf5; border-radius:8px; padding:7px; min-height:46px; background:#fff; }
    .decision-price span { display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
    .decision-price b { font-size:15px; }
    .decision-exit { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; margin:6px 0; }
    .decision-exit div { border:1px solid #eef1f5; border-radius:6px; padding:6px; background:#fbfcfe; min-height:46px; }
    .decision-exit span { display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
    .decision-exit b { font-size:14px; }
    .decision-reason { color:var(--muted); font-size:12px; line-height:1.4; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    .risk-panel { border:1px solid #fecdd6; border-top:4px solid var(--bad); scroll-margin-top:82px; }
    .risk-panel #exitRisks { max-height:280px; overflow:auto; padding-right:4px; scrollbar-width:thin; }
    .wide-panel { grid-column:1 / -1; }
    details.panel h2 { font-size:14px; margin:12px 0 6px; }
    h2 { font-size:15px; margin:0 0 8px; }
    .line { color:var(--muted); margin:4px 0; font-size:13px; line-height:1.45; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:12px 0; flex-wrap:wrap; padding:10px; background:rgba(255,255,255,.92); border:1px solid var(--line); border-radius:12px; position:sticky; top:58px; z-index:12; backdrop-filter:blur(10px); box-shadow:var(--shadow-sm); scroll-margin-top:82px; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; position:sticky; top:0; z-index:20; padding:10px 0; background:rgba(238,243,248,.94); backdrop-filter:blur(10px); border-bottom:1px solid rgba(208,213,221,.75); }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:40px; padding:8px 15px; border:1px solid #cfd7e6; border-radius:8px; background:var(--panel); color:#0b4a8b; text-decoration:none; font-weight:800; box-shadow:var(--shadow-sm); }
    .nav-tab.active { background:var(--terminal); color:white; border-color:var(--terminal); }
    input, select { border:1px solid var(--line); border-radius:8px; padding:9px 10px; background:white; min-height:40px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:separate; border-spacing:0; background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; box-shadow:var(--shadow-sm); }
    .table-shell { scroll-margin-top:128px; }
    .chart-wrap { height:96px; margin-top:6px; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef3f8; font-size:12px; color:#475467; position:sticky; top:112px; z-index:8; }
    tbody tr[data-stock-id] { cursor:pointer; }
    tbody tr[data-stock-id]:hover { background:#f8fbff; }
    .grade { font-weight:700; border-radius:999px; padding:3px 8px; display:inline-block; min-width:32px; text-align:center; }
    .grade-S\+ { color:white; background:#7c2d12; }
    .grade-S { color:white; background:#b42318; }
    .grade-A { color:white; background:var(--good); }
    .grade-B { color:#3b2f00; background:#f6d365; }
    .grade-C { color:#344054; background:#e4e7ec; }
    .grade-- { color:#667085; background:#f2f4f7; }
    .small { color:var(--muted); font-size:12px; margin-top:3px; }
    .themes { color:#175cd3; }
    .chain-line { color:#475467; font-size:11px; line-height:1.35; margin-top:3px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    .chain-tags { display:flex; flex-wrap:wrap; gap:5px; margin-top:7px; }
    .chain-tag { display:inline-flex; align-items:center; max-width:100%; min-height:24px; padding:3px 8px; border-radius:999px; background:#f8fafc; border:1px solid #dbe4ef; color:#344054; font-size:11px; font-weight:700; white-space:nowrap; }
    .chain-heat-list { display:grid; gap:6px; margin-top:6px; }
    .chain-heat-item { border:1px solid #e6edf5; border-radius:8px; padding:7px 8px; background:#fbfcfe; }
    .chain-heat-item b { color:#0b4a8b; font-size:12px; margin-right:6px; }
    .chain-heat-item span { color:#9a6700; font-size:12px; font-weight:800; white-space:nowrap; }
    a.stock-link { color:#0b4a8b; text-decoration:none; }
    a.stock-link:hover { text-decoration:underline; }
    .detail-button { appearance:none; border:1px solid #cfd7e6; background:#fff; color:#0b4a8b; border-radius:6px; min-height:28px; padding:4px 8px; font-size:12px; font-weight:800; cursor:pointer; }
    .detail-button:hover { background:#eff6ff; border-color:#93c5fd; }
    .row-actions { margin-top:5px; }
    .bad { color:var(--bad); }
    .warn { color:var(--warn); }
    .good { color:var(--good); }
    .status-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; background:#98a2b3; }
    .status-ok { background:var(--good); }
    .status-warn { background:var(--warn); }
    .status-bad { background:var(--bad); }
    .tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:4px; }
    .tag { display:inline-block; padding:2px 7px; border-radius:999px; font-size:11px; font-weight:600; white-space:nowrap; }
    .tag-theme  { background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; }
    .tag-chip   { background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; }
    .tag-tech   { background:#fff7ed; color:#9a3412; border:1px solid #fed7aa; }
    .tag-fund   { background:#fdf4ff; color:#7e22ce; border:1px solid #e9d5ff; }
    .tag-over   { background:#f0f9ff; color:#0c4a6e; border:1px solid #bae6fd; }
    .tag-pattern{ background:#ecfdf3; color:#067647; border:1px solid #abefc6; }
    .tag-risk   { background:#fff1f3; color:#c01048; border:1px solid #fecdd6; }
    .tag-default{ background:#f8fafc; color:#475467; border:1px solid #e2e8f0; }
    .theme-table-wrap { max-height:128px; overflow:auto; border:1px solid var(--line); border-radius:6px; margin:6px 0; }
    .theme-table-wrap table { border:0; border-radius:0; }
    .theme-reason, .theme-headline { font-size:12px; line-height:1.45; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    .theme-panel #themes { max-height:560px; overflow:auto; padding-right:4px; scrollbar-width:thin; }
    .theme-panel #themes > .line { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    .discovery-list { display:grid; gap:5px; margin-top:6px; }
    .discovery-item { border:1px solid var(--line); border-radius:6px; padding:6px 8px; background:#fcfcfd; }
    .discovery-title { font-size:12px; font-weight:800; color:#0b4a8b; }
    .discovery-meta { font-size:11px; color:var(--muted); margin-top:2px; }
    .mini-detail { margin-top:6px; }
    .mini-detail summary { cursor:pointer; color:#0b4a8b; font-size:13px; font-weight:700; }
    .row-detail summary { cursor:pointer; color:#0b4a8b; font-size:12px; font-weight:700; }
    .row-detail[open] { margin-top:4px; }
    .stock-drawer-backdrop { position:fixed; inset:0; background:linear-gradient(90deg,rgba(15,23,42,.18),rgba(15,23,42,.05) 52%,rgba(15,23,42,.1)); opacity:0; pointer-events:none; transition:opacity .18s ease; z-index:80; }
    .stock-drawer-backdrop.open { opacity:1; pointer-events:auto; }
    .stock-drawer { position:fixed; top:0; right:0; width:min(520px,100%); height:100dvh; background:#fff; border-left:1px solid var(--line); box-shadow:-18px 0 38px rgba(15,23,42,.2); transform:translateX(104%); transition:transform .2s ease; z-index:81; overflow:auto; }
    .stock-drawer.open { transform:translateX(0); }
    .drawer-head { position:sticky; top:0; background:#fff; border-bottom:1px solid var(--line); padding:14px 16px; display:flex; align-items:flex-start; justify-content:space-between; gap:12px; z-index:1; }
    .drawer-title { font-size:20px; font-weight:900; line-height:1.2; }
    .drawer-body { padding:14px 16px 20px; display:grid; gap:10px; }
    .drawer-close { appearance:none; border:1px solid var(--line); background:#fff; border-radius:6px; min-width:34px; min-height:32px; cursor:pointer; font-weight:900; }
    .drawer-section { border:1px solid var(--line); border-radius:8px; background:#fbfcfe; padding:10px; }
    .drawer-section b { display:block; margin-bottom:4px; }
    .drawer-kv { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .drawer-kv div { border:1px solid #eef1f5; border-radius:6px; padding:8px; background:#fff; min-height:54px; }
    .drawer-kv span { display:block; color:var(--muted); font-size:11px; margin-bottom:3px; }
    @media (max-width: 1180px) {
      .metrics { grid-template-columns: repeat(4, minmax(0,1fr)); }
      .dashboard-layout { grid-template-columns:1fr; }
      .side-stack { position:static; }
      .market-theme-grid { grid-template-columns:1fr; }
      .detail-grid { grid-template-columns:1fr 1fr; }
      .trace-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .decision-card-grid { grid-template-columns:1fr; }
      .action-head { grid-template-columns:1fr; }
      .decision-strip { grid-template-columns:repeat(2,minmax(0,1fr)); }
    }
    @media (max-width: 900px) {
      header { position:static; }
      main, header { padding-left:12px; padding-right:12px; }
      .metrics { grid-template-columns:1fr 1fr; }
      .dashboard-layout, .detail-grid, .status-grid { grid-template-columns:1fr; }
      .trace-grid { grid-template-columns:1fr; }
      .decision-strip { grid-template-columns:1fr 1fr; }
      .decision-prices { grid-template-columns:1fr 1fr; }
      .decision-exit { grid-template-columns:1fr; }
      .decision-card { min-height:auto; }
      .risk-panel #exitRisks { max-height:none; }
      .theme-panel #themes { max-height:none; }
      .toolbar { align-items:stretch; }
      .jump-nav { position:sticky; top:0; z-index:18; padding:6px 0; background:rgba(238,243,248,.94); backdrop-filter:blur(10px); }
      .jump-nav a { flex:1 1 auto; justify-content:center; }
      input, select { width:100%; min-width:0; }
      table, thead, tbody, tr, td { display:block; width:100%; }
      thead { display:none; }
      table { border:0; background:transparent; }
      tr { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin-bottom:10px; padding:10px; }
      td { border:0; padding:5px 0; font-size:13px; }
      td::before { content: attr(data-label); display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
      td:first-child { float:left; width:42px; padding-top:0; }
      td:nth-child(2) { margin-left:52px; min-height:42px; padding-top:0; }
      td:nth-child(3) { clear:both; }
    }
  </style>
</head>
<body class="page-dashboard">
  <header>
    <h1>台股 AI 開盤前監控</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab active" href="index.html">今日監控</a>
      <a class="nav-tab" href="performance.html">訊號成效</a>
      <a class="nav-tab" href="potential.html">潛力雷達</a>
      <a class="nav-tab" href="weekly.html">每週總覽</a>
    </nav>
    <nav class="jump-nav" aria-label="今日監控區段">
      <a href="#today-action">決策</a>
      <a href="#risk-watch">風險</a>
      <a href="#table-tools">篩選</a>
      <a href="#stock-table">股票列表</a>
      <a href="#health-check">資料健康</a>
    </nav>
    <div class="metrics" id="metrics"></div>
    <div class="dashboard-layout">
      <div class="main-stack">
        <section class="action-panel" id="today-action">
          <div class="action-head">
            <div class="action-title">
              <h2>今日操作結論</h2>
              <div class="line">先看燈號與可追/等拉回，再用個股卡片確認進場上限、停損與開盤量能。</div>
              <div id="decisionBrief" class="decision-brief"></div>
            </div>
            <div id="decisionSummary" class="decision-summary-compact"></div>
          </div>
          <div id="actionLists"></div>
        </section>
        <div class="market-theme-grid">
          <section><h2>市場風向</h2><div id="market"></div></section>
          <details class="panel theme-panel" open><summary>新聞題材</summary><div id="themes"></div></details>
        </div>
      </div>
      <div class="side-stack">
        <section class="risk-panel" id="risk-watch"><h2>危險名單</h2><div id="exitRisks"></div></section>
        <section><h2>異常提醒</h2><div id="alerts"></div></section>
      </div>
      <div class="detail-grid">
        <details class="panel">
          <summary>散戶背離</summary>
          <div id="retailDivergence"></div>
        </details>
        <details class="panel">
          <summary>美國政策雷達</summary>
          <div id="usPolicyRadar"></div>
        </details>
        <details class="panel wide-panel" id="health-check">
          <summary>資料鏈檢查</summary>
          <div class="section-note">確認資料源、評分、追蹤、回測、潛力雷達與頁面輸出都有串接。</div>
          <div id="traceability"></div>
        </details>
        <details class="panel wide-panel">
          <summary>系統與資料狀態</summary>
          <div class="status-grid">
            <div><h2>健康狀態</h2><div id="health"></div></div>
            <div><h2>資料品質</h2><div id="dataQuality"></div></div>
          </div>
        </details>
        <details class="panel wide-panel">
          <summary>觀察追蹤</summary>
          <div id="watchReviews"></div>
        </details>
      </div>
    </div>
    <div class="toolbar" id="table-tools">
      <input id="search" placeholder="搜尋股票、題材、訊號..." />
      <select id="grade"><option value="">全部強度</option><option>S+</option><option>S</option><option>A</option><option>B</option><option>C</option><option value="-">資料不足</option></select>
    </div>
    <table id="stock-table" class="table-shell">
      <thead><tr><th>強度</th><th>股票</th><th>分數</th><th>原因標籤</th><th>題材</th><th>四面向</th><th>操作</th><th>進場/停損</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <div class="stock-drawer-backdrop" id="stockDrawerBackdrop" aria-hidden="true"></div>
  <aside class="stock-drawer" id="stockDrawer" aria-hidden="true">
    <div class="drawer-head">
      <div>
        <div class="drawer-title" id="drawerTitle">Stock</div>
        <div class="small" id="drawerSubtitle"></div>
      </div>
      <button class="drawer-close" type="button" data-drawer-close aria-label="Close">×</button>
    </div>
    <div class="drawer-body" id="drawerBody"></div>
  </aside>
  <script>
    const chartScript = document.createElement("script");
    chartScript.src = "https://cdn.jsdelivr.net/npm/chart.js";
    chartScript.defer = true;
    document.head.appendChild(chartScript);
    /* __INLINE_DATA_SENTINEL__ */
    let data = null;
    let themeHistory = null;
    let themeChart = null;
    const cls = g => "grade grade-" + (g === "-" ? "-" : g);
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
    function priceText(value) {
      if (value === null || value === undefined || value === "") return "待確認";
      const n = Number(value);
      return Number.isFinite(n) ? n.toFixed(2).replace(/\.00$/, "") : String(value);
    }
    function detailStockLink(row) {
      return `https://www.wantgoo.com/stock/${encodeURIComponent(String(row.stock_id || ""))}`;
    }
    function findRow(stockId) {
      return (data?.rows || []).find(row => String(row.stock_id) === String(stockId));
    }
    function detailList(items) {
      if (!items || !items.length) return '<div class="small">無資料</div>';
      return items.slice(0, 6).map(item => `<div class="small">- ${esc(item)}</div>`).join("");
    }
    function chainTags(items) {
      if (!items || !items.length) return '<div class="small">產業鏈位置尚未標記</div>';
      return `<div class="chain-tags">${items.slice(0, 5).map(item => `
        <span class="chain-tag" title="${esc(item.chain_role || item.role || "")}">
          ${esc(item.theme_name || item.theme_key)}｜${esc(item.chain_layer_label || "未分類")}｜${esc(item.beneficiary_label || item.tier_label || "")}
        </span>`).join("")}</div>`;
    }
    function chainSummary(row) {
      const summary = row.chain_summary || [];
      if (summary.length) return summary.slice(0, 2).map(item => `<div class="chain-line">${esc(item)}</div>`).join("");
      return "";
    }
    function openStockDrawer(row) {
      if (!row) return;
      const drawer = document.querySelector("#stockDrawer");
      const backdrop = document.querySelector("#stockDrawerBackdrop");
      const exitPlan = row.exit_plan || {};
      document.querySelector("#drawerTitle").innerHTML = `${esc(row.stock_id)} ${esc(row.name)}`;
      document.querySelector("#drawerSubtitle").innerHTML = `${esc(row.score ?? "-")}/100 | ${esc(row.grade || "-")} | ${esc(row.entry_decision || row.action || "-")}`;
      document.querySelector("#drawerBody").innerHTML = `
        <div class="drawer-kv">
          <div><span>進場上限</span><b>${esc(priceText(row.entry_limit_price))}</b></div>
          <div><span>停損參考</span><b class="${row.stop_price != null ? "bad" : ""}">${esc(priceText(row.stop_price))}</b></div>
          <div><span>第一段停利</span><b class="good">${esc(priceText(exitPlan.take_profit_1))}</b></div>
          <div><span>第二段停利</span><b class="good">${esc(priceText(exitPlan.take_profit_2))}</b></div>
          <div><span>AI 複核</span><b>${esc(row.ai_label || "未審核")}${row.ai_review ? ` ${esc(row.ai_review.pick_agreement_count || row.ai_review.agreement_count || 0)}/${esc(row.ai_review.model_count || 0)}` : ""}</b></div>
          <div><span>散戶狀態</span><b>${esc(row.retail_context || "無明顯訊號")}</b></div>
        </div>
        <div class="drawer-section"><b>主要理由</b><div class="small">${esc(row.decision_reason || row.trigger_summary || row.action || "-")}</div></div>
        <div class="drawer-section"><b>出場計劃｜${esc(exitPlan.plan_type || "標準控風險")}</b>
          <div class="small">${esc(exitPlan.trailing_rule || "依停損與移動停利控管。")}</div>
          ${(exitPlan.checklist || []).map(item => `<div class="small">□ ${esc(item)}</div>`).join("")}
        </div>
        <div class="drawer-section"><b>題材</b><div class="themes">${esc((row.theme_tiers || []).join(" / ") || (row.themes || []).join(" / ") || "-")}</div>${chainTags(row.theme_chain || [])}</div>
        <div class="drawer-section"><b>原因標籤</b><div class="tags">${renderTags(row.trigger_tags || [])}</div></div>
        <div class="drawer-section"><b>開盤檢查</b>${detailList(row.entry_checklist || [])}</div>
        <div class="drawer-section"><b>技術 / 籌碼 / 基本 / 風險</b>
          <div class="small">技術：${esc(row.technical || "-")}</div>
          <div class="small">籌碼：${esc(row.chip || "-")}</div>
          <div class="small">基本：${esc(row.fundamental || "-")}</div>
          <div class="small">風險：${esc(row.risk || "-")}</div>
        </div>
        <div><a class="nav-tab" href="${esc(detailStockLink(row))}" target="_blank" rel="noopener noreferrer">開啟玩股網</a></div>
      `;
      drawer.classList.add("open");
      backdrop.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      backdrop.setAttribute("aria-hidden", "false");
    }
    function closeStockDrawer() {
      const drawer = document.querySelector("#stockDrawer");
      const backdrop = document.querySelector("#stockDrawerBackdrop");
      drawer.classList.remove("open");
      backdrop.classList.remove("open");
      drawer.setAttribute("aria-hidden", "true");
      backdrop.setAttribute("aria-hidden", "true");
    }
    document.addEventListener("click", event => {
      const detailButton = event.target.closest("[data-detail-stock]");
      if (detailButton) {
        event.preventDefault();
        openStockDrawer(findRow(detailButton.dataset.detailStock));
        return;
      }
      const stockRow = event.target.closest("tr[data-stock-id]");
      if (stockRow && !event.target.closest("a, button, summary, details, input, select")) {
        openStockDrawer(findRow(stockRow.dataset.stockId));
        return;
      }
      if (event.target.closest("[data-drawer-close]") || event.target.id === "stockDrawerBackdrop") {
        closeStockDrawer();
      }
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeStockDrawer();
    });
    const zh = (map, value, fallback = "") => map[value] || value || fallback;
    const QUALITY_TEXT = { high: "高", medium: "中", low: "偏低" };
    const RECOVERY_TEXT = { retry_ready: "可自動補抓", manual_check: "需人工檢查", clean: "正常" };
    const EVENT_TYPE_TEXT = { fallback: "備援資料", empty: "空資料", error: "抓取失敗", quota: "限流" };
    const DATASET_TEXT = { STOCK_DAY: "個股月成交", stock_prices: "股價序列" };
    const REASON_TEXT = { twse_month_missing: "TWSE 月資料缺口", html: "TWSE 回傳網頁非資料", fetch_failed: "抓取失敗" };
    const RETRY_STATUS_TEXT = { pending: "待補抓", recovered: "已補回", failed: "補抓失敗" };
    const POLICY_EVENT_TEXT = {
      "Trump tariff / China tariff": "川普/中國關稅",
      "AI chip export control": "AI晶片出口管制",
      "House / Senate China bill": "美國國會對中法案",
      "Defense bill / NDAA": "國防授權法案/NDAA",
      "SpaceX / Starlink": "SpaceX/Starlink",
      "Data center power": "資料中心電力",
      "AI capex / hyperscaler": "AI資本支出/雲端大廠",
    };
    const POLICY_LEVEL_TEXT = {
      high: "高敏感", medium: "中敏感", low: "低敏感",
      confirmed: "已確認", signal: "訊號", watch: "觀察",
      bullish: "利多", risk: "風險", mixed: "多空交錯",
    };
    function themeName(key) {
      return data?.themes?.names?.[key] || key || "-";
    }
    const TAG_CLASS = {
      "題材": "tag-theme", "法人": "tag-chip", "外資": "tag-chip", "投信": "tag-chip",
      "突破": "tag-tech",  "趨勢": "tag-tech",  "技術": "tag-tech",
      "營收": "tag-fund",
      "美股": "tag-over",  "海外": "tag-over",
      "放量長紅": "tag-pattern", "陽包陰": "tag-pattern", "錘子線": "tag-pattern",
      "突破整理": "tag-pattern",
      "放量不漲": "tag-risk", "高位": "tag-risk", "陰包陽": "tag-risk",
    };
    function tagClass(tag) {
      for (const [kw, cls] of Object.entries(TAG_CLASS)) {
        if (tag.includes(kw)) return "tag " + cls;
      }
      return "tag tag-default";
    }
    function renderTags(tags) {
      if (!tags || !tags.length) return '<span class="tag tag-default">綜合訊號</span>';
      return tags.map(t => `<span class="${tagClass(t)}">${esc(t)}</span>`).join("");
    }
    function render() {
      if (!document.querySelector("#quickFilter")) {
        document.querySelector("#grade").insertAdjacentHTML("afterend", `<select id="quickFilter">
          <option value="">全部訊號</option>
          <option value="strong">S+/S 強度</option>
          <option value="chase">可追蹤/觀察</option>
          <option value="pullback">等拉回</option>
          <option value="risk">風險警示</option>
          <option value="retail_clean">散戶轉乾淨</option>
          <option value="retail_hot">散戶過熱</option>
          <option value="ai">AI 共識</option>
          <option value="new">今日新增</option>
          <option value="top_theme">主題焦點</option>
          <option value="pattern_bull">K線偏多</option>
          <option value="pattern_risk">K線風險</option>
        </select>`);
        document.querySelector("#quickFilter").addEventListener("change", render);
      }
      if (!document.querySelector("#usPolicyRadar")) {
        document.querySelector("#dataQuality").closest("section").insertAdjacentHTML("afterend", `<section><h2>美國政策雷達</h2><div id="usPolicyRadar"></div></section>`);
      }
      const q = document.querySelector("#search").value.trim().toLowerCase();
      const g = document.querySelector("#grade").value;
      const reportDate = data.generated_date || (data.health && data.health.generated_date) || data.as_of;
      const dataDate = data.data_date || data.as_of;
      document.querySelector("#subtitle").textContent = `早報日期 ${reportDate}｜資料日 ${dataDate}｜僅供研究追蹤，不是投資建議`;
      const actionLists = data.action_lists || {};
      const actionSummary = actionLists.summary || {};
      document.querySelector("#metrics").innerHTML = [
        ["有效標的", data.summary.valid, ""],
        ["S+/S 強度", actionSummary.strong ?? ((data.summary.s_plus_grade || 0) + (data.summary.s_grade || 0)), "is-good"],
        ["可追", actionSummary.chase ?? 0, "is-good"],
        ["等拉回", actionSummary.pullback ?? 0, "is-warn"],
        ["風險", actionSummary.risk ?? 0, "is-bad"]
      ].map(([k,v,c]) => `<div class="metric ${c}"><b>${v}</b><span>${k}</span></div>`).join("");
      const decision = data.decision_summary || {};
      function marketTemperature() {
        const retail = data.retail_divergence || {};
        const retailSummary = retail.summary || {};
        const risks = Number(actionSummary.risk || 0);
        const chase = Number(actionSummary.chase || 0);
        const strong = Number(actionSummary.strong || 0);
        const hotRetail = Number(retailSummary.overheated || 0) + Number(retailSummary.watch_overheated || 0);
        const cleanRetail = Number(retailSummary.clean || 0) + Number(retailSummary.watch_clean || 0);
        let heat = 0;
        const reasons = [];
        if (strong >= 12) { heat += 1; reasons.push(`強勢訊號 ${strong} 檔`); }
        if (chase >= 5) { heat += 1; reasons.push(`可追 ${chase} 檔`); }
        if (risks >= 5) { heat += 2; reasons.push(`風險名單 ${risks} 檔`); }
        if (hotRetail > cleanRetail && hotRetail > 0) { heat += 1; reasons.push(`散戶過熱 ${hotRetail} 檔`); }
        if (data.market?.warning) { heat += 1; reasons.push(data.market.warning); }
        if (String(data.overseas?.label || "").includes("偏空")) { heat += 1; reasons.push("海外偏空"); }
        if (cleanRetail > hotRetail && cleanRetail > 0) { heat -= 1; reasons.push(`籌碼轉乾淨 ${cleanRetail} 檔`); }
        if (heat >= 4) return { label: "過熱控風險", cls: "bad", note: reasons.slice(0, 3).join("｜") || "風險訊號偏多" };
        if (heat >= 2) return { label: "偏熱精選", cls: "warn", note: reasons.slice(0, 3).join("｜") || "訊號偏熱" };
        if (heat <= -1) return { label: "偏冷觀察", cls: "warn", note: reasons.slice(0, 3).join("｜") || "等待轉強" };
        return { label: "正常篩選", cls: "good", note: reasons.slice(0, 3).join("｜") || "無明顯過熱訊號" };
      }
      const postureText = {
        active_watch: "積極觀察",
        selective_watch: "精選觀察",
        risk_control: "風險控管",
      }[decision.posture] || "精選觀察";
      const decisionTopTheme = themeName(decision.top_theme);
      const temp = marketTemperature();
      const topChase = (actionLists.chase || []).slice(0, 3).map(row => `${row.stock_id} ${row.name}`).join("、") || "今日暫無";
      const topRisk = (actionLists.risk || []).slice(0, 2).map(row => `${row.stock_id} ${row.name}`).join("、") || "目前無紅黃警戒";
      document.querySelector("#decisionSummary").innerHTML = `
        <div class="temperature-card ${temp.cls}">
          <b>${esc(temp.label)}</b>
          <div class="small">${esc(temp.note)}</div>
        </div>
        <div class="decision-strip">
          <div class="decision-pill good"><b>${esc(actionSummary.chase ?? 0)}</b><span>可追</span></div>
          <div class="decision-pill warn"><b>${esc(actionSummary.pullback ?? 0)}</b><span>等拉回</span></div>
          <div class="decision-pill bad"><b>${esc(actionSummary.risk ?? 0)}</b><span>風險</span></div>
          <div class="decision-pill"><b>${esc(actionSummary.observe ?? 0)}</b><span>只觀察</span></div>
          <div class="decision-pill"><b>${esc(actionSummary.ai_agree ?? 0)}</b><span>AI 同意</span></div>
          <div class="decision-pill"><b>${esc(zh(QUALITY_TEXT, decision.data_quality, "-"))}</b><span>資料品質</span></div>
        </div>
        <div class="line"><b>${esc(postureText)}</b>｜主題焦點：${esc(decisionTopTheme)}</div>`;
      document.querySelector("#decisionBrief").innerHTML = `
        <div class="brief-row"><b>先看</b><span>${esc(temp.label)}｜可追 ${esc(actionSummary.chase ?? 0)} 檔、等拉回 ${esc(actionSummary.pullback ?? 0)} 檔</span></div>
        <div class="brief-row"><b>優先名單</b><span>${esc(topChase)}</span></div>
        <div class="brief-row"><b>避開風險</b><span>${esc(topRisk)}</span></div>`;
      document.querySelector("#market").innerHTML = `
        <div class="line">台股：${esc(data.market.summary)}</div>
        <div class="line">海外：${esc(data.overseas.label)}｜${esc(data.overseas.summary)}</div>
        ${(data.overseas.sector_impacts || []).slice(0,2).map(x => `<div class="line">映射：${esc(x.symbol)} ${Number(x.change_pct).toFixed(2)}% → ${esc(x.sector)}｜${esc(x.stocks)}</div>`).join("")}
        <div class="line"><span class="${sourceClass(data.source_status.label)}"></span>資料源：${esc(data.source_status.label)}｜API ${data.source_status.api || 0}｜快取 ${data.source_status.cache || 0}｜限流 ${data.source_status.quota || 0}</div>
        ${data.market.warning ? `<div class="line bad">提醒：${esc(data.market.warning)}</div>` : ""}`;
      const health = data.health || {};
      const healthCls = health.label === "正常" ? "good" : (health.label === "部分延遲" ? "warn" : "bad");
      const delay = health.schedule_delay_minutes;
      const delayText = delay === null || delay === undefined ? "未記錄" : `${Number(delay).toFixed(1)} 分`;
      const targetText = health.scheduled_target_taipei ? health.scheduled_target_taipei.replace("T", " ") : "未記錄";
      const scheduleLabel = health.schedule_label || "未記錄";
      const dataSourceLabel = health.data_source_label || health.provider_label || "未知";
      const newsLabel = health.news_label || (health.news_failed ? "部分失敗" : "正常");
      const delivery = health.telegram_delivery || data.delivery_status || {};
      const deliveryText = delivery.delivered
        ? `已推播 ${esc(String(delivery.sent_at || "").replace("T", " "))}${delivery.run_id ? `｜Run ${esc(delivery.run_id)}` : ""}`
        : `尚未推播｜早報日期 ${esc(delivery.delivery_date || health.report_date || reportDate)}`;
      const deliveryCls = delivery.delivered ? "good" : "warn";
      document.querySelector("#health").innerHTML = `
        <div class="line ${healthCls}"><span class="${sourceClass(health.label === "正常" ? "正常" : health.label === "部分延遲" ? "部分限流" : "錯誤")}"></span>系統：${esc(health.label || "未知")}</div>
        <div class="line ${deliveryCls}">Telegram：${deliveryText}</div>
        <div class="line">本次產生：${esc((health.generated_at || "").replace("T", " "))}</div>
        <div class="line">資料日期：${esc(health.data_date || data.as_of)}｜網站 ${esc(health.website_schedule || "07:58")}｜Telegram ${esc(health.telegram_schedule || "08:18")}</div>
        <div class="line">排程：${esc(scheduleLabel)}｜${esc(health.scheduler || "local")}｜${esc(health.scheduled_task || "-")}｜預定 ${esc(targetText)}｜延遲 ${esc(delayText)}</div>
        <div class="line">資料源：${esc(dataSourceLabel)}｜原始 ${esc(health.provider_label || "未知")}</div>
        <div class="line">新聞：${esc(newsLabel)}｜成功 ${health.news_sources || 0}｜失敗 ${health.news_failed || 0}</div>
        <div class="line">執行環境：${esc(health.github_event || "local")}${health.github_run_id ? `｜Run ${esc(health.github_run_id)}` : ""}</div>`;
      function priceText(value) {
        if (value === null || value === undefined || value === "") return "待確認";
        const n = Number(value);
        return Number.isFinite(n) ? n.toFixed(2).replace(/\.00$/, "") : String(value);
      }
      function decisionCard(row, mode) {
        const badgeText = mode === "pullback" ? "等拉回" : mode === "avoid" ? "避開" : "可追";
        const stockLink = `<a class="stock-link" href="https://www.wantgoo.com/stock/${esc(row.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(row.stock_id)} ${esc(row.name)}</a>`;
        const checklist = (row.entry_checklist || []).slice(0, 2).join(" / ");
        const qualityNotes = (row.selection_quality_notes || []).slice(0, 1).join(" / ");
        const reason = qualityNotes || row.reason || checklist || row.action || "綜合訊號";
        const aiReview = row.ai_review || {};
        const aiLabel = row.ai_label || "未複核";
        const aiText = aiReview.stock_id
          ? `｜${esc(aiLabel)} ${esc(aiReview.pick_agreement_count || aiReview.agreement_count || 0)}/${esc(aiReview.model_count || 0)}`
          : "｜AI 未複核";
        const light = row.decision_light || "gray";
        const lightLabel = row.decision_light_label || "灰燈追蹤";
        const lightReason = row.decision_light_reason || row.action_context_reason || "";
        const aiReason = row.ai_reason || "";
        const retailText = row.retail_context || "散戶：無明顯背離";
        const retailReason = row.retail_context_reason || "";
        const stabilityLabel = row.stability_label || "新進名單";
        const stabilityReason = row.stability_reason || "近期尚無連續推薦紀錄。";
        const exitPlan = row.exit_plan || {};
        return `<article class="decision-card ${mode}">
          <div class="decision-card-head">
            <div>
              <div class="decision-card-title">${stockLink}</div>
              <div class="small">${esc(row.score ?? "-")}/100｜${esc(row.grade || "-")}${row.entry_decision ? `｜${esc(row.entry_decision)}` : ""}｜${esc(stabilityLabel)}${aiText}</div>
              <div class="decision-light ${esc(light)}"><span class="decision-dot"></span>${esc(lightLabel)}<span class="small">｜${esc(lightReason)}</span></div>
            </div>
            <div class="decision-card-actions">
              <button class="detail-button" type="button" data-detail-stock="${esc(row.stock_id)}">詳情</button>
              <span class="decision-badge ${mode}">${badgeText}</span>
            </div>
          </div>
          <div class="decision-prices">
            <div class="decision-price"><span>進場上限</span><b>${esc(priceText(row.entry_limit_price))}</b></div>
            <div class="decision-price"><span>停損參考</span><b class="${row.stop_price != null ? "bad" : ""}">${esc(priceText(row.stop_price))}</b></div>
          </div>
          <div class="decision-exit">
            <div><span>硬停損</span><b class="${row.stop_price != null ? "bad" : ""}">${esc(priceText(row.stop_price))}</b></div>
            <div><span>第一段</span><b class="good">${esc(priceText(exitPlan.take_profit_1))}</b></div>
            <div><span>第二段</span><b class="good">${esc(priceText(exitPlan.take_profit_2))}</b></div>
          </div>
          <div class="decision-reason">${esc(reason)}</div>
          <details class="mini-detail">
            <summary>個股開盤檢查表</summary>
            ${(row.entry_checklist || []).map(item => `<div class="line small">□ ${esc(item)}</div>`).join("") || '<div class="line small">尚無足夠資料設定條件</div>'}
          </details>
          <details class="mini-detail">
            <summary>持倉出場計劃｜${esc(exitPlan.plan_type || "標準控風險")}</summary>
            <div class="line small">${esc(exitPlan.trailing_rule || "依停損與移動停利控管。")}</div>
            ${(exitPlan.checklist || []).map(item => `<div class="line small">□ ${esc(item)}</div>`).join("")}
          </details>
          <div class="decision-note-grid">
            <div class="decision-note"><b>AI</b><br>${esc(aiReason || aiLabel)}</div>
            <div class="decision-note"><b>穩定性</b><br>${esc(stabilityReason)}</div>
            <div class="decision-note"><b>散戶</b><br>${esc(retailText)}${retailReason ? `｜${esc(retailReason)}` : ""}</div>
          </div>
        </article>`;
      }
      const chaseCards = (actionLists.chase || []).slice(0, 4).map(row => decisionCard(row, "chase")).join("");
      const pullbackCards = (actionLists.pullback || []).slice(0, 2).map(row => decisionCard(row, "pullback")).join("");
      document.querySelector("#actionLists").innerHTML = `
        <details class="mini-detail open-check-guide">
          <summary>開盤時怎麼確認？</summary>
          <div class="line"><b>1. 等到 09:05</b>：先看前 5 分鐘，不在 09:00 第一筆追價。</div>
          <div class="line"><b>2. 價格不超限</b>：現價不得高於卡片的「進場上限」；超過就放棄追價。</div>
          <div class="line"><b>3. 價穩且有量</b>：價格站穩昨高或個股檢查條件，前 5 分鐘量達檢查表門檻。</div>
          <div class="line"><b>4. 風控先寫好</b>：跌破「停損參考」不進場；進場後跌破則依紀律退出。</div>
        </details>
        <div class="line good"><b>可追</b>：${esc(actionLists.summary?.chase ?? 0)} 檔</div>
        <div class="decision-card-grid">${chaseCards || '<div class="line">今日暫無高分可追清單</div>'}</div>
        <div class="line warn"><b>等拉回</b>：${esc(actionLists.summary?.pullback ?? 0)} 檔</div>
        <div class="decision-card-grid">${pullbackCards || '<div class="line">暫無等拉回清單</div>'}</div>`;
      function compactRetail(row) {
        const pct = row.holder_change_pct == null ? "—" : `${Number(row.holder_change_pct).toFixed(1)}%`;
        const px = row.price_change_pct == null ? "—" : `${Number(row.price_change_pct).toFixed(1)}%`;
        const stockLink = `<a class="stock-link" href="https://www.wantgoo.com/stock/${esc(row.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(row.stock_id)} ${esc(row.name)}</a>`;
        return `<div class="line"><b>${stockLink}</b>｜散戶 ${esc(pct)}｜股價 ${esc(px)}<div class="small">${esc(row.reason || row.signal || "")}</div></div>`;
      }
      const retail = data.retail_divergence || {};
      const retailSummary = retail.summary || {};
      document.querySelector("#retailDivergence").innerHTML = `
        <div class="line">週資料觀察，不直接等於買賣訊號；用來輔助判斷籌碼是否轉乾淨或散戶過熱。</div>
        <div class="line good"><b>籌碼轉乾淨</b>：${esc(retailSummary.clean ?? 0)} 檔</div>
        ${(retail.clean || []).slice(0,3).map(compactRetail).join("") || '<div class="line">尚未累積籌碼轉乾淨名單</div>'}
        <div class="line good"><b>觀察轉乾淨</b>：${esc(retailSummary.watch_clean ?? 0)} 檔</div>
        ${(retail.watch_clean || []).slice(0,2).map(compactRetail).join("") || '<div class="line">尚未累積觀察轉乾淨名單</div>'}
        <div class="line warn"><b>散戶過熱</b>：${esc(retailSummary.overheated ?? 0)} 檔</div>
        ${(retail.overheated || []).slice(0,3).map(compactRetail).join("") || '<div class="line">尚未累積散戶過熱名單</div>'}
        <div class="line warn"><b>觀察過熱</b>：${esc(retailSummary.watch_overheated ?? 0)} 檔</div>
        ${(retail.watch_overheated || []).slice(0,2).map(compactRetail).join("") || '<div class="line">尚未累積觀察過熱名單</div>'}`;
      const quality = data.data_quality || {};
      const bundleCoverage = data.source_status?.bundle_coverage || {};
      const coverageRows = bundleCoverage.datasets || {};
      const marketSnapshots = data.source_status?.market_snapshots || {};
      const universe = data.source_status?.universe || {};
      const qualityCls = (quality.label === "high" || quality.label === "高") ? "good" : (quality.label === "medium" || quality.label === "中") ? "warn" : "bad";
      const qualityHuman = quality.label === "high" ? "可用" : quality.label === "medium" ? "注意" : "偏低";
      const qualityNote = quality.label === "high"
        ? "主要資料已可用；若有補回紀錄，代表備援已處理。"
        : quality.label === "medium"
          ? "部分資料需留意；看個股前先確認進場條件。"
          : "資料品質偏低；今日訊號只適合觀察。";
      const retry = data.data_retry || {};
      const retryCounts = retry.status_counts || {};
      const retryLines = (retry.items || []).slice(0,3).map(x =>
        `<div class="line small">${esc(zh(RETRY_STATUS_TEXT, x.status))}｜${esc(zh(DATASET_TEXT, x.dataset))}｜${esc(x.data_id)}｜${esc(x.period || "-")}｜${esc(x.attempts || 0)} 次${x.last_error ? `｜${esc(x.last_error)}` : ""}</div>`
      ).join("");
      document.querySelector("#dataQuality").innerHTML = `
        <div class="line ${qualityCls}"><b>${esc(qualityHuman)}</b>｜${esc(quality.score ?? "—")}/100</div>
        <div class="line">${esc(qualityNote)}</div>
        <div class="line">官方快照：通過 ${esc(quality.official_valid || 0)}｜未通過 ${esc(quality.official_invalid || 0)}</div>
        ${Object.entries(quality.official_snapshots || {}).slice(0,4).map(([key, row]) => `<div class="line small">${esc(key)}｜${row.valid ? "已驗證" : "未通過"}${row.date ? `｜${esc(row.date)}` : ""}｜${esc(row.rows || 0)} 筆</div>`).join("")}
        ${(quality.warnings || []).length ? quality.warnings.slice(0,2).map(w => `<div class="line warn">- ${esc(w)}</div>`).join("") : '<div class="line">目前無重大資料品質警示</div>'}
        <details class="mini-detail">
          <summary>資料細節</summary>
          <div class="line">資料源 ${esc(quality.source_score ?? "—")}/100｜覆蓋率 ${esc(quality.coverage ?? "—")}%</div>
          <div class="line"><b>分層股票池</b>：${esc(universe.mode || "未啟用")}｜本次 ${esc(universe.selected_count || data.summary?.scanned || 0)} 檔｜約 ${esc(universe.coverage_pct ?? "—")}% / ${esc(universe.target_total_listed || 1056)} 家</div>
          <div class="line small">核心 ${esc(universe.core_count || 0)}｜當日題材 ${esc(universe.active_theme_count || 0)}｜題材輪動 ${esc(universe.theme_rotation_count || 0)}｜高成交候選 ${esc(universe.market_liquidity_count || 0)}｜官方候選 ${esc(universe.market_universe_available || 0)}</div>
          <div class="line"><b>逐檔資料稽核</b>：${bundleCoverage.all_critical_complete ? "核心資料完整" : "仍有缺口"}｜掃描 ${esc(bundleCoverage.stocks || 0)} 檔</div>
          ${Object.entries(coverageRows).map(([key, row]) => `<div class="line small">${esc(key)}｜${esc(row.coverage_pct ?? 0)}%｜缺 ${esc((row.missing || []).length)}${(row.missing || []).length ? `｜${esc((row.missing || []).slice(0,6).join(","))}` : ""}</div>`).join("")}
          ${Object.entries(marketSnapshots).map(([key, row]) => `<div class="line small">${esc(key)}｜${row.valid ? "已驗證" : "部分備援"}${row.date ? `｜${esc(row.date)}` : ""}｜${esc(row.source || "")}</div>`).join("")}
          ${(quality.details || []).length ? quality.details.slice(0,4).map(x => `<div class="line small">${esc(zh(EVENT_TYPE_TEXT, x.type))}｜${esc(zh(DATASET_TEXT, x.dataset))}｜${esc(x.data_id)}｜${esc(zh(REASON_TEXT, x.reason || x.period || "-"))}</div>`).join("") : '<div class="line small">目前無細節警示</div>'}
          <div class="line"><b>補抓佇列</b>：待補 ${esc(retry.pending || retryCounts.pending || 0)}｜已補 ${esc(retry.recovered || retryCounts.recovered || 0)}｜失敗 ${esc(retry.failed || retryCounts.failed || 0)}</div>
          ${retryLines || '<div class="line small">目前無待補抓資料</div>'}
        </details>`;
      const recovery = quality.recovery_status || {};
      if (recovery.label && recovery.label !== "clean") {
        document.querySelector("#dataQuality").insertAdjacentHTML("beforeend",
          `<div class="line warn">補抓狀態：${esc(zh(RECOVERY_TEXT, recovery.label))}｜可補抓 ${esc(recovery.retryable || 0)}｜暫停 ${esc(recovery.blocked || 0)}</div>`);
      }
      const traceability = data.traceability || {};
      const traceSteps = traceability.steps || [];
      const traceClass = status => status === "ok" ? "ok" : status === "bad" ? "bad" : "warn";
      const traceHistory = (traceability.history || []).slice(0, 10);
      const traceHistoryHtml = traceHistory.length
        ? `<div class="trace-history">${traceHistory.map(item => `
            <span class="trace-day ${traceClass(item.overall_status)}">${esc(item.run_date)} ${esc(item.overall_status || "-")}</span>
          `).join("")}</div>`
        : "";
      document.querySelector("#traceability").innerHTML = traceSteps.length
        ? `<div class="trace-grid">${traceSteps.map(step => `
            <div class="trace-card ${traceClass(step.status)}">
              <b>${esc(step.label)}</b>
              <div class="trace-value">${esc(step.value || "-")}</div>
              <div class="trace-note">${esc(step.note || "")}</div>
            </div>`).join("")}</div>${traceHistoryHtml}`
        : `<div class="line warn">尚未產生資料鏈檢查結果；請確認本次 run 是否完成到回測輸出階段。</div>`;
      const usEvents = data.themes?.policy?.us_events || [];
      document.querySelector("#usPolicyRadar").innerHTML = usEvents.length
        ? usEvents.slice(0,4).map(e => `<div class="line"><b>${esc(e.event_zh || zh(POLICY_EVENT_TEXT, e.event))}</b>｜${esc(zh(POLICY_LEVEL_TEXT, e.sensitivity))}｜${esc(zh(POLICY_LEVEL_TEXT, e.confidence))}｜${esc(zh(POLICY_LEVEL_TEXT, e.direction))}<div class="small">${esc((e.themes || []).map(themeName).join(" / "))}</div><div class="small">${esc(e.headline_zh || e.headline)}</div></div>`).join("")
        : `<div class="line">最新新聞未偵測到高敏感美國政策訊號。</div>`;
      function sparkBar(history) {
        const bars = "▁▂▃▄▅▆▇█";
        if (!history || !history.length) return "—";
        const max = Math.max(...history, 1);
        return [...history].slice(0, 7).reverse().map(v =>
          v === 0 ? "·" : bars[Math.min(7, Math.round((v / max) * 7))]
        ).join("");
      }
      function trendStyle(trend) {
        if (!trend) return "";
        if (trend.indexOf("急升") >= 0) return "color:#b42318;font-weight:700";
        if (trend.indexOf("升溫") >= 0) return "color:#0f7b4f;font-weight:600";
        if (trend.indexOf("降溫") >= 0) return "color:var(--muted)";
        if (trend.indexOf("消退") >= 0) return "color:#98a2b3";
        return "";
      }
      const momentum = data.themes.momentum || {};
      const allThemeEntries = Object.entries(data.themes.scores || {})
        .filter(([key, score]) => score > 0 || (momentum[key] && momentum[key].avg_3d > 0))
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6);
      const themeTableBody = allThemeEntries.map(([key, score]) => {
        const mom = momentum[key] || {};
        const trend = mom.trend || "-";
        const avg3d = mom.avg_3d != null ? Number(mom.avg_3d).toFixed(1) : "-";
        const spark = sparkBar(mom.history);
        const catalyst = (data.themes.catalyst_confidence || {})[key] || {};
        const catalystColor = catalyst.grade === "A" ? "var(--good)" : catalyst.grade === "B" ? "#175cd3" : catalyst.grade === "C" ? "var(--warn)" : "var(--muted)";
        return `<tr style="font-size:12px">` +
          `<td style="padding:3px 5px;color:#175cd3">${esc(data.themes.names[key] || key)}</td>` +
          `<td style="padding:3px 5px;text-align:center">${score}</td>` +
          `<td style="padding:3px 5px;text-align:center;color:var(--muted)">${avg3d}</td>` +
          `<td style="padding:3px 5px;${trendStyle(trend)}">${esc(trend)}</td>` +
          `<td style="padding:3px 5px;text-align:center;color:${catalystColor};font-weight:800">${esc(catalyst.grade || "-")}</td>` +
          `<td style="padding:3px 5px;letter-spacing:1px;font-family:monospace;color:#475467">${spark}</td>` +
          `</tr>`;
      }).join("");
      const themeHdr = `<thead><tr style="font-size:11px;color:var(--muted)">` +
        `<th style="padding:2px 5px;text-align:left;font-weight:600">題材</th>` +
        `<th style="padding:2px 5px;font-weight:600">今日</th>` +
        `<th style="padding:2px 5px;font-weight:600">3日均</th>` +
        `<th style="padding:2px 5px;font-weight:600">趨勢</th>` +
        `<th style="padding:2px 5px;font-weight:600">可信</th>` +
        `<th style="padding:2px 5px;font-weight:600">近7日▶</th>` +
        `</tr></thead>`;
      const themeTableHtml = themeTableBody
        ? `<div class="theme-table-wrap"><table style="width:100%;border-collapse:collapse">${themeHdr}<tbody>${themeTableBody}</tbody></table></div>`
        : "";
      const matchedHeadlines = data.themes.matched_headlines || {};
      const themeQuality = data.themes.quality || {};
      const catalystConfidence = data.themes.catalyst_confidence || {};
      const themeReasons = allThemeEntries
        .map(([key]) => {
          const hits = matchedHeadlines[key] || [];
          if (!hits.length) return "";
          const quality = themeQuality[key] ? `｜${esc(themeQuality[key])}` : "";
          const catalyst = catalystConfidence[key];
          const catalystText = catalyst ? `｜可信度 ${esc(catalyst.grade)} ${esc(catalyst.label)}：${esc(catalyst.reason)}` : "";
          return `<div class="line theme-reason"><b>${esc(data.themes.names[key] || key)}</b>${quality}${catalystText}：${esc(hits[0])}</div>`;
        })
        .filter(Boolean)
        .slice(0, 4)
        .join("");
      const discoveries = (data.themes.discovery || []).slice(0, 5);
      const discoveryHtml = discoveries.length
        ? `<details class="mini-detail">
            <summary>新題材雷達（先觀察，不加分）</summary>
            <div class="discovery-list">
              ${discoveries.map(item => `
                <div class="discovery-item">
                  <div class="discovery-title">${esc(item.keyword)}｜${esc(item.mentions || 0)} 則｜分數 ${esc(item.score || 0)}</div>
                  <div class="discovery-meta">${esc((item.stock_hits || []).slice(0,4).join("、") || "尚無明確股票命中")}</div>
                  <div class="discovery-meta">${esc((item.headlines || [])[0] || "")}</div>
                </div>`).join("")}
            </div>
          </details>`
        : "";
      const chainMap = data.themes.chain_map || {};
      const chainHeatHtml = allThemeEntries.length
        ? `<details class="mini-detail" open>
            <summary>產業鏈熱區</summary>
            <div class="chain-heat-list">
              ${allThemeEntries.slice(0, 5).map(([key]) => {
                const item = chainMap[key] || {};
                return `<div class="chain-heat-item">
                  <b>${esc(data.themes.names[key] || key)}</b>
                  <span>${esc(item.stage || "階段待標記")}</span>
                  <div class="small">${esc(item.lead_lag || item.stage_reason || "尚未建立上下游節奏說明")}</div>
                </div>`;
              }).join("")}
            </div>
          </details>`
        : "";
      document.querySelector("#themes").innerHTML = `
        <div class="line">熱門：${esc(data.themes.summary)}</div>
        <div class="line">政策：${esc(data.themes.policy?.summary || "未偵測到明顯政策訊號")}</div>
        <div class="chart-wrap"><canvas id="themeHistoryChart" aria-label="題材熱度歷史圖"></canvas></div>
        ${themeTableHtml}
        ${chainHeatHtml}
        ${discoveryHtml}
        <details class="mini-detail">
          <summary>新聞來源摘要</summary>
          ${themeReasons}
          ${data.themes.headlines.slice(0,2).map(h => `<div class="line theme-headline">- ${esc(h)}</div>`).join("")}
        </details>`;
      const ai = data.ai_council || {};
      const aiStatus = ai.status || {};
      const aiRequiredModels = ai.min_model_count || ai.min_agree_count || 5;
      const aiRequiredVotes = ai.min_agree_count || 5;
      const aiAvailability = aiStatus.requested_models
        ? `<div class="line">AI 可用率：${esc(aiStatus.successful_models || 0)}/${esc(aiStatus.requested_models || 0)} 模型成功${(aiStatus.failed_models || []).length ? `｜限流/失敗 ${esc((aiStatus.failed_models || []).length)}` : ""}${(aiStatus.timed_out_models || []).length ? `｜逾時 ${esc((aiStatus.timed_out_models || []).length)}` : ""}</div>`
        : "";
      const aiFailureDetail = [...(aiStatus.failed_models || []), ...(aiStatus.timed_out_models || [])]
        .slice(0, 4)
        .map(name => String(name).split("/").pop())
        .join("、");
      const aiHealthLine = aiStatus.health
        ? `<div class="line ${aiStatus.health.score >= 80 ? "good" : aiStatus.health.score >= 50 ? "warn" : "bad"}">模型健康度：${esc(aiStatus.health.label || "-")}｜${esc(aiStatus.health.score ?? 0)}/100${aiFailureDetail ? `｜異常：${esc(aiFailureDetail)}` : ""}</div>`
        : "";
      const aiReviewNote = ai.enabled
        ? `AI 複核：同意 ${esc(actionSummary.ai_agree ?? 0)}｜保留 ${esc(actionSummary.ai_hold ?? 0)}｜不建議 ${esc(actionSummary.ai_avoid ?? 0)}｜已複核 ${esc(actionSummary.ai_reviewed ?? 0)}`
        : "AI 複核未啟用";
      document.querySelector("#decisionSummary").insertAdjacentHTML("beforeend", `
        <div class="line">${aiReviewNote}</div>
        ${aiHealthLine || ""}
        ${aiAvailability || ""}
        ${ai.using_fallback_picks ? `<div class="line warn">AI 未達 ${esc(aiRequiredModels)} 模型參與 / ${esc(aiRequiredVotes)} 票強共識，僅作複核參考</div>` : ""}
      `);
      renderThemeHistoryChart();
      document.querySelector("#alerts").innerHTML = (data.alerts || []).length
        ? data.alerts.map(a => `<div class="line bad">- ${esc(a)}</div>`).join("")
        : `<div class="line">目前無重大異常</div>`;
      document.querySelector("#exitRisks").innerHTML = (data.exit_risks || []).length
        ? data.exit_risks.slice(0,5).map(x => {
            const cls = x.level === "紅色警戒" ? "bad" : "warn";
            return `<div class="line ${cls}">${esc(x.stock_id)} ${esc(x.name)}｜${esc(x.level)}｜危險分 ${esc(x.risk_score || 0)}｜${esc((x.reasons || []).slice(0,2).join("、"))}<div class="small">${esc(x.action || "")}</div></div>`;
          }).join("")
        : `<div class="line">目前無紅黃警戒</div>`;
      document.querySelector("#watchReviews").innerHTML = (data.watch_reviews || []).length
        ? data.watch_reviews.slice(0,4).map(w => `<div class="line">${esc(w.stock_id)} ${esc(w.name)}：${w.change_pct >= 0 ? "+" : ""}${Number(w.change_pct).toFixed(1)}%｜現分 ${w.current_score}/100</div>`).join("")
        : `<div class="line">尚無可追蹤觀察名單</div>`;
      const quick = document.querySelector("#quickFilter")?.value || "";
      const riskIds = new Set((data.exit_risks || []).map(x => String(x.stock_id)));
      const retailCleanIds = new Set([
        ...(data.retail_divergence?.clean || []),
        ...(data.retail_divergence?.watch_clean || []),
      ].map(x => String(x.stock_id)));
      const retailHotIds = new Set([
        ...(data.retail_divergence?.overheated || []),
        ...(data.retail_divergence?.watch_overheated || []),
      ].map(x => String(x.stock_id)));
      const topTheme = data.decision_summary?.top_theme || "";
      const rows = data.rows.filter(r => {
        const blob = JSON.stringify(r).toLowerCase();
        const action = String(r.action || "");
        const quickOk =
          !quick ||
          (quick === "strong" && ["S+", "S"].includes(r.grade)) ||
          (quick === "chase" && action.includes("追")) ||
          (quick === "pullback" && action.includes("等拉回")) ||
          (quick === "risk" && riskIds.has(String(r.stock_id))) ||
          (quick === "retail_clean" && retailCleanIds.has(String(r.stock_id))) ||
          (quick === "retail_hot" && retailHotIds.has(String(r.stock_id))) ||
          (quick === "ai" && r.ai_label === "AI 同意") ||
          (quick === "new" && String(data.as_of || "") === String(r.signal_date || data.as_of || "")) ||
          (quick === "top_theme" && (r.themes || []).includes(topTheme)) ||
          (quick === "pattern_bull" && (r.pattern_tags || []).length) ||
          (quick === "pattern_risk" && (r.pattern_risk_tags || []).length);
        return quickOk && (!q || blob.includes(q)) && (!g || r.grade === g);
      });
      document.querySelector("#rows").innerHTML = rows.map(r => `
        <tr data-stock-id="${esc(r.stock_id)}">
          <td data-label="強度"><span class="${cls(r.grade)}">${r.grade}</span></td>
          <td data-label="股票"><b><a class="stock-link" href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a></b><div class="small">${esc(r.label_text)}｜收 ${r.price ?? "-"}｜${esc(r.ai_label || "AI 未複核")}${r.ai_review ? ` ${esc(r.ai_review.pick_agreement_count || r.ai_review.agreement_count || 0)}/${esc(r.ai_review.model_count || 0)}` : ""}</div></td>
          <td data-label="分數"><b>${r.score}/100</b><div class="small">海外 ${r.overseas_adjustment >= 0 ? "+" : ""}${r.overseas_adjustment}｜機會 ${r.opportunity_score}</div></td>
          <td data-label="原因標籤"><div class="tags">${renderTags(r.trigger_tags)}</div></td>
          <td data-label="題材" class="themes"><div>${esc((r.theme_tiers || []).join(" / ") || (r.themes || []).join(" / ") || "-")}</div>${chainSummary(r)}</td>
          <td data-label="四面向">
            <div class="small">${esc(r.trigger_summary || "綜合訊號")}</div>
            <details class="row-detail">
              <summary>展開四面向</summary>
              <div class="small">技術：${esc(r.technical || "無明顯訊號")}</div>
              <div class="small">籌碼：${esc(r.chip || "無明顯訊號")}</div>
              <div class="small">基本：${esc(r.fundamental || "無明顯訊號")}</div>
              <div class="small">風險：${esc(r.risk || "無明顯訊號")}</div>
              <div class="small">入選：${esc(r.decision_reason || r.trigger_summary || "綜合訊號")}</div>
            </details>
          </td>
          <td data-label="操作"><b>${esc(r.entry_decision || r.action || "只觀察")}</b><div class="small">${esc(r.action || "")}</div><div class="decision-light ${esc(r.decision_light || "gray")}"><span class="decision-dot"></span>${esc(r.decision_light_label || "灰燈追蹤")}</div><div class="small"><b>今日：</b>${esc(r.action_context || "未列入今日操作")}</div><div class="small">${esc(r.action_context_reason || "")}</div><div class="small">${esc(r.retail_context || "散戶：無明顯背離")}</div></td>
          <td data-label="進場/停損">
            ${r.entry_limit_price != null ? `<div><b>📌 進場上限：${r.entry_limit_price}</b></div>` : ""}
            ${r.stop_price != null ? `<div style="color:var(--bad)"><b>🔴 止損：${r.stop_price}</b></div>` : ""}
            ${r.exit_plan?.take_profit_1 != null ? `<div class="small good">第一段停利：${esc(priceText(r.exit_plan.take_profit_1))}</div>` : ""}
            ${r.exit_plan?.take_profit_2 != null ? `<div class="small good">第二段停利：${esc(priceText(r.exit_plan.take_profit_2))}</div>` : ""}
            <details class="row-detail">
              <summary>進出場條件</summary>
              ${(r.entry_checklist || []).slice(0,3).map(x => `<div class="small">□ ${esc(x)}</div>`).join("")}
              <div class="small">${esc(r.entry_condition || "資料不足，暫不設進場條件")}</div>
              <div class="small">${esc(r.stop_reference || "資料不足，暫不設停損參考")}</div>
              <div class="small"><b>出場：</b>${esc(r.exit_plan?.trailing_rule || "依停損與移動停利控管。")}</div>
              ${(r.exit_plan?.checklist || []).slice(0,4).map(x => `<div class="small">□ ${esc(x)}</div>`).join("")}
            </details>
          </td>
        </tr>`).join("");
    }
    function sourceClass(label) {
      const base = "status-dot ";
      if (label === "正常") return base + "status-ok";
      if (label === "部分限流" || label === "限流") return base + "status-warn";
      if (label === "錯誤") return base + "status-bad";
      return base;
    }
    function renderThemeHistoryChart() {
      const canvas = document.querySelector("#themeHistoryChart");
      if (!canvas || !themeHistory || !window.Chart) return;
      const names = data.themes.names || {};
      const activeKeys = Object.keys(themeHistory)
        .filter(key => (themeHistory[key] || []).some(row => Number(row.score) > 0))
        .slice(0, 6);
      if (!activeKeys.length) return;
      const dates = [...new Set(activeKeys.flatMap(key => (themeHistory[key] || []).map(row => row.date)))]
        .sort()
        .slice(-14);
      const palette = ["#0b4a8b", "#b42318", "#0f7b4f", "#9a6700", "#7e22ce", "#475467"];
      const datasets = activeKeys.map((key, idx) => {
        const map = Object.fromEntries((themeHistory[key] || []).map(row => [row.date, Number(row.score || 0)]));
        return {
          label: names[key] || key,
          data: dates.map(date => map[date] || 0),
          borderColor: palette[idx % palette.length],
          backgroundColor: palette[idx % palette.length],
          tension: 0.25,
        };
      });
      if (themeChart) themeChart.destroy();
      themeChart = new Chart(canvas, {
        type: "line",
        data: { labels: dates, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      });
    }
    if (window.__DASHBOARD_DATA__ && window.__DASHBOARD_DATA__ !== null) {
      data = window.__DASHBOARD_DATA__;
      render();
    } else {
      fetch("dashboard_data.json")
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(json => { data = json; render(); })
        .catch(err => {
          document.querySelector("#subtitle").textContent = "資料載入失敗";
          document.querySelector("#metrics").innerHTML = "";
          document.querySelector("#market").innerHTML = `<div class="line bad">dashboard_data.json 載入失敗：${esc(err.message)}</div>`;
        });
    }
    document.querySelector("#search").addEventListener("input", render);
    document.querySelector("#grade").addEventListener("change", render);
    fetch("theme_history.json")
      .then(r => r.ok ? r.json() : {})
      .then(json => {
        themeHistory = json;
        if (window.Chart) renderThemeHistoryChart();
        chartScript.addEventListener("load", renderThemeHistoryChart, { once:true });
      })
      .catch(() => {});
  </script>
</body>
</html>"""


def _weekly_html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 每週總覽</title>
  <style>
    :root { color-scheme: light; --ink:#18202a; --muted:#667085; --line:#d9dee7; --bg:#eef2f7; --panel:#fff; --good:#0f7b4f; --warn:#9a6700; --bad:#b42318; --blue:#0b4a8b; --terminal:#0f172a; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Segoe UI", Arial, sans-serif; color:var(--ink); background:linear-gradient(180deg,#e9eef6 0,#f7f8fb 360px); }
    header { padding:20px 24px 12px; border-bottom:1px solid #263244; background:linear-gradient(135deg,var(--terminal),#172033 62%,#0b4a8b); color:white; box-shadow:0 6px 18px rgba(15,23,42,.12); }
    main { max-width:1280px; margin:auto; padding:18px 24px 36px; }
    h1 { margin:0 0 8px; font-size:24px; letter-spacing:0; }
    h2 { margin:0 0 10px; font-size:16px; }
    .sub, .line, .small { color:var(--muted); }
    .sub { font-size:14px; }
    header .sub { color:#cbd5e1; }
    .line { margin:6px 0; font-size:14px; line-height:1.55; }
    .small { font-size:12px; margin-top:3px; line-height:1.45; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; position:sticky; top:0; z-index:20; padding:10px 0; background:rgba(238,242,247,.94); backdrop-filter:blur(10px); border-bottom:1px solid rgba(208,213,221,.75); }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:8px 14px; border:1px solid #cfd7e6; border-radius:6px; background:var(--panel); color:var(--blue); text-decoration:none; font-weight:700; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .nav-tab.active { background:var(--terminal); color:white; border-color:var(--terminal); }
    .summary-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-bottom:14px; }
    .metric, section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 1px 2px rgba(15,23,42,.05); }
    .metric b { display:block; font-size:22px; margin-bottom:4px; }
    .content-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(320px,.72fr); gap:12px; align-items:start; }
    .stack { display:grid; gap:12px; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { padding:9px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; color:#475467; font-size:12px; }
    a.stock-link { color:var(--blue); text-decoration:none; font-weight:700; }
    a.stock-link:hover { text-decoration:underline; }
    .good { color:var(--good); }
    .warn { color:var(--warn); }
    .bad { color:var(--bad); }
    .spark { font-family:monospace; letter-spacing:1px; color:#475467; white-space:nowrap; }
    @media (max-width: 980px) {
      main, header { padding-left:12px; padding-right:12px; }
      .summary-grid { grid-template-columns:1fr 1fr; }
      .content-grid { grid-template-columns:1fr; }
    }
    @media (max-width: 720px) {
      .summary-grid { grid-template-columns:1fr; }
      table, thead, tbody, tr, td { display:block; width:100%; }
      thead { display:none; }
      table { border:0; background:transparent; }
      tr { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin-bottom:10px; padding:10px; }
      td { border:0; padding:5px 0; }
      td::before { content:attr(data-label); display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
    }
  </style>
</head>
<body class="page-weekly">
  <header>
    <h1>台股 AI 每週總覽</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab" href="index.html">今日監控</a>
      <a class="nav-tab" href="performance.html">訊號成效</a>
      <a class="nav-tab" href="potential.html">潛力雷達</a>
      <a class="nav-tab active" href="weekly.html">每週總覽</a>
    </nav>
    <div class="summary-grid" id="metrics"></div>
    <div class="content-grid">
      <div class="stack">
        <section><h2>本週題材熱度</h2><div id="themes"></div></section>
        <section><h2>散戶 / 大戶籌碼</h2><div id="retail"></div></section>
      </div>
      <div class="stack">
        <section><h2>法人週流向</h2><div id="institutional"></div></section>
        <section><h2>訊號品質摘要</h2><div id="performance"></div></section>
        <section><h2>市場環境</h2><div id="market"></div></section>
      </div>
    </div>
  </main>
  <script>
    /* __INLINE_WEEKLY_SENTINEL__ */
    let data = null;
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
    const pct = value => value === null || value === undefined ? "-" : `${Number(value).toFixed(1)}%`;
    const shares = value => value === null || value === undefined ? "-" : `${Math.round(Number(value) / 1000).toLocaleString()} 張`;
    const stockLink = row => `<a class="stock-link" href="https://www.wantgoo.com/stock/${esc(row.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(row.stock_id)} ${esc(row.name || "")}</a>`;
    function spark(history) {
      const bars = "▁▂▃▄▅▆▇█";
      const values = (history || []).map(x => Number(x.score || 0)).reverse();
      const max = Math.max(...values, 1);
      return values.map(v => v <= 0 ? "·" : bars[Math.min(7, Math.round(v / max * 7))]).join("");
    }
    function renderRetailRows(rows) {
      return (rows || []).slice(0, 6).map(row => `
        <tr>
          <td data-label="股票">${stockLink(row)}</td>
          <td data-label="人數變化">${esc(row.holder_change ?? "-")} 人<br><span class="small">${pct(row.holder_change_pct)}</span></td>
          <td data-label="股價變化">${pct(row.price_change_pct)}</td>
          <td data-label="原因">${esc(row.reason || row.signal || "")}</td>
        </tr>`).join("");
    }
    function renderFlowRows(rows) {
      return (rows || []).slice(0, 8).map(row => `
        <tr>
          <td data-label="股票">${stockLink(row)}</td>
          <td data-label="週淨買賣">${shares(row.net_shares)}</td>
        </tr>`).join("");
    }
    function render() {
      const retail = data.retail_divergence || {};
      const retailSummary = retail.summary || {};
      const perfStats = data.performance?.stats || {};
      document.querySelector("#subtitle").textContent = `${data.as_of || "-"}｜每週資料用來看方向，不等於買賣建議`;
      document.querySelector("#metrics").innerHTML = `
        <div class="metric"><b>${esc((data.themes || []).length)}</b><span>本週熱門題材</span></div>
        <div class="metric"><b>${esc(retailSummary.clean ?? 0)}</b><span>籌碼轉乾淨</span></div>
        <div class="metric"><b>${esc(retailSummary.overheated ?? 0)}</b><span>散戶過熱</span></div>
        <div class="metric"><b>${esc(perfStats.win_rate_5d ?? "-")}%</b><span>近30日 5日勝率</span></div>`;
      document.querySelector("#themes").innerHTML = `
        <table><thead><tr><th>題材</th><th>今日</th><th>週熱度</th><th>趨勢</th><th>近7日</th></tr></thead>
        <tbody>${(data.themes || []).slice(0, 10).map(row => `
          <tr>
            <td data-label="題材"><b>${esc(row.name)}</b></td>
            <td data-label="今日">${esc(row.today)}</td>
            <td data-label="週熱度">${esc(row.week_score)}</td>
            <td data-label="趨勢">${esc(row.trend || "-")}</td>
            <td data-label="近7日"><span class="spark">${spark(row.history)}</span></td>
          </tr>`).join("")}</tbody></table>`;
      document.querySelector("#retail").innerHTML = `
        <div class="line">週資料觀察散戶是否集中或退場，需搭配價格與成交量確認。</div>
        <h2 class="good">籌碼轉乾淨</h2>
        <table><thead><tr><th>股票</th><th>人數變化</th><th>股價變化</th><th>原因</th></tr></thead><tbody>${renderRetailRows(retail.clean) || "<tr><td>暫無資料</td></tr>"}</tbody></table>
        <h2 class="warn">散戶過熱</h2>
        <table><thead><tr><th>股票</th><th>人數變化</th><th>股價變化</th><th>原因</th></tr></thead><tbody>${renderRetailRows(retail.overheated) || "<tr><td>暫無資料</td></tr>"}</tbody></table>`;
      const flow = data.institutional || {};
      document.querySelector("#institutional").innerHTML = `
        <div class="line">區間：${esc(flow.since || "-")} 至 ${esc(flow.as_of || "-")}</div>
        <h2 class="good">法人週買超</h2>
        <table><thead><tr><th>股票</th><th>週淨買賣</th></tr></thead><tbody>${renderFlowRows(flow.top_buy) || "<tr><td>暫無資料</td></tr>"}</tbody></table>
        <h2 class="bad">法人週賣超</h2>
        <table><thead><tr><th>股票</th><th>週淨買賣</th></tr></thead><tbody>${renderFlowRows(flow.top_sell) || "<tr><td>暫無資料</td></tr>"}</tbody></table>`;
      const selection = data.performance?.selection_quality || {};
      document.querySelector("#performance").innerHTML = `
        <div class="line">訊號數：${esc(perfStats.signals ?? 0)}｜完成：${esc(perfStats.completed ?? 0)}</div>
        <div class="line">5日平均：${pct(perfStats.avg_return_5d)}｜10日平均：${pct(perfStats.avg_return_10d)}</div>
        <div class="line">最佳題材：${esc(selection.best_theme?.label || "-")}</div>
        <div class="line">樣本說明：${esc(selection.sample_label || "樣本仍在累積")}</div>`;
      document.querySelector("#market").innerHTML = `
        <div class="line"><b>台股</b>：${esc(data.market?.summary || "-")}</div>
        <div class="line"><b>海外</b>：${esc(data.overseas?.label || "-")}｜${esc(data.overseas?.summary || "-")}</div>
        <div class="line warn">每週總覽是方向盤，不是進場按鈕；進出場仍以今日監控的進場價、停損價、風險名單為主。</div>`;
    }
    if (window.__WEEKLY_DATA__ && window.__WEEKLY_DATA__ !== null) {
      data = window.__WEEKLY_DATA__;
      render();
    } else {
      fetch("weekly_data.json").then(r => r.json()).then(json => { data = json; render(); })
        .catch(() => { document.querySelector("#subtitle").textContent = "weekly_data.json 載入失敗"; });
    }
  </script>
</body>
</html>
"""


def _potential_html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 潛力雷達</title>
  <style>
    :root { --ink:#18202a; --muted:#667085; --line:#d9dee7; --bg:#eef2f7; --panel:#fff; --good:#0f7b4f; --bad:#b42318; --warn:#9a6700; --blue:#0b4a8b; --terminal:#0f172a; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Segoe UI", Arial, sans-serif; color:var(--ink); background:linear-gradient(180deg,#e9eef6 0,#f7f8fb 360px); }
    header { padding:20px 24px 12px; border-bottom:1px solid #263244; background:linear-gradient(135deg,var(--terminal),#172033 62%,#0b4a8b); color:white; box-shadow:0 6px 18px rgba(15,23,42,.12); }
    main { max-width:1280px; margin:auto; padding:18px 24px 36px; }
    h1 { margin:0 0 8px; font-size:24px; }
    h2 { margin:0 0 10px; font-size:16px; }
    a { color:var(--blue); text-decoration:none; font-weight:700; }
    a:hover { text-decoration:underline; }
    .sub, .small, .note { color:var(--muted); }
    .sub { font-size:14px; }
    header .sub { color:#cbd5e1; }
    .small { font-size:12px; margin-top:3px; line-height:1.45; }
    .note { font-size:13px; line-height:1.55; margin:4px 0 10px; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; position:sticky; top:0; z-index:20; padding:10px 0; background:rgba(238,242,247,.94); backdrop-filter:blur(10px); border-bottom:1px solid rgba(208,213,221,.75); }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:8px 14px; border:1px solid #cfd7e6; border-radius:6px; background:var(--panel); color:var(--blue); text-decoration:none; font-weight:700; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .nav-tab.active { background:var(--terminal); color:white; border-color:var(--terminal); }
    section, .metric { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 1px 2px rgba(15,23,42,.05); }
    .metrics { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; margin-bottom:14px; }
    .metric b { display:block; font-size:22px; margin-bottom:4px; }
    .grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(330px,.72fr); gap:12px; align-items:start; }
    .stack { display:grid; gap:12px; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { padding:9px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; line-height:1.45; }
    th { background:#eef1f5; color:#475467; font-size:12px; }
    .tag { display:inline-flex; align-items:center; max-width:100%; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; line-height:1.35; margin:2px 3px 0 0; border:1px solid #e2e8f0; background:#f8fafc; color:#475467; white-space:nowrap; word-break:keep-all; }
    .tag.good { background:#f0fdf4; color:var(--good); border-color:#abefc6; }
    .tag.warn { background:#fffbeb; color:var(--warn); border-color:#f6d365; }
    .tag.info { background:#eff6ff; color:var(--blue); border-color:#bfdbfe; }
    .stage { min-width:72px; justify-content:center; color:white; background:var(--blue); border-color:var(--blue); font-size:12px; letter-spacing:0; }
    .stock-link { display:inline-block; min-width:max-content; white-space:nowrap; word-break:keep-all; }
    .stage-col { min-width:90px; }
    .research-cell { min-width:160px; }
    .research-score { display:block; font-weight:800; margin-bottom:3px; }
    .factor-list { display:grid; gap:3px; margin-top:5px; }
    .factor-item { font-size:11px; color:var(--muted); line-height:1.35; }
    .factor-item.pass { color:var(--good); }
    .good { color:var(--good); }
    .bad { color:var(--bad); }
    .warn { color:var(--warn); }
    @media (max-width:1080px) { .metrics { grid-template-columns:repeat(3,minmax(0,1fr)); } .grid { grid-template-columns:1fr; } }
    @media (max-width:720px) {
      main, header { padding-left:12px; padding-right:12px; }
      .metrics { grid-template-columns:1fr 1fr; }
      table, thead, tbody, tr, td { display:block; width:100%; }
      thead { display:none; }
      table { border:0; background:transparent; }
      tr { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin-bottom:10px; padding:10px; }
      td { border:0; padding:5px 0; }
      td::before { content:attr(data-label); display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
    }
  </style>
</head>
<body class="page-potential">
  <header>
    <h1>台股 AI 潛力雷達</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab" href="index.html">今日監控</a>
      <a class="nav-tab" href="performance.html">訊號成效</a>
      <a class="nav-tab active" href="potential.html">潛力雷達</a>
      <a class="nav-tab" href="weekly.html">每週總覽</a>
    </nav>
    <div class="metrics" id="metrics"></div>
    <div class="grid">
      <div class="stack">
        <section>
          <h2>階段勝率</h2>
          <div class="note">比較低位醞釀、轉強初動、強勢等拉回哪一類比較有效；樣本少時先看方向。</div>
          <table><thead><tr><th class="stage-col">階段</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th><th>觀察中</th></tr></thead><tbody id="stageStats"></tbody></table>
        </section>
        <section>
          <h2>提前轉強漏斗</h2>
          <div class="note">追蹤潛力股是否在 14 天內轉成正式 S/A 強訊號，用來驗證我們是否能提早發現。</div>
          <div class="metrics compact-metrics" id="promotionMetrics"></div>
          <table><thead><tr><th>股票</th><th class="stage-col">潛力階段</th><th>轉強日</th><th>強度</th><th>5日</th></tr></thead><tbody id="promotionRows"></tbody></table>
        </section>
        <section>
          <h2>潛力觀察</h2>
          <div class="note">不是買進清單，而是尚未完成驗證、但條件正在累積的股票。</div>
          <table><thead><tr><th>股票</th><th class="stage-col">階段</th><th class="research-cell">研究快篩</th><th>3日</th><th>理由</th></tr></thead><tbody id="candidates"></tbody></table>
        </section>
        <section>
          <h2>因素歸因</h2>
          <div class="note">拆解散戶轉乾淨、K 線轉強、題材升溫等因素是否真的有效。</div>
          <table><thead><tr><th>因素</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th><th>成功/失敗</th></tr></thead><tbody id="factorStats"></tbody></table>
          <div class="note" id="factorNotes"></div>
        </section>
      </div>
      <div class="stack">
        <section><h2>命中樣本</h2><table><thead><tr><th>股票</th><th class="stage-col">階段</th><th>5日</th><th>原因</th></tr></thead><tbody id="successRows"></tbody></table></section>
        <section><h2>失敗樣本</h2><table><thead><tr><th>股票</th><th class="stage-col">階段</th><th>5日</th><th>原因</th></tr></thead><tbody id="failureRows"></tbody></table></section>
      </div>
    </div>
  </main>
  <script>
    /* __INLINE_POTENTIAL_SENTINEL__ */
    let data = null;
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
    const pct = value => value === null || value === undefined ? "—" : `<span class="${value >= 0 ? "good" : "bad"}">${value >= 0 ? "+" : ""}${Number(value).toFixed(1)}%</span>`;
    const neutralPct = value => value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;
    const metric = (label, value, suffix="") => `<div class="metric"><b>${value ?? "—"}${value === null || value === undefined ? "" : suffix}</b><span>${label}</span></div>`;
    const stock = row => `<a class="stock-link" href="https://www.wantgoo.com/stock/${esc(row.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(row.stock_id)} ${esc(row.name || "")}</a>`;
    const tags = row => (row.tags || []).slice(0, 6).map(tag => `<span class="tag">${esc(tag)}</span>`).join("");
    const stageTag = row => `<span class="tag stage">${esc(row.stage_label || "觀察")}</span>`;
    const researchClass = label => label === "順風研究" ? "good" : label === "正常篩選" ? "info" : label === "降溫等待" ? "warn" : "";
    function researchCell(row) {
      const score = row.research_score == null ? "—" : `${row.research_score}/10`;
      const factors = (row.research_factors || []).filter(item => item.passed).slice(0, 3)
        .map(item => `<div class="factor-item pass">✓ ${esc(item.label)}</div>`).join("");
      return `<span class="research-score">${esc(score)}</span>
        ${row.research_label ? `<span class="tag ${researchClass(row.research_label)}">${esc(row.research_label)}</span>` : ""}
        ${row.stock_type_label ? `<span class="tag info">${esc(row.stock_type_label)}</span>` : ""}
        ${row.position_hint_label ? `<span class="tag">${esc(row.position_hint_label)}</span>` : ""}
        ${factors ? `<div class="factor-list">${factors}</div>` : ""}`;
    }
    function signalRow(row) {
      const repeat = Number(row.occurrence_count || 1) > 1 ? `<div class="small">近30日出現 ${esc(row.occurrence_count)} 次，僅顯示代表訊號</div>` : "";
      return `<tr><td data-label="股票">${stock(row)}${repeat}</td><td data-label="階段">${stageTag(row)}</td><td data-label="5日">${pct(row.return_5d)}${row.return_10d != null ? `<div class="small">10日 ${pct(row.return_10d)}</div>` : ""}</td><td data-label="原因">${esc(row.outcome_reason || row.reason || "")}<div>${tags(row)}</div></td></tr>`;
    }
    function promotionRow(row) {
      return `<tr>
        <td data-label="股票">${stock(row)}${Number(row.occurrence_count || 1) > 1 ? `<div class="small">近30日出現 ${esc(row.occurrence_count)} 次</div>` : ""}</td>
        <td data-label="潛力階段">${esc(row.stage_label || "觀察")}<div class="small">${esc(row.signal_date || "")}</div></td>
        <td data-label="轉強日">${esc(row.promoted_signal_date || "—")}${row.days_to_promotion != null ? `<div class="small">${esc(row.days_to_promotion)} 天</div>` : ""}</td>
        <td data-label="強度">${esc(row.promoted_grade || "—")}${row.promoted_score != null ? `<div class="small">${esc(row.promoted_score)}/100</div>` : ""}</td>
        <td data-label="5日">${pct(row.return_5d)}</td>
      </tr>`;
    }
    function render() {
      const radar = data.potential_radar || {};
      const learning = data.learning_center || {};
      const stats = radar.stats || {};
      const funnel = radar.promotion_funnel || {};
      document.querySelector("#subtitle").textContent = `${data.as_of || ""}｜近 ${data.days || 30} 天｜僅供研究追蹤`;
      document.querySelector("#metrics").innerHTML = [
        metric("雷達記錄", stats.signals ?? 0),
        metric("已驗證", stats.completed ?? 0),
        metric("觀察中", stats.pending ?? 0),
        metric("5日勝率", stats.win_rate_5d?.toFixed(1), "%"),
        metric("5日平均", stats.avg_return_5d?.toFixed(1), "%"),
        metric("提前命中", stats.big_winner_count ?? 0),
      ].join("");
      document.querySelector("#stageStats").innerHTML = (radar.stage_stats || []).length ? radar.stage_stats.map(row => `<tr><td data-label="階段"><b>${esc(row.label)}</b></td><td data-label="訊號">${esc(row.signals)}</td><td data-label="完成">${esc(row.completed)}</td><td data-label="5日勝率">${neutralPct(row.win_rate_5d)}</td><td data-label="5日平均">${pct(row.avg_return_5d)}</td><td data-label="觀察中">${esc(row.pending)}</td></tr>`).join("") : `<tr><td data-label="階段" colspan="6">尚無潛力雷達資料</td></tr>`;
      document.querySelector("#promotionMetrics").innerHTML = [
        metric("潛力記錄", funnel.signals ?? 0),
        metric("已轉強", funnel.promoted ?? 0),
        metric("轉強率", funnel.conversion_rate?.toFixed(1), "%"),
        metric("轉強後勝率", funnel.promoted_win_rate_5d?.toFixed(1), "%"),
        metric("平均轉強", funnel.avg_days_to_promotion?.toFixed(1), "天"),
      ].join("");
      document.querySelector("#promotionRows").innerHTML = (funnel.examples || []).length ? funnel.examples.map(promotionRow).join("") : `<tr><td data-label="提前轉強" colspan="5">尚無潛力股轉強紀錄</td></tr>`;
      const potentialRows = (radar.pending_candidates || []).length ? radar.pending_candidates : (learning.potential_candidates || []);
      document.querySelector("#candidates").innerHTML = potentialRows.length ? potentialRows.slice(0, 12).map(row => `<tr><td data-label="股票">${stock(row)}${Number(row.occurrence_count || 1) > 1 ? `<div class="small">近30日出現 ${esc(row.occurrence_count)} 次</div>` : ""}</td><td data-label="階段">${stageTag(row)}<div class="small">${esc(row.signal_date || "")}</div></td><td data-label="研究快篩">${researchCell(row)}</td><td data-label="3日">${pct(row.return_3d)}</td><td data-label="理由"><b>${esc(row.grade)}｜${esc(row.total_score)}/100</b><div class="small">${esc(row.reason || "")}</div>${row.chase_risk_label ? `<div class="small">追高檢查：${esc(row.chase_risk_label)}</div>` : ""}<div>${tags(row)}</div></td></tr>`).join("") : `<tr><td data-label="潛力觀察" colspan="5">目前沒有符合條件的潛力觀察</td></tr>`;
      document.querySelector("#factorStats").innerHTML = (radar.factor_stats || []).length ? radar.factor_stats.map(row => `<tr><td data-label="因素">${esc(row.label)}</td><td data-label="訊號">${esc(row.signals)}</td><td data-label="完成">${esc(row.completed)}</td><td data-label="5日勝率">${neutralPct(row.win_rate_5d)}</td><td data-label="5日平均">${pct(row.avg_return_5d)}</td><td data-label="成功/失敗">${esc(row.success_count || 0)} / ${esc(row.failure_count || 0)}</td></tr>`).join("") : `<tr><td data-label="因素" colspan="6">因素樣本仍在累積中</td></tr>`;
      document.querySelector("#factorNotes").innerHTML = (radar.factor_notes || []).map(note => `- ${esc(note)}`).join("<br>");
      document.querySelector("#successRows").innerHTML = (radar.success_cases || []).length ? radar.success_cases.map(signalRow).join("") : `<tr><td data-label="命中樣本" colspan="4">尚無已驗證命中樣本</td></tr>`;
      document.querySelector("#failureRows").innerHTML = (radar.failure_cases || []).length ? radar.failure_cases.map(signalRow).join("") : `<tr><td data-label="失敗樣本" colspan="4">尚無已驗證失敗樣本</td></tr>`;
    }
    if (window.__POTENTIAL_DATA__) { data = window.__POTENTIAL_DATA__; render(); }
    fetch("potential_data.json").then(r => r.json()).then(json => { data = json; render(); }).catch(() => {});
  </script>
</body>
</html>"""


def _performance_html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 訊號成效追蹤</title>
  <style>
    :root { color-scheme: light; --ink:#18202a; --muted:#667085; --line:#d9dee7; --bg:#eef2f7; --panel:#fff; --good:#0f7b4f; --bad:#b42318; --blue:#0b4a8b; --terminal:#0f172a; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Segoe UI", Arial, sans-serif; color:var(--ink); background:linear-gradient(180deg,#e9eef6 0,#f7f8fb 360px); }
    header { padding:20px 24px 12px; border-bottom:1px solid #263244; background:linear-gradient(135deg,var(--terminal),#172033 62%,#0b4a8b); color:white; box-shadow:0 6px 18px rgba(15,23,42,.12); }
    h1 { margin:0 0 8px; font-size:24px; }
    .sub, .small { color:var(--muted); font-size:13px; }
    header .sub { color:#cbd5e1; }
    main { padding:18px 24px 32px; max-width:1320px; margin:auto; }
    .metrics { display:grid; grid-template-columns:repeat(6,minmax(120px,1fr)); gap:10px; margin-bottom:16px; }
    .compact-metrics { grid-template-columns:repeat(5,minmax(120px,1fr)); }
    .metric { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; box-shadow:0 1px 2px rgba(15,23,42,.05); }
    .metric b { display:block; font-size:clamp(18px, 4vw, 22px); margin-bottom:2px; overflow-wrap:anywhere; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:14px 0; flex-wrap:wrap; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; position:sticky; top:0; z-index:20; padding:10px 0; background:rgba(238,242,247,.94); backdrop-filter:blur(10px); border-bottom:1px solid rgba(208,213,221,.75); }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:8px 14px; border:1px solid #cfd7e6; border-radius:6px; background:var(--panel); color:#0b4a8b; text-decoration:none; font-weight:700; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .nav-tab.active { background:var(--terminal); color:white; border-color:var(--terminal); }
    input, select { border:1px solid var(--line); border-radius:6px; padding:9px 10px; background:white; min-height:38px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .analysis-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 1px 2px rgba(15,23,42,.05); }
    .quality-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:10px; }
    .quality-card { border:1px solid var(--line); border-radius:8px; padding:10px; min-height:94px; background:#fbfcfe; }
    .quality-card b { display:block; font-size:15px; margin-bottom:4px; }
    .quality-card .value { font-size:18px; font-weight:800; margin:2px 0; }
    .advice-list { display:grid; gap:8px; margin-top:10px; }
    .advice-item { border-left:4px solid #9a6700; background:#fffaf0; padding:9px 10px; border-radius:6px; font-size:13px; }
    .advice-item.good { border-left-color:var(--good); background:#f0f9f5; }
    .advice-item.bad { border-left-color:var(--bad); background:#fff5f5; }
    h2 { font-size:16px; margin:0 0 8px; }
    .note { color:var(--muted); font-size:12px; margin:0 0 10px; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; font-size:12px; color:#475467; }
    a { color:#0b4a8b; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .pos { color:var(--good); font-weight:700; }
    .neg { color:var(--bad); font-weight:700; }
    .lesson-tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:4px; }
    .lesson-tag { display:inline-block; padding:2px 7px; border-radius:999px; font-size:11px; font-weight:700; background:#f8fafc; color:#475467; border:1px solid #e2e8f0; }
    .lesson-tag.good { background:#f0f9f5; color:var(--good); border-color:#abefc6; }
    .lesson-tag.bad { background:#fff5f5; color:var(--bad); border-color:#fecdd6; }
    .tag-good { background:#f0f9f5; color:var(--good); border:1px solid #abefc6; }
    @media (max-width:1100px) {
      .metrics { grid-template-columns:repeat(3,1fr); }
    }
    @media (max-width:900px) {
      main, header { padding-left:12px; padding-right:12px; }
      .metrics { grid-template-columns:1fr 1fr; }
      .analysis-grid { grid-template-columns:1fr; }
      .quality-grid { grid-template-columns:1fr; }
      input, select { width:100%; min-width:0; }
      table, thead, tbody, tr, td { display:block; width:100%; }
      thead { display:none; }
      table { border:0; background:transparent; }
      tr { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin-bottom:10px; padding:10px; }
      td { border:0; padding:5px 0; }
      td::before { content:attr(data-label); display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
    }
  </style>
</head>
<body class="page-performance">
  <header>
    <h1>台股 AI 訊號成效追蹤</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab" href="index.html">今日監控</a>
      <a class="nav-tab active" href="performance.html">訊號成效</a>
      <a class="nav-tab" href="potential.html">潛力雷達</a>
      <a class="nav-tab" href="weekly.html">每週總覽</a>
    </nav>
    <div class="metrics" id="metrics"></div>
    <section style="margin-bottom:16px;">
      <h2>選股品質總覽</h2>
      <div class="note" id="qualityNote">載入中...</div>
      <div class="quality-grid" id="selectionQuality"></div>
      <div class="advice-list" id="calibrationAdvice"></div>
      <h2 style="margin-top:14px;">反饋權重建議</h2>
      <div class="note">根據已驗證的成功與失敗樣本提出調整方向；只做提示，不自動改核心分數。</div>
      <div class="advice-list" id="adaptiveFeedback"></div>
    </section>
    <section style="margin-bottom:16px;">
      <h2>信號歸因中心</h2>
      <div class="note">把今日操作、潛力雷達、AI 複核放在同一張表比較，用來看哪一層真的提升勝率；樣本不足時只觀察，不自動改權重。</div>
      <div class="analysis-grid">
        <section>
          <h2>來源層成效</h2>
          <table>
            <thead><tr><th>來源</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th><th>狀態</th></tr></thead>
            <tbody id="attributionSources"></tbody>
          </table>
        </section>
        <section>
          <h2>因素層成效</h2>
          <table>
            <thead><tr><th>因素</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th><th>樣本</th></tr></thead>
            <tbody id="attributionFactors"></tbody>
          </table>
        </section>
      </div>
      <div class="note" id="attributionNotes"></div>
    </section>
    <div class="analysis-grid">
      <section>
        <h2>5日強勢榜</h2>
        <table>
          <thead><tr><th>股票</th><th>訊號日</th><th>強度</th><th>5日報酬</th><th>題材</th></tr></thead>
          <tbody id="leaderTop"></tbody>
        </table>
      </section>
      <section>
        <h2>5日弱勢榜</h2>
        <table>
          <thead><tr><th>股票</th><th>訊號日</th><th>強度</th><th>5日報酬</th><th>停損</th></tr></thead>
          <tbody id="leaderBottom"></tbody>
        </table>
      </section>
    </div>
    <section style="margin-bottom:16px;">
      <h2>成功 / 失敗檢討</h2>
      <div class="note">每一筆推薦都會回頭用 5 日與 10 日表現驗證，成功、失敗、錯過機會都會留下原因。</div>
      <div class="metrics" id="postmortemMetrics"></div>
      <div class="analysis-grid">
        <section>
          <h2>成功樣本</h2>
          <table>
            <thead><tr><th>股票</th><th>訊號日</th><th>結果</th><th>5日報酬</th><th>原因</th></tr></thead>
            <tbody id="postmortemSuccess"></tbody>
          </table>
        </section>
        <section>
          <h2>失敗樣本</h2>
          <table>
            <thead><tr><th>股票</th><th>訊號日</th><th>結果</th><th>5日報酬</th><th>原因</th></tr></thead>
            <tbody id="postmortemFailure"></tbody>
          </table>
        </section>
      </div>
      <section style="margin-top:12px;">
        <h2>失敗歸因</h2>
        <div class="note">把失敗拆成可修正的原因，之後用來調整追價、停損與題材權重。</div>
        <table>
          <thead><tr><th>原因</th><th>筆數</th><th>5日平均</th><th>停損率</th><th>代表樣本</th><th>下次修正</th></tr></thead>
          <tbody id="failureAttribution"></tbody>
        </table>
      </section>
      <section style="margin-top:12px;">
        <h2>危險名單回測</h2>
        <div class="note">驗證危險名單提醒後 5 日內是否真的轉弱；命中率越高，代表避險規則越有效。</div>
        <div class="metrics compact-metrics" id="exitRiskMetrics"></div>
        <table>
          <thead><tr><th>股票</th><th>訊號日</th><th>等級</th><th>5日報酬</th><th>原因</th></tr></thead>
          <tbody id="exitRiskBacktest"></tbody>
        </table>
      </section>
      <div class="note" id="postmortemNotes"></div>
    </section>
    <section style="margin-bottom:16px;">
      <h2>選股學習中心</h2>
      <div class="note">把成功與失敗拆成可重複檢查的條件，另外列出尚未大漲、但條件正在累積的潛力觀察。</div>
      <div class="analysis-grid">
        <section>
          <h2>成功因素</h2>
          <table>
            <thead><tr><th>因素</th><th>樣本</th><th>5日勝率</th><th>5日平均</th><th>解讀</th></tr></thead>
            <tbody id="successFactors"></tbody>
          </table>
        </section>
        <section>
          <h2>失敗因素</h2>
          <table>
            <thead><tr><th>因素</th><th>樣本</th><th>5日勝率</th><th>5日平均</th><th>解讀</th></tr></thead>
            <tbody id="failureFactors"></tbody>
          </table>
        </section>
      </div>
      <section style="margin-top:12px;">
        <h2>潛力雷達摘要</h2>
        <div class="note">潛力股的階段勝率、命中/失敗樣本與因素歸因已移到獨立頁，成效頁只保留摘要避免資訊過載。</div>
        <div class="metrics compact-metrics" id="potentialRadarSummary"></div>
        <p class="note" id="potentialRadarSummaryNote"></p>
        <a class="nav-tab" href="potential.html">查看潛力雷達完整追蹤</a>
      </section>
      <div class="note" id="learningNotes"></div>
    </section>
    <div class="analysis-grid">
      <section>
        <h2>題材成效</h2>
        <div class="note">同一訊號若屬於多個題材，會分別計入各題材統計。<b>停損</b>欄 = 訊號發出後 5 日內股價觸及或跌破預設止損價的比率（<b>越低越好</b>，代表止損設定合理、未被提前出場）。</div>
        <table>
          <thead><tr><th>題材</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th><th>停損</th></tr></thead>
          <tbody id="themeStats"></tbody>
        </table>
      </section>
      <section>
        <h2>分數區間</h2>
        <div class="note">僅顯示資料，不自動調整 BUY/WATCH 門檻；目前只追蹤 BUY_WATCH（65 分以上）訊號，勝率定義為 5 日報酬 > 0%。</div>
        <table>
          <thead><tr><th>區間</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th></tr></thead>
          <tbody id="scoreBands"></tbody>
        </table>
      </section>
    </div>
    <div class="analysis-grid">
      <section>
        <h2>操作建議成效</h2>
        <table>
          <thead><tr><th>建議</th><th>訊號數</th><th>完成數</th><th>5日勝率</th><th>5日平均</th></tr></thead>
          <tbody id="actionStats"></tbody>
        </table>
      </section>
      <section>
        <h2>題材排行榜</h2>
        <table>
          <thead><tr><th>題材</th><th>完成數</th><th>5日勝率</th><th>5日平均</th><th>停損率</th></tr></thead>
          <tbody id="topThemes"></tbody>
        </table>
      </section>
    </div>
    <section style="margin-bottom:16px;">
      <h2>資料品質</h2>
      <table>
        <thead><tr><th>項目</th><th>數值</th></tr></thead>
        <tbody id="dataQuality"></tbody>
      </table>
    </section>
  <section>
      <h2>進場條件分析</h2>
      <div class="note">比較進場條件是否對報酬有正向影響；樣本不足時數據僅供參考。</div>
      <table>
        <thead><tr><th>類型</th><th>筆數</th><th>5日勝率</th><th>5日平均報酬</th></tr></thead>
        <tbody id="entryAnalysis"></tbody>
      </table>
    </section>
    <section style="margin-bottom:16px;">
      <h2>Signal Lab：強度驗證</h2>
      <div class="note">離線驗證 S+/S/A/B 各強度在 3 日、5 日、10 日後的平均表現；強度不是買賣建議，樣本未滿 30 筆前僅供觀察。</div>
      <table>
        <thead><tr><th>強度</th><th>訊號</th><th>3日勝率</th><th>3日平均</th><th>5日勝率</th><th>5日平均</th><th>10日勝率</th><th>10日平均</th></tr></thead>
        <tbody id="signalLab"></tbody>
      </table>
    </section>
    <div class="analysis-grid">
      <section>
        <h2>回測強項</h2>
        <table>
          <thead><tr><th>類型</th><th>區塊</th><th>樣本</th><th>5日勝率</th><th>5日平均</th></tr></thead>
          <tbody id="bestSegments"></tbody>
        </table>
      </section>
      <section>
        <h2>需檢討區塊</h2>
        <table>
          <thead><tr><th>類型</th><th>區塊</th><th>樣本</th><th>5日勝率</th><th>5日平均</th></tr></thead>
          <tbody id="weakSegments"></tbody>
        </table>
      </section>
    </div>
    <section style="margin-bottom:16px;">
      <h2>AI 複核勝率</h2>
      <div class="note">統計 OpenRouter 多模型共識建議後的 5 日勝率；AI 只做複核與記錄，不直接改變原始分數。</div>
      <table>
        <thead><tr><th>AI 建議</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th><th>10日平均</th></tr></thead>
        <tbody id="aiCouncilStats"></tbody>
      </table>
    </section>
    <div class="toolbar">
      <input id="search" placeholder="搜尋股票、日期、狀態..." />
      <select id="grade"><option value="">全部強度</option><option>S+</option><option>S</option><option>A</option><option>B</option><option>C</option></select>
      <select id="status"><option value="">全部狀態</option><option>已完成</option><option>進行中</option></select>
    </div>
    <table>
      <thead><tr><th>訊號日</th><th>股票</th><th>強度</th><th>分數</th><th>訊號價</th><th>進場觸發</th><th>3日漲跌</th><th>5日漲跌</th><th>停損觸及</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    /* __INLINE_PERF_SENTINEL__ */
    let data = null;
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
    const fmtPct = value => value === null || value === undefined ? "—" : `<span class="${value >= 0 ? "pos" : "neg"}">${value >= 0 ? "+" : ""}${Number(value).toFixed(1)}%</span>`;
    const fmtNeutralPct = value => value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;
    const fmtBool = value => value === null || value === undefined ? "—" : (value ? "是" : "否");
    function metric(label, value, suffix="") {
      return `<div class="metric"><b>${value ?? "—"}${value === null || value === undefined ? "" : suffix}</b><span>${label}</span></div>`;
    }
    function segmentText(row, suffix="") {
      if (!row || !row.label) return "樣本不足";
      const parts = [
        `${esc(row.label)}${suffix}`,
        `${esc(row.completed ?? 0)}筆`,
        `勝率 ${row.win_rate_5d == null ? "—" : Number(row.win_rate_5d).toFixed(1) + "%"}`,
        `平均 ${row.avg_return_5d == null ? "—" : (row.avg_return_5d >= 0 ? "+" : "") + Number(row.avg_return_5d).toFixed(1) + "%"}`
      ];
      return parts.join("｜");
    }
    function qualityCard(title, row, suffix="") {
      return `<div class="quality-card">
        <b>${esc(title)}</b>
        <div class="value">${row?.label ? esc(row.label) + suffix : "樣本不足"}</div>
        <div class="small">${segmentText(row, suffix)}</div>
      </div>`;
    }
    function adviceClass(priority) {
      if (priority === "加權觀察") return "good";
      if (priority === "降權觀察" || priority === "風險檢查") return "bad";
      return "";
    }
    function render() {
      const stats = data.stats || {};
      const quality = data.data_quality || {};
      const selection = data.selection_quality || {};
      document.querySelector("#subtitle").textContent = `${data.as_of}｜近 ${data.days} 天｜僅供研究追蹤`;
      document.querySelector("#metrics").innerHTML = [
        metric("訊號總數", stats.signals),
        metric("已完成", stats.completed),
        metric("5日勝率", stats.win_rate_5d?.toFixed(1), "%"),
        metric("5日平均", stats.avg_return_5d?.toFixed(1), "%"),
        `<div class="metric" title="訊號發出後 5 日內，股價觸及或跌破預設止損價的比率。越低代表止損設定越合理、訊號品質越佳。"><b>${stats.stop_hit_rate?.toFixed(1) ?? "—"}${stats.stop_hit_rate != null ? "%" : ""}</b><span>停損觸及率</span><div style="color:var(--muted);font-size:11px;margin-top:2px;">↓ 越低越好</div></div>`,
        metric("A級5日勝率", stats.a_win_rate_5d?.toFixed(1), "%"),
      ].join("");
      document.querySelector("#qualityNote").textContent = `${selection.sample_label || "樣本不足"}｜${selection.sample_note || "先持續累積樣本，不自動改權重。"}`;
      document.querySelector("#selectionQuality").innerHTML = [
        qualityCard("最有效強度", selection.best_grade),
        qualityCard("需檢討強度", selection.weak_grade),
        qualityCard("最有效題材", selection.best_theme),
        qualityCard("需檢討題材", selection.weak_theme),
        qualityCard("最佳分數區間", selection.best_score_band),
        qualityCard("需檢討分數區間", selection.weak_score_band),
        qualityCard("最佳操作建議", selection.best_action),
        `<div class="quality-card"><b>AI 複核樣本</b><div class="value">${esc(selection.ai?.sample_label || "樣本不足")}</div><div class="small">完成 ${esc(selection.ai?.completed ?? 0)} 筆｜勝率 ${selection.ai?.win_rate_5d == null ? "—" : Number(selection.ai.win_rate_5d).toFixed(1) + "%"}｜平均 ${selection.ai?.avg_return_5d == null ? "—" : (selection.ai.avg_return_5d >= 0 ? "+" : "") + Number(selection.ai.avg_return_5d).toFixed(1) + "%"}</div></div>`,
      ].join("");
      document.querySelector("#calibrationAdvice").innerHTML = (data.calibration_advice || []).length
        ? data.calibration_advice.map(row => `<div class="advice-item ${adviceClass(row.priority)}"><b>${esc(row.priority)}｜${esc(row.group)}：${esc(row.label)}</b><div>${esc(row.reason)}</div><div class="small">完成 ${esc(row.completed)} 筆｜5日勝率 ${row.win_rate_5d == null ? "—" : Number(row.win_rate_5d).toFixed(1) + "%"}｜5日平均 ${row.avg_return_5d == null ? "—" : (row.avg_return_5d >= 0 ? "+" : "") + Number(row.avg_return_5d).toFixed(1) + "%"}</div></div>`).join("")
        : `<div class="advice-item">目前樣本不足或無明顯需要調權的區塊，先持續記錄。</div>`;
      document.querySelector("#adaptiveFeedback").innerHTML = (data.adaptive_feedback || []).length
        ? data.adaptive_feedback.map(row => `<div class="advice-item ${row.priority === "high" ? "bad" : ""}"><b>${esc(row.source)}｜${esc(row.target || "整體")}：${esc(row.action || "持續觀察")}</b><div>${esc(row.reason || "")}</div><div class="small">樣本 ${esc(row.sample ?? 0)} 筆｜5日平均 ${row.avg_return_5d == null ? "—" : (row.avg_return_5d >= 0 ? "+" : "") + Number(row.avg_return_5d).toFixed(1) + "%"}</div></div>`).join("")
        : `<div class="advice-item">反饋樣本仍在累積中；目前不建議調整權重。</div>`;
      const attribution = data.signal_attribution || {};
      const attrSourceRow = row => `<tr>
        <td data-label="來源"><b>${esc(row.label)}</b><div class="small">${esc(row.note || "")}</div></td>
        <td data-label="訊號">${esc(row.signals ?? 0)}</td>
        <td data-label="完成">${esc(row.completed ?? 0)}</td>
        <td data-label="5日勝率">${fmtPct(row.win_rate_5d)}</td>
        <td data-label="5日平均">${fmtPct(row.avg_return_5d)}</td>
        <td data-label="狀態"><span class="tag ${Number(row.completed || 0) >= 20 ? "tag-good" : "tag-default"}">${Number(row.completed || 0) >= 20 ? "可參考" : "累積中"}</span></td>
      </tr>`;
      const attrFactorRow = row => `<tr>
        <td data-label="因素"><b>${esc(row.label)}</b></td>
        <td data-label="訊號">${esc(row.signals ?? 0)}</td>
        <td data-label="完成">${esc(row.completed ?? 0)}</td>
        <td data-label="5日勝率">${fmtPct(row.win_rate_5d)}</td>
        <td data-label="5日平均">${fmtPct(row.avg_return_5d)}</td>
        <td data-label="樣本">${esc(row.sample_label || "樣本不足")}</td>
      </tr>`;
      document.querySelector("#attributionSources").innerHTML = (attribution.summary_rows || []).length
        ? attribution.summary_rows.map(attrSourceRow).join("")
        : `<tr><td data-label="來源層成效" colspan="6">尚無歸因資料</td></tr>`;
      document.querySelector("#attributionFactors").innerHTML = (attribution.factor_rows || []).length
        ? attribution.factor_rows.slice(0, 8).map(attrFactorRow).join("")
        : `<tr><td data-label="因素層成效" colspan="6">尚無因素歸因資料</td></tr>`;
      document.querySelector("#attributionNotes").innerHTML = (attribution.notes || []).map(note => `- ${esc(note)}`).join("<br>");
      const leaderRow = (r, includeStop=false) => `
        <tr>
          <td data-label="股票"><a href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a></td>
          <td data-label="訊號日">${esc(r.signal_date)}</td>
          <td data-label="強度">${esc(r.grade)}</td>
          <td data-label="5日報酬">${fmtPct(r.return_5d)}</td>
          <td data-label="${includeStop ? "停損" : "題材"}">${includeStop ? fmtBool(r.stop_hit) : esc((r.themes || []).slice(0, 2).join(" / ") || "—")}</td>
        </tr>`;
      document.querySelector("#leaderTop").innerHTML = (data.leaderboard?.top_5d || []).length
        ? data.leaderboard.top_5d.slice(0, 5).map(r => leaderRow(r)).join("")
        : `<tr><td data-label="5日強勢榜" colspan="5">尚無完成追蹤訊號</td></tr>`;
      document.querySelector("#leaderBottom").innerHTML = (data.leaderboard?.bottom_5d || []).length
        ? data.leaderboard.bottom_5d.slice(0, 5).map(r => leaderRow(r, true)).join("")
        : `<tr><td data-label="5日弱勢榜" colspan="5">尚無完成追蹤訊號</td></tr>`;
      const postmortem = data.postmortem || {};
      const countBy = key => (postmortem.counts || []).find(row => row.category === key)?.count ?? 0;
      const postmortemRow = r => {
        const tags = (r.lesson_tags || []).slice(0, 4).map(tag => {
          const cls = String(tag).includes("失敗") || String(tag).includes("跌破") ? "bad" : String(tag).includes("成功") || String(tag).includes("飆股") ? "good" : "";
          return `<span class="lesson-tag ${cls}">${esc(tag)}</span>`;
        }).join("");
        return `<tr>
          <td data-label="股票"><a href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a><div class="small">${esc(r.grade)}｜${esc(r.total_score)}/100</div></td>
          <td data-label="訊號日">${esc(r.signal_date)}</td>
          <td data-label="結果">${esc(r.outcome_label)}</td>
          <td data-label="5日報酬">${fmtPct(r.return_5d)}${r.return_10d != null ? `<div class="small">10日 ${fmtPct(r.return_10d)}</div>` : ""}</td>
          <td data-label="原因">${esc(r.outcome_reason)}<div class="lesson-tags">${tags}</div></td>
        </tr>`;
      };
      document.querySelector("#postmortemMetrics").innerHTML = [
        metric("已驗證", postmortem.sample ?? 0),
        metric("飆股命中", countBy("big_winner")),
        metric("方向正確", countBy("true_positive")),
        metric("假訊號", countBy("false_positive")),
        metric("跌破停損", countBy("stop_loss")),
        metric("錯過機會", countBy("missed_opportunity")),
      ].join("");
      document.querySelector("#postmortemSuccess").innerHTML = (postmortem.success_cases || []).length
        ? postmortem.success_cases.slice(0, 6).map(postmortemRow).join("")
        : `<tr><td data-label="成功樣本" colspan="5">尚無已完成成功樣本</td></tr>`;
      document.querySelector("#postmortemFailure").innerHTML = (postmortem.failure_cases || []).length
        ? postmortem.failure_cases.slice(0, 6).map(postmortemRow).join("")
        : `<tr><td data-label="失敗樣本" colspan="5">尚無已完成失敗樣本</td></tr>`;
      const failureAttr = postmortem.failure_attribution || {};
      const failureAttrRow = row => {
        const examples = (row.examples || []).map(item => `${esc(item.stock_id)} ${esc(item.name || "")} ${item.return_5d == null ? "" : Number(item.return_5d).toFixed(1) + "%"}`).join("<br>");
        return `<tr>
          <td data-label="原因"><b>${esc(row.label)}</b></td>
          <td data-label="筆數">${esc(row.count ?? 0)}</td>
          <td data-label="5日平均">${fmtPct(row.avg_return_5d)}</td>
          <td data-label="停損率">${fmtNeutralPct(row.stop_hit_rate)}</td>
          <td data-label="代表樣本">${examples || "—"}</td>
          <td data-label="下次修正">${esc(row.lesson || "")}</td>
        </tr>`;
      };
      document.querySelector("#failureAttribution").innerHTML = (failureAttr.rows || []).length
        ? failureAttr.rows.map(failureAttrRow).join("")
        : `<tr><td data-label="失敗歸因" colspan="6">失敗樣本仍在累積中</td></tr>`;
      const exitRisk = data.exit_risk || {};
      const exitStats = exitRisk.stats || {};
      document.querySelector("#exitRiskMetrics").innerHTML = [
        metric("危險提醒", exitStats.signals ?? 0),
        metric("已驗證", exitStats.completed ?? 0),
        metric("5日命中率", exitStats.true_warning_rate_5d?.toFixed(1), "%"),
        metric("提醒後平均", exitStats.avg_return_5d?.toFixed(1), "%"),
      ].join("");
      const exitRiskRow = r => `<tr>
        <td data-label="股票"><a href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a></td>
        <td data-label="訊號日">${esc(r.signal_date)}</td>
        <td data-label="等級">${esc(r.level)}｜${esc(r.risk_score || 0)}</td>
        <td data-label="5日報酬">${fmtPct(r.return_5d)}</td>
        <td data-label="原因">${esc((r.reasons || []).slice(0, 3).join("、") || r.action || "—")}</td>
      </tr>`;
      const exitRows = [...(exitRisk.true_warnings || []), ...(exitRisk.false_warnings || [])].slice(0, 8);
      document.querySelector("#exitRiskBacktest").innerHTML = exitRows.length
        ? exitRows.map(exitRiskRow).join("")
        : `<tr><td data-label="危險名單回測" colspan="5">危險名單樣本仍在累積中</td></tr>`;
      document.querySelector("#postmortemNotes").innerHTML = (postmortem.notes || []).map(note => `- ${esc(note)}`).join("<br>");
      const learning = data.learning_center || {};
      const factorRow = row => `<tr>
        <td data-label="因素">${esc(row.label)}</td>
        <td data-label="樣本">${esc(row.completed ?? row.count ?? 0)}</td>
        <td data-label="5日勝率">${fmtPct(row.win_rate_5d)}</td>
        <td data-label="5日平均">${fmtPct(row.avg_return_5d)}</td>
        <td data-label="解讀">${esc(row.reason)}</td>
      </tr>`;
      document.querySelector("#successFactors").innerHTML = (learning.success_factors || []).length
        ? learning.success_factors.map(factorRow).join("")
        : `<tr><td data-label="成功因素" colspan="5">尚無足夠成功因素樣本</td></tr>`;
      document.querySelector("#failureFactors").innerHTML = (learning.failure_factors || []).length
        ? learning.failure_factors.map(factorRow).join("")
        : `<tr><td data-label="失敗因素" colspan="5">尚無足夠失敗因素樣本</td></tr>`;
      const radar = data.potential_radar || {};
      const radarStats = radar.stats || {};
      const topStage = (radar.stage_stats || [])[0];
      document.querySelector("#potentialRadarSummary").innerHTML = [
        metric("雷達記錄", radarStats.signals ?? 0),
        metric("已驗證", radarStats.completed ?? 0),
        metric("觀察中", radarStats.pending ?? 0),
        metric("5日勝率", radarStats.win_rate_5d?.toFixed(1), "%"),
        metric(topStage ? `主階段：${topStage.label}` : "主階段", topStage ? `${topStage.signals}` : "—", topStage ? "檔" : ""),
      ].join("");
      document.querySelector("#potentialRadarSummaryNote").textContent = topStage
        ? `目前樣本最多的階段是「${topStage.label}」，完整命中與失敗原因請到潛力雷達頁查看。`
        : "潛力雷達樣本仍在累積中。";
      document.querySelector("#learningNotes").innerHTML = (learning.notes || []).map(note => `- ${esc(note)}`).join("<br>");
      document.querySelector("#themeStats").innerHTML = (data.theme_stats || []).length
        ? data.theme_stats.map(r => `
          <tr>
            <td data-label="題材">${esc(r.label)}</td>
            <td data-label="訊號">${esc(r.signals)}</td>
            <td data-label="完成">${esc(r.completed)}</td>
            <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
            <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
            <td data-label="停損">${fmtNeutralPct(r.stop_hit_rate)}</td>
          </tr>
        `).join("")
        : `<tr><td data-label="題材" colspan="6">尚無題材統計資料</td></tr>`;
      document.querySelector("#scoreBands").innerHTML = (data.score_bands || []).map(r => `
        <tr>
          <td data-label="區間">${esc(r.label)}</td>
          <td data-label="訊號">${esc(r.signals)}</td>
          <td data-label="完成">${esc(r.completed)}</td>
          <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
          <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
        </tr>
      `).join("");
      document.querySelector("#actionStats").innerHTML = (data.action_stats || []).length
        ? data.action_stats.map(r => `
          <tr>
            <td data-label="建議">${esc(r.label)}</td>
            <td data-label="訊號數">${esc(r.signals)}</td>
            <td data-label="完成數">${esc(r.completed)}</td>
            <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
            <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
          </tr>
        `).join("")
        : `<tr><td data-label="操作建議成效" colspan="5">尚無操作建議統計</td></tr>`;
      document.querySelector("#topThemes").innerHTML = (data.top_themes || []).length
        ? data.top_themes.map(r => `
          <tr>
            <td data-label="題材">${esc(r.label)}</td>
            <td data-label="完成數">${esc(r.completed)}</td>
            <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
            <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
            <td data-label="停損率">${fmtNeutralPct(r.stop_hit_rate)}</td>
          </tr>
        `).join("")
        : `<tr><td data-label="題材排行榜" colspan="5">尚無完成追蹤題材</td></tr>`;
      document.querySelector("#dataQuality").innerHTML = [
        ["訊號總數", quality.signals],
        ["5日完成", quality.completed_5d],
        ["5日待追蹤", quality.pending_5d],
        ["5日資料缺口", quality.data_missing_5d],
        ["5日完成率", quality.completion_rate_5d == null ? "—" : `${Number(quality.completion_rate_5d).toFixed(1)}%`],
        ["進場觸發樣本", quality.entry_trigger_known],
        ["進場觸發率", quality.entry_trigger_rate == null ? "—" : `${Number(quality.entry_trigger_rate).toFixed(1)}%`],
        ["停損樣本", quality.stop_known],
        ["停損率", quality.stop_hit_rate == null ? "—" : `${Number(quality.stop_hit_rate).toFixed(1)}%`],
      ].map(([label, value]) => `<tr><td data-label="項目">${esc(label)}</td><td data-label="數值">${esc(value ?? "—")}</td></tr>`).join("");
      if ((quality.pending_examples || []).length) {
        document.querySelector("#dataQuality").insertAdjacentHTML(
          "beforeend",
          `<tr><td data-label="項目">待追蹤範例</td><td data-label="數值">${quality.pending_examples.slice(0,4).map(x => `${esc(x.signal_date)} ${esc(x.stock_id)} ${esc(x.name)}`).join("<br>")}</td></tr>`
        );
      }
      if ((quality.missing_examples || []).length) {
        document.querySelector("#dataQuality").insertAdjacentHTML(
          "beforeend",
          `<tr><td data-label="項目">資料缺口範例</td><td data-label="數值">${quality.missing_examples.slice(0,4).map(x => `${esc(x.signal_date)} ${esc(x.stock_id)} ${esc(x.name)}`).join("<br>")}</td></tr>`
        );
      }
      const entry = data.entry_analysis || {};
      document.querySelector("#entryAnalysis").innerHTML = [
        ["有觸發進場", entry.triggered],
        ["未觸發進場", entry.not_triggered],
      ].map(([label, row]) => `
        <tr>
          <td data-label="類型">${esc(label)}</td>
          <td data-label="筆數">${esc(row?.count ?? 0)}</td>
          <td data-label="5日勝率">${fmtPct(row?.win_rate_5d)}</td>
          <td data-label="5日平均報酬">${fmtPct(row?.avg_return_5d)}</td>
        </tr>
      `).join("");
      document.querySelector("#signalLab").innerHTML = (data.signal_lab || []).map(r => `
        <tr>
          <td data-label="強度">${esc(r.grade)}</td>
          <td data-label="訊號">${esc(r.signals)}</td>
          <td data-label="3日勝率">${fmtPct(r.win_rate_3d)}</td>
          <td data-label="3日平均">${fmtPct(r.avg_return_3d)}</td>
          <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
          <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
          <td data-label="10日勝率">${fmtPct(r.win_rate_10d)}</td>
          <td data-label="10日平均">${fmtPct(r.avg_return_10d)}</td>
        </tr>
      `).join("");
      const segmentRow = r => `
        <tr>
          <td data-label="類型">${esc(r.group)}</td>
          <td data-label="區塊">${esc(r.label)}</td>
          <td data-label="樣本">${esc(r.completed)}</td>
          <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
          <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
        </tr>`;
      document.querySelector("#bestSegments").innerHTML = (data.backtest_insights?.best_segments || []).length
        ? data.backtest_insights.best_segments.slice(0,5).map(segmentRow).join("")
        : `<tr><td data-label="回測強項" colspan="5">樣本不足</td></tr>`;
      document.querySelector("#weakSegments").innerHTML = (data.backtest_insights?.weak_segments || []).length
        ? data.backtest_insights.weak_segments.slice(0,5).map(segmentRow).join("")
        : `<tr><td data-label="需檢討區塊" colspan="5">暫無負報酬區塊</td></tr>`;
      document.querySelector("#aiCouncilStats").innerHTML = (data.ai_council?.by_action || []).map(r => `
        <tr>
          <td data-label="AI 建議">${esc(r.action)}</td>
          <td data-label="訊號">${esc(r.signals)}</td>
          <td data-label="完成">${esc(r.completed)}</td>
          <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
          <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
          <td data-label="10日平均">${fmtPct(r.avg_return_10d)}</td>
        </tr>
      `).join("");
      const q = document.querySelector("#search").value.trim().toLowerCase();
      const grade = document.querySelector("#grade").value;
      const status = document.querySelector("#status").value;
      const rows = (data.items || []).filter(r => {
        const blob = JSON.stringify(r).toLowerCase();
        return (!q || blob.includes(q)) && (!grade || r.grade === grade) && (!status || r.status === status);
      });
      document.querySelector("#rows").innerHTML = rows.map(r => `
        <tr>
          <td data-label="訊號日">${esc(r.signal_date)}</td>
          <td data-label="股票"><a href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a><div class="small">${esc(r.status)}</div></td>
          <td data-label="強度">${esc(r.grade)}</td>
          <td data-label="分數">${esc(r.total_score)}/100</td>
          <td data-label="訊號價">${r.entry_price ?? "—"}</td>
          <td data-label="進場觸發">${fmtBool(r.entry_triggered)}</td>
          <td data-label="3日漲跌">${fmtPct(r.return_3d)}</td>
          <td data-label="5日漲跌">${fmtPct(r.return_5d)}${r.return_10d != null ? `<div class="small">10日 ${fmtPct(r.return_10d)}</div>` : ""}</td>
          <td data-label="停損觸及">${fmtBool(r.stop_hit)}</td>
        </tr>
      `).join("");
    }
    if (window.__PERFORMANCE_DATA__ && window.__PERFORMANCE_DATA__ !== null) {
      data = window.__PERFORMANCE_DATA__;
      render();
    } else {
      fetch("performance_data.json")
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(json => { data = json; render(); })
        .catch(err => {
          document.querySelector("#subtitle").textContent = "資料載入失敗";
          document.querySelector("#metrics").innerHTML = `<div class="metric"><b>錯誤</b><span>${esc(err.message)}</span></div>`;
        });
    }
    document.querySelector("#search").addEventListener("input", render);
    document.querySelector("#grade").addEventListener("change", render);
    document.querySelector("#status").addEventListener("change", render);
  </script>
</body>
</html>"""

