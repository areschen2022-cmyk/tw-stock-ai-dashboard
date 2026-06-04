from __future__ import annotations

from datetime import date

import pandas as pd

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

    def cached_only(self, dataset, stock_id, start_date, end_date):
        return pd.DataFrame()

    def institutional(self, stock_id, start_date, end_date):
        raise AssertionError("institutional network fallback should not be used")

    def margin(self, stock_id, start_date, end_date):
        raise AssertionError("margin network fallback should not be used")

    def monthly_revenue(self, stock_id, start_date, end_date):
        raise AssertionError("revenue network fallback should not be used")


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
    client.status_counts["fallback"] = 1
    assert client.source_status()["label"] == "部分限流"


def test_twse_source_status_includes_events(tmp_path) -> None:
    client = TwseClient(fallback=_Fallback(), cache_dir=tmp_path)

    client._count("empty", dataset="STOCK_DAY", data_id="2330", period="2026-05")
    status = client.source_status()

    assert status["events"][0]["type"] == "empty"
    assert status["events"][0]["dataset"] == "STOCK_DAY"
    assert status["events"][0]["data_id"] == "2330"


def test_twse_official_batch_snapshots_avoid_finmind_network(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_get(url, params=None, headers=None, timeout=20):
        calls.append(url)
        if url == TwseClient.STOCK_DAY_ALL_URL:
            return _Response(
                [{
                    "Date": "1150603",
                    "Code": "2330",
                    "Name": "台積電",
                    "TradeVolume": "100",
                    "OpeningPrice": "1000",
                    "HighestPrice": "1010",
                    "LowestPrice": "995",
                    "ClosingPrice": "1005",
                }]
            )
        if url == TwseClient.INSTITUTIONAL_URL:
            fields = [
                "證券代號",
                "證券名稱",
                "外陸資買進股數(不含外資自營商)",
                "外陸資賣出股數(不含外資自營商)",
                "投信買進股數",
                "投信賣出股數",
                "自營商買進股數(自行買賣)",
                "自營商賣出股數(自行買賣)",
                "自營商買進股數(避險)",
                "自營商賣出股數(避險)",
            ]
            return _Response(
                {
                    "stat": "OK",
                    "fields": fields,
                    "data": [["2330", "台積電", "1000", "500", "300", "100", "80", "50", "20", "10"]],
                }
            )
        if url == TwseClient.MARGIN_URL:
            return _Response([{"股票代號": "2330", "融資今日餘額": "1234", "融券今日餘額": "56"}])
        if url == TwseClient.REVENUE_URL:
            return _Response([{"資料年月": "11504", "公司代號": "2330", "營業收入-當月營收": "999999"}])
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("src.data_provider.twse_client.requests.get", fake_get)
    client = TwseClient(fallback=_Fallback(), cache_dir=tmp_path)

    institutional = client.institutional("2330", date(2026, 6, 1), date(2026, 6, 3))
    margin = client.margin("2330", date(2026, 6, 1), date(2026, 6, 3))
    revenue = client.monthly_revenue("2330", date(2026, 4, 1), date(2026, 6, 3))

    assert institutional["name"].tolist() == ["Foreign_Investor", "Investment_Trust", "Dealer"]
    assert institutional["buy"].tolist() == [1000.0, 300.0, 100.0]
    assert margin.iloc[-1]["MarginPurchaseTodayBalance"] == 1234.0
    assert margin.iloc[-1]["ShortSaleTodayBalance"] == 56.0
    assert revenue.iloc[-1]["revenue"] == 999999.0
    assert calls.count(TwseClient.STOCK_DAY_ALL_URL) == 1
    assert calls.count(TwseClient.INSTITUTIONAL_URL) == 1
    assert calls.count(TwseClient.MARGIN_URL) == 1
    assert calls.count(TwseClient.REVENUE_URL) == 1
    assert client.source_status()["official_snapshots"]["institutional"]["valid"] is True
    assert client.source_status()["official_snapshots"]["revenue"]["date"] == "2026-04-01"


def test_tpex_official_batch_snapshots_avoid_twse_html_and_finmind_network(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_get(url, params=None, headers=None, timeout=20):
        calls.append(url)
        if url == TwseClient.TPEX_QUOTES_URL:
            return _Response([{
                "Date": "1150603",
                "SecuritiesCompanyCode": "6510",
                "CompanyName": "精測",
                "Close": "1000",
                "Open": "980",
                "High": "1010",
                "Low": "970",
                "TradingShares": "123456",
            }])
        if url == TwseClient.TPEX_INSTITUTIONAL_URL:
            return _Response([{
                "Date": "1150603",
                "SecuritiesCompanyCode": "6510",
                "ForeignInvestorsIncludeMainlandAreaInvestors-TotalBuy": "1000",
                "ForeignInvestorsIncludeMainlandAreaInvestors-TotalSell": "400",
                "SecuritiesInvestmentTrustCompanies-TotalBuy": "300",
                "SecuritiesInvestmentTrustCompanies-TotalSell": "100",
                "Dealers-TotalBuy": "80",
                "Dealers-TotalSell": "20",
            }])
        if url == TwseClient.TPEX_MARGIN_URL:
            return _Response([{
                "Date": "1150603",
                "SecuritiesCompanyCode": "6510",
                "MarginPurchaseBalance": "1234",
                "ShortSaleBalance": "56",
            }])
        if url == TwseClient.STOCK_DAY_ALL_URL:
            return _Response([])
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("src.data_provider.twse_client.requests.get", fake_get)
    client = TwseClient(fallback=_Fallback(), cache_dir=tmp_path)

    prices = client.stock_prices("6510", date(2026, 6, 3), date(2026, 6, 3))
    institutional = client.institutional("6510", date(2026, 6, 3), date(2026, 6, 3))
    margin = client.margin("6510", date(2026, 6, 3), date(2026, 6, 3))

    assert prices.iloc[-1]["close"] == 1000.0
    assert institutional["buy"].tolist() == [1000.0, 300.0, 80.0]
    assert margin.iloc[-1]["MarginPurchaseTodayBalance"] == 1234.0
    assert TwseClient.STOCK_DAY_URL not in calls
    assert calls.count(TwseClient.TPEX_QUOTES_URL) == 1
    assert calls.count(TwseClient.TPEX_INSTITUTIONAL_URL) == 1
    assert calls.count(TwseClient.TPEX_MARGIN_URL) == 1
    status = client.source_status()["official_snapshots"]
    assert status["tpex_quotes"]["valid"] is True
    assert status["tpex_institutional"]["valid"] is True
    assert status["tpex_margin"]["valid"] is True
