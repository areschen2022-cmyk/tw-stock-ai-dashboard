from __future__ import annotations

from dataclasses import dataclass, field


TW_POLICY_RULES: tuple[dict, ...] = (
    {
        "label": "Drone / defense autonomy",
        "themes": ["defense_policy", "defense_ai", "low_orbit_satellite", "network_optical_communication"],
        "direction": "bullish",
        "sensitivity": "high",
        "weight": 12,
        "keywords": ["無人機", "無人載具", "反無人機", "國防自主", "軍工", "中科院", "軍用商規", "國防部"],
    },
    {
        "label": "Space / satellite policy",
        "themes": ["low_orbit_satellite", "network_optical_communication", "silicon_photonics"],
        "direction": "bullish",
        "sensitivity": "medium",
        "weight": 9,
        "keywords": ["低軌衛星", "衛星通訊", "太空產業", "星鏈", "地面站", "雷射星間鏈路"],
    },
    {
        "label": "Grid / energy infrastructure",
        "themes": ["power_grid", "energy_grid", "cooling_power"],
        "direction": "bullish",
        "sensitivity": "high",
        "weight": 10,
        "keywords": ["電網韌性", "強韌電網", "電力基礎建設", "儲能", "變壓器", "核電", "資料中心用電"],
    },
    {
        "label": "Semiconductor policy",
        "themes": ["advanced_packaging", "ai_server", "memory", "silicon_photonics"],
        "direction": "mixed",
        "sensitivity": "high",
        "weight": 10,
        "keywords": ["半導體補助", "半導體供應鏈", "先進封裝", "出口管制", "晶片法案", "AI晶片"],
    },
)


US_POLICY_RULES: tuple[dict, ...] = (
    {
        "label": "Trump tariff / China tariff",
        "themes": ["materials_recovery", "ai_server", "advanced_packaging"],
        "direction": "risk",
        "sensitivity": "high",
        "weight": 12,
        "keywords": ["trump tariff", "tariff", "china tariff", "reciprocal tariff", "trade war"],
    },
    {
        "label": "AI chip export control",
        "themes": ["advanced_packaging", "ai_server", "memory"],
        "direction": "risk",
        "sensitivity": "high",
        "weight": 18,
        "keywords": ["export control", "ai chip export", "chip export", "entity list", "semiconductor ban"],
    },
    {
        "label": "House / Senate China bill",
        "themes": ["defense_policy", "defense_ai", "network_optical_communication"],
        "direction": "mixed",
        "sensitivity": "high",
        "weight": 15,
        "keywords": ["house passes", "senate passes", "china bill", "select committee", "sanction"],
    },
    {
        "label": "Defense bill / NDAA",
        "themes": ["defense_policy", "defense_ai", "low_orbit_satellite"],
        "direction": "bullish",
        "sensitivity": "high",
        "weight": 15,
        "keywords": ["ndaa", "defense bill", "pentagon", "missile defense", "drone defense", "dod"],
    },
    {
        "label": "SpaceX / Starlink",
        "themes": ["low_orbit_satellite", "network_optical_communication", "silicon_photonics"],
        "direction": "bullish",
        "sensitivity": "medium",
        "weight": 10,
        "keywords": ["spacex", "starlink", "kuiper", "satellite internet", "leo satellite"],
    },
    {
        "label": "Data center power",
        "themes": ["power_grid", "energy_grid", "cooling_power"],
        "direction": "bullish",
        "sensitivity": "high",
        "weight": 14,
        "keywords": ["data center power", "grid upgrade", "nuclear power", "smr", "power demand", "electricity demand"],
    },
    {
        "label": "AI capex / hyperscaler",
        "themes": ["ai_server", "cooling_power", "advanced_packaging", "memory"],
        "direction": "bullish",
        "sensitivity": "medium",
        "weight": 9,
        "keywords": ["ai capex", "cloud capex", "hyperscaler", "nvidia", "amd", "broadcom", "blackwell"],
    },
)

US_POLICY_LABEL_ZH = {
    "Trump tariff / China tariff": "川普/中國關稅",
    "AI chip export control": "AI晶片出口管制",
    "House / Senate China bill": "美國國會對中法案",
    "Defense bill / NDAA": "國防授權法案/NDAA",
    "SpaceX / Starlink": "SpaceX/Starlink",
    "Data center power": "資料中心電力",
    "AI capex / hyperscaler": "AI資本支出/雲端大廠",
}

