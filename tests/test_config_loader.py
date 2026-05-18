from __future__ import annotations

from pathlib import Path

import yaml

from src.config_loader import merge_theme_database


def test_merge_theme_database_adds_stocks_and_keywords(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "theme_universe.yaml").write_text(
        yaml.safe_dump(
            {
                "themes": {
                    "memory": {
                        "name": "記憶體/HBM",
                        "keywords": ["HBM", "DRAM"],
                        "stocks": [
                            {"id": "2408", "name": "南亞科", "tier": "core", "role": "DRAM"},
                            {"id": "2344", "name": "華邦電", "tier": "beneficiary", "role": "DRAM"},
                        ],
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    config = {
        "theme_pools": {"memory": {"name": "Memory", "stocks": {"8299": "群聯"}}},
        "stock_names": {},
        "web_news": {"theme_keywords": {"memory": ["NAND"]}},
    }

    merged = merge_theme_database(config, tmp_path)

    assert merged["theme_pools"]["memory"]["name"] == "記憶體/HBM"
    assert merged["theme_pools"]["memory"]["stocks"]["2408"] == "南亞科"
    assert merged["theme_pools"]["memory"]["stocks"]["8299"] == "群聯"
    assert merged["stock_names"]["2344"] == "華邦電"
    assert merged["web_news"]["theme_keywords"]["memory"] == ["NAND", "HBM", "DRAM"]
    assert merged["theme_stock_meta"]["2408"]["memory"]["tier"] == "core"
    assert merged["theme_stock_meta"]["2408"]["memory"]["tier_label"] == "核心"
    assert merged["theme_stock_meta"]["2408"]["memory"]["role"] == "DRAM"


def test_real_theme_database_includes_satellite_and_passive_components() -> None:
    project_root = Path(__file__).resolve().parents[1]
    merged = merge_theme_database(
        {
            "theme_pools": {},
            "stock_names": {},
            "web_news": {"theme_keywords": {}},
        },
        project_root,
    )

    assert merged["theme_pools"]["low_orbit_satellite"]["name"] == "低軌衛星/SpaceX"
    assert merged["theme_pools"]["low_orbit_satellite"]["stocks"]["3491"] == "昇達科"
    assert merged["theme_pools"]["low_orbit_satellite"]["stocks"]["2313"] == "華通"
    assert "SpaceX" in merged["web_news"]["theme_keywords"]["low_orbit_satellite"]
    assert "Starlink" in merged["web_news"]["theme_keywords"]["low_orbit_satellite"]
    assert merged["theme_stock_meta"]["3491"]["low_orbit_satellite"]["tier"] == "core"

    assert merged["theme_pools"]["passive_components"]["name"] == "被動元件"
    assert merged["theme_pools"]["passive_components"]["stocks"]["2472"] == "立隆電"
    assert merged["theme_pools"]["passive_components"]["stocks"]["8042"] == "金山電"
    assert "國巨" in merged["web_news"]["theme_keywords"]["passive_components"]
    assert "立隆電" in merged["web_news"]["theme_keywords"]["passive_components"]

    assert merged["theme_pools"]["network_optical_communication"]["name"] == "網通光通訊"
    assert merged["theme_pools"]["network_optical_communication"]["stocks"]["2345"] == "智邦"
    assert "網通光通訊" in merged["web_news"]["theme_keywords"]["network_optical_communication"]

    assert merged["theme_pools"]["defense_policy"]["name"] == "防禦與政策"
    assert merged["theme_pools"]["defense_policy"]["stocks"]["2634"] == "漢翔"
    assert "政策受惠" in merged["web_news"]["theme_keywords"]["defense_policy"]
