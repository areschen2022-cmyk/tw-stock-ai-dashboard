from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from src.backtest.signal_lab import grade_return_summary
from src.scoring.score_engine import StockScore
from src.scoring.grade import grade_label
from src.scoring.versioning import DECISION_VERSION, SCORE_VERSION, UNIVERSE_VERSION

TAIPEI = ZoneInfo("Asia/Taipei")


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        # Keep commits in the main sqlite file so GitHub Actions can persist
        # delivery claims and outcome updates without needing untracked -wal files.
        conn.execute("PRAGMA journal_mode = DELETE")
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_prices (
                    trade_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    close REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    source TEXT NOT NULL DEFAULT 'scan',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (trade_date, stock_id)
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_scores)").fetchall()}
            if "overseas_adjustment" not in columns:
                conn.execute("ALTER TABLE daily_scores ADD COLUMN overseas_adjustment INTEGER NOT NULL DEFAULT 0")
            if "opportunity_score" not in columns:
                conn.execute("ALTER TABLE daily_scores ADD COLUMN opportunity_score INTEGER NOT NULL DEFAULT 0")
            for column, definition in [
                ("score_version", "TEXT NOT NULL DEFAULT 'v1_unversioned'"),
                ("decision_version", "TEXT NOT NULL DEFAULT 'v1_unversioned'"),
                ("universe_version", "TEXT NOT NULL DEFAULT 'unknown'"),
            ]:
                if column not in columns:
                    conn.execute(f"ALTER TABLE daily_scores ADD COLUMN {column} {definition}")
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
                ("guardrail_tags_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("guardrail_notes_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("mfe_5d", "REAL"),
                ("mfe_10d", "REAL"),
                ("mae_5d", "REAL"),
                ("mae_10d", "REAL"),
                ("score_version", "TEXT NOT NULL DEFAULT 'v1_unversioned'"),
                ("decision_version", "TEXT NOT NULL DEFAULT 'v1_unversioned'"),
                ("universe_version", "TEXT NOT NULL DEFAULT 'unknown'"),
            ]:
                if column not in watch_columns:
                    conn.execute(f"ALTER TABLE watch_signals ADD COLUMN {column} {definition}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_adjustment_signals (
                    signal_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    total_score INTEGER,
                    grade TEXT,
                    label TEXT,
                    entry_price REAL,
                    source TEXT NOT NULL DEFAULT '',
                    original_action TEXT NOT NULL DEFAULT '',
                    adjusted_action TEXT NOT NULL DEFAULT '',
                    negative_matches_json TEXT NOT NULL DEFAULT '[]',
                    positive_matches_json TEXT NOT NULL DEFAULT '[]',
                    notes_json TEXT NOT NULL DEFAULT '[]',
                    return_3d REAL,
                    return_5d REAL,
                    return_10d REAL,
                    outcome_category TEXT,
                    outcome_label TEXT,
                    outcome_reason TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (signal_date, stock_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS potential_radar_signals (
                    signal_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    grade TEXT,
                    total_score INTEGER,
                    potential_score INTEGER NOT NULL DEFAULT 0,
                    action TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    themes_json TEXT NOT NULL DEFAULT '[]',
                    entry_price REAL,
                    stage TEXT,
                    stage_label TEXT,
                    chase_risk TEXT,
                    chase_risk_label TEXT,
                    research_score INTEGER,
                    research_label TEXT,
                    research_factors_json TEXT NOT NULL DEFAULT '[]',
                    stock_type TEXT,
                    stock_type_label TEXT,
                    position_hint TEXT,
                    position_hint_label TEXT,
                    lifecycle_stage TEXT,
                    lifecycle_stage_label TEXT,
                    lifecycle_reason TEXT,
                    smart_money TEXT,
                    smart_money_label TEXT,
                    smart_money_reason TEXT,
                    smart_money_score INTEGER,
                    branch_zscore_proxy REAL,
                    institutional_follow INTEGER,
                    signal_combo TEXT,
                    feedback_penalty INTEGER NOT NULL DEFAULT 0,
                    feedback_notes_json TEXT NOT NULL DEFAULT '[]',
                    return_3d REAL,
                    return_5d REAL,
                    return_10d REAL,
                    outcome_category TEXT,
                    outcome_label TEXT,
                    outcome_reason TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (signal_date, stock_id)
                )
                """
            )
            radar_columns = {row[1] for row in conn.execute("PRAGMA table_info(potential_radar_signals)").fetchall()}
            for column, definition in [
                ("potential_score", "INTEGER NOT NULL DEFAULT 0"),
                ("return_10d", "REAL"),
                ("outcome_category", "TEXT"),
                ("outcome_label", "TEXT"),
                ("outcome_reason", "TEXT"),
                ("stage", "TEXT"),
                ("stage_label", "TEXT"),
                ("chase_risk", "TEXT"),
                ("chase_risk_label", "TEXT"),
                ("research_score", "INTEGER"),
                ("research_label", "TEXT"),
                ("research_factors_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("stock_type", "TEXT"),
                ("stock_type_label", "TEXT"),
                ("position_hint", "TEXT"),
                ("position_hint_label", "TEXT"),
                ("lifecycle_stage", "TEXT"),
                ("lifecycle_stage_label", "TEXT"),
                ("lifecycle_reason", "TEXT"),
                ("smart_money", "TEXT"),
                ("smart_money_label", "TEXT"),
                ("smart_money_reason", "TEXT"),
                ("smart_money_score", "INTEGER"),
                ("branch_zscore_proxy", "REAL"),
                ("institutional_follow", "INTEGER"),
                ("signal_combo", "TEXT"),
                ("feedback_penalty", "INTEGER NOT NULL DEFAULT 0"),
                ("feedback_notes_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("radar_layer", "TEXT"),
                ("radar_layer_label", "TEXT"),
                ("discovery_score", "INTEGER NOT NULL DEFAULT 0"),
                ("discovery_components_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("score_version", "TEXT NOT NULL DEFAULT 'v1_unversioned'"),
                ("decision_version", "TEXT NOT NULL DEFAULT 'v1_unversioned'"),
                ("universe_version", "TEXT NOT NULL DEFAULT 'unknown'"),
            ]:
                if column not in radar_columns:
                    conn.execute(f"ALTER TABLE potential_radar_signals ADD COLUMN {column} {definition}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exit_risk_signals (
                    signal_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    level TEXT NOT NULL DEFAULT '',
                    risk_score INTEGER NOT NULL DEFAULT 0,
                    current_score INTEGER,
                    previous_score INTEGER,
                    entry_price REAL,
                    reasons_json TEXT NOT NULL DEFAULT '[]',
                    action TEXT NOT NULL DEFAULT '',
                    return_3d REAL,
                    return_5d REAL,
                    outcome TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (signal_date, stock_id)
                )
                """
            )
            exit_columns = {row[1] for row in conn.execute("PRAGMA table_info(exit_risk_signals)").fetchall()}
            for column, definition in [
                ("downside_category", "TEXT"),
                ("downside_label", "TEXT"),
            ]:
                if column not in exit_columns:
                    conn.execute(f"ALTER TABLE exit_risk_signals ADD COLUMN {column} {definition}")
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
                CREATE TABLE IF NOT EXISTS theme_discovery_candidates (
                    discovery_date TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    mentions INTEGER NOT NULL DEFAULT 0,
                    stock_hits_json TEXT NOT NULL DEFAULT '[]',
                    headlines_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT '觀察中',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (discovery_date, keyword)
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
                    status TEXT NOT NULL DEFAULT 'sent',
                    PRIMARY KEY (channel, delivery_date, message_type)
                )
                """
            )
            delivery_columns = {row[1] for row in conn.execute("PRAGMA table_info(delivery_log)").fetchall()}
            if "status" not in delivery_columns:
                conn.execute("ALTER TABLE delivery_log ADD COLUMN status TEXT NOT NULL DEFAULT 'sent'")
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
                CREATE TABLE IF NOT EXISTS traceability_runs (
                    run_date TEXT NOT NULL PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    overall_status TEXT NOT NULL,
                    source_status TEXT NOT NULL DEFAULT '',
                    score_status TEXT NOT NULL DEFAULT '',
                    watch_status TEXT NOT NULL DEFAULT '',
                    potential_status TEXT NOT NULL DEFAULT '',
                    ai_status TEXT NOT NULL DEFAULT '',
                    retry_status TEXT NOT NULL DEFAULT '',
                    pages_status TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    diagnosis_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            trace_columns = {row[1] for row in conn.execute("PRAGMA table_info(traceability_runs)").fetchall()}
            if "diagnosis_json" not in trace_columns:
                conn.execute("ALTER TABLE traceability_runs ADD COLUMN diagnosis_json TEXT NOT NULL DEFAULT '[]'")
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tdcc_holder_metrics (
                    week_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    retail_holders INTEGER,
                    retail_holder_change INTEGER,
                    retail_holder_change_pct REAL,
                    big_holder_pct REAL,
                    big_holder_change_pct REAL,
                    source TEXT NOT NULL DEFAULT 'tdcc',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (week_date, stock_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS block_trade_anomalies (
                    trade_date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    block_value REAL,
                    zscore REAL,
                    signal TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (trade_date, stock_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_update_log (
                    update_date TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    status TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    source_date TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (update_date, dataset)
                )
                """
            )

    def save_traceability_run(self, traceability: dict, run_date: date) -> None:
        steps = list(traceability.get("steps") or [])
        status_by_key = {str(item.get("key") or ""): str(item.get("status") or "") for item in steps}
        statuses = [status for status in status_by_key.values() if status]
        if any(status == "bad" for status in statuses):
            overall_status = "bad"
        elif any(status == "warn" for status in statuses):
            overall_status = "warn"
        else:
            overall_status = "ok"
        generated_at = str(traceability.get("generated_at") or datetime.now(TAIPEI).isoformat(timespec="seconds"))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO traceability_runs (
                    run_date, generated_at, overall_status,
                    source_status, score_status, watch_status, potential_status,
                    ai_status, retry_status, pages_status,
                    summary_json, steps_json, diagnosis_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_date.isoformat(),
                    generated_at,
                    overall_status,
                    status_by_key.get("source", ""),
                    status_by_key.get("score", ""),
                    status_by_key.get("watch", ""),
                    status_by_key.get("potential", ""),
                    status_by_key.get("ai", ""),
                    status_by_key.get("retry", ""),
                    status_by_key.get("pages", ""),
                    json.dumps(traceability.get("summary") or {}, ensure_ascii=False),
                    json.dumps(steps, ensure_ascii=False),
                    json.dumps(traceability.get("diagnosis") or [], ensure_ascii=False),
                ),
            )

    def recent_traceability_runs(self, as_of: date | None = None, days: int = 14) -> list[dict]:
        with self._connect() as conn:
            params: tuple
            where = ""
            if as_of is not None:
                where = "WHERE run_date <= ?"
                params = (as_of.isoformat(), int(days))
            else:
                params = (int(days),)
            rows = conn.execute(
                f"""
                SELECT run_date, generated_at, overall_status,
                       source_status, score_status, watch_status, potential_status,
                       ai_status, retry_status, pages_status,
                       summary_json, steps_json
                FROM traceability_runs
                {where}
                ORDER BY run_date DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        history = []
        for row in rows:
            history.append(
                {
                    "run_date": row[0],
                    "generated_at": row[1],
                    "overall_status": row[2],
                    "source_status": row[3],
                    "score_status": row[4],
                    "watch_status": row[5],
                    "potential_status": row[6],
                    "ai_status": row[7],
                    "retry_status": row[8],
                    "pages_status": row[9],
                    "summary": json.loads(row[10] or "{}"),
                    "steps": json.loads(row[11] or "[]"),
                }
            )
        return history

    def has_delivered_today(self, channel: str, delivery_date: date, message_type: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM delivery_log
                WHERE channel = ? AND delivery_date = ? AND message_type = ? AND status = 'sent'
                LIMIT 1
                """,
                (channel, delivery_date.isoformat(), message_type),
            ).fetchone()
        return row is not None

    def has_active_delivery_claim(
        self,
        channel: str,
        delivery_date: date,
        message_type: str,
        *,
        pending_ttl_minutes: int = 45,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT sent_at, status
                FROM delivery_log
                WHERE channel = ? AND delivery_date = ? AND message_type = ?
                LIMIT 1
                """,
                (channel, delivery_date.isoformat(), message_type),
            ).fetchone()
        if not row:
            return False
        sent_at, status = row
        if status == "sent":
            return True
        if status != "pending":
            return False
        try:
            claimed_at = datetime.fromisoformat(str(sent_at))
        except ValueError:
            return True
        return datetime.now(TAIPEI) - claimed_at < timedelta(minutes=pending_ttl_minutes)

    def delivery_status(self, channel: str, delivery_date: date, message_type: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT sent_at, run_id, status
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
            "status": row[2] or "sent",
        }

    def claim_delivery(
        self,
        channel: str,
        delivery_date: date,
        message_type: str,
        run_id: str = "",
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO delivery_log
                    (channel, delivery_date, message_type, sent_at, run_id, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (
                    channel,
                    delivery_date.isoformat(),
                    message_type,
                    datetime.now(TAIPEI).isoformat(timespec="seconds"),
                    run_id,
                ),
            )
        return cursor.rowcount > 0

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
                    (channel, delivery_date, message_type, sent_at, run_id, status)
                VALUES (?, ?, ?, ?, ?, 'sent')
                """,
                (
                    channel,
                    delivery_date.isoformat(),
                    message_type,
                    datetime.now(TAIPEI).isoformat(timespec="seconds"),
                    run_id,
                ),
            )
            conn.execute(
                """
                UPDATE delivery_log
                SET sent_at = ?, run_id = ?, status = 'sent'
                WHERE channel = ? AND delivery_date = ? AND message_type = ?
                  AND status = 'pending'
                """,
                (
                    datetime.now(TAIPEI).isoformat(timespec="seconds"),
                    run_id,
                    channel,
                    delivery_date.isoformat(),
                    message_type,
                ),
            )

    def clear_delivery_claim(self, channel: str, delivery_date: date, message_type: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM delivery_log
                WHERE channel = ? AND delivery_date = ? AND message_type = ? AND status = 'pending'
                """,
                (channel, delivery_date.isoformat(), message_type),
            )

    def record_data_update(
        self,
        dataset: str,
        update_date: date,
        *,
        status: str,
        row_count: int = 0,
        source_date: date | str | None = None,
        message: str = "",
        run_id: str = "",
    ) -> None:
        if isinstance(source_date, date):
            source_date_text = source_date.isoformat()
        else:
            source_date_text = str(source_date or "")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO data_update_log
                    (update_date, dataset, status, row_count, source_date, message, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update_date.isoformat(),
                    str(dataset),
                    str(status),
                    int(row_count or 0),
                    source_date_text,
                    str(message or "")[:500],
                    str(run_id or ""),
                ),
            )

    def latest_data_updates(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT update_date, dataset, status, row_count, source_date, message, run_id, created_at
                FROM data_update_log
                ORDER BY update_date DESC, created_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            {
                "update_date": row[0],
                "dataset": row[1],
                "status": row[2],
                "row_count": row[3],
                "source_date": row[4],
                "message": row[5],
                "run_id": row[6],
                "created_at": row[7],
            }
            for row in rows
        ]

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
                        str(item.get("signal") or "無訊號"),
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
                        WHEN '觀察籌碼轉乾淨' THEN 2
                        WHEN '觀察散戶過熱' THEN 3
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
            reason_rows = conn.execute(
                """
                SELECT status, dataset, reason, COUNT(*), MAX(last_attempt_at), MAX(first_seen_at)
                FROM data_retry_queue
                WHERE status IN ('pending', 'failed')
                GROUP BY status, dataset, reason
                ORDER BY COUNT(*) DESC, MAX(COALESCE(last_attempt_at, first_seen_at)) DESC
                LIMIT 12
                """
            ).fetchall()
            recovered_rows = conn.execute(
                """
                SELECT dataset, COUNT(*), MAX(recovered_at)
                FROM data_retry_queue
                WHERE status = 'recovered'
                GROUP BY dataset
                ORDER BY COUNT(*) DESC
                LIMIT 8
                """
            ).fetchall()
        return {
            "status_counts": counts,
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
            "recovered": counts.get("recovered", 0),
            "items": [_retry_row(row) for row in rows],
            "diagnosis": [
                {
                    "status": row[0],
                    "dataset": row[1],
                    "reason": row[2],
                    "count": row[3],
                    "last_attempt_at": row[4],
                    "first_seen_at": row[5],
                    "suggestion": _retry_suggestion(row[1], row[2], row[0]),
                }
                for row in reason_rows
            ],
            "recovered_by_dataset": [
                {"dataset": row[0], "count": row[1], "last_recovered_at": row[2]}
                for row in recovered_rows
            ],
        }

    def save_daily_score(self, score: StockScore, as_of: date) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_scores (
                    as_of_date, stock_id, total_score, label, price,
                    technical_score, chip_score, fundamental_score, risk_score,
                    market_adjustment, overseas_adjustment, opportunity_score, reasons_json, warnings_json,
                    score_version, decision_version, universe_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    SCORE_VERSION,
                    DECISION_VERSION,
                    UNIVERSE_VERSION,
                ),
            )
            self._save_daily_price_conn(conn, score, as_of, source="score")

    def save_daily_prices_from_bundle(self, stock_id: str, prices, as_of: date, source: str = "bundle") -> None:
        if prices is None or getattr(prices, "empty", True):
            return
        if "date" not in prices.columns or "close" not in prices.columns:
            return
        df = prices.copy()
        df["date"] = datetime_column_to_date(df["date"])
        df = df[df["date"] <= as_of].sort_values("date")
        if df.empty:
            return
        row = df.iloc[-1]
        if row["date"] != as_of:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_prices
                    (trade_date, stock_id, close, high, low, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    as_of.isoformat(),
                    str(stock_id),
                    _safe_float(row.get("close")),
                    _safe_float(row.get("high", row.get("close"))),
                    _safe_float(row.get("low", row.get("close"))),
                    _safe_float(row.get("volume")),
                    source,
                ),
            )

    def _save_daily_price_conn(self, conn: sqlite3.Connection, score: StockScore, as_of: date, source: str) -> None:
        if score.price is None:
            return
        conn.execute(
            """
            INSERT OR IGNORE INTO daily_prices
                (trade_date, stock_id, close, high, low, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                as_of.isoformat(),
                score.stock_id,
                score.price,
                score.price,
                score.price,
                None,
                source,
            ),
        )

    def pending_outcome_stock_ids(self, as_of: date, max_age_days: int = 35, limit: int = 120) -> list[str]:
        since = (as_of - timedelta(days=max_age_days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT stock_id
                FROM (
                    SELECT stock_id FROM watch_signals
                    WHERE signal_date >= ? AND signal_date < ? AND return_10d IS NULL
                    UNION
                    SELECT stock_id FROM potential_radar_signals
                    WHERE signal_date >= ? AND signal_date < ? AND return_10d IS NULL
                    UNION
                    SELECT stock_id FROM knowledge_adjustment_signals
                    WHERE signal_date >= ? AND signal_date < ? AND return_10d IS NULL
                    UNION
                    SELECT stock_id FROM ai_council_reviews
                    WHERE review_date >= ? AND review_date < ? AND return_10d IS NULL
                )
                ORDER BY stock_id
                LIMIT ?
                """,
                (
                    since,
                    as_of.isoformat(),
                    since,
                    as_of.isoformat(),
                    since,
                    as_of.isoformat(),
                    since,
                    as_of.isoformat(),
                    limit,
                ),
            ).fetchall()
        return [str(row[0]) for row in rows if row and row[0]]

    def prune_daily_scores(self, as_of: date, stock_ids: list[str]) -> None:
        """Keep same-day daily_scores aligned with the current scan universe."""
        keep_ids = [str(stock_id) for stock_id in dict.fromkeys(stock_ids) if str(stock_id).strip()]
        with self._connect() as conn:
            if not keep_ids:
                conn.execute("DELETE FROM daily_scores WHERE as_of_date = ?", (as_of.isoformat(),))
                return
            placeholders = ",".join("?" for _ in keep_ids)
            conn.execute(
                f"DELETE FROM daily_scores WHERE as_of_date = ? AND stock_id NOT IN ({placeholders})",
                (as_of.isoformat(), *keep_ids),
            )

    def _entry_price_conn(self, conn: sqlite3.Connection, stock_id: str, signal_date: str) -> float | None:
        row = conn.execute(
            """
            SELECT close
            FROM daily_prices
            WHERE trade_date = ? AND stock_id = ? AND close IS NOT NULL
            LIMIT 1
            """,
            (signal_date, stock_id),
        ).fetchone()
        if row:
            return float(row[0])
        row = conn.execute(
            """
            SELECT price
            FROM daily_scores
            WHERE as_of_date = ? AND stock_id = ? AND price IS NOT NULL
            LIMIT 1
            """,
            (signal_date, stock_id),
        ).fetchone()
        return float(row[0]) if row else None

    def _forward_price_rows_conn(
        self,
        conn: sqlite3.Connection,
        stock_id: str,
        signal_date: str,
        *,
        max_calendar_days: int = 35,
    ) -> list[tuple]:
        end_date = (date.fromisoformat(str(signal_date)) + timedelta(days=max_calendar_days)).isoformat()
        rows = conn.execute(
            """
            SELECT trade_date, close, low, high
            FROM daily_prices
            WHERE stock_id = ?
              AND trade_date > ?
              AND trade_date <= ?
              AND close IS NOT NULL
            ORDER BY trade_date
            """,
            (stock_id, signal_date, end_date),
        ).fetchall()
        if rows:
            return rows
        return conn.execute(
            """
            SELECT as_of_date, price, price, price
            FROM daily_scores
            WHERE stock_id = ?
              AND as_of_date > ?
              AND as_of_date <= ?
              AND price IS NOT NULL
            ORDER BY as_of_date
            """,
            (stock_id, signal_date, end_date),
        ).fetchall()

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
        tracked_actions = {"可追", "可追蹤突破", "等拉回"}
        candidates = [
            score
            for score in scores
            if score.label == "BUY_WATCH" and score.price is not None and score.action in tracked_actions
        ]
        with self._connect() as conn:
            conn.execute("DELETE FROM watch_signals WHERE signal_date = ?", (as_of.isoformat(),))
            for score in candidates:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO watch_signals (
                        signal_date, stock_id, name, total_score, label, action,
                        entry_price, entry_condition, stop_reference, themes_json,
                        stop_price, entry_limit_price, vol_5min_threshold, grade,
                        guardrail_tags_json, guardrail_notes_json,
                        score_version, decision_version, universe_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        as_of.isoformat(),
                        score.stock_id,
                        stock_names.get(score.stock_id, "未知股票"),
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
                        json.dumps(score.guardrail_tags, ensure_ascii=False),
                        json.dumps(score.guardrail_notes, ensure_ascii=False),
                        SCORE_VERSION,
                        DECISION_VERSION,
                        UNIVERSE_VERSION,
                    ),
                )

    def save_tdcc_holder_metrics(self, metrics: list[dict], week_date: date) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tdcc_holder_metrics WHERE week_date = ?", (week_date.isoformat(),))
            for item in metrics:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO tdcc_holder_metrics (
                        week_date, stock_id, name, retail_holders,
                        retail_holder_change, retail_holder_change_pct,
                        big_holder_pct, big_holder_change_pct, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        week_date.isoformat(),
                        str(item.get("stock_id") or ""),
                        str(item.get("name") or ""),
                        item.get("retail_holders"),
                        item.get("retail_holder_change"),
                        item.get("retail_holder_change_pct"),
                        item.get("big_holder_pct"),
                        item.get("big_holder_change_pct"),
                        str(item.get("source") or "tdcc"),
                    ),
                )

    def latest_tdcc_holder_metrics(self, week_date: date | None = None, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            target = week_date.isoformat() if week_date else conn.execute(
                "SELECT MAX(week_date) FROM tdcc_holder_metrics"
            ).fetchone()[0]
            if not target:
                return []
            rows = conn.execute(
                """
                SELECT week_date, stock_id, name, retail_holders, retail_holder_change,
                       retail_holder_change_pct, big_holder_pct, big_holder_change_pct, source
                FROM tdcc_holder_metrics
                WHERE week_date = ?
                ORDER BY COALESCE(big_holder_change_pct, 0) DESC, COALESCE(big_holder_pct, 0) DESC
                LIMIT ?
                """,
                (target, limit),
            ).fetchall()
        return [
            {
                "week_date": row[0],
                "stock_id": row[1],
                "name": row[2],
                "retail_holders": row[3],
                "retail_holder_change": row[4],
                "retail_holder_change_pct": row[5],
                "big_holder_pct": row[6],
                "big_holder_change_pct": row[7],
                "source": row[8],
            }
            for row in rows
        ]

    def save_block_trade_anomalies(self, anomalies: list[dict], trade_date: date) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM block_trade_anomalies WHERE trade_date = ?", (trade_date.isoformat(),))
            for item in anomalies:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO block_trade_anomalies (
                        trade_date, stock_id, name, block_value, zscore, signal, source, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade_date.isoformat(),
                        str(item.get("stock_id") or ""),
                        str(item.get("name") or ""),
                        item.get("block_value"),
                        item.get("zscore"),
                        str(item.get("signal") or ""),
                        str(item.get("source") or ""),
                        str(item.get("reason") or ""),
                    ),
                )

    def latest_block_trade_anomalies(self, trade_date: date | None = None, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            target = trade_date.isoformat() if trade_date else conn.execute(
                "SELECT MAX(trade_date) FROM block_trade_anomalies"
            ).fetchone()[0]
            if not target:
                return []
            rows = conn.execute(
                """
                SELECT trade_date, stock_id, name, block_value, zscore, signal, source, reason
                FROM block_trade_anomalies
                WHERE trade_date = ?
                ORDER BY COALESCE(zscore, 0) DESC, COALESCE(block_value, 0) DESC
                LIMIT ?
                """,
                (target, limit),
            ).fetchall()
        return [
            {
                "trade_date": row[0],
                "stock_id": row[1],
                "name": row[2],
                "block_value": row[3],
                "zscore": row[4],
                "signal": row[5],
                "source": row[6],
                "reason": row[7],
            }
            for row in rows
        ]

    def save_knowledge_adjustments(self, scores: list[StockScore], as_of: date, stock_names: dict[str, str]) -> None:
        records = [
            score
            for score in scores
            if score.knowledge_adjustment and (score.knowledge_notes or score.knowledge_adjustment.get("negative_matches") or score.knowledge_adjustment.get("positive_matches"))
        ]
        with self._connect() as conn:
            conn.execute("DELETE FROM knowledge_adjustment_signals WHERE signal_date = ?", (as_of.isoformat(),))
            for score in records:
                adjustment = score.knowledge_adjustment or {}
                conn.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_adjustment_signals (
                        signal_date, stock_id, name, total_score, grade, label, entry_price,
                        source, original_action, adjusted_action,
                        negative_matches_json, positive_matches_json, notes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        as_of.isoformat(),
                        score.stock_id,
                        stock_names.get(score.stock_id, ""),
                        score.total_score,
                        _grade(score.total_score),
                        score.label,
                        score.price,
                        str(adjustment.get("source") or ""),
                        str(adjustment.get("original_action") or ""),
                        str(adjustment.get("adjusted_action") or score.action or ""),
                        json.dumps(adjustment.get("negative_matches") or [], ensure_ascii=False),
                        json.dumps(adjustment.get("positive_matches") or [], ensure_ascii=False),
                        json.dumps(score.knowledge_notes or [], ensure_ascii=False),
                    ),
                )

    def save_exit_risks(self, risks: list[dict], as_of: date) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM exit_risk_signals WHERE signal_date = ?", (as_of.isoformat(),))
            for item in risks:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO exit_risk_signals (
                        signal_date, stock_id, name, level, risk_score, current_score,
                        previous_score, entry_price, reasons_json, action,
                        downside_category, downside_label
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        as_of.isoformat(),
                        str(item.get("stock_id") or ""),
                        str(item.get("name") or ""),
                        str(item.get("level") or ""),
                        int(item.get("risk_score") or 0),
                        item.get("current_score"),
                        item.get("previous_score"),
                        item.get("price"),
                        json.dumps(item.get("reasons") or [], ensure_ascii=False),
                        str(item.get("action") or ""),
                        str(item.get("downside_category") or ""),
                        str(item.get("downside_label") or ""),
                    ),
                )

    def update_exit_risk_forward_returns(self, as_of: date) -> None:
        with self._connect() as conn:
            signals = conn.execute(
                """
                SELECT signal_date, stock_id, entry_price
                FROM exit_risk_signals
                WHERE signal_date < ? AND return_5d IS NULL
                """,
                (as_of.isoformat(),),
            ).fetchall()
            for signal_date, stock_id, entry_price in signals:
                base_entry = entry_price
                if base_entry is None:
                    base = self._entry_price_conn(conn, stock_id, signal_date)
                    if not base:
                        continue
                    base_entry = float(base)
                future_rows = self._forward_price_rows_conn(conn, stock_id, signal_date)
                if not future_rows:
                    continue
                return_3d = _pct_return(_nth_trading_close(future_rows, 3), base_entry)
                return_5d = _pct_return(_nth_trading_close(future_rows, 5), base_entry)
                outcome = _exit_risk_outcome(return_5d)
                conn.execute(
                    """
                    UPDATE exit_risk_signals
                    SET entry_price = COALESCE(entry_price, ?),
                        return_3d = COALESCE(?, return_3d),
                        return_5d = COALESCE(?, return_5d),
                        outcome = ?
                    WHERE signal_date = ? AND stock_id = ?
                    """,
                    (base_entry, return_3d, return_5d, outcome, signal_date, stock_id),
                )

    def save_potential_radar(self, candidates: list[dict], as_of: date) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM potential_radar_signals WHERE signal_date = ?", (as_of.isoformat(),))
            for item in candidates:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO potential_radar_signals (
                        signal_date, stock_id, name, grade, total_score, potential_score, action,
                        reason, tags_json, themes_json, entry_price, stage, stage_label,
                        chase_risk, chase_risk_label, research_score, research_label,
                        research_factors_json, stock_type, stock_type_label, position_hint,
                        position_hint_label, lifecycle_stage, lifecycle_stage_label,
                        lifecycle_reason, smart_money, smart_money_label, smart_money_reason,
                        smart_money_score, branch_zscore_proxy, institutional_follow, signal_combo,
                        feedback_penalty, feedback_notes_json, radar_layer, radar_layer_label,
                        discovery_score, discovery_components_json, score_version, decision_version, universe_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.get("signal_date") or as_of.isoformat()),
                        str(item.get("stock_id") or ""),
                        str(item.get("name") or ""),
                        item.get("grade"),
                        item.get("total_score"),
                        item.get("potential_score") or 0,
                        str(item.get("action") or ""),
                        str(item.get("reason") or ""),
                        json.dumps(item.get("tags") or [], ensure_ascii=False),
                        json.dumps(item.get("themes") or [], ensure_ascii=False),
                        item.get("entry_price"),
                        item.get("stage"),
                        item.get("stage_label"),
                        item.get("chase_risk"),
                        item.get("chase_risk_label"),
                        item.get("research_score"),
                        item.get("research_label"),
                        json.dumps(item.get("research_factors") or [], ensure_ascii=False),
                        item.get("stock_type"),
                        item.get("stock_type_label"),
                        item.get("position_hint"),
                        item.get("position_hint_label"),
                        item.get("lifecycle_stage"),
                        item.get("lifecycle_stage_label"),
                        item.get("lifecycle_reason"),
                        item.get("smart_money"),
                        item.get("smart_money_label"),
                        item.get("smart_money_reason"),
                        item.get("smart_money_score"),
                        item.get("branch_zscore_proxy"),
                        1 if item.get("institutional_follow") else 0,
                        item.get("signal_combo"),
                        item.get("feedback_penalty") or 0,
                        json.dumps(item.get("feedback_notes") or [], ensure_ascii=False),
                        item.get("radar_layer"),
                        item.get("radar_layer_label"),
                        item.get("discovery_score") or item.get("potential_score") or 0,
                        json.dumps(item.get("discovery_components") or {}, ensure_ascii=False),
                        SCORE_VERSION,
                        DECISION_VERSION,
                        UNIVERSE_VERSION,
                    ),
                )

    def update_potential_forward_returns(self, as_of: date) -> None:
        with self._connect() as conn:
            signals = conn.execute(
                """
                SELECT signal_date, stock_id, entry_price, tags_json
                FROM potential_radar_signals
                WHERE signal_date < ?
                  AND (return_5d IS NULL OR return_10d IS NULL)
                """,
                (as_of.isoformat(),),
            ).fetchall()
            for signal_date, stock_id, entry_price, tags_json in signals:
                base_entry = entry_price
                if base_entry is None:
                    base = self._entry_price_conn(conn, stock_id, signal_date)
                    if not base:
                        continue
                    base_entry = float(base)
                future_rows = self._forward_price_rows_conn(conn, stock_id, signal_date)
                if not future_rows:
                    continue
                return_3d = _pct_return(_nth_trading_close(future_rows, 3), base_entry)
                return_5d = _pct_return(_nth_trading_close(future_rows, 5), base_entry)
                return_10d = _pct_return(_nth_trading_close(future_rows, 10), base_entry)
                outcome = _potential_outcome(return_5d, return_10d, _json_list(tags_json))
                conn.execute(
                    """
                    UPDATE potential_radar_signals
                    SET entry_price = COALESCE(entry_price, ?),
                        return_3d = COALESCE(?, return_3d),
                        return_5d = COALESCE(?, return_5d),
                        return_10d = COALESCE(?, return_10d),
                        outcome_category = ?,
                        outcome_label = ?,
                        outcome_reason = ?
                    WHERE signal_date = ? AND stock_id = ?
                    """,
                    (
                        base_entry,
                        return_3d,
                        return_5d,
                        return_10d,
                        outcome["category"],
                        outcome["label"],
                        outcome["reason"],
                        signal_date,
                        stock_id,
                    ),
                )

    def update_knowledge_forward_returns(self, as_of: date) -> None:
        with self._connect() as conn:
            signals = conn.execute(
                """
                SELECT signal_date, stock_id, entry_price, original_action, adjusted_action,
                       negative_matches_json, positive_matches_json
                FROM knowledge_adjustment_signals
                WHERE signal_date < ?
                  AND (return_5d IS NULL OR return_10d IS NULL)
                """,
                (as_of.isoformat(),),
            ).fetchall()
            for signal_date, stock_id, entry_price, original_action, adjusted_action, negative_json, positive_json in signals:
                base_entry = entry_price
                if base_entry is None:
                    base = self._entry_price_conn(conn, stock_id, signal_date)
                    if not base:
                        continue
                    base_entry = float(base)
                future_rows = self._forward_price_rows_conn(conn, stock_id, signal_date)
                if not future_rows:
                    continue
                return_3d = _pct_return(_nth_trading_close(future_rows, 3), base_entry)
                return_5d = _pct_return(_nth_trading_close(future_rows, 5), base_entry)
                return_10d = _pct_return(_nth_trading_close(future_rows, 10), base_entry)
                outcome = _knowledge_outcome(
                    return_5d,
                    original_action=str(original_action or ""),
                    adjusted_action=str(adjusted_action or ""),
                    negative_matches=_json_list(negative_json),
                    positive_matches=_json_list(positive_json),
                )
                conn.execute(
                    """
                    UPDATE knowledge_adjustment_signals
                    SET entry_price = COALESCE(entry_price, ?),
                        return_3d = COALESCE(?, return_3d),
                        return_5d = COALESCE(?, return_5d),
                        return_10d = COALESCE(?, return_10d),
                        outcome_category = ?,
                        outcome_label = ?,
                        outcome_reason = ?
                    WHERE signal_date = ? AND stock_id = ?
                    """,
                    (
                        base_entry,
                        return_3d,
                        return_5d,
                        return_10d,
                        outcome["category"],
                        outcome["label"],
                        outcome["reason"],
                        signal_date,
                        stock_id,
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
                future_rows = self._forward_price_rows_conn(conn, stock_id, signal_date)
                if not future_rows:
                    continue
                prices = [float(row[1]) for row in future_rows]
                lows = [float(row[2]) if row[2] is not None else float(row[1]) for row in future_rows]
                price_3d = _nth_trading_close(future_rows, 3)
                price_5d = _nth_trading_close(future_rows, 5)
                price_10d = _nth_trading_close(future_rows, 10)
                return_3d = _pct_return(price_3d, entry_price)
                return_5d = _pct_return(price_5d, entry_price)
                return_10d = _pct_return(price_10d, entry_price)
                mfe_5d = _mfe_return(future_rows[:5], entry_price)
                mfe_10d = _mfe_return(future_rows[:10], entry_price)
                mae_5d = _mae_return(future_rows[:5], entry_price)
                mae_10d = _mae_return(future_rows[:10], entry_price)
                stop_hit = None
                if stop_price is not None:
                    stop_hit = int(any(price <= float(stop_price) for price in lows[:5]))
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
                        mfe_5d = COALESCE(?, mfe_5d),
                        mfe_10d = COALESCE(?, mfe_10d),
                        mae_5d = COALESCE(?, mae_5d),
                        mae_10d = COALESCE(?, mae_10d),
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
                        mfe_5d,
                        mfe_10d,
                        mae_5d,
                        mae_10d,
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
            base = self._entry_price_conn(conn, stock_id, review_date)
            if not base:
                continue
            future_rows = self._forward_price_rows_conn(conn, stock_id, review_date)
            if not future_rows:
                continue
            entry_price = float(base)
            conn.execute(
                """
                UPDATE ai_council_reviews
                SET return_3d = COALESCE(?, return_3d),
                    return_5d = COALESCE(?, return_5d),
                    return_10d = COALESCE(?, return_10d)
                WHERE review_date = ? AND stock_id = ?
                """,
                (
                    _pct_return(_nth_trading_close(future_rows, 3), entry_price),
                    _pct_return(_nth_trading_close(future_rows, 5), entry_price),
                    _pct_return(_nth_trading_close(future_rows, 10), entry_price),
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
                       entry_triggered, return_3d, return_5d, return_10d, stop_hit, action, themes_json,
                       guardrail_tags_json, guardrail_notes_json,
                       mfe_5d, mfe_10d, mae_5d, mae_10d,
                       score_version, decision_version, universe_version
                FROM watch_signals
                WHERE signal_date >= ?
                ORDER BY signal_date DESC, total_score DESC
                """,
                (since.isoformat(),),
            ).fetchall()
        items = []
        for row in rows:
            (
                signal_date, stock_id, name, grade, total_score, entry_price,
                entry_triggered, return_3d, return_5d, return_10d, stop_hit, action,
                themes_json, guardrail_tags_json, guardrail_notes_json,
                mfe_5d, mfe_10d, mae_5d, mae_10d,
                score_version, decision_version, universe_version,
            ) = row
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
                    "mfe_5d": mfe_5d,
                    "mfe_10d": mfe_10d,
                    "mae_5d": mae_5d,
                    "mae_10d": mae_10d,
                    "stop_hit": _bool_or_none(stop_hit),
                    "action": action,
                    "themes": json.loads(themes_json or "[]"),
                    "guardrail_tags": json.loads(guardrail_tags_json or "[]"),
                    "guardrail_notes": json.loads(guardrail_notes_json or "[]"),
                    "score_version": score_version or "v1_unversioned",
                    "decision_version": decision_version or "v1_unversioned",
                    "universe_version": universe_version or "unknown",
                    "status_code": status_code,
                    "status_label": {
                        "completed_5d": "completed",
                        "pending_5d": "pending",
                        "data_missing": "data_missing",
                    }[status_code],
                    "status": "已完成" if return_5d is not None else "觀察中",
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
        potential_radar = self.potential_radar_summary(as_of, days=days)
        exit_risk = self.exit_risk_summary(as_of, days=days)
        knowledge_adjustment = self.knowledge_adjustment_summary(as_of, days=days)
        signal_lab = grade_return_summary(items)
        postmortem = _postmortem_summary(items)
        learning_center = _learning_center_summary(items)
        signal_attribution = _signal_attribution_center(items, potential_radar, ai_council)
        calibration_advice = _calibration_advice(signal_lab, action_stats, theme_stats)
        low_win_rate_breakdown = _low_win_rate_breakdown(
            items,
            theme_stats=theme_stats,
            action_stats=action_stats,
            score_bands=score_bands,
            entry_analysis=_entry_analysis(items),
            factor_rows=signal_attribution.get("factor_rows", []),
        )
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
            "leaderboard": {
                "top_5d": _leaderboard(items, limit=8),
                "bottom_5d": sorted(
                    [item for item in items if item.get("return_5d") is not None],
                    key=lambda item: float(item.get("return_5d") or 0),
                )[:8],
            },
            "data_quality": _performance_data_quality(items),
            "score_bands": score_bands,
            "entry_analysis": _entry_analysis(items),
            "signal_lab": signal_lab,
            "postmortem": postmortem,
            "learning_center": learning_center,
            "potential_radar": potential_radar,
            "guardrail_stats": _guardrail_stats(items),
            "exit_risk": exit_risk,
            "knowledge_adjustment": knowledge_adjustment,
            "backtest_insights": backtest_insights,
            "ai_council": ai_council,
            "signal_attribution": signal_attribution,
            "selection_quality": _selection_quality_overview(
                items,
                theme_stats=theme_stats,
                action_stats=action_stats,
                score_bands=score_bands,
                ai_council=ai_council,
            ),
            "low_win_rate_breakdown": low_win_rate_breakdown,
            "calibration_advice": calibration_advice,
            "adaptive_feedback": _adaptive_feedback(postmortem, potential_radar, signal_attribution, calibration_advice),
            "items": items,
        }

    def potential_radar_summary(self, as_of: date, days: int = 30) -> dict:
        since = as_of - timedelta(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signal_date, stock_id, name, grade, total_score, action,
                       potential_score, reason, tags_json, themes_json, entry_price,
                       stage, stage_label, chase_risk, chase_risk_label,
                       research_score, research_label, research_factors_json,
                       stock_type, stock_type_label, position_hint, position_hint_label,
                       return_3d, return_5d, return_10d,
                       outcome_category, outcome_label, outcome_reason,
                       lifecycle_stage, lifecycle_stage_label, lifecycle_reason,
                       smart_money, smart_money_label, smart_money_reason,
                       smart_money_score, branch_zscore_proxy, institutional_follow, signal_combo,
                       feedback_penalty, feedback_notes_json, radar_layer, radar_layer_label
                FROM potential_radar_signals
                WHERE signal_date >= ?
                ORDER BY signal_date DESC, total_score DESC
                """,
                (since.isoformat(),),
            ).fetchall()
        items = []
        for row in rows:
            outcome = _potential_outcome(row[23], row[24], _json_list(row[8]))
            category = row[25] or outcome["category"]
            label = row[26] or outcome["label"]
            reason = row[27] or outcome["reason"]
            items.append(
                {
                    "signal_date": row[0],
                    "stock_id": row[1],
                    "name": row[2],
                    "grade": row[3],
                    "total_score": row[4],
                    "action": row[5],
                    "potential_score": row[6],
                    "reason": row[7],
                    "tags": json.loads(row[8] or "[]"),
                    "themes": json.loads(row[9] or "[]"),
                    "entry_price": row[10],
                    "stage": row[11] or _infer_potential_stage(row[6], row[4], row[3], _json_list(row[8]))["key"],
                    "stage_label": row[12] or _infer_potential_stage(row[6], row[4], row[3], _json_list(row[8]))["label"],
                    "chase_risk": row[13] or "",
                    "chase_risk_label": row[14] or "",
                    "research_score": row[15],
                    "research_label": row[16] or "",
                    "research_factors": json.loads(row[17] or "[]"),
                    "stock_type": row[18] or "",
                    "stock_type_label": row[19] or "",
                    "position_hint": row[20] or "",
                    "position_hint_label": row[21] or "",
                    "return_3d": row[22],
                    "return_5d": row[23],
                    "return_10d": row[24],
                    "outcome_category": category,
                    "outcome_label": label,
                    "outcome_reason": reason,
                    "lifecycle_stage": row[28] or "",
                    "lifecycle_stage_label": row[29] or "",
                    "lifecycle_reason": row[30] or "",
                    "smart_money": row[31] or "",
                    "smart_money_label": row[32] or "",
                    "smart_money_reason": row[33] or "",
                    "smart_money_score": row[34],
                    "branch_zscore_proxy": row[35],
                    "institutional_follow": bool(row[36]) if row[36] is not None else False,
                    "signal_combo": row[37] or "",
                    "feedback_penalty": row[38] or 0,
                    "feedback_notes": json.loads(row[39] or "[]"),
                    "radar_layer": row[40] or _infer_radar_layer(row[11], row[28], row[31], row[4], row[3], row[6])["key"],
                    "radar_layer_label": row[41] or _infer_radar_layer(row[11], row[28], row[31], row[4], row[3], row[6])["label"],
                }
            )
        with self._connect() as conn:
            _annotate_potential_promotions(conn, items)
        completed = [item for item in items if item["return_5d"] is not None]
        success = [
            item for item in completed
            if item["outcome_category"] in {"potential_big_winner", "potential_success"}
        ]
        failure = [item for item in completed if item["outcome_category"] == "potential_false_positive"]
        pending = [item for item in items if item["return_5d"] is None]
        counts = {}
        for item in items:
            counts[item["outcome_category"]] = counts.get(item["outcome_category"], 0) + 1
        factor_stats = _potential_factor_stats(items)
        occurrence_counts = _potential_occurrence_counts(items)
        success_cases = _unique_potential_items(
            success,
            occurrence_counts,
            key_func=lambda item: (
                float(item["return_10d"] if item["return_10d"] is not None else item["return_5d"] or 0),
                float(item["return_5d"] or 0),
            ),
            reverse=True,
            limit=8,
        )
        failure_cases = _unique_potential_items(
            failure,
            occurrence_counts,
            key_func=lambda item: float(item["return_5d"] or 0),
            reverse=False,
            limit=8,
        )
        pending_candidates = _unique_potential_items(
            pending,
            occurrence_counts,
            key_func=lambda item: (
                item.get("signal_date") or "",
                int(item.get("potential_score") or 0),
                int(item.get("total_score") or 0),
            ),
            reverse=True,
            limit=8,
        )
        return {
            "stats": {
                "signals": len(items),
                "completed": len(completed),
                "pending": len(pending),
                "win_rate_5d": _rate([item["return_5d"] > 0 for item in completed]),
                "avg_return_5d": _avg([item["return_5d"] for item in completed]),
                "avg_return_10d": _avg([item["return_10d"] for item in items if item["return_10d"] is not None]),
                "big_winner_count": counts.get("potential_big_winner", 0),
                "false_positive_count": counts.get("potential_false_positive", 0),
            },
            "counts": [{"category": key, "count": value} for key, value in sorted(counts.items())],
            "success_cases": success_cases,
            "failure_cases": failure_cases,
            "pending_candidates": pending_candidates,
            "factor_stats": factor_stats,
            "stage_stats": _potential_stage_stats(items),
            "layer_stats": _potential_bucket_stats(items, "radar_layer_label", "雷達層級"),
            "lifecycle_stats": _potential_bucket_stats(items, "lifecycle_stage_label", "生命週期"),
            "smart_money_stats": _potential_bucket_stats(items, "smart_money_label", "資金同步"),
            "combo_stats": _potential_bucket_stats(items, "signal_combo", "訊號組合", limit=12),
            "promotion_funnel": _potential_promotion_funnel(items, occurrence_counts),
            "strong_factors": _rank_potential_factors(factor_stats, reverse=True),
            "weak_factors": _rank_potential_factors(factor_stats, reverse=False),
            "factor_notes": _potential_factor_notes(factor_stats),
            "items": items,
        }

    def exit_risk_summary(self, as_of: date, days: int = 30) -> dict:
        since = as_of - timedelta(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signal_date, stock_id, name, level, risk_score, current_score,
                       previous_score, entry_price, reasons_json, action,
                       return_3d, return_5d, outcome, downside_category, downside_label
                FROM exit_risk_signals
                WHERE signal_date >= ? AND signal_date <= ?
                ORDER BY signal_date DESC, risk_score DESC
                """,
                (since.isoformat(), as_of.isoformat()),
            ).fetchall()
        items = [
            {
                "signal_date": row[0],
                "stock_id": row[1],
                "name": row[2],
                "level": row[3],
                "risk_score": row[4],
                "current_score": row[5],
                "previous_score": row[6],
                "entry_price": row[7],
                "reasons": _json_list(row[8]),
                "action": row[9],
                "return_3d": row[10],
                "return_5d": row[11],
                "outcome": row[12],
                "downside_category": row[13] or "",
                "downside_label": row[14] or "",
            }
            for row in rows
        ]
        completed = [item for item in items if item.get("return_5d") is not None]
        true_warnings = [item for item in completed if float(item.get("return_5d") or 0) < 0]
        false_warnings = [item for item in completed if float(item.get("return_5d") or 0) >= 0]
        downside_stats: dict[str, dict] = {}
        for item in items:
            label = str(item.get("downside_label") or "未分類跌因")
            bucket = downside_stats.setdefault(
                label,
                {
                    "label": label,
                    "signals": 0,
                    "completed": 0,
                    "true_warnings": 0,
                    "false_warnings": 0,
                    "true_warning_rate_3d": None,
                    "true_warning_rate_5d": None,
                    "avg_return_5d": None,
                    "sample_label": "樣本不足",
                    "_hits_3d": [],
                    "_hits_5d": [],
                    "_returns_5d": [],
                },
            )
            bucket["signals"] += 1
            if item.get("return_5d") is not None:
                bucket["completed"] += 1
                hit_5d = float(item.get("return_5d") or 0) < 0
                bucket["true_warnings"] += 1 if hit_5d else 0
                bucket["false_warnings"] += 0 if hit_5d else 1
                bucket["_hits_5d"].append(hit_5d)
                bucket["_returns_5d"].append(item.get("return_5d"))
            if item.get("return_3d") is not None:
                bucket["_hits_3d"].append(float(item.get("return_3d") or 0) < 0)
        for bucket in downside_stats.values():
            bucket["true_warning_rate_3d"] = _rate(bucket.pop("_hits_3d"))
            bucket["true_warning_rate_5d"] = _rate(bucket.pop("_hits_5d"))
            bucket["avg_return_5d"] = _avg(bucket.pop("_returns_5d"))
            completed_count = int(bucket.get("completed") or 0)
            bucket["sample_label"] = _exit_risk_sample_label(completed_count)
        return {
            "items": items[:20],
            "stats": {
                "signals": len(items),
                "completed": len(completed),
                "true_warning_rate_5d": _rate([float(item.get("return_5d") or 0) < 0 for item in completed]),
                "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
                "true_warnings": len(true_warnings),
                "false_warnings": len(false_warnings),
            },
            "downside_stats": sorted(
                downside_stats.values(),
                key=lambda item: (-int(item.get("signals") or 0), str(item.get("label") or "")),
            ),
            "true_warnings": sorted(true_warnings, key=lambda item: float(item.get("return_5d") or 0))[:8],
            "false_warnings": sorted(false_warnings, key=lambda item: float(item.get("return_5d") or 0), reverse=True)[:8],
        }

    def knowledge_adjustment_summary(self, as_of: date, days: int = 30) -> dict:
        since = as_of - timedelta(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signal_date, stock_id, name, total_score, grade, label, entry_price,
                       source, original_action, adjusted_action,
                       negative_matches_json, positive_matches_json, notes_json,
                       return_3d, return_5d, return_10d,
                       outcome_category, outcome_label, outcome_reason
                FROM knowledge_adjustment_signals
                WHERE signal_date >= ?
                ORDER BY signal_date DESC, total_score DESC
                """,
                (since.isoformat(),),
            ).fetchall()
        items = [
            {
                "signal_date": row[0],
                "stock_id": row[1],
                "name": row[2],
                "total_score": row[3],
                "grade": row[4],
                "label": row[5],
                "entry_price": row[6],
                "source": row[7],
                "original_action": row[8],
                "adjusted_action": row[9],
                "negative_matches": _json_list(row[10]),
                "positive_matches": _json_list(row[11]),
                "notes": _json_list(row[12]),
                "return_3d": row[13],
                "return_5d": row[14],
                "return_10d": row[15],
                "outcome_category": row[16],
                "outcome_label": row[17],
                "outcome_reason": row[18],
            }
            for row in rows
        ]
        completed = [item for item in items if item.get("return_5d") is not None]
        downgraded = [item for item in items if item.get("original_action") != item.get("adjusted_action")]
        completed_downgraded = [item for item in downgraded if item.get("return_5d") is not None]
        positive = [item for item in items if item.get("positive_matches")]
        completed_positive = [item for item in positive if item.get("return_5d") is not None]
        return {
            "signals": len(items),
            "completed": len(completed),
            "downgraded": len(downgraded),
            "downgraded_completed": len(completed_downgraded),
            "protected_count": sum(1 for item in completed_downgraded if float(item.get("return_5d") or 0) <= 0),
            "protection_rate_5d": _rate([float(item.get("return_5d") or 0) <= 0 for item in completed_downgraded]),
            "positive_completed": len(completed_positive),
            "positive_win_rate_5d": _rate([float(item.get("return_5d") or 0) > 0 for item in completed_positive]),
            "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
            "avg_return_10d": _avg([item.get("return_10d") for item in completed if item.get("return_10d") is not None]),
            "items": items,
            "status": "sample_accumulating" if len(completed) < 20 else "calibratable",
            "note": "知識庫調整需累積至少 20 筆完成樣本才進入校準。",
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
                "status": "已完成" if row[13] is not None else "觀察中",
            }
            for row in rows
        ]
        by_action = []
        for action in ["可追", "可追蹤突破", "等拉回", "只觀察", "避免"]:
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

    def recommendation_stability(self, as_of: date, days: int = 10) -> dict:
        """Summarize how often each stock has appeared in recent BUY_WATCH signals."""

        since = as_of - timedelta(days=days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT signal_date, stock_id, name, grade, total_score, action, return_5d
                FROM watch_signals
                WHERE signal_date >= ? AND signal_date <= ?
                ORDER BY stock_id, signal_date DESC
                """,
                (since.isoformat(), as_of.isoformat()),
            ).fetchall()

        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(str(row[1]), []).append(
                {
                    "signal_date": row[0],
                    "stock_id": row[1],
                    "name": row[2],
                    "grade": row[3],
                    "total_score": row[4],
                    "action": row[5],
                    "return_5d": row[6],
                }
            )

        by_stock = {}
        rows_out = []
        for stock_id, signals in grouped.items():
            signals.sort(key=lambda item: str(item.get("signal_date") or ""), reverse=True)
            latest = signals[0]
            active_today = latest.get("signal_date") == as_of.isoformat()
            first_seen = signals[-1].get("signal_date")
            previous_seen = signals[1].get("signal_date") if len(signals) > 1 else None
            recent_count = len(signals)
            label = _stability_label(recent_count, active_today)
            item = {
                "stock_id": stock_id,
                "name": latest.get("name"),
                "active_today": active_today,
                "recent_count": recent_count,
                "first_seen": first_seen,
                "last_seen": latest.get("signal_date"),
                "previous_seen": previous_seen,
                "best_grade": _best_grade([str(signal.get("grade") or "") for signal in signals]),
                "best_score": max(int(signal.get("total_score") or 0) for signal in signals),
                "completed": len([signal for signal in signals if signal.get("return_5d") is not None]),
                "avg_return_5d": _avg([signal.get("return_5d") for signal in signals]),
                "stability_label": label,
                "stability_reason": _stability_reason(label, recent_count, first_seen, previous_seen),
            }
            by_stock[stock_id] = item
            rows_out.append(item)

        rows_out.sort(
            key=lambda item: (
                bool(item.get("active_today")),
                int(item.get("recent_count") or 0),
                int(item.get("best_score") or 0),
            ),
            reverse=True,
        )
        return {
            "as_of": as_of.isoformat(),
            "days": days,
            "by_stock": by_stock,
            "top": rows_out[:12],
            "summary": {
                "tracked": len(rows_out),
                "active_today": len([item for item in rows_out if item.get("active_today")]),
                "repeat_today": len([
                    item for item in rows_out
                    if item.get("active_today") and int(item.get("recent_count") or 0) >= 2
                ]),
            },
        }

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

    def save_theme_discovery(self, candidates: list[dict], as_of: date) -> None:
        """Persist emerging theme candidates for review and later validation."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM theme_discovery_candidates WHERE discovery_date = ?",
                (as_of.isoformat(),),
            )
            for item in candidates:
                keyword = str(item.get("keyword") or "").strip()
                if not keyword:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO theme_discovery_candidates
                        (discovery_date, keyword, score, mentions, stock_hits_json, headlines_json, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        as_of.isoformat(),
                        keyword,
                        int(item.get("score") or 0),
                        int(item.get("mentions") or 0),
                        json.dumps(item.get("stock_hits") or [], ensure_ascii=False),
                        json.dumps(item.get("headlines") or [], ensure_ascii=False),
                        str(item.get("status") or "觀察中"),
                    ),
                )

    def theme_discovery_summary(self, as_of: date, days: int = 7, limit: int = 12) -> dict:
        """Return recent emerging theme candidates, grouped by keyword."""
        since = (as_of - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT discovery_date, keyword, score, mentions, stock_hits_json, headlines_json, status
                FROM theme_discovery_candidates
                WHERE discovery_date >= ?
                ORDER BY discovery_date DESC, score DESC, mentions DESC
                """,
                (since,),
            ).fetchall()

        by_keyword: dict[str, dict] = {}
        for discovery_date, keyword, score, mentions, stock_hits_json, headlines_json, status in rows:
            item = by_keyword.setdefault(
                keyword,
                {
                    "keyword": keyword,
                    "latest_date": discovery_date,
                    "days": 0,
                    "total_score": 0,
                    "total_mentions": 0,
                    "stock_hits": [],
                    "headlines": [],
                    "status": status or "觀察中",
                },
            )
            item["days"] += 1
            item["total_score"] += int(score or 0)
            item["total_mentions"] += int(mentions or 0)
            for hit in json.loads(stock_hits_json or "[]"):
                if hit not in item["stock_hits"]:
                    item["stock_hits"].append(hit)
            for headline in json.loads(headlines_json or "[]"):
                if headline not in item["headlines"]:
                    item["headlines"].append(headline)

        candidates = sorted(
            by_keyword.values(),
            key=lambda item: (item["days"], item["total_score"], item["total_mentions"], item["keyword"]),
            reverse=True,
        )[:limit]
        return {
            "as_of": as_of.isoformat(),
            "days": days,
            "candidates": candidates,
        }

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


