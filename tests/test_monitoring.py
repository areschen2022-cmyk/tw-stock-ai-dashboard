from __future__ import annotations

from datetime import date, timedelta

from src.report.monitoring import detect_alerts, format_watch_reviews
from src.scoring.score_engine import StockScore
from src.storage.sqlite_store import SQLiteStore


def _score(stock_id: str, score: int, label: str = "BUY_WATCH", price: float = 100.0) -> StockScore:
    return StockScore(
        stock_id=stock_id,
        total_score=score,
        label=label,
        price=price,
        technical_score=20,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=0,
        action="可追",
        entry_condition="測試進場",
        stop_reference="測試停損",
        themes=["測試題材"],
    )


def test_watch_reviews_compare_current_price(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    signal_day = date(2026, 5, 10)
    today = date(2026, 5, 11)

    signal = _score("2408", 80, price=100.0)
    current = _score("2408", 82, price=110.0)
    store.save_daily_score(signal, signal_day)
    store.save_watch_candidates([signal], signal_day, {"2408": "南亞科"})
    store.save_daily_score(current, today)

    reviews = store.watch_reviews(today)

    assert len(reviews) == 1
    assert reviews[0]["stock_id"] == "2408"
    assert reviews[0]["change_pct"] == 10
    assert format_watch_reviews(reviews)[0].startswith("2408 南亞科：+10.0%")


def test_save_watch_candidates_replaces_same_day(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    signal_day = date(2026, 5, 10)

    store.save_daily_score(_score("2408", 80, price=100.0), signal_day)
    store.save_daily_score(_score("2344", 80, price=50.0), signal_day)
    store.save_watch_candidates([_score("2408", 80, price=100.0)], signal_day, {"2408": "南亞科"})
    store.save_watch_candidates([_score("2344", 80, price=50.0)], signal_day, {"2344": "華邦電"})

    with store._connect() as conn:
        rows = conn.execute("SELECT stock_id FROM watch_signals WHERE signal_date = ?", (signal_day.isoformat(),)).fetchall()

    assert rows == [("2344",)]


def test_performance_summary_uses_forward_prices(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    prices = [101.0, 102.0, 106.0, 104.0, 108.0]

    signal = _score("2408", 80, price=100.0)
    signal.stop_price = 95.0
    signal.entry_limit_price = 103.0
    store.save_daily_score(signal, day0)
    store.save_watch_candidates([signal], day0, {"2408": "南亞科"})
    for index, price in enumerate(prices, start=1):
        store.save_daily_score(_score("2408", 82, price=price), day0 + timedelta(days=index))

    store.update_forward_returns(day0 + timedelta(days=5))
    summary = store.performance_summary(day0 + timedelta(days=5))

    assert summary["stats"]["signals"] == 1
    assert summary["stats"]["completed"] == 1
    assert summary["items"][0]["return_3d"] == 6
    assert summary["items"][0]["return_5d"] == 8
    assert summary["items"][0]["entry_triggered"] is True
    assert summary["items"][0]["stop_hit"] is False


def test_detect_alerts_flags_score_jump(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    previous_day = date(2026, 5, 10)
    today = date(2026, 5, 11)
    store.save_daily_score(_score("2408", 55, label="WAIT", price=90.0), previous_day)

    alerts = detect_alerts(
        [_score("2408", 82, price=100.0)],
        today,
        store,
        {"label": "正常"},
        overseas=None,
        theme_signal=None,
    )

    assert any("分數跳升" in alert for alert in alerts)
    assert any("新進買進觀察" in alert for alert in alerts)
