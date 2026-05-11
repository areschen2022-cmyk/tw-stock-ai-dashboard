from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from src.scoring.score_engine import StockScore


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_scores (
                    as_of_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    total_score INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    price REAL,
                    technical_score INTEGER NOT NULL,
                    chip_score INTEGER NOT NULL,
                    fundamental_score INTEGER NOT NULL,
                    risk_score INTEGER NOT NULL,
                    market_adjustment INTEGER NOT NULL,
                    overseas_adjustment INTEGER NOT NULL DEFAULT 0,
                    opportunity_score INTEGER NOT NULL DEFAULT 0,
                    reasons_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (as_of_date, stock_id)
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_scores)").fetchall()}
            if "overseas_adjustment" not in columns:
                conn.execute("ALTER TABLE daily_scores ADD COLUMN overseas_adjustment INTEGER NOT NULL DEFAULT 0")
            if "opportunity_score" not in columns:
                conn.execute("ALTER TABLE daily_scores ADD COLUMN opportunity_score INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watch_signals (
                    signal_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    total_score INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entry_price REAL,
                    entry_condition TEXT NOT NULL,
                    stop_reference TEXT NOT NULL,
                    themes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (signal_date, stock_id)
                )
                """
            )
            watch_columns = {row[1] for row in conn.execute("PRAGMA table_info(watch_signals)").fetchall()}
            for column, definition in [
                ("stop_price", "REAL"),
                ("entry_limit_price", "REAL"),
                ("grade", "TEXT"),
                ("price_3d", "REAL"),
                ("price_5d", "REAL"),
                ("return_3d", "REAL"),
                ("return_5d", "REAL"),
                ("stop_hit", "INTEGER"),
                ("entry_triggered", "INTEGER"),
            ]:
                if column not in watch_columns:
                    conn.execute(f"ALTER TABLE watch_signals ADD COLUMN {column} {definition}")

    def save_daily_score(self, score: StockScore, as_of: date) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_scores (
                    as_of_date, stock_id, total_score, label, price,
                    technical_score, chip_score, fundamental_score, risk_score,
                    market_adjustment, overseas_adjustment, opportunity_score, reasons_json, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    as_of.isoformat(),
                    score.stock_id,
                    score.total_score,
                    score.label,
                    score.price,
                    score.technical_score,
                    score.chip_score,
                    score.fundamental_score,
                    score.risk_score,
                    score.market_adjustment,
                    score.overseas_adjustment,
                    score.opportunity_score,
                    json.dumps(score.reasons, ensure_ascii=False),
                    json.dumps(score.warnings, ensure_ascii=False),
                ),
            )

    def latest_score_before(self, stock_id: str, as_of: date) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT as_of_date, total_score, label, price, opportunity_score
                FROM daily_scores
                WHERE stock_id = ? AND as_of_date < ?
                ORDER BY as_of_date DESC
                LIMIT 1
                """,
                (stock_id, as_of.isoformat()),
            ).fetchone()
        if not row:
            return None
        return {
            "as_of_date": row[0],
            "total_score": row[1],
            "label": row[2],
            "price": row[3],
            "opportunity_score": row[4],
        }

    def save_watch_candidates(self, scores: list[StockScore], as_of: date, stock_names: dict[str, str]) -> None:
        candidates = [
            score
            for score in scores
            if score.label == "BUY_WATCH" and score.price is not None
        ]
        with self._connect() as conn:
            conn.execute("DELETE FROM watch_signals WHERE signal_date = ?", (as_of.isoformat(),))
            for score in candidates:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO watch_signals (
                        signal_date, stock_id, name, total_score, label, action,
                        entry_price, entry_condition, stop_reference, themes_json,
                        stop_price, entry_limit_price, grade
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        as_of.isoformat(),
                        score.stock_id,
                        stock_names.get(score.stock_id, "名稱未設定"),
                        score.total_score,
                        score.label,
                        score.action,
                        score.price,
                        score.entry_condition,
                        score.stop_reference,
                        json.dumps(score.themes, ensure_ascii=False),
                        score.stop_price,
                        score.entry_limit_price,
                        _grade(score.total_score),
                    ),
                )

    def update_forward_returns(self, as_of: date) -> None:
        with self._connect() as conn:
            signals = conn.execute(
                """
                SELECT signal_date, stock_id, entry_price, stop_price, entry_limit_price
                FROM watch_signals
                WHERE signal_date < ?
                  AND (return_5d IS NULL OR stop_hit IS NULL OR entry_triggered IS NULL)
                """,
                (as_of.isoformat(),),
            ).fetchall()
            for signal_date, stock_id, entry_price, stop_price, entry_limit_price in signals:
                if entry_price is None:
                    continue
                future_rows = conn.execute(
                    """
                    SELECT as_of_date, price
                    FROM daily_scores
                    WHERE stock_id = ? AND as_of_date > ? AND as_of_date <= ? AND price IS NOT NULL
                    ORDER BY as_of_date
                    """,
                    (stock_id, signal_date, (date.fromisoformat(signal_date) + timedelta(days=14)).isoformat()),
                ).fetchall()
                if not future_rows:
                    continue
                prices = [float(row[1]) for row in future_rows]
                price_3d = prices[2] if len(prices) >= 3 else None
                price_5d = prices[4] if len(prices) >= 5 else None
                return_3d = _pct_return(price_3d, entry_price)
                return_5d = _pct_return(price_5d, entry_price)
                stop_hit = None
                if stop_price is not None:
                    stop_hit = int(any(price <= float(stop_price) for price in prices[:5]))
                entry_triggered = None
                if entry_limit_price is not None and prices:
                    entry_triggered = int(prices[0] <= float(entry_limit_price))
                conn.execute(
                    """
                    UPDATE watch_signals
                    SET price_3d = COALESCE(?, price_3d),
                        price_5d = COALESCE(?, price_5d),
                        return_3d = COALESCE(?, return_3d),
                        return_5d = COALESCE(?, return_5d),
                        stop_hit = COALESCE(?, stop_hit),
                        entry_triggered = COALESCE(?, entry_triggered)
                    WHERE signal_date = ? AND stock_id = ?
                    """,
                    (
                        price_3d,
                        price_5d,
                        return_3d,
                        return_5d,
                        stop_hit,
                        entry_triggered,
                        signal_date,
                        stock_id,
                    ),
                )

    def performance_summary(self, as_of: date, days: int = 30) -> dict:
        since = as_of - timedelta(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signal_date, stock_id, name, grade, total_score, entry_price,
                       entry_triggered, return_3d, return_5d, stop_hit, action, themes_json
                FROM watch_signals
                WHERE signal_date >= ?
                ORDER BY signal_date DESC, total_score DESC
                """,
                (since.isoformat(),),
            ).fetchall()
        items = []
        for row in rows:
            signal_date, stock_id, name, grade, total_score, entry_price, entry_triggered, return_3d, return_5d, stop_hit, action, themes_json = row
            items.append(
                {
                    "signal_date": signal_date,
                    "stock_id": stock_id,
                    "name": name,
                    "grade": grade or _grade(total_score),
                    "total_score": total_score,
                    "entry_price": entry_price,
                    "entry_triggered": _bool_or_none(entry_triggered),
                    "return_3d": return_3d,
                    "return_5d": return_5d,
                    "stop_hit": _bool_or_none(stop_hit),
                    "action": action,
                    "themes": json.loads(themes_json or "[]"),
                    "status": "已完成" if return_5d is not None else "進行中",
                }
            )
        completed = [item for item in items if item["return_5d"] is not None]
        a_completed = [item for item in completed if item["grade"] == "A"]
        stop_known = [item for item in items if item["stop_hit"] is not None]
        return {
            "as_of": as_of.isoformat(),
            "days": days,
            "stats": {
                "signals": len(items),
                "completed": len(completed),
                "win_rate_5d": _rate([item["return_5d"] > 0 for item in completed]),
                "avg_return_5d": _avg([item["return_5d"] for item in completed]),
                "stop_hit_rate": _rate([item["stop_hit"] for item in stop_known]),
                "a_win_rate_5d": _rate([item["return_5d"] > 0 for item in a_completed]),
            },
            "theme_stats": _theme_stats(items),
            "score_bands": _score_band_stats(items),
            "items": items,
        }

    def watch_reviews(self, as_of: date, max_age_days: int = 5) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.signal_date, w.stock_id, w.name, w.total_score, w.entry_price,
                    w.action, w.themes_json, d.price, d.total_score, d.label
                FROM watch_signals w
                JOIN daily_scores d
                  ON d.stock_id = w.stock_id
                 AND d.as_of_date = ?
                WHERE w.signal_date < ?
                  AND julianday(?) - julianday(w.signal_date) <= ?
                  AND w.entry_price IS NOT NULL
                  AND d.price IS NOT NULL
                ORDER BY w.signal_date DESC, w.total_score DESC
                """,
                (as_of.isoformat(), as_of.isoformat(), as_of.isoformat(), max_age_days),
            ).fetchall()
        reviews = []
        for row in rows:
            signal_date, stock_id, name, signal_score, entry_price, action, themes_json, current_price, current_score, current_label = row
            change_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
            reviews.append(
                {
                    "signal_date": signal_date,
                    "stock_id": stock_id,
                    "name": name,
                    "signal_score": signal_score,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "current_score": current_score,
                    "current_label": current_label,
                    "change_pct": change_pct,
                    "action": action,
                    "themes": json.loads(themes_json or "[]"),
                }
            )
        return reviews


