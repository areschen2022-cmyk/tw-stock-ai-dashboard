from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_OUTPUT = Path("dashboard/claude_review_packet.md")
IMPORTANT_FILES = [
    ".github/workflows/daily.yml",
    "main.py",
    "config.yaml",
    "src/config_loader.py",
    "src/report/dashboard.py",
    "src/scoring/score_engine.py",
    "src/storage/sqlite_store.py",
    "scripts/post_optimization_finalize.py",
    "scripts/verification_loop.py",
    "scripts/research_source_review.py",
    "data/theme_universe.yaml",
    "data/theme_universe.d/2026_trends.yaml",
    "data/theme_chain_map.yaml",
    "data/research_source_registry.json",
    "dashboard/post_update_check.json",
    "dashboard/verification_loop.json",
    "dashboard/post_optimization_finalize.json",
    "dashboard/research_source_review.json",
]


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _run(command: list[str], root: Path, timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(command failed: {exc})"
    output = (proc.stdout or proc.stderr or "").strip()
    return output[-4000:] if output else "(no output)"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _json_summary(path: Path) -> str:
    payload = _read_json(path)
    if not payload:
        return "missing/unreadable"
    keys = [
        "status",
        "generated_at",
        "as_of",
        "last_data_date",
        "counts",
        "next_actions",
    ]
    summary = {key: payload.get(key) for key in keys if key in payload}
    if "checks" in payload:
        summary["checks"] = {
            key: value.get("ok") for key, value in payload.get("checks", {}).items() if isinstance(value, dict)
        }
    return json.dumps(summary, ensure_ascii=False, indent=2)


def build_packet(root: Path) -> str:
    status = _run(["git", "status", "--short"], root)
    head = _run(["git", "log", "--oneline", "-5"], root)
    remote = _run(["git", "remote", "-v"], root)
    workflow = _run(["gh", "run", "list", "--repo", "areschen2022-cmyk/tw-stock-ai-dashboard", "--limit", "5"], root)

    existing_files = [item for item in IMPORTANT_FILES if (root / item).exists()]
    missing_files = [item for item in IMPORTANT_FILES if not (root / item).exists()]

    post_update = _json_summary(root / "dashboard" / "post_update_check.json")
    verification = _json_summary(root / "dashboard" / "verification_loop.json")
    finalize = _json_summary(root / "dashboard" / "post_optimization_finalize.json")
    research = _json_summary(root / "dashboard" / "research_source_review.json")

    return f"""# Claude Code 審查包｜tw-stock-ai

產生時間：{_now()}

## 專案位置

請直接讀取這個資料夾：

```text
{root}
```

GitHub repo：

```text
areschen2022-cmyk/tw-stock-ai-dashboard
```

網站：
- 今日監控：https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/dashboard/
- 訊號成效：https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/dashboard/performance.html
- 潛力雷達：https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/dashboard/potential.html
- 每週總覽：https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/dashboard/weekly.html

## 請 Claude 優先檢查

1. 每日 GitHub Actions 是否能穩定更新網站與推播。
2. dashboard/docs 是否同步，四個頁面資料日期是否一致。
3. 題材資料、產業鏈資料、股票名稱是否有亂碼或錯誤代碼。
4. 今日操作結論、潛力雷達、訊號成效、每週總覽是否互相矛盾。
5. 知識庫匯出是否真的能把成功/失敗歸因回寫。
6. 研究來源 registry 是否只是記錄，還是有不小心直接影響分數。
7. 有沒有高風險 bug、資料缺失、錯誤靜默失敗或排程死角。

請用中文回覆，先列高風險問題，再列優化建議。不要直接改檔案，先給 code review 報告。

## Git 狀態

```text
{status}
```

## 最近 Commit

```text
{head}
```

## Remote

```text
{remote}
```

## 最近 GitHub Actions

```text
{workflow}
```

## 重要檔案

存在：

```text
{chr(10).join(existing_files)}
```

缺少：

```text
{chr(10).join(missing_files) if missing_files else "(none)"}
```

## 本機檢查摘要

### post_update_check

```json
{post_update}
```

### verification_loop

```json
{verification}
```

### post_optimization_finalize

```json
{finalize}
```

### research_source_review

```json
{research}
```
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a concise Claude Code review packet for tw-stock-ai.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_packet(root), encoding="utf-8")
    print(f"claude-review-packet output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
