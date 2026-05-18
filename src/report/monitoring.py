from __future__ import annotations

from datetime import date

from src.indicators.overseas import OverseasSentiment
from src.news.web_theme import ThemeSignal
from src.scoring.score_engine import StockScore
from src.storage.sqlite_store import SQLiteStore


def detect_alerts(
    scores: list[StockScore],
    as_of: date,
    store: SQLiteStore,
    source_status: dict,
    overseas: OverseasSentiment | None,
    theme_signal: ThemeSignal | None,
    score_jump_threshold: int = 20,
    max_items: int = 5,
) -> list[str]:
    alerts: list[str] = []
    source_label = str(source_status.get("label", "未知"))
    if source_label in {"錯誤", "限流"}:
        alerts.append(f"資料源異常：{source_label}")
    elif source_label == "部分限流":
        alerts.append("資料源提醒：部分限流，分數需保守解讀")

    if overseas and overseas.label == "偏空":
        alerts.append(f"海外偏空：{overseas.summary}")

    if theme_signal and theme_signal.source_count == 0:
        alerts.append("新聞題材資料源異常：全部來源未取得可用標題")

    if theme_signal and theme_signal.scores:
        top_theme, top_count = max(theme_signal.scores.items(), key=lambda item: item[1])
        if top_count >= 3:
            alerts.append(f"題材升溫：{theme_signal.summary}")
        # Momentum-based alert: flag any non-top theme that suddenly spikes
        for t_key, mom in (theme_signal.momentum or {}).items():
            if mom.trend == "急升🔥" and t_key != top_theme:
                alerts.append(f"題材急升 {t_key}：今日{mom.today}則（3日均{mom.avg_3d:.1f}則）")

    ranked_scores = sorted(scores, key=lambda score: score.total_score, reverse=True)
    for score in ranked_scores:
        if score.label == "DATA_INSUFFICIENT":
            continue
        previous = store.latest_score_before(score.stock_id, as_of)
        if previous:
            jump = score.total_score - int(previous["total_score"])
            if jump >= score_jump_threshold:
                alerts.append(f"{score.stock_id} 分數跳升：{previous['total_score']} -> {score.total_score}")
            if previous["label"] != "BUY_WATCH" and score.label == "BUY_WATCH":
                alerts.append(f"{score.stock_id} 新進買進觀察：{score.total_score}/100")
        elif score.label == "BUY_WATCH":
            alerts.append(f"{score.stock_id} 首次列入買進觀察：{score.total_score}/100")

        if score.opportunity_score >= 15:
            alerts.append(f"{score.stock_id} 異常熱度高：{score.opportunity_score} 分")

        if len(alerts) >= max_items:
            break

    return alerts[:max_items]


def format_watch_reviews(reviews: list[dict], max_items: int = 3) -> list[str]:
    lines: list[str] = []
    for item in reviews[:max_items]:
        sign = "+" if item["change_pct"] >= 0 else ""
        lines.append(
            f"{item['stock_id']} {item['name']}：{sign}{item['change_pct']:.1f}%｜現分 {item['current_score']}/100"
        )
    return lines
