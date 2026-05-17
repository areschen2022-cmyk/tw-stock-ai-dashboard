from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from src.config_loader import load_yaml, merge_theme_database
from src.data_provider.finmind_client import FinMindClient
from src.data_provider.mock_data import MockDataProvider
from src.data_provider.twse_client import TwseClient
from src.indicators.market import sector_context
from src.indicators.overseas import analyze_overseas_sentiment
from src.indicators.opportunity import opportunity_score
from src.notifier.telegram import TelegramNotifier
from src.news.web_theme import fetch_theme_signal
from src.report.dashboard import build_dashboard_payload, write_dashboard, write_performance, write_theme_history
from src.report.exit_risk import build_exit_risks
from src.report.monitoring import detect_alerts, format_watch_reviews
from src.report.report_builder import build_report
from src.scoring.score_engine import ScoreEngine
from src.storage.sqlite_store import SQLiteStore


ROOT = Path(__file__).resolve().parent


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


def resolve_as_of(config: dict, cli_value: str | None) -> date:
    value = cli_value or config.get("runtime", {}).get("as_of_date")
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return date.today()


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
    active_theme_keys = set(theme_signal.active_themes)
    selected_theme_pools = {
        key: value
        for key, value in theme_pools.items()
        if not active_theme_keys or key in active_theme_keys
    }
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
    write_dashboard(dashboard_payload, ROOT / "dashboard")
    write_performance(store.performance_summary(as_of, days=30), ROOT / "dashboard")
    write_theme_history(
        store.all_theme_history(list(config.get("theme_pools", {}).keys()), days=30),
        ROOT / "dashboard",
    )
    telegram_message = report
    if args.telegram_summary:
        s = dashboard_payload["summary"]
        top_rows = [row for row in dashboard_payload["rows"] if row["grade"] in {"S+", "S", "A", "B"}][:3]

        def _entry_line(row: dict) -> str:
            action = row.get("action", "只觀察")
            limit = row.get("entry_limit_price")
            stop = row.get("stop_price")
            limit_str = f"上限 {limit:.2f}" if limit else ""
            stop_str = f"止損 {stop:.2f}" if stop else ""
            numbers = "｜".join(x for x in [limit_str, stop_str] if x)
            return f"{action}" + (f"（{numbers}）" if numbers else "")

        top_text = "\n".join(
            f"▸ <b>{row['stock_id']} {row['name']}</b>｜{row['score']}/100｜{row['grade']}級\n"
            f"  📌 {row['trigger_summary']}\n"
            f"  🎯 {_entry_line(row)}"
            for row in top_rows
        ) or "▸ 今日暫無 S/A/B 級觀察"
        alert_text = "\n".join(f"⚠️ {item}" for item in alerts[:3]) or "✅ 目前無重大異常"
        review_lines = format_watch_reviews(watch_reviews)
        review_text = "\n".join(f"▸ {item}" for item in review_lines) or "▸ 尚無可追蹤觀察"
        exit_text = "\n".join(
            f"▸ <b>{item['stock_id']} {item['name']}</b>｜{item['level']}｜{'、'.join(item['reasons'][:2])}"
            for item in exit_risks[:3]
        ) or "▸ 目前無紅黃警戒"
        default_dashboard_url = "https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/"
        dashboard_url = config.get("runtime", {}).get("dashboard_url") or default_dashboard_url
        telegram_message = "\n".join(
            [
                f"🇹🇼 <b>台股 AI 早報</b>｜{as_of.isoformat()}",
                "",
                f"🧭 風向：{dashboard_payload['overseas']['label']}",
                f"📰 題材：{dashboard_payload['themes']['summary']}",
                f"📊 掃描 <b>{s['scanned']}</b> 檔｜S+ <b>{s['s_plus_grade']}</b>｜S <b>{s['s_grade']}</b>｜A <b>{s['a_grade']}</b>｜B <b>{s['b_grade']}</b>｜資料源：{dashboard_payload['source_status']['label']}",
                "",
                "🏆 <b>Top 觀察：</b>",
                top_text,
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
                f"🔗 <a href=\"{dashboard_url}\">開啟監控頁</a>",
                "⚠️ 僅供研究追蹤，不是投資建議。",
            ]
        )
    notifier = TelegramNotifier.from_env(dry_run=dry_run)
    notifier.send(telegram_message)
    logging.info("Processed %s stocks for %s", len(results), as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
