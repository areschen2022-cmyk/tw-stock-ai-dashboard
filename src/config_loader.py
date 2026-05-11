from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def merge_theme_database(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    theme_db_path = Path(
        config.get("runtime", {}).get("theme_database_path")
        or project_root / "data" / "theme_universe.yaml"
    )
    if not theme_db_path.is_absolute():
        theme_db_path = project_root / theme_db_path
    if not theme_db_path.exists():
        return config

    database = load_yaml(theme_db_path)
    theme_pools = config.setdefault("theme_pools", {})
    stock_names = config.setdefault("stock_names", {})
    web_news = config.setdefault("web_news", {})
    theme_keywords = web_news.setdefault("theme_keywords", {})

    for theme_key, theme_cfg in database.get("themes", {}).items():
        pool = theme_pools.setdefault(theme_key, {})
        pool["name"] = theme_cfg.get("name", pool.get("name", theme_key))
        pool_stocks = pool.setdefault("stocks", {})

        for item in theme_cfg.get("stocks", []):
            stock_id = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip()
            if not stock_id:
                continue
            if name:
                pool_stocks[stock_id] = name
                stock_names.setdefault(stock_id, name)

        keywords = list(theme_keywords.get(theme_key, []))
        for keyword in theme_cfg.get("keywords", []):
            if keyword not in keywords:
                keywords.append(keyword)
        theme_keywords[theme_key] = keywords

    return config
