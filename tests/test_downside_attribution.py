from datetime import date

from src.storage.sqlite_store import SQLiteStore
from src.report.downside_attribution import (
    annotate_exit_risks,
    build_downside_attribution,
    classify_downside_reasons,
)


def test_classify_chip_distribution_first() -> None:
    result = classify_downside_reasons(["法人賣、融資增、股價轉弱", "外資連 3 日賣超"])
    assert result["category"] == "chip_distribution"
    assert result["label"] == "籌碼倒貨"


def test_classify_technical_breakdown() -> None:
    result = classify_downside_reasons(["跌破 MA20", "爆量長黑，疑似資金撤退"])
    assert result["category"] == "technical_breakdown"
    assert result["label"] == "技術轉弱"


def test_annotate_exit_risks_adds_fields() -> None:
    rows = [{"stock_id": "2330", "reasons": ["散戶過熱", "散戶增加但近 3 日股價未轉強"]}]
    annotated = annotate_exit_risks(rows)
    assert annotated[0]["downside_category"] == "retail_overheat"
    assert annotated[0]["downside_label"] == "散戶過熱"


def test_build_downside_attribution_summary() -> None:
    payload = build_downside_attribution(
        date(2026, 7, 24),
        [
            {"stock_id": "2330", "name": "台積電", "level": "紅色警戒", "risk_score": 6, "reasons": ["外資連 3 日賣超"]},
            {"stock_id": "2308", "name": "台達電", "level": "紅色警戒", "risk_score": 5, "reasons": ["融資增 9.0% 但股價跌"]},
        ],
    )
    assert payload["summary"] == "主要跌因：籌碼倒貨 2 檔"
    assert payload["top_category"]["label"] == "籌碼倒貨"
    assert payload["items"][0]["downside_label"] == "籌碼倒貨"


def test_exit_risk_store_keeps_downside_labels(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    store.save_exit_risks(
        [
            {
                "stock_id": "2330",
                "name": "台積電",
                "level": "紅色警戒",
                "risk_score": 6,
                "current_score": 80,
                "previous_score": 95,
                "price": 100.0,
                "reasons": ["外資連 3 日賣超"],
                "action": "準備減碼",
                "downside_category": "chip_distribution",
                "downside_label": "籌碼倒貨",
            }
        ],
        date(2026, 7, 24),
    )
    summary = store.exit_risk_summary(date(2026, 7, 24))
    assert summary["items"][0]["downside_label"] == "籌碼倒貨"
    assert summary["downside_stats"][0]["label"] == "籌碼倒貨"
