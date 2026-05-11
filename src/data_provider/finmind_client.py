from __future__ import annotations

import os
import logging
from datetime import date
from datetime import timedelta
from pathlib import Path
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

    def _cache_path(self, dataset: str, data_id: str, start_date: date, end_date: date) -> Path:
        safe_id = data_id.replace("^", "idx_").replace("/", "_").replace(" ", "_")
        name = f"{dataset}__{safe_id}__{start_date.isoformat()}__{end_date.isoformat()}.json"
        return self.cache_dir / name

    def _fetch(self, dataset: str, data_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        cache_path = self._cache_path(dataset, data_id, start_date, end_date)
        if cache_path.exists():
            self.status_counts["cache"] += 1
            return pd.read_json(cache_path, orient="records")

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
            self.status_counts["quota"] += 1
            return pd.DataFrame()
        try:
            response.raise_for_status()
        except requests.HTTPError:
            self.status_counts["error"] += 1
            raise
        payload = response.json()
        if not payload.get("data"):
            self.status_counts["empty"] += 1
            return pd.DataFrame()
        df = pd.DataFrame(payload["data"])
        df.to_json(cache_path, orient="records", force_ascii=False, date_format="iso")
        self.status_counts["api"] += 1
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
