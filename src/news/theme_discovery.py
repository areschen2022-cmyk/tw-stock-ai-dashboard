from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field


_COMMON_STOP_TERMS = {
    "台股",
    "大盤",
    "上市",
    "上櫃",
    "法人",
    "外資",
    "投信",
    "營收",
    "獲利",
    "股價",
    "漲停",
    "跌停",
    "美股",
    "指數",
    "今日",
    "明日",
    "焦點",
    "熱門",
    "新聞",
    "市場",
    "公司",
    "財報",
    "COMPUTEX",
    "Factset",
    "FactSet",
    "EPS",
}

_DEFAULT_SEEDS = (
    "石英元件",
    "石英",
    "碳化矽",
    "SiC",
    "玻纖布",
    "Low CTE",
    "太空資料中心",
    "耐輻射記憶體",
    "航太級封裝",
    "雷射星間鏈路",
    "邊緣AI",
    "機器視覺",
    "核能SMR",
)

_DOMAIN_SUFFIXES = (
    "元件",
    "材料",
    "模組",
    "封裝",
    "散熱",
    "液冷",
    "電源",
    "重電",
    "光通訊",
    "低軌衛星",
    "機器人",
    "感測器",
    "矽光子",
    "玻纖布",
    "銅箔基板",
    "石英元件",
    "碳化矽",
    "氮化鎵",
    "先進製程",
    "先進封裝",
)

_TERM_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9+\-]{2,18}")
_STOCK_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?:-TW)?(?!\d)")


@dataclass
class ThemeDiscoveryCandidate:
    keyword: str
    score: int
    mentions: int
    headlines: list[str] = field(default_factory=list)
    stock_hits: list[str] = field(default_factory=list)
    status: str = "觀察中"

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "score": self.score,
            "mentions": self.mentions,
            "headlines": self.headlines[:5],
            "stock_hits": self.stock_hits[:8],
            "status": self.status,
        }


def discover_emerging_themes(
    headlines: list[str],
    keyword_map: dict[str, list[str]],
    stock_names: dict[str, str] | None = None,
    config: dict | None = None,
) -> list[dict]:
    """Find recurring concepts not yet covered by existing theme keywords.

    The detector is conservative by design: it records candidates for review
    but does not change trading scores until a theme is explicitly promoted.
    """

    cfg = config or {}
    if not cfg.get("enabled", True):
        return []

    min_mentions = max(1, int(cfg.get("min_mentions", 2)))
    max_candidates = max(1, int(cfg.get("max_candidates", 8)))
    max_headlines = max(1, int(cfg.get("max_headlines_per_candidate", 4)))
    stop_terms = set(_COMMON_STOP_TERMS) | {str(item) for item in cfg.get("stop_terms", [])}
    seed_terms = tuple(dict.fromkeys([*_DEFAULT_SEEDS, *[str(item) for item in cfg.get("seed_terms", [])]]))
    existing_terms = _existing_terms(keyword_map)
    stock_names = stock_names or {}

    counts: Counter[str] = Counter()
    headline_hits: dict[str, list[str]] = defaultdict(list)
    stock_hits: dict[str, set[str]] = defaultdict(set)

    for headline in headlines:
        if not headline:
            continue
        for term in _candidate_terms(headline, seed_terms):
            normalized = _normalize_term(term)
            if not _is_useful_term(normalized, existing_terms, stop_terms):
                continue
            counts[normalized] += 1
            if len(headline_hits[normalized]) < max_headlines and headline not in headline_hits[normalized]:
                headline_hits[normalized].append(headline)
            for hit in _stock_hits(headline, stock_names):
                stock_hits[normalized].add(hit)

    candidates: list[ThemeDiscoveryCandidate] = []
    for term, mentions in counts.items():
        if mentions < min_mentions:
            continue
        evidence_bonus = min(len(stock_hits[term]), 4) * 2
        domain_bonus = 2 if _looks_like_domain_term(term) else 0
        score = mentions * 3 + evidence_bonus + domain_bonus
        candidates.append(
            ThemeDiscoveryCandidate(
                keyword=term,
                score=score,
                mentions=mentions,
                headlines=headline_hits[term],
                stock_hits=sorted(stock_hits[term]),
            )
        )

    candidates.sort(key=lambda item: (item.score, item.mentions, item.keyword), reverse=True)
    return [item.to_dict() for item in candidates[:max_candidates]]


def _existing_terms(keyword_map: dict[str, list[str]]) -> set[str]:
    terms: set[str] = set()
    for keywords in keyword_map.values():
        for keyword in keywords or []:
            normalized = _normalize_term(str(keyword))
            if normalized:
                terms.add(normalized)
    return terms


def _candidate_terms(headline: str, seed_terms: tuple[str, ...]) -> set[str]:
    terms: set[str] = set()
    lower_headline = headline.lower()
    for seed in seed_terms:
        if seed and seed.lower() in lower_headline:
            terms.add(seed)
    for match in _TERM_RE.finditer(headline):
        term = match.group(0)
        if _looks_like_domain_term(term):
            terms.add(term)
    return terms


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", "", term.strip(" ，、。；：:()（）[]【】「」『』"))


def _looks_like_domain_term(term: str) -> bool:
    if term in _DEFAULT_SEEDS:
        return True
    return any(suffix in term for suffix in _DOMAIN_SUFFIXES)


def _is_useful_term(term: str, existing_terms: set[str], stop_terms: set[str]) -> bool:
    if len(term) < 2 or len(term) > 18:
        return False
    if term in stop_terms:
        return False
    lower = term.lower()
    if any(lower == item.lower() or lower in item.lower() or item.lower() in lower for item in existing_terms):
        return False
    if re.fullmatch(r"[A-Za-z0-9+\-]+", term) and len(term) < 3:
        return False
    if any(stop in term for stop in stop_terms if len(stop) >= 2):
        return False
    return _looks_like_domain_term(term)


def _stock_hits(headline: str, stock_names: dict[str, str]) -> list[str]:
    hits: list[str] = []
    for code in _STOCK_CODE_RE.findall(headline):
        name = stock_names.get(code)
        if name:
            hits.append(f"{code} {name}")
    for code, name in stock_names.items():
        if name and name in headline:
            label = f"{code} {name}"
            if label not in hits:
                hits.append(label)
    return hits
