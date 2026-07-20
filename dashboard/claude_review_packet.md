# Claude Code 審查包｜tw-stock-ai

產生時間：2026-07-20T16:21:42+08:00

## 專案位置

請直接讀取這個資料夾：

```text
C:\Users\User\Documents\Codex\_archive\codex_workspaces_20260703_2350\2026-05-11\files-mentioned-by-the-user-taiwan\tw-stock-ai
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
M scripts/post_optimization_finalize.py
?? scripts/claude_review_packet.py
?? tests/test_claude_review_packet.py
```

## 最近 Commit

```text
d2846b1 auto: dashboard 2026-07-20
07cf9cf fix: harden theme encoding checks
ca892b7 chore: record telegram delivery 2026-07-19 [skip ci]
72b7e46 auto: dashboard 2026-07-19
f6d5d46 auto: dashboard 2026-07-19
```

## Remote

```text
origin	https://github.com/areschen2022-cmyk/tw-stock-ai-dashboard.git (fetch)
origin	https://github.com/areschen2022-cmyk/tw-stock-ai-dashboard.git (push)
```

## 最近 GitHub Actions

```text
completed	success	fix: harden theme encoding checks	Taiwan Stock AI Daily	main	push	29725414813	3m5s	2026-07-20T07:41:37Z
completed	success	Taiwan Stock AI Daily	Taiwan Stock AI Daily	main	schedule	29715637235	44s	2026-07-20T03:53:47Z
completed	failure	Taiwan Stock AI Daily	Taiwan Stock AI Daily	main	schedule	29710654236	28s	2026-07-20T01:15:00Z
completed	success	Taiwan Stock AI Daily	Taiwan Stock AI Daily	main	schedule	29710471609	53s	2026-07-20T01:07:58Z
completed	success	Taiwan Stock AI Daily	Taiwan Stock AI Daily	main	schedule	29709196565	51s	2026-07-20T00:14:05Z
```

## 重要檔案

存在：

```text
.github/workflows/daily.yml
main.py
config.yaml
src/config_loader.py
src/report/dashboard.py
src/scoring/score_engine.py
src/storage/sqlite_store.py
scripts/post_optimization_finalize.py
scripts/verification_loop.py
scripts/research_source_review.py
data/theme_universe.yaml
data/theme_universe.d/2026_trends.yaml
data/theme_chain_map.yaml
data/research_source_registry.json
dashboard/post_update_check.json
dashboard/verification_loop.json
dashboard/post_optimization_finalize.json
dashboard/research_source_review.json
```

缺少：

```text
(none)
```

## 本機檢查摘要

### post_update_check

```json
{
  "status": "ok",
  "generated_at": "2026-07-20T15:44:23+08:00",
  "counts": {
    "critical": 0,
    "warning": 0,
    "info": 1
  }
}
```

### verification_loop

```json
{
  "status": "ok",
  "generated_at": "2026-07-20T15:44:23+08:00",
  "next_actions": [
    "Next optimization: feed knowledge-hub findings back into candidate scoring as internal-only context."
  ],
  "checks": {
    "compile": true,
    "post_update": true,
    "freshness": true,
    "knowledge_hub": true
  }
}
```

### post_optimization_finalize

```json
{
  "status": "ok",
  "generated_at": "2026-07-20T15:40:14+08:00",
  "next_actions": [
    "下一步可把本次新經驗納入選股規則，但仍需累積樣本再調整權重。"
  ],
  "checks": {
    "compile": true,
    "tests": true,
    "research_source_review": true,
    "post_update": true,
    "mojibake_scan": true,
    "knowledge_export": true,
    "verification_loop": true
  }
}
```

### research_source_review

```json
{
  "status": "ok",
  "generated_at": "2026-07-20T15:44:22+08:00",
  "next_actions": [
    "TWSE/TPEx Industry Value Chain -> theme_chain_map",
    "backtesting.py -> strategy_replay",
    "QuantStats -> performance_report",
    "twstock Python Library -> backup_adapter",
    "vectorbt -> research_backtest"
  ]
}
```
