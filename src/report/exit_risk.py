from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Any

import pandas as pd

from src.scoring.score_engine import StockScore
from src.storage.sqlite_store import SQLiteStore


@dataclass
class ExitRisk:
    stock_id: str
    name: str
    level: str
    risk_score: int
    current_score: int
    previous_score: int | None
    price: float | None
    reasons: list[str]
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_exit_risks(
    scores: list[StockScore],
    bundles: dict[str, dict[str, pd.DataFrame]],
    as_of: date,
    store: SQLiteStore,
    stock_names: dict[str, str],
    config: dict,
) -> list[dict[str, Any]]:
    cfg = config.get("exit_risk", {})
    if not cfg.get("enabled", True):
        return []

    max_items = int(cfg.get("max_items", 8))
    score_drop_limit = int(cfg.get("score_drop", 15))
    margin_rise_pct = float(cfg.get("margin_rise_pct", 0.08))
    price_drop_5d_pct = float(cfg.get("price_drop_5d_pct", -5.0))

    risks: list[ExitRisk] = []
    for score in scores:
        if score.label == "DATA_INSUFFICIENT" or score.price is None:
            continue

        bundle = bundles.get(score.stock_id, {})
        prices = bundle.get("prices", pd.DataFrame())
        institutional = bundle.get("institutional", pd.DataFrame())
        margin = bundle.get("margin", pd.DataFrame())
        previous = store.latest_score_before(score.stock_id, as_of)

        points = 0
        reasons: list[str] = []

        sell_points, sell_reasons = _institutional_sell_risk(institutional)
        points += sell_points
        reasons.extend(sell_reasons)

        price_points, price_reasons = _price_break_risk(prices, price_drop_5d_pct)
        points += price_points
        reasons.extend(price_reasons)

        margin_points, margin_reasons = _margin_retail_risk(margin, prices, margin_rise_pct)
        points += margin_points
        reasons.extend(margin_reasons)

        divergence_points, divergence_reasons = _chip_divergence_risk(
            sell_reasons,
            margin_reasons,
            price_reasons,
        )
        points += divergence_points
        reasons = [*divergence_reasons, *reasons]

        if previous:
            prev_score = int(previous.get("total_score") or 0)
            drop = prev_score - score.total_score
            if drop >= score_drop_limit:
                points += 2
                reasons.append(f"分數下降 {drop} 分")
            if previous.get("label") == "BUY_WATCH" and score.label != "BUY_WATCH":
                points += 2
                reasons.append("由買進觀察轉弱")
        else:
            prev_score = None

        if points >= 5:
            level = "紅色警戒"
            action = "準備減碼或停利，跌破停損不硬凹"
        elif points >= 3:
            level = "黃色警戒"
            action = "提高停損，暫停加碼"
        else:
            continue

        risks.append(
            ExitRisk(
                stock_id=score.stock_id,
                name=stock_names.get(score.stock_id, score.stock_id),
                level=level,
                risk_score=points,
                current_score=score.total_score,
                previous_score=prev_score,
                price=score.price,
                reasons=reasons[:4],
                action=action,
            )
        )

    risks.sort(key=lambda item: (item.level != "紅色警戒", -item.risk_score, item.current_score))
    return [item.to_dict() for item in risks[:max_items]]


def _institutional_sell_risk(institutional: pd.DataFrame) -> tuple[int, list[str]]:
    if institutional.empty or "name" not in institutional.columns:
        return 0, []

    df = institutional.copy().sort_values("date")
    df["net"] = df.get("buy", 0).astype(float) - df.get("sell", 0).astype(float)
    points = 0
    reasons: list[str] = []

    foreign = _daily_net(df, "Foreign|外資")
    trust = _daily_net(df, "Trust|投信")

    if len(foreign) >= 3 and (foreign.tail(3) < 0).all():
        points += 2
        reasons.append("外資連 3 日賣超")
    elif len(foreign) >= 3 and foreign.tail(3).sum() < 0:
        points += 1
        reasons.append("外資近 3 日偏賣")

    if len(trust) >= 3 and (trust.tail(3) < 0).all():
        points += 2
        reasons.append("投信連 3 日賣超")
    elif len(trust) >= 3 and trust.tail(3).sum() < 0:
        points += 1
        reasons.append("投信近 3 日偏賣")

    if len(foreign) >= 5 and foreign.tail(5).sum() < 0:
        points += 1
        reasons.append("外資 5 日合計賣超")

    return points, reasons


