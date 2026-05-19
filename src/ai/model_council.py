from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date
from typing import Any

from src.ai.openrouter_client import OpenRouterClient


VALID_ACTIONS = ("可追", "等拉回", "只觀察", "避免")
ACTION_RANK = {"可追": 3, "等拉回": 2, "只觀察": 1, "避免": 0}

log = logging.getLogger(__name__)


def run_ai_council(
    rows: list[dict],
    as_of: date,
    config: dict,
    client: OpenRouterClient | None = None,
) -> list[dict[str, Any]]:
    cfg = config.get("ai_council", {})
    if not cfg.get("enabled", False):
        return []

    client = client or OpenRouterClient(timeout=int(cfg.get("timeout", 45)))
    if not client.enabled:
        log.info("AI council skipped: OPENROUTER_API_KEY is not set")
        return []

    top_n = int(cfg.get("top_n", 5))
    models = list(cfg.get("models", []))
    if not models:
        return []

    candidates = [_candidate_payload(row) for row in rows[:top_n]]
    model_reviews: list[dict[str, Any]] = []
    for model in models:
        try:
            content = client.chat_json(
                model,
                _messages(as_of, candidates),
                max_tokens=int(cfg.get("max_tokens", 900)),
            )
            model_reviews.append(_parse_model_review(model, content))
        except Exception as exc:
            log.warning("AI council model failed %s: %s", model, exc)

    return _consensus(as_of, candidates, model_reviews)


def _candidate_payload(row: dict) -> dict:
    return {
        "stock_id": row.get("stock_id"),
        "name": row.get("name"),
        "score": row.get("score"),
        "grade": row.get("grade"),
        "action": row.get("action"),
        "decision_reason": row.get("decision_reason") or row.get("trigger_summary"),
        "technical": row.get("technical"),
        "chip": row.get("chip"),
        "fundamental": row.get("fundamental"),
        "risk": row.get("risk"),
        "entry_limit_price": row.get("entry_limit_price"),
        "stop_price": row.get("stop_price"),
        "themes": row.get("themes", []),
    }


def _messages(as_of: date, candidates: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是台股交易訊號複核員。只能根據使用者提供的結構化資料判斷，"
                "不可自行編造新聞或價格。輸出必須是 JSON。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "as_of": as_of.isoformat(),
                    "task": "逐檔給出 action: 可追/等拉回/只觀察/避免，並用一句話說明主要風險或優勢。",
                    "schema": {
                        "reviews": [
                            {
                                "stock_id": "string",
                                "action": "可追|等拉回|只觀察|避免",
                                "confidence": 0.0,
                                "reason": "string",
                            }
                        ]
                    },
                    "candidates": candidates,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _parse_model_review(model: str, content: str) -> dict[str, Any]:
    payload = json.loads(content)
    rows = payload.get("reviews") if isinstance(payload, dict) else []
    parsed = []
    for row in rows or []:
        action = str(row.get("action") or "只觀察").strip()
        if action not in VALID_ACTIONS:
            action = "只觀察"
        parsed.append(
            {
                "stock_id": str(row.get("stock_id") or ""),
                "action": action,
                "confidence": _float(row.get("confidence"), 0.5),
                "reason": str(row.get("reason") or "")[:120],
            }
        )
    return {"model": model, "reviews": parsed}


def _consensus(as_of: date, candidates: list[dict], model_reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_stock: dict[str, list[dict[str, Any]]] = {str(row["stock_id"]): [] for row in candidates}
    for model_result in model_reviews:
        model = model_result["model"]
        for review in model_result.get("reviews", []):
            if review["stock_id"] in by_stock:
                by_stock[review["stock_id"]].append({**review, "model": model})

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        stock_id = str(candidate["stock_id"])
        reviews = by_stock.get(stock_id, [])
        if not reviews:
            continue
        actions = [row["action"] for row in reviews]
        action_counts = Counter(actions)
        consensus_action = sorted(
            action_counts,
            key=lambda action: (action_counts[action], ACTION_RANK[action]),
            reverse=True,
        )[0]
        avg_confidence = sum(float(row["confidence"]) for row in reviews) / len(reviews)
        reasons = [row["reason"] for row in reviews if row.get("reason")]
        results.append(
            {
                "review_date": as_of.isoformat(),
                "stock_id": stock_id,
                "name": candidate.get("name", stock_id),
                "score": candidate.get("score"),
                "grade": candidate.get("grade"),
                "consensus_action": consensus_action,
                "confidence": round(avg_confidence, 2),
                "model_count": len(reviews),
                "reason": "；".join(reasons[:2])[:180],
                "model_reviews": reviews,
            }
        )
    return results


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
