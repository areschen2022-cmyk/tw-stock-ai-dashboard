from src.news.headline_classifier import classify_headlines
from src.news.catalyst_confidence import classify_catalyst_confidence
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
    assert result.quality["cooling_power"].startswith("高")
    assert result.quality["memory"].startswith("低")


def test_policy_signal_reports_theme_boosts_without_stock_scoring() -> None:
    signal = classify_policy_headlines(["政府推動電網與儲能基礎建設", "壽險受惠降息循環"])

    assert signal.theme_boosts["power_grid"] == 1
    assert signal.theme_boosts["financial_revaluation"] == 1
    assert "能源與重電" in signal.summary
    assert "金融評價修復" in signal.summary


def test_us_policy_radar_boosts_sensitive_themes() -> None:
    signal = classify_policy_headlines([
        "House passes NDAA defense bill with drone defense and Starlink funding",
        "Trump tariff plan targets China semiconductor supply chain",
        "Commerce Department expands AI chip export control entity list",
    ])

    assert signal.us_events
    assert signal.theme_boosts["defense_policy"] > 0
    assert signal.theme_boosts["advanced_packaging"] > 0
    assert signal.us_events[0]["sensitivity"] == "high"
    assert signal.us_events[0]["event_zh"]
    assert signal.us_events[0]["headline_zh"]


def test_passive_component_headline_matches_theme_keywords() -> None:
    result = classify_headlines(
        ["被動元件強勢撐盤，國巨、立隆電、金山電創高"],
        {"passive_components": ["被動元件", "國巨", "立隆電", "金山電"]},
        stock_names={"2327": "國巨", "2472": "立隆電", "8042": "金山電"},
    )

    assert result.scores["passive_components"] == 3
    assert result.quality["passive_components"].startswith("高")


def test_satellite_headline_matches_spacex_theme_keywords() -> None:
    result = classify_headlines(
        ["SpaceX 傳 6/12 那斯達克上市，Starlink 低軌衛星供應鏈昇達科、華通受惠"],
        {"low_orbit_satellite": ["SpaceX", "Starlink", "低軌衛星", "昇達科", "華通"]},
        stock_names={"3491": "昇達科", "2313": "華通"},
    )

    assert result.scores["low_orbit_satellite"] >= 3
    assert result.matched_headlines["low_orbit_satellite"]


def test_spacex_rumor_is_marked_as_market_rumor() -> None:
    confidence = classify_catalyst_confidence([
        "SpaceX reportedly targets June 12 Nasdaq listing, sources say",
        "SpaceX 傳 6/12 掛牌帶動低軌衛星供應鏈",
    ])

    assert confidence.grade == "C"
    assert confidence.label == "市場傳聞"


def test_confirmed_catalyst_is_marked_high_confidence() -> None:
    confidence = classify_catalyst_confidence([
        "光聖股東會表示 AI 資料中心需求帶動光通訊營收成長",
        "公司公告 5 月營收年增創高",
    ])

    assert confidence.grade == "A"
    assert confidence.label == "已確認"


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
