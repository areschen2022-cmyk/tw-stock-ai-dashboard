# tw-stock-ai Agent Workflows

本檔把專案常用技能固定成可檢查的流程，避免每次都靠臨時記憶。所有輸出僅供研究追蹤，不構成投資建議。

## Daily Taiwan Stock Monitor

用途：檢查每日網站更新、Telegram 推播、資料品質與排程健康。

建議使用技能：
- `github:gh-fix-ci`：GitHub Actions 失敗、Pages 未部署、workflow skipped。
- `verification-before-completion`：宣稱修好前，必須跑測試與查 Actions。
- `data-quality-checker`：資料源異常、快取補抓、空資料風險。
- `security-threat-model`：檢查 token、GitHub secrets、外部 API 暴露面。

驗證步驟：
- `python -m pytest`
- `gh run list --repo areschen2022-cmyk/tw-stock-ai-dashboard --limit 8`
- 檢查 `delivery_log` 是否有當日 `telegram / morning_report`
- 檢查 `dashboard/dashboard_data.json` 與 `docs/dashboard_data.json` 是否含最新 `delivery_status`

**Daily Taiwan Stock Monitor:**
1. Finance News → 檢查每日新聞與市場摘要是否正常。
2. Market News Analyst → 檢查題材新聞與催化是否合理。
3. Risk Management → 檢查危險名單、停損與追高風險。
4. Signal Postmortem → 檢查近期訊號 3/5/10 日成效。

## Stock Selection Quality Review

用途：審查「今日行動清單」、S+/S/A/B 分級、AI 自選股、危險名單是否互相矛盾。

建議使用技能：
- `technical-analysis`：技術面、突破、拉回、停損條件。
- `risk-management`：停損、追高、倉位與紅色警戒。
- `entry-signals`：進場條件與歷史勝率語氣。
- `signal-postmortem`：回看訊號 3/5/10 日成效。
- `exposure-coach`：市場過熱時降低追價曝險。

規則：
- S+/S/A/B 只代表訊號強度，不代表一定可以買。
- 真正操作以「今日操作結論」為主，並需符合開盤不過度跳空、量能延續、停損可控。
- AI 自選股維持嚴格共識：至少 5 個模型成功、5 票同意，才列為正式 AI 自選股。

**Stock Selection Quality Review:**
1. Technical Analysis → 檢查突破、拉回、量價與停損位置。
2. Entry Signals → 檢查進場條件是否可執行。
3. Risk Management → 檢查紅色警戒與避開名單。
4. Exposure Coach → 給出當日可承擔曝險層級。

## Retail Divergence Review

用途：每週檢查集保戶股權分散資料，輔助判斷籌碼是否轉乾淨或散戶過熱。

建議使用技能：
- `data-analysis`：檢查持股人數變化、價格背離、成交量門檻。
- `quantitative-research`：驗證散戶背離與後續 3/5/10 日報酬。
- `signal-postmortem`：追蹤散戶訊號後續成效。

規則：
- 強訊號才影響選股分數。
- 觀察訊號只顯示在 dashboard，不直接加減分。
- 若 `retail_holder_snapshots` 有資料但 `retail_holder_signals` 為 0，代表尚未符合門檻，不代表任務失敗。

**Retail Divergence Review:**
1. Data Analysis → 檢查集保戶人數變化、價格背離與成交量門檻。
2. Quantitative Research → 驗證散戶背離與後續報酬是否有統計價值。
3. Signal Postmortem → 追蹤強訊號與觀察訊號後續表現。

## News And Theme Radar

用途：檢查題材熱度、政策催化、SpaceX、被動元件、重電、網通光通訊等題材是否正確觸發。

建議使用技能：
- `market-news-analyst`：新聞題材摘要與催化判斷。
- `sector-analyst`：族群輪動與板塊強弱。
- `edge-hint-extractor`：從每日異常新聞與市場反應抽取可回測假說。
- `web-scraping`：新聞來源或公開資料格式改版時檢查抓取器。

規則：
- 題材新聞只作為候選池與加權依據，不可單獨成為買進理由。
- SpaceX 題材需區分「供應鏈核心」與「純概念聯想」。
- 公司名關鍵字應避免單獨觸發題材，需搭配產業詞或新聞上下文。

**News And Theme Radar:**
1. Market News Analyst → 檢查每日新聞催化與題材摘要。
2. Market Regimes → 檢查市場環境是否支持題材追價。
3. Edge Hint Extractor → 從異常新聞與市場反應抽出可回測假說。
4. Web Scraping → 檢查新聞來源格式變動與抓取風險。

## Token And Skill Hygiene

用途：減少重複上下文、避免技能重複或無效對接。

建議使用技能：
- `token-coach`：長對話前後壓縮重點。
- `markdown-token-optimizer`：壓縮規格文件與報告。
- `skill-integration-tester`：檢查本檔 workflow 是否有對應技能與觸發條件。
- `fleet-auditor`：檢查 agent/skill token 浪費。

規則：
- 優先使用已安裝且可信的 trading-skills，不重複安裝未知來源技能。
- 新技能需先看 `SKILL.md` 與來源，不把有交易執行權限或不明網路行為的技能接進專案。

**Token And Skill Hygiene:**
1. Token Coach → 長對話前後壓縮重點。
2. Markdown Token Optimizer → 壓縮規格文件與報告。
3. Fleet Auditor → 檢查 agent/skill token 浪費。
4. LLM Trading Agent Security → 檢查第三方技能、token 與外部 API 暴露面。
