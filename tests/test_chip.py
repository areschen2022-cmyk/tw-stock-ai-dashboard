from __future__ import annotations

from datetime import date, timedelta

from src.data_provider.mock_data import MockDataProvider
from src.indicators.chip import chip_score


def test_chip_score_uses_institutional_and_margin_data() -> None:
    provider = MockDataProvider(date(2026, 5, 11))
    start = date(2026, 5, 11) - timedelta(days=180)
    bundle = provider.stock_bundle("2330", start, date(2026, 5, 11))
    score, reasons = chip_score(bundle["institutional"], bundle["margin"], bundle["prices"])
    assert score <= 30
    assert "外資近 3 日買超" in reasons
