from __future__ import annotations

import datetime as dt

from src.news.cnyes_api import CnyesArticle, fetch_cnyes_news
from src.news.web_theme import fetch_theme_signal


def test_fetch_cnyes_news_parses_structured_fields(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "items": {
                    "last_page": 1,
                    "data": [
                        {
                            "newsId": 123,
                            "title": "SpaceX 上市題材帶動低軌衛星供應鏈",
                            "summary": "昇達科與華通受市場關注",
                            "publishAt": 1779108424,
                            "stock": [],
                            "market": [{"code": "3491"}],
                            "otherProduct": ["TWS:2313:STOCK:COMMON"],
                            "keyword": ["SpaceX", "低軌衛星"],
                        }
                    ],
                }
            }

    monkeypatch.setattr("src.news.cnyes_api.requests.get", lambda *args, **kwargs: Response())

    articles = fetch_cnyes_news(
        now=dt.datetime(2026, 5, 18, 8, 20, tzinfo=dt.timezone.utc),
        days_back=1,
        limit=10,
        max_pages=1,
    )

    assert len(articles) == 1
    assert articles[0].news_id == "123"
    assert articles[0].stock_codes == ["3491", "2313"]
    assert "SpaceX" in articles[0].keywords


def test_cnyes_articles_feed_theme_scoring(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.news.web_theme.fetch_cnyes_news",
        lambda **kwargs: [
            CnyesArticle(
                news_id="1",
                title="SpaceX 上市帶動台廠低軌衛星供應鏈",
                summary="昇達科、華通受惠，相關光通訊與 PCB 題材升溫",
                stock_codes=["3491", "2313"],
                keywords=["SpaceX", "低軌衛星"],
            )
        ],
    )

    signal = fetch_theme_signal(
        {
            "web_news": {
                "enabled": True,
                "cnyes_api": {"enabled": True, "days_back": 1, "limit": 10, "max_pages": 1},
                "urls": [],
                "theme_keywords": {
                    "low_orbit_satellite": ["SpaceX", "低軌衛星", "昇達科", "華通"],
                },
            },
            "stock_names": {"3491": "昇達科", "2313": "華通"},
            "opportunity": {"max_active_themes": 5},
            "theme_pools": {"low_orbit_satellite": {"name": "低軌衛星/SpaceX"}},
        }
    )

    assert signal.source_count == 1
    assert signal.failed_count == 0
    assert signal.active_themes == ["low_orbit_satellite"]
    assert signal.headlines == ["SpaceX 上市帶動台廠低軌衛星供應鏈"]
