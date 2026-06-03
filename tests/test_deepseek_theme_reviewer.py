from __future__ import annotations

import json
from datetime import date

from src.news.deepseek_theme_reviewer import apply_theme_review_adjustments, review_theme_headlines


class _FakeDeepSeekClient:
    enabled = True

    def __init__(self) -> None:
        self.calls = []

    def chat_json(self, model, messages, max_tokens=500):
        self.calls.append((model, messages, max_tokens))
        return json.dumps(
            {
                "reviews": [
                    {
                        "theme_key": "memory",
                        "confidence": "high",
                        "adjustment": 3,
                        "reason": "多則台股供應鏈新聞",
                    }
                ]
            },
            ensure_ascii=False,
        )


def test_deepseek_theme_review_only_reviews_high_value_themes() -> None:
    client = _FakeDeepSeekClient()
    result = review_theme_headlines(
        {
            "memory": ["HBM 供應鏈報價上升，華邦電與南亞科受關注"],
            "cooling_power": ["散熱概念股整理"],
        },
        {"memory": 10, "cooling_power": 2},
        {"memory": "記憶體/HBM", "cooling_power": "散熱/液冷"},
        date(2026, 6, 3),
        {
            "deepseek_theme_review": {
                "enabled": True,
                "min_theme_score": 8,
                "max_themes": 1,
                "max_headlines_per_theme": 2,
            }
        },
        client=client,
    )

    adjusted = apply_theme_review_adjustments({"memory": 10, "cooling_power": 2}, result)

    assert len(client.calls) == 1
    assert result.reviews["memory"].confidence == "high"
    assert adjusted["memory"] == 13
    assert adjusted["cooling_power"] == 2


def test_deepseek_theme_review_skips_without_key() -> None:
    class DisabledClient:
        enabled = False

    result = review_theme_headlines(
        {"memory": ["HBM headline"]},
        {"memory": 10},
        {"memory": "記憶體/HBM"},
        date(2026, 6, 3),
        {"deepseek_theme_review": {"enabled": True}},
        client=DisabledClient(),
    )

    assert result.reviews == {}
    assert result.skipped_reason == "missing_deepseek_key"
