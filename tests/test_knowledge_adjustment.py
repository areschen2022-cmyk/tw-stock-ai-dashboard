import json

from src.scoring.knowledge_adjustment import apply_knowledge_adjustment, load_knowledge_context
from src.scoring.score_engine import StockScore


def _score(action: str = "可追") -> StockScore:
    return StockScore(
        stock_id="2330",
        total_score=88,
        label="BUY_WATCH",
        price=100.0,
        technical_score=25,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=3,
        action=action,
        entry_decision="開盤確認",
        reasons={"technical": ["放量長紅"], "risk": []},
        trigger_tags=["題材過熱", "技術突破"],
        themes=["AI伺服器"],
    )


def test_knowledge_adjustment_no_context_is_noop():
    score = _score()

    apply_knowledge_adjustment(score, {"rows": []})

    assert score.action == "可追"
    assert score.total_score == 88
    assert score.knowledge_notes == []


def test_knowledge_adjustment_downgrades_matched_failure_pattern_without_changing_score():
    score = _score(action="可追")
    context = {
        "source": "test",
        "rows": [
            {
                "topic": "台股失敗歸因：題材過熱",
                "claim": "題材過熱常出現在失敗樣本，5 日平均報酬 -4.2%。",
                "status": "backtest_supported",
                "confidence": 0.8,
                "tags": ["題材過熱", "失敗歸因"],
            }
        ],
    }

    apply_knowledge_adjustment(score, context)

    assert score.action == "等拉回"
    assert score.total_score == 88
    assert score.knowledge_adjustment["original_action"] == "可追"
    assert score.knowledge_adjustment["adjusted_action"] == "等拉回"
    assert "knowledge" in score.reasons
    assert "智慧庫修正" in score.trigger_tags


def test_knowledge_adjustment_positive_match_does_not_promote_action():
    score = _score(action="只觀察")
    score.trigger_tags = ["放量長紅"]
    context = {
        "source": "test",
        "rows": [
            {
                "topic": "台股成功歸因：放量長紅",
                "claim": "放量長紅在歷史樣本有效，平均報酬 +3.1%。",
                "status": "pending_validation",
                "confidence": 0.7,
                "tags": ["放量長紅", "成功歸因"],
            }
        ],
    }

    apply_knowledge_adjustment(score, context)

    assert score.action == "只觀察"
    assert score.total_score == 88
    assert score.knowledge_adjustment["positive_matches"]
    assert not score.knowledge_adjustment["negative_matches"]


def test_load_knowledge_context_prefers_latest_export_rows(tmp_path):
    export_dir = tmp_path / "data" / "knowledge_exports"
    export_dir.mkdir(parents=True)
    rows = [
        {
            "topic": "舊教訓",
            "claim": "舊資料",
            "status": "backtest_supported",
            "updated_at": "2026-07-01T08:00:00+08:00",
        },
        {
            "topic": "新教訓",
            "claim": "近期低勝率拆解",
            "status": "backtest_supported",
            "updated_at": "2026-07-17T08:00:00+08:00",
        },
    ]
    (export_dir / "taiwan_stock_learning.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )

    context = load_knowledge_context(tmp_path, limit=1)

    assert context["rows"][0]["topic"] == "新教訓"