def _mfe_return(rows: list[tuple], entry: float | None) -> float | None:
    if not rows or not entry:
        return None
    highs = [float(row[3]) for row in rows if len(row) > 3 and row[3] is not None]
    if not highs:
        return None
    return _pct_return(max(highs), entry)


def _mae_return(rows: list[tuple], entry: float | None) -> float | None:
    if not rows or not entry:
        return None
    lows = [float(row[2]) for row in rows if len(row) > 2 and row[2] is not None]
    if not lows:
        return None
    return _pct_return(min(lows), entry)


def _nth_trading_close(rows: list[tuple], n: int) -> float | None:
    if len(rows) < n:
        return None
    value = rows[n - 1][1]
    return float(value) if value is not None else None


def datetime_column_to_date(values) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def _safe_float(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _best_grade(grades: list[str]) -> str:
    order = {"S+": 0, "S": 1, "A": 2, "B": 3, "C": 4}
    usable = [grade for grade in grades if grade]
    if not usable:
        return ""
    return sorted(usable, key=lambda grade: order.get(grade, 99))[0]


def _stability_label(recent_count: int, active_today: bool) -> str:
    if not active_today:
        return "近期曾入選"
    if recent_count >= 3:
        return "連續追蹤"
    if recent_count == 2:
        return "再次入選"
    return "新進名單"


def _stability_reason(label: str, recent_count: int, first_seen, previous_seen) -> str:
    if label == "連續追蹤":
        return f"近 10 天出現 {recent_count} 次，訊號有延續性。"
    if label == "再次入選":
        return f"上次入選日 {previous_seen or '-'}，今日重新轉強。"
    if label == "新進名單":
        return "今日首次進入近期觀察，先看開盤是否確認。"
    return f"曾於 {first_seen or '-'} 入選，今日未必仍在操作清單。"


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


def _guardrail_stats(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        for tag in item.get("guardrail_tags") or []:
            buckets.setdefault(str(tag), []).append(item)

    rows: list[dict] = []
    for tag, bucket in buckets.items():
        completed = [item for item in bucket if item.get("return_5d") is not None]
        stop_known = [item for item in bucket if item.get("stop_hit") is not None]
        rows.append(
            {
                "tag": tag,
                "signals": len(bucket),
                "completed": len(completed),
                "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
                "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
                "stop_hit_rate": _rate([item.get("stop_hit") for item in stop_known]),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["signals"] or 0), str(row["tag"])))


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


def _signal_attribution_center(watch_items: list[dict], potential_radar: dict, ai_council: dict) -> dict:
    potential_items = list((potential_radar or {}).get("items") or [])
    ai_stats = (ai_council or {}).get("stats") or {}
    rows = [
        _attribution_source_row("watch", "今日操作訊號", watch_items, note="正式進場訊號，追蹤 3/5/10 日表現。"),
        _attribution_source_row("potential", "潛力雷達", potential_items, note="尚未進場的提前觀察名單。"),
        {
            "key": "ai_council",
            "label": "AI 複核",
            "signals": ai_stats.get("signals", 0),
            "completed": ai_stats.get("completed", 0),
            "win_rate_5d": ai_stats.get("win_rate_5d"),
            "avg_return_5d": ai_stats.get("avg_return_5d"),
            "avg_return_10d": ai_stats.get("avg_return_10d"),
            "success_count": ai_stats.get("wins_5d", 0),
            "failure_count": ai_stats.get("losses_5d", 0),
            "pending_count": max(int(ai_stats.get("signals") or 0) - int(ai_stats.get("completed") or 0), 0),
            "note": "AI 只做複核與註記，不直接加分。",
        },
    ]
    factor_rows = _factor_attribution_rows(watch_items, potential_items)
    return {
        "summary_rows": rows,
        "factor_rows": factor_rows,
        "best_factor": factor_rows[0] if factor_rows else None,
        "weak_factor": _weak_factor(factor_rows),
        "notes": [
            "成功/失敗歸因會回寫績效頁與知識庫，用來校準下一輪篩選。",
            "樣本不足時只做觀察，不自動改變核心分數。",
        ],
    }


def _attribution_source_row(key: str, label: str, items: list[dict], note: str) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    success = [item for item in completed if float(item.get("return_5d") or 0) > 0]
    failure = [item for item in completed if float(item.get("return_5d") or 0) <= 0]
    return {
        "key": key,
        "label": label,
        "signals": len(items),
        "completed": len(completed),
        "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
        "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
        "avg_return_10d": _avg([item.get("return_10d") for item in items if item.get("return_10d") is not None]),
        "success_count": len(success),
        "failure_count": len(failure),
        "pending_count": len(items) - len(completed),
        "sample_label": _sample_label(len(completed)),
        "note": note,
    }


def _factor_attribution_rows(watch_items: list[dict], potential_items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in watch_items:
        for tag in _watch_factor_tags(item):
            buckets.setdefault(tag, []).append(item)
    for item in potential_items:
        for tag in _potential_factor_tags(item):
            buckets.setdefault(tag, []).append(item)
    rows = []
    for label, bucket in buckets.items():
        completed = [item for item in bucket if item.get("return_5d") is not None]
        if not bucket:
            continue
        rows.append(
            {
                "label": label,
                "signals": len(bucket),
                "completed": len(completed),
                "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
                "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
                "sample_label": _sample_label(len(completed)),
            }
        )
    return sorted(rows, key=lambda row: (-(row.get("completed") or 0), -(row.get("avg_return_5d") or -999), str(row.get("label") or "")))


def _watch_factor_tags(item: dict) -> list[str]:
    tags = [str(tag) for tag in item.get("guardrail_tags") or [] if tag]
    text = _item_text(item)
    if item.get("grade") in {"S+", "S"}:
        tags.append("高強度")
    if item.get("entry_triggered") is True:
        tags.append("進場觸發")
    elif item.get("entry_triggered") is False:
        tags.append("進場未觸發")
    if "等拉回" in str(item.get("action") or ""):
        tags.append("等拉回")
    if item.get("stop_hit") is True:
        tags.append("停損觸發")
    if "法人" in text or "外資" in text or "投信" in text:
        tags.append("法人籌碼")
    if "營收" in text:
        tags.append("營收支撐")
    if "散戶" in text:
        tags.append("散戶籌碼")
    return _dedupe(tags)


def _potential_factor_tags(item: dict) -> list[str]:
    tags = [str(tag) for tag in item.get("tags") or [] if tag]
    for field in ("stage_label", "radar_layer_label", "lifecycle_stage_label", "smart_money_label", "stock_type_label", "research_label"):
        value = str(item.get(field) or "")
        if value:
            tags.append(value)
    return _dedupe([_potential_factor_label(tag) for tag in tags])


def _weak_factor(rows: list[dict]) -> dict | None:
    completed = [row for row in rows if int(row.get("completed") or 0) > 0]
    if not completed:
        return None
    return sorted(completed, key=lambda row: (float(row.get("avg_return_5d") or 0), float(row.get("win_rate_5d") or 0)))[0]


def _theme_stats(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        themes = item.get("themes") or ["未標記"]
        for theme in themes:
            buckets.setdefault(str(theme), []).append(item)
    return [_bucket_stats(label, bucket) for label, bucket in sorted(buckets.items())]


def _action_stats(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        buckets.setdefault(str(item.get("action") or "未標記"), []).append(item)
    return [_bucket_stats(label, bucket) for label, bucket in sorted(buckets.items())]


def _top_buckets(rows: list[dict], min_completed: int = 1, limit: int = 5) -> list[dict]:
    candidates = [row for row in rows if int(row.get("completed") or 0) >= min_completed]
    return sorted(candidates, key=lambda row: (float(row.get("avg_return_5d") or -999), float(row.get("win_rate_5d") or 0)), reverse=True)[:limit]


def _leaderboard(items: list[dict], limit: int = 8) -> list[dict]:
    completed = [item for item in items if item.get("return_5d") is not None]
    return sorted(completed, key=lambda item: float(item.get("return_5d") or 0), reverse=True)[:limit]


def _postmortem_item(item: dict) -> dict:
    ret5 = item.get("return_5d")
    if ret5 is None:
        return {"outcome_category": "pending", "outcome_label": "觀察中", "lesson_tags": ["尚未到期"], "lesson": "等待 5 日結果。"}
    if item.get("entry_triggered") is False and float(ret5) >= 8:
        return {"outcome_category": "missed_opportunity", "outcome_label": "錯過機會", "lesson_tags": _watch_factor_tags(item), "lesson": "未觸發進場但後續上漲，需檢討進場條件是否過嚴。"}
    if float(ret5) >= 8:
        return {"outcome_category": "big_winner", "outcome_label": "大漲成功", "lesson_tags": _watch_factor_tags(item), "lesson": "訊號後 5 日強勢上漲，保留有效因子。"}
    if float(ret5) > 0:
        return {"outcome_category": "true_positive", "outcome_label": "成功", "lesson_tags": _watch_factor_tags(item), "lesson": "訊號後 5 日為正報酬。"}
    if item.get("stop_hit") is True:
        return {"outcome_category": "stop_loss", "outcome_label": "停損", "lesson_tags": _failure_reason_tags(item), "lesson": "訊號後觸及停損，需檢討進場條件與風險。"}
    return {"outcome_category": "false_positive", "outcome_label": "失敗", "lesson_tags": _failure_reason_tags(item), "lesson": _failure_lesson(_failure_reason_tags(item)[0])}


def _postmortem_summary(items: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        category = str(item.get("outcome_category") or "pending")
        counts[category] = counts.get(category, 0) + 1
    completed = [item for item in items if item.get("return_5d") is not None]
    failures = [item for item in completed if float(item.get("return_5d") or 0) <= 0]
    successes = [item for item in completed if float(item.get("return_5d") or 0) > 0]
    missed = [item for item in completed if item.get("outcome_category") == "missed_opportunity"]
    return {
        "sample": len(completed),
        "counts": [{"category": key, "count": value} for key, value in sorted(counts.items())],
        "success_cases": sorted(successes, key=lambda item: float(item.get("return_5d") or 0), reverse=True)[:8],
        "failure_cases": sorted(failures, key=lambda item: float(item.get("return_5d") or 0))[:8],
        "missed_opportunities": sorted(missed, key=lambda item: float(item.get("return_5d") or 0), reverse=True)[:8],
        "missed_cases": sorted(missed, key=lambda item: float(item.get("return_5d") or 0), reverse=True)[:8],
        "failure_attribution": _failure_attribution_summary(failures),
        "notes": _failure_attribution_notes(_failure_attribution_summary(failures)),
    }


def _item_text(item: dict) -> str:
    values = []
    for key in ("action", "reason", "outcome_reason", "trigger_summary", "guardrail_notes", "guardrail_tags", "tags", "themes"):
        value = item.get(key)
        if isinstance(value, list):
            values.extend(str(v) for v in value)
        else:
            values.append(str(value or ""))
    return " ".join(values)


def _failure_reason_tags(item: dict) -> list[str]:
    text = _item_text(item)
    tags: list[str] = []
    if "追高" in text or "過熱" in text or "高乖離" in text:
        tags.append("追價過熱")
    if "進場未觸發" in text:
        tags.append("進場未觸發")
    if "法人賣" in text or "外資賣" in text or "融資增" in text:
        tags.append("籌碼轉弱")
    if "散戶過熱" in text:
        tags.append("散戶過熱")
    if "題材" in text and "營收" not in text:
        tags.append("題材缺實績")
    if item.get("stop_hit") is True:
        tags.append("停損觸發")
    if item.get("return_5d") is not None and float(item.get("return_5d") or 0) <= 0:
        tags.append("進場後轉弱")
    return _dedupe(tags) or ["未分類失敗"]


def _failure_attribution_summary(items: list[dict], limit: int = 8) -> dict:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        for tag in _failure_reason_tags(item):
            buckets.setdefault(tag, []).append(item)
    rows = []
    for label, bucket in buckets.items():
        rows.append(
            {
                "label": label,
                "count": len(bucket),
                "avg_return_5d": _avg([item.get("return_5d") for item in bucket]),
                "lesson": _failure_lesson(label),
            }
        )
    rows.sort(key=lambda row: (-int(row.get("count") or 0), float(row.get("avg_return_5d") or 0)))
    return {"sample": len(items), "rows": rows[:limit], "top": rows[0] if rows else None}


def _failure_lesson(label: str) -> str:
    lessons = {
        "追價過熱": "追價訊號需要降權，開盤跳空或高乖離時改等拉回。",
        "進場未觸發": "條件未觸發仍需等待，不應因分數高提前進場。",
        "籌碼轉弱": "法人賣超、融資增加時提高危險權重。",
        "散戶過熱": "散戶增加但股價不漲，應列入避險觀察。",
        "題材缺實績": "題材若缺營收或供應鏈證據，不應單獨升級。",
        "停損觸發": "停損有效，需檢討是否進場太晚或波動過大。",
    }
    return lessons.get(label, "樣本仍需累積，先保留觀察。")


def _failure_attribution_notes(summary: dict) -> list[str]:
    rows = summary.get("rows") or []
    if not rows:
        return ["尚無足夠失敗樣本可歸因。"]
    top = rows[0]
    return [f"主要失敗因子：{top['label']}（{top['count']} 筆）。", top.get("lesson") or "請持續觀察。"]


def _annotate_potential_promotions(conn, items: list[dict]) -> None:
    for item in items:
        row = conn.execute(
            """
            SELECT MIN(signal_date), COUNT(*)
            FROM watch_signals
            WHERE stock_id = ? AND signal_date > ?
            """,
            (item.get("stock_id"), item.get("signal_date")),
        ).fetchone()
        item["promoted_date"] = row[0] if row and row[0] else None
        item["promoted_count"] = row[1] if row and row[1] else 0
        if item["promoted_date"]:
            item["promotion_label"] = "已轉強"
            continue
        row = conn.execute(
            """
            SELECT MIN(as_of_date), COUNT(*)
            FROM daily_scores
            WHERE stock_id = ?
              AND as_of_date > ?
              AND label = 'BUY_WATCH'
            """,
            (item.get("stock_id"), item.get("signal_date")),
        ).fetchone()
        item["promoted_date"] = row[0] if row and row[0] else None
        item["promoted_count"] = row[1] if row and row[1] else 0
        item["promotion_label"] = "已轉強" if item["promoted_date"] else "觀察中"


def _potential_occurrence_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        sid = str(item.get("stock_id") or "")
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def _with_potential_occurrence(item: dict, occurrence_counts: dict[str, int]) -> dict:
    row = dict(item)
    row["occurrence_count"] = occurrence_counts.get(str(item.get("stock_id") or ""), 0)
    try:
        if row.get("promoted_date") and row.get("signal_date"):
            days = (date.fromisoformat(str(row["promoted_date"])) - date.fromisoformat(str(row["signal_date"]))).days
            row["days_to_promotion"] = days + 1 if days >= 0 else days
        else:
            row["days_to_promotion"] = None
    except ValueError:
        row["days_to_promotion"] = None
    return row


def _unique_potential_items(items: list[dict], occurrence_counts: dict[str, int], *, key_func, reverse: bool, limit: int) -> list[dict]:
    sorted_items = sorted(items, key=key_func, reverse=reverse)
    result = []
    seen = set()
    for item in sorted_items:
        sid = str(item.get("stock_id") or "")
        if sid in seen:
            continue
        seen.add(sid)
        result.append(_with_potential_occurrence(item, occurrence_counts))
        if len(result) >= limit:
            break
    return result


def _potential_promotion_funnel(items: list[dict], occurrence_counts: dict[str, int]) -> dict:
    promoted = [item for item in items if item.get("promoted_date")]
    completed = [item for item in items if item.get("return_5d") is not None]
    examples = _unique_potential_items(
        promoted,
        occurrence_counts,
        key_func=lambda item: (
            item.get("promoted_date") or "",
            int(item.get("potential_score") or 0),
            int(item.get("total_score") or 0),
        ),
        reverse=True,
        limit=8,
    )
    return {
        "signals": len(items),
        "promoted": len(promoted),
        "promotion_rate": _rate([True for _ in promoted] + [False for _ in range(max(len(items) - len(promoted), 0))]),
        "avg_days_to_promote": _avg([item.get("promoted_count") for item in promoted]),
        "completed": len(completed),
        "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
        "examples": examples,
    }


def _factor_row(label: str, items: list[dict], reason: str) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    success = [
        item for item in completed
        if str(item.get("outcome_category") or "") in {"potential_big_winner", "potential_success", "big_winner", "true_positive"}
        or float(item.get("return_5d") or 0) > 0
    ]
    failure = [item for item in completed if item not in success]
    return {
        "label": label,
        "signals": len(items),
        "completed": len(completed),
        "success_count": len(success),
        "failure_count": len(failure),
        "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
        "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
        "reason": reason,
        "sample_label": _sample_label(len(completed)),
    }


def _top_factor_rows(factors: list[dict], *, reverse: bool, limit: int = 6) -> list[dict]:
    completed = [row for row in factors if int(row.get("completed") or 0) > 0]
    return sorted(completed, key=lambda row: (float(row.get("avg_return_5d") or 0), float(row.get("win_rate_5d") or 0)), reverse=reverse)[:limit]


def _potential_factor_stats(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        for tag in _potential_factor_tags(item):
            buckets.setdefault(tag, []).append(item)
    return sorted((_factor_row(label, bucket, "潛力雷達因子成效") for label, bucket in buckets.items()), key=lambda row: (-int(row.get("signals") or 0), str(row.get("label") or "")))


def _potential_stage_stats(items: list[dict]) -> list[dict]:
    return _potential_bucket_stats(items, "stage_label", "潛力階段")


def _potential_bucket_stats(items: list[dict], field: str, fallback: str, limit: int = 8) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        label = str(item.get(field) or fallback)
        buckets.setdefault(label, []).append(item)
    rows = [_factor_row(label, bucket, fallback) for label, bucket in buckets.items()]
    return sorted(rows, key=lambda row: (-int(row.get("signals") or 0), str(row.get("label") or "")))[:limit]


def _potential_factor_label(tag: str) -> str:
    if tag.startswith("題材升溫:"):
        return "題材升溫"
    for prefix in ("成效降權:", "回測偏弱:", "K線型態:", "K線轉強:", "K線風險:", "題材:", "生命週期:", "資金同步:", "訊號組合:", "組合:", "研究:", "類型:", "部位:", "階段:"):
        if tag.startswith(prefix):
            return tag.split(":", 1)[1]
    return tag


def _rank_potential_factors(factors: list[dict], *, reverse: bool, limit: int = 6) -> list[dict]:
    return _top_factor_rows(factors, reverse=reverse, limit=limit)


def _potential_factor_notes(factors: list[dict]) -> list[str]:
    strong = _top_factor_rows(factors, reverse=True, limit=1)
    weak = _top_factor_rows(factors, reverse=False, limit=1)
    notes = []
    if strong:
        notes.append(f"目前較有效因子：{strong[0]['label']}，5日平均 {_fmt_pct(strong[0].get('avg_return_5d'))}。")
    if weak:
        notes.append(f"需要降權觀察：{weak[0]['label']}，5日平均 {_fmt_pct(weak[0].get('avg_return_5d'))}。")
    return notes or ["潛力雷達仍在累積樣本。"]


def _potential_candidate(item: dict) -> dict:
    return {
        "stock_id": item.get("stock_id"),
        "name": item.get("name"),
        "stage": item.get("stage_label"),
        "score": item.get("potential_score"),
        "reason": item.get("reason"),
        "tags": item.get("tags") or [],
    }


def _infer_potential_stage(potential_score, total_score, grade, tags: list | None) -> dict[str, str]:
    text = " ".join(str(tag) for tag in (tags or []))
    if "等拉回" in text:
        return {"key": "pullback_watch", "label": "強勢等拉回"}
    if int(potential_score or 0) >= 10 or str(grade or "") in {"S", "A"}:
        return {"key": "early_turn", "label": "轉強初動"}
    if int(total_score or 0) >= 75:
        return {"key": "wait_cooldown", "label": "等待降溫"}
    return {"key": "low_base", "label": "低位醞釀"}


def _infer_radar_layer(stage, lifecycle_stage, smart_money, total_score, grade, potential_score) -> dict[str, str]:
    if stage == "pullback_watch" or smart_money == "sync" or int(potential_score or 0) >= 10:
        return {"key": "confirmed_wait", "label": "確認等待"}
    if lifecycle_stage == "extended" or int(total_score or 0) >= 90 or str(grade or "") in {"S+", "S"}:
        return {"key": "extended_watch", "label": "延伸觀察"}
    return {"key": "early_potential", "label": "早期潛力"}


def _potential_outcome(return_5d: float | None, return_10d: float | None, tags: list[str] | None = None) -> dict:
    if return_5d is None:
        return {"category": "pending", "label": "觀察中", "reason": "等待 5 日結果。"}
    best = max(float(return_5d or 0), float(return_10d or return_5d or 0))
    if best >= 8:
        return {"category": "potential_big_winner", "label": "提前命中飆股", "reason": "潛力雷達提前抓到後續強勢股。"}
    if float(return_5d or 0) > 0:
        return {"category": "potential_success", "label": "成功轉強", "reason": "5 日後為正報酬，早期觀察有效。"}
    return {"category": "potential_false_positive", "label": "未轉強", "reason": _potential_failure_reason(tags or [])}


def _knowledge_outcome(
    return_5d: float | None,
    blocked: bool | None = None,
    adjustment: int | float | None = None,
    *,
    original_action: str = "",
    adjusted_action: str = "",
    negative_matches: list | None = None,
    positive_matches: list | None = None,
) -> dict:
    if return_5d is None:
        return {"category": "pending", "label": "觀察中", "reason": "等待 5 日結果。"}
    adj = float(adjustment or 0)
    if blocked is None:
        blocked = bool(negative_matches) or (original_action and adjusted_action and original_action != adjusted_action)
    if blocked and float(return_5d or 0) <= 0:
        return {"category": "knowledge_protected", "label": "知識庫保護成功", "reason": "知識庫降權後標的走弱。"}
    if blocked and float(return_5d or 0) > 0:
        return {"category": "knowledge_too_strict", "label": "知識庫過度保守", "reason": "知識庫降權但標的上漲，需重新校準。"}
    if (adj > 0 or positive_matches) and float(return_5d or 0) > 0:
        return {"category": "knowledge_helped", "label": "知識庫加分有效", "reason": "知識庫加分後標的上漲。"}
    if (adj > 0 or positive_matches) and float(return_5d or 0) <= 0:
        return {"category": "knowledge_misled", "label": "知識庫加分失效", "reason": "知識庫加分但標的走弱。"}
    return {"category": "knowledge_neutral", "label": "中性", "reason": "知識庫影響有限。"}


def _potential_failure_reason(tags: list[str]) -> str:
    text = " ".join(tags)
    if "追價" in text or "成熟" in text:
        return "偏成熟或追價風險，未能延續。"
    if "題材" in text and "法人" not in text:
        return "題材有熱度但缺少資金同步。"
    if "散戶過熱" in text:
        return "散戶過熱壓抑後續漲幅。"
    return "條件未能轉成實際買盤，繼續觀察樣本。"


def _exit_risk_outcome(return_5d: float | None) -> str:
    if return_5d is None:
        return "觀察中"
    value = float(return_5d or 0)
    if value <= -5:
        return "strong_true_warning"
    if value < 0:
        return "true_warning"
    return "false_warning"


def _fmt_pct(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "-"


def _json_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _dedupe(items: list[str]) -> list[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _learning_center_summary(items: list[dict]) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    failures = [item for item in completed if float(item.get("return_5d") or 0) <= 0]
    successes = [item for item in completed if float(item.get("return_5d") or 0) > 0]
    potential_candidates = [
        {
            "signal_date": item.get("signal_date"),
            "stock_id": item.get("stock_id"),
            "name": item.get("name"),
            "grade": item.get("grade"),
            "total_score": item.get("total_score"),
            "action": item.get("action") or "觀察",
            "entry_price": item.get("entry_price"),
            "tags": _dedupe(["分數已成形", *_watch_factor_tags(item)]),
            "themes": item.get("themes") or [],
            "reason": "尚未完成 5 日驗證，先列入潛力觀察。",
        }
        for item in items
        if item.get("return_5d") is None and item.get("total_score") is not None and int(item.get("total_score") or 0) >= 75
    ][:12]
    return {
        "completed": len(completed),
        "failure_count": len(failures),
        "failure_rate": _rate([float(item.get("return_5d") or 0) <= 0 for item in completed]),
        "success_factors": _factor_summary_from_items(successes, _watch_factor_tags, limit=6),
        "failure_factors": _factor_summary_from_items(failures, _learning_failure_tags, limit=6),
        "top_failure_tags": (_failure_attribution_summary(failures).get("rows") or [])[:5],
        "potential_candidates": potential_candidates,
    }


def _factor_summary_from_items(items: list[dict], tag_func, limit: int = 6) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        for tag in tag_func(item):
            buckets.setdefault(tag, []).append(item)
    rows = [
        {
            "label": label,
            "count": len(bucket),
            "avg_return_5d": _avg([item.get("return_5d") for item in bucket]),
        }
        for label, bucket in buckets.items()
    ]
    rows.sort(key=lambda row: (-int(row.get("count") or 0), float(row.get("avg_return_5d") or 0)))
    return rows[:limit]


def _learning_failure_tags(item: dict) -> list[str]:
    tags = _failure_reason_tags(item)
    if int(item.get("total_score") or 0) >= 90:
        tags.append("高分失敗")
    return _dedupe(tags)


def _return_status_code(signal_date: str, return_5d: float | None, as_of: date, horizon_days: int = 5) -> str:
    if return_5d is not None:
        return "completed_5d"
    try:
        start = date.fromisoformat(str(signal_date))
    except ValueError:
        return "data_missing"
    return "pending_5d" if (as_of - start).days < horizon_days + 4 else "data_missing"


def _performance_data_quality(items: list[dict]) -> dict:
    missing = [item for item in items if item.get("status_code") == "data_missing"]
    pending = [item for item in items if item.get("status_code") == "pending_5d"]
    completed = [item for item in items if item.get("status_code") == "completed_5d"]
    total = len(items)
    coverage = round(len(completed) / total * 100, 1) if total else 100.0
    return {
        "label": "高" if coverage >= 80 else "中" if coverage >= 50 else "偏低",
        "coverage": coverage,
        "completion_rate_5d": coverage,
        "status_counts": {
            "completed_5d": len(completed),
            "pending_5d": len(pending),
            "data_missing": len(missing),
        },
        "missing": len(missing),
        "pending": len(pending),
        "completed": len(completed),
        "pending_examples": _pending_examples(pending),
        "missing_examples": _pending_examples(missing),
    }


def _pending_examples(items: list[dict], limit: int = 8) -> list[dict]:
    return [{"stock_id": item.get("stock_id"), "name": item.get("name"), "signal_date": item.get("signal_date")} for item in items[:limit]]


def _backtest_insights(items: list[dict]) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    candidates = _leaderboard(items, limit=5)
    weak = sorted(completed, key=lambda item: float(item.get("return_5d") or 0))[:5]
    best_segments = []
    if completed:
        best_segments.append(
            {
                "label": "整體完成樣本",
                "completed": len(completed),
                "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
                "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
            }
        )
    return {"sample": len(completed), "candidates": candidates, "weak": weak, "best_segments": best_segments, "notes": _backtest_notes(completed, candidates, weak)}


def _backtest_notes(completed: list[dict], candidates: list[dict], weak: list[dict]) -> list[str]:
    if not completed:
        return ["尚無完成樣本，先累積資料。"]
    notes = [f"已完成 {len(completed)} 筆，5 日勝率 {_fmt_pct(_rate([item.get('return_5d') > 0 for item in completed]))}。"]
    if candidates:
        notes.append(f"近期最佳樣本：{candidates[0].get('stock_id')} {candidates[0].get('name')}，5日 {_fmt_pct(candidates[0].get('return_5d'))}。")
    if weak:
        notes.append(f"近期最弱樣本：{weak[0].get('stock_id')} {weak[0].get('name')}，5日 {_fmt_pct(weak[0].get('return_5d'))}。")
    return notes


def _low_win_rate_breakdown(items: list[dict], *, theme_stats: list[dict], action_stats: list[dict], score_bands: list[dict], entry_analysis: dict, factor_rows: list[dict], target_win_rate: float = 50.0) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    overall_win_rate = _rate([item.get("return_5d") > 0 for item in completed])
    overall_avg = _avg([item.get("return_5d") for item in completed])
    weak_rows = []
    for group, rows in [("題材", theme_stats), ("進場條件", action_stats), ("強度", score_bands), ("因子", factor_rows)]:
        for row in rows:
            if int(row.get("completed") or 0) <= 0:
                continue
            avg = float(row.get("avg_return_5d") or 0)
            win = row.get("win_rate_5d")
            if (win is not None and float(win) < target_win_rate) or avg < 0:
                weak_rows.append({
                    "group": group,
                    "label": row.get("label") or row.get("band") or row.get("tag"),
                    "completed": row.get("completed"),
                    "win_rate_5d": win,
                    "avg_return_5d": row.get("avg_return_5d"),
                    "diagnosis": _low_win_rate_diagnosis(group, str(row.get("label") or ""), avg),
                    "action": _low_win_rate_action(group, str(row.get("label") or "")),
                    "recommended_action": _low_win_rate_action(group, str(row.get("label") or "")),
                })
    weak_rows.sort(key=lambda row: (float(row.get("avg_return_5d") or 0), float(row.get("win_rate_5d") or 0)))
    return {
        "sample": len(completed),
        "is_below_target": overall_win_rate is not None and float(overall_win_rate) < target_win_rate,
        "overall_win_rate": overall_win_rate,
        "overall_avg_return_5d": overall_avg,
        "target_win_rate": target_win_rate,
        "target_win_rate_5d": target_win_rate,
        "weak_rows": weak_rows[:10],
        "rows": weak_rows[:10],
        "top_drag": weak_rows[0] if weak_rows else None,
        "notes": _low_win_rate_notes(overall_win_rate, overall_avg, weak_rows, target_win_rate),
    }


def _low_win_rate_diagnosis(group: str, label: str, avg_return: float) -> str:
    if "追" in label or "可追" in label:
        return "可能追價過急，應增加開盤量價確認。"
    if group == "題材":
        return "題材熱度未轉為實際買盤或營收證據不足。"
    if group == "因子":
        return "此因子近期失效，需降權觀察。"
    if avg_return < -3:
        return "平均虧損偏大，需加強停損或過熱防護。"
    return "樣本偏弱，先列入週檢討。"


def _low_win_rate_action(group: str, label: str) -> str:
    if "追" in label:
        return "提高進場門檻，開盤未放量不追。"
    if group in {"題材", "因子"}:
        return "降權至樣本回升。"
    return "保留觀察，等待更多樣本。"


def _low_win_rate_notes(overall_win_rate, overall_avg, rows: list[dict], target_win_rate: float) -> list[str]:
    notes = []
    if overall_win_rate is None:
        notes.append("尚無足夠完成樣本。")
    elif float(overall_win_rate) < target_win_rate:
        notes.append(f"整體 5 日勝率低於 {target_win_rate:.0f}%，需要檢討追價與弱題材。")
    if overall_avg is not None and float(overall_avg) < 0:
        notes.append("整體 5 日平均報酬為負，優先降低高風險訊號。")
    if rows:
        notes.append(f"最弱區塊：{rows[0].get('group')} / {rows[0].get('label')}。")
    return notes or ["目前勝率未低於警戒門檻。"]


def _segment_summary(row: dict | None, label_key: str = "label") -> dict | None:
    if not row:
        return None
    return {
        "label": row.get(label_key) or row.get("label"),
        "completed": row.get("completed"),
        "win_rate_5d": row.get("win_rate_5d"),
        "avg_return_5d": row.get("avg_return_5d"),
        "sample_label": _sample_label(int(row.get("completed") or 0)),
    }


def _best_segment(rows: list[dict], label_key: str = "label", min_completed: int = 1) -> dict | None:
    candidates = [row for row in rows if int(row.get("completed") or 0) >= min_completed]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (float(row.get("avg_return_5d") or -999), float(row.get("win_rate_5d") or 0)), reverse=True)[0]


def _weak_segment(rows: list[dict], label_key: str = "label", min_completed: int = 1) -> dict | None:
    candidates = [row for row in rows if int(row.get("completed") or 0) >= min_completed]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (float(row.get("avg_return_5d") or 999), float(row.get("win_rate_5d") or 100)))[0]


def _sample_label(completed: int) -> str:
    if completed >= 60:
        return "可校準"
    if completed >= 30:
        return "樣本充足"
    if completed >= 10:
        return "觀察中"
    return "樣本不足"


def _sample_note(completed: int) -> str:
    return f"完成樣本 {completed} 筆，{_sample_label(completed)}。"


def _exit_risk_sample_label(completed: int) -> str:
    if completed <= 0:
        return "樣本不足"
    if completed < 10:
        return "累積中"
    return _sample_label(completed)


def _selection_quality_overview(items: list[dict], *, theme_stats: list[dict], action_stats: list[dict], score_bands: list[dict], ai_council: dict) -> dict:
    completed = [item for item in items if item.get("return_5d") is not None]
    return {
        "signals": len(items),
        "completed_5d": len(completed),
        "sample_label": "樣本不足" if len(completed) < 10 else _sample_label(len(completed)),
        "win_rate_5d": _rate([item.get("return_5d") > 0 for item in completed]),
        "avg_return_5d": _avg([item.get("return_5d") for item in completed]),
        "best_theme": _segment_summary(_best_segment(theme_stats)),
        "weak_theme": _segment_summary(_weak_segment(theme_stats)),
        "best_action": _segment_summary(_best_segment(action_stats)),
        "weak_action": _segment_summary(_weak_segment(action_stats)),
        "best_score_band": _segment_summary(_best_segment(score_bands)),
        "weak_score_band": _segment_summary(_weak_segment(score_bands)),
        "ai_council": ai_council,
        "notes": ["分級只是訊號強度，不等於可買；實際決策以今日操作結論與開盤條件為準。"],
    }


def _calibration_row(group: str, row: dict, label_key: str = "label") -> dict | None:
    if not row or int(row.get("completed") or 0) <= 0:
        return None
    completed = int(row.get("completed") or 0)
    avg = float(row.get("avg_return_5d") or 0)
    win = row.get("win_rate_5d")
    priority = "加權觀察" if avg > 0 and (win is None or float(win) >= 50) else "降權觀察" if avg < 0 or (win is not None and float(win) < 45) else "維持觀察"
    return {"group": group, "label": row.get(label_key) or row.get("label"), "completed": completed, "win_rate_5d": win, "avg_return_5d": row.get("avg_return_5d"), "priority": priority, "sample_label": _sample_label(completed)}


def _calibration_advice(grade_rows: list[dict], action_rows: list[dict], theme_rows: list[dict], limit: int = 8) -> list[dict]:
    rows = []
    for group, source in [("分級", grade_rows), ("操作", action_rows), ("題材", theme_rows)]:
        for row in source:
            item = _calibration_row(group, row)
            if item:
                rows.append(item)
    rows.sort(key=lambda row: ({"降權觀察": 0, "維持觀察": 1, "加權觀察": 2}.get(row["priority"], 1), -int(row["completed"])))
    return rows[:limit]


def _adaptive_feedback(postmortem: dict, potential_radar: dict, signal_attribution: dict, calibration_advice: list[dict], limit: int = 8) -> list[dict]:
    feedback = []
    for row in (postmortem.get("failure_attribution") or {}).get("rows", [])[:3]:
        feedback.append({"priority": "high", "source": "失敗歸因", "target": row.get("label"), "sample": row.get("count"), "avg_return_5d": row.get("avg_return_5d"), "action": "提高風險權重", "reason": row.get("lesson")})
    for row in calibration_advice[:3]:
        feedback.append({"priority": "medium", "source": "校準建議", "target": f"{row.get('group')}:{row.get('label')}", "sample": row.get("completed"), "avg_return_5d": row.get("avg_return_5d"), "action": row.get("priority"), "reason": "依近期 5 日績效調整觀察權重。"})
    weak_factor = (signal_attribution or {}).get("weak_factor")
    if weak_factor:
        feedback.append({"priority": "medium", "source": "訊號因子", "target": weak_factor.get("label"), "sample": weak_factor.get("completed"), "avg_return_5d": weak_factor.get("avg_return_5d"), "action": "降低因子權重", "reason": "近期同因子表現偏弱。"})
    return feedback[:limit]


def _score_band_stats(items: list[dict]) -> list[dict]:
    bands = {"50-64": [], "65-74": [], "75-84": [], "85-94": [], "95+": []}
    for item in items:
        score = int(item.get("total_score") or 0)
        key = "95+" if score >= 95 else "85-94" if score >= 85 else "75-84" if score >= 75 else "65-74" if score >= 65 else "50-64"
        bands[key].append(item)
    return [_bucket_stats(label, bucket) for label, bucket in bands.items()]


def _entry_analysis(items: list[dict]) -> dict:
    triggered = [item for item in items if item.get("entry_triggered") is True and item.get("return_5d") is not None]
    not_triggered = [item for item in items if item.get("entry_triggered") is False and item.get("return_5d") is not None]
    return {
        "triggered": {"count": len(triggered), "win_rate_5d": _rate([item.get("return_5d") > 0 for item in triggered]), "avg_return_5d": _avg([item.get("return_5d") for item in triggered])},
        "not_triggered": {"count": len(not_triggered), "win_rate_5d": _rate([item.get("return_5d") > 0 for item in not_triggered]), "avg_return_5d": _avg([item.get("return_5d") for item in not_triggered])},
    }


def _retry_row(row: tuple) -> dict:
    return {
        "dataset": row[0],
        "stock_id": row[1],
        "period": row[2],
        "reason": row[3],
        "status": row[4],
        "attempts": row[5],
        "first_seen_at": row[6],
        "last_attempt_at": row[7],
        "last_error": row[8],
        "recovered_at": row[9],
        "suggestion": _retry_suggestion(row[0], row[3], row[4]),
    }


def _retry_suggestion(dataset: str, reason: str, status: str) -> str:
    text = f"{dataset} {reason} {status}"
    if "empty" in text.lower() or "空" in text:
        return "確認該股票是否有官方資料；若已由 fallback 補回，可降低資料品質扣分。"
    if "timeout" in text.lower() or "limit" in text.lower() or "限流" in text:
        return "保留快取並延後重試，避免同一來源連續請求。"
    if "HTML" in text or "html" in text:
        return "TWSE 回傳 HTML 時使用 fallback，成功補回不視為核心資料缺失。"
    return "保留在重試佇列，等待下次排程補抓。"
