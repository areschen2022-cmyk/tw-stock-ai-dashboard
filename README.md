# TW Stock AI

Taiwan stock screening MVP with FinMind-compatible data loading, deterministic mock data, SQLite persistence, scoring, dry-run reporting, Telegram notification hooks, and focused pytest coverage.

## Quick Start

```powershell
cd tw-stock-ai
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe -m pip install -r requirements.txt
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe main.py --dry-run --mock-data
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe -m pytest
```

## Configuration

Copy `.env.example` to `.env` if you want real FinMind or Telegram integration. The default `config.yaml` is safe for local dry-runs.

For real Telegram delivery, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, then run without `--dry-run`:

```powershell
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe main.py --mock-data --send-telegram
```

## GitHub Pages

The monitoring dashboard is generated in `dashboard/`. To publish it through GitHub Pages, copy it to `docs/` and push:

```powershell
.\scripts\publish_pages.ps1 -Message "Update dashboard"
```

## External Scheduler

Cloudflare Workers Cron can trigger the GitHub workflow through `workflow_dispatch` for more reliable timing than GitHub's native schedule. The Worker also passes the intended Asia/Taipei trigger time so the dashboard can show schedule delay minutes. See `docs/external_scheduler.md`.

## AI Council

AI picks require enough model participation before they are shown as official picks. Current strict rule: at least 5 valid model reviews and 5 votes for `可追`. See `docs/ai_council_rules.md`.

Stock grades describe signal strength, not automatic buy permission. The dashboard now separates strength from `entry_decision`, danger-list rules, and theme quality. See `docs/entry_risk_theme_rules.md`.

## Backtest Quality Check

Validate stored signal data and forward-return backtests:

```powershell
python scripts/backtest_quality_check.py --days 365
```

## Trading Knowledge Hub Export

Learning outcomes can be exported to the shared local knowledge hub at:

```text
C:\Users\User\trading_knowledge_hub\data\knowledge_points.jsonl
```

Manual export:

```powershell
.\scripts\run_knowledge_hub_export.bat
```

Install or refresh the Windows scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_knowledge_hub_export_task.ps1
```

The task name is `tw-stock-ai-knowledge-hub-export`. It runs daily at 08:45, pulls the latest GitHub dashboard state when possible, and upserts performance attribution into the knowledge hub.

## Post-Optimization Finalize

After every code, dashboard, scoring, data-source, or automation optimization, run the standard finalizer before reporting completion:

```powershell
.\scripts\post_optimization_finalize.bat
```

The finalizer runs Python compile checks, pytest, dashboard self-checks, a mojibake scan, knowledge-hub export, and the verification loop. It writes the audit report to:

```text
dashboard/post_optimization_finalize.json
```

If this script reports `bad`, fix the listed issue first and rerun it before pushing or declaring the update complete.
