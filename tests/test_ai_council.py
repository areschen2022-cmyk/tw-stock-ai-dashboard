from __future__ import annotations

import json
from datetime import date, timedelta

from src.ai.model_council import run_ai_council
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


def test_ai_council_builds_consensus() -> None:
    rows = [{"stock_id": "2408", "name": "南亞科", "score": 90, "grade": "S", "decision_reason": "測試"}]
    reviews = run_ai_council(
        rows,
        date(2026, 5, 19),
        {"ai_council": {"enabled": True, "top_n": 1, "models": ["model-a", "model-b"]}},
        client=_FakeClient(),
    )

    assert reviews[0]["stock_id"] == "2408"
    assert reviews[0]["consensus_action"] == "可追"
    assert reviews[0]["model_count"] == 2


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
