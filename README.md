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

AI picks require enough model participation before they are shown as official picks. Current rule: at least 5 valid model reviews and at least 4 votes for `可追`. See `docs/ai_council_rules.md`.

## Backtest Quality Check

Validate stored signal data and forward-return backtests:

```powershell
python scripts/backtest_quality_check.py --days 365
```
