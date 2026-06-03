from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field


_COMMON_STOP_TERMS = {
    "台股",
    "股價",
    "法人",
    "外資",
    "投信",
    "營收",
    "公司",
    "市場",
    "產業",
    "今日",
    "今年",
    "明年",
    "需求",
    "題材",
    "概念",
    "個股",
    "族群",
    "看好",
    "受惠",
    "布局",
    "商機",
    "新聞",
    "盤中",
    "開盤",
    "收盤",
    "大盤",
}

_DEFAULT_SEEDS = (
    "石英元件",
    "石英",
    "玻纖布",
    "Low CTE",
    "碳化矽",
    "SiC",
    "機器視覺",
    "邊緣AI",
    "太空資料中心",
    "雷射星間鏈路",
    "耐輻射",
)

_TERM_RE = re.compile(
    r"([A-Za-z0-9+\-]{2,18}|[\u4e00-\u9fffA-Za-z0-9+\-]{2,18}"
    r"(?:元件|材料|設備|模組|封裝|通訊|衛星|電源|散熱|記憶體|機器人|玻纖|載板|電網|重電|軍工|儲能|"
    r"光通訊|矽光子|液冷|石英|碳化矽|電池|電纜|線材|鏡頭|面板|機殼|連接器|資料中心))"
)
_QUOTED_RE = re.compile(r"[「『]([^」』]{2,18})[」』]")
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
    """Find recurring concepts that are not covered by the existing theme map.

    This is intentionally conservative: it records candidates for review but
    does not change trading scores. A later version can promote proven
    candidates into config/theme_universe.
    """
    cfg = config or {}
    if not cfg.get("enabled", True):
        return []

    min_mentions = max(1, int(cfg.get("min_mentions", 2)))
    max_candidates = max(1, int(cfg.get("max_candidates", 8)))
    max_headlines = max(1, int(cfg.get("max_headlines_per_candidate", 4)))
    stop_terms = set(_COMMON_STOP_TERMS) | set(cfg.get("stop_terms", []))
    seed_terms = tuple(dict.fromkeys([*_DEFAULT_SEEDS, *cfg.get("seed_terms", [])]))
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
        score = mentions * 3 + min(len(stock_hits[term]), 4) * 2
        if any(marker in term for marker in ("元件", "材料", "設備", "模組", "封裝", "通訊", "資料中心")):
            score += 1
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
            if keyword:
                terms.add(_normalize_term(str(keyword)))
    return terms


def _candidate_terms(headline: str, seed_terms: tuple[str, ...]) -> set[str]:
    terms: set[str] = set()
    for seed in seed_terms:
        if seed and seed.lower() in headline.lower():
            terms.add(seed)
    terms.update(match.group(1) for match in _TERM_RE.finditer(headline))
    terms.update(match.group(1) for match in _QUOTED_RE.finditer(headline))
    return terms


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", "", term.strip(" ，。！？、:：|｜()（）[]【】"))


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
    return True


def _stock_hits(headline: str, stock_names: dict[str, str]) -> list[str]:
    hits: list[str] = []
    for code in _STOCK_CODE_RE.findall(headline):
        name = stock_names.get(code)
        hits.append(f"{code} {name}" if name else code)
    for code, name in stock_names.items():
        if name and name in headline:
            label = f"{code} {name}"
            if label not in hits:
                hits.append(label)
    return hits
