from src.news.headline_classifier import classify_headlines
from src.news.policy_signal import classify_policy_headlines
from src.news.web_theme import fetch_theme_signal
from src.report.monitoring import detect_alerts


def test_headline_classifier_filters_negative_context_and_boosts_stock_relevance() -> None:
    result = classify_headlines(
        [
            "液冷散熱商機升溫，奇鋐 3017 受惠",
            "天氣炎熱散熱需求增加",
            "美光帶動記憶體報價上揚",
        ],
        {
            "cooling_power": ["散熱", "液冷"],
            "memory": ["記憶體", "美光"],
        },
        stock_names={"3017": "奇鋐"},
    )

    assert result.scores["cooling_power"] == 3
    assert result.scores["memory"] == 1
    assert result.matched_headlines["cooling_power"] == ["液冷散熱商機升溫，奇鋐 3017 受惠"]


def test_policy_signal_reports_theme_boosts_without_stock_scoring() -> None:
    signal = classify_policy_headlines(["政府推動電網與儲能基礎建設", "壽險受惠降息循環"])

    assert signal.theme_boosts["power_grid"] == 1
    assert signal.theme_boosts["financial_revaluation"] == 1
    assert "power_grid" in signal.summary


def test_passive_component_headline_matches_theme_keywords() -> None:
    result = classify_headlines(
        ["被動元件強勢撐盤，國巨、立隆電、金山電創高"],
        {"passive_components": ["被動元件", "國巨", "立隆電", "金山電"]},
        stock_names={"2327": "國巨", "2472": "立隆電", "8042": "金山電"},
    )

    assert result.scores["passive_components"] == 3


def test_satellite_headline_matches_spacex_theme_keywords() -> None:
    result = classify_headlines(
        ["SpaceX 傳 6/12 那斯達克上市，Starlink 低軌衛星供應鏈昇達科、華通受惠"],
        {"low_orbit_satellite": ["SpaceX", "Starlink", "低軌衛星", "昇達科", "華通"]},
        stock_names={"3491": "昇達科", "2313": "華通"},
    )

    assert result.scores["low_orbit_satellite"] >= 3
    assert result.matched_headlines["low_orbit_satellite"]


def test_cloudflare_challenge_is_not_treated_as_news(monkeypatch, tmp_path) -> None:
    class Response:
        text = "<html><title>Just a moment...</title><script src='https://challenges.cloudflare.com/x'></script></html>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("src.news.web_theme.requests.get", lambda *args, **kwargs: Response())

    signal = fetch_theme_signal(
        {
            "web_news": {
                "enabled": True,
                "urls": ["https://www.wantgoo.com/stock"],
                "theme_keywords": {"memory": ["記憶體"]},
            },
            "stock_names": {},
            "opportunity": {"max_active_themes": 5},
            "theme_pools": {},
        }
    )

    assert signal.source_count == 0
    assert signal.failed_count == 1
    assert signal.active_themes == []


def test_news_source_failure_generates_alert(tmp_path) -> None:
    from datetime import date

    from src.news.web_theme import ThemeSignal
    from src.storage.sqlite_store import SQLiteStore

    alerts = detect_alerts(
        [],
        date(2026, 5, 18),
        SQLiteStore(tmp_path / "test.sqlite3"),
        {"label": "正常"},
        overseas=None,
        theme_signal=ThemeSignal([], "未偵測到明顯題材", [], {"memory": 0}, source_count=0, failed_count=3),
    )

    assert "新聞題材資料源異常" in alerts[0]
