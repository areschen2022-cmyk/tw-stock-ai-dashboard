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
