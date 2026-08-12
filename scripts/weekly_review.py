from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_sorted(rows: list[dict], key: str, *, reverse: bool = True, min_completed: int = 0) -> dict:
    usable = [row for row in rows if row.get(key) is not None and int(_num(row.get("completed"))) >= min_completed]
    if not usable:
        return {}
    return sorted(usable, key=lambda row: _num(row.get(key)), reverse=reverse)[0]


def _label(row: dict) -> str:
    return str(row.get("label") or row.get("theme") or row.get("action") or row.get("stage") or "-")


def _compact_stat(row: dict) -> dict:
    if not row:
        return {}
    return {
        "label": _label(row),
        "signals": row.get("signals") or row.get("count"),
        "completed": row.get("completed"),
        "win_rate_5d": row.get("win_rate_5d"),
        "avg_return_5d": row.get("avg_return_5d"),
        "stop_hit_rate": row.get("stop_hit_rate"),
    }


def _guardrail_status(row: dict, *, min_completed: int = 10) -> str:
    completed = int(_num(row.get("completed")))
    win_rate = row.get("win_rate_5d")
    avg_return = row.get("avg_return_5d")
    if completed < min_completed or win_rate is None or avg_return is None:
        return "needs_more_samples"
    if _num(win_rate) < 45 or _num(avg_return) < 0:
        return "needs_review"
    if _num(win_rate) >= 52 and _num(avg_return) >= 0:
        return "working"
    return "neutral"


def _previous_guardrail_status(previous_review: dict | None) -> dict[str, str]:
    if not isinstance(previous_review, dict):
        return {}
    return {
        str(row.get("tag")): str(row.get("status"))
        for row in previous_review.get("guardrail_effectiveness") or []
        if row.get("tag")
    }


def _guardrail_recommendation(status: str, consecutive_review: bool) -> str:
    if consecutive_review:
        return "連續兩週效果偏弱，先降低此守門條件權重，並檢查是否過度過濾好訊號。"
    if status == "needs_review":
        return "本週效果偏弱，列入下週觀察；暫不加權，等更多樣本確認。"
    if status == "working":
        return "守門條件有效，維持目前權重並持續追蹤。"
    if status == "neutral":
        return "效果中性，暫時維持，不主動升權。"
    return "樣本不足，先保留紀錄，不調整權重。"


def _guardrail_effectiveness(performance: dict, previous_review: dict | None = None) -> list[dict]:
    previous = _previous_guardrail_status(previous_review)
    rows: list[dict] = []
    for row in performance.get("guardrail_stats") or []:
        tag = str(row.get("tag") or "")
        if not tag:
            continue
        status = _guardrail_status(row)
        previous_status = previous.get(tag)
        consecutive_review = status == "needs_review" and previous_status == "needs_review"
        rows.append(
            {
                "tag": tag,
                "label": tag,
                "signals": row.get("signals"),
                "completed": row.get("completed"),
                "win_rate_5d": row.get("win_rate_5d"),
                "avg_return_5d": row.get("avg_return_5d"),
                "stop_hit_rate": row.get("stop_hit_rate"),
                "status": status,
                "previous_status": previous_status,
                "consecutive_review": consecutive_review,
                "recommended_action": _guardrail_recommendation(status, consecutive_review),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            0 if item["consecutive_review"] else 1,
            0 if item["status"] == "needs_review" else 1,
            -int(_num(item.get("completed"))),
            str(item.get("tag")),
        ),
    )


def _potential_rows(potential: dict, key: str) -> list[dict]:
    value = potential.get(key)
    if value is None and isinstance(potential.get("potential_radar"), dict):
        value = potential["potential_radar"].get(key)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("rows") or []
    return []


def _weekly_themes(weekly: dict, max_items: int = 5) -> list[dict]:
    return [
        {
            "theme": row.get("theme") or row.get("label") or row.get("name"),
            "week_score": row.get("week_score"),
            "trend": row.get("trend"),
            "today": row.get("today"),
        }
        for row in (weekly.get("themes") or [])[:max_items]
    ]


