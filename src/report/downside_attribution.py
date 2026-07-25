from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any


_CATEGORY_LABELS = {
    "chip_distribution": "籌碼倒貨",
    "technical_breakdown": "技術轉弱",
    "retail_overheat": "散戶過熱",
    "theme_cooling": "題材退潮",
    "fundamental_deterioration": "基本面轉弱",
    "macro_headwind": "大盤/海外拖累",
    "overextended_pullback": "漲多修正",
    "unknown": "待觀察",
}

_CATEGORY_KEYWORDS = {
    "chip_distribution": (
        "法人賣",
        "外資",
        "投信",
        "賣壓",
        "賣超",
        "融資增",
        "籌碼背離",
    ),
    "technical_breakdown": (
        "跌破",
        "放量下跌",
        "爆量長黑",
        "跌幅",
        "股價轉弱",
        "分數下降",
        "由買進觀察轉弱",
    ),
    "retail_overheat": (
        "散戶過熱",
        "散戶偏熱",
        "散戶增加",
        "人數",
    ),
    "theme_cooling": (
        "題材退潮",
        "題材降溫",
        "弱題材",
        "熱度轉弱",
    ),
    "fundamental_deterioration": (
        "營收",
        "月營收",
        "獲利",
        "EPS",
        "本益比",
        "估值",
        "毛利",
    ),
    "macro_headwind": (
        "海外",
        "美股",
        "Nasdaq",
        "SOX",
        "台指",
        "匯率",
        "政策",
    ),
    "overextended_pullback": (
        "過熱",
        "追高",
        "漲多",
        "高位",
        "20日高",
        "漲停",
    ),
}


def classify_downside_reasons(reasons: list[str] | tuple[str, ...] | None) -> dict[str, Any]:
    """Classify why a stock is weakening, without changing its score."""
    reason_list = [str(reason) for reason in reasons or [] if str(reason).strip()]
    text = "｜".join(reason_list)
    hits: Counter[str] = Counter()
    matched: dict[str, list[str]] = defaultdict(list)

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                hits[category] += 1
                matched[category].append(keyword)

    if not hits:
        category = "unknown"
    else:
        category = hits.most_common(1)[0][0]

    return {
        "category": category,
        "label": _CATEGORY_LABELS[category],
        "matched_keywords": matched.get(category, [])[:4],
        "all_matches": {key: values[:5] for key, values in matched.items()},
    }


def annotate_exit_risks(exit_risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach downside attribution to each exit-risk item in-place and return it."""
    for item in exit_risks:
        result = classify_downside_reasons(item.get("reasons") or [])
        item["downside_category"] = result["category"]
        item["downside_label"] = result["label"]
        item["downside_keywords"] = result["matched_keywords"]
    return exit_risks


def build_downside_attribution(
    as_of: date,
    exit_risks: list[dict[str, Any]] | None,
    alerts: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize the main falling-risk causes for dashboard data and Telegram."""
    items = annotate_exit_risks(list(exit_risks or []))
    counts: Counter[str] = Counter(str(item.get("downside_category") or "unknown") for item in items)
    score_totals: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in items:
        category = str(item.get("downside_category") or "unknown")
        score_totals[category] += int(item.get("risk_score") or 0)
        if len(examples[category]) < 3:
            examples[category].append(
                {
                    "stock_id": item.get("stock_id"),
                    "name": item.get("name"),
                    "level": item.get("level"),
                    "risk_score": item.get("risk_score"),
                    "reasons": (item.get("reasons") or [])[:2],
                }
            )

    category_rows = [
        {
            "category": category,
            "label": _CATEGORY_LABELS.get(category, category),
            "count": count,
            "risk_score_sum": score_totals[category],
            "examples": examples.get(category, []),
        }
        for category, count in counts.items()
    ]
    category_rows.sort(key=lambda row: (-int(row["count"]), -int(row["risk_score_sum"]), str(row["label"])))

    top = category_rows[0] if category_rows else None
    if top:
        summary = f"主要跌因：{top['label']} {top['count']} 檔"
    elif alerts:
        summary = "目前以市場提醒為主，個股跌因樣本不足"
    else:
        summary = "目前未偵測明顯個股跌因"

    return {
        "as_of": as_of.isoformat(),
        "total": len(items),
        "summary": summary,
        "top_category": top or {},
        "categories": category_rows,
        "items": items[:20],
        "methodology": "根據危險名單原因歸類；只做風險解釋與檢討，不直接改變核心分數。",
    }

