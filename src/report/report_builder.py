from __future__ import annotations

from datetime import date

from src.indicators.overseas import OverseasSentiment
from src.news.web_theme import ThemeSignal
from src.scoring.score_engine import StockScore


def _one(reasons: list[str]) -> str:
    return reasons[0] if reasons else "無明顯訊號"


def _status_text(label: str) -> str:
    labels = {
        "BUY_WATCH": "買進觀察",
        "WAIT": "等待",
        "AVOID": "避開",
        "DATA_INSUFFICIENT": "資料不足",
    }
    return labels.get(label, label)


def _grade(score: int) -> str:
    if score >= 75:
        return "A級｜優先觀察"
    if score >= 65:
        return "B級｜可觀察"
    return "C級｜只追蹤"


def build_report(
    scores: list[StockScore],
    as_of: date,
    market_summary: str,
    market_warning: str | None,
    config: dict,
    overseas: OverseasSentiment | None = None,
    theme_signal: ThemeSignal | None = None,
) -> str:
    push_min = int(config.get("thresholds", {}).get("push_min", 60))
    top_n = int(config.get("thresholds", {}).get("top_n", 5))
    opportunity_n = int(config.get("thresholds", {}).get("opportunity_n", 5))
    candidates = [
        item for item in scores if item.label != "DATA_INSUFFICIENT" and item.total_score >= push_min
    ]
    candidates.sort(key=lambda item: item.total_score, reverse=True)
    insufficient = [item for item in scores if item.label == "DATA_INSUFFICIENT"]
    data_source_issue = bool(scores) and len(insufficient) == len(scores)
    stock_names = config.get("stock_names", {})
    small_mid_exclude = set(config.get("opportunity", {}).get("small_mid_exclude", []))
    opportunity_min = int(config.get("opportunity", {}).get("min_score", 50))
    opportunity_candidates = [
        item
        for item in scores
        if item.label != "DATA_INSUFFICIENT"
        and item.stock_id not in small_mid_exclude
        and item.total_score >= opportunity_min
    ]
    opportunity_candidates.sort(
        key=lambda item: (item.opportunity_score, item.total_score),
        reverse=True,
    )

    overseas_line = "海外：未納入"
    if overseas:
        overseas_line = f"海外：{overseas.label}｜{overseas.summary}"

    market_bias = overseas.label if overseas else "中性"
    lines = [
        f"台股 AI 開盤前觀察｜{as_of.isoformat()} 08:20 模擬",
        "",
        f"今日風向：{market_bias}",
        f"台股大盤：{market_summary}",
        overseas_line,
        f"熱門題材：{theme_signal.summary if theme_signal else '未納入'}",
        f"掃描：{len(scores)} 檔｜進場觀察：{len(candidates)} 檔｜題材雷達：{len(opportunity_candidates)} 檔",
        "分數：滿分100；75以上=A優先觀察，65以上=B可觀察。",
    ]
    if market_warning:
        lines.append(f"提醒：{market_warning}")

    lines.extend(["", "今日進場觀察："])
    if data_source_issue:
        lines.append("資料源目前限流或不足，暫不產生進場標的。")
    for idx, item in enumerate(candidates[:top_n], start=1):
        name = stock_names.get(item.stock_id, "名稱未設定")
        overseas_note = ""
        if item.overseas_adjustment:
            overseas_note = f"｜海外調整 {item.overseas_adjustment:+d}"
        lines.extend(
            [
                f"{idx}. {item.stock_id} {name}｜{item.total_score}/100｜{_grade(item.total_score)}｜收 {item.price:.2f}{overseas_note}",
                f"   原因：{item.trigger_summary}",
                f"   進場：{item.entry_condition or '觀察中'}｜停損參考：{item.stop_reference or '—'}",
            ]
        )

    if not candidates and not data_source_issue:
        lines.append("今天沒有股票達到進場觀察門檻。")

    if opportunity_candidates:
        lines.extend(["", "中小型/題材雷達："])
        for idx, item in enumerate(opportunity_candidates[:opportunity_n], start=1):
            name = stock_names.get(item.stock_id, "名稱未設定")
            theme_text = "/".join(item.themes[:2]) if item.themes else "未歸類"
            lines.extend(
                [
                    f"{idx}. {item.stock_id} {name}｜{item.total_score}/100｜{_grade(item.total_score)}｜題材：{theme_text}",
                    f"   原因：{item.trigger_summary}",
                ]
            )

    if theme_signal and theme_signal.headlines:
        lines.extend(["", "新聞線索："])
        for headline in theme_signal.headlines[:3]:
            lines.append(f"- {headline}")

    if insufficient and not data_source_issue:
        lines.extend(["", f"資料不足：{', '.join(item.stock_id for item in insufficient)}"])
    elif data_source_issue:
        lines.extend(["", "資料提醒：FinMind 目前回傳限流/資料不足，已避免用不完整資料篩選標的。"])

    lines.extend(
        [
            "",
            "重點：這是開盤前觀察名單，進場仍需看開盤量價與個人風控。",
            "僅供研究追蹤，不是投資建議。",
        ]
    )
    return "\n".join(lines)
