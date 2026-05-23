from __future__ import annotations

import json
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import date
from math import ceil
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
    store=None,
    status_out: dict[str, Any] | None = None,
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

    min_agree_count = int(cfg.get("min_agree_count", 5))
    pick_action = str(cfg.get("pick_action", "可追"))

    candidates = [_candidate_payload(row) for row in rows[:top_n]]
    perf_context = ""
    if store is not None:
        try:
            perf_context = _build_perf_context(store.ai_council_summary(as_of))
            if perf_context:
                log.info("AI council: injecting performance context (%d chars)", len(perf_context))
        except Exception as exc:
            log.warning("AI council: failed to load performance context: %s", exc)

    model_reviews: list[dict[str, Any]] = []
    failed_models: list[str] = []
    timed_out_models: list[str] = []
    timeout = int(cfg.get("timeout", 45))

    def _call_model(model: str) -> dict[str, Any] | None:
        try:
            content = client.chat_json(
                model,
                _messages(as_of, candidates, perf_context=perf_context),
                max_tokens=int(cfg.get("max_tokens", 900)),
            )
            return _parse_model_review(model, content)
        except Exception as exc:
            log.warning("AI council model failed %s: %s", model, exc)
            return None

    max_workers = max(1, min(len(models), int(cfg.get("max_workers", len(models)))))
    default_total_timeout = (timeout + 5) * ceil(len(models) / max_workers)
    total_timeout = int(cfg.get("total_timeout", default_total_timeout))
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {pool.submit(_call_model, model): model for model in models}
        try:
            for future in as_completed(futures, timeout=total_timeout):
                result = future.result()
                if result is not None:
                    model_reviews.append(result)
                else:
                    failed_models.append(futures[future])
        except TimeoutError:
            pending = [model for future, model in futures.items() if not future.done()]
            timed_out_models.extend(pending)
            log.warning("AI council timed out waiting for models: %s", ", ".join(pending))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if status_out is not None:
        successful_models = [item["model"] for item in model_reviews]
        health = model_health(
            requested_models=models,
            successful_models=successful_models,
            failed_models=failed_models,
            timed_out_models=timed_out_models,
        )
        status_out.update(
            {
                "requested_models": len(models),
                "successful_models": len(successful_models),
                "failed_models": failed_models,
                "timed_out_models": timed_out_models,
                "success_model_names": successful_models,
                "available_ratio": round(len(successful_models) / len(models), 2) if models else 0,
                "health": health,
            }
        )

    return _consensus(
        as_of,
        candidates,
        model_reviews,
        min_agree_count=min_agree_count,
        pick_action=pick_action,
    )


def _candidate_payload(row: dict) -> dict:
    return {
        "stock_id": row.get("stock_id"),
        "name": row.get("name"),
        "score": row.get("score"),
        "grade": row.get("grade"),
        "action": row.get("action"),
        "decision_reason": row.get("trigger_summary") or row.get("decision_reason"),
        "technical": row.get("technical"),
        "chip": row.get("chip"),
        "fundamental": row.get("fundamental"),
        "risk": row.get("risk"),
        "themes": row.get("themes", []),
    }


def _build_perf_context(summary: dict, min_completed: int = 20) -> str:
    rows = []
    for row in summary.get("by_action", []):
        if int(row.get("completed") or 0) >= min_completed:
            rows.append(
                f"{row['action']}：{row['completed']}筆，"
                f"5日勝率 {row['win_rate_5d']}%，平均報酬 {row['avg_return_5d']}%"
            )
    if not rows:
        return ""
    return (
        "【本系統近期追蹤績效，僅供參考，不代表未來表現】\n"
        + "；".join(rows)
        + "\n請用此資料校準信心，但不要只因歷史勝率高低直接改變方向。"
    )


def _messages(as_of: date, candidates: list[dict], perf_context: str = "") -> list[dict[str, str]]:
    user_payload: dict[str, Any] = {
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
    }
    if perf_context:
        user_payload["system_track_record"] = perf_context
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
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


def _parse_model_review(model: str, content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        log.warning("AI council JSON parse failed for %s: %s | content: %.200s", model, exc, content)
        return {"model": model, "reviews": []}
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


def _consensus(
    as_of: date,
    candidates: list[dict],
    model_reviews: list[dict[str, Any]],
    *,
    min_agree_count: int = 5,
    pick_action: str = "可追",
) -> list[dict[str, Any]]:
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
        agreement_count = action_counts[consensus_action]
        pick_agreement_count = action_counts.get(pick_action, 0)
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
                "agreement_count": agreement_count,
                "pick_agreement_count": pick_agreement_count,
                "is_ai_pick": consensus_action == pick_action and pick_agreement_count >= min_agree_count,
                "reason": "；".join(reasons[:2])[:180],
                "model_reviews": reviews,
            }
        )
    return results


def select_ai_picks(
    reviews: list[dict[str, Any]],
    *,
    min_agree_count: int = 5,
    pick_action: str = "可追",
    fallback_count: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    strong_picks = [review for review in reviews if review.get("is_ai_pick")]
    if strong_picks or fallback_count <= 0:
        return strong_picks, False

    fallback_candidates = [
        review
        for review in reviews
        if review.get("consensus_action") == pick_action and int(review.get("pick_agreement_count") or 0) > 0
    ]
    fallback_candidates.sort(
        key=lambda review: (
            int(review.get("pick_agreement_count") or 0),
            int(review.get("agreement_count") or 0),
            float(review.get("confidence") or 0),
            int(review.get("score") or 0),
        ),
        reverse=True,
    )
    fallback_picks = []
    for review in fallback_candidates[:fallback_count]:
        copied = dict(review)
        copied["is_ai_fallback_pick"] = True
        copied["strong_pick_required_votes"] = min_agree_count
        fallback_picks.append(copied)
    return fallback_picks, bool(fallback_picks)


def model_health(
    *,
    requested_models: list[str],
    successful_models: list[str],
    failed_models: list[str],
    timed_out_models: list[str],
) -> dict[str, Any]:
    requested = len(requested_models)
    success = len(successful_models)
    failed = len(failed_models)
    timed_out = len(timed_out_models)
    available_ratio = (success / requested) if requested else 0
    timeout_ratio = (timed_out / requested) if requested else 0
    score = round(max(0, min(100, available_ratio * 100 - timeout_ratio * 25)))
    if requested == 0:
        label = "未設定"
    elif score >= 80:
        label = "穩定"
    elif score >= 50:
        label = "降級可用"
    else:
        label = "不穩定"
    return {
        "label": label,
        "score": score,
        "requested": requested,
        "success": success,
        "failed": failed,
        "timed_out": timed_out,
        "available_ratio": round(available_ratio, 2),
        "timeout_ratio": round(timeout_ratio, 2),
    }


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
