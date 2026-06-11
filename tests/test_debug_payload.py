from __future__ import annotations

from src.report.dashboard import build_debug_payload, build_traceability_summary


def test_debug_payload_collects_internal_data_chain_context() -> None:
    dashboard_payload = {
        "as_of": "2026-06-11",
        "generated_at": "2026-06-11T08:00:00+08:00",
        "summary": {"scanned": 2, "valid": 2},
        "source_status": {
            "label": "normal",
            "api": 3,
            "cache": 2,
            "fallback": 1,
            "official_snapshots": {"revenue": {"valid": True, "rows": 100}},
            "market_snapshots": {"overseas_public_market": {"valid": True, "rows": 5}},
            "bundle_coverage": {
                "stocks": 2,
                "all_critical_complete": False,
                "datasets": {
                    "prices": {"coverage_pct": 100, "missing": []},
                    "revenue": {"coverage_pct": 50, "missing": ["2330"]},
                },
            },
            "universe": {
                "mode": "layered",
                "selected_count": 84,
                "target_total_listed": 1056,
                "coverage_pct": 8.0,
                "market_universe_available": 1000,
            },
        },
        "data_quality": {"label": "high"},
        "data_source_health": {"label": "usable_pending", "blocking_count": 0},
        "data_retry": {
            "status_counts": {"pending": 1, "failed": 0, "recovered": 2},
            "pending": 1,
            "failed": 0,
            "recovered": 2,
            "diagnosis": [{"dataset": "revenue"}],
            "recovered_by_dataset": [{"dataset": "prices", "count": 2}],
            "items": [{"dataset": "revenue", "data_id": "2330"}],
        },
        "ai_council": {
            "status": {
                "health": {"label": "stable", "score": 100},
                "requested_models": 1,
                "successful_models": 1,
                "success_model_names": ["deepseek-chat"],
                "failed_model_names": [],
            }
        },
    }
    performance_payload = {
        "stats": {"signals": 3, "completed": 1},
        "potential_radar": {"stats": {"signals": 5, "completed": 2}},
    }
    dashboard_payload["traceability"] = build_traceability_summary(dashboard_payload, performance_payload)

    debug = build_debug_payload(dashboard_payload, performance_payload)

    assert debug["source_status"]["official_snapshots"]["revenue"]["rows"] == 100
    assert debug["source_status"]["market_snapshots"]["overseas_public_market"]["rows"] == 5
    assert debug["bundle_coverage"]["datasets"]["revenue"]["coverage_pct"] == 50
    assert debug["universe"]["target_total_listed"] == 1056
    assert debug["retry"]["pending"] == 1
    assert debug["ai"]["success_model_names"] == ["deepseek-chat"]
    assert debug["traceability"]["summary"]["data_coverage"]["bundle_stocks"] == 2
