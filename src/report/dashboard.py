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


def _decision_reason(item: StockScore) -> str:
    parts = [item.trigger_summary]
    for key in ("technical", "chip", "fundamental", "risk", "opportunity"):
        reason = _first(item.reasons.get(key, []))
        if reason != "無明顯訊號" and reason not in parts:
            parts.append(reason)
        if len(parts) >= 4:
            break
    return "；".join(parts)


def _action_lists(rows: list[dict], ai_picks: list[dict] | None = None, exit_risks: list[dict] | None = None) -> dict:
    ai_ids = {str(item.get("stock_id")) for item in ai_picks or []}
    exit_ids = {str(item.get("stock_id")) for item in exit_risks or []}
    ranked = sorted(rows, key=lambda row: (int(row.get("score") or 0), str(row.get("stock_id") or "")), reverse=True)

    def _compact(row: dict, reason: str = "") -> dict:
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
            "themes": row.get("themes", []),
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
    ai_watch = [_compact(row, "AI 首選觀察") for row in ranked if str(row.get("stock_id")) in ai_ids][:5]
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
        "ai_watch": ai_watch,
        "risk": risk,
        "summary": {
            "chase": len(chase),
            "pullback": len(pullback),
            "ai_watch": len(ai_watch),
            "risk": len(risk),
        },
    }


def _data_recovery_status(details: list[dict]) -> dict:
    if not details:
        return {"label": "clean", "retryable": 0, "blocked": 0, "items": []}
    retryable = []
    blocked = []
    recovered = []
    for item in details:
        reason = str(item.get("reason") or "")
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
        label = "高"
    elif score >= 65:
        label = "中"
    else:
        label = "偏低"
    if score >= 85:
        label = "高"
    elif score >= 65:
        label = "中"
    else:
        label = "偏低"
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
    }


def _decision_summary(rows: list[dict], action_lists: dict, data_quality: dict, health: dict, theme_signal: ThemeSignal | None) -> dict:
    risk_count = int((action_lists.get("summary") or {}).get("risk") or 0)
    chase_count = int((action_lists.get("summary") or {}).get("chase") or 0)
    pullback_count = int((action_lists.get("summary") or {}).get("pullback") or 0)
    s_count = sum(1 for row in rows if row.get("grade") in {"S+", "S"})
    quality_label = str(data_quality.get("label") or "")
    health_label = str(health.get("label") or "")
    if health_label in {"甇?虜", "正常"} and quality_label in {"擃?", "高", "high"} and chase_count:
        posture = "active_watch"
    elif risk_count or quality_label in {"??", "偏低", "low"}:
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
        "telegram_schedule": "07:20 / 07:35 / 08:05",
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
    rows = []
    for item in sorted(scores, key=lambda score: score.total_score, reverse=True):
        rows.append(
            {
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
                "action": item.action or "只觀察",
                "entry_condition": item.entry_condition or "資料不足，暫不設進場條件",
                "stop_reference": item.stop_reference or "資料不足，暫不設停損參考",
                "stop_price": item.stop_price,
                "entry_limit_price": item.entry_limit_price,
                "themes": item.themes,
                "theme_tiers": item.theme_tiers,
                "entry_decision": item.entry_decision,
                "entry_checklist": item.entry_checklist,
                "overseas_adjustment": item.overseas_adjustment,
                "opportunity_score": item.opportunity_score,
                "warnings": item.warnings,
                "trigger_tags": item.trigger_tags,
                "trigger_summary": item.trigger_summary,
                "decision_reason": _decision_reason(item),
                "retail_signal": item.retail_signal,
                "selection_quality_adjustment": item.selection_quality_adjustment,
                "selection_quality_notes": item.selection_quality_notes,
            }
        )
    valid = [row for row in rows if row["label"] != "DATA_INSUFFICIENT"]
    action_lists = _action_lists(rows, ai_picks=ai_picks, exit_risks=exit_risks)
    data_quality = _data_quality(source_status, rows, ai_status=ai_status)
    health = _build_health_status(as_of, source_status, theme_signal)
    return {
        "as_of": as_of.isoformat(),
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
        },
        "source_status": source_status or {"label": "未知"},
        "health": health,
        "alerts": alerts or [],
        "watch_reviews": watch_reviews or [],
        "exit_risks": exit_risks or [],
        "retail_divergence": retail_divergence or empty_retail_divergence(as_of),
        "action_lists": action_lists,
        "data_quality": data_quality,
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
) -> dict:
    rows = payload.get("rows", [])
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
    (output_dir / "performance.html").write_text(html, encoding="utf-8")


