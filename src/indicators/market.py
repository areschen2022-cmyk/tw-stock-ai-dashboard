from __future__ import annotations

import pandas as pd


# 主要指數名稱對照（MI_INDEX index_name → 中文短標籤）
_INDEX_LABELS: dict[str, str] = {
    "發行量加權股價指數": "加權",
    "半導體類指數": "半導體",
    "電子類指數": "電子",
    "金融保險類指數": "金融",
    "航運類指數": "航運",
    "生技醫療類指數": "生技",
}


def sector_context(sector_df: pd.DataFrame) -> str:
    """Return a compact one-line sector summary, e.g. '加權+1.23%｜半導體+2.45%｜電子+0.87%'.

    Args:
        sector_df: DataFrame returned by ``TwseClient.sector_indices_today()``.
                   Expected columns: ``index_name``, ``change_pct``.

    Returns:
        Formatted string or empty string when data is unavailable.
    """
    if sector_df is None or sector_df.empty:
        return ""
    if "index_name" not in sector_df.columns or "change_pct" not in sector_df.columns:
        return ""
    parts: list[str] = []
    for full_name, short_label in _INDEX_LABELS.items():
        row = sector_df[sector_df["index_name"] == full_name]
        if row.empty:
            continue
        try:
            pct = float(row.iloc[0]["change_pct"])
        except (ValueError, TypeError):
            continue
        sign = "+" if pct >= 0 else ""
        parts.append(f"{short_label}{sign}{pct:.2f}%")
    return "｜".join(parts)


def market_adjustment(prices: pd.DataFrame, ma_short: int = 20, ma_long: int = 60) -> tuple[int, str, str | None]:
    if prices.empty or len(prices) < ma_long:
        return 0, "大盤資料不足", "大盤調整略過：指數資料不足"
    close = prices.sort_values("date")["close"].astype(float)
    latest = close.iloc[-1]
    short = close.rolling(ma_short).mean().iloc[-1]
    long = close.rolling(ma_long).mean().iloc[-1]
    if latest < short and short < long:
        return -10, "偏空：指數跌破 MA20，且 MA20 低於 MA60", None
    if latest < long:
        return -5, "偏弱：指數位於 MA60 下方", None
    return 0, "健康：指數維持在主要均線上方", None
