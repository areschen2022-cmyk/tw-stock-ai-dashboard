from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.indicators.overseas import OverseasSentiment
from src.news.web_theme import ThemeSignal
from src.scoring.grade import grade_label
from src.scoring.score_engine import StockScore

TAIPEI = ZoneInfo("Asia/Taipei")


def _status_text(label: str) -> str:
    return {
        "BUY_WATCH": "買進觀察",
        "WAIT": "等待",
        "AVOID": "避開",
        "DATA_INSUFFICIENT": "資料不足",
    }.get(label, label)


def _grade(score: int) -> str:
    return grade_label(score)


def _first(reasons: list[str]) -> str:
    return reasons[0] if reasons else "無明顯訊號"


def _decision_reason(item: StockScore) -> str:
    parts = [item.trigger_summary]
    for key in ("technical", "chip", "fundamental", "risk", "opportunity"):
        reason = _first(item.reasons.get(key, []))
        if reason != "無明顯訊號" and reason not in parts:
            parts.append(reason)
        if len(parts) >= 4:
            break
    return "；".join(parts)


def _build_health_status(
    as_of: date,
    source_status: dict | None,
    theme_signal: ThemeSignal | None,
) -> dict:
    generated_at = datetime.now(TAIPEI)
    provider_label = str((source_status or {}).get("label", "未知"))
    news_sources = theme_signal.source_count if theme_signal else 0
    news_failed = theme_signal.failed_count if theme_signal else 0

    if provider_label in {"錯誤", "限流"} or news_sources == 0:
        label = "異常"
    elif provider_label == "部分限流" or news_failed > 0:
        label = "部分延遲"
    else:
        label = "正常"

    return {
        "label": label,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "generated_date": generated_at.date().isoformat(),
        "data_date": as_of.isoformat(),
        "website_schedule": "08:08",
        "telegram_schedule": "08:28",
        "provider_label": provider_label,
        "news_sources": news_sources,
        "news_failed": news_failed,
        "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
        "github_event": os.getenv("GITHUB_EVENT_NAME", "local"),
    }


def build_dashboard_payload(
    scores: list[StockScore],
    as_of: date,
    market_summary: str,
    market_warning: str | None,
    config: dict,
    overseas: OverseasSentiment | None,
    theme_signal: ThemeSignal | None,
    source_status: dict | None = None,
    alerts: list[str] | None = None,
    watch_reviews: list[dict] | None = None,
    exit_risks: list[dict] | None = None,
) -> dict:
    stock_names = config.get("stock_names", {})
    rows = []
    for item in sorted(scores, key=lambda score: score.total_score, reverse=True):
        rows.append(
            {
                "stock_id": item.stock_id,
                "name": stock_names.get(item.stock_id, "名稱未設定"),
                "score": item.total_score,
                "grade": _grade(item.total_score),
                "label": item.label,
                "label_text": _status_text(item.label),
                "price": item.price,
                "technical": _first(item.reasons.get("technical", [])),
                "chip": _first(item.reasons.get("chip", [])),
                "fundamental": _first(item.reasons.get("fundamental", [])),
                "risk": _first(item.reasons.get("risk", [])),
                "opportunity": _first(item.reasons.get("opportunity", [])),
                "action": item.action or "只觀察",
                "entry_condition": item.entry_condition or "資料不足，暫不設進場條件",
                "stop_reference": item.stop_reference or "資料不足，暫不設停損參考",
                "stop_price": item.stop_price,
                "entry_limit_price": item.entry_limit_price,
                "themes": item.themes,
                "theme_tiers": item.theme_tiers,
                "overseas_adjustment": item.overseas_adjustment,
                "opportunity_score": item.opportunity_score,
                "warnings": item.warnings,
                "trigger_tags": item.trigger_tags,
                "trigger_summary": item.trigger_summary,
                "decision_reason": _decision_reason(item),
            }
        )
    valid = [row for row in rows if row["label"] != "DATA_INSUFFICIENT"]
    return {
        "as_of": as_of.isoformat(),
        "market": {"summary": market_summary, "warning": market_warning},
        "overseas": {
            "label": overseas.label if overseas else "未納入",
            "summary": overseas.summary if overseas else "未納入",
            "reasons": overseas.reasons if overseas else [],
            "sector_impacts": overseas.sector_impacts if overseas else [],
        },
        "themes": {
            "summary": theme_signal.summary if theme_signal else "未納入",
            "active": theme_signal.active_themes if theme_signal else [],
            "headlines": theme_signal.headlines[:8] if theme_signal else [],
            "scores": theme_signal.scores if theme_signal else {},
            "names": {key: value.get("name", key) for key, value in config.get("theme_pools", {}).items()},
            "pool_counts": {
                key: len(value.get("stocks", {}))
                for key, value in config.get("theme_pools", {}).items()
            },
            "momentum": {
                key: {
                    "today": mom.today,
                    "avg_3d": round(mom.avg_3d, 1),
                    "trend": mom.trend,
                    "history": mom.history[:7],
                }
                for key, mom in (theme_signal.momentum or {}).items()
            } if theme_signal else {},
            "policy": {
                "summary": theme_signal.policy.summary,
                "theme_boosts": theme_signal.policy.theme_boosts,
                "matched_headlines": theme_signal.policy.matched_headlines,
            } if theme_signal and theme_signal.policy else {
                "summary": "未納入",
                "theme_boosts": {},
                "matched_headlines": {},
            },
        },
        "source_status": source_status or {"label": "未知"},
        "health": _build_health_status(as_of, source_status, theme_signal),
        "alerts": alerts or [],
        "watch_reviews": watch_reviews or [],
        "exit_risks": exit_risks or [],
        "summary": {
            "scanned": len(rows),
            "valid": len(valid),
            "s_plus_grade": sum(1 for row in valid if row["grade"] == "S+"),
            "s_grade": sum(1 for row in valid if row["grade"] == "S"),
            "a_grade": sum(1 for row in valid if row["grade"] == "A"),
            "b_grade": sum(1 for row in valid if row["grade"] == "B"),
            "data_insufficient": len(rows) - len(valid),
        },
        "rows": rows,
    }


