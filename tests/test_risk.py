from __future__ import annotations

from datetime import date, timedelta

from src.data_provider.mock_data import MockDataProvider
from src.indicators.risk import risk_score


def test_risk_score_stays_in_bounds() -> None:
    as_of = date(2026, 5, 11)
    provider = MockDataProvider(as_of)
    score, reasons = risk_score(
        provider.stock_prices("2330", as_of - timedelta(days=180), as_of),
        provider.dividend("2330", as_of - timedelta(days=180), as_of),
        as_of,
    )
    assert 0 <= score <= 20
    assert reasons

