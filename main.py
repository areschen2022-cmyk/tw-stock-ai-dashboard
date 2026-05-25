from __future__ import annotations

import argparse
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.ai.model_council import run_ai_council, select_ai_picks
from src.config_loader import load_yaml, merge_theme_database
from src.data_provider.finmind_client import FinMindClient
from src.data_provider.mock_data import MockDataProvider
from src.data_provider.retry_queue import run_retry_queue
from src.data_provider.twse_client import TwseClient
from src.indicators.market import sector_context
from src.indicators.overseas import analyze_overseas_sentiment
from src.indicators.opportunity import opportunity_score
from src.notifier.telegram import TelegramNotifier
from src.news.web_theme import fetch_theme_signal
from src.report.dashboard import build_dashboard_payload, enrich_dashboard_payload, write_dashboard, write_performance, write_theme_history
from src.report.exit_risk import build_exit_risks
from src.report.monitoring import detect_alerts, format_watch_reviews
from src.report.report_builder import build_report
from src.scoring.score_engine import ScoreEngine
from src.storage.sqlite_store import SQLiteStore


ROOT = Path(__file__).resolve().parent
TAIPEI = ZoneInfo("Asia/Taipei")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Taiwan stock AI screener MVP")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Print notification instead of sending Telegram")
    parser.add_argument("--send-telegram", action="store_true", help="Force real Telegram delivery")
    parser.add_argument("--telegram-summary", action="store_true", help="Send a short Telegram summary instead of full report")
    parser.add_argument("--mock-data", action="store_true", help="Use deterministic local mock data")
    parser.add_argument("--as-of-date", help="Override analysis date, format YYYY-MM-DD")
    return parser.parse_args()


def load_config(path: str) -> dict:
    config = load_yaml(path)
    return merge_theme_database(config, ROOT)


def load_sector_map() -> dict:
    path = ROOT / "config" / "sector_map.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("sector_map.json is invalid; overseas sector mapping disabled")
        return {}


def _previous_weekday(value: date) -> date:
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def default_as_of(now: datetime | None = None) -> date:
    local_now = now.astimezone(TAIPEI) if now else datetime.now(TAIPEI)
    candidate = local_now.date()
    if local_now.weekday() >= 5 or local_now.time() < time(14, 30):
        candidate -= timedelta(days=1)
    return _previous_weekday(candidate)


def resolve_as_of(config: dict, cli_value: str | None) -> date:
    value = cli_value or config.get("runtime", {}).get("as_of_date")
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return default_as_of()


def delivery_date_for_run(now: datetime | None = None) -> date:
    """Return the calendar date this notification run is responsible for."""
    target = os.getenv("SCHEDULED_TARGET_TAIPEI", "").strip()
    if target:
        try:
            parsed = datetime.fromisoformat(target.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=TAIPEI)
            return parsed.astimezone(TAIPEI).date()
        except ValueError:
            logging.warning("Invalid SCHEDULED_TARGET_TAIPEI=%r; using current Taipei date.", target)
    local_now = now.astimezone(TAIPEI) if now else datetime.now(TAIPEI)
    return local_now.date()


def select_theme_pools(theme_pools: dict, active_theme_keys: set[str]) -> dict:
    if not active_theme_keys:
        return {}
    return {key: value for key, value in theme_pools.items() if key in active_theme_keys}


def _zh_posture(value: str) -> str:
    return {
        "active_watch": "積極觀察",
        "selective_watch": "精選觀察",
        "risk_control": "風險控管",
    }.get(value, value)


def _zh_policy_event(value: object) -> str:
    return {
        "Trump tariff / China tariff": "川普/中國關稅",
        "AI chip export control": "AI晶片出口管制",
        "House / Senate China bill": "美國國會對中法案",
        "Defense bill / NDAA": "國防授權法案/NDAA",
        "SpaceX / Starlink": "SpaceX/Starlink",
        "Data center power": "資料中心電力",
        "AI capex / hyperscaler": "AI資本支出/雲端大廠",
    }.get(str(value or ""), str(value or ""))


def _zh_policy_level(value: object) -> str:
    return {
        "high": "高敏感",
        "medium": "中敏感",
        "low": "低敏感",
        "confirmed": "已確認",
        "signal": "訊號",
        "watch": "觀察",
        "bullish": "利多",
        "risk": "風險",
        "mixed": "多空交錯",
    }.get(str(value or ""), str(value or ""))


def _zh_data_event(value: object) -> str:
    return {
        "fallback": "備援資料",
        "empty": "空資料",
        "error": "抓取失敗",
        "quota": "限流",
    }.get(str(value or ""), str(value or ""))


