from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests


@dataclass
class ThemeSignal:
    active_themes: list[str]
    summary: str
    headlines: list[str]
    scores: dict[str, int]


def _fetch_url(url: str, timeout: int = 15) -> str:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0)"},
    )
    response.raise_for_status()
    return response.text


def _rss_titles(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    titles: list[str] = []
    for item in root.findall(".//item"):
        title = item.findtext("title")
        if title:
            titles.append(html.unescape(title.strip()))
    return titles


def _html_titles(text: str) -> list[str]:
    candidates = re.findall(r"<h[123][^>]*>(.*?)</h[123]>", text, flags=re.I | re.S)
    titles: list[str] = []
    for raw in candidates:
        clean = re.sub(r"<[^>]+>", "", raw)
        clean = html.unescape(re.sub(r"\s+", " ", clean)).strip()
        if 6 <= len(clean) <= 80:
            titles.append(clean)
    return titles


def fetch_theme_signal(config: dict) -> ThemeSignal:
    news_cfg = config.get("web_news", {})
    if not news_cfg.get("enabled", False):
        return ThemeSignal([], "新聞題材未啟用", [], {})

    headlines: list[str] = []
    for url in news_cfg.get("urls", []):
        try:
            text = _fetch_url(url)
        except requests.RequestException:
            continue
        titles = _rss_titles(text)
        if not titles:
            titles = _html_titles(text)
        headlines.extend(titles[:15])

    deduped = list(dict.fromkeys(headlines))
    keyword_map = news_cfg.get("theme_keywords", {})
    scores = {theme: 0 for theme in keyword_map}
    for headline in deduped:
        lower = headline.lower()
        for theme, keywords in keyword_map.items():
            for keyword in keywords:
                if keyword.lower() in lower:
                    scores[theme] += 1
                    break

    ranked = [(theme, score) for theme, score in sorted(scores.items(), key=lambda item: item[1], reverse=True) if score > 0]
    active = [theme for theme, _ in ranked]
    max_themes = int(config.get("opportunity", {}).get("max_active_themes", 3))
    active = active[:max_themes]
    theme_names = config.get("theme_pools", {})
    active_names = [f"{theme_names.get(theme, {}).get('name', theme)}({scores[theme]})" for theme in active]
    summary = "、".join(active_names) if active_names else "未偵測到明顯題材"
    return ThemeSignal(active, summary, deduped[:8], scores)