def _issue(code: str, severity: str, finding: str, evidence: str, recommendation: str) -> dict:
    return {
        "code": code,
        "severity": severity,
        "finding": finding,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _selection_logic_audit(
    performance: dict,
    potential: dict,
    weekly: dict,
    backtest: dict,
    dashboard: dict | None = None,
) -> dict:
    """Weekly internal audit for whether the stock-picking logic is too strict or too loose.

    This is intentionally kept out of the main UI. It feeds weekly_review.json
    and the knowledge hub so future scoring changes can be based on evidence.
    """
    dashboard = dashboard or {}
    perf_stats = performance.get("stats") or {}
    pot_stats = potential.get("stats") or (potential.get("potential_radar") or {}).get("stats") or {}
    traffic = (dashboard.get("traffic_lights") or {}).get("counts") or {}
    action_summary = dashboard.get("action_summary") or {}
    current_backtest = performance.get("current_selection_backtest") or dashboard.get("current_selection_backtest") or {}
    weak_segments = ((backtest.get("weak") or {}).get("segments") or [])[:5]
    low_win_rows = (performance.get("low_win_rate_breakdown") or {}).get("rows") or []

    green = int(_num(traffic.get("green", action_summary.get("chase"))))
    yellow = int(_num(traffic.get("yellow", action_summary.get("pullback"))))
    red = int(_num(traffic.get("red", action_summary.get("risk"))))
    daily_completed = int(_num(perf_stats.get("completed")))
    daily_win = perf_stats.get("win_rate_5d")
    potential_completed = int(_num(pot_stats.get("completed")))
    potential_win = pot_stats.get("win_rate_5d")

    issues: list[dict] = []
    if green == 0 and yellow > 0:
        issues.append(
            _issue(
                "no_green_with_watchlist",
                "medium",
                "本週沒有綠燈可追，但仍有黃燈觀察名單，可能是進場門檻偏嚴或市場尚未確認。",
                f"green={green}, yellow={yellow}, red={red}",
                "檢查可追條件是否過度嚴格；若黃燈後續勝率高，可建立小倉位觀察規則。",
            )
        )
    if red >= max(5, green + yellow):
        issues.append(
            _issue(
                "risk_list_dominates",
                "high",
                "危險名單數量明顯高於可追與等拉回，代表風控壓力偏高。",
                f"green={green}, yellow={yellow}, red={red}",
                "下週優先檢查紅色警戒是否命中下跌；若命中率低，降低過度保守的風險權重。",
            )
        )
    if daily_completed >= 10 and daily_win is not None and _num(daily_win) < 50:
        issues.append(
            _issue(
                "daily_signal_win_rate_below_50",
                "high",
                "每日選股已完成樣本的 5 日勝率低於 50%，需要檢討進場條件與加分來源。",
                f"completed={daily_completed}, win_rate_5d={_num(daily_win):.1f}%",
                "降低低勝率來源的權重，優先檢查重複訊號、弱題材升級與追價條件。",
            )
        )
    if potential_completed >= 10 and potential_win is not None and _num(potential_win) < 50:
        issues.append(
            _issue(
                "potential_radar_win_rate_below_50",
                "medium",
                "潛力雷達已完成樣本勝率低於 50%，代表提前觀察條件需要再校準。",
                f"completed={potential_completed}, win_rate_5d={_num(potential_win):.1f}%",
                "把潛力雷達拆成分群回測，弱分群降權，強分群保留到正式選股前置名單。",
            )
        )
    if current_backtest and int(_num(current_backtest.get("candidate_count"))) > 0:
        ref_count = int(_num(current_backtest.get("referenceable_count")))
        if ref_count == 0:
            issues.append(
                _issue(
                    "current_candidates_no_reference",
                    "medium",
                    "今日候選股缺少可比較的歷史同條件樣本，決策可信度較低。",
                    f"candidate_count={current_backtest.get('candidate_count')}, referenceable_count={ref_count}",
                    "補足同條件回測索引，至少用題材、強度、進場條件三層標籤找參考樣本。",
                )
            )
    if weak_segments or low_win_rows:
        sample = weak_segments[0] if weak_segments else low_win_rows[0]
        issues.append(
            _issue(
                "weak_segments_available",
                "info",
                "已找到較弱的歷史分群，可作為下週調權參考。",
                f"group={sample.get('group')}, label={sample.get('label')}, completed={sample.get('completed')}",
                "把弱分群同步到 backtest_guard，避免同類低勝率條件下週繼續放大權重。",
            )
        )

    if not issues:
        status = "normal"
        verdict = "本週選股邏輯沒有明顯失衡，維持目前規則並持續累積樣本。"
    elif any(item["severity"] == "high" for item in issues):
        status = "needs_review"
        verdict = "本週選股邏輯需要檢討，高風險項目應先降權或暫停升級。"
    else:
        status = "watch"
        verdict = "本週選股邏輯需觀察，先不大改規則，但下週要追蹤弱項是否延續。"

    return {
        "status": status,
        "logic_verdict": verdict,
        "traffic_counts": {"green": green, "yellow": yellow, "red": red},
        "sample_state": {
            "daily_completed": daily_completed,
            "daily_win_rate_5d": daily_win,
            "potential_completed": potential_completed,
            "potential_win_rate_5d": potential_win,
        },
        "issues": issues,
        "next_week_focus": [item["recommendation"] for item in issues if item["severity"] in {"high", "medium"}][:5],
    }


def _automation_failure_summary(github_failures: dict | None) -> dict | None:
    if not github_failures:
        return None
    failures = github_failures.get("recent_failures") or []
    categories = github_failures.get("summary", {}).get("categories") or {}
    return {
        "status": github_failures.get("status", "unknown"),
        "generated_at": github_failures.get("generated_at"),
        "failed_run_count": github_failures.get("summary", {}).get("failed_run_count", len(failures)),
        "top_categories": [
            {"category": key, "count": value}
            for key, value in sorted(categories.items(), key=lambda item: (-int(item[1]), item[0]))[:5]
        ],
        "latest_failures": [
            {
                "run_id": row.get("run_id"),
                "workflow": row.get("workflow"),
                "title": row.get("display_title"),
                "created_at": row.get("created_at"),
                "url": row.get("url"),
                "root_cause": row.get("root_cause"),
                "annotation_count": row.get("annotation_count"),
            }
            for row in failures[:5]
        ],
    }


def _action_items(
    performance: dict,
    potential: dict,
    backtest: dict,
    guardrails: list[dict] | None = None,
    logic_audit: dict | None = None,
    automation_failures: dict | None = None,
) -> list[dict]:
    actions: list[dict] = []

    win_rate = _num((performance.get("stats") or {}).get("win_rate_5d"))
    if win_rate < 50:
        actions.append(
            {
                "type": "deweight",
                "target": "每日選股總體",
                "reason": f"5日勝率 {win_rate:.1f}% 低於 50%，下週應降低弱訊號權重並檢查追價條件。",
            }
        )

    entry = performance.get("entry_analysis") or {}
    triggered = entry.get("triggered") or {}
    not_triggered = entry.get("not_triggered") or {}
    if _num(triggered.get("completed") or triggered.get("count")) >= 20 and _num(triggered.get("avg_return_5d")) < _num(
        not_triggered.get("avg_return_5d"), -999
    ):
        actions.append(
            {
                "type": "investigate",
                "target": "進場觸發條件",
                "reason": "進場觸發後的平均報酬低於未觸發組，需檢查是否追高或突破確認太寬鬆。",
            }
        )

    weak_stage = _first_sorted(_potential_rows(potential, "stage_stats"), "avg_return_5d", reverse=False, min_completed=10)
    if weak_stage and _num(weak_stage.get("avg_return_5d")) < 0:
        actions.append(
            {
                "type": "deweight",
                "target": f"潛力雷達：{_label(weak_stage)}",
                "reason": f"已完成 {int(_num(weak_stage.get('completed')))} 筆，5日平均 {_num(weak_stage.get('avg_return_5d')):.1f}%，下週先降權。",
            }
        )

    for item in (backtest.get("adaptive_feedback") or [])[:3]:
        target = item.get("target") or item.get("label")
        action = item.get("action")
        if target and action:
            actions.append({"type": "carry_forward", "target": target, "reason": action})

    for row in guardrails or []:
        if row.get("status") != "needs_review":
            continue
        actions.append(
            {
                "type": "review_guardrail",
                "target": f"守門條件：{row.get('tag')}",
                "reason": row.get("recommended_action"),
            }
        )

    for issue in (logic_audit or {}).get("issues") or []:
        if issue.get("severity") not in {"high", "medium"}:
            continue
        actions.append(
            {
                "type": "logic_audit",
                "target": issue.get("code"),
                "reason": issue.get("recommendation"),
            }
        )

    if (automation_failures or {}).get("failed_run_count", 0):
        latest = ((automation_failures or {}).get("latest_failures") or [{}])[0]
        actions.append(
            {
                "type": "automation_failure",
                "target": "GitHub Actions",
                "reason": f"最近有 {automation_failures.get('failed_run_count')} 次失敗；最新原因：{latest.get('root_cause') or '未分類'}。",
            }
        )

    return actions[:8]


def build_weekly_review(
    performance: dict,
    potential: dict,
    weekly: dict,
    backtest: dict,
    previous_review: dict | None = None,
    dashboard: dict | None = None,
    github_failures: dict | None = None,
) -> dict:
    perf_stats = performance.get("stats") or {}
    pot_stats = potential.get("stats") or (potential.get("potential_radar") or {}).get("stats") or {}
    stage_rows = _potential_rows(potential, "stage_stats")
    factor_rows = _potential_rows(potential, "factor_stats")
    backtest_summary = backtest.get("summary") or {}

    daily_win = _num(perf_stats.get("win_rate_5d"))
    potential_win = _num(pot_stats.get("win_rate_5d"))
    risk_level = "normal"
    if daily_win < 50 or potential_win < 50 or backtest.get("risk_level") in {"needs_review", "sample_too_small"}:
        risk_level = "needs_review"
    if daily_win < 45 and potential_win < 45:
        risk_level = "high_review"

    guardrail_rows = _guardrail_effectiveness(performance, previous_review)
    logic_audit = _selection_logic_audit(performance, potential, weekly, backtest, dashboard)
    automation_failures = _automation_failure_summary(github_failures)

    return {
        "as_of": performance.get("as_of") or weekly.get("as_of") or backtest.get("as_of"),
        "generated_at": _now(),
        "status": "ok",
        "risk_level": risk_level,
        "summary": {
            "daily_signals": perf_stats.get("signals"),
            "daily_completed": perf_stats.get("completed"),
            "daily_win_rate_5d": perf_stats.get("win_rate_5d"),
            "daily_avg_return_5d": perf_stats.get("avg_return_5d"),
            "potential_signals": pot_stats.get("signals"),
            "potential_completed": pot_stats.get("completed"),
            "potential_win_rate_5d": pot_stats.get("win_rate_5d"),
            "potential_avg_return_5d": pot_stats.get("avg_return_5d"),
            "backtest_risk_level": backtest.get("risk_level"),
            "backtest_completed": backtest_summary.get("completed"),
        },
        "best": {
            "potential_stage": _compact_stat(_first_sorted(stage_rows, "avg_return_5d", min_completed=10)),
            "potential_factor": _compact_stat(_first_sorted(factor_rows, "avg_return_5d", min_completed=10)),
            "weekly_themes": _weekly_themes(weekly),
        },
        "weak": {
            "potential_stage": _compact_stat(_first_sorted(stage_rows, "avg_return_5d", reverse=False, min_completed=10)),
            "potential_factor": _compact_stat(_first_sorted(factor_rows, "avg_return_5d", reverse=False, min_completed=10)),
            "backtest_segments": ((backtest.get("weak") or {}).get("segments") or [])[:5],
            "failure_attribution": ((backtest.get("weak") or {}).get("failure_attribution") or [])[:5],
        },
        "guardrail_effectiveness": guardrail_rows,
        "selection_logic_audit": logic_audit,
        **({"automation_failures": automation_failures} if automation_failures else {}),
        "next_week_actions": _action_items(performance, potential, backtest, guardrail_rows, logic_audit, automation_failures),
        "rules": [
            "週檢討只提供下週調權建議，不直接改變當日交易決策。",
            "樣本數低於 10 筆的分群不做硬性升降權。",
            "每日選股、潛力雷達、危險名單分開檢討，避免把不同任務混在一起。",
            "守門條件需連續累積成效後才調權，避免單週雜訊造成過度修正。",
        ],
    }


def write_weekly_review(root: Path, output: Path, github_failures_path: Path | None = None) -> dict:
    dashboard = root / "dashboard"
    previous_review = _read_json(output)
    github_failures = _read_json(github_failures_path) if github_failures_path else None
    review = build_weekly_review(
        _read_json(dashboard / "performance_data.json"),
        _read_json(dashboard / "potential_data.json"),
        _read_json(dashboard / "weekly_data.json"),
        _read_json(dashboard / "backtest_review.json"),
        previous_review,
        _read_json(dashboard / "dashboard_data.json"),
        github_failures,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly review summary for internal learning and next-week guardrails.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dashboard/weekly_review.json")
    parser.add_argument("--github-failures", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    github_failures_path = (root / args.github_failures).resolve() if args.github_failures else None
    review = write_weekly_review(root, output, github_failures_path)
    print(f"weekly_review status={review['status']} risk_level={review['risk_level']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
