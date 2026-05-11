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
