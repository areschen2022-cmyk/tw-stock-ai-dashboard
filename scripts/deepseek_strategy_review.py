from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
if str(ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(ROOT_FOR_IMPORTS))

from src.ai.deepseek_client import DeepSeekClient


TAIPEI = ZoneInfo("Asia/Taipei")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {"status": "invalid_json", "path": path.as_posix()}


def _read_knowledge_rows(root: Path, limit: int = 30) -> list[dict[str, Any]]:
    path = root / "data" / "knowledge_exports" / "taiwan_stock_learning.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _compact_context(root: Path) -> dict[str, Any]:
    performance = _read_json(root / "dashboard" / "performance_data.json")
    research_5y = _read_json(root / "dashboard" / "research_backtest_5y.json")
    backtest_review = _read_json(root / "dashboard" / "backtest_review.json")
    dashboard = _read_json(root / "dashboard" / "dashboard_data.json")
    potential = _read_json(root / "dashboard" / "potential_data.json")
    knowledge_rows = _read_knowledge_rows(root)

    return {
        "as_of": dashboard.get("as_of") or performance.get("as_of"),
        "daily_candidate_count": len(dashboard.get("rows") or []),
        "performance_stats": performance.get("stats") or {},
        "entry_analysis": performance.get("entry_analysis") or {},
        "theme_stats_top": (performance.get("theme_stats") or [])[:8],
        "research_5y_summary": (research_5y.get("summary") or {}),
        "research_5y_limits": (research_5y.get("method") or {}).get("limitations") or [],
        "backtest_review": {
            "status": backtest_review.get("status"),
            "risk_level": backtest_review.get("risk_level"),
            "weak": (backtest_review.get("weak") or {}).get("segments", [])[:8],
            "strong": (backtest_review.get("strong") or {}).get("segments", [])[:8],
        },
        "potential_radar_keys": list((potential.get("potential_radar") or {}).keys())[:20],
        "knowledge_lessons": [
            {
                "topic": row.get("topic"),
                "claim": row.get("claim"),
                "status": row.get("status"),
                "confidence": row.get("confidence"),
                "tags": row.get("tags"),
            }
            for row in knowledge_rows[:20]
        ],
        "active_layers": [
            "daily decision cards",
            "potential radar",
            "danger list",
            "institutional flow",
            "retail holder divergence",
            "theme/news heat",
            "revenue acceleration",
            "candlestick/technical patterns",
            "backtest guard",
            "knowledge hub readback",
            "DeepSeek AI council",
        ],
    }


