from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


SIGNAL_CLEAN = "籌碼轉乾淨"
SIGNAL_OVERHEATED = "散戶過熱"
SIGNAL_CLEAN_WATCH = "觀察籌碼轉乾淨"
SIGNAL_OVERHEATED_WATCH = "觀察散戶過熱"
SIGNAL_NEUTRAL = "中性"


@dataclass(frozen=True)
class RetailDivergenceThresholds:
    holder_change_pct: float = 3.0
    watch_holder_change_pct: float = 1.5
    price_flat_pct: float = 1.0
    min_volume: float = 1000.0


def classify_retail_divergence(
    *,
    holder_change_pct: float | None,
    price_change_pct: float | None,
    volume: float | None,
    thresholds: RetailDivergenceThresholds | None = None,
) -> tuple[str, str]:
    """Classify weekly retail-holder divergence.

    Positive signal: retail holders decrease but price does not fall.
    Risk signal: retail holders increase but price does not rise.
    """
    t = thresholds or RetailDivergenceThresholds()
    if holder_change_pct is None or price_change_pct is None:
        return SIGNAL_NEUTRAL, "持股人數或股價資料不足"
    if volume is None or volume < t.min_volume:
        return SIGNAL_NEUTRAL, f"成交量低於 {int(t.min_volume)} 張，訊號參考性不足"

    if holder_change_pct <= -t.holder_change_pct and price_change_pct >= -t.price_flat_pct:
        return SIGNAL_CLEAN, "散戶人數下降且股價未弱，籌碼較乾淨"
    if holder_change_pct >= t.holder_change_pct and price_change_pct <= t.price_flat_pct:
        return SIGNAL_OVERHEATED, "散戶人數增加但股價漲不動，需防範籌碼過熱"
    if holder_change_pct <= -t.watch_holder_change_pct and price_change_pct >= -t.price_flat_pct:
        return SIGNAL_CLEAN_WATCH, "散戶人數小幅下降且股價未弱，列入籌碼轉乾淨觀察"
    if holder_change_pct >= t.watch_holder_change_pct and price_change_pct <= t.price_flat_pct:
        return SIGNAL_OVERHEATED_WATCH, "散戶人數小幅增加且股價未強，列入散戶過熱觀察"
    return SIGNAL_NEUTRAL, "未出現明顯散戶背離"


def enrich_retail_records(
    records: Iterable[dict],
    *,
    thresholds: RetailDivergenceThresholds | None = None,
) -> list[dict]:
    enriched = []
    for row in records:
        signal, reason = classify_retail_divergence(
            holder_change_pct=_float_or_none(row.get("holder_change_pct")),
            price_change_pct=_float_or_none(row.get("price_change_pct")),
            volume=_float_or_none(row.get("volume")),
            thresholds=thresholds,
        )
        item = dict(row)
        item["signal"] = signal
        item["reason"] = row.get("reason") or reason
        enriched.append(item)
    return enriched


def summarize_retail_divergence(records: Iterable[dict], max_items: int = 10) -> dict:
    items = list(records)
    clean = [item for item in items if item.get("signal") == SIGNAL_CLEAN]
    overheated = [item for item in items if item.get("signal") == SIGNAL_OVERHEATED]
    watch_clean = [item for item in items if item.get("signal") == SIGNAL_CLEAN_WATCH]
    watch_overheated = [item for item in items if item.get("signal") == SIGNAL_OVERHEATED_WATCH]
    clean.sort(key=lambda item: (_float_or_none(item.get("holder_change_pct")) or 0, -(_float_or_none(item.get("volume")) or 0)))
    overheated.sort(key=lambda item: (-(_float_or_none(item.get("holder_change_pct")) or 0), -(_float_or_none(item.get("volume")) or 0)))
    watch_clean.sort(key=lambda item: (_float_or_none(item.get("holder_change_pct")) or 0, -(_float_or_none(item.get("volume")) or 0)))
    watch_overheated.sort(key=lambda item: (-(_float_or_none(item.get("holder_change_pct")) or 0), -(_float_or_none(item.get("volume")) or 0)))
    latest_date = max((str(item.get("week_date") or "") for item in items), default="")
    return {
        "week_date": latest_date,
        "summary": {
            "clean": len(clean),
            "overheated": len(overheated),
            "watch_clean": len(watch_clean),
            "watch_overheated": len(watch_overheated),
            "total": len(items),
        },
        "clean": clean[:max_items],
        "overheated": overheated[:max_items],
        "watch_clean": watch_clean[:max_items],
        "watch_overheated": watch_overheated[:max_items],
        "note": "週資料用來判斷籌碼是否轉乾淨或過熱；仍需搭配價格、成交量與每日操作結論。",
    }


def empty_retail_divergence(as_of: date | None = None) -> dict:
    return {
        "week_date": as_of.isoformat() if as_of else "",
        "summary": {"clean": 0, "overheated": 0, "watch_clean": 0, "watch_overheated": 0, "total": 0},
        "clean": [],
        "overheated": [],
        "watch_clean": [],
        "watch_overheated": [],
        "note": "尚未取得集保股權分散週資料；每日選股仍可運作，但缺少散戶背離輔助。",
    }


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
