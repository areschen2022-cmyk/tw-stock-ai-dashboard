from __future__ import annotations

from dataclasses import dataclass, field


NEGATIVE_KEYWORDS = ("天氣", "選舉", "疫情")


@dataclass
class HeadlineThemeScore:
    scores: dict[str, int]
    matched_headlines: dict[str, list[str]] = field(default_factory=dict)


def classify_headlines(
    headlines: list[str],
    keyword_map: dict[str, list[str]],
    stock_names: dict[str, str] | None = None,
    negative_keywords: tuple[str, ...] = NEGATIVE_KEYWORDS,
) -> HeadlineThemeScore:
    """Score headlines by theme keywords with simple false-positive protection.

    Base score is 1 per matching headline. If the headline also mentions a
    tracked Taiwan stock id or company name, add 2 extra points to the matched
    themes so market-relevant headlines rank higher.
    """
    scores: dict[str, int] = {theme: 0 for theme in keyword_map}
    matched: dict[str, list[str]] = {theme: [] for theme in keyword_map}
    tracked_terms = _tracked_terms(stock_names or {})

    for headline in headlines:
        if _is_negative_context(headline, negative_keywords):
            continue
        lower = headline.lower()
        relevance = 2 if any(term and term in headline for term in tracked_terms) else 0
        for theme, keywords in keyword_map.items():
            if any(keyword.lower() in lower for keyword in keywords):
                scores[theme] += 1 + relevance
                matched[theme].append(headline)

    return HeadlineThemeScore(scores=scores, matched_headlines=matched)


def _is_negative_context(headline: str, negative_keywords: tuple[str, ...]) -> bool:
    return any(keyword in headline for keyword in negative_keywords)


def _tracked_terms(stock_names: dict[str, str]) -> set[str]:
    terms: set[str] = set()
    for stock_id, name in stock_names.items():
        if stock_id:
            terms.add(str(stock_id))
        if name:
            terms.add(str(name))
    return terms