def _pct_return(price: float | None, entry: float | None) -> float | None:
    if price is None or not entry:
        return None
    return (float(price) - float(entry)) / float(entry) * 100


def _grade(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "-"


def _bool_or_none(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _avg(values: list[float | None]) -> float | None:
    nums = [float(value) for value in values if value is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _rate(values: list[bool | None]) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(1 for value in known if value) / len(known) * 100


def _bucket_stats(label: str, items: list[dict]) -> dict:
    completed = [item for item in items if item["return_5d"] is not None]
    stop_known = [item for item in items if item["stop_hit"] is not None]
    return {
        "label": label,
        "signals": len(items),
        "completed": len(completed),
        "win_rate_5d": _rate([item["return_5d"] > 0 for item in completed]),
        "avg_return_5d": _avg([item["return_5d"] for item in completed]),
        "stop_hit_rate": _rate([item["stop_hit"] for item in stop_known]),
    }


def _theme_stats(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        for theme in item.get("themes", []) or []:
            buckets.setdefault(theme, []).append(item)
    return [
        _bucket_stats(theme, bucket_items)
        for theme, bucket_items in sorted(buckets.items(), key=lambda entry: (-len(entry[1]), entry[0]))
    ]


def _score_band_stats(items: list[dict]) -> list[dict]:
    bands = [
        ("50-64", 50, 64),
        ("65-74", 65, 74),
        ("75-84", 75, 84),
        ("85-100", 85, 100),
    ]
    result = []
    for label, lower, upper in bands:
        band_items = [
            item
            for item in items
            if lower <= int(item.get("total_score", 0)) <= upper
        ]
        result.append(_bucket_stats(label, band_items))
    return result
