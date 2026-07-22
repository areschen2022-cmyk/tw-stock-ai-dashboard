from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

import pandas as pd

from src.config_loader import load_yaml, merge_theme_database
from src.data_provider.finmind_client import FinMindClient


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_COST_BPS = 60.0
MIN_PHASE2_SAMPLE = 80


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _num_series(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce")


def _clean_prices(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    out = out[out["close"] > 0].sort_values("date").drop_duplicates("date")
    return out.reset_index(drop=True)


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags) * 100, 2) if flags else None


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    window = closes[-period - 1 :]
    for prev, cur in zip(window, window[1:]):
        change = cur - prev
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = mean(gains) if gains else 0
    avg_loss = mean(losses) if losses else 0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def classify_kronos_proxy(prices: pd.DataFrame, idx: int) -> dict:
    """Classify the technical sequence visible at *idx*.

    This is a lightweight, deterministic proxy for a sequence model gate. It
    deliberately uses only bars up to the signal day, so it can be backtested
    without look-ahead.
    """

    if idx < 60:
        return {"bias": "insufficient", "score": 0, "features": []}
    close = _num_series(prices, "close").tolist()
    high = _num_series(prices, "high").tolist()
    low = _num_series(prices, "low").tolist()
    volume = _num_series(prices, "volume").tolist()
    visible_close = close[: idx + 1]
    visible_volume = volume[: idx + 1]
    price = visible_close[-1]
    ma5 = mean(visible_close[-5:])
    ma20 = mean(visible_close[-20:])
    ma60 = mean(visible_close[-60:])
    vol20 = mean(visible_volume[-20:]) if visible_volume[-20:] else 0
    vol_ratio = visible_volume[-1] / vol20 if vol20 else 0
    ret5 = price / visible_close[-6] - 1 if len(visible_close) >= 6 and visible_close[-6] else 0
    ret20 = price / visible_close[-21] - 1 if len(visible_close) >= 21 and visible_close[-21] else 0
    extension = price / ma20 - 1 if ma20 else 0
    rsi14 = _rsi(visible_close, 14)
    atr_pct = mean(
        (float(h) - float(l)) / price
        for h, l in zip(high[max(0, idx - 13) : idx + 1], low[max(0, idx - 13) : idx + 1])
        if price > 0
    )

    bullish = 0
    bearish = 0
    features: list[str] = []

    if price > ma20 > ma60:
        bullish += 2
        features.append("close_gt_ma20_gt_ma60")
    if ma5 > ma20 and price > ma5:
        bullish += 1
        features.append("short_trend_up")
    if ret20 > 0.05:
        bullish += 1
        features.append("ret20_positive")
    if 1.1 <= vol_ratio <= 3.2:
        bullish += 1
        features.append("volume_confirmed")
    if rsi14 is not None and 45 <= rsi14 <= 75:
        bullish += 1
        features.append("rsi_balanced")
    if 0 <= extension <= 0.15:
        bullish += 1
        features.append("not_overextended")

    if price < ma20:
        bearish += 2
        features.append("close_below_ma20")
    if ma20 < ma60:
        bearish += 1
        features.append("ma20_below_ma60")
    if ret20 < -0.05:
        bearish += 1
        features.append("ret20_negative")
    if rsi14 is not None and rsi14 > 82:
        bearish += 1
        features.append("rsi_overheated")
    if extension > 0.22:
        bearish += 1
        features.append("overextended")
    if vol_ratio > 2.5 and price < visible_close[-2]:
        bearish += 1
        features.append("high_volume_reversal")
    if atr_pct > 0.075 and ret5 < 0:
        bearish += 1
        features.append("volatile_pullback")

    if bullish >= 5 and bearish <= 1:
        bias = "bullish"
    elif bearish >= 3:
        bias = "bearish"
    else:
        bias = "neutral"

    return {
        "bias": bias,
        "score": bullish - bearish,
        "bullish_points": bullish,
        "bearish_points": bearish,
        "features": features,
        "metrics": {
            "ret5_pct": round(ret5 * 100, 2),
            "ret20_pct": round(ret20 * 100, 2),
            "extension_pct": round(extension * 100, 2),
            "vol_ratio": round(vol_ratio, 2),
            "rsi14": round(rsi14, 2) if rsi14 is not None else None,
            "atr_pct": round(atr_pct * 100, 2),
        },
    }


def _return_stats(rows: list[dict], key: str = "net_return_5d") -> dict:
    values = [float(row[key]) for row in rows if row.get(key) is not None and math.isfinite(float(row[key]))]
    return {
        "signals": len(rows),
        "completed": len(values),
        "win_rate": _rate([value > 0 for value in values]),
        "avg_return": _avg(values),
        "median_return": round(median(values), 4) if values else None,
        "best_return": round(max(values), 4) if values else None,
        "worst_return": round(min(values), 4) if values else None,
    }


