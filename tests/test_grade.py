from src.scoring.grade import grade_description, grade_label


def test_grade_label_supports_s_tiers() -> None:
    assert grade_label(100) == "S+"
    assert grade_label(95) == "S+"
    assert grade_label(94) == "S"
    assert grade_label(85) == "S"
    assert grade_label(84) == "A"
    assert grade_label(75) == "A"
    assert grade_label(65) == "B"
    assert grade_label(50) == "C"
    assert grade_label(49) == "-"


def test_grade_description_is_human_readable() -> None:
    assert "S+級" in grade_description(95)
    assert "S級" in grade_description(85)
    assert "A級" in grade_description(75)
