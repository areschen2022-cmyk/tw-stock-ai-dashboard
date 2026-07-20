from __future__ import annotations

from scripts.claude_review_packet import build_packet


def test_claude_review_packet_contains_review_context(tmp_path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "data" / "theme_universe.d").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()

    for path in [
        ".github/workflows/daily.yml",
        "main.py",
        "src/config_loader.py",
        "scripts/post_optimization_finalize.py",
        "data/theme_universe.yaml",
        "data/theme_universe.d/2026_trends.yaml",
        "dashboard/post_update_check.json",
    ]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("{}", encoding="utf-8")

    packet = build_packet(tmp_path)

    assert "Claude Code 審查包" in packet
    assert str(tmp_path) in packet
    assert "今日監控" in packet
    assert "潛力雷達" in packet
    assert "請 Claude 優先檢查" in packet
    assert "data/theme_universe.yaml" in packet
