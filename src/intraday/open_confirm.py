"""
open_confirm.py — 9:10 intraday open-condition checker

For each A/B-grade candidate saved by the morning screener, fetch the
first 9 minutes of minute data (09:00–09:08) from FinMind, then evaluate:

  1. Gap check  — open price <= entry_limit_price (not chasing)
  2. Volume     — first-5-min volume >= vol_5min_threshold (日均量 5%)
  3. Price hold — latest price > stop_price (not already stopped out)

Returns a list of ConfirmResult objects ready for Telegram formatting.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

# Minutes to collect for the "open burst" window (Taiwan opens 09:00)
_OPEN_BURST_END = "09:04"   # 09:00 ~ 09:04 inclusive = 5 bars


@dataclass
class ConfirmResult:
    stock_id: str
    name: str
    total_score: int
    grade: str
    action: str
    prev_close: float | None
    open_price: float | None
    latest_price: float | None
    gap_pct: float | None          # (open - prev_close) / prev_close * 100
    entry_limit_price: float | None
    stop_price: float | None
    vol_5min_actual: float | None  # shares
    vol_5min_threshold: float | None  # shares
    gap_ok: bool | None            # None = data unavailable
    vol_ok: bool | None
    price_hold: bool | None
    passed: bool
    reason: str                    # human-readable pass/fail reason (Chinese)
    no_data: bool = False          # True when FinMind returned nothing


def _vol_display(shares: float | None) -> str:
    if shares is None:
        return "N/A"
    zhang = shares / 1000
    if zhang >= 1:
        return f"{zhang:.0f} 張"
    return f"{shares:.0f} 股"


def check_candidates(
    candidates: list[dict],
    intraday_fn,          # callable(stock_id: str, trade_date: date) -> pd.DataFrame
    trade_date: date,
) -> list[ConfirmResult]:
    """
    Parameters
    ----------
    candidates   : list of dicts from SQLiteStore.watch_candidates_today()
    intraday_fn  : provider.intraday_prices bound method
    trade_date   : today's date

    Returns
    -------
    list[ConfirmResult] sorted: passed first, then by score desc.
    """
    results: list[ConfirmResult] = []

    for cand in candidates:
        stock_id = cand["stock_id"]
        name = cand["name"]
        score = cand["total_score"]
        grade = cand["grade"] or "-"
        action = cand["action"] or "只觀察"
        prev_close = cand.get("prev_close")
        entry_limit = cand.get("entry_limit_price")
        stop_price = cand.get("stop_price")
        vol_threshold = cand.get("vol_5min_threshold")

        try:
            minute_df = intraday_fn(stock_id, trade_date)
        except Exception as exc:
            logger.warning("intraday fetch failed for %s: %s", stock_id, exc)
            minute_df = pd.DataFrame()

        if minute_df.empty or "time" not in minute_df.columns:
            results.append(ConfirmResult(
                stock_id=stock_id, name=name, total_score=score, grade=grade,
                action=action, prev_close=prev_close, open_price=None,
                latest_price=None, gap_pct=None, entry_limit_price=entry_limit,
                stop_price=stop_price, vol_5min_actual=None,
                vol_5min_threshold=vol_threshold,
                gap_ok=None, vol_ok=None, price_hold=None,
                passed=False, reason="分鐘資料尚未可取得", no_data=True,
            ))
            continue

        # ── first 5-minute window ─────────────────────────────────────────
        burst = minute_df[minute_df["time"] <= _OPEN_BURST_END]
        open_price = float(burst["open"].iloc[0]) if not burst.empty else None
        latest_price = float(minute_df["close"].iloc[-1])
        vol_5min_actual = float(burst["volume"].sum()) if not burst.empty else 0.0

        # ── gap % ─────────────────────────────────────────────────────────
        gap_pct: float | None = None
        if open_price is not None and prev_close and prev_close > 0:
            gap_pct = (open_price - prev_close) / prev_close * 100

        # ── individual checks ─────────────────────────────────────────────
        gap_ok: bool | None = None
        if open_price is not None and entry_limit is not None:
            gap_ok = open_price <= entry_limit

        vol_ok: bool | None = None
        if vol_threshold is not None and vol_threshold > 0:
            vol_ok = vol_5min_actual >= vol_threshold

        price_hold: bool | None = None
        if stop_price is not None:
            price_hold = latest_price > stop_price

        # ── overall pass ──────────────────────────────────────────────────
        checks = [c for c in (gap_ok, vol_ok, price_hold) if c is not None]
        passed = bool(checks) and all(checks)

        # ── reason string ─────────────────────────────────────────────────
        parts: list[str] = []
        if gap_ok is False:
            parts.append(f"跳空過大（開 {open_price:.2f}，超過上限 {entry_limit:.2f}）")
        elif gap_ok is True and gap_pct is not None:
            parts.append(f"開盤 {open_price:.2f}（+{gap_pct:.1f}%，未超限）")
        if vol_ok is False:
            parts.append(
                f"量能不足（前5分 {_vol_display(vol_5min_actual)} < 門檻 {_vol_display(vol_threshold)}）"
            )
        elif vol_ok is True:
            parts.append(
                f"前5分量 {_vol_display(vol_5min_actual)} >= {_vol_display(vol_threshold)} ✓"
            )
        if price_hold is False:
            parts.append(f"已跌破止損 {stop_price:.2f}")
        reason = "｜".join(parts) if parts else "資料不完整"

        results.append(ConfirmResult(
            stock_id=stock_id, name=name, total_score=score, grade=grade,
            action=action, prev_close=prev_close, open_price=open_price,
            latest_price=latest_price, gap_pct=gap_pct,
            entry_limit_price=entry_limit, stop_price=stop_price,
            vol_5min_actual=vol_5min_actual, vol_5min_threshold=vol_threshold,
            gap_ok=gap_ok, vol_ok=vol_ok, price_hold=price_hold,
            passed=passed, reason=reason,
        ))

    # sort: passed first, then by score desc
    results.sort(key=lambda r: (0 if r.passed else 1, -r.total_score))
    return results


def format_telegram(results: list[ConfirmResult], trade_date: date, check_time: str = "09:10") -> str:
    """Build the Telegram HTML message for the intraday confirmation push."""
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed and not r.no_data]
    no_data = [r for r in results if r.no_data]

    lines: list[str] = [
        f"🔔 <b>盤中確認｜{check_time}</b>｜{trade_date.isoformat()}",
        "",
    ]

    # ── Passed ───────────────────────────────────────────────────────────
    if passed:
        lines.append(f"✅ <b>通過開盤條件（{len(passed)} 檔）：</b>")
        for r in passed:
            limit_str = f"上限 {r.entry_limit_price:.2f}" if r.entry_limit_price else ""
            stop_str = f"止損 {r.stop_price:.2f}" if r.stop_price else ""
            numbers = "｜".join(x for x in [limit_str, stop_str] if x)
            plan_str = f"{r.action}" + (f"（{numbers}）" if numbers else "")
            lines.append(
                f"▸ <b>{r.stock_id} {r.name}</b>｜{r.total_score}/100｜{r.grade}級\n"
                f"  📊 {r.reason}\n"
                f"  🎯 {plan_str}"
            )
        lines.append("")
    else:
        lines.append("❌ <b>今日暫無股票通過開盤確認條件</b>")
        lines.append("")

    # ── Failed ───────────────────────────────────────────────────────────
    if failed:
        lines.append(f"🚫 <b>條件未過（{len(failed)} 檔）：</b>")
        for r in failed:
            lines.append(f"▸ {r.stock_id} {r.name} — {r.reason}")
        lines.append("")

    # ── No data ──────────────────────────────────────────────────────────
    if no_data:
        ids = "、".join(f"{r.stock_id}" for r in no_data)
        lines.append(f"⏳ 資料暫缺（{ids}），待下次確認")
        lines.append("")

    lines.append("⚠️ 僅供研究追蹤，不是投資建議。")
    return "\n".join(lines)
