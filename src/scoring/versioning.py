from __future__ import annotations


SCORE_VERSION = "v2"
DECISION_VERSION = "v2"
UNIVERSE_VERSION = "tw_stock_universe_v2"


def model_versions() -> dict[str, str]:
    return {
        "score_version": SCORE_VERSION,
        "decision_version": DECISION_VERSION,
        "universe_version": UNIVERSE_VERSION,
    }
