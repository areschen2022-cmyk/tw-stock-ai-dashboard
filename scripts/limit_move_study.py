from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_yaml, merge_theme_database
from src.data_provider.finmind_client import FinMindClient


TAIPEI = ZoneInfo("Asia/Taipei")
LIMIT_UP_THRESHOLD = 9.5
LIMIT_DOWN_THRESHOLD = -9.5


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _default_as_of() -> date:
    today = datetime.now(TAIPEI).date()
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    return today


def _num(value, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _round(value, digits: int = 2) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _safe_avg(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if _num(value) is not None]
    return round(mean(clean), 2) if clean else None


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags) * 100, 1) if flags else None


def _cache_stock_ids(cache_dir: Path) -> list[str]:
    ids: set[str] = set()
    pattern = re.compile(r"^TaiwanStockPrice__(?P<stock_id>\d{4,6})__\d{4}-\d{2}(?:-current)?\.json$")
    for path in cache_dir.glob("TaiwanStockPrice__*.json"):
        match = pattern.match(path.name)
        if match:
            ids.add(match.group("stock_id"))
    return sorted(ids)


def _configured_stock_ids(config: dict) -> list[str]:
    ids: list[str] = [str(stock_id) for stock_id in config.get("stocks", [])]
    for pool in (config.get("theme_pools") or {}).values():
        ids.extend(str(stock_id) for stock_id in (pool.get("stocks") or {}))
    seen: set[str] = set()
    output: list[str] = []
    for stock_id in ids:
        if stock_id not in seen:
            seen.add(stock_id)
            output.append(stock_id)
    return output


def build_theme_lookup(config: dict) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = defaultdict(list)
    for pool in (config.get("theme_pools") or {}).values():
        theme_name = str(pool.get("name") or "").strip()
        for stock_id in (pool.get("stocks") or {}):
            if theme_name:
                lookup[str(stock_id)].append(theme_name)
    return {stock_id: sorted(set(themes)) for stock_id, themes in lookup.items()}


