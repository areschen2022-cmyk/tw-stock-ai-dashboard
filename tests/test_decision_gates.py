from src.scoring.decision_gates import (
    apply_dashboard_decision_gates,
    normalize_ai_pick_action,
    weak_themes_from_backtest_guard,
)


def _row(stock_id="2408", **overrides):
    row = {
        "stock_id": stock_id,
        "name": "南亞科",
        "score": 90,
        "grade": "S",
        "action": "可追蹤突破",
        "entry_decision": "開盤確認",
        "trigger_tags": ["題材強共振", "法人共振", "營收加速", "放量長紅", "突破整理"],
        "themes": ["記憶體/HBM"],
        "theme_tiers": ["記憶體/HBM:核心"],
        "theme_chain": [{"chain_layer_label": "核心", "role": "DRAM"}],
        "exit_plan": {"plan_type": "old"},
    }
    row.update(overrides)
    return row


def test_normalize_ai_pick_action_falls_back_on_mojibake():
    assert normalize_ai_pick_action("可追") == "可追"
    assert normalize_ai_pick_action("\ufffd\ufffd\ufffd") == "可追"
    assert normalize_ai_pick_action("BUY") == "可追"


def test_red_alert_blocks_chase_action():
    payload = {"rows": [_row("2330")]}
    summary = apply_dashboard_decision_gates(
        payload,
        exit_risks=[{"stock_id": "2330", "level": "紅色警戒"}],
    )
    row = payload["rows"][0]
    assert summary["red_alert_blocked"] == 1
    assert row["action"] == "避免"
    assert row["entry_decision"] == "避免"
    assert row["decision_light"] == "red"
    assert "exit_plan" not in row


def test_repeated_signal_downgrades_to_pullback():
    payload = {"rows": [_row("2408")]}
    summary = apply_dashboard_decision_gates(
        payload,
        repeated_signal_context={"by_stock": {"2408": {"recent_count": 4}}},
    )
    row = payload["rows"][0]
    assert summary["repeat_downgraded"] == 1
    assert row["action"] == "等拉回"
    assert row["entry_decision"] == "等拉回"
    assert "60日重複降權" in row["trigger_tags"]


def test_missing_volume_or_base_downgrades_chase():
    payload = {"rows": [_row(trigger_tags=["題材強共振", "法人共振", "營收加速"])]}
    summary = apply_dashboard_decision_gates(payload)
    row = payload["rows"][0]
    assert summary["volume_downgraded"] == 1
    assert summary["base_downgraded"] == 1
    assert row["action"] == "等拉回"


def test_pullback_action_forces_pullback_entry_decision():
    payload = {"rows": [_row(action="等拉回", entry_decision="開盤確認")]}
    summary = apply_dashboard_decision_gates(payload)
    row = payload["rows"][0]
    assert summary["entry_strict_adjusted"] == 1
    assert row["action"] == "等拉回"
    assert row["entry_decision"] == "等拉回"
    assert "進場觸發轉嚴格" in row["trigger_tags"]


def test_weak_theme_needs_non_theme_confirmation():
    payload = {
        "rows": [
            _row(
                trigger_tags=["題材強共振", "放量長紅", "突破整理"],
                theme_chain=[],
            )
        ]
    }
    summary = apply_dashboard_decision_gates(payload, weak_themes={"記憶體/HBM"})
    row = payload["rows"][0]
    assert summary["weak_theme_downgraded"] == 1
    assert row["action"] == "等拉回"
    assert "弱題材未確認" in row["trigger_tags"]


def test_weak_themes_from_backtest_guard_extracts_theme_segments():
    context = {"segments": [{"group": "theme", "label": "記憶體/HBM"}, {"group": "grade", "label": "S"}]}
    assert weak_themes_from_backtest_guard(context) == {"記憶體/HBM"}
