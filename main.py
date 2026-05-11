from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.data_provider.finmind_client import FinMindClient
from src.data_provider.mock_data import MockDataProvider
from src.indicators.overseas import analyze_overseas_sentiment
from src.indicators.opportunity import opportunity_score
from src.notifier.telegram import TelegramNotifier
from src.news.web_theme import fetch_theme_signal
from src.report.dashboard import build_dashboard_payload, write_dashboard
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
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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

    as_of = resolve_as_of(config, args.as_of_date)
    start_date = as_of - timedelta(days=int(config["data"]["lookback_days"]))
    use_mock = args.mock_data or bool(config.get("runtime", {}).get("use_mock_data", False))
    dry_run = False if args.send_telegram else args.dry_run or bool(config.get("runtime", {}).get("dry_run", True))

    provider = MockDataProvider(as_of=as_of) if use_mock else FinMindClient()
    store = SQLiteStore(ROOT / "data" / "tw_stock_ai.sqlite3")
    engine = ScoreEngine(config)

    market_prices = provider.stock_prices(config["market"]["index_id"], start_date, as_of)
    market_adjustment, market_summary, market_warning = engine.market_adjustment(market_prices)
    overseas = None
    if config.get("overseas", {}).get("enabled", False):
        overseas = analyze_overseas_sentiment(provider.overseas_bundle(start_date, as_of))
    theme_signal = fetch_theme_signal(config)

    results = []
    semiconductor_sensitive = set(config.get("overseas", {}).get("semiconductor_sensitive", []))
    stock_themes: dict[str, list[str]] = {stock_id: [] for stock_id in config["stocks"]}
    theme_pools = config.get("theme_pools", {})
    active_theme_keys = set(theme_signal.active_themes)
    selected_theme_pools = {
        key: value
        for key, value in theme_pools.items()
        if not active_theme_keys or key in active_theme_keys
    }
    for theme_cfg in selected_theme_pools.values():
        theme_name = theme_cfg.get("name", "題材")
        for stock_id in theme_cfg.get("stocks", {}):
            stock_themes.setdefault(stock_id, []).append(theme_name)

    all_stock_ids = list(dict.fromkeys([*config["stocks"], *stock_themes.keys()]))
    core_ids = set(config["stocks"])
    for stock_id in all_stock_ids:
        bundle = provider.stock_bundle(stock_id, start_date, as_of, include_dividend=stock_id in core_ids)
        overseas_adj = 0
        if overseas:
            overseas_adj = overseas.adjustment
            if stock_id in semiconductor_sensitive:
                overseas_adj += overseas.semiconductor_adjustment
        opp_adj = 0
        opp_reasons: list[str] = []
        if config.get("opportunity", {}).get("enabled", False):
            opp_adj, opp_reasons = opportunity_score(bundle, stock_themes.get(stock_id, []))
        score = engine.score_stock(
            stock_id,
            bundle,
            market_adjustment,
            as_of,
            overseas_adj=overseas_adj,
            opportunity_adj=opp_adj,
            opportunity_reasons=opp_reasons,
            themes=stock_themes.get(stock_id, []),
        )
        results.append(score)
        store.save_daily_score(score, as_of)

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
    )
    write_dashboard(dashboard_payload, ROOT / "dashboard")
    telegram_message = report
    if args.telegram_summary:
        s = dashboard_payload["summary"]
        top_rows = [row for row in dashboard_payload["rows"] if row["grade"] in {"A", "B"}][:3]
        top_text = "\n".join(
            f"- {row['stock_id']} {row['name']}｜{row['score']}/100｜{row['grade']}級"
            for row in top_rows
        ) or "- 今日暫無 A/B 級觀察"
        telegram_message = "\n".join(
            [
                f"台股 AI 早報已更新｜{as_of.isoformat()}",
                f"風向：{dashboard_payload['overseas']['label']}｜題材：{dashboard_payload['themes']['summary']}",
                f"掃描：{s['scanned']}｜A級：{s['a_grade']}｜B級：{s['b_grade']}｜資料不足：{s['data_insufficient']}",
                "Top觀察：",
                top_text,
                f"監控頁：{config.get('runtime', {}).get('dashboard_url') or ROOT / 'dashboard' / 'dashboard.html'}",
                "僅供研究追蹤，不是投資建議。",
            ]
        )
    notifier = TelegramNotifier.from_env(dry_run=dry_run)
    notifier.send(telegram_message)
    logging.info("Processed %s stocks for %s", len(results), as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
