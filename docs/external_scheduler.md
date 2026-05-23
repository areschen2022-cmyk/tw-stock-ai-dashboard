# External Scheduler

This project can use Cloudflare Workers Cron Triggers to call GitHub `workflow_dispatch`.
That avoids relying only on GitHub Actions `schedule`, which can be delayed under load.

## Schedule

All cron expressions are UTC.

| Taiwan time | UTC cron | Task |
| --- | --- | --- |
| 04:30 Mon-Fri | `30 20 * * 0-4` | dashboard |
| 05:00 Mon-Fri | `0 21 * * 0-4` | dashboard backup |
| 08:00 Mon-Fri | `0 0 * * 1-5` | Telegram |
| 08:15 Mon-Fri | `15 0 * * 1-5` | Telegram backup |

The Telegram backup is safe because `delivery_log` prevents duplicate morning reports.

## Cloudflare Setup

1. Create a fine-grained GitHub token for `areschen2022-cmyk/tw-stock-ai-dashboard`.
2. Grant repository permission: `Actions: Read and write`.
3. Copy `cloudflare-worker/wrangler.toml.example` to `cloudflare-worker/wrangler.toml`.
4. Set Worker secrets:

```powershell
cd cloudflare-worker
wrangler secret put GITHUB_TOKEN
wrangler secret put DISPATCH_SECRET
```

`DISPATCH_SECRET` is optional for cron runs, but useful for protected manual HTTP dispatch.

5. Deploy:

```powershell
wrangler deploy
```

## Manual HTTP Dispatch

After deploy, you can manually trigger a task:

```text
https://<worker-host>/dispatch?task=dashboard&secret=<DISPATCH_SECRET>
https://<worker-host>/dispatch?task=telegram&secret=<DISPATCH_SECRET>
https://<worker-host>/dispatch?task=all&secret=<DISPATCH_SECRET>
```

The Worker sends:

```json
{
  "ref": "main",
  "inputs": {
    "task": "dashboard|telegram|all",
    "send_telegram": "true|false",
    "scheduled_at_taipei": "2026-05-23T08:00:00+08:00",
    "scheduler": "cloudflare-worker",
    "scheduler_cron": "0 0 * * 1-5"
  }
}
```

`scheduled_at_taipei` is used by the dashboard health panel and Telegram summary
to show how many minutes the actual run lagged behind the intended trigger time.
For manual HTTP testing, you can pass it as a query parameter:

```text
https://<worker-host>/dispatch?task=dashboard&scheduled_at_taipei=2026-05-23T04:30:00%2B08:00&secret=<DISPATCH_SECRET>
```
