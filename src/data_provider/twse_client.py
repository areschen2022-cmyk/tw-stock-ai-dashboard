from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
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
    INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
    MARGIN_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    TPEX_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
    TPEX_EMERGING_REVENUE_URL = "https://www.tpex.org.tw/openapi/v1/t187ap05_R"
    TPEX_QUOTES_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
    TPEX_MARGIN_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"

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
        self.status_events: list[dict[str, Any]] = []
        self._lock = Lock()
        self._today_all_lock = Lock()
        self._today_all_df: pd.DataFrame | None = None  # in-memory cache for STOCK_DAY_ALL
        self._valuation_lock = Lock()
        self._valuation_df: pd.DataFrame | None = None  # in-memory cache for BWIBBU_ALL
        self._sector_lock = Lock()
        self._sector_df: pd.DataFrame | None = None    # in-memory cache for MI_INDEX
        self._institutional_lock = Lock()
        self._institutional_df: pd.DataFrame | None = None
        self._margin_lock = Lock()
        self._margin_df: pd.DataFrame | None = None
        self._revenue_lock = Lock()
        self._revenue_df: pd.DataFrame | None = None
        self._tpex_revenue_lock = Lock()
        self._tpex_revenue_df: pd.DataFrame | None = None
        self._tpex_emerging_revenue_lock = Lock()
        self._tpex_emerging_revenue_df: pd.DataFrame | None = None
        self._tpex_quotes_lock = Lock()
        self._tpex_quotes_df: pd.DataFrame | None = None
        self._tpex_institutional_lock = Lock()
        self._tpex_institutional_df: pd.DataFrame | None = None
        self._tpex_margin_lock = Lock()
        self._tpex_margin_df: pd.DataFrame | None = None
        self.official_snapshots: dict[str, dict[str, Any]] = {}
        self.market_snapshots: dict[str, dict[str, Any]] = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0; research dashboard)",
            "Accept": "application/json,text/plain,*/*",
        }

    def _count(self, key: str, *, record_event: bool = True, **event: Any) -> None:
        with self._lock:
            self.status_counts[key] += 1
            if record_event and key in {"quota", "error", "empty", "fallback"}:
                self.status_events.append({"type": key, **event})

    def source_status(self) -> dict[str, Any]:
        fallback_status = self.fallback.source_status()
        fallback_events = fallback_status.get("events", []) if isinstance(fallback_status, dict) else []
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
            "events": [*self.status_events, *fallback_events][-20:],
            "fallback_status": fallback_status,
            "official_snapshots": self.official_snapshots,
            "market_snapshots": self.market_snapshots,
        }

    def _cache_path(self, dataset: str, data_id: str, key: str) -> Path:
        safe_id = data_id.replace("^", "idx_").replace("/", "_").replace(" ", "_")
        return self.cache_dir / f"{dataset}__{safe_id}__{key}.json"

    def _official_history_path(self, dataset: str, stock_id: str) -> Path:
        history_dir = self.cache_dir / "official_history"
        history_dir.mkdir(parents=True, exist_ok=True)
        return history_dir / f"{dataset}__{stock_id}.json"

    def _load_official_history(self, dataset: str, stock_id: str) -> pd.DataFrame:
        path = self._official_history_path(dataset, stock_id)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_json(path, orient="records")

    def _save_official_history(
        self,
        dataset: str,
        stock_id: str,
        current: pd.DataFrame,
        *,
        subset: list[str],
    ) -> pd.DataFrame:
        history = self._load_official_history(dataset, stock_id)
        frames = [frame for frame in (history, current) if not frame.empty]
        if not frames:
            return pd.DataFrame()
        merged = pd.concat(frames, ignore_index=True)
        if "date" in merged.columns:
            merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
        merged = merged.drop_duplicates(subset=subset, keep="last")
        if "date" in merged.columns:
            merged = merged.sort_values("date")
        merged.to_json(
            self._official_history_path(dataset, stock_id),
            orient="records",
            force_ascii=False,
            date_format="iso",
        )
        return merged.reset_index(drop=True)

    def _cached_fallback(
        self,
        dataset: str,
        stock_id: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        cached_only = getattr(self.fallback, "cached_only", None)
        if not callable(cached_only):
            return pd.DataFrame()
        return cached_only(dataset, stock_id, start_date, end_date)

    def _complete_history_if_short(
        self,
        merged: pd.DataFrame,
        *,
        minimum_rows: int,
        minimum_span_days: int,
        fetcher,
        dataset: str,
        stock_id: str,
        start_date: date,
        end_date: date,
        subset: list[str],
    ) -> pd.DataFrame:
        """Use network fallback only on a cold/short history, never for a healthy cache."""
        if (end_date - start_date).days < minimum_span_days or len(merged) >= minimum_rows:
            return merged
        self._count("fallback", dataset=dataset, data_id=stock_id, reason="cold_history_short")
        fallback = fetcher(stock_id, start_date, end_date)
        return _merge_frames(fallback, merged, subset=subset, start_date=start_date, end_date=end_date)

    def _latest_official_trade_date(self) -> date | None:
        all_df = self._get_today_all()
        if all_df.empty or "Date" not in all_df.columns:
            return None
        for value in all_df["Date"].dropna().astype(str):
            try:
                return _roc_compact_date(value)
            except ValueError:
                continue
        return None

    def _is_current_official_snapshot(self, snapshot_date: date | None, end_date: date) -> bool:
        return bool(
            snapshot_date
            and snapshot_date <= end_date
            and end_date - snapshot_date <= timedelta(days=7)
        )

    def _is_twse_stock(self, stock_id: str) -> bool:
        all_df = self._get_today_all()
        return bool(
            not all_df.empty
            and "Code" in all_df.columns
            and (all_df["Code"].astype(str) == str(stock_id)).any()
        )

    def _is_tpex_stock(self, stock_id: str) -> bool:
        quotes, _ = self._tpex_quotes_today(date.today())
        return bool(
            not quotes.empty
            and "SecuritiesCompanyCode" in quotes.columns
            and (quotes["SecuritiesCompanyCode"].astype(str) == str(stock_id)).any()
        )

    def market_universe(self, as_of: date | None = None) -> list[dict[str, Any]]:
        """Return official listed/OTC candidates ranked by turnover.

        This is intentionally a broad, shallow market snapshot. It avoids
        per-stock requests and is used only to decide which extra stocks deserve
        deeper scoring in the layered scanner.
        """
        end_date = as_of or date.today()
        rows: list[dict[str, Any]] = []

        twse = self._get_today_all()
        if not twse.empty:
            for _, row in twse.iterrows():
                stock_id = str(row.get("Code") or "").strip()
                if not _is_common_stock_code(stock_id):
                    continue
                rows.append(
                    {
                        "stock_id": stock_id,
                        "name": str(row.get("Name") or "").strip(),
                        "market": "listed",
                        "trade_value": _num(row.get("TradeValue", 0)),
                        "volume": _num(row.get("TradeVolume", 0)),
                    }
                )

        tpex, _ = self._tpex_quotes_today(end_date)
        if not tpex.empty:
            for _, row in tpex.iterrows():
                stock_id = str(row.get("SecuritiesCompanyCode") or "").strip()
                if not _is_common_stock_code(stock_id):
                    continue
                rows.append(
                    {
                        "stock_id": stock_id,
                        "name": str(row.get("CompanyName") or row.get("SecuritiesCompanyName") or "").strip(),
                        "market": "otc",
                        "trade_value": _num(_first_existing(row, ["TradingValue", "TransactionAmount", "TradeValue"])),
                        "volume": _num(_first_existing(row, ["TradingShares", "TradingVolume", "TradeVolume"])),
                    }
                )

        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            current = deduped.get(row["stock_id"])
            if current is None or float(row.get("trade_value") or 0) > float(current.get("trade_value") or 0):
                deduped[row["stock_id"]] = row
        result = sorted(deduped.values(), key=lambda item: float(item.get("trade_value") or 0), reverse=True)
        self.market_snapshots["universe"] = {
            "date": end_date.isoformat(),
            "valid": bool(result),
            "rows": len(result),
            "source": "official",
        }
        return result

    def _record_official_snapshot(
        self,
        dataset: str,
        snapshot_date: date | None,
        *,
        valid: bool,
        rows: int,
    ) -> None:
        self.official_snapshots[dataset] = {
            "date": snapshot_date.isoformat() if snapshot_date else "",
            "valid": valid,
            "rows": rows,
            "source": "official",
        }

    def _record_market_snapshot(
        self,
        dataset: str,
        snapshot_date: date | None,
        *,
        valid: bool,
        rows: int,
        source: str,
    ) -> None:
        self.market_snapshots[dataset] = {
            "date": snapshot_date.isoformat() if snapshot_date else "",
            "valid": valid,
            "rows": rows,
            "source": source,
        }

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
                self._count("error", dataset="STOCK_DAY_ALL", data_id="all", reason="fetch_failed")
                self._today_all_df = pd.DataFrame()
                return pd.DataFrame()
            df = pd.DataFrame(payload) if isinstance(payload, list) else pd.DataFrame()
            if df.empty:
                self._count("empty", dataset="STOCK_DAY_ALL", data_id="all")
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
                self._count("empty", dataset="STOCK_DAY", data_id=stock_id, period=key, reason="html")
                logging.warning("TWSE returned non-json stock price page for %s %s", stock_id, key)
                return pd.DataFrame()
            payload = response.json()
        except Exception:
            self._count("error", dataset="STOCK_DAY", data_id=stock_id, period=key, reason="fetch_failed")
            logging.warning("TWSE stock price fetch failed for %s %s", stock_id, key)
            return pd.DataFrame()
        rows = payload.get("data") or []
        if not rows:
            self._count("empty", dataset="STOCK_DAY", data_id=stock_id, period=key)
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
        if self._is_tpex_stock(stock_id):
            quotes, snapshot_date = self._tpex_quotes_today(end_date)
            current = pd.DataFrame()
            if snapshot_date is not None:
                rows = quotes[quotes["SecuritiesCompanyCode"].astype(str) == str(stock_id)]
                if not rows.empty:
                    row = rows.iloc[0]
                    current = pd.DataFrame([{
                        "date": snapshot_date,
                        "stock_id": stock_id,
                        "open": _num(row.get("Open", 0)),
                        "high": _num(row.get("High", 0)),
                        "low": _num(row.get("Low", 0)),
                        "close": _num(row.get("Close", 0)),
                        "volume": _num(row.get("TradingShares", 0)),
                    }])
            official = self._save_official_history("prices", stock_id, current, subset=["date"])
            cached = self._cached_fallback("TaiwanStockPrice", stock_id, start_date, end_date)
            merged = _merge_frames(cached, official, subset=["date"], start_date=start_date, end_date=end_date)
            if not merged.empty and ((end_date - start_date).days <= 7 or len(merged) >= 20):
                return merged
            self._count("fallback", record_event=False)
            fallback = self.fallback.stock_prices(stock_id, start_date, end_date)
            return _merge_frames(fallback, official, subset=["date"], start_date=start_date, end_date=end_date)

        frames = []
        missing = False
        for year, month in self._month_segments(start_date, end_date):
            frame = self._stock_month(stock_id, year, month)
            if frame.empty:
                missing = True
            else:
                frames.append(frame)
        if missing:
            self._count("fallback", dataset="stock_prices", data_id=stock_id, reason="twse_month_missing")
            fallback = self.fallback.stock_prices(stock_id, start_date, end_date)
            if not fallback.empty:
                return fallback
        if not frames:
            self._count("fallback", dataset="stock_prices", data_id=stock_id, reason="twse_all_missing")
            return self.fallback.stock_prices(stock_id, start_date, end_date)
        df = pd.concat(frames, ignore_index=True)
        dates = pd.to_datetime(df["date"], errors="coerce").dt.date
        return df[(dates >= start_date) & (dates <= end_date)]

    def _tpex_quotes_today(self, end_date: date) -> tuple[pd.DataFrame, date | None]:
        with self._tpex_quotes_lock:
            if self._tpex_quotes_df is not None:
                return self._tpex_quotes_df, _snapshot_date(self._tpex_quotes_df)
            raw = self._official_list_snapshot("tpex_quotes", self.TPEX_QUOTES_URL)
            snapshot_date = _snapshot_date(raw)
            valid = self._is_current_official_snapshot(snapshot_date, end_date)
            if not valid:
                raw = pd.DataFrame()
            self._tpex_quotes_df = raw
            self._record_official_snapshot("tpex_quotes", snapshot_date, valid=valid and not raw.empty, rows=len(raw))
            return raw, snapshot_date

    def _official_list_snapshot(self, dataset: str, url: str) -> pd.DataFrame:
        cache_path = self._cache_path(dataset, "all", date.today().isoformat())
        if cache_path.exists():
            self._count("cache")
            return pd.read_json(cache_path, orient="records")
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            raw = pd.DataFrame(response.json())
        except Exception:
            self._count("error", dataset=dataset, data_id="all", reason="fetch_failed")
            return pd.DataFrame()
        if raw.empty:
            self._count("empty", dataset=dataset, data_id="all")
            return raw
        raw.to_json(cache_path, orient="records", force_ascii=False)
        self._count("api")
        return raw

    def _institutional_today(self, end_date: date) -> tuple[pd.DataFrame, date | None]:
        with self._institutional_lock:
            snapshot_date = self._latest_official_trade_date()
            valid = self._is_current_official_snapshot(snapshot_date, end_date)
            if self._institutional_df is not None:
                return self._institutional_df, snapshot_date
            if not valid or snapshot_date is None:
                self._record_official_snapshot("institutional", snapshot_date, valid=False, rows=0)
                self._institutional_df = pd.DataFrame()
                return self._institutional_df, snapshot_date
            cache_path = self._cache_path("T86", "all", snapshot_date.isoformat())
            if cache_path.exists():
                raw = pd.read_json(cache_path, orient="records")
                self._count("cache")
            else:
                try:
                    response = requests.get(
                        self.INSTITUTIONAL_URL,
                        params={"response": "json", "date": snapshot_date.strftime("%Y%m%d"), "selectType": "ALLBUT0999"},
                        headers=self.headers,
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    raw = pd.DataFrame(payload.get("data") or [], columns=payload.get("fields") or [])
                except Exception:
                    self._count("error", dataset="T86", data_id="all", reason="fetch_failed")
                    raw = pd.DataFrame()
                if not raw.empty:
                    raw.to_json(cache_path, orient="records", force_ascii=False)
                    self._count("api")
            self._institutional_df = raw
            self._record_official_snapshot("institutional", snapshot_date, valid=not raw.empty, rows=len(raw))
            return raw, snapshot_date

    def institutional(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        raw, snapshot_date = self._institutional_today(end_date)
        current = pd.DataFrame()
        if not raw.empty and snapshot_date is not None and "證券代號" in raw.columns:
            rows = raw[raw["證券代號"].astype(str) == str(stock_id)]
            if not rows.empty:
                row = rows.iloc[0]
                dealer_buy = _num(row.get("自營商買進股數(自行買賣)", 0)) + _num(row.get("自營商買進股數(避險)", 0))
                dealer_sell = _num(row.get("自營商賣出股數(自行買賣)", 0)) + _num(row.get("自營商賣出股數(避險)", 0))
                current = pd.DataFrame(
                    [
                        {"date": snapshot_date, "stock_id": stock_id, "name": "Foreign_Investor", "buy": _num(row.get("外陸資買進股數(不含外資自營商)", 0)), "sell": _num(row.get("外陸資賣出股數(不含外資自營商)", 0))},
                        {"date": snapshot_date, "stock_id": stock_id, "name": "Investment_Trust", "buy": _num(row.get("投信買進股數", 0)), "sell": _num(row.get("投信賣出股數", 0))},
                        {"date": snapshot_date, "stock_id": stock_id, "name": "Dealer", "buy": dealer_buy, "sell": dealer_sell},
                    ]
                )
        if not current.empty or self._is_twse_stock(stock_id):
            official = self._save_official_history("institutional", stock_id, current, subset=["date", "name"])
            cached = self._cached_fallback("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start_date, end_date)
            merged = _merge_frames(cached, official, subset=["date", "name"], start_date=start_date, end_date=end_date)
            return self._complete_history_if_short(
                merged,
                minimum_rows=9,
                minimum_span_days=14,
                fetcher=self.fallback.institutional,
                dataset="institutional",
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date,
                subset=["date", "name"],
            )
        tpex_raw, tpex_date = self._tpex_institutional_today(end_date)
        if not tpex_raw.empty and tpex_date is not None:
            rows = tpex_raw[tpex_raw["SecuritiesCompanyCode"].astype(str) == str(stock_id)]
            if not rows.empty:
                row = rows.iloc[0]
                current = pd.DataFrame([
                    {"date": tpex_date, "stock_id": stock_id, "name": "Foreign_Investor", "buy": _num(row.get("ForeignInvestorsIncludeMainlandAreaInvestors-TotalBuy", 0)), "sell": _num(row.get("ForeignInvestorsIncludeMainlandAreaInvestors-TotalSell", 0))},
                    {"date": tpex_date, "stock_id": stock_id, "name": "Investment_Trust", "buy": _num(row.get("SecuritiesInvestmentTrustCompanies-TotalBuy", 0)), "sell": _num(row.get("SecuritiesInvestmentTrustCompanies-TotalSell", 0))},
                    {"date": tpex_date, "stock_id": stock_id, "name": "Dealer", "buy": _num(row.get("Dealers-TotalBuy", 0)), "sell": _num(row.get("Dealers-TotalSell", 0))},
                ])
        if not current.empty or self._is_tpex_stock(stock_id):
            official = self._save_official_history("institutional", stock_id, current, subset=["date", "name"])
            cached = self._cached_fallback("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start_date, end_date)
            merged = _merge_frames(cached, official, subset=["date", "name"], start_date=start_date, end_date=end_date)
            return self._complete_history_if_short(
                merged,
                minimum_rows=9,
                minimum_span_days=14,
                fetcher=self.fallback.institutional,
                dataset="institutional",
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date,
                subset=["date", "name"],
            )
        self._count("fallback", record_event=False)
        return self.fallback.institutional(stock_id, start_date, end_date)

    def _tpex_institutional_today(self, end_date: date) -> tuple[pd.DataFrame, date | None]:
        with self._tpex_institutional_lock:
            if self._tpex_institutional_df is not None:
                return self._tpex_institutional_df, _snapshot_date(self._tpex_institutional_df)
            raw = self._official_list_snapshot("tpex_institutional", self.TPEX_INSTITUTIONAL_URL)
            snapshot_date = _snapshot_date(raw)
            valid = self._is_current_official_snapshot(snapshot_date, end_date)
            if not valid:
                raw = pd.DataFrame()
            self._tpex_institutional_df = raw
            self._record_official_snapshot("tpex_institutional", snapshot_date, valid=valid and not raw.empty, rows=len(raw))
            return raw, snapshot_date

    def _margin_today(self, end_date: date) -> tuple[pd.DataFrame, date | None]:
        with self._margin_lock:
            snapshot_date = self._latest_official_trade_date()
            valid = self._is_current_official_snapshot(snapshot_date, end_date)
            if self._margin_df is not None:
                return self._margin_df, snapshot_date
            if not valid or snapshot_date is None:
                self._record_official_snapshot("margin", snapshot_date, valid=False, rows=0)
                self._margin_df = pd.DataFrame()
                return self._margin_df, snapshot_date
            cache_path = self._cache_path("MI_MARGN", "all", snapshot_date.isoformat())
            if cache_path.exists():
                raw = pd.read_json(cache_path, orient="records")
                self._count("cache")
            else:
                try:
                    response = requests.get(self.MARGIN_URL, headers=self.headers, timeout=self.timeout)
                    response.raise_for_status()
                    raw = pd.DataFrame(response.json())
                except Exception:
                    self._count("error", dataset="MI_MARGN", data_id="all", reason="fetch_failed")
                    raw = pd.DataFrame()
                if not raw.empty:
                    raw.to_json(cache_path, orient="records", force_ascii=False)
                    self._count("api")
            self._margin_df = raw
            self._record_official_snapshot("margin", snapshot_date, valid=not raw.empty, rows=len(raw))
            return raw, snapshot_date

    def margin(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        raw, snapshot_date = self._margin_today(end_date)
        current = pd.DataFrame()
        if not raw.empty and snapshot_date is not None and "股票代號" in raw.columns:
            rows = raw[raw["股票代號"].astype(str) == str(stock_id)]
            if not rows.empty:
                row = rows.iloc[0]
                current = pd.DataFrame(
                    [{
                        "date": snapshot_date,
                        "stock_id": stock_id,
                        "MarginPurchaseTodayBalance": _num(row.get("融資今日餘額", 0)),
                        "ShortSaleTodayBalance": _num(row.get("融券今日餘額", 0)),
                    }]
                )
        if not current.empty or self._is_twse_stock(stock_id):
            official = self._save_official_history("margin", stock_id, current, subset=["date"])
            cached = self._cached_fallback("TaiwanStockMarginPurchaseShortSale", stock_id, start_date, end_date)
            merged = _merge_frames(cached, official, subset=["date"], start_date=start_date, end_date=end_date)
            return self._complete_history_if_short(
                merged,
                minimum_rows=3,
                minimum_span_days=14,
                fetcher=self.fallback.margin,
                dataset="margin",
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date,
                subset=["date"],
            )
        tpex_raw, tpex_date = self._tpex_margin_today(end_date)
        if not tpex_raw.empty and tpex_date is not None:
            rows = tpex_raw[tpex_raw["SecuritiesCompanyCode"].astype(str) == str(stock_id)]
            if not rows.empty:
                row = rows.iloc[0]
                current = pd.DataFrame([{
                    "date": tpex_date,
                    "stock_id": stock_id,
                    "MarginPurchaseTodayBalance": _num(row.get("MarginPurchaseBalance", 0)),
                    "ShortSaleTodayBalance": _num(row.get("ShortSaleBalance", 0)),
                }])
        if not current.empty or self._is_tpex_stock(stock_id):
            official = self._save_official_history("margin", stock_id, current, subset=["date"])
            cached = self._cached_fallback("TaiwanStockMarginPurchaseShortSale", stock_id, start_date, end_date)
            merged = _merge_frames(cached, official, subset=["date"], start_date=start_date, end_date=end_date)
            return self._complete_history_if_short(
                merged,
                minimum_rows=3,
                minimum_span_days=14,
                fetcher=self.fallback.margin,
                dataset="margin",
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date,
                subset=["date"],
            )
        self._count("fallback", record_event=False)
        return self.fallback.margin(stock_id, start_date, end_date)

    def _tpex_margin_today(self, end_date: date) -> tuple[pd.DataFrame, date | None]:
        with self._tpex_margin_lock:
            if self._tpex_margin_df is not None:
                return self._tpex_margin_df, _snapshot_date(self._tpex_margin_df)
            raw = self._official_list_snapshot("tpex_margin", self.TPEX_MARGIN_URL)
            snapshot_date = _snapshot_date(raw)
            valid = self._is_current_official_snapshot(snapshot_date, end_date)
            if not valid:
                raw = pd.DataFrame()
            self._tpex_margin_df = raw
            self._record_official_snapshot("tpex_margin", snapshot_date, valid=valid and not raw.empty, rows=len(raw))
            return raw, snapshot_date

    def _revenue_latest(self) -> pd.DataFrame:
        with self._revenue_lock:
            if self._revenue_df is not None:
                return self._revenue_df
            cache_path = self._cache_path("t187ap05_L", "all", date.today().isoformat())
            if cache_path.exists():
                raw = pd.read_json(cache_path, orient="records")
                self._count("cache")
            else:
                try:
                    response = requests.get(self.REVENUE_URL, headers=self.headers, timeout=self.timeout)
                    response.raise_for_status()
                    raw = pd.DataFrame(response.json())
                except Exception:
                    self._count("error", dataset="t187ap05_L", data_id="all", reason="fetch_failed")
                    raw = pd.DataFrame()
            if not raw.empty:
                raw.to_json(cache_path, orient="records", force_ascii=False)
                self._count("api")
            self._revenue_df = raw
            revenue_date = None
            if not raw.empty and "資料年月" in raw.columns:
                try:
                    revenue_date = _roc_month_date(raw.iloc[0]["資料年月"])
                except ValueError:
                    pass
            self._record_official_snapshot("revenue", revenue_date, valid=not raw.empty, rows=len(raw))
            return raw

    def _tpex_revenue_latest(self, *, emerging: bool = False) -> pd.DataFrame:
        lock = self._tpex_emerging_revenue_lock if emerging else self._tpex_revenue_lock
        attr = "_tpex_emerging_revenue_df" if emerging else "_tpex_revenue_df"
        dataset = "t187ap05_R" if emerging else "mopsfin_t187ap05_O"
        url = self.TPEX_EMERGING_REVENUE_URL if emerging else self.TPEX_REVENUE_URL
        snapshot_name = "revenue_emerging" if emerging else "revenue_tpex"
        with lock:
            cached_df = getattr(self, attr)
            if cached_df is not None:
                return cached_df
            cache_path = self._cache_path(dataset, "all", date.today().isoformat())
            if cache_path.exists():
                raw = pd.read_json(cache_path, orient="records")
                self._count("cache")
            else:
                try:
                    response = requests.get(url, headers=self.headers, timeout=self.timeout)
                    response.raise_for_status()
                    raw = pd.DataFrame(response.json())
                except Exception:
                    self._count("error", dataset=dataset, data_id="all", reason="fetch_failed")
                    raw = pd.DataFrame()
            if not raw.empty:
                raw.to_json(cache_path, orient="records", force_ascii=False)
                self._count("api")
            setattr(self, attr, raw)
            revenue_date = _revenue_snapshot_date(raw)
            self._record_official_snapshot(snapshot_name, revenue_date, valid=not raw.empty, rows=len(raw))
            return raw

    def monthly_revenue(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        current = pd.DataFrame()
        for raw in (
            self._revenue_latest(),
            self._tpex_revenue_latest(),
            self._tpex_revenue_latest(emerging=True),
        ):
            current = _revenue_row(raw, stock_id)
            if not current.empty:
                break
        if not current.empty or self._is_twse_stock(stock_id) or self._is_tpex_stock(stock_id):
            official = self._save_official_history("revenue", stock_id, current, subset=["date"])
            cached = self._cached_fallback("TaiwanStockMonthRevenue", stock_id, start_date, end_date)
            merged = _merge_frames(cached, official, subset=["date"], start_date=start_date, end_date=end_date)
            return self._complete_history_if_short(
                merged,
                minimum_rows=15,
                minimum_span_days=365,
                fetcher=self.fallback.monthly_revenue,
                dataset="revenue",
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date,
                subset=["date"],
            )
        self._count("fallback", record_event=False)
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
                self._count("error", dataset="TWT48U_ALL", data_id="all", reason="fetch_failed")
                logging.exception("TWSE dividend fetch failed")
                self._count("fallback", dataset="dividend", data_id=stock_id)
                return self.fallback.dividend(stock_id, start_date, end_date)
            if df.empty:
                self._count("empty", dataset="TWT48U_ALL", data_id="all")
                self._count("fallback", dataset="dividend", data_id=stock_id)
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
                self._count("error", dataset="BWIBBU_ALL", data_id="all", reason="fetch_failed")
                logging.warning("TWSE valuation (BWIBBU_ALL) fetch failed")
                self._valuation_df = pd.DataFrame()
                return pd.DataFrame()
            if df.empty:
                self._count("empty", dataset="BWIBBU_ALL", data_id="all")
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
                self._count("error", dataset="MI_INDEX", data_id="all", reason="fetch_failed")
                logging.warning("TWSE sector index (MI_INDEX) fetch failed")
                self._sector_df = pd.DataFrame()
                return pd.DataFrame()
            if raw.empty:
                self._count("empty", dataset="MI_INDEX", data_id="all")
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
        symbols = {
            "sp500": "^GSPC",
            "nasdaq": "^IXIC",
            "dow": "^DJI",
            "sox": "^SOX",
            "tsm_adr": "TSM",
            "glw": "GLW",
            "cohr": "COHR",
            "lite": "LITE",
            "mu": "MU",
            "nvda": "NVDA",
            "rklb": "RKLB",
            "asts": "ASTS",
            "us10y": "^TNX",
        }
        bundle: dict[str, pd.DataFrame] = {}
        valid = 0
        latest_date: date | None = None
        for name, symbol in symbols.items():
            frame = self._yahoo_chart(symbol, start_date, end_date)
            if frame.empty:
                self._count("fallback", dataset="overseas", data_id=symbol, reason="public_market_unavailable")
                if name == "us10y":
                    frame = self.fallback.government_bond_yield("United States 10-Year", start_date, end_date)
                else:
                    frame = self.fallback.us_stock_price(symbol, start_date, end_date)
            else:
                valid += 1
                frame_date = pd.to_datetime(frame["date"], errors="coerce").max()
                if not pd.isna(frame_date):
                    candidate = frame_date.date()
                    latest_date = max(latest_date, candidate) if latest_date else candidate
            if name == "us10y" and not frame.empty and "Close" in frame.columns and "value" not in frame.columns:
                frame = frame.assign(value=frame["Close"])
            bundle[name] = frame
        bundle["tx_night"] = self.fallback.futures_daily("TX", start_date, end_date)
        self._record_market_snapshot(
            "overseas_public_market",
            latest_date,
            valid=valid == len(symbols),
            rows=valid,
            source="Yahoo Finance chart API",
        )
        return bundle

    def _yahoo_chart(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        cache_path = self._cache_path("YAHOO_CHART", symbol, end_date.isoformat())
        if cache_path.exists():
            frame = pd.read_json(cache_path, orient="records")
            if _valid_market_frame(frame, end_date):
                self._count("cache")
                return frame
        period1 = int(datetime.combine(start_date, time.min, tzinfo=timezone.utc).timestamp())
        period2 = int(datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc).timestamp())
        try:
            response = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"period1": period1, "period2": period2, "interval": "1d"},
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = (response.json().get("chart", {}).get("result") or [])[0]
            timestamps = result.get("timestamp") or []
            quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("America/New_York").date,
                    "Open": quote.get("open", []),
                    "High": quote.get("high", []),
                    "Low": quote.get("low", []),
                    "Close": quote.get("close", []),
                    "Volume": quote.get("volume", []),
                }
            ).dropna(subset=["date", "Close"])
        except Exception as exc:
            logging.warning("Public overseas market request failed for %s: %s", symbol, exc)
            return pd.DataFrame()
        if not _valid_market_frame(frame, end_date):
            return pd.DataFrame()
        frame.to_json(cache_path, orient="records", force_ascii=False, date_format="iso")
        self._count("api")
        return frame.reset_index(drop=True)

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


def _roc_month_date(value: object) -> date:
    text = str(value).strip()
    if len(text) < 5:
        raise ValueError(f"Invalid ROC month: {value}")
    return date(int(text[:3]) + 1911, int(text[3:5]), 1)


def _revenue_snapshot_date(df: pd.DataFrame) -> date | None:
    if df.empty or "資料年月" not in df.columns:
        return None
    for value in df["資料年月"].dropna().astype(str):
        try:
            return _roc_month_date(value)
        except ValueError:
            continue
    return None


def _revenue_row(df: pd.DataFrame, stock_id: str) -> pd.DataFrame:
    if df.empty or "公司代號" not in df.columns:
        return pd.DataFrame()
    rows = df[df["公司代號"].astype(str) == str(stock_id)]
    if rows.empty:
        return pd.DataFrame()
    row = rows.iloc[0]
    try:
        revenue_date = _roc_month_date(row.get("資料年月", ""))
    except ValueError:
        return pd.DataFrame()
    return pd.DataFrame(
        [{
            "date": revenue_date,
            "stock_id": stock_id,
            "revenue": _num(row.get("營業收入-當月營收", 0)),
        }]
    )


def _valid_market_frame(frame: pd.DataFrame, end_date: date) -> bool:
    if frame.empty or "date" not in frame.columns or "Close" not in frame.columns or len(frame) < 2:
        return False
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        return False
    latest = dates.max().date()
    return latest <= end_date and end_date - latest <= timedelta(days=7)


def _snapshot_date(df: pd.DataFrame) -> date | None:
    if df.empty or "Date" not in df.columns:
        return None
    for value in df["Date"].dropna().astype(str):
        try:
            return _roc_compact_date(value)
        except ValueError:
            continue
    return None


def _is_common_stock_code(stock_id: str) -> bool:
    value = str(stock_id).strip()
    return bool(re.fullmatch(r"\d{4}", value)) and not value.startswith("0")


def _first_existing(row: pd.Series, keys: list[str]) -> object:
    for key in keys:
        if key in row and pd.notna(row.get(key)):
            return row.get(key)
    return 0


def _merge_frames(
    cached: pd.DataFrame,
    official: pd.DataFrame,
    *,
    subset: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    frames = [frame for frame in (cached, official) if not frame.empty]
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.dropna(subset=["date"]).drop_duplicates(subset=subset, keep="last")
    dates = merged["date"].dt.date
    return merged[(dates >= start_date) & (dates <= end_date)].sort_values("date").reset_index(drop=True)