def _local_review(context: dict[str, Any]) -> dict[str, Any]:
    stats = context.get("performance_stats") or {}
    entry = context.get("entry_analysis") or {}
    research = context.get("research_5y_summary") or {}
    theme_stats = context.get("theme_stats_top") or []

    triggered = entry.get("triggered") or {}
    not_triggered = entry.get("not_triggered") or {}
    weak_themes = [
        item
        for item in theme_stats
        if (item.get("completed") or 0) >= 20
        and ((item.get("win_rate_5d") or 0) < 45 or (item.get("avg_return_5d") or 0) < 0)
    ]

    return {
        "current_weaknesses": [
            {
                "issue": "Pure price/volume timing is not enough",
                "evidence": research.get("overall_5d"),
                "interpretation": "The 5-year baseline is below 50% win rate after costs, so breakout/volume should be an input, not a buy trigger.",
            },
            {
                "issue": "Triggered entries currently underperform not-triggered observations",
                "evidence": {"triggered": triggered, "not_triggered": not_triggered},
                "interpretation": "This suggests the current entry trigger may be chasing after the first burst, or stop/entry distance is too tight for volatile names.",
            },
            {
                "issue": "Several hot themes have weak realized 5-day performance",
                "evidence": weak_themes[:5],
                "interpretation": "Theme heat needs confirmation from revenue, institutional flow, or supply-chain role before it increases action urgency.",
            },
        ],
        "precision_improvements": [
            {
                "name": "Two-stage early ignition filter",
                "mechanism": "Separate early accumulation from actionable breakout. Potential radar flags early ignition; daily decision card only upgrades after next-day price/volume confirmation.",
                "required_data": ["daily OHLCV", "volume rank", "MA20/MA60", "previous high"],
                "expected_effect": "Reduces chasing mature breakouts while preserving watchlist discovery.",
                "risk": "May miss gap-and-go stocks; keep a small exception for high-liquidity leaders.",
            },
            {
                "name": "Theme validity gate",
                "mechanism": "Theme score cannot upgrade action unless matched to at least one of: revenue acceleration, institutional accumulation, supply-chain core tier, or policy/order evidence.",
                "required_data": ["theme heat", "revenue", "institutional flow", "theme universe tier", "policy radar"],
                "expected_effect": "Cuts pure news hype and reduces theme-failure losses.",
                "risk": "New themes without revenue data may be delayed; allow research-only status first.",
            },
            {
                "name": "Retail clean-up plus price resilience",
                "mechanism": "Prefer stocks where retail holders decline while price holds above MA20/MA60; downgrade retail crowding plus flat price.",
                "required_data": ["TDCC weekly holders", "daily close", "volume"],
                "expected_effect": "Finds quiet accumulation before public heat rises.",
                "risk": "Weekly data is slower; use as bias, not intraday trigger.",
            },
            {
                "name": "Regime-aware exposure gate",
                "mechanism": "In weak index/semiconductor overseas regime, require higher liquidity and stronger confirmation; in broad risk-on, allow earlier potential radar candidates.",
                "required_data": ["TAIEX trend", "OTC trend", "SOX/Nasdaq/NVDA/TSM ADR", "sector breadth"],
                "expected_effect": "Avoids applying the same entry rules in bull, bear, and choppy regimes.",
                "risk": "Regime labels can lag; keep rules simple and auditable.",
            },
            {
                "name": "Outcome-weighted tag calibration",
                "mechanism": "Each reason tag earns promotion/demotion only after enough completed samples; weak tags become action downgrades, not score changes.",
                "required_data": ["performance_data", "knowledge hub lessons", "reason tags"],
                "expected_effect": "Turns success/failure memory into a conservative decision filter.",
                "risk": "Small samples can mislead; require minimum completed count.",
            },
        ],
        "gating_rules": [
            "If a stock is on the red danger list, it cannot be '\u53ef\u8ffd' unless price/volume confirmation and institutional reversal both appear.",
            "If theme has weak realized history and no revenue/institutional confirmation, theme can label the stock but cannot upgrade action.",
            "If market regime is risk-off and overseas semiconductor is weak, S+/S grade must still pass opening volume confirmation.",
            "If stop distance is smaller than recent volatility, downgrade to \u7b49\u62c9\u56de or small position.",
            "If retail holders are rising while price fails to advance, mark as distribution risk.",
        ],
        "ablation_tests": [
            "Baseline price-volume only versus +theme validity gate.",
            "Current daily picks versus daily picks excluding weak backtest tags.",
            "Potential radar candidates with retail clean-up versus without retail clean-up.",
            "Triggered entry rule variants: next open, opening range break, pullback to MA5/MA10.",
            "Regime-on/off split: same signals during TAIEX above/below MA60 and SOX positive/negative.",
        ],
        "avoid": [
            "Do not let DeepSeek create stocks from news; only let it review structured candidates.",
            "Do not optimize many thresholds at once; one variable per ablation test.",
            "Do not treat a hot topic as a buy signal without supply-chain role or realized money flow.",
            "Do not display all research layers on the main page; keep them internal and show one decision.",
        ],
        "implementation_order": [
            "Add theme validity gate as internal tag/action downgrade.",
            "Add entry-trigger ablation report because current triggered entries underperform.",
            "Add regime-aware action threshold for risk-off days.",
            "Add retail clean-up confirmation into potential radar ranking.",
            "Run monthly outcome-weighted tag calibration into knowledge hub.",
        ],
    }


