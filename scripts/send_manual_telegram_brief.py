from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.notifier.telegram import TelegramNotifier


DEFAULT_URL = "https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/dashboard/"


def _text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _esc(value: Any, default: str = "-") -> str:
    return html.escape(_text(value, default), quote=False)


def _decision(row: dict[str, Any]) -> str:
    return _text(row.get("entry_decision") or row.get("action") or row.get("decision"), "只觀察")


def _row_line(row: dict[str, Any]) -> str:
    stock_id = _esc(row.get("stock_id") or row.get("id"))
    name = _esc(row.get("name"))
    score = _esc(row.get("score", "-"))
    grade = _esc(row.get("grade", "-"))
    decision = _esc(_decision(row))
    ai_label = _esc(row.get("ai_label") or row.get("ai_status") or "AI 未複核")
    return f"▸ <b>{stock_id} {name}</b>｜{score}/100｜{grade}｜{decision}｜{ai_label}"


def _rows(rows: list[dict[str, Any]], empty: str, limit: int) -> str:
    lines = [_row_line(row) for row in rows[:limit]]
    return "\n".join(lines) if lines else empty


def _risk_lines(payload: dict[str, Any], limit: int) -> str:
    risks = payload.get("exit_risks") or payload.get("risk_watchlist") or []
    lines: list[str] = []
    for item in risks[:limit]:
        stock_id = _esc(item.get("stock_id") or item.get("id"))
        name = _esc(item.get("name"))
        level = _esc(item.get("level") or item.get("risk_level") or "風險")
        reasons = item.get("reasons") or []
        reason = "、".join(_text(reason) for reason in reasons[:2]) if reasons else _text(item.get("reason"), "")
        lines.append(f"▸ <b>{stock_id} {name}</b>｜{level}｜{_esc(reason, '需觀察')}")
    return "\n".join(lines) if lines else "▸ 無紅黃警戒"


def build_message(payload: dict[str, Any], *, url: str, max_items: int) -> str:
    summary = payload.get("summary") or {}
    action_lists = payload.get("action_lists") or {}
    data_quality = payload.get("data_quality") or {}
    source_status = payload.get("source_status") or {}
    ai_health = (((payload.get("ai_council") or {}).get("status") or {}).get("health") or {})
    overseas = payload.get("overseas") or {}
    themes = payload.get("themes") or {}

    return "\n".join(
        [
            f"🇹🇼 <b>台股 AI 手動補推</b>｜{_esc(payload.get('generated_date'))}",
            f"資料日：{_esc(payload.get('as_of'))}｜產生：{_esc(payload.get('generated_at'))}",
            "",
            f"🧭 風向：{_esc(overseas.get('label'))}",
            f"📰 題材：{_esc(themes.get('summary'))}",
            (
                f"📊 掃描 <b>{_esc(summary.get('scanned', 0))}</b> 檔"
                f"｜有效 <b>{_esc(summary.get('valid', 0))}</b>"
                f"｜S+ <b>{_esc(summary.get('s_plus_grade', 0))}</b>"
                f"｜S <b>{_esc(summary.get('s_grade', 0))}</b>"
                f"｜A <b>{_esc(summary.get('a_grade', 0))}</b>"
            ),
            (
                f"✅ 資料品質：{_esc(data_quality.get('label_text') or data_quality.get('label'))}"
                f"｜資料源：{_esc(source_status.get('label'))}"
                f"｜AI：{_esc(ai_health.get('label'), '未啟用')}"
            ),
            "",
            "🔥 <b>可追</b>",
            _rows(action_lists.get("chase") or [], "▸ 今日暫無可追清單", max_items),
            "",
            "🟡 <b>等拉回</b>",
            _rows(action_lists.get("pullback") or [], "▸ 今日暫無等拉回清單", max_items),
            "",
            "🛡 <b>危險名單</b>",
            _risk_lines(payload, max_items),
            "",
            f"🔗 <a href=\"{html.escape(url, quote=True)}\">開啟今日監控</a>",
            "⚠️ 僅供研究追蹤，不是投資建議。",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a UTF-8 safe manual Telegram brief.")
    parser.add_argument("--payload", default="dashboard/dashboard_data.json")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--max-items", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    payload_path = (ROOT / args.payload).resolve()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    message = build_message(payload, url=args.url, max_items=max(1, args.max_items))
    TelegramNotifier.from_env(dry_run=args.dry_run).send(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
