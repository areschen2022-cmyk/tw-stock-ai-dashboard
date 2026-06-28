from __future__ import annotations

from scripts.post_optimization_finalize import scan_mojibake


def test_scan_mojibake_detects_corrupt_text(tmp_path) -> None:
    target = tmp_path / "README.md"
    target.write_text("bad ?" + chr(0x5557) + " text\n", encoding="utf-8")

    result = scan_mojibake(tmp_path)

    assert result["ok"] is False
    assert result["hit_count"] == 1
    assert result["hits"][0]["path"] == "README.md"


def test_scan_mojibake_ignores_clean_project_text(tmp_path) -> None:
    target = tmp_path / "README.md"
    target.write_text("台股 AI 每次優化後都要檢查並匯出智慧庫。\n", encoding="utf-8")

    result = scan_mojibake(tmp_path)

    assert result["ok"] is True
    assert result["hit_count"] == 0