def _deepseek_review(context: dict[str, Any], max_tokens: int, timeout: int) -> dict[str, Any]:
    client = DeepSeekClient(timeout=timeout)
    if not client.enabled:
        return {"status": "skipped", "reason": "DEEPSEEK_API_KEY is not set"}

    prompt = {
        "goal": "Improve precision for finding Taiwan stocks before acceleration while avoiding chasing hype.",
        "instructions": [
            "Review the system as a quant research supervisor.",
            "Do not recommend individual stocks.",
            "Prefer simple testable rules over complex AI predictions.",
            "Return JSON only with keys: current_weaknesses, precision_improvements, gating_rules, ablation_tests, avoid, implementation_order.",
        ],
        "system_context": context,
    }
    messages = [
        {
            "role": "system",
            "content": "You are a strict quant research reviewer. You care about out-of-sample validation, transaction costs, look-ahead bias, and avoiding overfitting. Output JSON only.",
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    content = client.chat_json("deepseek-chat", messages, max_tokens=max_tokens)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"raw": content}
    return {"status": "ok", "model": "deepseek-chat", "review": parsed}


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    local = payload.get("local_review") or {}
    deepseek = payload.get("deepseek_review") or {}
    lines = [
        "# DeepSeek Strategy Review",
        "",
        f"- Generated: {payload.get('generated_at')}",
        f"- As of: {payload.get('context', {}).get('as_of')}",
        f"- DeepSeek: {deepseek.get('status')}",
        "",
        "## Main Findings",
    ]
    for item in local.get("current_weaknesses", []):
        lines.append(f"- {item.get('issue')}: {item.get('interpretation')}")
    lines.extend(["", "## Recommended Implementation Order"])
    for idx, item in enumerate(local.get("implementation_order", []), start=1):
        lines.append(f"{idx}. {item}")
    lines.extend(["", "## Gating Rules"])
    for item in local.get("gating_rules", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Ablation Tests"])
    for item in local.get("ablation_tests", []):
        lines.append(f"- {item}")
    if deepseek.get("status") == "ok":
        lines.extend(["", "## DeepSeek Raw Review", "```json"])
        lines.append(json.dumps(deepseek.get("review"), ensure_ascii=False, indent=2))
        lines.append("```")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path, allow_api: bool, max_tokens: int, timeout: int) -> dict[str, Any]:
    context = _compact_context(root)
    local_review = _local_review(context)
    deepseek_review = (
        _deepseek_review(context, max_tokens=max_tokens, timeout=timeout)
        if allow_api
        else {"status": "skipped", "reason": "API call not requested"}
    )
    payload = {
        "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "context": context,
        "skill_integration": [
            "quantitative-research: backtest rigor, costs, look-ahead, sample size",
            "edge-pipeline-orchestrator: convert ideas into testable gates and ablation tests",
            "market-regimes: require different behavior in risk-on/risk-off regimes",
            "knowledge-agent: use historical success/failure lessons as conservative filters",
        ],
        "local_review": local_review,
        "deepseek_review": deepseek_review,
    }
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "deepseek_strategy_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown(reports_dir / "deepseek_strategy_review.md", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strategy precision review with optional DeepSeek API.")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--allow-api", action="store_true", help="Call DeepSeek when DEEPSEEK_API_KEY is available")
    parser.add_argument("--max-tokens", type=int, default=2200)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    load_dotenv(root / ".env")
    payload = run(root, allow_api=args.allow_api, max_tokens=args.max_tokens, timeout=args.timeout)
    deepseek = payload["deepseek_review"]
    local = payload["local_review"]
    print(
        "strategy-review "
        f"deepseek={deepseek.get('status')} "
        f"weaknesses={len(local.get('current_weaknesses', []))} "
        f"improvements={len(local.get('precision_improvements', []))} "
        f"report={root / 'reports' / 'deepseek_strategy_review.md'}"
    )
    if deepseek.get("status") != "ok":
        print(f"deepseek_note={deepseek.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
