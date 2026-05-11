from __future__ import annotations

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
