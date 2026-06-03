from __future__ import annotations

from datetime import date

from src.report.potential_radar import build_potential_radar_candidates


def test_potential_radar_prefers_early_confluence() -> None:
    rows = [
        {
            "stock_id": "2408",
            "name": "南亞科",
            "score": 82,
            "grade": "A",
            "label": "BUY_WATCH",
            "decision_light": "yellow",
            "entry_decision": "等拉回",
            "action_context": "今日未進場",
            "retail_context": "籌碼轉乾淨",
            "retail_context_reason": "散戶人數下降但股價抗跌",
            "pattern_tags": ["陽包陰"],
            "pattern_risk_tags": [],
            "themes": ["記憶體/HBM"],
            "opportunity_score": 6,
            "price": 100.0,
        },
        {
            "stock_id": "2330",
            "name": "台積電",
            "score": 100,
            "grade": "S+",
            "label": "BUY_WATCH",
            "decision_light": "green",
            "entry_decision": "可追",
            "retail_context": "籌碼轉乾淨",
            "pattern_tags": ["突破"],
            "themes": ["AI伺服器"],
            "opportunity_score": 8,
            "price": 1500.0,
        },
        {
            "stock_id": "9999",
            "name": "風險股",
            "score": 80,
            "grade": "A",
            "label": "BUY_WATCH",
            "decision_light": "red",
            "entry_decision": "避免",
            "retail_context": "籌碼轉乾淨",
            "pattern_tags": ["陽包陰"],
            "themes": ["題材"],
            "price": 10.0,
        },
    ]

    candidates = build_potential_radar_candidates(rows, date(2026, 6, 3))

    assert [row["stock_id"] for row in candidates] == ["2408"]
    assert candidates[0]["potential_score"] >= 8
    assert "散戶減少/籌碼轉乾淨" in candidates[0]["tags"]
    assert "K線轉強:陽包陰" in candidates[0]["tags"]
    assert candidates[0]["reason"].startswith("潛力分")
