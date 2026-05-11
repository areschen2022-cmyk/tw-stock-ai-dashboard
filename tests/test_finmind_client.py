from __future__ import annotations

from datetime import date

import pandas as pd

from src.data_provider.finmind_client import FinMindClient


class _Response:
    status_code = 200

    def __init__(self, data: list[dict]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": self._data}


def test_finmind_monthly_cache_reuses_complete_months(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params.copy())
        return _Response(
            [
                {"date": "2026-01-01", "stock_id": "2330", "close": 900},
                {"date": "2026-01-20", "stock_id": "2330", "close": 950},
                {"date": "2026-02-10", "stock_id": "2330", "close": 980},
                {"date": "2026-02-28", "stock_id": "2330", "close": 990},
            ]
        )

    monkeypatch.setattr("src.data_provider.finmind_client.requests.get", fake_get)
    client = FinMindClient(token=None, cache_dir=tmp_path)

    first = client._fetch("TaiwanStockPrice", "2330", date(2026, 1, 15), date(2026, 2, 10))
    second = client._fetch("TaiwanStockPrice", "2330", date(2026, 1, 16), date(2026, 2, 10))

    assert len(calls) == 1
    assert calls[0]["start_date"] == "2026-01-01"
    assert calls[0]["end_date"] == "2026-02-28"
    assert sorted(pd.to_datetime(first["date"]).dt.strftime("%Y-%m-%d").tolist()) == ["2026-01-20", "2026-02-10"]
    assert sorted(pd.to_datetime(second["date"]).dt.strftime("%Y-%m-%d").tolist()) == ["2026-01-20", "2026-02-10"]
    assert sorted(path.name for path in tmp_path.glob("*.json")) == [
        "TaiwanStockPrice__2330__2026-01.json",
        "TaiwanStockPrice__2330__2026-02.json",
    ]
    assert client.status_counts["api"] == 1
    assert client.status_counts["cache"] == 2
