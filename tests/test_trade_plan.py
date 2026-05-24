from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.indicators.trade_plan import trade_plan


def _prices(days: int = 25) -> pd.DataFrame:
    start = date(2026, 5, 1)
    closes = [100 + i for i in range(days)]
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(days)],
            "close": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 2 for value in closes],
            "volume": [1_000_000 + i * 10_000 for i in range(days)],
        }
    )


def test_trade_plan_separates_strength_from_entry_confirmation() -> None:
    plan = trade_plan(88, _prices(), [])

    assert plan["action"] == "可追蹤突破"
    assert plan["entry_decision"] == "開盤確認"
    assert any("站穩昨高" in item for item in plan["entry_checklist"])
    assert any("不追超過" in item for item in plan["entry_checklist"])


def test_trade_plan_marks_mid_score_as_cancel_without_volume_price_confirmation() -> None:
    plan = trade_plan(68, _prices(), [])

    assert plan["action"] == "只觀察"
    assert plan["entry_decision"] == "量價不確認取消"
    assert any("未同時滿足就取消" in item for item in plan["entry_checklist"])
