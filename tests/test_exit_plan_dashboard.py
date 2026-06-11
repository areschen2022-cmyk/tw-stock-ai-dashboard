from __future__ import annotations

from datetime import date

from src.report.dashboard import build_dashboard_payload
from src.scoring.score_engine import StockScore


def test_dashboard_payload_includes_exit_plan_prices() -> None:
    score = StockScore(
        stock_id="2408",
        total_score=90,
        label="BUY_WATCH",
        price=100.0,
        technical_score=20,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=0,
        reasons={"technical": ["突破整理"], "chip": ["法人共振"]},
    )
    score.action = "可追蹤突破"
    score.entry_decision = "開盤確認"
    score.entry_limit_price = 102.0
    score.stop_price = 95.0

    payload = build_dashboard_payload(
        [score],
        date(2026, 6, 11),
        "健康",
        None,
        {"stock_names": {"2408": "南亞科"}, "theme_pools": {}},
        overseas=None,
        theme_signal=None,
        source_status={"label": "正常", "api": 1, "cache": 0, "quota": 0, "error": 0},
    )

    exit_plan = payload["rows"][0]["exit_plan"]
    assert exit_plan["take_profit_1"] == 109.0
    assert exit_plan["take_profit_2"] == 116.0
    assert exit_plan["hard_stop"] == "跌破 95.00 退出，不攤平"
    assert payload["action_lists"]["chase"][0]["exit_plan"]["take_profit_1"] == 109.0
