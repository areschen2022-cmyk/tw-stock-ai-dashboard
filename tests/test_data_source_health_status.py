from __future__ import annotations

from datetime import date

from src.news.web_theme import ThemeSignal
from src.report.dashboard import build_dashboard_payload, build_traceability_summary, enrich_dashboard_payload
from src.scoring.score_engine import StockScore

NORMAL = "\u6b63\u5e38"
USABLE_PENDING = "\u53ef\u7528\u4f46\u5f85\u88dc"
NEEDS_CHECK = "\u9700\u6aa2\u67e5"


def _payload_with_retry(retry_summary: dict) -> dict:
    score = StockScore(
        stock_id="2330",
        total_score=80,
        label="BUY_WATCH",
        price=100.0,
        technical_score=20,
        chip_score=20,
        fundamental_score=20,
        risk_score=20,
        market_adjustment=0,
    )
    payload = build_dashboard_payload(
        [score],
        date(2026, 5, 18),
        "market ok",
        None,
        {"stock_names": {"2330": "TSMC"}, "theme_pools": {}},
        overseas=None,
        theme_signal=ThemeSignal([], "news ok", [], {}, source_count=1, failed_count=0),
        source_status={
            "label": NORMAL,
            "api": 10,
            "cache": 2,
            "fallback": 1,
            "quota": 0,
            "error": 0,
            "empty": 0,
            "official_snapshots": {
                "institutional": {"date": "2026-05-18", "valid": True, "rows": 1000}
            },
        },
    )
    payload["data_retry"] = retry_summary
    return enrich_dashboard_payload(
        payload,
        source_status=payload["source_status"],
        retry_summary=payload["data_retry"],
    )


def test_partial_retry_failures_do_not_block_usable_data_source() -> None:
    payload = _payload_with_retry(
        {
            "pending": 1,
            "failed": 1,
            "recovered": 20,
            "status_counts": {"pending": 1, "failed": 1, "recovered": 20},
            "diagnosis": [],
            "recovered_by_dataset": [{"dataset": "STOCK_DAY", "count": 20}],
        }
    )

    health = payload["data_source_health"]
    assert health["label"] == USABLE_PENDING
    assert health["blocking_count"] == 0
    assert health["historical_failed_count"] == 1

    trace = build_traceability_summary(payload)
    source_step = next(step for step in trace["steps"] if step["key"] == "source")
    assert source_step["status"] == "warn"


def test_unrecovered_retry_failures_remain_blocking() -> None:
    payload = _payload_with_retry(
        {
            "pending": 0,
            "failed": 3,
            "recovered": 0,
            "status_counts": {"failed": 3},
            "diagnosis": [],
            "recovered_by_dataset": [],
        }
    )

    health = payload["data_source_health"]
    assert health["label"] == NEEDS_CHECK
    assert health["blocking_count"] == 3