def write_theme_history(payload: dict[str, list[dict]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "theme_history.json").write_text(json_text, encoding="utf-8")


def _html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 開盤前監控</title>
  <style>
    :root { color-scheme: light; --ink:#18202a; --muted:#667085; --line:#d9dee7; --bg:#f6f7f9; --panel:#fff; --good:#0f7b4f; --warn:#9a6700; --bad:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: "Segoe UI", Arial, sans-serif; color:var(--ink); background:var(--bg); }
    header { padding:20px 24px 12px; border-bottom:1px solid var(--line); background:var(--panel); }
    h1 { margin:0 0 8px; font-size:24px; letter-spacing:0; }
    .sub { color:var(--muted); font-size:14px; }
    main { padding:18px 24px 32px; max-width:1680px; margin:auto; }
    .metrics { display:grid; grid-template-columns: repeat(7, minmax(96px,1fr)); gap:8px; margin-bottom:14px; }
    .metric { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 11px; min-height:70px; }
    .metric b { display:block; font-size:clamp(17px, 4vw, 21px); margin-bottom:2px; overflow-wrap:anywhere; }
    .metric span { color:var(--muted); font-size:13px; }
    .dashboard-layout { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(380px,.85fr); gap:12px; margin-bottom:16px; align-items:start; }
    .main-stack, .side-stack { display:grid; gap:12px; }
    .detail-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; grid-column:1 / -1; }
    section, details.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }
    details.panel summary { cursor:pointer; font-weight:700; font-size:16px; list-style:none; }
    details.panel summary::-webkit-details-marker { display:none; }
    details.panel summary::after { content:"＋"; float:right; color:var(--muted); }
    details.panel[open] summary::after { content:"－"; }
    .section-note { color:var(--muted); font-size:12px; margin-top:-4px; margin-bottom:8px; }
    .status-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px; }
    .action-panel { border-left:4px solid var(--good); }
    .decision-card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin:8px 0 10px; }
    .decision-card { border:1px solid var(--line); border-radius:8px; padding:10px; background:#fff; }
    .decision-card.chase { border-left:4px solid var(--good); }
    .decision-card.pullback { border-left:4px solid var(--warn); }
    .decision-card.avoid { border-left:4px solid var(--bad); }
    .decision-card-head { display:flex; gap:8px; justify-content:space-between; align-items:flex-start; }
    .decision-card-title { font-weight:800; line-height:1.25; }
    .decision-badge { display:inline-flex; align-items:center; min-height:22px; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:800; white-space:nowrap; }
    .decision-badge.chase { color:#fff; background:var(--good); }
    .decision-badge.pullback { color:#3b2f00; background:#f6d365; }
    .decision-badge.avoid { color:#fff; background:var(--bad); }
    .decision-prices { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin:8px 0; }
    .decision-price { border:1px solid #eef1f5; border-radius:6px; padding:6px; min-height:48px; }
    .decision-price span { display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
    .decision-price b { font-size:15px; }
    .decision-reason { color:var(--muted); font-size:12px; line-height:1.45; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    .risk-panel { border-left:4px solid var(--bad); }
    .wide-panel { grid-column:1 / -1; }
    details.panel h2 { font-size:14px; margin:12px 0 6px; }
    h2 { font-size:16px; margin:0 0 10px; }
    .line { color:var(--muted); margin:5px 0; font-size:14px; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:14px 0; flex-wrap:wrap; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:8px 14px; border:1px solid var(--line); border-radius:6px; background:var(--panel); color:#0b4a8b; text-decoration:none; font-weight:700; }
    .nav-tab.active { background:#0b4a8b; color:white; border-color:#0b4a8b; }
    input, select { border:1px solid var(--line); border-radius:6px; padding:9px 10px; background:white; min-height:38px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .chart-wrap { height:130px; margin-top:8px; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; font-size:12px; color:#475467; }
    .grade { font-weight:700; border-radius:999px; padding:3px 8px; display:inline-block; min-width:32px; text-align:center; }
    .grade-S\+ { color:white; background:#7c2d12; }
    .grade-S { color:white; background:#b42318; }
    .grade-A { color:white; background:var(--good); }
    .grade-B { color:#3b2f00; background:#f6d365; }
    .grade-C { color:#344054; background:#e4e7ec; }
    .grade-- { color:#667085; background:#f2f4f7; }
    .small { color:var(--muted); font-size:12px; margin-top:3px; }
    .themes { color:#175cd3; }
    a.stock-link { color:#0b4a8b; text-decoration:none; }
    a.stock-link:hover { text-decoration:underline; }
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
    .tag-default{ background:#f8fafc; color:#475467; border:1px solid #e2e8f0; }
    .theme-table-wrap { max-height:178px; overflow:auto; border:1px solid var(--line); border-radius:6px; margin:6px 0; }
    .theme-table-wrap table { border:0; border-radius:0; }
    .theme-reason, .theme-headline { font-size:12px; line-height:1.45; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
    .mini-detail { margin-top:6px; }
    .mini-detail summary { cursor:pointer; color:#0b4a8b; font-size:13px; font-weight:700; }
    .row-detail summary { cursor:pointer; color:#0b4a8b; font-size:12px; font-weight:700; }
    .row-detail[open] { margin-top:4px; }
    @media (max-width: 1180px) {
      .metrics { grid-template-columns: repeat(4, minmax(0,1fr)); }
      .dashboard-layout { grid-template-columns:1fr; }
      .detail-grid { grid-template-columns:1fr 1fr; }
      .decision-card-grid { grid-template-columns:1fr; }
    }
    @media (max-width: 900px) {
      header { position:static; }
      main, header { padding-left:12px; padding-right:12px; }
      .metrics { grid-template-columns:1fr 1fr; }
      .dashboard-layout, .detail-grid, .status-grid { grid-template-columns:1fr; }
      .decision-prices { grid-template-columns:1fr 1fr; }
      .toolbar { align-items:stretch; }
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
<body>
  <header>
    <h1>台股 AI 開盤前監控</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab active" href="index.html">今日監控</a>
      <a class="nav-tab" href="performance.html">訊號成效</a>
    </nav>
    <div class="metrics" id="metrics"></div>
    <div class="dashboard-layout">
      <div class="main-stack">
        <section class="action-panel"><h2>今日操作結論</h2><div id="actionLists"></div></section>
        <section><h2>市場風向</h2><div id="market"></div></section>
        <section class="theme-panel"><h2>新聞題材</h2><div id="themes"></div></section>
      </div>
      <div class="side-stack">
        <section><h2>今日決策</h2><div id="decisionSummary"></div></section>
        <section class="risk-panel"><h2>危險名單</h2><div id="exitRisks"></div></section>
        <section><h2>AI 自選股</h2><div id="aiCouncil"></div></section>
      </div>
      <div class="detail-grid">
        <section><h2>異常提醒</h2><div id="alerts"></div></section>
        <section><h2>散戶背離</h2><div id="retailDivergence"></div></section>
        <section><h2>美國政策雷達</h2><div id="usPolicyRadar"></div></section>
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
    <div class="toolbar">
      <input id="search" placeholder="搜尋股票、題材、訊號..." />
      <select id="grade"><option value="">全部強度</option><option>S+</option><option>S</option><option>A</option><option>B</option><option>C</option><option value="-">資料不足</option></select>
    </div>
    <table>
      <thead><tr><th>強度</th><th>股票</th><th>分數</th><th>原因標籤</th><th>題材</th><th>四面向</th><th>操作</th><th>進場/停損</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
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
          <option value="risk">風險警示</option>
          <option value="ai">AI 共識</option>
          <option value="new">今日新增</option>
          <option value="top_theme">主題焦點</option>
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
      document.querySelector("#metrics").innerHTML = [
        ["掃描", data.summary.scanned],
        ["有效", data.summary.valid],
        ["S+強度", data.summary.s_plus_grade || 0],
        ["S強度", data.summary.s_grade || 0],
        ["A強度", data.summary.a_grade],
        ["B強度", data.summary.b_grade],
        ["資料不足", data.summary.data_insufficient]
      ].map(([k,v]) => `<div class="metric"><b>${v}</b><span>${k}</span></div>`).join("");
      const decision = data.decision_summary || {};
      const postureText = {
        active_watch: "積極觀察",
        selective_watch: "精選觀察",
        risk_control: "風險控管",
      }[decision.posture] || "精選觀察";
      const decisionTopTheme = themeName(decision.top_theme);
      document.querySelector("#decisionSummary").innerHTML = `
        <div class="line"><b>${esc(postureText)}</b></div>
        <div class="line">觀察 ${esc(decision.watch_count ?? 0)}｜拉回 ${esc(decision.pullback_count ?? 0)}｜風險 ${esc(decision.risk_count ?? 0)}</div>
        <div class="line">強勢訊號 ${esc(decision.strong_grade_count ?? 0)}｜資料品質 ${esc(zh(QUALITY_TEXT, decision.data_quality, "-"))}</div>
        <div class="line">主題焦點：${esc(decisionTopTheme)}</div>`;
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
        return `<article class="decision-card ${mode}">
          <div class="decision-card-head">
            <div>
              <div class="decision-card-title">${stockLink}</div>
              <div class="small">${esc(row.score ?? "-")}/100｜${esc(row.grade || "-")}${row.entry_decision ? `｜${esc(row.entry_decision)}` : ""}</div>
            </div>
            <span class="decision-badge ${mode}">${badgeText}</span>
          </div>
          <div class="decision-prices">
            <div class="decision-price"><span>進場上限</span><b>${esc(priceText(row.entry_limit_price))}</b></div>
            <div class="decision-price"><span>停損參考</span><b class="${row.stop_price != null ? "bad" : ""}">${esc(priceText(row.stop_price))}</b></div>
          </div>
          <div class="decision-reason">${esc(reason)}</div>
        </article>`;
      }
      const actionLists = data.action_lists || {};
      const chaseCards = (actionLists.chase || []).slice(0, 4).map(row => decisionCard(row, "chase")).join("");
      const pullbackCards = (actionLists.pullback || []).slice(0, 2).map(row => decisionCard(row, "pullback")).join("");
      document.querySelector("#actionLists").innerHTML = `
        <div class="line">S+/S/A/B 是訊號強度，不等於直接買；今日是否進場以操作結論、開盤跳空與量能確認為準。</div>
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
        <div class="line warn"><b>散戶過熱</b>：${esc(retailSummary.overheated ?? 0)} 檔</div>
        ${(retail.overheated || []).slice(0,3).map(compactRetail).join("") || '<div class="line">尚未累積散戶過熱名單</div>'}`;
      const quality = data.data_quality || {};
      const qualityCls = (quality.label === "high" || quality.label === "高") ? "good" : (quality.label === "medium" || quality.label === "中") ? "warn" : "bad";
      const retry = data.data_retry || {};
      const retryCounts = retry.status_counts || {};
      const retryLines = (retry.items || []).slice(0,3).map(x =>
        `<div class="line small">${esc(zh(RETRY_STATUS_TEXT, x.status))}｜${esc(zh(DATASET_TEXT, x.dataset))}｜${esc(x.data_id)}｜${esc(x.period || "-")}｜${esc(x.attempts || 0)} 次${x.last_error ? `｜${esc(x.last_error)}` : ""}</div>`
      ).join("");
      document.querySelector("#dataQuality").innerHTML = `
        <div class="line ${qualityCls}"><b>${esc(quality.label_text || zh(QUALITY_TEXT, quality.label, "未知"))}</b>｜${esc(quality.score ?? "—")}/100</div>
        <div class="line">資料源 ${esc(quality.source_score ?? "—")}/100｜覆蓋率 ${esc(quality.coverage ?? "—")}%</div>
        ${(quality.warnings || []).length ? quality.warnings.slice(0,3).map(w => `<div class="line warn">- ${esc(w)}</div>`).join("") : '<div class="line">目前無重大資料品質警示</div>'}
        ${(quality.details || []).length ? '<div class="line"><b>明細</b></div>' + quality.details.slice(0,4).map(x => `<div class="line small">${esc(zh(EVENT_TYPE_TEXT, x.type))}｜${esc(zh(DATASET_TEXT, x.dataset))}｜${esc(x.data_id)}｜${esc(zh(REASON_TEXT, x.reason || x.period || "-"))}</div>`).join("") : ""}
        <div class="line"><b>補抓佇列</b>：待補 ${esc(retry.pending || retryCounts.pending || 0)}｜已補 ${esc(retry.recovered || retryCounts.recovered || 0)}｜失敗 ${esc(retry.failed || retryCounts.failed || 0)}</div>
        ${retryLines}`;
      const recovery = quality.recovery_status || {};
      if (recovery.label && recovery.label !== "clean") {
        document.querySelector("#dataQuality").insertAdjacentHTML("beforeend",
          `<div class="line warn">補抓狀態：${esc(zh(RECOVERY_TEXT, recovery.label))}｜可補抓 ${esc(recovery.retryable || 0)}｜暫停 ${esc(recovery.blocked || 0)}</div>`);
      }
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
      document.querySelector("#themes").innerHTML = `
        <div class="line">熱門：${esc(data.themes.summary)}</div>
        <div class="line">政策：${esc(data.themes.policy?.summary || "未偵測到明顯政策訊號")}</div>
        <div class="chart-wrap"><canvas id="themeHistoryChart" aria-label="題材熱度歷史圖"></canvas></div>
        ${themeTableHtml}
        <details class="mini-detail">
          <summary>新聞來源摘要</summary>
          ${themeReasons}
          ${data.themes.headlines.slice(0,2).map(h => `<div class="line theme-headline">- ${esc(h)}</div>`).join("")}
        </details>`;
      const ai = data.ai_council || {};
      const aiPicks = ai.picks || [];
      const aiStatus = ai.status || {};
      const aiRequiredModels = ai.min_model_count || ai.min_agree_count || 5;
      const aiRequiredVotes = ai.min_agree_count || 5;
      const aiAvailability = aiStatus.requested_models
        ? `<div class="line">AI 可用率：${esc(aiStatus.successful_models || 0)}/${esc(aiStatus.requested_models || 0)} 模型成功${(aiStatus.failed_models || []).length ? `｜限流/失敗 ${esc((aiStatus.failed_models || []).length)}` : ""}${(aiStatus.timed_out_models || []).length ? `｜逾時 ${esc((aiStatus.timed_out_models || []).length)}` : ""}</div>`
        : "";
      const aiFallbackNote = ai.using_fallback_picks
        ? `<div class="line warn">未達 ${esc(aiRequiredModels)} 模型參與 / ${esc(aiRequiredVotes)} 票強共識，先顯示 AI 首選觀察</div>`
        : "";
      document.querySelector("#aiCouncil").innerHTML = aiPicks.length
        ? aiFallbackNote + aiPicks.slice(0,5).map(r => `<div class="line"><b>${esc(r.stock_id)} ${esc(r.name)}</b>｜${esc(r.consensus_action)}｜${esc(r.model_count || 0)} 模型參與｜${esc(r.pick_agreement_count || r.agreement_count || 0)}/${esc(aiRequiredVotes)} 票同意<div class="small">${esc(r.reason || "")}</div></div>`).join("")
        : `<div class="line">${ai.enabled ? `今日沒有達到 ${esc(aiRequiredModels)} 模型參與且 ${esc(aiRequiredVotes)} 票同意的 AI 自選股` : "未啟用，待設定 OPENROUTER_API_KEY 後啟用"}</div>`;
      if (aiAvailability) document.querySelector("#aiCouncil").insertAdjacentHTML("afterbegin", aiAvailability);
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
      const aiIds = new Set((data.action_lists?.ai_watch || []).map(x => String(x.stock_id)));
      const riskIds = new Set((data.exit_risks || []).map(x => String(x.stock_id)));
      const topTheme = data.decision_summary?.top_theme || "";
      const rows = data.rows.filter(r => {
        const blob = JSON.stringify(r).toLowerCase();
        const action = String(r.action || "");
        const quickOk =
          !quick ||
          (quick === "strong" && ["S+", "S"].includes(r.grade)) ||
          (quick === "chase" && action.includes("追")) ||
          (quick === "risk" && riskIds.has(String(r.stock_id))) ||
          (quick === "ai" && aiIds.has(String(r.stock_id))) ||
          (quick === "new" && String(data.as_of || "") === String(r.signal_date || data.as_of || "")) ||
          (quick === "top_theme" && (r.themes || []).includes(topTheme));
        return quickOk && (!q || blob.includes(q)) && (!g || r.grade === g);
      });
      document.querySelector("#rows").innerHTML = rows.map(r => `
        <tr>
          <td data-label="強度"><span class="${cls(r.grade)}">${r.grade}</span></td>
          <td data-label="股票"><b><a class="stock-link" href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a></b><div class="small">${esc(r.label_text)}｜收 ${r.price ?? "-"}</div></td>
          <td data-label="分數"><b>${r.score}/100</b><div class="small">海外 ${r.overseas_adjustment >= 0 ? "+" : ""}${r.overseas_adjustment}｜機會 ${r.opportunity_score}</div></td>
          <td data-label="原因標籤"><div class="tags">${renderTags(r.trigger_tags)}</div></td>
          <td data-label="題材" class="themes">${esc((r.theme_tiers || []).join(" / ") || (r.themes || []).join(" / ") || "-")}</td>
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
          <td data-label="操作"><b>${esc(r.entry_decision || r.action || "只觀察")}</b><div class="small">${esc(r.action || "")}</div></td>
          <td data-label="進場/停損">
            ${r.entry_limit_price != null ? `<div><b>📌 進場上限：${r.entry_limit_price}</b></div>` : ""}
            ${r.stop_price != null ? `<div style="color:var(--bad)"><b>🔴 止損：${r.stop_price}</b></div>` : ""}
            <details class="row-detail">
              <summary>進出場條件</summary>
              ${(r.entry_checklist || []).slice(0,3).map(x => `<div class="small">□ ${esc(x)}</div>`).join("")}
              <div class="small">${esc(r.entry_condition || "資料不足，暫不設進場條件")}</div>
              <div class="small">${esc(r.stop_reference || "資料不足，暫不設停損參考")}</div>
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


def _performance_html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 訊號成效追蹤</title>
  <style>
    :root { color-scheme: light; --ink:#18202a; --muted:#667085; --line:#d9dee7; --bg:#f6f7f9; --panel:#fff; --good:#0f7b4f; --bad:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Segoe UI", Arial, sans-serif; color:var(--ink); background:var(--bg); }
    header { padding:20px 24px 12px; border-bottom:1px solid var(--line); background:var(--panel); }
    h1 { margin:0 0 8px; font-size:24px; }
    .sub, .small { color:var(--muted); font-size:13px; }
    main { padding:18px 24px 32px; max-width:1320px; margin:auto; }
    .metrics { display:grid; grid-template-columns:repeat(6,minmax(120px,1fr)); gap:10px; margin-bottom:16px; }
    .metric { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }
    .metric b { display:block; font-size:clamp(18px, 4vw, 22px); margin-bottom:2px; overflow-wrap:anywhere; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:14px 0; flex-wrap:wrap; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:8px 14px; border:1px solid var(--line); border-radius:6px; background:var(--panel); color:#0b4a8b; text-decoration:none; font-weight:700; }
    .nav-tab.active { background:#0b4a8b; color:white; border-color:#0b4a8b; }
    input, select { border:1px solid var(--line); border-radius:6px; padding:9px 10px; background:white; min-height:38px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .analysis-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }
    h2 { font-size:16px; margin:0 0 8px; }
    .note { color:var(--muted); font-size:12px; margin:0 0 10px; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; font-size:12px; color:#475467; }
    a { color:#0b4a8b; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .pos { color:var(--good); font-weight:700; }
    .neg { color:var(--bad); font-weight:700; }
    @media (max-width:1100px) {
      .metrics { grid-template-columns:repeat(3,1fr); }
    }
    @media (max-width:900px) {
      main, header { padding-left:12px; padding-right:12px; }
      .metrics { grid-template-columns:1fr 1fr; }
      .analysis-grid { grid-template-columns:1fr; }
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
<body>
  <header>
    <h1>台股 AI 訊號成效追蹤</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab" href="index.html">今日監控</a>
      <a class="nav-tab active" href="performance.html">訊號成效</a>
    </nav>
    <div class="metrics" id="metrics"></div>
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
    function render() {
      const stats = data.stats || {};
      const quality = data.data_quality || {};
      document.querySelector("#subtitle").textContent = `${data.as_of}｜近 ${data.days} 天｜僅供研究追蹤`;
      document.querySelector("#metrics").innerHTML = [
        metric("訊號總數", stats.signals),
        metric("已完成", stats.completed),
        metric("5日勝率", stats.win_rate_5d?.toFixed(1), "%"),
        metric("5日平均", stats.avg_return_5d?.toFixed(1), "%"),
        `<div class="metric" title="訊號發出後 5 日內，股價觸及或跌破預設止損價的比率。越低代表止損設定越合理、訊號品質越佳。"><b>${stats.stop_hit_rate?.toFixed(1) ?? "—"}${stats.stop_hit_rate != null ? "%" : ""}</b><span>停損觸及率</span><div style="color:var(--muted);font-size:11px;margin-top:2px;">↓ 越低越好</div></div>`,
        metric("A級5日勝率", stats.a_win_rate_5d?.toFixed(1), "%"),
      ].join("");
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
