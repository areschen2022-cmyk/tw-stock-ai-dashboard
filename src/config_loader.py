from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TIER_LABELS = {
    "core": "核心",
    "beneficiary": "受惠",
    "speculative": "聯想",
}

CHAIN_LAYER_LABELS = {
    "upstream": "上游",
    "midstream": "中游",
    "downstream": "下游",
    "infrastructure": "基礎設施",
    "service": "服務/應用",
    "unknown": "未分類",
}

BENEFICIARY_LABELS = {
    1: "直接受惠",
    2: "二階受惠",
    3: "題材聯想",
}


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve_path(project_root: Path, raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else project_root / path


def _load_theme_chain_map(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    raw_path = (
        config.get("runtime", {}).get("theme_chain_map_path")
        or project_root / "data" / "theme_chain_map.yaml"
    )
    chain_path = _resolve_path(project_root, raw_path)
    if not chain_path.exists():
        return {}
    data = load_yaml(chain_path)
    return data if isinstance(data, dict) else {}


def _match_rule_layer(role: str, role_rules: dict[str, Any]) -> str:
    normalized = role.lower()
    for layer, keywords in role_rules.items():
        for keyword in keywords or []:
            if str(keyword).lower() in normalized:
                return str(layer)
    return ""


def _chain_meta_for_stock(
    *,
    stock_id: str,
    tier: str,
    role: str,
    chain_theme: dict[str, Any],
) -> dict[str, Any]:
    stock_overrides = chain_theme.get("stocks", {}) or {}
    override = stock_overrides.get(stock_id, {}) or {}
    layer = str(override.get("layer") or "").strip()
    if not layer:
        layer = _match_rule_layer(role, chain_theme.get("role_rules", {}) or {})
    if not layer:
        layer = "midstream" if tier in {"core", "beneficiary"} else "unknown"

    order_raw = override.get("beneficiary_order")
    if order_raw is None:
        order_raw = 1 if tier == "core" else 2 if tier == "beneficiary" else 3
    try:
        beneficiary_order = int(order_raw)
    except (TypeError, ValueError):
        beneficiary_order = 3

    return {
        "chain_layer": layer,
        "chain_layer_label": CHAIN_LAYER_LABELS.get(layer, layer),
        "beneficiary_order": beneficiary_order,
        "beneficiary_label": BENEFICIARY_LABELS.get(beneficiary_order, f"{beneficiary_order}階受惠"),
        "chain_role": str(override.get("chain_role") or role or "").strip(),
        "lead_lag": str(override.get("lead_lag") or chain_theme.get("lead_lag") or "").strip(),
    }


def merge_theme_database(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    theme_db_path = Path(
        config.get("runtime", {}).get("theme_database_path")
        or project_root / "data" / "theme_universe.yaml"
    )
    if not theme_db_path.is_absolute():
        theme_db_path = project_root / theme_db_path
    if not theme_db_path.exists():
        return config

    databases = [load_yaml(theme_db_path)]
    supplement_dir = theme_db_path.parent / "theme_universe.d"
    if supplement_dir.exists():
        databases.extend(load_yaml(path) for path in sorted(supplement_dir.glob("*.yaml")))

    theme_pools = config.setdefault("theme_pools", {})
    theme_stock_meta = config.setdefault("theme_stock_meta", {})
    stock_names = config.setdefault("stock_names", {})
    web_news = config.setdefault("web_news", {})
    theme_keywords = web_news.setdefault("theme_keywords", {})
    chain_database = _load_theme_chain_map(config, project_root)
    chain_themes = chain_database.get("themes", {}) if isinstance(chain_database, dict) else {}
    config["theme_chain_map"] = chain_themes

    for database in databases:
        for theme_key, theme_cfg in database.get("themes", {}).items():
            pool = theme_pools.setdefault(theme_key, {})
            pool["name"] = theme_cfg.get("name", pool.get("name", theme_key))
            pool_stocks = pool.setdefault("stocks", {})
            chain_theme = chain_themes.get(theme_key, {}) or {}

            for item in theme_cfg.get("stocks", []):
                stock_id = str(item.get("id", "")).strip()
                name = str(item.get("name", "")).strip()
                if not stock_id:
                    continue
                if name:
                    pool_stocks[stock_id] = name
                    stock_names.setdefault(stock_id, name)
                tier = str(item.get("tier", "beneficiary")).strip() or "beneficiary"
                role = str(item.get("role", "")).strip()
                meta = {
                    "theme_key": theme_key,
                    "theme_name": pool["name"],
                    "tier": tier,
                    "tier_label": TIER_LABELS.get(tier, tier),
                    "role": role,
                }
                meta.update(
                    _chain_meta_for_stock(
                        stock_id=stock_id,
                        tier=tier,
                        role=role,
                        chain_theme=chain_theme,
                    )
                )
                theme_stock_meta.setdefault(stock_id, {})[theme_key] = meta

            keywords = list(theme_keywords.get(theme_key, []))
            for keyword in theme_cfg.get("keywords", []):
                if keyword not in keywords:
                    keywords.append(keyword)
            theme_keywords[theme_key] = keywords

    return config
