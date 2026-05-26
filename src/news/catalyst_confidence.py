from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalystConfidence:
    grade: str
    label: str
    reason: str
    evidence_count: int


CONFIDENCE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}

CONFIRMED_TERMS = (
    "公告",
    "正式",
    "法說",
    "財報",
    "營收",
    "接單",
    "出貨",
    "股東會",
    "簽署",
    "授權",
    "通過",
    "申請",
    "SEC",
    "S-1",
    "Nasdaq filing",
    "prospectus",
)

REPORT_TERMS = (
    "Reuters",
    "Bloomberg",
    "Nikkei",
    "鉅亨",
    "MoneyDJ",
    "工商",
    "經濟日報",
    "中央社",
    "TechCrunch",
    "Axios",
)

RUMOR_TERMS = (
    "傳",
    "傳聞",
    "據傳",
    "市場傳出",
    "可能",
    "有望",
    "倒數",
    "reportedly",
    "sources say",
    "could",
    "may",
    "eyes",
    "targets",
)

SPECULATIVE_TERMS = (
    "概念",
    "題材",
    "願景",
    "未來",
    "想像",
    "長線",
    "藍海",
    "太空地產",
    "火星殖民",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def classify_catalyst_confidence(headlines: list[str]) -> CatalystConfidence:
    """Classify event credibility from matched headlines.

    The grade describes evidence quality only. It does not imply buy/sell advice.
    """
    evidence = [headline for headline in headlines if headline]
    if not evidence:
        return CatalystConfidence("D", "低", "未找到可佐證新聞", 0)

    joined = " ".join(evidence[:5])
    confirmed_hits = sum(1 for headline in evidence if _contains_any(headline, CONFIRMED_TERMS))
    report_hits = sum(1 for headline in evidence if _contains_any(headline, REPORT_TERMS))
    rumor_hits = sum(1 for headline in evidence if _contains_any(headline, RUMOR_TERMS))
    speculative_hits = sum(1 for headline in evidence if _contains_any(headline, SPECULATIVE_TERMS))

    if confirmed_hits >= 2 or (confirmed_hits >= 1 and len(evidence) >= 2 and rumor_hits == 0):
        return CatalystConfidence("A", "已確認", "公告/財報/正式事件佐證", len(evidence))
    if report_hits >= 1 and rumor_hits <= report_hits:
        return CatalystConfidence("B", "高可信報導", "可信媒體或多源報導，仍需追蹤正式文件", len(evidence))
    if rumor_hits >= 1:
        return CatalystConfidence("C", "市場傳聞", "含傳聞或 sources say 類訊號，需等正式確認", len(evidence))
    if speculative_hits >= 1 or _contains_any(joined, SPECULATIVE_TERMS):
        return CatalystConfidence("D", "概念延伸", "偏概念或長線想像，短線需降低權重", len(evidence))
    if len(evidence) >= 3:
        return CatalystConfidence("B", "多源升溫", "多則新聞同時命中，可信度中高", len(evidence))
    return CatalystConfidence("C", "一般新聞", "新聞命中但缺少正式佐證", len(evidence))


def classify_theme_catalysts(matched_headlines: dict[str, list[str]]) -> dict[str, CatalystConfidence]:
    return {
        theme: classify_catalyst_confidence(headlines)
        for theme, headlines in matched_headlines.items()
        if headlines
    }