def _clean_prices(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "Trading_Volume" in out.columns and "volume" not in out.columns:
        out = out.rename(columns={"Trading_Volume": "volume", "max": "high", "min": "low"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    out = out[out["close"] > 0].sort_values("date").drop_duplicates("date")
    return out.reset_index(drop=True)


def _pct(current: float, base: float) -> float | None:
    if not base or base <= 0:
        return None
    return (current / base - 1) * 100


def _labels(side: str, row: pd.Series) -> list[str]:
    labels: list[str] = []
    volume_ratio = _num(row.get("volume_ratio_20"), 0) or 0
    pre_5d = _num(row.get("pre_5d_return"), 0) or 0
    pre_20d = _num(row.get("pre_20d_return"), 0) or 0
    pre_range = _num(row.get("pre_20d_range"), 0) or 0
    prior_above_ma20 = bool(row.get("prior_above_ma20"))
    breakout_20d = bool(row.get("breakout_20d"))
    breakdown_20d = bool(row.get("breakdown_20d"))

    if side == "limit_up":
        if breakout_20d:
            labels.append("突破整理")
        if volume_ratio >= 3:
            labels.append("異常爆量")
        elif volume_ratio >= 1.8:
            labels.append("量能放大")
        if prior_above_ma20:
            labels.append("趨勢在均線上")
        if pre_range <= 18 and breakout_20d:
            labels.append("盤整後發動")
        if pre_20d >= 15:
            labels.append("題材續強")
        if pre_20d <= -10 or pre_5d <= -6:
            labels.append("跌深反彈")
    else:
        if breakdown_20d:
            labels.append("跌破整理")
        if volume_ratio >= 2:
            labels.append("放量倒貨")
        if pre_20d >= 20:
            labels.append("高檔轉弱")
        if pre_20d <= -10:
            labels.append("弱勢續跌")
        if not prior_above_ma20:
            labels.append("均線下方")
        if pre_range >= 30:
            labels.append("高波動警訊")
    return labels or ["未分類"]


def detect_limit_events(stock_id: str, name: str, themes: list[str], prices: pd.DataFrame) -> list[dict]:
    df = _clean_prices(prices)
    if len(df) < 70:
        return []

    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")
    df["pct_change"] = close.pct_change() * 100
    df["ma20"] = close.rolling(20, min_periods=20).mean()
    df["vol20_prior"] = volume.shift(1).rolling(20, min_periods=20).mean()
    df["high20_prior"] = high.shift(1).rolling(20, min_periods=20).max()
    df["low20_prior"] = low.shift(1).rolling(20, min_periods=20).min()
    df["pre_5d_return"] = (close.shift(1) / close.shift(6) - 1) * 100
    df["pre_20d_return"] = (close.shift(1) / close.shift(21) - 1) * 100
    df["pre_20d_range"] = (df["high20_prior"] / df["low20_prior"] - 1) * 100
    df["volume_ratio_20"] = volume / df["vol20_prior"]
    df["prior_above_ma20"] = close.shift(1) > df["ma20"].shift(1)
    df["breakout_20d"] = close >= df["high20_prior"]
    df["breakdown_20d"] = close <= df["low20_prior"]

    events: list[dict] = []
    for idx in range(21, len(df)):
        current = df.iloc[idx]
        change = _num(current.get("pct_change"))
        if change is None:
            continue
        side = ""
        if change >= LIMIT_UP_THRESHOLD:
            side = "limit_up"
        elif change <= LIMIT_DOWN_THRESHOLD:
            side = "limit_down"
        if not side:
            continue

        post_5d = None
        post_10d = None
        if idx + 5 < len(df):
            post_5d = _pct(float(df.iloc[idx + 5]["close"]), float(current["close"]))
        if idx + 10 < len(df):
            post_10d = _pct(float(df.iloc[idx + 10]["close"]), float(current["close"]))
        labels = _labels(side, current)
        events.append(
            {
                "stock_id": stock_id,
                "name": name,
                "date": current["date"].date().isoformat(),
                "side": side,
                "close": _round(current["close"], 2),
                "pct_change": _round(change, 2),
                "volume_ratio_20": _round(current.get("volume_ratio_20"), 2),
                "pre_5d_return": _round(current.get("pre_5d_return"), 2),
                "pre_20d_return": _round(current.get("pre_20d_return"), 2),
                "pre_20d_range": _round(current.get("pre_20d_range"), 2),
                "prior_above_ma20": bool(current.get("prior_above_ma20")),
                "breakout_20d": bool(current.get("breakout_20d")),
                "breakdown_20d": bool(current.get("breakdown_20d")),
                "post_5d_return": _round(post_5d, 2),
                "post_10d_return": _round(post_10d, 2),
                "labels": labels,
                "themes": themes,
            }
        )
    return events


def _factor_summary(events: list[dict], side: str) -> list[dict]:
    rows: list[dict] = []
    for label, count in Counter(label for event in events for label in event["labels"]).most_common():
        matched = [event for event in events if label in event["labels"]]
        if side == "limit_up":
            continuation_5d = _rate([(event.get("post_5d_return") or 0) > 0 for event in matched if event.get("post_5d_return") is not None])
        else:
            continuation_5d = _rate([(event.get("post_5d_return") or 0) < 0 for event in matched if event.get("post_5d_return") is not None])
        rows.append(
            {
                "label": label,
                "events": count,
                "avg_volume_ratio_20": _safe_avg([event.get("volume_ratio_20") for event in matched]),
                "avg_pre_20d_return": _safe_avg([event.get("pre_20d_return") for event in matched]),
                "avg_post_5d_return": _safe_avg([event.get("post_5d_return") for event in matched]),
                "avg_post_10d_return": _safe_avg([event.get("post_10d_return") for event in matched]),
                "continuation_5d_rate": continuation_5d,
            }
        )
    return rows


def _theme_summary(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for theme, count in Counter(theme for event in events for theme in event.get("themes", [])).most_common(12):
        matched = [event for event in events if theme in event.get("themes", [])]
        rows.append(
            {
                "theme": theme,
                "events": count,
                "limit_up": sum(1 for event in matched if event["side"] == "limit_up"),
                "limit_down": sum(1 for event in matched if event["side"] == "limit_down"),
                "avg_post_5d_return": _safe_avg([event.get("post_5d_return") for event in matched]),
            }
        )
    return rows


def summarize_events(events: list[dict]) -> dict:
    up = [event for event in events if event["side"] == "limit_up"]
    down = [event for event in events if event["side"] == "limit_down"]
    return {
        "limit_up": {
            "events": len(up),
            "completed_5d": sum(1 for event in up if event.get("post_5d_return") is not None),
            "avg_post_5d_return": _safe_avg([event.get("post_5d_return") for event in up]),
            "continuation_5d_rate": _rate([(event.get("post_5d_return") or 0) > 0 for event in up if event.get("post_5d_return") is not None]),
            "common_labels": _factor_summary(up, "limit_up"),
            "recent_examples": sorted(up, key=lambda event: event.get("date", ""), reverse=True)[:20],
        },
        "limit_down": {
            "events": len(down),
            "completed_5d": sum(1 for event in down if event.get("post_5d_return") is not None),
            "avg_post_5d_return": _safe_avg([event.get("post_5d_return") for event in down]),
            "continuation_5d_rate": _rate([(event.get("post_5d_return") or 0) < 0 for event in down if event.get("post_5d_return") is not None]),
            "common_labels": _factor_summary(down, "limit_down"),
            "recent_examples": sorted(down, key=lambda event: event.get("date", ""), reverse=True)[:20],
        },
        "theme_summary": _theme_summary(events),
    }


def build_study(root: Path, years: int, universe_mode: str, max_stocks: int | None, offline: bool) -> dict:
    load_dotenv(root / ".env")
    config = merge_theme_database(load_yaml(str(root / "config.yaml")), root)
    names = {str(k): str(v) for k, v in (config.get("stock_names") or {}).items()}
    theme_lookup = build_theme_lookup(config)
    provider = FinMindClient(cache_dir=root / "data" / "cache")
    as_of = _default_as_of()
    start_date = as_of - timedelta(days=int(years * 365.25) + 35)

    if universe_mode == "cache":
        universe = _cache_stock_ids(root / "data" / "cache")
    elif universe_mode == "configured":
        universe = _configured_stock_ids(config)
    else:
        universe = sorted(set(_cache_stock_ids(root / "data" / "cache")) | set(_configured_stock_ids(config)))
    if max_stocks:
        universe = universe[:max_stocks]

    all_events: list[dict] = []
    coverage: list[dict] = []
    for stock_id in universe:
        prices = provider.cached_only("TaiwanStockPrice", stock_id, start_date, as_of) if offline else provider.stock_prices(stock_id, start_date, as_of)
        cleaned = _clean_prices(prices)
        coverage.append(
            {
                "stock_id": stock_id,
                "name": names.get(stock_id, ""),
                "rows": len(cleaned),
                "start": cleaned["date"].min().date().isoformat() if not cleaned.empty else None,
                "end": cleaned["date"].max().date().isoformat() if not cleaned.empty else None,
            }
        )
        if len(cleaned) < 70:
            continue
        all_events.extend(detect_limit_events(stock_id, names.get(stock_id, ""), theme_lookup.get(stock_id, []), cleaned))

    usable = [row for row in coverage if row["rows"] >= 70]
    summary = summarize_events(all_events)
    return {
        "as_of": as_of.isoformat(),
        "generated_at": _now(),
        "status": "ok" if all_events else "no_events",
        "method": {
            "name": "limit up/down event study",
            "years": years,
            "universe_mode": universe_mode,
            "offline_cache_only": offline,
            "limit_up_threshold_pct": LIMIT_UP_THRESHOLD,
            "limit_down_threshold_pct": LIMIT_DOWN_THRESHOLD,
            "lookahead_guard": "Only pre-event features use data before or on the limit move day; post 5/10 day returns are outcome labels only.",
            "limitations": [
                "This first pass uses local cached stocks, not guaranteed full Taiwan market coverage.",
                "Rule labels describe recurring statistical conditions, not confirmed news causality.",
                "5-year and 10-year studies should run after full historical cache expansion.",
            ],
        },
        "coverage": {
            "stocks_requested": len(universe),
            "stocks_usable": len(usable),
            "events_total": len(all_events),
            "earliest": min((row["start"] for row in usable if row["start"]), default=None),
            "latest": max((row["end"] for row in usable if row["end"]), default=None),
            "sample": usable[:20],
        },
        "provider_status": provider.source_status(),
        "summary": summary,
        "findings": build_findings(summary),
    }


def build_findings(summary: dict) -> list[str]:
    up_labels = summary.get("limit_up", {}).get("common_labels") or []
    down_labels = summary.get("limit_down", {}).get("common_labels") or []
    findings: list[str] = []
    if up_labels:
        top = "、".join(row["label"] for row in up_labels[:4])
        findings.append(f"近一年漲停前最常重複的條件是：{top}。先把這些條件轉成潛力股前置檢查，不要只等新聞爆量後才追。")
    if down_labels:
        top = "、".join(row["label"] for row in down_labels[:4])
        findings.append(f"近一年跌停前最常重複的條件是：{top}。這些條件可回接危險名單，避免把高風險股誤列可追。")
    if not findings:
        findings.append("本地快取樣本尚未找到足夠漲跌停事件；需要先擴充歷史價格快取。")
    findings.append("下一階段應先擴充全市場 1 年快取，再跑 5 年與 10 年；不要直接拿目前 75 檔題材池代表全市場。")
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Study common preconditions of Taiwan limit-up and limit-down events.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--years", type=int, default=1)
    parser.add_argument("--universe", choices=["cache", "configured", "all"], default="cache")
    parser.add_argument("--max-stocks", type=int)
    parser.add_argument("--offline", action="store_true", default=True)
    parser.add_argument("--online", action="store_false", dest="offline")
    parser.add_argument("--output", default="dashboard/limit_move_study.json")
    parser.add_argument("--docs-output", default="docs/limit_move_study.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    payload = build_study(root, args.years, args.universe, args.max_stocks, args.offline)
    for target in [root / args.output, root / args.docs_output]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "limit_move_study",
        payload["status"],
        "stocks",
        payload["coverage"]["stocks_usable"],
        "events",
        payload["coverage"]["events_total"],
    )
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
