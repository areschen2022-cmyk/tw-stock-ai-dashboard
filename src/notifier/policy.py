from __future__ import annotations

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
REPORT_MODES = {"brief", "full"}


def report_mode(config: dict, *, force_brief: bool = False) -> str:
    if force_brief:
        return "brief"
    mode = (
        config.get("notification", {})
        .get("telegram", {})
        .get("report_mode", "brief")
    )
    mode = str(mode).strip().lower()
    return mode if mode in REPORT_MODES else "brief"


def notification_limits(config: dict) -> dict[str, int]:
    cfg = config.get("notification", {}).get("telegram", {})
    return {
        "max_pick_items": max(1, int(cfg.get("max_pick_items", 3))),
        "max_alert_items": max(0, int(cfg.get("max_alert_items", 2))),
        "max_exit_items": max(0, int(cfg.get("max_exit_items", 2))),
    }


def notification_severity(
    dashboard_payload: dict,
    *,
    alerts: list[str] | None = None,
    exit_risks: list[dict] | None = None,
) -> str:
    alerts = alerts or []
    exit_risks = exit_risks or []
    action_summary = dashboard_payload.get("action_lists", {}).get("summary", {})
    data_quality = dashboard_payload.get("data_quality", {})
    source_status = dashboard_payload.get("source_status", {})
    source_label = str(source_status.get("label", "")).lower()
    source_state = str(source_status.get("status", "") or source_status.get("level", "")).lower()

    if exit_risks or source_state in {"error", "bad"} or "error" in source_label or data_quality.get("label") == "low":
        return "critical"
    if alerts or int(action_summary.get("avoid", 0) or 0) > 0:
        return "warning"
    return "info"


def should_send(config: dict, severity: str) -> bool:
    cfg = config.get("notification", {}).get("telegram", {})
    minimum = str(cfg.get("min_severity", "info")).strip().lower()
    if minimum not in SEVERITY_RANK:
        minimum = "info"
    severity = str(severity).strip().lower()
    if severity not in SEVERITY_RANK:
        severity = "info"
    return SEVERITY_RANK[severity] >= SEVERITY_RANK[minimum]
