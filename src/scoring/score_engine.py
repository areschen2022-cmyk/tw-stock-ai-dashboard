from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from src.indicators.chip import chip_score
from src.indicators.fundamental import fundamental_score
from src.indicators.market import market_adjustment as calc_market_adjustment
from src.indicators.risk import risk_score
from src.indicators.technical import technical_score
from src.indicators.trade_plan import trade_plan


@dataclass
class StockScore:
    stock_id: str
    total_score: int
    label: str
    price: float | None
    technical_score: int
    chip_score: int
    fundamental_score: int
    risk_score: int
    market_adjustment: int
    overseas_adjustment: int = 0
    opportunity_score: int = 0
    themes: list[str] = field(default_factory=list)
    theme_tiers: list[str] = field(default_factory=list)
    action: str = "只觀察"
    entry_condition: str = ""
    stop_reference: str = ""
    stop_price: float | None = None
    entry_limit_price: float | None = None
    vol_5min_threshold: float | None = None
    reasons: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    trigger_tags: list[str] = field(default_factory=list)

    @property
    def trigger_summary(self) -> str:
        """Human-readable summary: '題材升溫 + 外資買超 + 放量突破'"""
        return " + ".join(self.trigger_tags) if self.trigger_tags else "綜合訊號"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["trigger_summary"] = self.trigger_summary
        return d


def _build_trigger_tags(
    t_score: int,
    t_reasons: list[str],
    c_score: int,
    c_reasons: list[str],
    f_score: int,
    overseas_adj: int,
    opportunity_adj: int,
    themes: list[str],
) -> list[str]:
    """Distil all sub-scores and reasons into concise human-readable trigger tags.

    Tags are ordered: 題材 → 籌碼 → 技術 → 基本面 → 海外.
    Phase 2 will append a '收盤資金流入' tag from the capital-flow module.
    """
    tags: list[str] = []

    # ── 題材面 ──────────────────────────────────────────────
    if themes:
        if opportunity_adj >= 10:
            tags.append("題材強共振")
        elif opportunity_adj >= 5:
            tags.append("題材升溫")
        else:
            tags.append("題材關注")

    # ── 籌碼面 ──────────────────────────────────────────────
    has_foreign = any("外資" in r for r in c_reasons)
    has_trust = any("投信" in r for r in c_reasons)
    if has_foreign and has_trust:
        tags.append("法人共振")
    elif has_foreign:
        tags.append("外資買超")
    elif has_trust:
        tags.append("投信買超")
    elif c_score >= 18:
        tags.append("籌碼偏多")
    elif c_score >= 10:
        tags.append("法人關注")

    # ── 技術面 ──────────────────────────────────────────────
    if t_score > 0:
        t_text = " ".join(t_reasons)
        if "爆量" in t_text or ("量增" in t_text and "突破" in t_text):
            tags.append("放量突破")
        elif "突破" in t_text or "新高" in t_text:
            tags.append("技術突破")
        elif "均線多頭" in t_text or "趨勢向上" in t_text or "多頭排列" in t_text:
            tags.append("趨勢向上")
        elif t_score >= 15:
            tags.append("技術偏多")

    # ── 基本面 ──────────────────────────────────────────────
    if f_score >= 10:
        tags.append("營收加速")
    elif f_score >= 5:
        tags.append("營收回升")

    # ── 海外連動 ─────────────────────────────────────────────
    if overseas_adj >= 5:
        tags.append("美股映射")
    elif overseas_adj >= 3:
        tags.append("海外順風")

    return tags or ["綜合訊號"]


class ScoreEngine:
    def __init__(self, config: dict) -> None:
        self.config = config

    def market_adjustment(self, prices: pd.DataFrame) -> tuple[int, str, str | None]:
        market_cfg = self.config.get("market", {})
        return calc_market_adjustment(
            prices,
            ma_short=int(market_cfg.get("ma_short", 20)),
            ma_long=int(market_cfg.get("ma_long", 60)),
        )

    def score_stock(
        self,
        stock_id: str,
        bundle: dict[str, pd.DataFrame],
        market_adj: int,
        as_of: date,
        overseas_adj: int = 0,
        opportunity_adj: int = 0,
        opportunity_reasons: list[str] | None = None,
        themes: list[str] | None = None,
        theme_tiers: list[str] | None = None,
    ) -> StockScore:
        prices = bundle.get("prices", pd.DataFrame())
        min_days = int(self.config.get("data", {}).get("min_data_days", 25))
        if prices.empty or len(prices) < min_days:
            return StockScore(
                stock_id=stock_id,
                total_score=0,
                label="DATA_INSUFFICIENT",
                price=None,
                technical_score=0,
                chip_score=0,
                fundamental_score=0,
                risk_score=0,
                market_adjustment=market_adj,
                overseas_adjustment=overseas_adj,
                opportunity_score=opportunity_adj,
                themes=themes or [],
                theme_tiers=theme_tiers or [],
                action="只觀察",
                entry_condition="價格資料不足",
                stop_reference="價格資料不足",
                stop_price=None,
                entry_limit_price=None,
                vol_5min_threshold=None,
                warnings=[f"價格資料少於 {min_days} 筆"],
            )

        t_score, t_reasons = technical_score(prices)
        c_score, c_reasons = chip_score(
            bundle.get("institutional", pd.DataFrame()),
            bundle.get("margin", pd.DataFrame()),
            prices,
        )
        f_score, f_reasons = fundamental_score(bundle.get("revenue", pd.DataFrame()))
        r_score, r_reasons = risk_score(
            prices,
            bundle.get("dividend", pd.DataFrame()),
            as_of,
            dividend_warning_days=int(self.config.get("risk", {}).get("dividend_warning_days", 5)),
        )
        total = max(min(t_score + c_score + f_score + r_score + market_adj + overseas_adj + opportunity_adj, 100), 0)
        thresholds = self.config.get("thresholds", {})
        if total >= int(thresholds.get("buy_watch", 65)):
            label = "BUY_WATCH"
        elif total >= int(thresholds.get("wait_min", 50)):
            label = "WAIT"
        else:
            label = "AVOID"
        plan = trade_plan(total, prices, r_reasons)
        tags = _build_trigger_tags(
            t_score=t_score,
            t_reasons=t_reasons,
            c_score=c_score,
            c_reasons=c_reasons,
            f_score=f_score,
            overseas_adj=overseas_adj,
            opportunity_adj=opportunity_adj,
            themes=themes or [],
        )
        return StockScore(
            stock_id=stock_id,
            total_score=total,
            label=label,
            price=float(prices.sort_values("date")["close"].iloc[-1]),
            technical_score=t_score,
            chip_score=c_score,
            fundamental_score=f_score,
            risk_score=r_score,
            market_adjustment=market_adj,
            overseas_adjustment=overseas_adj,
            opportunity_score=opportunity_adj,
            themes=themes or [],
            theme_tiers=theme_tiers or [],
            action=plan["action"],
            entry_condition=plan["entry"],
            stop_reference=plan["stop"],
            stop_price=plan.get("stop_price"),
            entry_limit_price=plan.get("entry_limit_price"),
            vol_5min_threshold=plan.get("vol_5min_threshold"),
            reasons={
                "technical": t_reasons,
                "chip": c_reasons,
                "fundamental": f_reasons,
                "risk": r_reasons,
                "opportunity": opportunity_reasons or [],
            },
            trigger_tags=tags,
        )
