from src.news.headline_classifier import classify_headlines
from src.news.policy_signal import classify_policy_headlines


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
