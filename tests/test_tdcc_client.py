from __future__ import annotations

from datetime import date

from retail_divergence_job import build_retail_signals
from src.data_provider.tdcc_client import parse_tdcc_csv, retail_holder_counts


SAMPLE = """資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
20260515,2408,1,1000,100000,1.0
20260515,2408,2,500,200000,2.0
20260515,2408,3,100,100000,1.0
20260522,2408,1,900,90000,0.9
20260522,2408,2,450,180000,1.8
20260522,2408,3,90,90000,0.9
20260515,2344,1,1000,100000,1.0
20260515,2344,2,500,200000,2.0
20260515,2344,3,100,100000,1.0
20260522,2344,1,1100,110000,1.1
20260522,2344,2,560,220000,2.2
20260522,2344,3,110,110000,1.1
"""


class DummyProvider:
    def stock_prices(self, stock_id, start_date, end_date):
        import pandas as pd

        volume = 2_000_000
        if stock_id == "2408":
            return pd.DataFrame(
                [
                    {"date": date(2026, 5, 15), "close": 100.0, "volume": volume},
                    {"date": date(2026, 5, 22), "close": 100.5, "volume": volume},
                ]
            )
        return pd.DataFrame(
            [
                {"date": date(2026, 5, 15), "close": 100.0, "volume": volume},
                {"date": date(2026, 5, 22), "close": 100.2, "volume": volume},
            ]
        )


def test_parse_tdcc_csv_and_group_retail_holders() -> None:
    rows = parse_tdcc_csv(SAMPLE)
    grouped = retail_holder_counts(rows)

    assert grouped[date(2026, 5, 15)]["2408"] == 1600
    assert grouped[date(2026, 5, 22)]["2344"] == 1770


def test_build_retail_signals_from_tdcc_rows() -> None:
    rows = parse_tdcc_csv(SAMPLE)
    signals, week_date = build_retail_signals(
        rows,
        {"2408": "南亞科", "2344": "華邦電"},
        DummyProvider(),
        as_of=date(2026, 5, 26),
    )

    assert week_date == date(2026, 5, 22)
    by_id = {item["stock_id"]: item for item in signals}
    assert by_id["2408"]["signal"] == "籌碼轉乾淨"
    assert by_id["2344"]["signal"] == "散戶過熱"


def test_build_retail_signals_can_use_previous_snapshot() -> None:
    latest_only = "\n".join(SAMPLE.splitlines()[:1] + SAMPLE.splitlines()[4:])
    rows = parse_tdcc_csv(latest_only)
    signals, week_date = build_retail_signals(
        rows,
        {"2408": "南亞科"},
        DummyProvider(),
        as_of=date(2026, 5, 26),
        previous_date=date(2026, 5, 15),
        previous_counts={"2408": 1600},
    )

    assert week_date == date(2026, 5, 22)
    assert signals[0]["stock_id"] == "2408"
    assert signals[0]["signal"] == "籌碼轉乾淨"
