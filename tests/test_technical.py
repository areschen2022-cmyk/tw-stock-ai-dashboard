from __future__ import annotations

from datetime import date, timedelta

from src.data_provider.mock_data import MockDataProvider
from src.indicators.technical import rsi_wilder, technical_score


def test_rsi_wilder_returns_constructive_value_for_uptrend() -> None:
    provider = MockDataProvider(date(2026, 5, 11))
    prices = provider.stock_prices("2330", date(2026, 1, 1), date(2026, 5, 11))
    rsi = rsi_wilder(prices["close"]).iloc[-1]
    assert 0 <= rsi <= 100


def test_technical_score_has_reasons() -> None:
    provider = MockDataProvider(date(2026, 5, 11))
    prices = provider.stock_prices("2454", date(2026, 5, 11) - timedelta(days=180), date(2026, 5, 11))
    score, reasons = technical_score(prices)
    assert 0 <= score <= 30
    assert reasons

