from __future__ import annotations

from datetime import date, timedelta

from src.report.potential_radar import build_potential_radar_candidates
from src.scoring.score_engine import StockScore
from src.storage.sqlite_store import SQLiteStore


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
            "action_context": "強勢但等拉回",
            "retail_context": "籌碼轉乾淨",
            "retail_context_reason": "散戶人數減少，價格尚未失控",
            "pattern_tags": ["突破整理"],
            "pattern_risk_tags": [],
            "trigger_tags": ["法人共振", "技術突破"],
            "themes": ["記憶體/HBM"],
            "theme_tiers": ["core"],
            "opportunity_score": 6,
            "technical_score": 14,
            "chip_score": 14,
            "fundamental_score": 14,
            "fundamental": "最新月營收年增 30%，營收加速創高",
            "risk": "風險條件可接受",
            "atr_pct": 4.2,
            "price": 100.0,
            "entry_limit_price": 103.0,
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
            "pattern_tags": ["放量長紅"],
            "themes": ["AI伺服器"],
            "opportunity_score": 8,
            "price": 1500.0,
        },
        {
            "stock_id": "9999",
            "name": "高風險股",
            "score": 80,
            "grade": "A",
            "label": "BUY_WATCH",
            "decision_light": "red",
            "entry_decision": "避開",
            "retail_context": "籌碼轉乾淨",
            "pattern_tags": ["突破整理"],
            "themes": ["題材"],
            "price": 10.0,
        },
    ]

    candidates = build_potential_radar_candidates(rows, date(2026, 6, 3))

    assert [row["stock_id"] for row in candidates] == ["2408"]
    assert candidates[0]["potential_score"] >= 10
    assert "散戶減少/籌碼轉乾淨" in candidates[0]["tags"]
    assert "K線轉強:突破整理" in candidates[0]["tags"]
    assert "法人開始同步" in candidates[0]["tags"]
    assert candidates[0]["stage"] == "pullback_watch"
    assert candidates[0]["stage_label"] == "強勢等拉回"
    assert candidates[0]["chase_risk"] == "low"
    assert candidates[0]["research_score"] >= 7
    assert candidates[0]["research_label"] == "順風研究"
    assert candidates[0]["stock_type_label"] == "成長確認型"
    assert candidates[0]["position_hint_label"] == "正常部位"
    assert any(item["label"] == "營收加速" and item["passed"] for item in candidates[0]["research_factors"])
    assert candidates[0]["reason"].startswith("強勢等拉回｜潛力分")


def test_potential_radar_penalizes_overheated_retail_and_volume_divergence() -> None:
    rows = [
        {
            "stock_id": "2344",
            "name": "華邦電",
            "score": 78,
            "grade": "A",
            "label": "BUY_WATCH",
            "decision_light": "yellow",
            "entry_decision": "只觀察",
            "retail_context": "散戶過熱，人數增加",
            "pattern_tags": ["突破整理"],
            "trigger_tags": ["放量不漲"],
            "themes": ["記憶體/HBM"],
            "opportunity_score": 6,
            "price": 50.0,
        }
    ]

    assert build_potential_radar_candidates(rows, date(2026, 6, 3)) == []


def test_potential_radar_filters_chasing_above_entry_limit() -> None:
    rows = [
        {
            "stock_id": "6770",
            "name": "力積電",
            "score": 88,
            "grade": "A",
            "label": "BUY_WATCH",
            "decision_light": "yellow",
            "entry_decision": "等拉回",
            "retail_context": "籌碼轉乾淨",
            "pattern_tags": ["突破整理"],
            "trigger_tags": ["法人共振", "技術突破"],
            "themes": ["AI伺服器"],
            "opportunity_score": 6,
            "price": 110.0,
            "entry_limit_price": 105.0,
        }
    ]

    assert build_potential_radar_candidates(rows, date(2026, 6, 3)) == []


