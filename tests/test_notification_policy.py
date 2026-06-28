from __future__ import annotations

from src.notifier.policy import notification_limits, notification_severity, report_mode, should_send


def test_report_mode_defaults_to_brief_and_respects_force_flag() -> None:
    assert report_mode({}) == "brief"
    assert report_mode({"notification": {"telegram": {"report_mode": "full"}}}) == "full"
    assert report_mode({"notification": {"telegram": {"report_mode": "full"}}}, force_brief=True) == "brief"
    assert report_mode({"notification": {"telegram": {"report_mode": "unknown"}}}) == "brief"


def test_notification_limits_are_configurable_with_safe_minimums() -> None:
    config = {"notification": {"telegram": {"max_pick_items": 5, "max_alert_items": -1, "max_exit_items": 0}}}

    assert notification_limits(config) == {
        "max_pick_items": 5,
        "max_alert_items": 0,
        "max_exit_items": 0,
    }


def test_notification_severity_prioritizes_exit_risk_and_alerts() -> None:
    payload = {"action_lists": {"summary": {}}, "data_quality": {"label": "high"}, "source_status": {"label": "正常"}}

    assert notification_severity(payload) == "info"
    assert notification_severity(payload, alerts=["theme spike"]) == "warning"
    assert notification_severity(payload, exit_risks=[{"stock_id": "2330"}]) == "critical"
    assert notification_severity({**payload, "source_status": {"status": "error"}}) == "critical"


def test_should_send_applies_minimum_severity_threshold() -> None:
    config = {"notification": {"telegram": {"min_severity": "warning"}}}

    assert should_send(config, "info") is False
    assert should_send(config, "warning") is True
    assert should_send(config, "critical") is True
