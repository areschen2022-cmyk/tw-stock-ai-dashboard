from __future__ import annotations

import json
from datetime import date, timedelta

from src.ai.model_council import model_health, run_ai_council, select_ai_picks
from src.scoring.score_engine import StockScore
from src.storage.sqlite_store import SQLiteStore


class _FakeClient:
    enabled = True

    def chat_json(self, model, messages, max_tokens=900):
        action = "可追" if model.endswith("a") else "等拉回"
        return json.dumps(
            {
                "reviews": [
                    {"stock_id": "2408", "action": action, "confidence": 0.7, "reason": f"{model} reason"}
                ]
            },
            ensure_ascii=False,
        )


class _FencedJsonClient:
    enabled = True

    def __init__(self) -> None:
        self.messages = []

    def chat_json(self, model, messages, max_tokens=900):
        self.messages.append(messages)
        return """```json
{"reviews":[{"stock_id":"2408","action":"可追","confidence":0.8,"reason":"JSON fenced"}]}
```"""


def test_ai_council_builds_consensus() -> None:
    rows = [{"stock_id": "2408", "name": "南亞科", "score": 90, "grade": "S", "decision_reason": "測試"}]
    status = {}
    reviews = run_ai_council(
        rows,
        date(2026, 5, 19),
        {"ai_council": {"enabled": True, "top_n": 1, "models": ["model-a", "model-b"]}},
        client=_FakeClient(),
        status_out=status,
    )

    assert reviews[0]["stock_id"] == "2408"
    assert reviews[0]["consensus_action"] == "可追"
    assert reviews[0]["model_count"] == 2
    assert reviews[0]["is_ai_pick"] is False
    assert status["requested_models"] == 2
    assert status["successful_models"] == 2
    assert status["available_ratio"] == 1
    assert status["health"]["label"] == "穩定"


def test_ai_council_requires_five_buy_votes_for_pick() -> None:
    rows = [{"stock_id": "2408", "name": "南亞科", "score": 90, "grade": "S", "decision_reason": "測試"}]
    reviews = run_ai_council(
        rows,
        date(2026, 5, 19),
        {
            "ai_council": {
                "enabled": True,
                "top_n": 1,
                "min_agree_count": 5,
                "models": ["model-a", "model-a", "model-a", "model-a", "model-a"],
            }
        },
        client=_FakeClient(),
    )

    assert reviews[0]["consensus_action"] == "可追"
    assert reviews[0]["pick_agreement_count"] == 5
    assert reviews[0]["is_ai_pick"] is True


def test_ai_council_does_not_pick_when_model_count_is_insufficient() -> None:
    rows = [{"stock_id": "2408", "name": "南亞科", "score": 90, "grade": "S", "decision_reason": "突破"}]
    reviews = run_ai_council(
        rows,
        date(2026, 5, 19),
        {"ai_council": {"enabled": True, "top_n": 1, "min_agree_count": 5, "models": ["model-a"]}},
        client=_FakeClient(),
    )

    picks, using_fallback = select_ai_picks(
        reviews,
        min_agree_count=4,
        min_model_count=5,
        pick_action="可追",
        fallback_count=1,
    )

    assert reviews[0]["is_ai_pick"] is False
    assert using_fallback is False
    assert picks == []


def test_ai_council_allows_four_of_five_strong_pick() -> None:
    rows = [{"stock_id": "2408", "name": "南亞科", "score": 90, "grade": "S", "decision_reason": "突破"}]
    reviews = run_ai_council(
        rows,
        date(2026, 5, 19),
        {
            "ai_council": {
                "enabled": True,
                "top_n": 1,
                "min_model_count": 5,
                "min_agree_count": 4,
                "models": ["model-a", "model-a", "model-a", "model-a", "model-b"],
            }
        },
        client=_FakeClient(),
    )

    assert reviews[0]["model_count"] == 5
    assert reviews[0]["pick_agreement_count"] == 4
    assert reviews[0]["is_ai_pick"] is True


def test_ai_council_accepts_fenced_json_and_redacts_strategy_prices() -> None:
    client = _FencedJsonClient()
    rows = [
        {
            "stock_id": "2408",
            "name": "南亞科",
            "score": 90,
            "grade": "S",
            "trigger_summary": "題材強共振",
            "entry_limit_price": 100,
            "stop_price": 90,
        }
    ]

    reviews = run_ai_council(
        rows,
        date(2026, 5, 19),
        {"ai_council": {"enabled": True, "top_n": 1, "models": ["model-a"]}},
        client=client,
    )
    payload = json.loads(client.messages[0][1]["content"])

    assert reviews[0]["consensus_action"] == "可追"
    assert "entry_limit_price" not in payload["candidates"][0]
    assert "stop_price" not in payload["candidates"][0]
    assert payload["candidates"][0]["decision_reason"] == "題材強共振"


def test_ai_council_summary_tracks_forward_win_rate(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    score0 = StockScore("2408", 90, "BUY_WATCH", 100.0, 0, 0, 0, 0, 0)
    store.save_daily_score(score0, day0)
    store.save_ai_council_reviews(
        [
            {
                "stock_id": "2408",
                "name": "南亞科",
                "score": 90,
                "grade": "S",
                "consensus_action": "可追",
                "confidence": 0.8,
                "model_count": 2,
                "agreement_count": 2,
                "pick_agreement_count": 2,
                "is_ai_pick": False,
                "reason": "AI 共識偏多",
            }
        ],
        day0,
    )
    for i, price in enumerate([101, 102, 103, 104, 110], start=1):
        store.save_daily_score(StockScore("2408", 90, "BUY_WATCH", price, 0, 0, 0, 0, 0), day0 + timedelta(days=i))

    store.update_forward_returns(day0 + timedelta(days=5))
    summary = store.ai_council_summary(day0 + timedelta(days=5))
    by_action = {row["action"]: row for row in summary["by_action"]}

    assert by_action["可追"]["completed"] == 1
    assert by_action["可追"]["win_rate_5d"] == 100
    assert by_action["可追"]["avg_return_5d"] == 10
    assert summary["items"][0]["agreement_count"] == 2
    assert summary["items"][0]["pick_agreement_count"] == 2


def test_model_health_scores_timeout_and_failures() -> None:
    health = model_health(
        requested_models=["a", "b", "c", "d"],
        successful_models=["a", "b"],
        failed_models=["c"],
        timed_out_models=["d"],
    )

    assert health["score"] == 44
    assert health["label"] == "不穩定"
    assert health["available_ratio"] == 0.5
