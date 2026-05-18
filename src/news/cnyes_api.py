from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests


CNYES_TW_STOCK_URL = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock"
TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass
class CnyesArticle:
    news_id: str
    title: str
    summary: str = ""
    publish_at: int | None = None
    stock_codes: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def scoring_text(self, stock_names: dict[str, str] | None = None) -> str:
        """Return a compact text blob for theme keyword scoring."""
        names = []
        if stock_names:
            names = [stock_names[code] for code in self.stock_codes if code in stock_names]
        parts = [
            self.title,
            self.summary[:180],
            " ".join(self.keywords),
            " ".join(self.stock_codes),
            " ".join(names),
        ]
        return " ".join(part for part in parts if part).strip()


def fetch_cnyes_news(
    *,
    days_back: int = 1,
    limit: int = 50,
    max_pages: int = 3,
    now: dt.datetime | None = None,
    timeout: int = 10,
) -> list[CnyesArticle]:
    """Fetch Taiwan stock news from Cnyes' public JSON API."""
    current = now or dt.datetime.now(TAIPEI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TAIPEI)
    start = current - dt.timedelta(days=max(1, days_back))

    articles: list[CnyesArticle] = []
    page = 1
    while page <= max(1, max_pages):
        response = requests.get(
            CNYES_TW_STOCK_URL,
            params={
                "startAt": int(start.timestamp()),
                "endAt": int(current.timestamp()),
                "limit": max(1, limit),
                "page": page,
            },
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0)",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items", {})
        rows = items.get("data", [])
        if not rows:
            break

        articles.extend(_parse_article(row) for row in rows if row.get("title"))
        last_page = int(items.get("last_page") or page)
        if page >= last_page:
            break
        page += 1

    return articles


def _parse_article(row: dict) -> CnyesArticle:
    return CnyesArticle(
        news_id=str(row.get("newsId") or ""),
        title=_clean_text(str(row.get("title") or "")),
        summary=_clean_text(str(row.get("summary") or "")),
        publish_at=_to_int(row.get("publishAt")),
        stock_codes=_extract_stock_codes(row),
        keywords=_extract_keywords(row),
    )


def _extract_stock_codes(row: dict) -> list[str]:
    codes: list[str] = []

    for item in row.get("stock") or []:
        if isinstance(item, str) and item.isdigit():
            codes.append(item)
        elif isinstance(item, dict):
            code = item.get("code") or item.get("symbol")
            if code:
                codes.append(str(code))

    for item in row.get("market") or []:
        if isinstance(item, dict):
            code = item.get("code") or item.get("symbol")
            if code:
                codes.append(str(code))

    for item in row.get("otherProduct") or []:
        if not isinstance(item, str):
            continue
        match = re.search(r"\bTWS:(\d{4})\b", item)
        if match:
            codes.append(match.group(1))

    return list(dict.fromkeys(code for code in codes if re.fullmatch(r"\d{4}", code)))


def _extract_keywords(row: dict) -> list[str]:
    raw = row.get("keyword") or []
    if isinstance(raw, str):
        raw = [raw]
    return list(dict.fromkeys(_clean_text(str(item)) for item in raw if item))


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