def _load_candidates(root: Path, start_date: date, min_score: int) -> list[dict]:
    with sqlite3.connect(root / "data" / "tw_stock_ai.sqlite3") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT as_of_date, stock_id, total_score, label, price
            FROM daily_scores
            WHERE as_of_date >= ?
              AND total_score >= ?
              AND label IN ('BUY_WATCH', 'WAIT')
            ORDER BY as_of_date, total_score DESC
            """,
            (start_date.isoformat(), min_score),
        ).fetchall()
    return [dict(row) for row in rows]


def _price_index(prices: pd.DataFrame) -> dict[str, int]:
    return {
        value.date().isoformat(): idx
        for idx, value in enumerate(pd.to_datetime(prices["date"], errors="coerce"))
        if not pd.isna(value)
    }


def _bucket(rows: list[dict], key: str) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key) or "unknown")].append(row)
    return [
        {key: name, **_return_stats(items)}
        for name, items in sorted(buckets.items())
    ]


def _feature_stats(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        for feature in row.get("features") or []:
            buckets[str(feature)].append(row)
    output = [
        {"feature": feature, **_return_stats(items)}
        for feature, items in buckets.items()
        if len(items) >= 10
    ]
    output.sort(key=lambda row: (row["completed"], row.get("avg_return") or -999), reverse=True)
    return output[:20]


def _phase2_decision(rows: list[dict]) -> dict:
    completed = [row for row in rows if row.get("net_return_5d") is not None]
    baseline = _return_stats(completed)
    by_bias = {row["kronos_bias"]: row for row in _bucket(completed, "kronos_bias")}
    bullish = by_bias.get("bullish") or {"completed": 0, "win_rate": None, "avg_return": None}
    bearish = by_bias.get("bearish") or {"completed": 0, "win_rate": None, "avg_return": None}
    base_win = float(baseline.get("win_rate") or 0)
    base_avg = float(baseline.get("avg_return") or 0)
    bull_win = float(bullish.get("win_rate") or 0)
    bull_avg = float(bullish.get("avg_return") or 0)
    bear_win = float(bearish.get("win_rate") or 0)
    bear_avg = float(bearish.get("avg_return") or 0)

    bullish_ok = int(bullish.get("completed") or 0) >= MIN_PHASE2_SAMPLE and bull_win >= base_win + 3 and bull_avg >= base_avg + 0.3
    bearish_ok = int(bearish.get("completed") or 0) >= 30 and (bear_win <= base_win - 8 or bear_avg <= base_avg - 1.0)
    qualified = bullish_ok or bearish_ok
    return {
        "qualified": qualified,
        "status": "qualified" if qualified else "not_qualified",
        "baseline": baseline,
        "bullish_gate": {
            "qualified": bullish_ok,
            "required": f"completed>={MIN_PHASE2_SAMPLE}, win_rate >= baseline+3pt, avg_return >= baseline+0.3pt",
            "observed": bullish,
        },
        "bearish_gate": {
            "qualified": bearish_ok,
            "required": "completed>=30 and win_rate <= baseline-8pt or avg_return <= baseline-1pt",
            "observed": bearish,
        },
        "recommended_integration": (
            [
                "Phase 2 only: use kronos_proxy_bias as an auxiliary gate, not as total-score points.",
                "可追/開盤確認 + bearish: downgrade to yellow confirmation.",
                "等拉回 + bullish: raise priority inside pullback list.",
                "危險名單 + bearish: strengthen risk wording.",
            ]
            if qualified
            else [
                "Do not change production trade decisions yet.",
                "Keep collecting daily proxy outcomes and rerun after more completed samples.",
            ]
        ),
    }


def build_kronos_proxy_backtest(
    root: Path,
    years: int = 5,
    min_score: int = 50,
    max_stocks: int | None = None,
    cost_bps: float = DEFAULT_COST_BPS,
    offline: bool = True,
) -> dict:
    config = merge_theme_database(load_yaml(str(root / "config.yaml")), root)
    names = {str(k): str(v) for k, v in (config.get("stock_names") or {}).items()}
    as_of = _latest_as_of(root)
    start_date = as_of - timedelta(days=int(years * 365.25))
    warmup_start = start_date - timedelta(days=140)
    candidates = _load_candidates(root, start_date, min_score=min_score)
    stock_ids = sorted({str(row["stock_id"]) for row in candidates})
    if max_stocks:
        selected_ids = set(stock_ids[:max_stocks])
        candidates = [row for row in candidates if str(row["stock_id"]) in selected_ids]
        stock_ids = sorted(selected_ids)

    provider = FinMindClient(cache_dir=root / "data" / "cache")
    by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in candidates:
        by_stock[str(row["stock_id"])].append(row)

    records: list[dict] = []
    coverage: list[dict] = []
    cost_pct = cost_bps / 100.0
    for stock_id in stock_ids:
        if offline:
            prices = provider.cached_only("TaiwanStockPrice", stock_id, warmup_start, as_of)
            if not prices.empty:
                prices = prices.rename(columns={"Trading_Volume": "volume", "max": "high", "min": "low"})
        else:
            prices = provider.stock_prices(stock_id, warmup_start, as_of)
        prices = _clean_prices(prices)
        idx_by_date = _price_index(prices) if not prices.empty else {}
        coverage.append(
            {
                "stock_id": stock_id,
                "name": names.get(stock_id, ""),
                "price_rows": len(prices),
                "candidate_rows": len(by_stock.get(stock_id, [])),
                "start": prices["date"].min().date().isoformat() if not prices.empty else None,
                "end": prices["date"].max().date().isoformat() if not prices.empty else None,
            }
        )
        if len(prices) < 75:
            continue
        for candidate in by_stock.get(stock_id, []):
            signal_date = str(candidate["as_of_date"])
            idx = idx_by_date.get(signal_date)
            if idx is None or idx < 60 or idx + 11 >= len(prices):
                continue
            bias = classify_kronos_proxy(prices, idx)
            entry = prices.iloc[idx + 1]
            exit_3d = prices.iloc[idx + 4]
            exit_5d = prices.iloc[idx + 6]
            exit_10d = prices.iloc[idx + 11]
            entry_price = float(entry["open"])
            if entry_price <= 0:
                continue
            ret3 = (float(exit_3d["close"]) / entry_price - 1) * 100
            ret5 = (float(exit_5d["close"]) / entry_price - 1) * 100
            ret10 = (float(exit_10d["close"]) / entry_price - 1) * 100
            records.append(
                {
                    "signal_date": signal_date,
                    "entry_date": entry["date"].date().isoformat(),
                    "stock_id": stock_id,
                    "name": names.get(stock_id, ""),
                    "score": int(candidate["total_score"]),
                    "label": candidate["label"],
                    "kronos_bias": bias["bias"],
                    "kronos_score": bias["score"],
                    "features": bias["features"],
                    "metrics": bias["metrics"],
                    "entry_price": round(entry_price, 4),
                    "net_return_3d": round(ret3 - cost_pct, 4),
                    "net_return_5d": round(ret5 - cost_pct, 4),
                    "net_return_10d": round(ret10 - cost_pct, 4),
                }
            )

    records.sort(key=lambda row: (row["signal_date"], row["score"]), reverse=True)
    phase2 = _phase2_decision(records)
    return {
        "as_of": as_of.isoformat(),
        "generated_at": _now(),
        "status": "ok" if records else "no_usable_records",
        "method": {
            "name": "Kronos-style deterministic OHLCV proxy backtest",
            "years": years,
            "min_score": min_score,
            "candidate_source": "daily_scores labels BUY_WATCH/WAIT",
            "execution": "Signal after close, enter next trading day open, exit at 3/5/10 trading-day close.",
            "cost_bps": cost_bps,
            "offline_cache_only": offline,
            "limitations": [
                "This is not the original Kronos neural model; it validates whether a sequence-style technical gate is useful before model integration.",
                "Universe comes from current stored signals and cached price history, so survivorship bias remains.",
                "No intraday fill simulation; use this as an auxiliary filter only.",
            ],
        },
        "coverage": {
            "candidate_rows": len(candidates),
            "stocks_requested": len(stock_ids),
            "stocks_with_price_history": sum(1 for row in coverage if int(row["price_rows"]) >= 75),
            "sample": coverage[:40],
        },
        "summary": {
            "overall_5d": _return_stats(records, "net_return_5d"),
            "overall_10d": _return_stats(records, "net_return_10d"),
            "by_bias": _bucket(records, "kronos_bias"),
            "by_label": _bucket(records, "label"),
            "by_feature": _feature_stats(records),
        },
        "phase2": phase2,
        "recent_examples": records[:30],
    }


def write_kronos_proxy_backtest(root: Path, output: Path, payload: dict | None = None) -> dict:
    payload = payload or build_kronos_proxy_backtest(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if output.parent.name == "dashboard":
        docs = root / "docs" / output.name
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _latest_as_of(root: Path) -> date:
    payload_path = root / "dashboard" / "dashboard_data.json"
    if payload_path.exists():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        return date.fromisoformat(str(payload["as_of"]))
    with sqlite3.connect(root / "data" / "tw_stock_ai.sqlite3") as conn:
        row = conn.execute("SELECT MAX(as_of_date) FROM daily_scores").fetchone()
    if not row or not row[0]:
        raise RuntimeError("No dashboard JSON or daily_scores data found")
    return date.fromisoformat(row[0])