def write_dashboard(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "dashboard_data.json").write_text(json_text, encoding="utf-8")
    # Embed data inline so the file works when opened via file:// without a server
    safe_json = json_text.replace("</script>", r"<\/script>")
    inline_script = f"window.__DASHBOARD_DATA__ = {safe_json};"
    html = _html().replace(
        "/* __INLINE_DATA_SENTINEL__ */",
        inline_script,
    )
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def write_performance(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "performance_data.json").write_text(json_text, encoding="utf-8")
    # Embed data inline so the file works when opened via file:// without a server
    safe_json = json_text.replace("</script>", r"<\/script>")
    inline_script = f"window.__PERFORMANCE_DATA__ = {safe_json};"
    html = _performance_html().replace(
        "/* __INLINE_PERF_SENTINEL__ */",
        inline_script,
    )
    (output_dir / "performance.html").write_text(html, encoding="utf-8")


def write_theme_history(payload: dict[str, list[dict]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / "theme_history.json").write_text(json_text, encoding="utf-8")


def _html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 開盤前監控</title>
  <style>
    :root { color-scheme: light; --ink:#18202a; --muted:#667085; --line:#d9dee7; --bg:#f6f7f9; --panel:#fff; --good:#0f7b4f; --warn:#9a6700; --bad:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: "Segoe UI", Arial, sans-serif; color:var(--ink); background:var(--bg); }
    header { padding:20px 24px 12px; border-bottom:1px solid var(--line); background:var(--panel); position:sticky; top:0; z-index:2; }
    h1 { margin:0 0 8px; font-size:24px; letter-spacing:0; }
    .sub { color:var(--muted); font-size:14px; }
    main { padding:18px 24px 32px; max-width:1320px; margin:auto; }
    .metrics { display:grid; grid-template-columns: repeat(7, minmax(110px,1fr)); gap:10px; margin-bottom:16px; }
    .metric { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }
    .metric b { display:block; font-size:clamp(18px, 4vw, 22px); margin-bottom:2px; overflow-wrap:anywhere; }
    .metric span { color:var(--muted); font-size:13px; }
    .bands { display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:16px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }
    h2 { font-size:16px; margin:0 0 10px; }
    .line { color:var(--muted); margin:5px 0; font-size:14px; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:14px 0; flex-wrap:wrap; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:8px 14px; border:1px solid var(--line); border-radius:6px; background:var(--panel); color:#0b4a8b; text-decoration:none; font-weight:700; }
    .nav-tab.active { background:#0b4a8b; color:white; border-color:#0b4a8b; }
    input, select { border:1px solid var(--line); border-radius:6px; padding:9px 10px; background:white; min-height:38px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .chart-wrap { height:180px; margin-top:8px; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; font-size:12px; color:#475467; }
    .grade { font-weight:700; border-radius:999px; padding:3px 8px; display:inline-block; min-width:32px; text-align:center; }
    .grade-S\+ { color:white; background:#7c2d12; }
    .grade-S { color:white; background:#b42318; }
    .grade-A { color:white; background:var(--good); }
    .grade-B { color:#3b2f00; background:#f6d365; }
    .grade-C { color:#344054; background:#e4e7ec; }
    .grade-- { color:#667085; background:#f2f4f7; }
    .small { color:var(--muted); font-size:12px; margin-top:3px; }
    .themes { color:#175cd3; }
    a.stock-link { color:#0b4a8b; text-decoration:none; }
    a.stock-link:hover { text-decoration:underline; }
    .bad { color:var(--bad); }
    .warn { color:var(--warn); }
    .good { color:var(--good); }
    .status-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; background:#98a2b3; }
    .status-ok { background:var(--good); }
    .status-warn { background:var(--warn); }
    .status-bad { background:var(--bad); }
    .tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:4px; }
    .tag { display:inline-block; padding:2px 7px; border-radius:999px; font-size:11px; font-weight:600; white-space:nowrap; }
    .tag-theme  { background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; }
    .tag-chip   { background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; }
    .tag-tech   { background:#fff7ed; color:#9a3412; border:1px solid #fed7aa; }
    .tag-fund   { background:#fdf4ff; color:#7e22ce; border:1px solid #e9d5ff; }
    .tag-over   { background:#f0f9ff; color:#0c4a6e; border:1px solid #bae6fd; }
    .tag-default{ background:#f8fafc; color:#475467; border:1px solid #e2e8f0; }
    @media (max-width: 900px) {
      header { position:static; }
      main, header { padding-left:12px; padding-right:12px; }
      .metrics, .bands { grid-template-columns:1fr; }
      .toolbar { align-items:stretch; }
      input, select { width:100%; min-width:0; }
      table, thead, tbody, tr, td { display:block; width:100%; }
      thead { display:none; }
      table { border:0; background:transparent; }
      tr { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin-bottom:10px; padding:10px; }
      td { border:0; padding:5px 0; font-size:13px; }
      td::before { content: attr(data-label); display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
      td:first-child { float:left; width:42px; padding-top:0; }
      td:nth-child(2) { margin-left:52px; min-height:42px; padding-top:0; }
      td:nth-child(3) { clear:both; }
    }
  </style>
</head>
<body>
  <header>
    <h1>台股 AI 開盤前監控</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab active" href="index.html">今日監控</a>
      <a class="nav-tab" href="performance.html">訊號成效</a>
    </nav>
    <div class="metrics" id="metrics"></div>
    <div class="bands">
      <section><h2>市場風向</h2><div id="market"></div></section>
      <section><h2>健康狀態</h2><div id="health"></div></section>
      <section><h2>新聞題材</h2><div id="themes"></div></section>
      <section><h2>異常提醒</h2><div id="alerts"></div></section>
      <section><h2>危險名單</h2><div id="exitRisks"></div></section>
      <section><h2>觀察追蹤</h2><div id="watchReviews"></div></section>
    </div>
    <div class="toolbar">
      <input id="search" placeholder="搜尋股票、題材、訊號..." />
      <select id="grade"><option value="">全部級別</option><option>S+</option><option>S</option><option>A</option><option>B</option><option>C</option><option value="-">資料不足</option></select>
    </div>
    <table>
      <thead><tr><th>級別</th><th>股票</th><th>分數</th><th>原因標籤</th><th>題材</th><th>四面向</th><th>操作</th><th>進場/停損</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    const chartScript = document.createElement("script");
    chartScript.src = "https://cdn.jsdelivr.net/npm/chart.js";
    chartScript.defer = true;
    document.head.appendChild(chartScript);
    /* __INLINE_DATA_SENTINEL__ */
    let data = null;
    let themeHistory = null;
    let themeChart = null;
    const cls = g => "grade grade-" + (g === "-" ? "-" : g);
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
    const TAG_CLASS = {
      "題材": "tag-theme", "法人": "tag-chip", "外資": "tag-chip", "投信": "tag-chip",
      "突破": "tag-tech",  "趨勢": "tag-tech",  "技術": "tag-tech",
      "營收": "tag-fund",
      "美股": "tag-over",  "海外": "tag-over",
    };
    function tagClass(tag) {
      for (const [kw, cls] of Object.entries(TAG_CLASS)) {
        if (tag.includes(kw)) return "tag " + cls;
      }
      return "tag tag-default";
    }
    function renderTags(tags) {
      if (!tags || !tags.length) return '<span class="tag tag-default">綜合訊號</span>';
      return tags.map(t => `<span class="${tagClass(t)}">${esc(t)}</span>`).join("");
    }
    function render() {
      const q = document.querySelector("#search").value.trim().toLowerCase();
      const g = document.querySelector("#grade").value;
      document.querySelector("#subtitle").textContent = `${data.as_of}｜僅供研究追蹤，不是投資建議`;
      document.querySelector("#metrics").innerHTML = [
        ["掃描", data.summary.scanned],
        ["有效", data.summary.valid],
        ["S+級", data.summary.s_plus_grade || 0],
        ["S級", data.summary.s_grade || 0],
        ["A級", data.summary.a_grade],
        ["B級", data.summary.b_grade],
        ["資料不足", data.summary.data_insufficient]
      ].map(([k,v]) => `<div class="metric"><b>${v}</b><span>${k}</span></div>`).join("");
      document.querySelector("#market").innerHTML = `
        <div class="line">台股：${esc(data.market.summary)}</div>
        <div class="line">海外：${esc(data.overseas.label)}｜${esc(data.overseas.summary)}</div>
        ${(data.overseas.sector_impacts || []).slice(0,2).map(x => `<div class="line">映射：${esc(x.symbol)} ${Number(x.change_pct).toFixed(2)}% → ${esc(x.sector)}｜${esc(x.stocks)}</div>`).join("")}
        <div class="line"><span class="${sourceClass(data.source_status.label)}"></span>資料源：${esc(data.source_status.label)}｜API ${data.source_status.api || 0}｜快取 ${data.source_status.cache || 0}｜限流 ${data.source_status.quota || 0}</div>
        ${data.market.warning ? `<div class="line bad">提醒：${esc(data.market.warning)}</div>` : ""}`;
      const health = data.health || {};
      const healthCls = health.label === "正常" ? "good" : (health.label === "部分延遲" ? "warn" : "bad");
      document.querySelector("#health").innerHTML = `
        <div class="line ${healthCls}"><span class="${sourceClass(health.label === "正常" ? "正常" : health.label === "部分延遲" ? "部分限流" : "錯誤")}"></span>系統：${esc(health.label || "未知")}</div>
        <div class="line">本次產生：${esc((health.generated_at || "").replace("T", " "))}</div>
        <div class="line">資料日期：${esc(health.data_date || data.as_of)}｜網站 ${esc(health.website_schedule || "08:08")}｜Telegram ${esc(health.telegram_schedule || "08:28")}</div>
        <div class="line">新聞來源：成功 ${health.news_sources || 0}｜失敗 ${health.news_failed || 0}</div>
        <div class="line">執行環境：${esc(health.github_event || "local")}${health.github_run_id ? `｜Run ${esc(health.github_run_id)}` : ""}</div>`;
      function sparkBar(history) {
        const bars = "▁▂▃▄▅▆▇█";
        if (!history || !history.length) return "—";
        const max = Math.max(...history, 1);
        return [...history].slice(0, 7).reverse().map(v =>
          v === 0 ? "·" : bars[Math.min(7, Math.round((v / max) * 7))]
        ).join("");
      }
      function trendStyle(trend) {
        if (!trend) return "";
        if (trend.indexOf("急升") >= 0) return "color:#b42318;font-weight:700";
        if (trend.indexOf("升溫") >= 0) return "color:#0f7b4f;font-weight:600";
        if (trend.indexOf("降溫") >= 0) return "color:var(--muted)";
        if (trend.indexOf("消退") >= 0) return "color:#98a2b3";
        return "";
      }
      const momentum = data.themes.momentum || {};
      const allThemeEntries = Object.entries(data.themes.scores || {})
        .filter(([key, score]) => score > 0 || (momentum[key] && momentum[key].avg_3d > 0))
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6);
      const themeTableBody = allThemeEntries.map(([key, score]) => {
        const mom = momentum[key] || {};
        const trend = mom.trend || "-";
        const avg3d = mom.avg_3d != null ? Number(mom.avg_3d).toFixed(1) : "-";
        const spark = sparkBar(mom.history);
        return `<tr style="font-size:12px">` +
          `<td style="padding:3px 5px;color:#175cd3">${esc(data.themes.names[key] || key)}</td>` +
          `<td style="padding:3px 5px;text-align:center">${score}</td>` +
          `<td style="padding:3px 5px;text-align:center;color:var(--muted)">${avg3d}</td>` +
          `<td style="padding:3px 5px;${trendStyle(trend)}">${esc(trend)}</td>` +
          `<td style="padding:3px 5px;letter-spacing:1px;font-family:monospace;color:#475467">${spark}</td>` +
          `</tr>`;
      }).join("");
      const themeHdr = `<thead><tr style="font-size:11px;color:var(--muted)">` +
        `<th style="padding:2px 5px;text-align:left;font-weight:600">題材</th>` +
        `<th style="padding:2px 5px;font-weight:600">今日</th>` +
        `<th style="padding:2px 5px;font-weight:600">3日均</th>` +
        `<th style="padding:2px 5px;font-weight:600">趨勢</th>` +
        `<th style="padding:2px 5px;font-weight:600">近7日▶</th>` +
        `</tr></thead>`;
      const themeTableHtml = themeTableBody
        ? `<table style="width:100%;border-collapse:collapse;margin:5px 0 4px">${themeHdr}<tbody>${themeTableBody}</tbody></table>`
        : "";
      document.querySelector("#themes").innerHTML = `
        <div class="line">熱門：${esc(data.themes.summary)}</div>
        <div class="line">政策：${esc(data.themes.policy?.summary || "未偵測到明顯政策訊號")}</div>
        ${themeTableHtml}
        <div class="chart-wrap"><canvas id="themeHistoryChart" aria-label="題材熱度歷史圖"></canvas></div>
        ${data.themes.headlines.slice(0,2).map(h => `<div class="line" style="font-size:12px">- ${esc(h)}</div>`).join("")}`;
      renderThemeHistoryChart();
      document.querySelector("#alerts").innerHTML = (data.alerts || []).length
        ? data.alerts.map(a => `<div class="line bad">- ${esc(a)}</div>`).join("")
        : `<div class="line">目前無重大異常</div>`;
      document.querySelector("#exitRisks").innerHTML = (data.exit_risks || []).length
        ? data.exit_risks.slice(0,5).map(x => {
            const cls = x.level === "紅色警戒" ? "bad" : "warn";
            return `<div class="line ${cls}">${esc(x.stock_id)} ${esc(x.name)}｜${esc(x.level)}｜${esc((x.reasons || []).slice(0,2).join("、"))}<div class="small">${esc(x.action || "")}</div></div>`;
          }).join("")
        : `<div class="line">目前無紅黃警戒</div>`;
      document.querySelector("#watchReviews").innerHTML = (data.watch_reviews || []).length
        ? data.watch_reviews.slice(0,4).map(w => `<div class="line">${esc(w.stock_id)} ${esc(w.name)}：${w.change_pct >= 0 ? "+" : ""}${Number(w.change_pct).toFixed(1)}%｜現分 ${w.current_score}/100</div>`).join("")
        : `<div class="line">尚無可追蹤觀察名單</div>`;
      const rows = data.rows.filter(r => {
        const blob = JSON.stringify(r).toLowerCase();
        return (!q || blob.includes(q)) && (!g || r.grade === g);
      });
      document.querySelector("#rows").innerHTML = rows.map(r => `
        <tr>
          <td data-label="級別"><span class="${cls(r.grade)}">${r.grade}</span></td>
          <td data-label="股票"><b><a class="stock-link" href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a></b><div class="small">${esc(r.label_text)}｜收 ${r.price ?? "-"}</div></td>
          <td data-label="分數"><b>${r.score}/100</b><div class="small">海外 ${r.overseas_adjustment >= 0 ? "+" : ""}${r.overseas_adjustment}｜機會 ${r.opportunity_score}</div></td>
          <td data-label="原因標籤"><div class="tags">${renderTags(r.trigger_tags)}</div></td>
          <td data-label="題材" class="themes">${esc((r.theme_tiers || []).join(" / ") || (r.themes || []).join(" / ") || "-")}</td>
          <td data-label="四面向">
            <div class="small">技術：${esc(r.technical || "無明顯訊號")}</div>
            <div class="small">籌碼：${esc(r.chip || "無明顯訊號")}</div>
            <div class="small">基本：${esc(r.fundamental || "無明顯訊號")}</div>
            <div class="small">風險：${esc(r.risk || "無明顯訊號")}</div>
            <div class="small">入選：${esc(r.decision_reason || r.trigger_summary || "綜合訊號")}</div>
          </td>
          <td data-label="操作"><b>${esc(r.action || "只觀察")}</b></td>
          <td data-label="進場/停損">
            ${r.entry_limit_price != null ? `<div><b>📌 進場上限：${r.entry_limit_price}</b></div>` : ""}
            ${r.stop_price != null ? `<div style="color:var(--bad)"><b>🔴 止損：${r.stop_price}</b></div>` : ""}
            <div class="small">${esc(r.entry_condition || "資料不足，暫不設進場條件")}</div>
            <div class="small">${esc(r.stop_reference || "資料不足，暫不設停損參考")}</div>
          </td>
        </tr>`).join("");
    }
    function sourceClass(label) {
      const base = "status-dot ";
      if (label === "正常") return base + "status-ok";
      if (label === "部分限流" || label === "限流") return base + "status-warn";
      if (label === "錯誤") return base + "status-bad";
      return base;
    }
    function renderThemeHistoryChart() {
      const canvas = document.querySelector("#themeHistoryChart");
      if (!canvas || !themeHistory || !window.Chart) return;
      const names = data.themes.names || {};
      const activeKeys = Object.keys(themeHistory)
        .filter(key => (themeHistory[key] || []).some(row => Number(row.score) > 0))
        .slice(0, 6);
      if (!activeKeys.length) return;
      const dates = [...new Set(activeKeys.flatMap(key => (themeHistory[key] || []).map(row => row.date)))]
        .sort()
        .slice(-14);
      const palette = ["#0b4a8b", "#b42318", "#0f7b4f", "#9a6700", "#7e22ce", "#475467"];
      const datasets = activeKeys.map((key, idx) => {
        const map = Object.fromEntries((themeHistory[key] || []).map(row => [row.date, Number(row.score || 0)]));
        return {
          label: names[key] || key,
          data: dates.map(date => map[date] || 0),
          borderColor: palette[idx % palette.length],
          backgroundColor: palette[idx % palette.length],
          tension: 0.25,
        };
      });
      if (themeChart) themeChart.destroy();
      themeChart = new Chart(canvas, {
        type: "line",
        data: { labels: dates, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      });
    }
    if (window.__DASHBOARD_DATA__ && window.__DASHBOARD_DATA__ !== null) {
      data = window.__DASHBOARD_DATA__;
      render();
    } else {
      fetch("dashboard_data.json")
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(json => { data = json; render(); })
        .catch(err => {
          document.querySelector("#subtitle").textContent = "資料載入失敗";
          document.querySelector("#metrics").innerHTML = "";
          document.querySelector("#market").innerHTML = `<div class="line bad">dashboard_data.json 載入失敗：${esc(err.message)}</div>`;
        });
    }
    document.querySelector("#search").addEventListener("input", render);
    document.querySelector("#grade").addEventListener("change", render);
    fetch("theme_history.json")
      .then(r => r.ok ? r.json() : {})
      .then(json => {
        themeHistory = json;
        if (window.Chart) renderThemeHistoryChart();
        chartScript.addEventListener("load", renderThemeHistoryChart, { once:true });
      })
      .catch(() => {});
  </script>
</body>
</html>"""


def _performance_html() -> str:
    return r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>台股 AI 訊號成效追蹤</title>
  <style>
    :root { color-scheme: light; --ink:#18202a; --muted:#667085; --line:#d9dee7; --bg:#f6f7f9; --panel:#fff; --good:#0f7b4f; --bad:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Segoe UI", Arial, sans-serif; color:var(--ink); background:var(--bg); }
    header { padding:20px 24px 12px; border-bottom:1px solid var(--line); background:var(--panel); }
    h1 { margin:0 0 8px; font-size:24px; }
    .sub, .small { color:var(--muted); font-size:13px; }
    main { padding:18px 24px 32px; max-width:1320px; margin:auto; }
    .metrics { display:grid; grid-template-columns:repeat(6,minmax(120px,1fr)); gap:10px; margin-bottom:16px; }
    .metric { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }
    .metric b { display:block; font-size:clamp(18px, 4vw, 22px); margin-bottom:2px; overflow-wrap:anywhere; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:14px 0; flex-wrap:wrap; }
    .nav-tabs { display:flex; gap:8px; margin:0 0 16px; flex-wrap:wrap; }
    .nav-tab { display:inline-flex; align-items:center; justify-content:center; min-height:38px; padding:8px 14px; border:1px solid var(--line); border-radius:6px; background:var(--panel); color:#0b4a8b; text-decoration:none; font-weight:700; }
    .nav-tab.active { background:#0b4a8b; color:white; border-color:#0b4a8b; }
    input, select { border:1px solid var(--line); border-radius:6px; padding:9px 10px; background:white; min-height:38px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .analysis-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }
    h2 { font-size:16px; margin:0 0 8px; }
    .note { color:var(--muted); font-size:12px; margin:0 0 10px; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; font-size:12px; color:#475467; }
    a { color:#0b4a8b; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .pos { color:var(--good); font-weight:700; }
    .neg { color:var(--bad); font-weight:700; }
    @media (max-width:1100px) {
      .metrics { grid-template-columns:repeat(3,1fr); }
    }
    @media (max-width:900px) {
      main, header { padding-left:12px; padding-right:12px; }
      .metrics { grid-template-columns:1fr 1fr; }
      .analysis-grid { grid-template-columns:1fr; }
      input, select { width:100%; min-width:0; }
      table, thead, tbody, tr, td { display:block; width:100%; }
      thead { display:none; }
      table { border:0; background:transparent; }
      tr { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin-bottom:10px; padding:10px; }
      td { border:0; padding:5px 0; }
      td::before { content:attr(data-label); display:block; color:var(--muted); font-size:11px; margin-bottom:2px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>台股 AI 訊號成效追蹤</h1>
    <div class="sub" id="subtitle">載入中...</div>
  </header>
  <main>
    <nav class="nav-tabs" aria-label="頁面切換">
      <a class="nav-tab" href="index.html">今日監控</a>
      <a class="nav-tab active" href="performance.html">訊號成效</a>
    </nav>
    <div class="metrics" id="metrics"></div>
    <div class="analysis-grid">
      <section>
        <h2>題材成效</h2>
        <div class="note">同一訊號若屬於多個題材，會分別計入各題材統計。<b>停損</b>欄 = 訊號發出後 5 日內股價觸及或跌破預設止損價的比率（<b>越低越好</b>，代表止損設定合理、未被提前出場）。</div>
        <table>
          <thead><tr><th>題材</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th><th>停損</th></tr></thead>
          <tbody id="themeStats"></tbody>
        </table>
      </section>
      <section>
        <h2>分數區間</h2>
        <div class="note">僅顯示資料，不自動調整 BUY/WATCH 門檻；目前只追蹤 BUY_WATCH（65 分以上）訊號，勝率定義為 5 日報酬 > 0%。</div>
        <table>
          <thead><tr><th>區間</th><th>訊號</th><th>完成</th><th>5日勝率</th><th>5日平均</th></tr></thead>
          <tbody id="scoreBands"></tbody>
        </table>
      </section>
    </div>
  <section>
      <h2>進場條件分析</h2>
      <div class="note">比較進場條件是否對報酬有正向影響；樣本不足時數據僅供參考。</div>
      <table>
        <thead><tr><th>類型</th><th>筆數</th><th>5日勝率</th><th>5日平均報酬</th></tr></thead>
        <tbody id="entryAnalysis"></tbody>
      </table>
    </section>
    <section style="margin-bottom:16px;">
      <h2>Signal Lab：級別驗證</h2>
      <div class="note">離線驗證 S+/S/A/B 各級別在 3 日、5 日、10 日後的平均表現；樣本未滿 30 筆前僅供觀察。</div>
      <table>
        <thead><tr><th>級別</th><th>訊號</th><th>3日勝率</th><th>3日平均</th><th>5日勝率</th><th>5日平均</th><th>10日勝率</th><th>10日平均</th></tr></thead>
        <tbody id="signalLab"></tbody>
      </table>
    </section>
    <div class="toolbar">
      <input id="search" placeholder="搜尋股票、日期、狀態..." />
      <select id="grade"><option value="">全部級別</option><option>S+</option><option>S</option><option>A</option><option>B</option><option>C</option></select>
      <select id="status"><option value="">全部狀態</option><option>已完成</option><option>進行中</option></select>
    </div>
    <table>
      <thead><tr><th>訊號日</th><th>股票</th><th>級別</th><th>分數</th><th>訊號價</th><th>進場觸發</th><th>3日漲跌</th><th>5日漲跌</th><th>停損觸及</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    /* __INLINE_PERF_SENTINEL__ */
    let data = null;
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
    const fmtPct = value => value === null || value === undefined ? "—" : `<span class="${value >= 0 ? "pos" : "neg"}">${value >= 0 ? "+" : ""}${Number(value).toFixed(1)}%</span>`;
    const fmtNeutralPct = value => value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;
    const fmtBool = value => value === null || value === undefined ? "—" : (value ? "是" : "否");
    function metric(label, value, suffix="") {
      return `<div class="metric"><b>${value ?? "—"}${value === null || value === undefined ? "" : suffix}</b><span>${label}</span></div>`;
    }
    function render() {
      const stats = data.stats || {};
      document.querySelector("#subtitle").textContent = `${data.as_of}｜近 ${data.days} 天｜僅供研究追蹤`;
      document.querySelector("#metrics").innerHTML = [
        metric("訊號總數", stats.signals),
        metric("已完成", stats.completed),
        metric("5日勝率", stats.win_rate_5d?.toFixed(1), "%"),
        metric("5日平均", stats.avg_return_5d?.toFixed(1), "%"),
        `<div class="metric" title="訊號發出後 5 日內，股價觸及或跌破預設止損價的比率。越低代表止損設定越合理、訊號品質越佳。"><b>${stats.stop_hit_rate?.toFixed(1) ?? "—"}${stats.stop_hit_rate != null ? "%" : ""}</b><span>停損觸及率</span><div style="color:var(--muted);font-size:11px;margin-top:2px;">↓ 越低越好</div></div>`,
        metric("A級5日勝率", stats.a_win_rate_5d?.toFixed(1), "%"),
      ].join("");
      document.querySelector("#themeStats").innerHTML = (data.theme_stats || []).length
        ? data.theme_stats.map(r => `
          <tr>
            <td data-label="題材">${esc(r.label)}</td>
            <td data-label="訊號">${esc(r.signals)}</td>
            <td data-label="完成">${esc(r.completed)}</td>
            <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
            <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
            <td data-label="停損">${fmtNeutralPct(r.stop_hit_rate)}</td>
          </tr>
        `).join("")
        : `<tr><td data-label="題材" colspan="6">尚無題材統計資料</td></tr>`;
      document.querySelector("#scoreBands").innerHTML = (data.score_bands || []).map(r => `
        <tr>
          <td data-label="區間">${esc(r.label)}</td>
          <td data-label="訊號">${esc(r.signals)}</td>
          <td data-label="完成">${esc(r.completed)}</td>
          <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
          <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
        </tr>
      `).join("");
      const entry = data.entry_analysis || {};
      document.querySelector("#entryAnalysis").innerHTML = [
        ["有觸發進場", entry.triggered],
        ["未觸發進場", entry.not_triggered],
      ].map(([label, row]) => `
        <tr>
          <td data-label="類型">${esc(label)}</td>
          <td data-label="筆數">${esc(row?.count ?? 0)}</td>
          <td data-label="5日勝率">${fmtPct(row?.win_rate_5d)}</td>
          <td data-label="5日平均報酬">${fmtPct(row?.avg_return_5d)}</td>
        </tr>
      `).join("");
      document.querySelector("#signalLab").innerHTML = (data.signal_lab || []).map(r => `
        <tr>
          <td data-label="級別">${esc(r.grade)}</td>
          <td data-label="訊號">${esc(r.signals)}</td>
          <td data-label="3日勝率">${fmtPct(r.win_rate_3d)}</td>
          <td data-label="3日平均">${fmtPct(r.avg_return_3d)}</td>
          <td data-label="5日勝率">${fmtPct(r.win_rate_5d)}</td>
          <td data-label="5日平均">${fmtPct(r.avg_return_5d)}</td>
          <td data-label="10日勝率">${fmtPct(r.win_rate_10d)}</td>
          <td data-label="10日平均">${fmtPct(r.avg_return_10d)}</td>
        </tr>
      `).join("");
      const q = document.querySelector("#search").value.trim().toLowerCase();
      const grade = document.querySelector("#grade").value;
      const status = document.querySelector("#status").value;
      const rows = (data.items || []).filter(r => {
        const blob = JSON.stringify(r).toLowerCase();
        return (!q || blob.includes(q)) && (!grade || r.grade === grade) && (!status || r.status === status);
      });
      document.querySelector("#rows").innerHTML = rows.map(r => `
        <tr>
          <td data-label="訊號日">${esc(r.signal_date)}</td>
          <td data-label="股票"><a href="https://www.wantgoo.com/stock/${esc(r.stock_id)}" target="_blank" rel="noopener noreferrer">${esc(r.stock_id)} ${esc(r.name)}</a><div class="small">${esc(r.status)}</div></td>
          <td data-label="級別">${esc(r.grade)}</td>
          <td data-label="分數">${esc(r.total_score)}/100</td>
          <td data-label="訊號價">${r.entry_price ?? "—"}</td>
          <td data-label="進場觸發">${fmtBool(r.entry_triggered)}</td>
          <td data-label="3日漲跌">${fmtPct(r.return_3d)}</td>
          <td data-label="5日漲跌">${fmtPct(r.return_5d)}${r.return_10d != null ? `<div class="small">10日 ${fmtPct(r.return_10d)}</div>` : ""}</td>
          <td data-label="停損觸及">${fmtBool(r.stop_hit)}</td>
        </tr>
      `).join("");
    }
    if (window.__PERFORMANCE_DATA__ && window.__PERFORMANCE_DATA__ !== null) {
      data = window.__PERFORMANCE_DATA__;
      render();
    } else {
      fetch("performance_data.json")
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(json => { data = json; render(); })
        .catch(err => {
          document.querySelector("#subtitle").textContent = "資料載入失敗";
          document.querySelector("#metrics").innerHTML = `<div class="metric"><b>錯誤</b><span>${esc(err.message)}</span></div>`;
        });
    }
    document.querySelector("#search").addEventListener("input", render);
    document.querySelector("#grade").addEventListener("change", render);
    document.querySelector("#status").addEventListener("change", render);
  </script>
</body>
</html>"""
