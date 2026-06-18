from __future__ import annotations

from pathlib import Path

import yaml

from src.config_loader import merge_theme_database


def test_merge_theme_database_adds_stocks_keywords_and_chain_metadata(tmp_path) -> None:
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
                            {"id": "8299", "name": "群聯", "tier": "beneficiary", "role": "NAND controller"},
                        ],
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (data_dir / "theme_chain_map.yaml").write_text(
        yaml.safe_dump(
            {
                "themes": {
                    "memory": {
                        "stage": "供需循環",
                        "lead_lag": "原廠先行",
                        "role_rules": {
                            "midstream": ["DRAM"],
                            "upstream": ["controller"],
                        },
                        "stocks": {
                            "2408": {"layer": "midstream", "beneficiary_order": 1},
                        },
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    config = {
        "theme_pools": {"memory": {"name": "Memory", "stocks": {"2344": "華邦電"}}},
        "stock_names": {},
        "web_news": {"theme_keywords": {"memory": ["NAND"]}},
    }

    merged = merge_theme_database(config, tmp_path)

    assert merged["theme_pools"]["memory"]["name"] == "記憶體/HBM"
    assert merged["theme_pools"]["memory"]["stocks"]["2408"] == "南亞科"
    assert merged["theme_pools"]["memory"]["stocks"]["2344"] == "華邦電"
    assert merged["stock_names"]["8299"] == "群聯"
    assert merged["web_news"]["theme_keywords"]["memory"] == ["NAND", "HBM", "DRAM"]

    south = merged["theme_stock_meta"]["2408"]["memory"]
    phison = merged["theme_stock_meta"]["8299"]["memory"]
    assert south["tier"] == "core"
    assert south["tier_label"] == "核心"
    assert south["chain_layer"] == "midstream"
    assert south["chain_layer_label"] == "中游"
    assert south["beneficiary_label"] == "直接受惠"
    assert phison["chain_layer"] == "upstream"
    assert phison["beneficiary_label"] == "二階受惠"
    assert merged["theme_chain_map"]["memory"]["stage"] == "供需循環"


def test_real_theme_database_includes_key_themes_and_chain_map() -> None:
    project_root = Path(__file__).resolve().parents[1]
    merged = merge_theme_database(
        {
            "theme_pools": {},
            "stock_names": {},
            "web_news": {"theme_keywords": {}},
        },
        project_root,
    )

    for theme_key in [
        "ai_server",
        "advanced_packaging",
        "memory",
        "low_orbit_satellite",
        "passive_components",
        "quartz_frequency_control",
        "network_optical_communication",
    ]:
        assert theme_key in merged["theme_pools"]
        assert theme_key in merged["theme_chain_map"]
        assert merged["theme_chain_map"][theme_key]["stage"]

    assert "2408" in merged["theme_pools"]["memory"]["stocks"]
    assert "SpaceX" in merged["web_news"]["theme_keywords"]["low_orbit_satellite"]
    assert "MLCC" in merged["web_news"]["theme_keywords"]["passive_components"]
    assert merged["theme_stock_meta"]["2408"]["memory"]["tier_label"] == "核心"
    assert merged["theme_stock_meta"]["2408"]["memory"]["chain_layer_label"] in {"中游", "上游"}
