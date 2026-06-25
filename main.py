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
from src.report.dashboard import (
    build_dashboard_payload,
    build_debug_payload,
    build_traceability_diagnosis,
    build_traceability_summary,
    build_weekly_overview_payload,
    enrich_dashboard_payload,
    write_dashboard,
    write_debug,
    write_performance,
    write_potential,
    write_theme_history,
    write_weekly_overview,
)
from src.report.exit_risk import build_exit_risks
from src.report.monitoring import detect_alerts
from src.report.potential_radar import build_potential_radar_candidates
from src.report.retail_divergence import SIGNAL_CLEAN, SIGNAL_OVERHEATED, empty_retail_divergence, summarize_retail_divergence
from src.report.report_builder import build_report
from src.scoring.knowledge_adjustment import apply_knowledge_adjustment, load_knowledge_context
from src.scoring.score_engine import ScoreEngine
from src.storage.sqlite_store import SQLiteStore


ROOT = Path(__file__).resolve().parent
TAIPEI = ZoneInfo("Asia/Taipei")


def attach_delivery_status(payload: dict, store: SQLiteStore, delivery_date: date) -> dict:
    status = store.delivery_status("telegram", delivery_date, "morning_report")
    payload["delivery_status"] = status
    payload.setdefault("health", {})["report_date"] = delivery_date.isoformat()
    payload.setdefault("health", {})["telegram_delivery"] = status
    return status


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


def _theme_stock_ids(theme_pools: dict) -> list[str]:
    stock_ids: list[str] = []
    for theme_cfg in theme_pools.values():
        for stock_id in theme_cfg.get("stocks", {}):
            sid = str(stock_id).strip()
            if sid and sid not in stock_ids:
                stock_ids.append(sid)
    return stock_ids


def _market_candidates(provider, as_of: date) -> list[dict]:
    market_universe = getattr(provider, "market_universe", None)
    if not callable(market_universe):
        return []
    try:
        rows = market_universe(as_of)
    except Exception as exc:  # pragma: no cover - runtime guard
        logging.warning("market universe fetch failed: %s", exc)
        return []
    normalized = []
    for row in rows or []:
        stock_id = str(row.get("stock_id") or "").strip()
        if not stock_id:
            continue
        normalized.append(
            {
                "stock_id": stock_id,
                "name": str(row.get("name") or "").strip(),
                "market": str(row.get("market") or "").strip(),
                "trade_value": float(row.get("trade_value") or 0),
            }
        )
    normalized.sort(key=lambda item: item["trade_value"], reverse=True)
    return normalized


def build_layered_stock_universe(
    config: dict,
    theme_signal,
    selected_theme_pools: dict,
    provider,
    as_of: date,
) -> tuple[list[str], dict]:
    """Build a rate-limit aware stock universe for the current run.

    Layers:
    - core: manually curated daily watch list.
    - active_theme: stocks tied to themes detected today.
    - theme_rotation: broader thematic pool, mainly for weekly expansion.
    - market_liquidity: official TWSE/TPEX market list ranked by turnover.
    """
    universe_cfg = config.get("universe", {})
    core_ids = [str(stock_id) for stock_id in config.get("stocks", [])]
    active_theme_ids = _theme_stock_ids(selected_theme_pools)
    all_theme_ids = _theme_stock_ids(config.get("theme_pools", {}))
    stock_names = config.setdefault("stock_names", {})

    enabled = bool(universe_cfg.get("enabled", False))
    weekly_weekday = int(universe_cfg.get("weekly_full_scan_weekday", 0))
    is_weekly = as_of.weekday() == weekly_weekday
    mode = "weekly_full_scan" if enabled and is_weekly else "daily_layered"
    market_limit = int(
        universe_cfg.get("weekly_market_limit" if is_weekly else "daily_market_limit", 0)
    )
    theme_rotation_limit = int(
        universe_cfg.get("weekly_theme_rotation_limit" if is_weekly else "daily_theme_rotation_limit", 0)
    )
    max_total = int(universe_cfg.get("max_weekly_total" if is_weekly else "max_daily_total", 0))

    ordered: list[str] = []

    def add_many(stock_ids: list[str]) -> int:
        before = len(ordered)
        for stock_id in stock_ids:
            sid = str(stock_id).strip()
            if sid and sid not in ordered:
                ordered.append(sid)
        return len(ordered) - before

    core_added = add_many(core_ids)
    active_theme_added = add_many(active_theme_ids)
    theme_rotation_added = 0
    market_added = 0
    market_rows = []

    if enabled:
        if theme_rotation_limit > 0:
            theme_rotation_added = add_many(all_theme_ids[:theme_rotation_limit])
        market_rows = _market_candidates(provider, as_of)
        for row in market_rows:
            if market_added >= market_limit:
                break
            stock_id = row["stock_id"]
            if stock_id in ordered:
                continue
            if row.get("name"):
                stock_names.setdefault(stock_id, row["name"])
            ordered.append(stock_id)
            market_added += 1
        if max_total > 0 and len(ordered) > max_total:
            ordered = ordered[:max_total]

    report = {
        "enabled": enabled,
        "mode": mode,
        "target_total_listed": int(universe_cfg.get("target_total_listed", 1056)),
        "selected_count": len(ordered),
        "coverage_pct": round(
            len(ordered) / max(1, int(universe_cfg.get("target_total_listed", 1056))) * 100,
            1,
        ),
        "core_count": core_added,
        "active_theme_count": active_theme_added,
        "theme_rotation_count": theme_rotation_added,
        "market_liquidity_count": market_added,
        "market_universe_available": len(market_rows),
        "daily_market_limit": int(universe_cfg.get("daily_market_limit", 0)),
        "weekly_market_limit": int(universe_cfg.get("weekly_market_limit", 0)),
        "weekly_full_scan_weekday": weekly_weekday,
        "active_themes": list(theme_signal.active_themes or []) if theme_signal else [],
    }
    return ordered, report


