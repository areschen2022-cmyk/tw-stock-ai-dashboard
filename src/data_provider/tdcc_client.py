from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import requests


DEFAULT_TDCC_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"


@dataclass(frozen=True)
class TdccHoldingRow:
    data_date: date
    stock_id: str
    holding_level: int
    holders: int
    shares: int
    ratio_pct: float | None = None


class TdccClient:
    def __init__(self, url: str = DEFAULT_TDCC_URL, timeout: int = 30) -> None:
        self.url = url
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/1.0; research dashboard)",
            "Accept": "text/csv,text/plain,*/*",
        }

    def fetch_holding_rows(self) -> list[TdccHoldingRow]:
        response = requests.get(self.url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        if response.text.lstrip().startswith("<"):
            raise RuntimeError("TDCC returned HTML instead of CSV")
        return parse_tdcc_csv(response.content)


def parse_tdcc_csv(content: bytes | str) -> list[TdccHoldingRow]:
    text = _decode_csv(content)
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        normalized = {_normalize_key(key): value for key, value in raw.items() if key is not None}
        stock_id = _first_value(normalized, "證券代號", "securitiescode", "stockid", "stock_id")
        data_date = _first_value(normalized, "資料日期", "date", "datadate")
        level = _first_value(normalized, "持股分級", "securitiesholdingrange", "holdingrange", "level")
        holders = _first_value(normalized, "人數", "numberofholders", "holders")
        shares = _first_value(normalized, "股數", "numberofsharesunits", "shares")
        ratio = _first_value(normalized, "占集保庫存數比例%", "佔集保庫存數比例%", "percentageofcentrallydepositedsecurities", "ratio")
        if not stock_id or not data_date or not level or not holders:
            continue
        try:
            rows.append(
                TdccHoldingRow(
                    data_date=_parse_date(data_date),
                    stock_id=str(stock_id).strip(),
                    holding_level=int(float(str(level).strip())),
                    holders=_int(holders),
                    shares=_int(shares),
                    ratio_pct=_float_or_none(ratio),
                )
            )
        except (TypeError, ValueError):
            logging.debug("Skip malformed TDCC row: %s", raw)
    return rows


def load_tdcc_csv(path: Path) -> list[TdccHoldingRow]:
    return parse_tdcc_csv(path.read_bytes())


def retail_holder_counts(
    rows: Iterable[TdccHoldingRow],
    *,
    retail_levels: set[int] | None = None,
) -> dict[date, dict[str, int]]:
    levels = retail_levels or {1, 2, 3}
    grouped: dict[date, dict[str, int]] = {}
    for row in rows:
        if row.holding_level not in levels:
            continue
        grouped.setdefault(row.data_date, {})
        grouped[row.data_date][row.stock_id] = grouped[row.data_date].get(row.stock_id, 0) + row.holders
    return grouped


def big_holder_ratios(
    rows: Iterable[TdccHoldingRow],
    *,
    big_holder_levels: set[int] | None = None,
) -> dict[date, dict[str, float]]:
    """Return TDCC large-holder ownership ratio by stock.

    TDCC holding ranges differ slightly by source naming, so callers can override
    the level set. The default uses the high-end levels that normally correspond
    to holders above roughly 1,000 lots.
    """
    levels = big_holder_levels or {15, 16, 17}
    grouped: dict[date, dict[str, float]] = {}
    for row in rows:
        if row.holding_level not in levels or row.ratio_pct is None:
            continue
        grouped.setdefault(row.data_date, {})
        grouped[row.data_date][row.stock_id] = grouped[row.data_date].get(row.stock_id, 0.0) + float(row.ratio_pct)
    return grouped


def _decode_csv(content: bytes | str) -> str:
    if isinstance(content, str):
        return content
    for encoding in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in str(value).strip().lower() if ch.isalnum() or ch in {"證", "券", "代", "號", "資", "料", "日", "期", "持", "股", "分", "級", "人", "數", "占", "佔", "集", "保", "庫", "存", "比", "例"})


def _first_value(row: dict[str, str], *keys: str) -> str | None:
    normalized_keys = [_normalize_key(key) for key in keys]
    for key in normalized_keys:
        if key in row and str(row[key]).strip():
            return row[key]
    return None


def _parse_date(value: str) -> date:
    text = str(value).strip().replace("/", "").replace("-", "")
    if len(text) == 7 and text.isdigit():
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return datetime.fromisoformat(str(value).strip()).date()


def _int(value) -> int:
    return int(float(str(value or "0").replace(",", "").strip() or "0"))


def _float_or_none(value) -> float | None:
    if value is None or str(value).strip() in {"", "-"}:
        return None
    return float(str(value).replace(",", "").replace("%", "").strip())
