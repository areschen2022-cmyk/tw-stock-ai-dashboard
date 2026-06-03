from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.backtest.signal_lab import grade_return_summary
from src.scoring.score_engine import StockScore
from src.scoring.grade import grade_label

TAIPEI = ZoneInfo("Asia/Taipei")


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

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
                ("vol_5min_threshold", "REAL"),
                ("grade", "TEXT"),
                ("price_3d", "REAL"),
                ("price_5d", "REAL"),
                ("price_10d", "REAL"),
                ("return_3d", "REAL"),
                ("return_5d", "REAL"),
                ("return_10d", "REAL"),
                ("stop_hit", "INTEGER"),
                ("entry_triggered", "INTEGER"),
            ]:
                if column not in watch_columns:
                    conn.execute(f"ALTER TABLE watch_signals ADD COLUMN {column} {definition}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capital_flow_signals (
                    trade_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    quadrant TEXT NOT NULL,
                    volume_rank INTEGER,
                    prev_volume_rank INTEGER,
                    rank_change INTEGER,
                    price_change_pct REAL,
                    volume_value REAL,
                    themes_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (trade_date, stock_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS theme_daily_scores (
                    score_date TEXT NOT NULL,
                    theme_key TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    matched_headlines_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (score_date, theme_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS institutional_flow (
                    trade_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    investor TEXT NOT NULL,
                    buy_shares REAL NOT NULL DEFAULT 0,
                    sell_shares REAL NOT NULL DEFAULT 0,
                    net_shares REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (trade_date, stock_id, investor)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_council_reviews (
                    review_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    score INTEGER,
                    grade TEXT,
                    consensus_action TEXT NOT NULL,
                    confidence REAL,
                    model_count INTEGER NOT NULL DEFAULT 0,
                    agreement_count INTEGER NOT NULL DEFAULT 0,
                    pick_agreement_count INTEGER NOT NULL DEFAULT 0,
                    is_ai_pick INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    model_reviews_json TEXT NOT NULL DEFAULT '[]',
                    return_3d REAL,
                    return_5d REAL,
                    return_10d REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (review_date, stock_id)
                )
                """
            )
            ai_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_council_reviews)").fetchall()}
            for column, definition in [
                ("agreement_count", "INTEGER NOT NULL DEFAULT 0"),
                ("pick_agreement_count", "INTEGER NOT NULL DEFAULT 0"),
                ("is_ai_pick", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                if column not in ai_columns:
                    conn.execute(f"ALTER TABLE ai_council_reviews ADD COLUMN {column} {definition}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_log (
                    channel TEXT NOT NULL,
                    delivery_date TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    run_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (channel, delivery_date, message_type)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_retry_queue (
                    dataset TEXT NOT NULL,
                    data_id TEXT NOT NULL,
                    period TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_attempt_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    recovered_at TEXT,
                    PRIMARY KEY (dataset, data_id, period)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retail_holder_signals (
                    week_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    holder_count INTEGER,
                    prev_holder_count INTEGER,
                    holder_change INTEGER,
                    holder_change_pct REAL,
                    price_change_pct REAL,
                    volume REAL,
                    signal TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (week_date, stock_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retail_holder_snapshots (
                    week_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    holder_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (week_date, stock_id)
                )
                """
            )

    def has_delivered_today(self, channel: str, delivery_date: date, message_type: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM delivery_log
                WHERE channel = ? AND delivery_date = ? AND message_type = ?
                LIMIT 1
                """,
                (channel, delivery_date.isoformat(), message_type),
            ).fetchone()
        return row is not None

    def delivery_status(self, channel: str, delivery_date: date, message_type: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT sent_at, run_id
                FROM delivery_log
                WHERE channel = ? AND delivery_date = ? AND message_type = ?
                LIMIT 1
                """,
                (channel, delivery_date.isoformat(), message_type),
            ).fetchone()
        if not row:
            return {
                "channel": channel,
                "delivery_date": delivery_date.isoformat(),
                "message_type": message_type,
                "delivered": False,
                "sent_at": "",
                "run_id": "",
            }
        return {
            "channel": channel,
            "delivery_date": delivery_date.isoformat(),
            "message_type": message_type,
            "delivered": True,
            "sent_at": row[0] or "",
            "run_id": row[1] or "",
        }

    def record_delivery(
        self,
        channel: str,
        delivery_date: date,
        message_type: str,
        run_id: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO delivery_log
                    (channel, delivery_date, message_type, sent_at, run_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    channel,
                    delivery_date.isoformat(),
                    message_type,
                    datetime.now(TAIPEI).isoformat(timespec="seconds"),
                    run_id,
                ),
            )

    def save_retail_holder_signals(self, signals: list[dict], week_date: date) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM retail_holder_signals WHERE week_date = ?", (week_date.isoformat(),))
            for item in signals:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO retail_holder_signals (
                        week_date, stock_id, name, holder_count, prev_holder_count,
                        holder_change, holder_change_pct, price_change_pct, volume,
                        signal, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        week_date.isoformat(),
                        str(item.get("stock_id") or ""),
                        str(item.get("name") or ""),
                        item.get("holder_count"),
                        item.get("prev_holder_count"),
                        item.get("holder_change"),
                        item.get("holder_change_pct"),
                        item.get("price_change_pct"),
                        item.get("volume"),
                        str(item.get("signal") or "中性"),
                        str(item.get("reason") or ""),
                    ),
                )

    def save_retail_holder_snapshot(self, holder_counts: dict[str, int], week_date: date, stock_names: dict[str, str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM retail_holder_snapshots WHERE week_date = ?", (week_date.isoformat(),))
            for stock_id, holder_count in holder_counts.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO retail_holder_snapshots
                        (week_date, stock_id, name, holder_count)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        week_date.isoformat(),
                        str(stock_id),
                        stock_names.get(str(stock_id), ""),
                        int(holder_count),
                    ),
                )

    def retail_holder_snapshot_before(self, week_date: date) -> tuple[date, dict[str, int]] | tuple[None, dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(week_date)
                FROM retail_holder_snapshots
                WHERE week_date < ?
                """,
                (week_date.isoformat(),),
            ).fetchone()
            if not row or not row[0]:
                return None, {}
            selected_date = date.fromisoformat(row[0])
            rows = conn.execute(
                """
                SELECT stock_id, holder_count
                FROM retail_holder_snapshots
                WHERE week_date = ?
                """,
                (selected_date.isoformat(),),
            ).fetchall()
        return selected_date, {row[0]: int(row[1]) for row in rows}

    def latest_retail_holder_signals(self, week_date: date | None = None, limit: int = 30) -> list[dict]:
        with self._connect() as conn:
            selected_date = week_date.isoformat() if week_date else None
            if selected_date is None:
                row = conn.execute("SELECT MAX(week_date) FROM retail_holder_signals").fetchone()
                selected_date = row[0] if row and row[0] else None
            if selected_date is None:
                return []
            rows = conn.execute(
                """
                SELECT week_date, stock_id, name, holder_count, prev_holder_count,
                       holder_change, holder_change_pct, price_change_pct, volume,
                       signal, reason
                FROM retail_holder_signals
                WHERE week_date = ?
                ORDER BY
                    CASE signal
                        WHEN '籌碼轉乾淨' THEN 0
                        WHEN '散戶過熱' THEN 1
                        WHEN '觀察-籌碼轉乾淨' THEN 2
                        WHEN '觀察-散戶過熱' THEN 3
                        ELSE 4
                    END,
                    ABS(COALESCE(holder_change_pct, 0)) DESC,
                    COALESCE(volume, 0) DESC
                LIMIT ?
                """,
                (selected_date, limit),
            ).fetchall()
        return [
            {
                "week_date": row[0],
                "stock_id": row[1],
                "name": row[2],
                "holder_count": row[3],
                "prev_holder_count": row[4],
                "holder_change": row[5],
                "holder_change_pct": row[6],
                "price_change_pct": row[7],
                "volume": row[8],
                "signal": row[9],
                "reason": row[10],
            }
            for row in rows
        ]

    def enqueue_data_retry(self, details: list[dict]) -> int:
        retryable_types = {"empty", "error"}
        queued = 0
        now = datetime.now(TAIPEI).isoformat(timespec="seconds")
        with self._connect() as conn:
            for item in details:
                reason = str(item.get("reason") or "")
                if item.get("type") not in retryable_types or "quota" in reason.lower():
                    continue
                dataset = str(item.get("dataset") or "").strip()
                data_id = str(item.get("data_id") or "").strip()
                period = str(item.get("period") or "").strip()
                if not dataset or not data_id or data_id == "-":
                    continue
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO data_retry_queue
                        (dataset, data_id, period, reason, status, first_seen_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                    """,
                    (dataset, data_id, period, reason, now),
                )
                queued += cursor.rowcount
                conn.execute(
                    """
                    UPDATE data_retry_queue
                    SET reason = ?,
                        status = CASE WHEN status = 'recovered' THEN status ELSE 'pending' END
                    WHERE dataset = ? AND data_id = ? AND period = ?
                    """,
                    (reason, dataset, data_id, period),
                )
        return queued

    def pending_data_retries(self, limit: int = 8) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT dataset, data_id, period, reason, status, attempts, first_seen_at,
                       last_attempt_at, last_error, recovered_at
                FROM data_retry_queue
                WHERE status IN ('pending', 'failed')
                  AND attempts < 3
                ORDER BY attempts ASC, first_seen_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_retry_row(row) for row in rows]

    def record_retry_attempt(
        self,
        dataset: str,
        data_id: str,
        period: str,
        *,
        ok: bool,
        last_error: str = "",
    ) -> None:
        now = datetime.now(TAIPEI).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE data_retry_queue
                SET attempts = attempts + 1,
                    last_attempt_at = ?,
                    last_error = ?,
                    status = CASE
                        WHEN ? THEN 'recovered'
                        WHEN attempts + 1 >= 3 THEN 'failed'
                        ELSE 'pending'
                    END,
                    recovered_at = CASE WHEN ? THEN ? ELSE recovered_at END
                WHERE dataset = ? AND data_id = ? AND period = ?
                """,
                (now, last_error[:300], int(ok), int(ok), now, dataset, data_id, period),
            )

    def retry_queue_summary(self, limit: int = 8) -> dict:
        with self._connect() as conn:
            counts = {
                row[0]: row[1]
                for row in conn.execute(
                    """
                    SELECT status, COUNT(*)
                    FROM data_retry_queue
                    GROUP BY status
                    """
                ).fetchall()
            }
            rows = conn.execute(
                """
                SELECT dataset, data_id, period, reason, status, attempts, first_seen_at,
                       last_attempt_at, last_error, recovered_at
                FROM data_retry_queue
                ORDER BY COALESCE(last_attempt_at, first_seen_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {
            "status_counts": counts,
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
            "recovered": counts.get("recovered", 0),
            "items": [_retry_row(row) for row in rows],
        }

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
                        stop_price, entry_limit_price, vol_5min_threshold, grade
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        score.vol_5min_threshold,
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
                  AND return_5d IS NULL
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
                    (stock_id, signal_date, (date.fromisoformat(signal_date) + timedelta(days=21)).isoformat()),
                ).fetchall()
                if not future_rows:
                    continue
                prices = [float(row[1]) for row in future_rows]
                price_3d = prices[2] if len(prices) >= 3 else None
                price_5d = prices[4] if len(prices) >= 5 else None
                price_10d = prices[9] if len(prices) >= 10 else None
                return_3d = _pct_return(price_3d, entry_price)
                return_5d = _pct_return(price_5d, entry_price)
                return_10d = _pct_return(price_10d, entry_price)
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
                        price_10d = COALESCE(?, price_10d),
                        return_3d = COALESCE(?, return_3d),
                        return_5d = COALESCE(?, return_5d),
                        return_10d = COALESCE(?, return_10d),
                        stop_hit = COALESCE(?, stop_hit),
                        entry_triggered = COALESCE(?, entry_triggered)
                    WHERE signal_date = ? AND stock_id = ?
                    """,
                    (
                        price_3d,
                        price_5d,
                        price_10d,
                        return_3d,
                        return_5d,
                        return_10d,
                        stop_hit,
                        entry_triggered,
                        signal_date,
                        stock_id,
                    ),
                )
            self._update_ai_forward_returns(conn, as_of)

    def _update_ai_forward_returns(self, conn: sqlite3.Connection, as_of: date) -> None:
        rows = conn.execute(
            """
            SELECT review_date, stock_id
            FROM ai_council_reviews
            WHERE review_date < ?
              AND return_5d IS NULL
            """,
            (as_of.isoformat(),),
        ).fetchall()
        for review_date, stock_id in rows:
            base = conn.execute(
                """
                SELECT price FROM daily_scores
                WHERE as_of_date = ? AND stock_id = ? AND price IS NOT NULL
                """,
                (review_date, stock_id),
            ).fetchone()
            if not base:
                continue
            future_rows = conn.execute(
                """
                SELECT as_of_date, price
                FROM daily_scores
                WHERE stock_id = ? AND as_of_date > ? AND as_of_date <= ? AND price IS NOT NULL
                ORDER BY as_of_date
                """,
                (stock_id, review_date, (date.fromisoformat(review_date) + timedelta(days=21)).isoformat()),
            ).fetchall()
            if not future_rows:
                continue
            prices = [float(row[1]) for row in future_rows]
            entry_price = float(base[0])
            conn.execute(
                """
                UPDATE ai_council_reviews
                SET return_3d = COALESCE(?, return_3d),
                    return_5d = COALESCE(?, return_5d),
                    return_10d = COALESCE(?, return_10d)
                WHERE review_date = ? AND stock_id = ?
                """,
                (
                    _pct_return(prices[2] if len(prices) >= 3 else None, entry_price),
                    _pct_return(prices[4] if len(prices) >= 5 else None, entry_price),
                    _pct_return(prices[9] if len(prices) >= 10 else None, entry_price),
                    review_date,
                    stock_id,
                ),
            )

    def save_ai_council_reviews(self, reviews: list[dict], as_of: date) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM ai_council_reviews WHERE review_date = ?", (as_of.isoformat(),))
            if not reviews:
                return
            for review in reviews:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ai_council_reviews (
                        review_date, stock_id, name, score, grade, consensus_action,
                        confidence, model_count, agreement_count, pick_agreement_count,
                        is_ai_pick, reason, model_reviews_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        as_of.isoformat(),
                        review["stock_id"],
                        review.get("name", review["stock_id"]),
                        review.get("score"),
                        review.get("grade"),
                        review.get("consensus_action", "只觀察"),
                        review.get("confidence"),
                        review.get("model_count", 0),
                        review.get("agreement_count", 0),
                        review.get("pick_agreement_count", 0),
                        int(bool(review.get("is_ai_pick", False))),
                        review.get("reason", ""),
                        json.dumps(review.get("model_reviews", []), ensure_ascii=False),
                    ),
                )

    def watch_candidates_today(self, as_of: date) -> list[dict]:
        """Return today's watch candidates (grade S+/S/A/B) for intraday confirmation."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stock_id, name, total_score, grade, action,
                       entry_price, entry_limit_price, stop_price, vol_5min_threshold,
                       entry_condition, stop_reference
                FROM watch_signals
                WHERE signal_date = ?
                  AND grade IN ('S+', 'S', 'A', 'B')
                ORDER BY total_score DESC
                """,
                (as_of.isoformat(),),
            ).fetchall()
        return [
            {
                "stock_id": row[0],
                "name": row[1],
                "total_score": row[2],
                "grade": row[3],
                "action": row[4],
                "prev_close": row[5],   # entry_price stored as yesterday's close
                "entry_limit_price": row[6],
                "stop_price": row[7],
                "vol_5min_threshold": row[8],
                "entry_condition": row[9],
                "stop_reference": row[10],
            }
            for row in rows
        ]

    def performance_summary(self, as_of: date, days: int = 30) -> dict:
        since = as_of - timedelta(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signal_date, stock_id, name, grade, total_score, entry_price,
                       entry_triggered, return_3d, return_5d, return_10d, stop_hit, action, themes_json
                FROM watch_signals
                WHERE signal_date >= ?
                ORDER BY signal_date DESC, total_score DESC
                """,
                (since.isoformat(),),
            ).fetchall()
        items = []
        for row in rows:
            signal_date, stock_id, name, grade, total_score, entry_price, entry_triggered, return_3d, return_5d, return_10d, stop_hit, action, themes_json = row
            status_code = _return_status_code(signal_date, return_5d, as_of, horizon_days=5)
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
                    "return_10d": return_10d,
                    "stop_hit": _bool_or_none(stop_hit),
                    "action": action,
                    "themes": json.loads(themes_json or "[]"),
                    "status_code": status_code,
                    "status_label": {
                        "completed_5d": "completed",
                        "pending_5d": "pending",
                        "data_missing": "data_missing",
                    }[status_code],
                    "status": "已完成" if return_5d is not None else "進行中",
                }
            )
        for item in items:
            item.update(_postmortem_item(item))
        completed = [item for item in items if item["return_5d"] is not None]
        a_completed = [item for item in completed if item["grade"] == "A"]
        stop_known = [item for item in items if item["stop_hit"] is not None]
        theme_stats = _theme_stats(items)
        action_stats = _action_stats(items)
        score_bands = _score_band_stats(items)
        ai_council = self.ai_council_summary(as_of, days=days)
        backtest_insights = _backtest_insights(items)
        return {
            "as_of": as_of.isoformat(),
            "days": days,
            "stats": {
                "signals": len(items),
                "completed": len(completed),
                "win_rate_5d": _rate([item["return_5d"] > 0 for item in completed]),
                "avg_return_5d": _avg([item["return_5d"] for item in completed]),
                "avg_return_10d": _avg([item["return_10d"] for item in items if item["return_10d"] is not None]),
                "stop_hit_rate": _rate([item["stop_hit"] for item in stop_known]),
                "a_win_rate_5d": _rate([item["return_5d"] > 0 for item in a_completed]),
            },
            "theme_stats": theme_stats,
            "top_themes": _top_buckets(theme_stats, min_completed=1, limit=5),
            "action_stats": action_stats,
            "leaderboard": _leaderboard(items, limit=8),
            "data_quality": _performance_data_quality(items),
            "score_bands": score_bands,
            "entry_analysis": _entry_analysis(items),
            "signal_lab": grade_return_summary(items),
            "postmortem": _postmortem_summary(items),
            "backtest_insights": backtest_insights,
            "ai_council": ai_council,
            "selection_quality": _selection_quality_overview(
                items,
                theme_stats=theme_stats,
                action_stats=action_stats,
                score_bands=score_bands,
                ai_council=ai_council,
            ),
            "calibration_advice": _calibration_advice(
                grade_return_summary(items),
                action_stats,
                theme_stats,
            ),
            "items": items,
        }

    def ai_council_summary(self, as_of: date, days: int = 30) -> dict:
        since = as_of - timedelta(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT review_date, stock_id, name, score, grade, consensus_action,
                       confidence, model_count, agreement_count, pick_agreement_count,
                       is_ai_pick, reason, return_3d, return_5d, return_10d
                FROM ai_council_reviews
                WHERE review_date >= ?
                ORDER BY review_date DESC, score DESC
                """,
                (since.isoformat(),),
            ).fetchall()
        items = [
            {
                "review_date": row[0],
                "stock_id": row[1],
                "name": row[2],
                "score": row[3],
                "grade": row[4],
                "consensus_action": row[5],
                "confidence": row[6],
                "model_count": row[7],
                "agreement_count": row[8],
                "pick_agreement_count": row[9],
                "is_ai_pick": _bool_or_none(row[10]),
                "reason": row[11],
                "return_3d": row[12],
                "return_5d": row[13],
                "return_10d": row[14],
                "status": "已完成" if row[13] is not None else "進行中",
            }
            for row in rows
        ]
        by_action = []
        for action in ["可追", "等拉回", "只觀察", "避免"]:
            bucket = [item for item in items if item["consensus_action"] == action]
            completed = [item for item in bucket if item["return_5d"] is not None]
            by_action.append(
                {
                    "action": action,
                    "signals": len(bucket),
                    "completed": len(completed),
                    "win_rate_5d": _rate([item["return_5d"] > 0 for item in completed]),
                    "avg_return_5d": _avg([item["return_5d"] for item in completed]),
                    "avg_return_10d": _avg([item["return_10d"] for item in bucket if item["return_10d"] is not None]),
                }
            )
        completed_all = [item for item in items if item["return_5d"] is not None]
        return {
            "items": items,
            "by_action": by_action,
            "stats": {
                "signals": len(items),
                "completed": len(completed_all),
                "win_rate_5d": _rate([item["return_5d"] > 0 for item in completed_all]),
                "avg_return_5d": _avg([item["return_5d"] for item in completed_all]),
            },
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

    def save_capital_flow(self, signals: list[dict], trade_date: date) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM capital_flow_signals WHERE trade_date = ?", (trade_date.isoformat(),))
            for signal in signals:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO capital_flow_signals (
                        trade_date, stock_id, quadrant, volume_rank, prev_volume_rank,
                        rank_change, price_change_pct, volume_value, themes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade_date.isoformat(),
                        signal["stock_id"],
                        signal["quadrant"],
                        signal.get("volume_rank"),
                        signal.get("prev_volume_rank"),
                        signal.get("rank_change"),
                        signal.get("price_change_pct"),
                        signal.get("volume_value"),
                        json.dumps(signal.get("themes", []), ensure_ascii=False),
                    ),
                )

    def save_institutional_flow(self, stock_id: str, institutional_rows) -> None:
        """Persist daily institutional buy/sell rows for later continuity analysis."""
        if institutional_rows is None or institutional_rows.empty:
            return
        required = {"date", "name"}
        if not required.issubset(set(institutional_rows.columns)):
            return
        with self._connect() as conn:
            for _, row in institutional_rows.iterrows():
                trade_date = str(row.get("date", ""))[:10]
                investor = str(row.get("name", "") or "unknown")
                if not trade_date or not investor:
                    continue
                buy = _number(row.get("buy"))
                sell = _number(row.get("sell"))
                net = _number(row.get("net"))
                if net == 0 and (buy or sell):
                    net = buy - sell
                conn.execute(
                    """
                    INSERT OR REPLACE INTO institutional_flow
                        (trade_date, stock_id, investor, buy_shares, sell_shares, net_shares)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (trade_date, stock_id, investor, buy, sell, net),
                )

    def save_theme_signal_scores(
        self,
        scores: dict[str, int],
        matched_headlines: dict[str, list[str]],
        as_of: date,
    ) -> None:
        """Persist today's per-theme news scores and matched headlines."""
        with self._connect() as conn:
            for theme_key, score in scores.items():
                headlines = matched_headlines.get(theme_key, [])
                conn.execute(
                    """
                    INSERT OR REPLACE INTO theme_daily_scores
                        (score_date, theme_key, score, matched_headlines_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        as_of.isoformat(),
                        theme_key,
                        score,
                        json.dumps(headlines[:10], ensure_ascii=False),
                    ),
                )

    def theme_momentum(self, as_of: date, lookback_days: int = 7) -> dict[str, dict]:
        """Return momentum stats per theme over the last *lookback_days* days.

        Returns::

            {
              "ai_server": {
                  "today": 4,
                  "avg_3d": 2.3,
                  "history": [4, 3, 2, 1, 0, 0, 1],   # newest-first, up to lookback_days
                  "headlines": ["...", "..."],           # today's matched headlines
              },
              ...
            }
        """
        since = (as_of - timedelta(days=lookback_days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT theme_key, score_date, score, matched_headlines_json
                FROM theme_daily_scores
                WHERE score_date >= ?
                ORDER BY theme_key, score_date DESC
                """,
                (since,),
            ).fetchall()

        by_theme: dict[str, list[tuple[str, int, str]]] = {}
        for theme_key, score_date, score, headlines_json in rows:
            by_theme.setdefault(theme_key, []).append((score_date, score, headlines_json))

        result: dict[str, dict] = {}
        today_str = as_of.isoformat()
        for theme_key, entries in by_theme.items():
            # entries already sorted newest-first
            today_score = 0
            today_headlines: list[str] = []
            history: list[int] = []
            for score_date, score, hl_json in entries:
                if score_date == today_str:
                    today_score = score
                    today_headlines = json.loads(hl_json or "[]")
                else:
                    history.append(score)

            prev3 = history[:3]
            avg_3d = sum(prev3) / len(prev3) if prev3 else 0.0
            result[theme_key] = {
                "today": today_score,
                "avg_3d": round(avg_3d, 1),
                "history": [today_score, *history],
                "headlines": today_headlines,
            }
        return result

    def theme_history(self, theme_key: str, days: int = 30) -> list[dict]:
        """Return daily score history for a single theme (for debugging / dashboard)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT score_date, score, matched_headlines_json
                FROM theme_daily_scores
                WHERE theme_key = ?
                ORDER BY score_date DESC
                LIMIT ?
                """,
                (theme_key, days),
            ).fetchall()
        return [
            {
                "date": row[0],
                "score": row[1],
                "headlines": json.loads(row[2] or "[]"),
            }
            for row in rows
        ]

    def all_theme_history(self, theme_keys: list[str], days: int = 30) -> dict[str, list[dict]]:
        return {theme_key: self.theme_history(theme_key, days=days) for theme_key in theme_keys}

    def weekly_institutional_summary(
        self,
        as_of: date,
        stock_names: dict[str, str],
        days: int = 7,
        limit: int = 10,
    ) -> dict:
        """Aggregate recent institutional flows for the weekly overview page."""
        since = (as_of - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stock_id, SUM(net_shares) AS net
                FROM institutional_flow
                WHERE trade_date >= ? AND trade_date <= ?
                GROUP BY stock_id
                HAVING net IS NOT NULL
                ORDER BY net DESC
                """,
                (since, as_of.isoformat()),
            ).fetchall()
            foreign_rows = conn.execute(
                """
                SELECT stock_id, SUM(net_shares) AS net
                FROM institutional_flow
                WHERE trade_date >= ? AND trade_date <= ?
                  AND (investor LIKE '%Foreign%' OR investor LIKE '%外資%')
                GROUP BY stock_id
                HAVING net IS NOT NULL
                ORDER BY net DESC
                """,
                (since, as_of.isoformat()),
            ).fetchall()

        def _items(source_rows: list[tuple], reverse: bool = False) -> list[dict]:
            selected = sorted(source_rows, key=lambda row: float(row[1] or 0), reverse=not reverse)[:limit]
            return [
                {
                    "stock_id": str(row[0]),
                    "name": stock_names.get(str(row[0]), ""),
                    "net_shares": float(row[1] or 0),
                }
                for row in selected
            ]

        return {
            "since": since,
            "as_of": as_of.isoformat(),
            "days": days,
            "top_buy": _items(rows),
            "top_sell": _items(rows, reverse=True),
            "foreign_top_buy": _items(foreign_rows),
            "foreign_top_sell": _items(foreign_rows, reverse=True),
        }

    def latest_capital_flow(self, trade_date: date) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stock_id, quadrant, volume_rank, prev_volume_rank,
                       rank_change, price_change_pct, volume_value, themes_json
                FROM capital_flow_signals
                WHERE trade_date = ?
                ORDER BY volume_rank
                """,
                (trade_date.isoformat(),),
            ).fetchall()
        return [
            {
                "stock_id": row[0],
                "quadrant": row[1],
                "volume_rank": row[2],
                "prev_volume_rank": row[3],
                "rank_change": row[4],
                "price_change_pct": row[5],
                "volume_value": row[6],
                "themes": json.loads(row[7] or "[]"),
            }
            for row in rows
        ]


