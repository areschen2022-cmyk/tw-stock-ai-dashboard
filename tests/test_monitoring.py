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
    assert summary["items"][0]["outcome_category"] == "big_winner"
    assert summary["postmortem"]["counts"][0]["category"] == "big_winner"


def test_performance_summary_records_success_failure_and_missed_lessons(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    winner = _score("2408", 98, price=100.0)
    winner.stop_price = 95.0
    winner.entry_limit_price = 103.0
    stopped = _score("2344", 96, price=100.0)
    stopped.stop_price = 95.0
    stopped.entry_limit_price = 103.0
    missed = _score("2317", 88, price=100.0)
    missed.stop_price = 95.0
    missed.entry_limit_price = 99.0

    for signal in [winner, stopped, missed]:
        store.save_daily_score(signal, day0)
    store.save_watch_candidates(
        [winner, stopped, missed],
        day0,
        {"2408": "Winner", "2344": "Stopped", "2317": "Missed"},
    )

    price_paths = {
        "2408": [101.0, 105.0, 108.0, 110.0, 112.0],
        "2344": [101.0, 96.0, 94.0, 93.0, 92.0],
        "2317": [101.0, 103.0, 106.0, 108.0, 110.0],
    }
    for stock_id, prices in price_paths.items():
        for index, price in enumerate(prices, start=1):
            store.save_daily_score(_score(stock_id, 90, price=price), day0 + timedelta(days=index))

    store.update_forward_returns(day0 + timedelta(days=5))
    summary = store.performance_summary(day0 + timedelta(days=5))
    by_stock = {item["stock_id"]: item for item in summary["items"]}

    assert by_stock["2408"]["outcome_category"] == "big_winner"
    assert by_stock["2344"]["outcome_category"] == "stop_loss"
    assert by_stock["2317"]["outcome_category"] == "missed_opportunity"
    assert summary["postmortem"]["sample"] == 3
    assert summary["postmortem"]["success_cases"][0]["stock_id"] == "2408"
    assert summary["postmortem"]["failure_cases"][0]["stock_id"] == "2344"
    assert summary["postmortem"]["missed_cases"][0]["stock_id"] == "2317"
    assert summary["learning_center"]["success_factors"]
    assert summary["learning_center"]["failure_factors"]
    assert any(row["label"] == "高分失敗" for row in summary["learning_center"]["failure_factors"])


def test_learning_center_lists_potential_candidates(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    candidate = _score("2408", 88, price=100.0)
    candidate.entry_limit_price = 99.0
    candidate.stop_price = 95.0
    store.save_daily_score(candidate, day0)
    store.save_watch_candidates([candidate], day0, {"2408": "Potential"})

    summary = store.performance_summary(day0 + timedelta(days=1))
    potentials = summary["learning_center"]["potential_candidates"]

    assert potentials
    assert potentials[0]["stock_id"] == "2408"
    assert "分數已成形" in potentials[0]["tags"]


def test_potential_radar_records_and_validates_candidates(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    winner = _score("2408", 88, price=100.0)
    loser = _score("2344", 86, price=100.0)
    store.save_daily_score(winner, day0)
    store.save_daily_score(loser, day0)
    store.save_watch_candidates([winner, loser], day0, {"2408": "Winner", "2344": "Loser"})

    initial = store.performance_summary(day0 + timedelta(days=1))
    store.save_potential_radar(initial["learning_center"]["potential_candidates"], day0)

    winner_prices = [101.0, 102.0, 103.0, 104.0, 108.0]
    loser_prices = [99.0, 98.0, 97.0, 96.0, 94.0]
    for index, price in enumerate(winner_prices, start=1):
        store.save_daily_score(_score("2408", 88, price=price), day0 + timedelta(days=index))
    for index, price in enumerate(loser_prices, start=1):
        store.save_daily_score(_score("2344", 86, price=price), day0 + timedelta(days=index))

    store.update_potential_forward_returns(day0 + timedelta(days=5))
    summary = store.potential_radar_summary(day0 + timedelta(days=5))
    by_stock = {item["stock_id"]: item for item in summary["items"]}

    assert summary["stats"]["completed"] == 2
    assert summary["stats"]["big_winner_count"] == 1
    assert summary["stats"]["false_positive_count"] == 1
    assert by_stock["2408"]["outcome_category"] == "potential_big_winner"
    assert by_stock["2344"]["outcome_category"] == "potential_false_positive"
    assert summary["success_cases"][0]["stock_id"] == "2408"
    assert summary["failure_cases"][0]["stock_id"] == "2344"


def test_weekly_institutional_summary_groups_recent_flow(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    as_of = date(2026, 5, 29)
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO institutional_flow
                (trade_date, stock_id, investor, buy_shares, sell_shares, net_shares)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (as_of.isoformat(), "2408", "Foreign", 10000, 1000, 9000),
        )
        conn.execute(
            """
            INSERT INTO institutional_flow
                (trade_date, stock_id, investor, buy_shares, sell_shares, net_shares)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ((as_of - timedelta(days=1)).isoformat(), "2330", "Foreign", 1000, 6000, -5000),
        )

    summary = store.weekly_institutional_summary(as_of, {"2408": "Stock A", "2330": "Stock B"}, days=7)

    assert summary["top_buy"][0]["stock_id"] == "2408"
    assert summary["top_buy"][0]["net_shares"] == 9000
    assert summary["top_sell"][0]["stock_id"] == "2330"
    assert summary["foreign_top_sell"][0]["stock_id"] == "2330"


def test_performance_summary_groups_by_theme_and_score_band(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    signal = _score("2408", 88, price=100.0)
    signal.themes = ["記憶體/HBM", "AI伺服器"]
    signal.stop_price = 95.0
    signal.entry_limit_price = 103.0
    store.save_daily_score(signal, day0)
    store.save_watch_candidates([signal], day0, {"2408": "南亞科"})
    for index, price in enumerate([101.0, 102.0, 103.0, 104.0, 110.0], start=1):
        store.save_daily_score(_score("2408", 88, price=price), day0 + timedelta(days=index))

    store.update_forward_returns(day0 + timedelta(days=5))
    summary = store.performance_summary(day0 + timedelta(days=5))
    theme_stats = {row["label"]: row for row in summary["theme_stats"]}
    score_bands = {row["label"]: row for row in summary["score_bands"]}

    assert theme_stats["記憶體/HBM"]["signals"] == 1
    assert theme_stats["AI伺服器"]["signals"] == 1
    assert theme_stats["記憶體/HBM"]["win_rate_5d"] == 100
    assert score_bands["85-94"]["signals"] == 1
    assert score_bands["85-94"]["avg_return_5d"] == 10
    assert summary["top_themes"][0]["avg_return_5d"] == 10
    assert summary["leaderboard"]["top_5d"][0]["stock_id"] == "2408"
    assert summary["data_quality"]["completion_rate_5d"] == 100
    assert summary["data_quality"]["pending_examples"] == []
    assert summary["data_quality"]["status_counts"]["completed_5d"] == 1
    assert summary["data_quality"]["status_counts"]["data_missing"] == 0
    assert summary["backtest_insights"]["sample"] == 1
    assert summary["backtest_insights"]["best_segments"]
    assert summary["selection_quality"]["best_theme"]["label"] in {"記憶體/HBM", "AI伺服器"}
    assert summary["selection_quality"]["sample_label"] == "樣本不足"


def test_performance_summary_builds_calibration_advice(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    names = {f"24{i:02d}": f"Stock {i}" for i in range(10)}

    signals = []
    for index in range(5):
        signal = _score(f"24{index:02d}", 88, price=100.0)
        signal.themes = ["強題材"]
        signal.stop_price = 95.0
        signal.entry_limit_price = 103.0
        signals.append(signal)
        store.save_daily_score(signal, day0)
        for offset, price in enumerate([101.0, 102.0, 103.0, 104.0, 110.0], start=1):
            store.save_daily_score(_score(signal.stock_id, 88, price=price), day0 + timedelta(days=offset))

    store.save_watch_candidates(signals, day0, names)
    store.update_forward_returns(day0 + timedelta(days=5))
    summary = store.performance_summary(day0 + timedelta(days=5))

    assert summary["selection_quality"]["completed_5d"] == 5
    assert summary["selection_quality"]["best_theme"]["label"] == "強題材"
    assert any(row["priority"] == "加權觀察" and row["label"] == "強題材" for row in summary["calibration_advice"])


def test_performance_summary_entry_analysis(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    triggered = _score("2408", 80, price=100.0)
    triggered.entry_limit_price = 103.0
    triggered.stop_price = 95.0
    not_triggered = _score("2344", 80, price=100.0)
    not_triggered.entry_limit_price = 99.0
    not_triggered.stop_price = 95.0
    store.save_daily_score(triggered, day0)
    store.save_daily_score(not_triggered, day0)
    store.save_watch_candidates(
        [triggered, not_triggered],
        day0,
        {"2408": "Stock A", "2344": "Stock B"},
    )

    triggered_prices = [101.0, 102.0, 103.0, 104.0, 110.0]
    not_triggered_prices = [101.0, 99.0, 96.0, 94.0, 90.0]
    for index, price in enumerate(triggered_prices, start=1):
        store.save_daily_score(_score("2408", 80, price=price), day0 + timedelta(days=index))
    for index, price in enumerate(not_triggered_prices, start=1):
        store.save_daily_score(_score("2344", 80, price=price), day0 + timedelta(days=index))

    store.update_forward_returns(day0 + timedelta(days=5))
    summary = store.performance_summary(day0 + timedelta(days=5))
    entry = summary["entry_analysis"]

    assert entry["triggered"]["count"] == 1
    assert entry["triggered"]["win_rate_5d"] == 100
    assert entry["triggered"]["avg_return_5d"] == 10
    assert entry["not_triggered"]["count"] == 1
    assert entry["not_triggered"]["win_rate_5d"] == 0
    assert entry["not_triggered"]["avg_return_5d"] == -10


def test_forward_returns_complete_when_stop_price_is_missing(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    day0 = date(2026, 5, 1)
    signal = _score("2408", 80, price=100.0)
    signal.stop_price = None
    signal.entry_limit_price = 103.0
    store.save_daily_score(signal, day0)
    store.save_watch_candidates([signal], day0, {"2408": "南亞科"})
    for index, price in enumerate([101.0, 102.0, 103.0, 104.0, 105.0], start=1):
        store.save_daily_score(_score("2408", 80, price=price), day0 + timedelta(days=index))

    store.update_forward_returns(day0 + timedelta(days=5))
    summary = store.performance_summary(day0 + timedelta(days=5))

    assert summary["stats"]["completed"] == 1
    assert summary["items"][0]["return_5d"] == 5
    assert summary["items"][0]["stop_hit"] is None


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
