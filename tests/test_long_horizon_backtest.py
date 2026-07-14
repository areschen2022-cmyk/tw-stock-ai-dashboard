from scripts.long_horizon_backtest import _bucket_returns, _coverage_status, _return_stats


def test_return_stats_calculates_monthly_signal_performance():
    items = [
        {"signal_date": "2026-06-01", "return_5d": 5.0},
        {"signal_date": "2026-06-02", "return_5d": -2.0},
        {"signal_date": "2026-06-03", "return_5d": None},
    ]

    stats = _return_stats(items)

    assert stats["signals"] == 3
    assert stats["completed"] == 2
    assert stats["win_rate_5d"] == 50.0
    assert stats["avg_signal_return_5d"] == 1.5
    assert "equal_weight_compound_return_5d" not in stats


def test_bucket_returns_groups_by_signal_month():
    rows = _bucket_returns(
        [
            {"signal_date": "2026-06-01", "return_5d": 2.0},
            {"signal_date": "2026-06-10", "return_5d": -1.0},
            {"signal_date": "2026-07-01", "return_5d": 4.0},
        ],
        7,
    )

    assert rows[0]["period"] == "2026-06"
    assert rows[0]["signals"] == 2
    assert rows[0]["avg_signal_return_5d"] == 0.5
    assert rows[1]["period"] == "2026-07"
    assert rows[1]["win_rate_5d"] == 100.0


def test_coverage_status_marks_short_history_as_partial():
    assert _coverage_status(60, 10958) == "partial_coverage"
    assert _coverage_status(0, 10958) == "no_signal_data"