def _pct_return(price: float | None, entry: float | None) -> float | None:
    if price is None or not entry:
        return None
    return (float(price) - float(entry)) / float(entry) * 100


def _number(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _grade(score: int) -> str:
    return grade_label(score)


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
        "avg_return_10d": _avg([item["return_10d"] for item in items if item.get("return_10d") is not None]),
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


def _action_stats(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        label = str(item.get("action") or "未分類")
        buckets.setdefault(label, []).append(item)
    return [
        _bucket_stats(action, bucket_items)
        for action, bucket_items in sorted(buckets.items(), key=lambda entry: (-len(entry[1]), entry[0]))
    ]


def _top_buckets(buckets: list[dict], min_completed: int = 1, limit: int = 5) -> list[dict]:
    eligible = [bucket for bucket in buckets if int(bucket.get("completed") or 0) >= min_completed]
    eligible.sort(
        key=lambda bucket: (
            float(bucket.get("avg_return_5d") if bucket.get("avg_return_5d") is not None else -999),
            float(bucket.get("win_rate_5d") if bucket.get("win_rate_5d") is not None else -999),
            int(bucket.get("completed") or 0),
        ),
        reverse=True,
    )
    return eligible[:limit]


def _leaderboard(items: list[dict], limit: int = 8) -> dict:
    completed_5d = [item for item in items if item.get("return_5d") is not None]
    completed_3d = [item for item in items if item.get("return_3d") is not None]

    def _rank(source: list[dict], key: str, reverse: bool) -> list[dict]:
        ranked = sorted(source, key=lambda item: float(item.get(key) or 0), reverse=reverse)[:limit]
        return [
            {
                "signal_date": item.get("signal_date"),
                "stock_id": item.get("stock_id"),
                "name": item.get("name"),
                "grade": item.get("grade"),
                "total_score": item.get("total_score"),
                "action": item.get("action"),
                "themes": item.get("themes", []),
                "return_3d": item.get("return_3d"),
                "return_5d": item.get("return_5d"),
                "return_10d": item.get("return_10d"),
                "stop_hit": item.get("stop_hit"),
            }
            for item in ranked
        ]

    return {
        "top_5d": _rank(completed_5d, "return_5d", True),
        "bottom_5d": _rank(completed_5d, "return_5d", False),
        "top_3d": _rank(completed_3d, "return_3d", True),
    }


def _postmortem_item(item: dict) -> dict:
    return_5d = item.get("return_5d")
    return_10d = item.get("return_10d")
    stop_hit = item.get("stop_hit")
    entry_triggered = item.get("entry_triggered")
    themes = item.get("themes") or []
    grade = str(item.get("grade") or "")
    score = int(item.get("total_score") or 0)

    if return_5d is None:
        return {
            "outcome_category": "pending",
            "outcome_label": "等待驗證",
            "outcome_reason": "尚未滿 5 個交易日，暫不判定成功或失敗。",
            "lesson_tags": ["等待驗證"],
        }

    ret5 = float(return_5d)
    ret10 = float(return_10d) if return_10d is not None else None
    tags: list[str] = []
    if grade in {"S+", "S"}:
        tags.append("高分訊號")
    if entry_triggered is True:
        tags.append("進場觸發")
    elif entry_triggered is False:
        tags.append("進場未觸發")
    if stop_hit is True:
        tags.append("跌破停損")
    if themes:
        tags.extend([f"題材:{theme}" for theme in themes[:2]])

    if stop_hit is True:
        category = "stop_loss"
        label = "失敗：跌破停損"
        reason = "訊號後觸及停損，代表進場位置或風險條件需要檢討。"
    elif entry_triggered is False and ret5 > 0:
        category = "missed_opportunity"
        label = "錯過機會"
        reason = "股價後續上漲但未觸發進場條件，代表進場條件可能太嚴格。"
    elif entry_triggered is False and ret5 <= 0:
        category = "filtered_risk"
        label = "成功過濾"
        reason = "未觸發進場且後續表現不佳，代表進場條件有幫助。"
    elif ret5 >= 8 or (ret10 is not None and ret10 >= 12):
        category = "big_winner"
        label = "飆股命中"
        reason = "訊號後短期報酬明顯放大，應保留當時的題材、籌碼與技術條件。"
    elif ret5 > 0:
        category = "true_positive"
        label = "成功：方向正確"
        reason = "訊號後 5 日報酬為正，條件有效但未達飆股門檻。"
    else:
        category = "false_positive"
        label = "失敗：假訊號"
        reason = "訊號後 5 日報酬為負，需要檢查是否追高、題材退潮或籌碼轉弱。"

    if score >= 95 and category in {"false_positive", "stop_loss"}:
        tags.append("高分失敗")
    if score >= 95 and category in {"big_winner", "true_positive"}:
        tags.append("高分成功")
    if category == "big_winner":
        tags.append("飆股樣本")
    if category in {"false_positive", "stop_loss"}:
        tags.append("失敗樣本")

    return {
        "outcome_category": category,
        "outcome_label": label,
        "outcome_reason": reason,
        "lesson_tags": tags[:8],
    }


def _postmortem_summary(items: list[dict], limit: int = 8) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    categories = [
        ("big_winner", "飆股命中"),
        ("true_positive", "方向正確"),
        ("false_positive", "假訊號"),
        ("stop_loss", "跌破停損"),
        ("missed_opportunity", "錯過機會"),
        ("filtered_risk", "成功過濾"),
        ("pending", "等待驗證"),
    ]
    counts = []
    for key, label in categories:
        bucket = [item for item in items if item.get("outcome_category") == key]
        completed_bucket = [item for item in bucket if item.get("return_5d") is not None]
        counts.append(
            {
                "category": key,
                "label": label,
                "count": len(bucket),
                "completed": len(completed_bucket),
                "avg_return_5d": _avg([item.get("return_5d") for item in completed_bucket]),
                "avg_return_10d": _avg([item.get("return_10d") for item in completed_bucket]),
            }
        )

    def _rank(source: list[dict], reverse: bool) -> list[dict]:
        ranked = sorted(source, key=lambda item: float(item.get("return_5d") or 0), reverse=reverse)[:limit]
        return [
            {
                "signal_date": item.get("signal_date"),
                "stock_id": item.get("stock_id"),
                "name": item.get("name"),
                "grade": item.get("grade"),
                "total_score": item.get("total_score"),
                "action": item.get("action"),
                "themes": item.get("themes", []),
                "return_3d": item.get("return_3d"),
                "return_5d": item.get("return_5d"),
                "return_10d": item.get("return_10d"),
                "outcome_label": item.get("outcome_label"),
                "outcome_reason": item.get("outcome_reason"),
                "lesson_tags": item.get("lesson_tags", []),
            }
            for item in ranked
        ]

    success = [item for item in completed if item.get("outcome_category") in {"big_winner", "true_positive"}]
    failure = [item for item in completed if item.get("outcome_category") in {"false_positive", "stop_loss"}]
    missed = [item for item in completed if item.get("outcome_category") == "missed_opportunity"]

    notes = []
    if len(completed) < 20:
        notes.append("樣本仍少，先看方向與失敗原因，等累積 20 筆以上再調整權重。")
    if success:
        notes.append("成功樣本會保留當時題材、分數、進場條件，用來找出重複出現的有效組合。")
    if failure:
        notes.append("失敗樣本會優先檢查高分失敗、跌破停損與追高假訊號。")
    if missed:
        notes.append("錯過機會代表條件可能太嚴格，之後可回頭調整進場確認門檻。")

    return {
        "sample": len(completed),
        "counts": counts,
        "success_cases": _rank(success, True),
        "failure_cases": _rank(failure, False),
        "missed_cases": _rank(missed, True),
        "notes": notes,
    }


def _return_status_code(signal_date: str, return_5d: float | None, as_of: date, horizon_days: int = 5) -> str:
    if return_5d is not None:
        return "completed_5d"
    try:
        signal_day = date.fromisoformat(str(signal_date)[:10])
    except ValueError:
        return "data_missing"
    age_days = (as_of - signal_day).days
    if age_days < horizon_days + 2:
        return "pending_5d"
    return "data_missing"


def _performance_data_quality(items: list[dict]) -> dict:
    completed_5d = [item for item in items if item.get("return_5d") is not None]
    pending_5d = [item for item in items if item.get("status_code") == "pending_5d"]
    missing_5d = [item for item in items if item.get("status_code") == "data_missing"]
    entry_known = [item for item in items if item.get("entry_triggered") is not None]
    stop_known = [item for item in items if item.get("stop_hit") is not None]
    return {
        "signals": len(items),
        "completed_5d": len(completed_5d),
        "pending_5d": len(pending_5d),
        "data_missing_5d": len(missing_5d),
        "completion_rate_5d": _rate([item.get("return_5d") is not None for item in items]),
        "entry_trigger_known": len(entry_known),
        "entry_trigger_rate": _rate([item.get("entry_triggered") for item in entry_known]),
        "stop_known": len(stop_known),
        "stop_hit_rate": _rate([item.get("stop_hit") for item in stop_known]),
        "status_counts": {
            "completed_5d": len(completed_5d),
            "pending_5d": len(pending_5d),
            "data_missing": len(missing_5d),
        },
        "pending_examples": _pending_examples(pending_5d, limit=8),
        "missing_examples": _pending_examples(missing_5d, limit=8),
    }


def _pending_examples(items: list[dict], limit: int = 8) -> list[dict]:
    return [
        {
            "signal_date": item.get("signal_date"),
            "stock_id": item.get("stock_id"),
            "name": item.get("name"),
            "grade": item.get("grade"),
            "action": item.get("action"),
        }
        for item in sorted(items, key=lambda row: (str(row.get("signal_date") or ""), int(row.get("total_score") or 0)), reverse=True)[:limit]
    ]


def _backtest_insights(items: list[dict]) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    grade_rows = grade_return_summary(items)
    action_rows = _action_stats(items)
    theme_rows = _theme_stats(items)
    candidates = []
    for group, rows in [
        ("grade", grade_rows),
        ("action", action_rows),
        ("theme", theme_rows),
    ]:
        label_key = "grade" if group == "grade" else "label"
        for row in rows:
            completed_count = int(row.get("completed") or row.get("completed_5d") or 0)
            if completed_count <= 0:
                continue
            candidates.append(
                {
                    "group": group,
                    "label": row.get(label_key),
                    "signals": row.get("signals"),
                    "completed": completed_count,
                    "win_rate_5d": row.get("win_rate_5d"),
                    "avg_return_5d": row.get("avg_return_5d"),
                    "stop_hit_rate": row.get("stop_hit_rate"),
                }
            )
    candidates.sort(
        key=lambda row: (
            float(row.get("avg_return_5d") if row.get("avg_return_5d") is not None else -999),
            float(row.get("win_rate_5d") if row.get("win_rate_5d") is not None else -999),
            int(row.get("completed") or 0),
        ),
        reverse=True,
    )
    weak = [row for row in candidates if row.get("avg_return_5d") is not None and float(row["avg_return_5d"]) < 0]
    weak.sort(
        key=lambda row: (
            float(row.get("avg_return_5d") if row.get("avg_return_5d") is not None else 999),
            float(row.get("win_rate_5d") if row.get("win_rate_5d") is not None else 999),
        )
    )
    return {
        "sample": len(completed),
        "best_segments": candidates[:5],
        "weak_segments": weak[:5],
        "notes": _backtest_notes(completed, candidates, weak),
    }


def _backtest_notes(completed: list[dict], candidates: list[dict], weak: list[dict]) -> list[str]:
    notes = []
    if len(completed) < 20:
        notes.append("樣本低於 20 筆，暫不建議調整門檻")
    if candidates:
        best = candidates[0]
        notes.append(f"目前最佳區塊：{best['group']} {best['label']}，5日平均 {best['avg_return_5d']}%")
    if weak:
        worst = weak[0]
        notes.append(f"需檢討區塊：{worst['group']} {worst['label']}，5日平均 {worst['avg_return_5d']}%")
    return notes


def _segment_summary(row: dict | None, label_key: str = "label") -> dict | None:
    if not row:
        return None
    return {
        "label": row.get(label_key),
        "signals": row.get("signals"),
        "completed": row.get("completed") or row.get("completed_5d") or 0,
        "win_rate_5d": row.get("win_rate_5d"),
        "avg_return_5d": row.get("avg_return_5d"),
        "avg_return_10d": row.get("avg_return_10d"),
        "stop_hit_rate": row.get("stop_hit_rate"),
    }


def _best_segment(rows: list[dict], label_key: str = "label", min_completed: int = 1) -> dict | None:
    eligible = [row for row in rows if int(row.get("completed") or row.get("completed_5d") or 0) >= min_completed]
    if not eligible:
        return None
    best = max(
        eligible,
        key=lambda row: (
            float(row.get("avg_return_5d") if row.get("avg_return_5d") is not None else -999),
            float(row.get("win_rate_5d") if row.get("win_rate_5d") is not None else -999),
            int(row.get("completed") or row.get("completed_5d") or 0),
        ),
    )
    return _segment_summary(best, label_key=label_key)


def _weak_segment(rows: list[dict], label_key: str = "label", min_completed: int = 1) -> dict | None:
    eligible = [row for row in rows if int(row.get("completed") or row.get("completed_5d") or 0) >= min_completed]
    if not eligible:
        return None
    weak = min(
        eligible,
        key=lambda row: (
            float(row.get("avg_return_5d") if row.get("avg_return_5d") is not None else 999),
            float(row.get("win_rate_5d") if row.get("win_rate_5d") is not None else 999),
        ),
    )
    return _segment_summary(weak, label_key=label_key)


def _sample_label(completed: int) -> str:
    if completed >= 60:
        return "可校準"
    if completed >= 30:
        return "可初判"
    if completed >= 10:
        return "觀察中"
    return "樣本不足"


def _sample_note(completed: int) -> str:
    if completed >= 60:
        return "樣本已足夠做門檻與權重校準，但仍建議人工確認。"
    if completed >= 30:
        return "樣本可做初步方向判斷，暫不建議全自動改權重。"
    if completed >= 10:
        return "樣本開始有參考價值，適合找出明顯強弱區塊。"
    return "樣本仍少，先持續記錄，不用急著調整選股規則。"


def _selection_quality_overview(
    items: list[dict],
    *,
    theme_stats: list[dict],
    action_stats: list[dict],
    score_bands: list[dict],
    ai_council: dict,
) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    ai_stats = (ai_council or {}).get("stats", {})
    return {
        "sample_label": _sample_label(len(completed)),
        "sample_note": _sample_note(len(completed)),
        "completed_5d": len(completed),
        "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
        "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
        "best_grade": _best_segment(grade_return_summary(items), label_key="grade"),
        "weak_grade": _weak_segment(grade_return_summary(items), label_key="grade"),
        "best_score_band": _best_segment(score_bands),
        "weak_score_band": _weak_segment(score_bands),
        "best_theme": _best_segment(theme_stats),
        "weak_theme": _weak_segment(theme_stats),
        "best_action": _best_segment(action_stats),
        "weak_action": _weak_segment(action_stats),
        "ai": {
            "signals": ai_stats.get("signals", 0),
            "completed": ai_stats.get("completed", 0),
            "win_rate_5d": ai_stats.get("win_rate_5d"),
            "avg_return_5d": ai_stats.get("avg_return_5d"),
            "sample_label": _sample_label(int(ai_stats.get("completed") or 0)),
        },
    }


def _calibration_row(group: str, row: dict, label_key: str = "label") -> dict | None:
    completed = int(row.get("completed") or row.get("completed_5d") or 0)
    avg_return = row.get("avg_return_5d")
    win_rate = row.get("win_rate_5d")
    stop_rate = row.get("stop_hit_rate")
    if completed < 5:
        return None
    label = row.get(label_key)
    if avg_return is not None and win_rate is not None and float(avg_return) >= 2 and float(win_rate) >= 55:
        return {
            "priority": "加權觀察",
            "group": group,
            "label": label,
            "completed": completed,
            "win_rate_5d": win_rate,
            "avg_return_5d": avg_return,
            "reason": "5日平均報酬與勝率都高於目前基準，可列入加權候選。",
        }
    if avg_return is not None and win_rate is not None and float(avg_return) <= -1 and float(win_rate) <= 45:
        return {
            "priority": "降權觀察",
            "group": group,
            "label": label,
            "completed": completed,
            "win_rate_5d": win_rate,
            "avg_return_5d": avg_return,
            "reason": "5日平均報酬偏弱且勝率不足，後續應檢查是否過度加分。",
        }
    if stop_rate is not None and float(stop_rate) >= 50:
        return {
            "priority": "風險檢查",
            "group": group,
            "label": label,
            "completed": completed,
            "win_rate_5d": win_rate,
            "avg_return_5d": avg_return,
            "reason": "停損觸及率偏高，代表進場位置或題材延續性需要重新檢查。",
        }
    return None


def _calibration_advice(
    grade_rows: list[dict],
    action_rows: list[dict],
    theme_rows: list[dict],
    limit: int = 8,
) -> list[dict]:
    advice: list[dict] = []
    for group, rows, label_key in [
        ("強度", grade_rows, "grade"),
        ("操作", action_rows, "label"),
        ("題材", theme_rows, "label"),
    ]:
        for row in rows:
            item = _calibration_row(group, row, label_key=label_key)
            if item:
                advice.append(item)
    order = {"降權觀察": 0, "風險檢查": 1, "加權觀察": 2}
    advice.sort(
        key=lambda row: (
            order.get(str(row.get("priority")), 9),
            -int(row.get("completed") or 0),
            float(row.get("avg_return_5d") if row.get("avg_return_5d") is not None else 0),
        )
    )
    return advice[:limit]


def _score_band_stats(items: list[dict]) -> list[dict]:
    bands = [
        ("50-64", 50, 64),
        ("65-74", 65, 74),
        ("75-84", 75, 84),
        ("85-94", 85, 94),
        ("95-100", 95, 100),
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


def _entry_analysis(items: list[dict]) -> dict:
    triggered = [
        item
        for item in items
        if item["entry_triggered"] is True and item["return_5d"] is not None
    ]
    not_triggered = [
        item
        for item in items
        if item["entry_triggered"] is False and item["return_5d"] is not None
    ]
    return {
        "triggered": {
            "count": len(triggered),
            "win_rate_5d": _rate([item["return_5d"] > 0 for item in triggered]),
            "avg_return_5d": _avg([item["return_5d"] for item in triggered]),
        },
        "not_triggered": {
            "count": len(not_triggered),
            "win_rate_5d": _rate([item["return_5d"] > 0 for item in not_triggered]),
            "avg_return_5d": _avg([item["return_5d"] for item in not_triggered]),
        },
    }


def _retry_row(row: tuple) -> dict:
    return {
        "dataset": row[0],
        "data_id": row[1],
        "period": row[2],
        "reason": row[3],
        "status": row[4],
        "attempts": row[5],
        "first_seen_at": row[6],
        "last_attempt_at": row[7],
        "last_error": row[8],
        "recovered_at": row[9],
    }