def bundle_coverage_report(bundles: dict[str, dict]) -> dict:
    """Measure actual per-stock bundle coverage instead of inferring it from request status."""
    datasets = {
        "prices": {"minimum": 20, "complete": [], "missing": []},
        "institutional": {"minimum": 1, "complete": [], "missing": []},
        "margin": {"minimum": 1, "complete": [], "missing": []},
        "revenue": {"minimum": 1, "complete": [], "missing": []},
        "revenue_15m": {"minimum": 15, "complete": [], "missing": []},
    }
    for stock_id, bundle in bundles.items():
        for key in ("prices", "institutional", "margin", "revenue"):
            count = len(bundle.get(key, []))
            target = datasets[key]
            target["complete" if count >= target["minimum"] else "missing"].append(stock_id)
        revenue_count = len(bundle.get("revenue", []))
        datasets["revenue_15m"]["complete" if revenue_count >= 15 else "missing"].append(stock_id)
    total = len(bundles)
    for row in datasets.values():
        row["count"] = len(row["complete"])
        row["coverage_pct"] = round(row["count"] / total * 100, 1) if total else 0.0
        row["missing"] = row["missing"][:20]
        row.pop("complete", None)
    critical = ["prices", "institutional", "margin", "revenue"]
    return {
        "stocks": total,
        "datasets": datasets,
        "all_critical_complete": all(not datasets[key]["missing"] for key in critical),
    }


def _score_label(total: int, config: dict) -> str:
    thresholds = config.get("thresholds", {})
    if total >= int(thresholds.get("buy_watch", 65)):
        return "BUY_WATCH"
    if total >= int(thresholds.get("wait_min", 50)):
        return "WAIT"
    return "AVOID"


def apply_selection_quality_adjustments(
    score,
    *,
    retail_signal: dict | None,
    theme_details: list[dict],
    config: dict,
) -> None:
    adjustment = 0
    notes: list[str] = []

    if retail_signal:
        signal = retail_signal.get("signal")
        if signal == SIGNAL_CLEAN:
            adjustment += 5
            notes.append("散戶人數下降且股價未弱，籌碼較乾淨")
            score.trigger_tags.append("散戶轉乾淨")
        elif signal == SIGNAL_OVERHEATED:
            adjustment -= 8
            notes.append("散戶人數增加但股價不漲，疑似有人倒貨")
            score.trigger_tags.append("散戶過熱")
            score.warnings.append("散戶背離轉弱")

    space_roles = [
        item for item in theme_details
        if item.get("theme_key") == "low_orbit_satellite"
        and item.get("tier") in {"core", "beneficiary"}
    ]
    if space_roles:
        if score.fundamental_score >= 10:
            adjustment += 3
            notes.append("SpaceX 題材具核心供應鏈角色，且營收成長有佐證")
            score.trigger_tags.append("SpaceX營收佐證")
        elif score.fundamental_score <= 0:
            notes.append("SpaceX 題材有供應鏈角色，但營收佐證不足")

    if not notes:
        return

    score.reasons.setdefault("quality", []).extend(notes)
    score.total_score = max(0, min(100, int(score.total_score) + adjustment))
    score.label = _score_label(score.total_score, config)
    score.retail_signal = retail_signal or {}
    score.selection_quality_adjustment = adjustment
    score.selection_quality_notes = notes