def _zh_dataset(value: object) -> str:
    return {
        "STOCK_DAY": "個股月成交",
        "stock_prices": "股價序列",
        "STOCK_DAY_ALL": "全市場日成交",
    }.get(str(value or ""), str(value or ""))


def _zh_data_reason(value: object) -> str:
    return {
        "html": "TWSE 回傳網頁非資料",
        "fetch_failed": "抓取失敗",
        "twse_month_missing": "TWSE 月資料缺口",
        "empty_after_retry": "補抓後仍無資料",
    }.get(str(value or ""), str(value or ""))


def main() -> int:
    load_dotenv(ROOT / ".env")
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "data").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(ROOT / "logs" / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    args = parse_args()
    config = load_config(args.config)
    sector_map = load_sector_map()

    as_of = resolve_as_of(config, args.as_of_date)
    start_date = as_of - timedelta(days=int(config["data"]["lookback_days"]))
    use_mock = args.mock_data or bool(config.get("runtime", {}).get("use_mock_data", False))
    dry_run = False if args.send_telegram else args.dry_run or bool(config.get("runtime", {}).get("dry_run", True))

    data_provider = str(config.get("runtime", {}).get("data_provider", "finmind")).lower()
    if use_mock:
        provider = MockDataProvider(as_of=as_of)
    elif data_provider == "twse":
        provider = TwseClient(fallback=FinMindClient())
    else:
        provider = FinMindClient()
    store = SQLiteStore(ROOT / "data" / "tw_stock_ai.sqlite3")
    delivery_date = delivery_date_for_run()
    if args.send_telegram and not dry_run and store.has_delivered_today("telegram", delivery_date, "morning_report"):
        logging.info("Telegram morning report already delivered for run date %s; skipping.", delivery_date)
        return 0
    engine = ScoreEngine(config)

    market_prices = provider.stock_prices(config["market"]["index_id"], start_date, as_of)
    market_adjustment, market_summary, market_warning = engine.market_adjustment(market_prices)

    # 類股指數今日漲跌（TWSE OpenAPI MI_INDEX）
    sector_ctx = ""
    if hasattr(provider, "sector_indices_today"):
        try:
            sector_df = provider.sector_indices_today()
            sector_ctx = sector_context(sector_df)
        except Exception:
            pass
    if sector_ctx:
        market_summary = f"{market_summary}｜{sector_ctx}"

    overseas = None
    if config.get("overseas", {}).get("enabled", False):
        overseas = analyze_overseas_sentiment(provider.overseas_bundle(start_date, as_of), sector_map=sector_map)
    theme_signal = fetch_theme_signal(config, store=store, as_of=as_of)

    results = []
    semiconductor_sensitive = set(config.get("overseas", {}).get("semiconductor_sensitive", []))
    stock_themes: dict[str, list[str]] = {stock_id: [] for stock_id in config["stocks"]}
    stock_theme_details: dict[str, list[dict]] = {stock_id: [] for stock_id in config["stocks"]}
    theme_stock_meta = config.get("theme_stock_meta", {})
    theme_pools = config.get("theme_pools", {})
    active_theme_keys = set(theme_signal.active_themes) if theme_signal and theme_signal.active_themes else set()
    selected_theme_pools = select_theme_pools(theme_pools, active_theme_keys)
    for theme_key, theme_cfg in selected_theme_pools.items():
        theme_name = theme_cfg.get("name", "題材")
        for stock_id in theme_cfg.get("stocks", {}):
            stock_themes.setdefault(stock_id, []).append(theme_name)
            meta = theme_stock_meta.get(stock_id, {}).get(theme_key)
            if meta:
                stock_theme_details.setdefault(stock_id, []).append(meta)

    all_stock_ids = list(dict.fromkeys([*config["stocks"], *stock_themes.keys()]))
    core_ids = set(config["stocks"])
    bundles = {}
    max_workers = int(config.get("runtime", {}).get("fetch_workers", 3))
    max_workers = max(1, min(max_workers, 6))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(provider.stock_bundle, stock_id, start_date, as_of, stock_id in core_ids): stock_id
            for stock_id in all_stock_ids
        }
        for future in as_completed(futures):
            stock_id = futures[future]
            bundles[stock_id] = future.result()

    for stock_id in all_stock_ids:
        bundle = bundles[stock_id]
        overseas_adj = 0
        if overseas:
            overseas_adj = overseas.adjustment
            if stock_id in semiconductor_sensitive:
                overseas_adj += overseas.semiconductor_adjustment
            overseas_adj += (overseas.stock_adjustments or {}).get(stock_id, 0)
        opp_adj = 0
        opp_reasons: list[str] = []
        if config.get("opportunity", {}).get("enabled", False):
            opp_adj, opp_reasons = opportunity_score(
                bundle,
                stock_themes.get(stock_id, []),
                stock_theme_details.get(stock_id, []),
            )
        score = engine.score_stock(
            stock_id,
            bundle,
            market_adjustment,
            as_of,
            overseas_adj=overseas_adj,
            opportunity_adj=opp_adj,
            opportunity_reasons=opp_reasons,
            themes=stock_themes.get(stock_id, []),
            theme_tiers=[
                f"{item.get('theme_name', '題材')}:{item.get('tier_label', item.get('tier', '受惠'))}"
                for item in stock_theme_details.get(stock_id, [])
            ],
        )
        results.append(score)
        store.save_daily_score(score, as_of)
        store.save_institutional_flow(stock_id, bundle.get("institutional"))

    source_status = provider.source_status()
    watch_reviews = store.watch_reviews(as_of)
    exit_risks = build_exit_risks(
        results,
        bundles,
        as_of,
        store,
        config.get("stock_names", {}),
        config,
    )
    alerts = detect_alerts(
        results,
        as_of,
        store,
        source_status,
        overseas,
        theme_signal,
        {key: value.get("name", key) for key, value in config.get("theme_pools", {}).items()},
    )
    store.save_watch_candidates(results, as_of, config.get("stock_names", {}))
    store.update_forward_returns(as_of)

    report = build_report(
        results,
        as_of,
        market_summary,
        market_warning,
        config,
        overseas=overseas,
        theme_signal=theme_signal,
    )
    dashboard_payload = build_dashboard_payload(
        results,
        as_of,
        market_summary,
        market_warning,
        config,
        overseas,
        theme_signal,
        source_status,
        alerts,
        watch_reviews,
        exit_risks,
    )
    ai_status = {}
    ai_reviews = run_ai_council(
        [row for row in dashboard_payload["rows"] if row["grade"] in {"S+", "S", "A"}],
        as_of,
        config,
        store=store,
        status_out=ai_status,
    )
    store.save_ai_council_reviews(ai_reviews, as_of)
    store.update_forward_returns(as_of)
    ai_cfg = config.get("ai_council", {})
    ai_min_agree_count = int(ai_cfg.get("min_agree_count", 5))
    ai_min_model_count = int(ai_cfg.get("min_model_count", ai_min_agree_count))
    ai_pick_action = str(ai_cfg.get("pick_action", "可追"))
    ai_fallback_count = int(ai_cfg.get("fallback_pick_count", 3))
    ai_picks, ai_using_fallback = select_ai_picks(
        ai_reviews,
        min_agree_count=ai_min_agree_count,
        min_model_count=ai_min_model_count,
        pick_action=ai_pick_action,
        fallback_count=ai_fallback_count,
    )
    dashboard_payload["ai_council"] = {
        "enabled": bool(ai_cfg.get("enabled", False)),
        "reviews": ai_reviews,
        "picks": ai_picks,
        "using_fallback_picks": ai_using_fallback,
        "status": ai_status,
        "min_agree_count": ai_min_agree_count,
        "min_model_count": ai_min_model_count,
        "fallback_pick_count": ai_fallback_count,
        "pick_action": ai_pick_action,
    }
    enrich_dashboard_payload(
        dashboard_payload,
        source_status=source_status,
        ai_picks=ai_picks,
        ai_status=ai_status,
        exit_risks=exit_risks,
    )
    retry_cfg = config.get("data_retry", {})
    if retry_cfg.get("enabled", True):
        store.enqueue_data_retry((dashboard_payload.get("data_quality") or {}).get("details", []))
        dashboard_payload["data_retry"] = run_retry_queue(
            provider,
            store,
            as_of=as_of,
            lookback_start=start_date,
            limit=int(retry_cfg.get("limit", 8)),
        )
    else:
        dashboard_payload["data_retry"] = store.retry_queue_summary()
    enrich_dashboard_payload(
        dashboard_payload,
        source_status=source_status,
        ai_picks=ai_picks,
        ai_status=ai_status,
        exit_risks=exit_risks,
        retry_summary=dashboard_payload.get("data_retry", {}),
    )
    write_dashboard(dashboard_payload, ROOT / "dashboard")
    performance_payload = store.performance_summary(as_of, days=30)
    write_performance(performance_payload, ROOT / "dashboard")
    write_theme_history(
        store.all_theme_history(list(config.get("theme_pools", {}).keys()), days=30),
        ROOT / "dashboard",
    )
    telegram_message = report
    if args.telegram_summary:
        s = dashboard_payload["summary"]
        action_lists = dashboard_payload.get("action_lists", {})
        data_quality = dashboard_payload.get("data_quality", {})
        data_retry = dashboard_payload.get("data_retry", {})
        ai_health = dashboard_payload.get("ai_council", {}).get("status", {}).get("health", {})
        decision = dashboard_payload.get("decision_summary", {})
        us_events = dashboard_payload.get("themes", {}).get("policy", {}).get("us_events", [])

        def _entry_line(row: dict) -> str:
            action = row.get("entry_decision") or row.get("action", "只觀察")
            limit = row.get("entry_limit_price")
            stop = row.get("stop_price")
            limit_str = f"上限 {limit:.2f}" if limit else ""
            stop_str = f"止損 {stop:.2f}" if stop else ""
            numbers = "｜".join(x for x in [limit_str, stop_str] if x)
            checks = "；".join((row.get("entry_checklist") or [])[:2])
            return f"{action}" + (f"（{numbers}）" if numbers else "") + (f"\n  □ {checks}" if checks else "")

        def _fmt_perf_pct(value: object, signed: bool = False) -> str:
            if value is None:
                return "—"
            numeric = float(value)
            sign = "+" if signed and numeric > 0 else ""
            return f"{sign}{numeric:.1f}%"

        def _list_text(rows: list[dict], empty: str, limit: int = 3) -> str:
            return "\n".join(
                f"▸ <b>{row['stock_id']} {row['name']}</b>｜{row.get('score', row.get('risk_score', 0))}/100｜{row.get('grade', row.get('level', '-'))}\n"
                f"  📌 {row.get('reason') or row.get('trigger_summary') or ''}\n"
                f"  🎯 {_entry_line(row) if row.get('entry_limit_price') or row.get('stop_price') else row.get('action', '')}"
                for row in rows[:limit]
            ) or empty

        must_watch_text = _list_text(action_lists.get("chase", []), "▸ 今日暫無高分可追清單")
        ai_watch_text = _list_text(action_lists.get("ai_watch", []), "▸ AI 暫無首選觀察")
        pullback_text = _list_text(action_lists.get("pullback", []), "▸ 今日暫無等拉回清單", limit=2)
        alert_text = "\n".join(f"⚠️ {item}" for item in alerts[:3]) or "✅ 目前無重大異常"
        review_lines = format_watch_reviews(watch_reviews)
        review_text = "\n".join(f"▸ {item}" for item in review_lines) or "▸ 尚無可追蹤觀察"
        exit_text = "\n".join(
            f"▸ <b>{item['stock_id']} {item['name']}</b>｜{item['level']}｜危險分 {item.get('risk_score', 0)}｜{'、'.join(item['reasons'][:2])}"
            for item in exit_risks[:3]
        ) or "▸ 目前無紅黃警戒"
        perf_stats = performance_payload.get("stats", {})
        perf_quality = performance_payload.get("data_quality", {})
        top_signal = (performance_payload.get("leaderboard", {}).get("top_5d") or [None])[0]
        perf_text = (
            f"近30日：{perf_stats.get('completed', 0)}/{perf_stats.get('signals', 0)} 已完成｜"
            f"5日勝率 {_fmt_perf_pct(perf_stats.get('win_rate_5d'))}｜"
            f"平均 {_fmt_perf_pct(perf_stats.get('avg_return_5d'), signed=True)}｜"
            f"完成率 {_fmt_perf_pct(perf_quality.get('completion_rate_5d'))}"
        )
        if top_signal:
            perf_text += (
                f"\n▸ 最佳：<b>{top_signal['stock_id']} {top_signal['name']}</b>｜"
                f"5日 {_fmt_perf_pct(top_signal.get('return_5d'), signed=True)}"
            )
        health = dashboard_payload.get("health", {})
        theme_names = dashboard_payload.get("themes", {}).get("names", {})
        schedule_delay = health.get("schedule_delay_minutes")
        schedule_text = "未記錄"
        if schedule_delay is not None:
            schedule_text = f"{float(schedule_delay):.1f} 分"
        quality_text = (
            f"{data_quality.get('label_text') or data_quality.get('label', '未知')}｜分數 {data_quality.get('score', '—')}/100｜"
            f"覆蓋率 {data_quality.get('coverage', '—')}%｜AI {ai_health.get('label', '未啟用')}"
        )
        if data_quality.get("warnings"):
            quality_text += "\n" + "\n".join(f"⚠️ {item}" for item in data_quality["warnings"][:3])
        if data_quality.get("details"):
            detail_lines = []
            for item in data_quality["details"][:3]:
                detail_lines.append(
                    f"▸ {_zh_data_event(item.get('type'))}｜{_zh_dataset(item.get('dataset'))}｜{item.get('data_id')}｜{_zh_data_reason(item.get('reason') or item.get('period') or '-')}"
                )
            quality_text += "\n" + "\n".join(detail_lines)
        recovery = data_quality.get("recovery_status", {})
        if recovery and recovery.get("label") != "clean":
            recovery_label = {
                "retry_ready": "可自動補抓",
                "manual_check": "需人工檢查",
                "clean": "正常",
            }.get(recovery.get("label"), recovery.get("label"))
            quality_text += f"\n補抓狀態：{recovery_label}｜可補抓 {recovery.get('retryable', 0)}｜暫停 {recovery.get('blocked', 0)}"
        if data_retry:
            quality_text += (
                f"\nRetry Queue：待補 {data_retry.get('pending', 0)}｜"
                f"已補 {data_retry.get('recovered', 0)}｜失敗 {data_retry.get('failed', 0)}"
            )
        decision_text = (
            f"{_zh_posture(decision.get('posture', 'selective_watch'))}｜"
            f"觀察 {decision.get('watch_count', 0)}｜拉回 {decision.get('pullback_count', 0)}｜"
            f"風險 {decision.get('risk_count', 0)}｜主題 {theme_names.get(decision.get('top_theme'), decision.get('top_theme') or '-')}"
        )
        us_policy_text = "\n".join(
            f"- {item.get('event_zh') or _zh_policy_event(item.get('event'))}｜{_zh_policy_level(item.get('sensitivity'))}｜{_zh_policy_level(item.get('confidence'))}\n  {item.get('headline_zh') or item.get('headline')}"
            for item in us_events[:3]
        ) or "- 最新新聞未偵測到高敏感美國政策訊號"
        quality_text += f"\n今日決策：{decision_text}\n美國政策雷達：\n{us_policy_text}"
        default_dashboard_url = "https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/"
        dashboard_url = config.get("runtime", {}).get("dashboard_url") or default_dashboard_url
        telegram_message = "\n".join(
            [
                f"🇹🇼 <b>台股 AI 早報</b>｜{as_of.isoformat()}",
                "",
                f"🧭 風向：{dashboard_payload['overseas']['label']}",
                f"📰 題材：{dashboard_payload['themes']['summary']}",
                f"📊 掃描 <b>{s['scanned']}</b> 檔｜S+ <b>{s['s_plus_grade']}</b>｜S <b>{s['s_grade']}</b>｜A <b>{s['a_grade']}</b>｜B <b>{s['b_grade']}</b>｜資料源：{dashboard_payload['source_status']['label']}",
                f"⏱ 排程：{health.get('scheduler', 'local')}｜{health.get('scheduled_task') or '-'}｜延遲 {schedule_text}",
                "",
                "🔥 <b>今日必看：</b>",
                must_watch_text,
                "",
                "🤖 <b>AI 首選觀察：</b>",
                ai_watch_text,
                "",
                "⏳ <b>等拉回：</b>",
                pullback_text,
                "",
                "🚨 <b>異常提醒：</b>",
                alert_text,
                "",
                "🛡 <b>危險名單：</b>",
                exit_text,
                "",
                "👁 <b>觀察追蹤：</b>",
                review_text,
                "",
                "📈 <b>訊號成效：</b>",
                perf_text,
                "",
                "🧪 <b>資料品質：</b>",
                quality_text,
                "",
                f"🔗 <a href=\"{dashboard_url}\">開啟監控頁</a>",
                "⚠️ 僅供研究追蹤，不是投資建議。",
            ]
        )
    if not dry_run and store.has_delivered_today("telegram", delivery_date, "morning_report"):
        logging.info("Telegram morning report already delivered for run date %s; skipping.", delivery_date)
        return 0
    notifier = TelegramNotifier.from_env(dry_run=dry_run)
    notifier.send(telegram_message)
    if not dry_run:
        store.record_delivery(
            "telegram",
            delivery_date,
            "morning_report",
            run_id=os.getenv("GITHUB_RUN_ID", ""),
        )
    logging.info("Processed %s stocks for %s", len(results), as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
