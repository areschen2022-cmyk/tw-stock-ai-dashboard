from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


class MockDataProvider:
    def __init__(self, as_of: date) -> None:
        self.as_of = as_of

    def stock_prices(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        days = pd.date_range(start=start_date, end=end_date, freq="B")
        seed = sum(ord(ch) for ch in stock_id)
        rows = []
        base = 60 + seed % 500
        for i, day in enumerate(days):
            trend = i * (0.25 + (seed % 7) * 0.03)
            wave = ((i + seed) % 9 - 4) * 0.7
            close = round(base + trend + wave, 2)
            rows.append(
                {
                    "date": day.date().isoformat(),
                    "stock_id": stock_id,
                    "open": round(close - 0.8, 2),
                    "high": round(close + 1.6, 2),
                    "low": round(close - 1.9, 2),
                    "close": close,
                    "volume": int(1_000_000 + (seed % 37) * 20_000 + i * 2_500),
                }
            )
        return pd.DataFrame(rows)

    def institutional(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        days = pd.date_range(start=max(start_date, end_date - timedelta(days=10)), end=end_date, freq="B")
        seed = sum(ord(ch) for ch in stock_id)
        rows = []
        for i, day in enumerate(days):
            rows.extend(
                [
                    {"date": day.date().isoformat(), "name": "Foreign_Dealer", "buy": 1000 + seed + i * 10, "sell": 400 + i},
                    {"date": day.date().isoformat(), "name": "Investment_Trust", "buy": 700 + i * 8, "sell": 300 + seed % 20},
                    {"date": day.date().isoformat(), "name": "Dealer_self", "buy": 500 + i * 4, "sell": 450 + seed % 30},
                ]
            )
        return pd.DataFrame(rows)

    def margin(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        days = pd.date_range(start=max(start_date, end_date - timedelta(days=10)), end=end_date, freq="B")
        return pd.DataFrame(
            {
                "date": [d.date().isoformat() for d in days],
                "MarginPurchaseTodayBalance": [1000 + i * 5 for i in range(len(days))],
                "ShortSaleTodayBalance": [200 - i for i in range(len(days))],
            }
        )

    def monthly_revenue(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        months = pd.date_range(end=end_date, periods=16, freq="MS")
        seed = sum(ord(ch) for ch in stock_id)
        rows = []
        for i, month in enumerate(months):
            rows.append(
                {
                    "date": month.date().isoformat(),
                    "stock_id": stock_id,
                    "revenue": 10_000_000 + seed * 1000 + i * 300_000,
                    "revenue_month": month.month,
                    "revenue_year": month.year,
                }
            )
        return pd.DataFrame(rows)

    def dividend(self, stock_id: str, start_date: date, end_date: date) -> pd.DataFrame:
        ex_date = end_date + timedelta(days=30)
        return pd.DataFrame([{"date": ex_date.isoformat(), "stock_id": stock_id, "CashDividend": 1.0}])

    def stock_bundle(
        self,
        stock_id: str,
        start_date: date,
        end_date: date,
        include_dividend: bool = True,
    ) -> dict[str, pd.DataFrame]:
        return {
            "prices": self.stock_prices(stock_id, start_date, end_date),
            "institutional": self.institutional(stock_id, start_date, end_date),
            "margin": self.margin(stock_id, start_date, end_date),
            "revenue": self.monthly_revenue(stock_id, start_date, end_date),
            "dividend": self.dividend(stock_id, start_date, end_date) if include_dividend else pd.DataFrame(),
        }

    def overseas_bundle(self, start_date: date, end_date: date) -> dict[str, pd.DataFrame]:
        return {}
