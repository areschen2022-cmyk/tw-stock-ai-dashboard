from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from main import default_as_of


TAIPEI = ZoneInfo("Asia/Taipei")


def test_default_as_of_uses_previous_friday_on_monday_morning() -> None:
    assert default_as_of(datetime(2026, 5, 18, 8, 8, tzinfo=TAIPEI)).isoformat() == "2026-05-15"


def test_default_as_of_uses_today_after_close() -> None:
    assert default_as_of(datetime(2026, 5, 18, 15, 0, tzinfo=TAIPEI)).isoformat() == "2026-05-18"


def test_default_as_of_uses_friday_on_weekend() -> None:
    assert default_as_of(datetime(2026, 5, 17, 9, 0, tzinfo=TAIPEI)).isoformat() == "2026-05-15"
