from __future__ import annotations

import pandas as pd

from src.indicators.opportunity import opportunity_score


def test_theme_tier_changes_opportunity_score() -> None:
    empty_bundle: dict[str, pd.DataFrame] = {}
    core_score, core_reasons = opportunity_score(
        empty_bundle,
        ["記憶體/HBM"],
        [{"theme_name": "記憶體/HBM", "tier": "core", "tier_label": "核心"}],
    )
    speculative_score, speculative_reasons = opportunity_score(
        empty_bundle,
        ["記憶體/HBM"],
        [{"theme_name": "記憶體/HBM", "tier": "speculative", "tier_label": "投機"}],
    )

    assert core_score > speculative_score
    assert "核心" in core_reasons[0]
    assert "投機" in speculative_reasons[0]


def test_opportunity_does_not_double_count_chip_or_revenue() -> None:
    institutional = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3),
            "name": ["Foreign_Dealer_Self"] * 3,
            "buy": [100, 100, 100],
            "sell": [0, 0, 0],
        }
    )
    revenue = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=15, freq="MS"),
            "revenue": [100] * 14 + [200],
        }
    )

    score, reasons = opportunity_score({"institutional": institutional, "revenue": revenue}, [])

    assert score == 0
    assert reasons == ["尚無明顯異常訊號"]
