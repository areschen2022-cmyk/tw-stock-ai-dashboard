from __future__ import annotations

from datetime import date, timedelta

import yaml

from src.data_provider.mock_data import MockDataProvider
from src.scoring.score_engine import ScoreEngine, _build_trigger_tags


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


def test_trigger_tags_populated() -> None:
    """trigger_tags must be a non-empty list and trigger_summary must be a non-empty string."""
    with open("config.yaml", "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    as_of = date(2026, 5, 11)
    provider = MockDataProvider(as_of)
    start = as_of - timedelta(days=180)
    engine = ScoreEngine(config)
    score = engine.score_stock("2330", provider.stock_bundle("2330", start, as_of), 0, as_of)
    assert isinstance(score.trigger_tags, list)
    assert len(score.trigger_tags) >= 1
    assert isinstance(score.trigger_summary, str)
    assert len(score.trigger_summary) > 0


def test_trigger_tags_theme_upgrade() -> None:
    """High opportunity_adj with themes should produce 題材強共振 or 題材升溫."""
    tags = _build_trigger_tags(
        t_score=20, t_reasons=["放量突破20日高點"],
        c_score=16, c_reasons=["外資近 3 日買超", "整體法人近 3 日買超"],
        f_score=0,
        overseas_adj=0,
        opportunity_adj=12,
        themes=["AI 伺服器"],
    )
    assert any("題材" in t for t in tags), f"Expected a 題材 tag, got: {tags}"
    assert any("外資" in t or "法人" in t for t in tags), f"Expected a chip tag, got: {tags}"
    assert any("突破" in t or "技術" in t or "趨勢" in t for t in tags), f"Expected a tech tag, got: {tags}"


def test_trigger_tags_no_signal_gives_fallback() -> None:
    """When all scores are zero, should return ['綜合訊號'] not an empty list."""
    tags = _build_trigger_tags(
        t_score=0, t_reasons=[],
        c_score=0, c_reasons=[],
        f_score=0,
        overseas_adj=0,
        opportunity_adj=0,
        themes=[],
    )
    assert tags == ["綜合訊號"]


def test_trigger_tags_chip_score_fallback_when_reason_text_is_unreadable() -> None:
    """High chip score should still create a chip tag even when reason text is malformed."""
    tags = _build_trigger_tags(
        t_score=0, t_reasons=[],
        c_score=18, c_reasons=["???"],
        f_score=0,
        overseas_adj=0,
        opportunity_adj=0,
        themes=[],
    )
    assert "籌碼偏多" in tags


def test_trigger_summary_joins_with_plus() -> None:
    """trigger_summary should join tags with ' + '."""
    with open("config.yaml", "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    as_of = date(2026, 5, 11)
    provider = MockDataProvider(as_of)
    start = as_of - timedelta(days=180)
    engine = ScoreEngine(config)
    score = engine.score_stock(
        "2330",
        provider.stock_bundle("2330", start, as_of),
        0, as_of,
        overseas_adj=5,
        opportunity_adj=10,
        themes=["AI 伺服器"],
    )
    if len(score.trigger_tags) > 1:
        assert " + " in score.trigger_summary
    else:
        assert score.trigger_summary == score.trigger_tags[0]


def test_to_dict_includes_trigger_summary() -> None:
    """to_dict() must expose trigger_summary for JSON serialisation."""
    with open("config.yaml", "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    as_of = date(2026, 5, 11)
    provider = MockDataProvider(as_of)
    start = as_of - timedelta(days=180)
    engine = ScoreEngine(config)
    score = engine.score_stock("2330", provider.stock_bundle("2330", start, as_of), 0, as_of)
    d = score.to_dict()
    assert "trigger_tags" in d
    assert "trigger_summary" in d
    assert d["trigger_summary"] == score.trigger_summary
