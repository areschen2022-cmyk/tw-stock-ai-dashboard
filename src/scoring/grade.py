from __future__ import annotations


def grade_label(score: int) -> str:
    """Return the dashboard grade for a 0-100 stock score."""
    if score >= 95:
        return "S+"
    if score >= 85:
        return "S"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "-"


def grade_description(score: int) -> str:
    grade = grade_label(score)
    return {
        "S+": "S+級｜最優先觀察",
        "S": "S級｜高強度觀察",
        "A": "A級｜優先觀察",
        "B": "B級｜可觀察",
        "C": "C級｜只追蹤",
        "-": "觀察不足",
    }[grade]
