from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd
import requests

from src.data_provider.finmind_client import FinMindClient


class TwseClient:
    STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
    INDEX_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
    DIVIDEND_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"

    def __init__(
        self,
        fallback: FinMindClient | None = None,
        timeout: int = 20,
        cache_dir: Path | None = None,
    ) -> None:
        self.fallback = fallback or FinMindClient()
        self.timeout = timeout
        self.cache_dir = cache_dir or Path("data") / "cache" / "twse"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.status_counts = {"api": 0, "cache": 0, "quota": 0, "error": 0, "empty": 0, "fallback": 0}
        self._lock = Lock()
        self._today_all_lock = Lock()
        self._today_all_df: pd.DataFrame | None = None  # in-memory cache for STOCK_DAY_ALL
        self._valuation_lock = Lock()
        self._valuation_df: pd.DataFrame | None = None  # in-memory cache for BWIBBU_ALL
        self._sector_lock = Lock()
        self._sector_df: pd.DataFrame | None = None    # in-memory cache for MI_INDEX
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0; research dashboard)",
            "Accept": "application/json,text/plain,*/*",
        }

    def _count(self, key: str) -> None:
        with self._lock:
            self.status_counts[key] += 1

    def source_status(self) -> dict[str, Any]:
        fallback_status = self.fallback.source_status()
        error = self.status_counts["error"] + int(fallback_status.get("error", 0))
        quota = self.status_counts["quota"] + int(fallback_status.get("quota", 0))
        api = self.status_counts["api"] + int(fallback_status.get("api", 0))
        cache = self.status_counts["cache"] + int(fallback_status.get("cache", 0))
        recovered = api + cache + int(self.status_counts.get("fallback", 0))
        if error and recovered == 0:
            label = "錯誤"
        elif error:
            label = "部分限流"
        elif quota and api == 0 and cache == 0:
            label = "限流"
        elif quota:
            label = "部分限流"
        elif api or cache:
            label = "正常"
        else:
            label = "無資料"
        return {
            "label": label,
            **self.status_counts,
            "api": api,
            "cache": cache,
            "quota": quota,
            "error": error,
            "fallback_status": fallback_status,
        }

    def _cache_path(self, dataset: str, data_id: str, key: str) -> Path:
        safe_id = data_id.replace("^", "idx_").replace("/", "_").replace(" ", "_")
        return self.cache_dir / f"{dataset}__{safe_id}__{key}.json"

    def _month_segments(self, start_date: date, end_date: date) -> list[tuple[int, int]]:
        segments = []
        cursor = date(start_date.year, start_date.month, 1)
        while cursor <= end_date:
            segments.append((cursor.year, cursor.month))
            cursor = date(cursor.year + int(cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
        return segments

    # ── STOCK_DAY_ALL — batch today snapshot (shared across all stocks) ────
    def _get_today_all(self) -> pd.DataFrame:
        """Fetch STOCK_DAY_ALL once per day; in-memory + disk cached.

        Fields: Date(ROC 7-digit), Code, Name, TradeVolume, TradeValue,
                OpeningPrice, HighestPrice, LowestPrice, ClosingPrice, Change, Transaction.
        Thread-safe: only one actual HTTP request is made per process lifetime.
        """
        with self._today_all_lock:
            if self._today_all_df is not None:
                return self._today_all_df
            cache_path = self._cache_path("STOCK_DAY_ALL", "all", date.today().isoformat())
            if cache_path.exists():
                df = pd.read_json(cache_path, orient="records")
                self._today_all_df = df
                self._count("cache")
                return df
            try:
                response = requests.get(
                    self.STOCK_DAY_ALL_URL, headers=self.headers, timeout=self.timeout
                )
                response.raise_for_status()
                payload = response.json()
            except Exception:
                logging.warning("TWSE STOCK_DAY_ALL fetch failed")
                self._count("error")
                self._today_all_df = pd.DataFrame()
                return pd.DataFrame()
            df = pd.DataFrame(payload) if isinstance(payload, list) else pd.DataFrame()
            if df.empty:
                self._count("empty")
                self._today_all_df = pd.DataFrame()
                return df
            df.to_json(cache_path, orient="records", force_ascii=False)
            self._count("api")
            self._today_all_df = df
            return df

    def _stock_month(self, stock_id: str, year: int, month: int) -> pd.DataFrame:
        """Fetch one month of daily OHLCV for stock_id.

        Cache strategy:
        - Historical months (not current): cache never expires.
        - Current month: cache expires daily (mtime check). If stale, supplements
          from STOCK_DAY_ALL (one shared request) before falling back to STOCK_DAY API.
        """
        key = f"{year}-{month:02d}"
        cache_path = self._cache_path("STOCK_DAY", stock_id, key)
        today = date.today()
        is_current_month = (year == today.year and month == today.month)

        if cache_path.exists():
            if not is_current_month:
                # Historical month: immutable, always valid
                self._count("cache")
                return pd.read_json(cache_path, orient="records")
            # Current month: check if cache was written today
            cache_mtime = date.fromtimestamp(cache_path.stat().st_mtime)
            if cache_mtime == today:
                self._count("cache")
                return pd.read_json(cache_path, orient="records")
            # Cache is stale (written on a previous day) — fall through to refresh

        # Current month: try STOCK_DAY_ALL first to get today's row without a per-stock call
        if is_current_month:
            all_df = self._get_today_all()
            if not all_df.empty and "Code" in all_df.columns:
                match = all_df[all_df["Code"].astype(str) == str(stock_id)]
                if not match.empty:
                    r = match.iloc[0]
                    try:
                        row_date = _roc_compact_date(r.get("Date", ""))
                    except Exception:
                        row_date = today
                    new_entry = {
                        "date": row_date.isoformat(),
                        "stock_id": stock_id,
                        "open": _num(r.get("OpeningPrice", 0)),
                        "high": _num(r.get("HighestPrice", 0)),
                        "low": _num(r.get("LowestPrice", 0)),
                        "close": _num(r.get("ClosingPrice", 0)),
                        "volume": _num(r.get("TradeVolume", 0)),
                    }
                    # Merge new row with existing cache (previous days of this month)
                    if cache_path.exists():
                        existing = pd.read_json(cache_path, orient="records")
                        existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
                        existing = existing[existing["date"].dt.date != row_date]
                        merged = pd.concat([existing, pd.DataFrame([new_entry])], ignore_index=True)
                    else:
                        merged = pd.DataFrame([new_entry])
                    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
                    merged = merged.sort_values("date").reset_index(drop=True)
                    merged.to_json(cache_path, orient="records", force_ascii=False, date_format="iso")
                    return merged

        # Fall back: individual STOCK_DAY API call (full month)
        params = {
            "date": f"{year}{month:02d}01",
            "stockNo": stock_id,
            "response": "json",
        }
        try:
            response = requests.get(self.STOCK_DAY_URL, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            if "json" not in response.headers.get("Content-Type", "").lower() and response.text.lstrip().startswith("<"):
                self._count("empty")
                logging.warning("TWSE returned non-json stock price page for %s %s", stock_id, key)
                return pd.DataFrame()
            payload = response.json()
        except Exception:
            self._count("error")
            logging.warning("TWSE stock price fetch failed for %s %s", stock_id, key)
            return pd.DataFrame()
        rows = payload.get("data") or []
        if not rows:
            self._count("empty")
            return pd.DataFrame()
        parsed = []
        for row in rows:
            parsed.append(
                {
                    "date": _roc_slash_date(row[0]).isoformat(),
                    "stock_id": stock_id,
                    "open": _num(row[3]),
                    "high": _num(row[4]),
                    "low": _num(row[5]),
                    "close": _num(row[6]),
                    "volume": _num(row[1]),
                }
            )
        df = pd.DataFrame(parsed)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df.to_json(cache_path, orient="records", force_ascii=False, date_format="iso")
        self._count("api")
        return df

    def stock_prices(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        frames = []
        missing = False
        for year, month in self._month_segments(start_date, end_date):
            frame = self._stock_month(stock_id, year, month)
            if frame.empty:
                missing = True
            else:
                frames.append(frame)
        if missing:
            self._count("fallback")
            fallback = self.fallback.stock_prices(stock_id, start_date, end_date)
            if not fallback.empty:
                return fallback
        if not frames:
            self._count("fallback")
            return self.fallback.stock_prices(stock_id, start_date, end_date)
        df = pd.concat(frames, ignore_index=True)
        dates = pd.to_datetime(df["date"], errors="coerce").dt.date
        return df[(dates >= start_date) & (dates <= end_date)]

    def institutional(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        self._count("fallback")
        return self.fallback.institutional(stock_id, start_date, end_date)

    def margin(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        self._count("fallback")
        return self.fallback.margin(stock_id, start_date, end_date)

    def monthly_revenue(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        self._count("fallback")
        return self.fallback.monthly_revenue(stock_id, start_date, end_date)

    def dividend(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        cache_path = self._cache_path("TWT48U_ALL", "all", date.today().isoformat())
        if cache_path.exists():
            self._count("cache")
            df = pd.read_json(cache_path, orient="records")
        else:
            try:
                response = requests.get(self.DIVIDEND_URL, headers=self.headers, timeout=self.timeout)
                response.raise_for_status()
                df = pd.DataFrame(response.json())
            except Exception:
                self._count("error")
                logging.exception("TWSE dividend fetch failed")
                self._count("fallback")
                return self.fallback.dividend(stock_id, start_date, end_date)
            if df.empty:
                self._count("empty")
                self._count("fallback")
                return self.fallback.dividend(stock_id, start_date, end_date)
            df.to_json(cache_path, orient="records", force_ascii=False, date_format="iso")
            self._count("api")
        if "Code" not in df.columns:
            return pd.DataFrame()
        rows = df[df["Code"].astype(str) == str(stock_id)].copy()
        if rows.empty:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "date": [_roc_compact_date(value).isoformat() for value in rows["Date"]],
                "stock_id": rows["Code"].astype(str),
                "CashDividend": rows.get("CashDividend", pd.Series([""] * len(rows))).map(_num),
            }
        )

    # ── Valuation snapshot: PE / PB / Dividend Yield (BWIBBU_ALL) ─────────
    def valuation_today(self) -> pd.DataFrame:
        """Fetch PE ratio, PB ratio, dividend yield for all TWSE stocks (today's snapshot).

        Returns DataFrame with columns: Date, Code, Name, PEratio, DividendYield, PBratio.
        Empty strings indicate missing data for that stock. Cached once per calendar day.
        Thread-safe: in-memory + disk cache; only one HTTP request per process lifetime.
        """
        with self._valuation_lock:
            if self._valuation_df is not None:
                return self._valuation_df
            cache_path = self._cache_path("BWIBBU_ALL", "all", date.today().isoformat())
            if cache_path.exists():
                df = pd.read_json(cache_path, orient="records")
                self._valuation_df = df
                self._count("cache")
                return df
            try:
                response = requests.get(self.VALUATION_URL, headers=self.headers, timeout=self.timeout)
                response.raise_for_status()
                df = pd.DataFrame(response.json())
            except Exception:
                self._count("error")
                logging.warning("TWSE valuation (BWIBBU_ALL) fetch failed")
                self._valuation_df = pd.DataFrame()
                return pd.DataFrame()
            if df.empty:
                self._count("empty")
                self._valuation_df = pd.DataFrame()
                return pd.DataFrame()
            df.to_json(cache_path, orient="records", force_ascii=False)
            self._count("api")
            self._valuation_df = df
            return df

    def _valuation_for_stock(self, stock_id: str) -> dict[str, float | None]:
        """Return pe/pb/div_yield for one stock from today's BWIBBU_ALL snapshot.

        Returns a dict with keys 'pe', 'pb', 'div_yield'; values are float or None
        when the field is unavailable or zero (e.g. loss-making stocks have no PE).
        """
        df = self.valuation_today()
        if df.empty or "Code" not in df.columns:
            return {"pe": None, "pb": None, "div_yield": None}
        match = df[df["Code"].astype(str) == str(stock_id)]
        if match.empty:
            return {"pe": None, "pb": None, "div_yield": None}
        r = match.iloc[0]
        return {
            "pe": _safe_float(r.get("PEratio")),
            "pb": _safe_float(r.get("PBratio")),
            "div_yield": _safe_float(r.get("DividendYield")),
        }

    # ── Sector / market indices (MI_INDEX) ─────────────────────────────────
    def sector_indices_today(self) -> pd.DataFrame:
        """Fetch all TWSE sector and market index closing values for today.

        Normalises Chinese field names to English:
          index_name, close, direction, change_pts, change_pct (signed float).
        Cached once per calendar day.
        Thread-safe: in-memory + disk cache; only one HTTP request per process lifetime.
        """
        with self._sector_lock:
            if self._sector_df is not None:
                return self._sector_df
            cache_path = self._cache_path("MI_INDEX", "all", date.today().isoformat())
            if cache_path.exists():
                df = pd.read_json(cache_path, orient="records")
                self._sector_df = df
                self._count("cache")
                return df
            try:
                response = requests.get(self.INDEX_URL, headers=self.headers, timeout=self.timeout)
                response.raise_for_status()
                raw = pd.DataFrame(response.json())
            except Exception:
                self._count("error")
                logging.warning("TWSE sector index (MI_INDEX) fetch failed")
                self._sector_df = pd.DataFrame()
                return pd.DataFrame()
            if raw.empty:
                self._count("empty")
                self._sector_df = pd.DataFrame()
                return pd.DataFrame()
            rename_map = {
                "日期": "date",
                "指數": "index_name",
                "收盤指數": "close",
                "漲跌": "direction",
                "漲跌點數": "change_pts",
                "漲跌百分比": "change_pct",
                "特殊處理註記": "notes",
            }
            df = raw.rename(columns={k: v for k, v in rename_map.items() if k in raw.columns})
            # Combine direction (+/-) with magnitude to produce a signed float
            # MI_INDEX direction column may be "+" / "-" or Chinese "漲"/"跌"
            if "change_pct" in df.columns and "direction" in df.columns:
                def _signed_pct(row: pd.Series) -> float:
                    try:
                        val = float(str(row["change_pct"]).replace(",", "").strip())
                        dir_str = str(row.get("direction", "+")).strip()
                        is_neg = dir_str == "-" or dir_str == "跌" or dir_str.startswith("-")
                        return -abs(val) if is_neg else abs(val)
                    except (ValueError, TypeError):
                        return 0.0
                df["change_pct"] = df.apply(_signed_pct, axis=1)
            df.to_json(cache_path, orient="records", force_ascii=False)
            self._count("api")
            self._sector_df = df
            return df

    def overseas_bundle(self, start_date: date, end_date: date) -> dict[str, pd.DataFrame]:
        self._count("fallback")
        return self.fallback.overseas_bundle(start_date, end_date)

    def stock_bundle(
        self,
        stock_id: str,
        start_date: date,
        end_date: date,
        include_dividend: bool = True,
    ) -> dict[str, pd.DataFrame | dict]:
        revenue_start = end_date.replace(day=1)
        revenue_start = date(revenue_start.year - 2, revenue_start.month, 1)
        return {
            "prices": self.stock_prices(stock_id, start_date, end_date),
            "institutional": self.institutional(stock_id, start_date, end_date),
            "margin": self.margin(stock_id, start_date, end_date),
            "revenue": self.monthly_revenue(stock_id, revenue_start, end_date),
            "dividend": self.dividend(stock_id, start_date, end_date) if include_dividend else pd.DataFrame(),
            "valuation": self._valuation_for_stock(stock_id),  # {pe, pb, div_yield}
        }


# ── Module-level helpers ───────────────────────────────────────────────────

def _num(value: object) -> float:
    text = str(value).replace(",", "").strip()
    if text in {"", "--", "nan", "None"}:
        return 0.0
    return float(text)


def _safe_float(value: object) -> float | None:
    """Convert value to positive float, returning None for empty/zero/invalid."""
    try:
        v = float(str(value).strip())
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _roc_slash_date(value: object) -> date:
    year, month, day = str(value).split("/")[:3]
    return date(int(year) + 1911, int(month), int(day))


def _roc_compact_date(value: object) -> date:
    text = str(value).strip()
    if len(text) < 7:
        raise ValueError(f"Invalid ROC date: {value}")
    return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
