from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from scripts.limit_move_study import detect_limit_events, summarize_events


def _prices(changes: list[float], base: float = 100.0) -> pd.DataFrame:
    rows = []
    close = base
    start = date(2026, 1, 1)
    for idx, change in enumerate(changes):
        prev = close
        close = prev * (1 + change / 100)
        rows.append(
            {
                "date": (start + timedelta(days=idx)).isoformat(),
                "open": prev,
                "high": max(prev, close) * 1.01,
                "low": min(prev, close) * 0.99,
                "close": close,
                "volume": 1000 if idx < 25 else 4000,
            }
        )
    return pd.DataFrame(rows)


def test_detect_limit_up_event_with_breakout_labels():
    changes = [0.2] * 65 + [10.0] + [1.0] * 10

    events = detect_limit_events("2330", "台積電", ["AI伺服器"], _prices(changes))

    assert len(events) == 1
    assert events[0]["side"] == "limit_up"
    assert "突破整理" in events[0]["labels"]
    assert events[0]["labels"]


def test_detect_limit_down_event_with_distribution_labels():
    changes = [1.1] * 65 + [-10.0] + [-1.0] * 10

    events = detect_limit_events("2330", "台積電", ["AI伺服器"], _prices(changes))

    assert len(events) == 1
    assert events[0]["side"] == "limit_down"
    assert events[0]["labels"]


def test_summarize_events_separates_up_and_down():
    events = [
        {
            "side": "limit_up",
            "labels": ["突破整理"],
            "post_5d_return": 3.0,
            "post_10d_return": 5.0,
            "volume_ratio_20": 2.0,
            "pre_20d_return": 5.0,
            "themes": ["AI伺服器"],
        },
        {
            "side": "limit_down",
            "labels": ["放量倒貨"],
            "post_5d_return": -4.0,
            "post_10d_return": -2.0,
            "volume_ratio_20": 3.0,
            "pre_20d_return": 22.0,
            "themes": ["AI伺服器"],
        },
    ]

    summary = summarize_events(events)

    assert summary["limit_up"]["events"] == 1
    assert summary["limit_down"]["events"] == 1
    assert summary["limit_up"]["common_labels"][0]["label"] == "突破整理"
    assert summary["theme_summary"][0]["theme"] == "AI伺服器"
