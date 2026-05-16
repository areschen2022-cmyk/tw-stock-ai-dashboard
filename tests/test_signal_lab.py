from src.backtest.signal_lab import grade_return_summary


def test_signal_lab_summarizes_grade_forward_returns() -> None:
    summary = grade_return_summary(
        [
            {"grade": "S+", "return_3d": 2, "return_5d": 3, "return_10d": 4},
            {"grade": "S+", "return_3d": -1, "return_5d": 1, "return_10d": None},
            {"grade": "A", "return_3d": 0.5, "return_5d": -2, "return_10d": -1},
        ]
    )
    by_grade = {row["grade"]: row for row in summary}

    assert by_grade["S+"]["signals"] == 2
    assert by_grade["S+"]["win_rate_5d"] == 100
    assert by_grade["A"]["avg_return_10d"] == -1
