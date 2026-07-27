from __future__ import annotations

from dataclasses import dataclass, field


PRIMARY_MARKET_RULES: tuple[dict, ...] = (
    {
        "label": "SpaceX / Starlink IPO",
        "label_zh": "SpaceX/Starlink 上市傳聞",
        "themes": ["low_orbit_satellite", "network_optical_communication", "silicon_photonics"],
        "weight": 10,
        "confidence": "watch",
        "keywords": ["spacex ipo", "spacex listing", "starlink ipo", "spacex 上市", "starlink 上市"],
        "risk_note": "僅屬初級市場傳聞或籌資預期，需確認正式文件與台廠營收連結。",
    },
    {
        "label": "Satellite / space infrastructure funding",
        "label_zh": "衛星基礎建設募資",
        "themes": ["low_orbit_satellite", "network_optical_communication", "defense_policy"],
        "weight": 8,
        "confidence": "signal",
        "keywords": ["satellite funding", "space infrastructure", "leo constellation", "衛星募資", "太空基礎建設"],
        "risk_note": "偏向產業前導訊號，需追蹤訂單、發射量與供應鏈角色。",
    },
    {
        "label": "AI infrastructure IPO / fundraising",
        "label_zh": "AI 基礎建設 IPO/募資",
        "themes": ["ai_server", "advanced_packaging", "cooling_power", "memory"],
        "weight": 7,
        "confidence": "signal",
        "keywords": ["ai ipo", "ai infrastructure ipo", "ai startup funding", "ai data center funding", "ai 基礎建設 ipo", "ai 募資"],
        "risk_note": "需區分資本市場熱度與實際訂單，避免只因新聞熱度追價。",
    },
    {
        "label": "Taiwan IPO / listing",
        "label_zh": "台灣新股/上市櫃",
        "themes": [],
        "weight": 5,
        "confidence": "watch",
        "keywords": ["新股", "興櫃", "申請上市", "申請上櫃", "ipo", "上市案", "上櫃案", "掛牌"],
        "risk_note": "新股事件只記錄不加權，避免把申購或掛牌熱度誤判為可買訊號。",
    },
)


@dataclass
class PrimaryMarketSignal:
    summary: str
    theme_boosts: dict[str, int] = field(default_factory=dict)
    matched_headlines: dict[str, list[str]] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)


def classify_primary_market_headlines(headlines: list[str]) -> PrimaryMarketSignal:
    boosts: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    events: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for headline in headlines:
        text = str(headline or "").strip()
        lower = text.lower()
        if not text:
            continue
        for rule in PRIMARY_MARKET_RULES:
            if not any(str(keyword).lower() in lower for keyword in rule["keywords"]):
                continue
            key = (str(rule["label"]), text)
            if key in seen:
                continue
            seen.add(key)
            score = int(rule["weight"])
            if any(word in lower for word in ["files", "上市", "申請", "核准", "approved", "掛牌"]):
                score += 3
                confidence = "confirmed"
            else:
                confidence = str(rule["confidence"])
            event = {
                "event": rule["label"],
                "event_zh": rule["label_zh"],
                "headline": text,
                "themes": list(rule["themes"]),
                "confidence": confidence,
                "score": score,
                "risk_note": rule["risk_note"],
            }
            events.append(event)
            for theme in event["themes"]:
                boosts[theme] = boosts.get(theme, 0) + score
                matched.setdefault(theme, []).append(text)

    events.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    if not events:
        return PrimaryMarketSignal("初級市場：未偵測到明顯 IPO/募資催化", {}, {}, [])

    labels: list[str] = []
    for event in events:
        label = str(event.get("event_zh") or event.get("event"))
        if label not in labels:
            labels.append(label)
        if len(labels) >= 2:
            break
    summary = "初級市場：" + "、".join(labels) + "；只作題材前導觀察，需確認正式文件與營收連結。"
    return PrimaryMarketSignal(
        summary=summary,
        theme_boosts=dict(sorted(boosts.items(), key=lambda item: item[1], reverse=True)),
        matched_headlines={theme: rows[:5] for theme, rows in matched.items()},
        events=events[:8],
    )
