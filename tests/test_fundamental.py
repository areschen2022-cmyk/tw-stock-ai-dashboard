from __future__ import annotations

from datetime import date, timedelta

from src.data_provider.mock_data import MockDataProvider
from src.indicators.fundamental import fundamental_score


def test_fundamental_score_handles_monthly_revenue() -> None:
    provider = MockDataProvider(date(2026, 5, 11))
    revenue = provider.monthly_revenue("2330", date(2025, 1, 1), date(2026, 5, 11))
    score, reasons = fundamental_score(revenue)
    assert 0 <= score <= 20
    assert reasons

