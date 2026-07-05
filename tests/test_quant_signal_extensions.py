from __future__ import annotations

from datetime import date

from src.data_provider.tdcc_client import TdccHoldingRow, big_holder_ratios
from src.report.potential_radar import build_potential_radar_candidates
from src.storage.sqlite_store import SQLiteStore


def test_potential_radar_adds_lifecycle_smart_money_and_combo(tmp_path) -> None:
    rows = [
        {
            "stock_id": "1234",
            "name": "測試股",
            "score": 78,
            "grade": "A",
            "price": 50.0,
            "decision_light": "green",
            "technical_score": 24,
            "chip_score": 5,
            "opportunity_score": 9,
            "trigger_summary": "突破整理，量增但法人尚未追",
            "trigger_tags": ["技術突破"],
            "retail_context": "散戶減少，籌碼轉乾淨",
            "pattern_tags": ["紅包孕"],
            "themes": ["測試題材"],
            "entry_decision": "開盤確認",
        }
    ]
    candidates = build_potential_radar_candidates(rows, date(2026, 7, 1))
    assert candidates
    first = candidates[0]
    assert first["lifecycle_stage"] in {"fresh", "maturing", "extended"}
    assert first["smart_money"] in {"lead", "sync", "none"}
    assert first["signal_combo"]
    assert "組合:" in " ".join(first["tags"])

    store = SQLiteStore(tmp_path / "test.sqlite3")
    store.save_potential_radar(candidates, date(2026, 7, 1))
    summary = store.potential_radar_summary(date(2026, 7, 1))
    assert summary["items"][0]["signal_combo"]
    assert "smart_money_stats" in summary
    assert "combo_stats" in summary


def test_tdcc_big_holder_ratios_aggregate_high_levels() -> None:
    rows = [
        TdccHoldingRow(date(2026, 6, 26), "2330", 3, 100, 1000, 0.1),
        TdccHoldingRow(date(2026, 6, 26), "2330", 15, 5, 1000000, 12.5),
        TdccHoldingRow(date(2026, 6, 26), "2330", 16, 2, 900000, 8.0),
        TdccHoldingRow(date(2026, 6, 26), "2317", 15, 1, 500000, None),
    ]
    ratios = big_holder_ratios(rows)
    assert ratios[date(2026, 6, 26)]["2330"] == 20.5
    assert "2317" not in ratios[date(2026, 6, 26)]


def test_weekly_and_block_trade_storage_round_trip(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    store.save_tdcc_holder_metrics(
        [
            {
                "stock_id": "2330",
                "name": "台積電",
                "retail_holders": 1000,
                "retail_holder_change": -50,
                "retail_holder_change_pct": -4.8,
                "big_holder_pct": 42.5,
                "big_holder_change_pct": 1.2,
            }
        ],
        date(2026, 6, 26),
    )
    assert store.latest_tdcc_holder_metrics()[0]["big_holder_pct"] == 42.5

    store.save_block_trade_anomalies(
        [
            {
                "stock_id": "2330",
                "name": "台積電",
                "block_value": 12.3,
                "zscore": 3.1,
                "signal": "鉅額交易異常",
                "source": "manual-test",
                "reason": "成交金額高於近期常態",
            }
        ],
        date(2026, 7, 1),
    )
    assert store.latest_block_trade_anomalies()[0]["signal"] == "鉅額交易異常"
