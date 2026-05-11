from __future__ import annotations

from datetime import date, timedelta

import yaml

from src.data_provider.mock_data import MockDataProvider
from src.scoring.score_engine import ScoreEngine


def test_score_engine_returns_label() -> None:
    with open("config.yaml", "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    as_of = date(2026, 5, 11)
    provider = MockDataProvider(as_of)
    start = as_of - timedelta(days=180)
    engine = ScoreEngine(config)
    score = engine.score_stock("2330", provider.stock_bundle("2330", start, as_of), 0, as_of)
    assert score.label in {"BUY_WATCH", "WAIT", "AVOID", "DATA_INSUFFICIENT"}
    assert 0 <= score.total_score <= 100
    assert score.reasons

