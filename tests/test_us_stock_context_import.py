import json

from scripts.import_us_stock_context import build_us_stock_context, write_context


def test_build_us_stock_context_keeps_numeric_market_and_symbols(tmp_path):
    source = tmp_path / "us"
    (source / "docs").mkdir(parents=True)
    (source / "data").mkdir(parents=True)
    (source / "docs" / "dashboard_data.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-26",
                "market": {"SPY": 734.3, "SMH": 636.8, "VIX": 18.9, "OTHER": 1},
                "overview": {"total_scored": 40, "grade_B": 3},
                "strategy": {
                    "regime": {"allow_new_entries": True, "breadth_phase2_pct": 25},
                    "divergence": {
                        "n_compared": 40,
                        "avg_gap": 22.8,
                        "missed_strong": [{"symbol": "AMD", "score": 56, "rs_rating": 99}],
                    },
                },
                "top10": [{"symbol": "NVDA", "score": 80, "grade": "B"}],
            }
        ),
        encoding="utf-8",
    )
    (source / "docs" / "performance_data.json").write_text(
        json.dumps({"stats": {"signals": 2}}),
        encoding="utf-8",
    )
    (source / "data" / "trading_hub_context.json").write_text(
        json.dumps({"used_count": 5}),
        encoding="utf-8",
    )

    context = build_us_stock_context(source)

    assert context["status"] == "ok"
    assert context["market"] == {"SPY": 734.3, "SMH": 636.8, "VIX": 18.9}
    assert context["divergence"]["missed_strong"][0]["symbol"] == "AMD"
    assert context["candidates"][0]["symbol"] == "NVDA"
    assert context["knowledge_rows"] == 5


def test_write_us_stock_context_handles_missing_source(tmp_path):
    output = tmp_path / "context.json"

    context = write_context(tmp_path / "missing", output)

    assert context["status"] == "missing"
    assert output.exists()