TW_POLICY_LABEL_ZH = {
    "Drone / defense autonomy": "無人機/國防自主",
    "Space / satellite policy": "太空/低軌衛星政策",
    "Grid / energy infrastructure": "電力能源基建",
    "Semiconductor policy": "半導體政策",
}

US_DIRECTION_ZH = {"risk": "偏風險", "bullish": "偏利多", "mixed": "多空交錯"}
US_CONFIDENCE_ZH = {"confirmed": "已確認", "signal": "訊號", "watch": "觀察"}

TW_CONFIRMED_TERMS = ("宣布", "通過", "核定", "公告", "啟動", "決議", "推動", "採購", "標案")
TW_WATCH_TERMS = ("研議", "規劃", "可望", "傳出", "預期", "擬", "有望", "將")
CONFIRMED_TERMS = ("announces", "announced", "passes", "passed", "approves", "approved", "signs", "signed")
WATCH_TERMS = ("may", "could", "proposal", "draft", "considering", "expected", "hearing", "urges")


POLICY_KEYWORDS: dict[str, list[str]] = {
    "power_grid": ["電網", "電力", "核電", "儲能", "變壓器", "電力基礎建設"],
    "defense_ai": ["國防", "軍工", "無人機", "軍備", "防衛"],
    "advanced_packaging": ["半導體補助", "晶片法案", "先進封裝", "出口管制"],
    "silicon_photonics": ["高速網路", "資料中心網路", "CPO", "光通訊"],
    "financial_revaluation": ["降息", "併購", "金融整併", "壽險"],
}

POLICY_THEME_NAMES: dict[str, str] = {
    "power_grid": "能源與重電",
    "defense_ai": "防禦與政策",
    "advanced_packaging": "先進封裝/CoWoS",
    "silicon_photonics": "矽光子/CPO",
    "financial_revaluation": "金融評價修復",
}

SUMMARY_THEME_ALIASES = {
    "defense_policy": "無人機/國防自主",
    "defense_ai": "無人機/國防自主",
    "low_orbit_satellite": "低軌衛星",
    "network_optical_communication": "網通/光通訊",
    "power_grid": "電力能源",
    "energy_grid": "電力能源",
    "cooling_power": "散熱/液冷",
    "advanced_packaging": "先進封裝",
    "ai_server": "AI伺服器",
    "memory": "記憶體",
    "silicon_photonics": "矽光子",
    "financial_revaluation": "金融評價修復",
}


@dataclass
class PolicySignal:
    summary: str
    theme_boosts: dict[str, int] = field(default_factory=dict)
    matched_headlines: dict[str, list[str]] = field(default_factory=dict)
    us_events: list[dict] = field(default_factory=list)
    tw_events: list[dict] = field(default_factory=list)


def classify_policy_headlines(
    headlines: list[str],
    policy_keywords: dict[str, list[str]] | None = None,
) -> PolicySignal:
    """Classify policy headlines without changing core stock scores."""
    keyword_map = policy_keywords or POLICY_KEYWORDS
    boosts: dict[str, int] = {theme: 0 for theme in keyword_map}
    matched: dict[str, list[str]] = {theme: [] for theme in keyword_map}

    tw_events = classify_taiwan_policy_events(headlines)
    for event in tw_events:
        for theme in event["themes"]:
            boosts.setdefault(theme, 0)
            matched.setdefault(theme, [])
            boosts[theme] += int(event["score"])
            matched[theme].append(event["headline"])

    us_events = classify_us_policy_events(headlines)
    for event in us_events:
        for theme in event["themes"]:
            boosts.setdefault(theme, 0)
            matched.setdefault(theme, [])
            boosts[theme] += int(event["score"])
            matched[theme].append(event["headline"])

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
        summary = _policy_summary(active, tw_events, us_events)
    else:
        summary = "未偵測到明顯政策訊號"
    return PolicySignal(
        summary=summary,
        theme_boosts={theme: score for theme, score in active},
        matched_headlines={theme: rows[:5] for theme, rows in matched.items() if rows},
        us_events=us_events[:8],
        tw_events=tw_events[:8],
    )


