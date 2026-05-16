import pandas as pd

from src.indicators.overseas import analyze_overseas_sentiment


def _prices(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": [f"2026-05-{10+i:02d}" for i in range(len(values))], "Close": values})


def test_overseas_sector_map_creates_stock_adjustments_and_reasons() -> None:
    sentiment = analyze_overseas_sentiment(
        {
            "nasdaq": _prices([100, 100.5]),
            "sp500": _prices([100, 100.2]),
            "sox": _prices([100, 100.5]),
            "tsm_adr": _prices([100, 100.3]),
            "glw": _prices([100, 103]),
        },
        sector_map={
            "us_to_tw": {"GLW": ["6442", "4979"]},
            "sector_map": {"光通訊光模組": ["6442", "4979"]},
        },
    )

    assert sentiment.stock_adjustments == {"6442": 1, "4979": 1}
    assert sentiment.sector_impacts
    assert any("GLW" in reason for reason in sentiment.reasons)
