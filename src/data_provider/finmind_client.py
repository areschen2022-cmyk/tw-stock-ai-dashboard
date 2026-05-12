from __future__ import annotations

import os
import logging
from calendar import monthrange
from datetime import date
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd
import requests


class FinMindClient:
    BASE_URL = "https://api.finmindtrade.com/api/v4/data"

    def __init__(self, token: str | None = None, timeout: int = 20, cache_dir: Path | None = None) -> None:
        self.token = token or os.getenv("FINMIND_TOKEN")
        self.timeout = timeout
        self.cache_dir = cache_dir or Path("data") / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.status_counts = {"api": 0, "cache": 0, "quota": 0, "error": 0, "empty": 0}
        self._lock = Lock()

    def _count(self, key: str) -> None:
        with self._lock:
            self.status_counts[key] += 1

    def _cache_path(self, dataset: str, data_id: str, year: int, month: int, current: bool = False) -> Path:
        safe_id = data_id.replace("^", "idx_").replace("/", "_").replace(" ", "_")
        suffix = f"{year}-{month:02d}-current" if current else f"{year}-{month:02d}"
        name = f"{dataset}__{safe_id}__{suffix}.json"
        return self.cache_dir / name

    def _month_segments(self, start_date: date, end_date: date) -> list[tuple[int, int, date, date, bool]]:
        segments = []
        cursor = date(start_date.year, start_date.month, 1)
        today = date.today()
        while cursor <= end_date:
            last_day = monthrange(cursor.year, cursor.month)[1]
            month_start = cursor
            month_end = date(cursor.year, cursor.month, last_day)
            is_current = cursor.year == today.year and cursor.month == today.month
            fetch_start = month_start
            fetch_end = min(month_end, end_date) if is_current else month_end
            segments.append((cursor.year, cursor.month, fetch_start, fetch_end, is_current))
            cursor = date(cursor.year + int(cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
        return segments

    def _current_cache_is_fresh(self, cache_path: Path) -> bool:
        if not cache_path.exists():
            return False
        modified = date.fromtimestamp(cache_path.stat().st_mtime)
        return modified == date.today()

    def _request_range(
        self,
        dataset: str,
        data_id: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {
            "dataset": dataset,
            "data_id": data_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        if self.token:
            params["token"] = self.token
        response = requests.get(self.BASE_URL, params=params, timeout=self.timeout)
        if response.status_code in {402, 429}:
            logging.warning("FinMind quota/permission issue for %s %s: %s", dataset, data_id, response.status_code)
            self._count("quota")
            return pd.DataFrame()
        try:
            response.raise_for_status()
        except requests.HTTPError:
            self._count("error")
            raise
        payload = response.json()
        if not payload.get("data"):
            self._count("empty")
            return pd.DataFrame()
        df = pd.DataFrame(payload["data"])
        self._count("api")
        return df

    def _write_month_cache(self, df: pd.DataFrame, cache_path: Path, start_date: date, end_date: date) -> None:
        if df.empty:
            return
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"], errors="coerce").dt.date
            month_df = df[(dates >= start_date) & (dates <= end_date)]
        elif "Date" in df.columns:
            dates = pd.to_datetime(df["Date"], errors="coerce").dt.date
            month_df = df[(dates >= start_date) & (dates <= end_date)]
        else:
            month_df = df
        if not month_df.empty:
            month_df.to_json(cache_path, orient="records", force_ascii=False, date_format="iso")

    def _fetch(self, dataset: str, data_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        segments = self._month_segments(start_date, end_date)
        frames = []
        missing = []
        for year, month, segment_start, segment_end, is_current in segments:
            cache_path = self._cache_path(dataset, data_id, year, month, current=is_current)
            refresh = is_current and not self._current_cache_is_fresh(cache_path)
            if cache_path.exists() and not refresh:
                self._count("cache")
                frame = pd.read_json(cache_path, orient="records")
                if not frame.empty:
                    frames.append(frame)
            else:
                missing.append((year, month, segment_start, segment_end, is_current, cache_path))
        if missing:
            group_start = missing[0][2]
            group_end = missing[-1][3]
            fetched = self._request_range(dataset, data_id, group_start, group_end)
            if not fetched.empty:
                frames.append(fetched)
                for _, _, segment_start, segment_end, _, cache_path in missing:
                    self._write_month_cache(fetched, cache_path, segment_start, segment_end)
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"], errors="coerce").dt.date
            df = df[(dates >= start_date) & (dates <= end_date)]
        if "Date" in df.columns:
            dates = pd.to_datetime(df["Date"], errors="coerce").dt.date
            df = df[(dates >= start_date) & (dates <= end_date)]
        return df

    def source_status(self) -> dict[str, Any]:
        quota = self.status_counts["quota"]
        error = self.status_counts["error"]
        api = self.status_counts["api"]
        cache = self.status_counts["cache"]
        if error:
            label = "錯誤"
        elif quota and api == 0 and cache == 0:
            label = "限流"
        elif quota:
            label = "部分限流"
        elif api or cache:
            label = "正常"
        else:
            label = "無資料"
        return {"label": label, **self.status_counts}

    def stock_prices(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        df = self._fetch("TaiwanStockPrice", stock_id, start_date, end_date)
        if df.empty:
            return df
        return df.rename(columns={"Trading_Volume": "volume", "max": "high", "min": "low"})

    def institutional(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start_date, end_date)

    def margin(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch("TaiwanStockMarginPurchaseShortSale", stock_id, start_date, end_date)

    def monthly_revenue(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch("TaiwanStockMonthRevenue", stock_id, start_date, end_date)

    def dividend(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch("TaiwanStockDividend", stock_id, start_date, end_date)

    def us_stock_price(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch("USStockPrice", stock_id, start_date, end_date)

    def government_bond_yield(self, name: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch("GovernmentBondsYield", name, start_date, end_date)

    def futures_daily(self, futures_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch("TaiwanFuturesDaily", futures_id, start_date, end_date)

    def overseas_bundle(self, start_date: date, end_date: date) -> dict[str, pd.DataFrame]:
        symbols = {
            "sp500": "^GSPC",
            "nasdaq": "^IXIC",
            "dow": "^DJI",
            "sox": "^SOX",
            "tsm_adr": "TSM",
        }
        bundle = {name: self.us_stock_price(symbol, start_date, end_date) for name, symbol in symbols.items()}
        bundle["us10y"] = self.government_bond_yield("United States 10-Year", start_date, end_date)
        bundle["tx_night"] = self.futures_daily("TX", start_date, end_date)
        return bundle

    def intraday_prices(self, stock_id: str, trade_date: date) -> pd.DataFrame:
        """Fetch minute-level OHLCV for *trade_date* (TaiwanStockPriceMinute).

        Returns a DataFrame with columns:
          datetime (Timestamp), time (str HH:MM), open, high, low, close, volume
        Rows are sorted ascending by datetime.
        """
        df = self._request_range("TaiwanStockPriceMinute", stock_id, trade_date, trade_date)
        if df.empty:
            return df
        if "date" in df.columns:
            df["datetime"] = pd.to_datetime(df["date"], errors="coerce")
            df["time"] = df["datetime"].dt.strftime("%H:%M")
            df = df.sort_values("datetime").reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def stock_bundle(
        self,
        stock_id: str,
        start_date: date,
        end_date: date,
        include_dividend: bool = True,
    ) -> dict[str, pd.DataFrame]:
        revenue_start = end_date - timedelta(days=560)
        return {
            "prices": self.stock_prices(stock_id, start_date, end_date),
            "institutional": self.institutional(stock_id, start_date, end_date),
            "margin": self.margin(stock_id, start_date, end_date),
            "revenue": self.monthly_revenue(stock_id, revenue_start, end_date),
            "dividend": self.dividend(stock_id, start_date, end_date) if include_dividend else pd.DataFrame(),
        }