def classify_taiwan_policy_events(headlines: list[str]) -> list[dict]:
    """Return Taiwan policy events that can catalyze local thematic stocks."""
    events: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for headline in headlines:
        lower = headline.lower()
        for rule in TW_POLICY_RULES:
            if not any(keyword.lower() in lower for keyword in rule["keywords"]):
                continue
            confidence = "confirmed" if any(term in headline for term in TW_CONFIRMED_TERMS) else "watch"
            if confidence == "watch" and not any(term in headline for term in TW_WATCH_TERMS):
                confidence = "signal"
            score = int(rule["weight"])
            if confidence == "confirmed":
                score += 3
            elif confidence == "watch":
                score = max(3, score - 4)
            key = (str(rule["label"]), headline)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "event": rule["label"],
                    "event_zh": TW_POLICY_LABEL_ZH.get(str(rule["label"]), str(rule["label"])),
                    "headline": headline,
                    "headline_zh": _policy_headline_zh_tw(str(rule["label"]), str(rule["direction"]), confidence),
                    "themes": list(rule["themes"]),
                    "direction": rule["direction"],
                    "sensitivity": rule["sensitivity"],
                    "confidence": confidence,
                    "score": score,
                }
            )
    events.sort(key=lambda item: (item["sensitivity"] == "high", item["score"]), reverse=True)
    return events


def classify_us_policy_events(headlines: list[str]) -> list[dict]:
    """Return high-sensitivity US policy events that may lead Taiwan themes."""
    events: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for headline in headlines:
        lower = headline.lower()
        for rule in US_POLICY_RULES:
            if not any(keyword in lower for keyword in rule["keywords"]):
                continue
            confidence = "confirmed" if any(term in lower for term in CONFIRMED_TERMS) else "watch"
            if confidence == "watch" and not any(term in lower for term in WATCH_TERMS):
                confidence = "signal"
            score = int(rule["weight"])
            if confidence == "confirmed":
                score += 4
            elif confidence == "watch":
                score = max(3, score - 5)
            key = (str(rule["label"]), headline)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "event": rule["label"],
                    "event_zh": US_POLICY_LABEL_ZH.get(str(rule["label"]), str(rule["label"])),
                    "headline": headline,
                    "headline_zh": _policy_headline_zh(str(rule["label"]), str(rule["direction"]), confidence),
                    "themes": list(rule["themes"]),
                    "direction": rule["direction"],
                    "sensitivity": rule["sensitivity"],
                    "confidence": confidence,
                    "score": score,
                }
            )
    events.sort(key=lambda item: (item["sensitivity"] == "high", item["score"]), reverse=True)
    return events


def _policy_headline_zh(label: str, direction: str, confidence: str) -> str:
    return (
        f"{US_POLICY_LABEL_ZH.get(label, label)}出現{US_CONFIDENCE_ZH.get(confidence, confidence)}；"
        f"對相關台股題材影響為{US_DIRECTION_ZH.get(direction, direction)}。"
    )


def _policy_headline_zh_tw(label: str, direction: str, confidence: str) -> str:
    return (
        f"{TW_POLICY_LABEL_ZH.get(label, label)}出現{US_CONFIDENCE_ZH.get(confidence, confidence)}；"
        f"對相關台股題材影響為{US_DIRECTION_ZH.get(direction, direction)}。"
    )


def _policy_summary(active: list[tuple[str, int]], tw_events: list[dict], us_events: list[dict]) -> str:
    """Build one low-noise sentence for dashboard/Telegram use."""
    theme_labels: list[str] = []
    for theme, _score in active:
        label = SUMMARY_THEME_ALIASES.get(theme) or POLICY_THEME_NAMES.get(theme) or theme
        if label not in theme_labels:
            theme_labels.append(label)
        if len(theme_labels) >= 2:
            break

    if not theme_labels:
        return "未偵測到明顯政策訊號"

    prefix = "政策催化" if tw_events else "海外政策催化" if us_events else "政策催化"
    joined = "/".join(theme_labels)
    return f"{prefix}：{joined}升溫，相關股若放量需確認是否有訂單或只是題材炒作。"
