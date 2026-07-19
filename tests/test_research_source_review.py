from __future__ import annotations

from scripts.research_source_review import build_review


def test_research_source_review_accepts_valid_registry() -> None:
    registry = {
        "sources": [
            {
                "id": "twse_openapi",
                "name": "TWSE OpenAPI",
                "url": "https://openapi.twse.com.tw/",
                "source_type": "official_market_data",
                "priority": "core",
                "status": "adopted",
                "integration": "data_provider",
                "decision_use": "Use official daily market data.",
                "score_use": "Core score allowed.",
                "risks": ["holiday_or_delay"],
                "ui_policy": "status_only",
            },
            {
                "id": "concept_reference",
                "name": "Concept Reference",
                "url": "https://example.com",
                "source_type": "concept_reference",
                "priority": "high",
                "status": "candidate",
                "integration": "theme_validation",
                "decision_use": "Cross-check themes.",
                "score_use": "Internal confidence only.",
                "risks": ["terms_of_use"],
                "ui_policy": "internal_only",
            },
        ]
    }

    review = build_review(registry)

    assert review["status"] == "ok"
    assert review["summary"]["total"] == 2
    assert review["summary"]["adopted"] == 1
    assert review["summary"]["manual_review"] == 1
    assert review["rows"][0]["id"] == "twse_openapi"


def test_research_source_review_rejects_duplicate_ids() -> None:
    source = {
        "id": "same",
        "name": "A",
        "url": "https://example.com",
        "source_type": "reference",
        "priority": "medium",
        "status": "candidate",
        "integration": "research",
        "decision_use": "Research only.",
        "score_use": "No score.",
        "risks": [],
        "ui_policy": "internal_only",
    }

    review = build_review({"sources": [source, dict(source)]})

    assert review["status"] == "bad"
    assert any(item["message"] == "duplicate source id" for item in review["issues"])
