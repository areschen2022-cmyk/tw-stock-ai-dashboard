# 專案操作偏好

- 任何完成後會影響網站、排程、資料或報表的更新，都要提交並推送到 GitHub，讓 GitHub Pages 與每日排程使用同一份最新內容。
- 本機測試可以先產生資料，但最終交付以 GitHub 上的 `main` 分支與 GitHub Pages 公開網址為準。
- 不把 `.env`、Telegram token、FinMind token 或其他金鑰寫入 repo。
- 每次優化後固定執行 `scripts\post_optimization_finalize.bat`，它會檢查語法、測試、dashboard 健康、亂碼、智慧庫匯出與 verification loop。
- 若 `dashboard/post_optimization_finalize.json` 的 `status` 不是 `ok`，要先修正問題再回報完成。
- 智慧庫匯出預設寫入 `C:\Users\User\trading_knowledge_hub\data\knowledge_points.jsonl`；若未來更換路徑，優先用 `TRADING_KNOWLEDGE_HUB_FILE` 或腳本參數覆寫。
