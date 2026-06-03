from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.ai.deepseek_client import DeepSeekClient

log = logging.getLogger(__name__)


@dataclass
class ThemeReview:
    theme_key: str
    confidence: str
    adjustment: int
    reason: str


@dataclass
class ThemeReviewResult:
    reviews: dict[str, ThemeReview] = field(default_factory=dict)
    skipped_reason: str = ""


def review_theme_headlines(
    matched_headlines: dict[str, list[str]],
    scores: dict[str, int],
    theme_names: dict[str, str],
    as_of: date,
    config: dict,
    client: DeepSeekClient | None = None,
) -> ThemeReviewResult:
    """Use DeepSeek sparingly to review only high-value theme/news matches.

    The review is intentionally a small confidence overlay for news themes. It
    should not replace keyword matching and should not directly change stock
    scores. This keeps token usage bounded and limits model hallucination risk.
    """
    cfg = config.get("deepseek_theme_review", {})
    if not cfg.get("enabled", False):
        return ThemeReviewResult(skipped_reason="disabled")

    client = client or DeepSeekClient(timeout=int(cfg.get("timeout", 30)))
    if not client.enabled:
        return ThemeReviewResult(skipped_reason="missing_deepseek_key")

    min_score = int(cfg.get("min_theme_score", 8))
    max_themes = max(1, int(cfg.get("max_themes", 3)))
    max_headlines = max(1, int(cfg.get("max_headlines_per_theme", 3)))
    max_tokens = max(200, int(cfg.get("max_tokens", 500)))

    candidates = [
        (theme, int(scores.get(theme, 0)), matched_headlines.get(theme, [])[:max_headlines])
        for theme in matched_headlines
        if int(scores.get(theme, 0)) >= min_score and matched_headlines.get(theme)
    ]
    candidates.sort(key=lambda row: row[1], reverse=True)
    candidates = candidates[:max_themes]
    if not candidates:
        return ThemeReviewResult(skipped_reason="no_high_value_theme")

    payload = {
        "as_of": as_of.isoformat(),
        "task": "請只根據提供的新聞標題判斷題材是否真的與台股投資題材相關。不要補充外部新聞。",
        "schema": {
            "reviews": [
                {
                    "theme_key": "string",
                    "confidence": "high|medium|low",
                    "adjustment": -2,
                    "reason": "20字內中文理由",
                }
            ]
        },
        "rules": [
            "若標題明確提到台股、公司、產業鏈、訂單、營收、法人或供應鏈，confidence 可為 high。",
            "若只是海外大趨勢或傳聞，confidence 為 medium 或 low。",
            "adjustment 只能是 -2 到 +3 的整數，用來小幅修正題材熱度，不可當成買賣建議。",
        ],
        "themes": [
            {
                "theme_key": theme,
                "theme_name": theme_names.get(theme, theme),
                "keyword_score": score,
                "headlines": headlines,
            }
            for theme, score, headlines in candidates
        ],
    }

    try:
        content = client.chat_json(
            str(cfg.get("model", "deepseek-chat")),
            [
                {
                    "role": "system",
                    "content": "你是台股新聞題材複核員，只輸出 JSON，不提供投資建議。",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=max_tokens,
        )
        data = _parse_json(content)
    except Exception as exc:
        log.warning("DeepSeek theme review failed: %s", exc)
        return ThemeReviewResult(skipped_reason="api_failed")

    reviews: dict[str, ThemeReview] = {}
    for row in _rows(data):
        theme = str(row.get("theme_key") or "")
        if theme not in {item[0] for item in candidates}:
            continue
        confidence = str(row.get("confidence") or "medium").lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        adjustment = _clamp_int(row.get("adjustment"), -2, 3)
        reviews[theme] = ThemeReview(
            theme_key=theme,
            confidence=confidence,
            adjustment=adjustment,
            reason=str(row.get("reason") or "").strip()[:40],
        )

    return ThemeReviewResult(reviews=reviews)


def apply_theme_review_adjustments(scores: dict[str, int], result: ThemeReviewResult) -> dict[str, int]:
    adjusted = dict(scores)
    for theme, review in result.reviews.items():
        adjusted[theme] = max(0, int(adjusted.get(theme, 0)) + int(review.adjustment))
    return adjusted


def _parse_json(content: str) -> Any:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("reviews") or data.get("results") or []
        return [row for row in rows if isinstance(row, dict)]
    return []


def _clamp_int(value, lower: int, upper: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = 0
    return max(lower, min(upper, number))
