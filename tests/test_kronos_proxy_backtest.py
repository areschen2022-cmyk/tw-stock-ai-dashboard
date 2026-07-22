from __future__ import annotations

import pandas as pd

from src.backtest.kronos_proxy import _phase2_decision, _phase2_segments, classify_kronos_proxy


def test_classify_kronos_proxy_uses_only_visible_uptrend() -> None:
    dates = pd.date_range("2025-01-01", periods=90, freq="B")
    close = [100 + i * 0.4 for i in range(90)]
    prices = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": [1000 + i * 5 for i in range(90)],
        }
    )

    result = classify_kronos_proxy(prices, 80)

    assert result["bias"] == "bullish"
    assert "close_gt_ma20_gt_ma60" in result["features"]
    assert result["metrics"]["ret20_pct"] > 0


def test_phase2_decision_requires_real_improvement() -> None:
    rows = []
    for idx in range(100):
        rows.append({"kronos_bias": "bullish", "net_return_5d": 2.0 if idx < 62 else -1.0})
    for idx in range(100):
        rows.append({"kronos_bias": "neutral", "net_return_5d": 0.5 if idx < 50 else -0.5})
    for idx in range(40):
        rows.append({"kronos_bias": "bearish", "net_return_5d": -2.0 if idx < 30 else 1.0})

    decision = _phase2_decision(rows)

    assert decision["qualified"] is True
    assert decision["bullish_gate"]["qualified"] is True
    assert decision["bearish_gate"]["qualified"] is True



def test_phase2_segments_identifies_subgroup_edges() -> None:
    rows = []
    for idx in range(80):
        rows.append(
            {
                "grade": "S",
                "score_band": "90+",
                "label": "BUY_WATCH",
                "kronos_bias": "bullish",
                "label_kronos": "BUY_WATCH|bullish",
                "grade_kronos": "S|bullish",
                "net_return_5d": 3.0 if idx < 60 else -1.0,
            }
        )
    for idx in range(80):
        rows.append(
            {
                "grade": "A",
                "score_band": "70-79",
                "label": "WAIT",
                "kronos_bias": "neutral",
                "label_kronos": "WAIT|neutral",
                "grade_kronos": "A|neutral",
                "net_return_5d": 0.5 if idx < 36 else -1.0,
            }
        )
    for idx in range(60):
        rows.append(
            {
                "grade": "B",
                "score_band": "60-69",
                "label": "BUY_WATCH",
                "kronos_bias": "bearish",
                "label_kronos": "BUY_WATCH|bearish",
                "grade_kronos": "B|bearish",
                "net_return_5d": -3.0 if idx < 50 else 1.0,
            }
        )

    result = _phase2_segments(rows)

    assert result["qualified_count"] >= 1
    assert result["weak_count"] >= 1
    assert any(row["segment"] == "strength_x_kronos" for row in result["all_segments"])
