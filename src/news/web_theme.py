from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

from src.news.cnyes_api import fetch_cnyes_news
from src.news.headline_classifier import classify_headlines
from src.news.policy_signal import PolicySignal, classify_policy_headlines

try:
    import feedparser
except ImportError:  # pragma: no cover - fallback for minimal local envs
    feedparser = None

log = logging.getLogger(__name__)


@dataclass
class ThemeMomentum:
    """Per-theme momentum derived from historical daily scores stored in SQLite."""
    today: int
    avg_3d: float
    trend: str          # "急升🔥" / "升溫↑" / "持平→" / "降溫↓" / "消退" / "-"
    history: list[int]  # last N days, newest first


@dataclass
class ThemeSignal:
    active_themes: list[str]
    summary: str
    headlines: list[str]
    scores: dict[str, int]
    matched_headlines: dict[str, list[str]] = field(default_factory=dict)
    momentum: dict[str, ThemeMomentum] = field(default_factory=dict)
    policy: PolicySignal | None = None
    source_count: int = 0
    failed_count: int = 0


# ──────────────────────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────────────────────

def _fetch_url(url: str, timeout: int = 15) -> str:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0)"},
    )
    response.raise_for_status()
    if "Just a moment..." in response.text and "challenges.cloudflare.com" in response.text:
        raise requests.RequestException(f"Cloudflare challenge page returned for {url}")
    return response.text


def _rss_titles(text: str) -> list[str]:
    if feedparser is not None:
        feed = feedparser.parse(text)
        titles = [
            html.unescape(str(entry.get("title", "")).strip())
            for entry in feed.entries
            if entry.get("title")
        ]
        if titles:
            return titles
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


# ──────────────────────────────────────────────────────────────
# Scoring helpers
# ──────────────────────────────────────────────────────────────

def _score_headlines(
    deduped: list[str],
    keyword_map: dict[str, list[str]],
    stock_names: dict[str, str] | None = None,
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Return (scores, matched_headlines) for all themes."""
    result = classify_headlines(deduped, keyword_map, stock_names=stock_names)
    return result.scores, result.matched_headlines


def _build_momentum(raw: dict[str, dict]) -> dict[str, ThemeMomentum]:
    """Convert raw SQLite momentum rows → ThemeMomentum objects."""
    result: dict[str, ThemeMomentum] = {}
    for theme_key, data in raw.items():
        today = int(data.get("today", 0))
        avg_3d = float(data.get("avg_3d", 0.0))
        history = [int(v) for v in data.get("history", [])]

        if today >= 3 and avg_3d > 0 and today >= avg_3d * 1.5:
            trend = "急升🔥"
        elif today >= 2 and today > avg_3d:
            trend = "升溫↑"
        elif today > 0 and abs(today - avg_3d) < 0.5:
            trend = "持平→"
        elif avg_3d >= 2 and today < avg_3d * 0.6:
            trend = "降溫↓"
        elif today == 0 and avg_3d >= 1:
            trend = "消退"
        else:
            trend = "-"

        result[theme_key] = ThemeMomentum(
            today=today,
            avg_3d=avg_3d,
            trend=trend,
            history=history,
        )
    return result


# ──────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────

def fetch_theme_signal(config: dict, store=None, as_of=None) -> ThemeSignal:
    """Fetch RSS/HTML news, score by theme keywords, and optionally persist to *store*.

    Args:
        config:  Full application config dict.
        store:   Optional ``SQLiteStore`` instance.  When provided:
                 1. Today's scores are written to ``theme_daily_scores`` table.
                 2. Momentum (3-day trend) is loaded and attached to the signal.
        as_of:   Date for persistence.  Defaults to ``date.today()``.
    """
    news_cfg = config.get("web_news", {})
    if not news_cfg.get("enabled", False):
        return ThemeSignal([], "新聞題材未啟用", [], {})

    # ── 1. Collect headlines ───────────────────────────────────
    headlines: list[str] = []
    scoring_headlines: list[str] = []
    source_count = 0
    failed_count = 0

    cnyes_cfg = news_cfg.get("cnyes_api", {})
    if cnyes_cfg.get("enabled", False):
        try:
            articles = fetch_cnyes_news(
                days_back=int(cnyes_cfg.get("days_back", 1)),
                limit=int(cnyes_cfg.get("limit", 50)),
                max_pages=int(cnyes_cfg.get("max_pages", 3)),
                timeout=int(cnyes_cfg.get("timeout", 10)),
            )
        except (requests.RequestException, ValueError) as exc:
            log.warning("fetch_theme_signal: failed cnyes_api — %s", exc)
            failed_count += 1
        else:
            if articles:
                source_count += 1
                stock_names = config.get("stock_names", {})
                headlines.extend(article.title for article in articles[:20])
                scoring_headlines.extend(article.scoring_text(stock_names) for article in articles)
            else:
                log.warning("fetch_theme_signal: no usable titles from cnyes_api")
                failed_count += 1

    for url in news_cfg.get("urls", []):
        try:
            text = _fetch_url(url)
        except requests.RequestException as exc:
            log.warning("fetch_theme_signal: failed %s — %s", url, exc)
            failed_count += 1
            continue
        titles = _rss_titles(text)
        if not titles:
            titles = _html_titles(text)
        if titles:
            source_count += 1
        else:
            log.warning("fetch_theme_signal: no usable titles from %s", url)
            failed_count += 1
        headlines.extend(titles[:15])
        scoring_headlines.extend(titles[:15])

    deduped = list(dict.fromkeys(headlines))
    deduped_scoring = list(dict.fromkeys(scoring_headlines or headlines))

    # ── 2. Score themes ────────────────────────────────────────
    keyword_map = news_cfg.get("theme_keywords", {})
    scores, matched = _score_headlines(
        deduped_scoring,
        keyword_map,
        stock_names=config.get("stock_names", {}),
    )
    policy_signal = classify_policy_headlines(deduped_scoring)

    # ── 3. Persist + load momentum ────────────────────────────
    momentum: dict[str, ThemeMomentum] = {}
    if store is not None:
        try:
            from datetime import date as _date
            target = as_of if as_of is not None else _date.today()
            store.save_theme_signal_scores(scores, matched, target)
            raw_momentum = store.theme_momentum(target)
            momentum = _build_momentum(raw_momentum)
        except Exception as exc:
            log.warning("fetch_theme_signal: store persistence failed — %s", exc)

    # ── 4. Rank active themes ──────────────────────────────────
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    active = [theme for theme, sc in ranked if sc > 0]
    max_themes = int(config.get("opportunity", {}).get("max_active_themes", 5))
    active = active[:max_themes]

    theme_pools = config.get("theme_pools", {})
    active_names: list[str] = []
    for theme in active:
        name = theme_pools.get(theme, {}).get("name", theme)
        trend_label = momentum.get(theme, ThemeMomentum(scores[theme], 0, "-", [])).trend
        suffix = f"{trend_label}" if trend_label != "-" else f"{scores[theme]}則"
        active_names.append(f"{name}({suffix})")

    summary = "、".join(active_names) if active_names else "未偵測到明顯題材"
    return ThemeSignal(
        active_themes=active,
        summary=summary,
        headlines=deduped[:8],
        scores=scores,
        matched_headlines={t: v[:5] for t, v in matched.items() if v},
        momentum=momentum,
        policy=policy_signal,
        source_count=source_count,
        failed_count=failed_count,
    )
