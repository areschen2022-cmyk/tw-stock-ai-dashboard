from __future__ import annotations

import json
import sqlite3
from datetime import date
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
                        entry_price, entry_condition, stop_reference, themes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )

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
