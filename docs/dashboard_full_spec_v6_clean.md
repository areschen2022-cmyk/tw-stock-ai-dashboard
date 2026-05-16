# 台股 AI Dashboard v6 去重版

整理日期：2026-05-16

來源：`C:\Users\User\Downloads\dashboard_full_spec_v6.txt`

## 已併入現有系統

- GitHub Actions 自動化：保留每日 08:00 更新網站，08:20 發 Telegram 早報。
- GitHub Pages：保留 `/dashboard/` 與 `/dashboard/performance.html`。
- Telegram：保留單一早報推播，不再保留 09:10 盤中二次推播。
- FinMind / TWSE：沿用現有 `TwseClient + FinMind fallback`，不再新增重複的 `fetch_price_margin.py`、`fetch_institutional.py` 拆分腳本。
- 題材熱度：沿用 `src/news/web_theme.py` 與 `theme_daily_scores`，不重做 `topics.json` 流程。
- 訊號成效：沿用 `performance.html`、`watch_signals`、forward return 統計。
- 收盤資金流向：沿用 `capital_flow_job.py` 與 `src/report/capital_flow.py`。

## 本版保留的新需求

1. S 級評級
   - `95-100`: S+
   - `85-94`: S
   - `75-84`: A
   - `65-74`: B
   - `50-64`: C
   - `<50`: -

2. 美股對台股題材對照
   - 新增 `config/sector_map.json`
   - 保留 `us_to_tw`、`policy_us_to_tw`、`sector_map`、`peer_map`
   - 先作為資料設定檔，後續再接入海外映射與題材評分

3. 政策訊號來源
   - 白宮 RSS 與 Federal Register 可以作為下一階段題材來源
   - 不在 GitHub Actions 內執行 agent-memory
   - 不把政策訊號直接當成買進訊號，只作為題材加權與風險提醒

4. Signal Lab
   - 回測引擎定位為離線、手動、低頻執行
   - 不納入每日 08:00/08:20 自動流程

5. agent-memory
   - 僅作為本機開發記憶層
   - 不納入 GitHub Actions
   - 不要求部署到 GitHub Pages

## 明確剃除的重複內容

- `scripts/fetch_price_margin.py`：目前由 `main.py` 透過 provider 統一抓取。
- `scripts/fetch_institutional.py`：目前由 provider bundle 統一處理。
- `scripts/build_json.py`：目前由 `write_dashboard()` / `write_performance()` 直接產出 dashboard JSON。
- `scripts/send_telegram.py`：目前由 `src/notifier/telegram.py` 處理。
- `daily.yml` 裡的 17 步拆分流程：與現有單一 `main.py` 入口重複，暫不採用。
- 自動下單 / 券商 API：保留為後期選配，不進入目前版。

## 下一階段建議

1. 將 `config/sector_map.json` 接到海外情緒模組，讓 GLW/COHR/LITE/MU/NVDA 的漲跌能更明確映射到台股族群。
2. 新增政策訊號模組，先只輸出摘要與題材加權，不改變核心交易分數。
3. 建立離線 Signal Lab，驗證 S+/S/A/B 各級別的 3 日、5 日、10 日表現。