def _daily_net(df: pd.DataFrame, pattern: str) -> pd.Series:
    rows = df[df["name"].astype(str).str.contains(pattern, case=False, na=False, regex=True)]
    if rows.empty:
        return pd.Series(dtype=float)
    return rows.groupby("date")["net"].sum().astype(float)


def _price_break_risk(prices: pd.DataFrame, price_drop_5d_pct: float) -> tuple[int, list[str]]:
    if prices.empty or len(prices) < 20:
        return 0, []

    df = prices.sort_values("date")
    close = df["close"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(dtype=float)
    latest = close.iloc[-1]
    points = 0
    reasons: list[str] = []

    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    if latest < ma5:
        points += 1
        reasons.append("跌破 MA5")
    if latest < ma10:
        points += 1
        reasons.append("跌破 MA10")
    if latest < ma20:
        points += 2
        reasons.append("跌破 MA20")

    if len(close) >= 4 and latest <= close.iloc[-4:-1].min():
        points += 1
        reasons.append("跌破近 3 日低點")

    if len(close) >= 6:
        ret_5d = (latest / close.iloc[-6] - 1) * 100
        if ret_5d <= price_drop_5d_pct:
            points += 2
            reasons.append(f"5 日跌幅 {ret_5d:.1f}%")

    if len(volume) >= 20 and len(close) >= 2:
        vol_ma20 = volume.rolling(20).mean().iloc[-1]
        if vol_ma20 > 0 and volume.iloc[-1] > vol_ma20 * 1.5 and latest < close.iloc[-2]:
            points += 1
            reasons.append("放量下跌")

    return points, reasons


def _chip_divergence_risk(
    sell_reasons: list[str],
    margin_reasons: list[str],
    price_reasons: list[str],
) -> tuple[int, list[str]]:
    has_institutional_sell = any("外資" in reason or "投信" in reason for reason in sell_reasons)
    has_margin_rise = any("融資增" in reason for reason in margin_reasons)
    has_price_weakness = any(
        keyword in reason
        for reason in price_reasons
        for keyword in ("跌破", "下跌", "跌幅")
    )
    if has_institutional_sell and has_margin_rise and has_price_weakness:
        return 3, ["法人賣、融資增、股價轉弱"]
    if has_institutional_sell and has_margin_rise:
        return 2, ["法人賣、融資增，籌碼背離"]
    return 0, []


def _margin_retail_risk(
    margin: pd.DataFrame,
    prices: pd.DataFrame,
    margin_rise_pct: float,
) -> tuple[int, list[str]]:
    if margin.empty or len(margin) < 4 or prices.empty or len(prices) < 4:
        return 0, []
    if "MarginPurchaseTodayBalance" not in margin.columns:
        return 0, []

    m = margin.sort_values("date")
    balance = m["MarginPurchaseTodayBalance"].astype(float)
    if balance.iloc[-4] <= 0:
        return 0, []

    margin_change = balance.iloc[-1] / balance.iloc[-4] - 1
    close = prices.sort_values("date")["close"].astype(float)
    price_change = close.iloc[-1] / close.iloc[-4] - 1

    if margin_change >= margin_rise_pct and price_change < 0:
        return 2, [f"融資增 {margin_change * 100:.1f}% 但股價跌"]
    if margin_change >= margin_rise_pct:
        return 1, [f"融資增 {margin_change * 100:.1f}%"]
    return 0, []
