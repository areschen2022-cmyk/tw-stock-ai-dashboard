from __future__ import annotations

from dataclasses import dataclass, field


POLICY_KEYWORDS: dict[str, list[str]] = {
    "power_grid": ["電網", "電力", "核電", "儲能", "變壓器", "電力基礎建設"],
    "defense_ai": ["國防", "軍工", "無人機", "軍備", "防衛"],
    "advanced_packaging": ["半導體補助", "晶片法案", "先進封裝", "出口管制"],
    "silicon_photonics": ["高速網路", "資料中心網路", "CPO", "光通訊"],
    "financial_revaluation": ["降息", "併購", "金融整併", "壽險"],
}


@dataclass
class PolicySignal:
    summary: str
    theme_boosts: dict[str, int] = field(default_factory=dict)
    matched_headlines: dict[str, list[str]] = field(default_factory=dict)


def classify_policy_headlines(
    headlines: list[str],
    policy_keywords: dict[str, list[str]] | None = None,
) -> PolicySignal:
    """Classify policy headlines without changing core stock scores."""
    keyword_map = policy_keywords or POLICY_KEYWORDS
    boosts: dict[str, int] = {theme: 0 for theme in keyword_map}
    matched: dict[str, list[str]] = {theme: [] for theme in keyword_map}

    for headline in headlines:
        lower = headline.lower()
        for theme, keywords in keyword_map.items():
            if any(keyword.lower() in lower for keyword in keywords):
                boosts[theme] += 1
                matched[theme].append(headline)

    active = sorted(
        ((theme, score) for theme, score in boosts.items() if score > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    if active:
        summary = "、".join(f"{theme}:{score}" for theme, score in active[:4])
    else:
        summary = "未偵測到明顯政策訊號"
    return PolicySignal(
        summary=summary,
        theme_boosts={theme: score for theme, score in active},
        matched_headlines={theme: rows[:5] for theme, rows in matched.items() if rows},
    )
