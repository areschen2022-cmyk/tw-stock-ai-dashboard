from __future__ import annotations

from datetime import date

from src.data_provider.twse_client import TwseClient, _roc_compact_date, _roc_slash_date


class _Response:
    def __init__(self, payload) -> None:
        self._payload = payload
        self.headers = {"Content-Type": "application/json"}
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _Fallback:
    def source_status(self):
        return {"api": 0, "cache": 0, "quota": 0, "error": 0, "empty": 0}

    def stock_prices(self, stock_id, start_date, end_date):
        raise AssertionError("stock price fallback should not be used")


def test_roc_date_parsers() -> None:
    assert _roc_slash_date("115/05/04") == date(2026, 5, 4)
    assert _roc_compact_date("1150519") == date(2026, 5, 19)


def test_twse_stock_prices_parse_and_cache(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_get(url, params=None, headers=None, timeout=20):
        calls.append(params.copy())
        return _Response(
            {
                "stat": "OK",
                "data": [
                    ["115/05/04", "44,458,732", "99,944,198,300", "2,200.00", "2,285.00", "2,195.00", "2,275.00", "+140.00", "129,173", ""],
                    ["115/05/05", "26,644,983", "60,009,590,420", "2,250.00", "2,270.00", "2,240.00", "2,250.00", "-25.00", "153,870", ""],
                ],
            }
        )

    monkeypatch.setattr("src.data_provider.twse_client.requests.get", fake_get)
    client = TwseClient(fallback=_Fallback(), cache_dir=tmp_path)

    first = client.stock_prices("2330", date(2026, 5, 4), date(2026, 5, 5))
    second = client.stock_prices("2330", date(2026, 5, 4), date(2026, 5, 5))

    assert len(calls) == 1
    assert calls[0]["date"] == "20260501"
    assert first["close"].tolist() == [2275.0, 2250.0]
    assert first["volume"].tolist() == [44458732.0, 26644983.0]
    assert second["close"].tolist() == [2275.0, 2250.0]
    assert client.status_counts["api"] == 1
    assert client.status_counts["cache"] == 1


def test_twse_source_status_labels_are_readable(tmp_path) -> None:
    client = TwseClient(fallback=_Fallback(), cache_dir=tmp_path)
    assert client.source_status()["label"] == "無資料"
    client.status_counts["api"] = 1
    assert client.source_status()["label"] == "正常"
    client.status_counts["quota"] = 1
    assert client.source_status()["label"] == "部分限流"
    client.status_counts["api"] = 0
    client.status_counts["cache"] = 0
    assert client.source_status()["label"] == "限流"
    client.status_counts["error"] = 1
    assert client.source_status()["label"] == "錯誤"