def merge_retail_exit_risks(exit_risks: list[dict], retail_rows: list[dict], stock_names: dict[str, str]) -> list[dict]:
    existing = {str(item.get("stock_id")) for item in exit_risks}
    merged = list(exit_risks)
    for row in retail_rows:
        stock_id = str(row.get("stock_id") or "")
        if not stock_id or stock_id in existing or row.get("signal") != SIGNAL_OVERHEATED:
            continue
        merged.append(
            {
                "stock_id": stock_id,
                "name": stock_names.get(stock_id) or row.get("name") or "",
                "level": "紅色警戒",
                "risk_score": 12,
                "reasons": ["散戶人數增加但股價不漲", "籌碼過熱疑似倒貨"],
                "action": "準備減碼或暫停追高；跌破停損不硬凹",
            }
        )
        existing.add(stock_id)
    return merged


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
    knowledge_context = load_knowledge_context(ROOT)
    if knowledge_context.get("rows"):
        logging.info(
            "Trading knowledge context loaded from %s (%s rows)",
            knowledge_context.get("source", "unknown"),
            len(knowledge_context.get("rows") or []),
        )
    retail_rows = store.latest_retail_holder_signals(limit=200)
    retail_map = {str(row.get("stock_id")): row for row in retail_rows}

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

    all_stock_ids, universe_report = build_layered_stock_universe(
        config,
        theme_signal,
        selected_theme_pools,
        provider,
        as_of,
    )
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
            try:
                bundles[stock_id] = future.result()
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                logging.exception("Failed to fetch stock bundle for %s: %s", stock_id, exc)
                bundles[stock_id] = {}

    for stock_id in all_stock_ids:
        bundle = bundles.get(stock_id, {})
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
        apply_selection_quality_adjustments(
            score,
            retail_signal=retail_map.get(stock_id),
            theme_details=stock_theme_details.get(stock_id, []),
            config=config,
        )
        apply_knowledge_adjustment(score, knowledge_context)
        results.append(score)
        store.save_daily_score(score, as_of)
        store.save_institutional_flow(stock_id, bundle.get("institutional"))
    store.record_data_update(
        "institutional_flow",
        as_of,
        status="ok",
        row_count=len(results),
        source_date=as_of,
        message=f"{len(results)} stocks scanned for institutional flow",
        run_id=os.getenv("GITHUB_RUN_ID", ""),
    )
    store.prune_daily_scores(as_of, [score.stock_id for score in results])

    source_status = provider.source_status()
    source_status["bundle_coverage"] = bundle_coverage_report(bundles)
    source_status["universe"] = universe_report
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
    retail_divergence = summarize_retail_divergence(retail_rows) if retail_rows else empty_retail_divergence(as_of)
    exit_risks = merge_retail_exit_risks(exit_risks, retail_rows, config.get("stock_names", {}))
    store.save_exit_risks(exit_risks, as_of)
    store.update_exit_risk_forward_returns(as_of)
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
        retail_divergence=retail_divergence,
    )
    attach_delivery_status(dashboard_payload, store, delivery_date)
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
    recommendation_stability = store.recommendation_stability(as_of, days=10)
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
        recommendation_stability=recommendation_stability,
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
        recommendation_stability=recommendation_stability,
    )
    store.save_potential_radar(
        build_potential_radar_candidates(dashboard_payload.get("rows", []), as_of),
        as_of,
    )
    store.update_potential_forward_returns(as_of)
    performance_payload = store.performance_summary(as_of, days=30)
    traceability_payload = build_traceability_summary(dashboard_payload, performance_payload)
    traceability_record = dict(traceability_payload)
    traceability_record["diagnosis"] = build_traceability_diagnosis(traceability_payload, dashboard_payload)
    store.save_traceability_run(traceability_record, as_of)
    traceability_payload["history"] = store.recent_traceability_runs(as_of, days=14)
    dashboard_payload["traceability"] = traceability_payload
    write_dashboard(dashboard_payload, ROOT / "dashboard")
    write_performance(performance_payload, ROOT / "dashboard")
    write_potential(performance_payload, ROOT / "dashboard")
    write_debug(build_debug_payload(dashboard_payload, performance_payload), ROOT / "dashboard")
    theme_history_payload = store.all_theme_history(list(config.get("theme_pools", {}).keys()), days=30)
    write_theme_history(
        theme_history_payload,
        ROOT / "dashboard",
    )
    write_weekly_overview(
        build_weekly_overview_payload(
            as_of,
            dashboard_payload,
            performance_payload,
            theme_history_payload,
            store.weekly_institutional_summary(as_of, config.get("stock_names", {}), days=7),
            store.latest_data_updates(limit=30),
        ),
        ROOT / "dashboard",
    )
    telegram_message = report
    if args.telegram_summary:
        s = dashboard_payload["summary"]
        action_lists = dashboard_payload.get("action_lists", {})
        data_quality = dashboard_payload.get("data_quality", {})
        ai_health = dashboard_payload.get("ai_council", {}).get("status", {}).get("health", {})

        def _compact_list(rows: list[dict], empty: str, limit: int = 3) -> str:
            return "\n".join(
                f"▸ <b>{row['stock_id']} {row['name']}</b>｜{row.get('score', 0)}/100｜"
                f"{row.get('grade', '-')}｜{row.get('entry_decision') or row.get('action', '只觀察')}｜"
                f"{row.get('ai_label', 'AI 未複核')}"
                for row in rows[:limit]
            ) or empty

        must_watch_text = _compact_list(action_lists.get("chase", []), "▸ 今日暫無可追清單", limit=3)
        ai_summary = action_lists.get("summary", {})
        ai_review_text = (
            f"AI 複核：同意 {ai_summary.get('ai_agree', 0)}｜"
            f"保留 {ai_summary.get('ai_hold', 0)}｜"
            f"不建議 {ai_summary.get('ai_avoid', 0)}｜"
            f"已複核 {ai_summary.get('ai_reviewed', 0)}"
        )
        alert_text = "\n".join(f"⚠️ {item}" for item in alerts[:2]) or "✅ 無重大異常"
        exit_text = "\n".join(
            f"▸ <b>{item['stock_id']} {item['name']}</b>｜{item['level']}｜{'、'.join(item['reasons'][:1])}"
            for item in exit_risks[:2]
        ) or "▸ 無紅黃警戒"
        health = dashboard_payload.get("health", {})
        schedule_delay = health.get("schedule_delay_minutes")
        schedule_text = "未記錄"
        if schedule_delay is not None:
            schedule_text = f"{float(schedule_delay):.1f} 分"
        default_dashboard_url = "https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/"
        dashboard_url = config.get("runtime", {}).get("dashboard_url") or default_dashboard_url
        telegram_message = "\n".join(
            [
                f"🇹🇼 <b>台股 AI 早報</b>｜{delivery_date.isoformat()}",
                f"資料日：{as_of.isoformat()}",
                "",
                f"🧭 風向：{dashboard_payload['overseas']['label']}",
                f"📰 題材：{dashboard_payload['themes']['summary']}",
                f"📊 掃描 <b>{s['scanned']}</b> 檔｜S+ <b>{s['s_plus_grade']}</b>｜S <b>{s['s_grade']}</b>｜A <b>{s['a_grade']}</b>｜B <b>{s['b_grade']}</b>｜資料源：{dashboard_payload['source_status']['label']}",
                f"⏱ 延遲：{schedule_text}｜資料品質：{data_quality.get('label_text') or data_quality.get('label', '未知')}｜AI：{ai_health.get('label', '未啟用')}",
                "",
                "🔥 <b>今日重點</b>",
                must_watch_text,
                f"🤖 {ai_review_text}",
                "",
                "🚨 <b>提醒</b>",
                alert_text,
                "",
                "🛡 <b>危險名單</b>",
                exit_text,
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
        attach_delivery_status(dashboard_payload, store, delivery_date)
        write_dashboard(dashboard_payload, ROOT / "dashboard")
    logging.info("Processed %s stocks for %s", len(results), as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
