from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.report.exit_risk import build_exit_risks
from src.scoring.score_engine import StockScore
from src.storage.sqlite_store import SQLiteStore


def test_build_exit_risks_flags_foreign_selling_and_price_break(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    as_of = date(2026, 5, 15)
    score = StockScore(
        stock_id="2330",
        total_score=58,
        label="WAIT",
        price=90.0,
        technical_score=0,
        chip_score=0,
        fundamental_score=0,
        risk_score=0,
        market_adjustment=0,
    )
    old_score = StockScore(
        stock_id="2330",
        total_score=78,
        label="BUY_WATCH",
        price=105.0,
        technical_score=0,
        chip_score=0,
        fundamental_score=0,
        risk_score=0,
        market_adjustment=0,
    )
    store.save_daily_score(old_score, as_of - timedelta(days=1))

    prices = pd.DataFrame(
        {
            "date": [as_of - timedelta(days=i) for i in range(24, -1, -1)],
            "close": [110.0] * 19 + [105.0, 101.0, 98.0, 95.0, 92.0, 90.0],
            "volume": [1000.0] * 24 + [2200.0],
        }
    )
    institutional = pd.DataFrame(
        {
            "date": [as_of - timedelta(days=2), as_of - timedelta(days=1), as_of],
            "name": ["Foreign_Investor", "Foreign_Investor", "Foreign_Investor"],
            "buy": [100.0, 100.0, 100.0],
            "sell": [300.0, 300.0, 500.0],
        }
    )
    margin = pd.DataFrame(
        {
            "date": [as_of - timedelta(days=3), as_of - timedelta(days=2), as_of - timedelta(days=1), as_of],
            "MarginPurchaseTodayBalance": [1000.0, 1050.0, 1090.0, 1120.0],
        }
    )

    risks = build_exit_risks(
        [score],
        {"2330": {"prices": prices, "institutional": institutional, "margin": margin}},
        as_of,
        store,
        {"2330": "台積電"},
        {"exit_risk": {"enabled": True}},
    )

    assert risks
    assert risks[0]["level"] == "紅色警戒"
    assert any("外資" in reason for reason in risks[0]["reasons"])
    assert any("跌破" in reason for reason in risks[0]["reasons"])
    assert any("融資增" in reason for reason in risks[0]["reasons"])
    assert any("法人賣" in reason for reason in risks[0]["reasons"])
    assert any("爆量長黑" in reason or "成交量" in reason for reason in risks[0]["reasons"])


def test_build_exit_risks_uses_retail_overheated_signal(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    as_of = date(2026, 6, 5)
    score = StockScore(
        stock_id="2408",
        total_score=72,
        label="WAIT",
        price=100.0,
        technical_score=0,
        chip_score=0,
        fundamental_score=0,
        risk_score=0,
        market_adjustment=0,
    )
    old_score = StockScore(
        stock_id="2408",
        total_score=90,
        label="BUY_WATCH",
        price=105.0,
        technical_score=0,
        chip_score=0,
        fundamental_score=0,
        risk_score=0,
        market_adjustment=0,
    )
    store.save_daily_score(old_score, as_of - timedelta(days=1))
    store.save_retail_holder_signals(
        [
            {
                "stock_id": "2408",
                "name": "南亞科",
                "holder_count": 12000,
                "prev_holder_count": 10000,
                "holder_change": 2000,
                "holder_change_pct": 20.0,
                "price_change_pct": 0.2,
                "volume": 5000,
                "signal": "散戶過熱",
                "reason": "散戶增加但股價不漲",
            }
        ],
        as_of,
    )
    prices = pd.DataFrame(
        {
            "date": [as_of - timedelta(days=i) for i in range(24, -1, -1)],
            "close": [100.0] * 25,
            "volume": [1000.0] * 25,
        }
    )
    margin = pd.DataFrame(
        {
            "date": [as_of - timedelta(days=3), as_of - timedelta(days=2), as_of - timedelta(days=1), as_of],
            "MarginPurchaseTodayBalance": [1000.0, 1040.0, 1080.0, 1120.0],
        }
    )

    risks = build_exit_risks(
        [score],
        {"2408": {"prices": prices, "institutional": pd.DataFrame(), "margin": margin}},
        as_of,
        store,
        {"2408": "南亞科"},
        {"exit_risk": {"enabled": True}},
    )

    assert risks
    assert risks[0]["level"] == "紅色警戒"
    assert any("散戶過熱" in reason for reason in risks[0]["reasons"])