def test_potential_radar_factor_attribution_tracks_winners_and_failures(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 6, 1)

    for stock_id in ["2408", "2344"]:
        store.save_daily_score(
            StockScore(stock_id, 80, "BUY_WATCH", 100.0, 0, 0, 0, 0, 0),
            day0,
        )

    store.save_potential_radar(
        [
            {
                "signal_date": day0.isoformat(),
                "stock_id": "2408",
                "name": "南亞科",
                "grade": "A",
                "total_score": 82,
                "potential_score": 9,
                "action": "等拉回",
                "reason": "潛力分 9",
                "tags": ["散戶減少/籌碼轉乾淨", "K線轉強:突破整理", "題材升溫:記憶體/HBM"],
                "themes": ["記憶體/HBM"],
                "entry_price": 100.0,
                "stage": "pullback_watch",
                "stage_label": "強勢等拉回",
                "chase_risk": "low",
                "chase_risk_label": "尚未過熱",
                "research_score": 8,
                "research_label": "順風研究",
                "research_factors": [{"label": "散戶結構", "passed": True}],
                "stock_type": "growth_confirmed",
                "stock_type_label": "成長確認型",
                "position_hint": "normal",
                "position_hint_label": "正常部位",
            },
            {
                "signal_date": day0.isoformat(),
                "stock_id": "2344",
                "name": "華邦電",
                "grade": "B",
                "total_score": 70,
                "potential_score": 5,
                "action": "只觀察",
                "reason": "潛力分 5",
                "tags": ["題材升溫:記憶體/HBM"],
                "themes": ["記憶體/HBM"],
                "entry_price": 100.0,
                "stage": "low_base",
                "stage_label": "低位醞釀",
                "chase_risk": "low",
                "chase_risk_label": "尚未過熱",
                "research_score": 5,
                "research_label": "正常篩選",
                "research_factors": [{"label": "產業題材", "passed": True}],
                "stock_type": "cyclical_recovery",
                "stock_type_label": "景氣反轉型",
                "position_hint": "half",
                "position_hint_label": "半部位",
            },
        ],
        day0,
    )

    for index, price in enumerate([101, 102, 103, 104, 108], start=1):
        store.save_daily_score(
            StockScore("2408", 80, "BUY_WATCH", price, 0, 0, 0, 0, 0),
            day0 + timedelta(days=index),
        )
    for index, price in enumerate([99, 98, 97, 96, 94], start=1):
        store.save_daily_score(
            StockScore("2344", 70, "WAIT", price, 0, 0, 0, 0, 0),
            day0 + timedelta(days=index),
        )
    promoted = StockScore("2408", 91, "BUY_WATCH", 102, 0, 0, 0, 0, 0)
    store.save_watch_candidates([promoted], day0 + timedelta(days=2), {"2408": "??蝘?"})

    store.update_potential_forward_returns(day0 + timedelta(days=5))
    summary = store.potential_radar_summary(day0 + timedelta(days=5))
    factors = {row["label"]: row for row in summary["factor_stats"]}

    assert factors["散戶減少/籌碼轉乾淨"]["completed"] == 1
    assert factors["散戶減少/籌碼轉乾淨"]["win_rate_5d"] == 100
    assert factors["題材升溫"]["completed"] == 2
    assert factors["題材升溫"]["success_count"] == 1
    assert factors["題材升溫"]["failure_count"] == 1
    assert factors["順風研究"]["completed"] == 1
    assert factors["成長確認型"]["win_rate_5d"] == 100
    assert summary["items"][0]["stage_label"] in {"強勢等拉回", "低位醞釀"}
    assert summary["items"][0]["research_label"] in {"順風研究", "正常篩選"}
    assert summary["items"][0]["stock_type_label"] in {"成長確認型", "景氣反轉型"}
    assert summary["items"][0]["position_hint_label"] in {"正常部位", "半部位"}
    assert summary["stage_stats"]
    assert summary["promotion_funnel"]["promoted"] == 1
    assert summary["promotion_funnel"]["examples"][0]["stock_id"] == "2408"
    assert summary["promotion_funnel"]["examples"][0]["days_to_promotion"] == 2
    by_stock = {item["stock_id"]: item for item in summary["items"]}
    assert by_stock["2408"]["promotion_label"] == "已轉強"
    assert summary["strong_factors"]
    assert summary["weak_factors"]
    assert summary["factor_notes"]
