from __future__ import annotations


def grade_return_summary(items: list[dict]) -> list[dict]:
    """Offline Signal Lab summary for S+/S/A/B forward returns."""
    grades = ["S+", "S", "A", "B"]
    return [_grade_bucket(grade, [item for item in items if item.get("grade") == grade]) for grade in grades]


def _grade_bucket(grade: str, items: list[dict]) -> dict:
    return {
        "grade": grade,
        "signals": len(items),
        "completed_3d": _count_known(items, "return_3d"),
        "completed_5d": _count_known(items, "return_5d"),
        "completed_10d": _count_known(items, "return_10d"),
        "win_rate_3d": _win_rate(items, "return_3d"),
        "win_rate_5d": _win_rate(items, "return_5d"),
        "win_rate_10d": _win_rate(items, "return_10d"),
        "avg_return_3d": _avg_return(items, "return_3d"),
        "avg_return_5d": _avg_return(items, "return_5d"),
        "avg_return_10d": _avg_return(items, "return_10d"),
    }


def _known(items: list[dict], key: str) -> list[float]:
    return [float(item[key]) for item in items if item.get(key) is not None]


def _count_known(items: list[dict], key: str) -> int:
    return len(_known(items, key))


def _avg_return(items: list[dict], key: str) -> float | None:
    values = _known(items, key)
    if not values:
        return None
    return sum(values) / len(values)


def _win_rate(items: list[dict], key: str) -> float | None:
    values = _known(items, key)
    if not values:
        return None
    return sum(1 for value in values if value > 0) / len(values) * 100
