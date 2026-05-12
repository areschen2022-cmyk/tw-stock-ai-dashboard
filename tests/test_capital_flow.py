from __future__ import annotations

from datetime import date

from src.report.capital_flow import (
    build_telegram_message,
    build_watchlist,
    classify_quadrant,
    summarize_themes,
)
from src.storage.sqlite_store import SQLiteStore


def test_classify_quadrant() -> None:
    assert classify_quadrant(rank_change=100, price_change_pct=2.5) == "主動流入"
    assert classify_quadrant(rank_change=100, price_change_pct=-1.0) == "止跌承接"
    assert classify_quadrant(rank_change=-50, price_change_pct=-2.0) == "主動砍倉"
    assert classify_quadrant(rank_change=-50, price_change_pct=0.5) == "量縮漲"
    assert classify_quadrant(rank_change=0, price_change_pct=0) == "量縮漲"


def test_save_and_load_capital_flow(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    trade_date = date(2026, 5, 11)
    signals = [
        {
            "stock_id": "2408",
            "quadrant": "主動流入",
            "volume_rank": 5,
            "prev_volume_rank": 200,
            "rank_change": 195,
            "price_change_pct": 3.2,
            "volume_value": 150.0,
            "themes": ["記憶體/HBM"],
        },
    ]

    store.save_capital_flow(signals, trade_date)
    loaded = store.latest_capital_flow(trade_date)

    assert len(loaded) == 1
    assert loaded[0]["quadrant"] == "主動流入"
    assert loaded[0]["rank_change"] == 195
    assert loaded[0]["themes"] == ["記憶體/HBM"]


def test_theme_summary_and_watchlist() -> None:
    signals = [
        {
            "stock_id": "2408",
            "name": "南亞科",
            "quadrant": "主動流入",
            "volume_rank": 5,
            "rank_change": 195,
            "price_change_pct": 3.2,
        },
        {
            "stock_id": "2313",
            "name": "華通",
            "quadrant": "止跌承接",
            "volume_rank": 8,
            "rank_change": 120,
            "price_change_pct": -2.1,
        },
    ]

    summary = summarize_themes(signals, {"記憶體/HBM": ["2408"], "PCB/載板": ["2313"]})
    watchlist = build_watchlist(signals, {"2408": "南亞科", "2313": "華通"})

    assert summary[0]["theme"] == "記憶體/HBM"
    assert summary[0]["主動流入"] == 1
    assert watchlist[0]["stock_id"] == "2408"
    assert watchlist[1]["reason"].startswith("量增承接")


def test_build_telegram_message_structure() -> None:
    signals = [
        {"stock_id": f"24{i:02d}", "quadrant": "主動流入"}
        for i in range(5)
    ]
    signals.append({"stock_id": "2344", "quadrant": "主動砍倉"})

    message = build_telegram_message(date(2026, 5, 11), signals, [], [])

    assert "台股收盤資金流向" in message
    assert "主動流入 5" in message
    assert "比值" in message
