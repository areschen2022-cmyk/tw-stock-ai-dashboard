from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd
import requests

from src.data_provider.finmind_client import FinMindClient


class TwseClient:
    STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
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

    def _stock_month(self, stock_id: str, year: int, month: int) -> pd.DataFrame:
        key = f"{year}-{month:02d}"
        cache_path = self._cache_path("STOCK_DAY", stock_id, key)
        if cache_path.exists():
            self._count("cache")
            return pd.read_json(cache_path, orient="records")
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

    def overseas_bundle(self, start_date: date, end_date: date) -> dict[str, pd.DataFrame]:
        self._count("fallback")
        return self.fallback.overseas_bundle(start_date, end_date)

    def stock_bundle(
        self,
        stock_id: str,
        start_date: date,
        end_date: date,
        include_dividend: bool = True,
    ) -> dict[str, pd.DataFrame]:
        revenue_start = end_date.replace(day=1)
        revenue_start = date(revenue_start.year - 2, revenue_start.month, 1)
        return {
            "prices": self.stock_prices(stock_id, start_date, end_date),
            "institutional": self.institutional(stock_id, start_date, end_date),
            "margin": self.margin(stock_id, start_date, end_date),
            "revenue": self.monthly_revenue(stock_id, revenue_start, end_date),
            "dividend": self.dividend(stock_id, start_date, end_date) if include_dividend else pd.DataFrame(),
        }


def _num(value: object) -> float:
    text = str(value).replace(",", "").strip()
    if text in {"", "--", "nan", "None"}:
        return 0.0
    return float(text)


def _roc_slash_date(value: object) -> date:
    year, month, day = str(value).split("/")[:3]
    return date(int(year) + 1911, int(month), int(day))


def _roc_compact_date(value: object) -> date:
    text = str(value).strip()
    if len(text) < 7:
        raise ValueError(f"Invalid ROC date: {value}")
    return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
