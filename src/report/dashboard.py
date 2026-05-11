from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.indicators.overseas import OverseasSentiment
from src.news.web_theme import ThemeSignal
from src.scoring.score_engine import StockScore


def _status_text(label: str) -> str:
    return {
        "BUY_WATCH": "買進觀察",
        "WAIT": "等待",
        "AVOID": "避開",
        "DATA_INSUFFICIENT": "資料不足",
    }.get(label, label)


def _grade(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "-"


def _first(reasons: list[str]) -> str:
    return reasons[0] if reasons else "無明顯訊號"


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
                "themes": item.themes,
                "theme_tiers": item.theme_tiers,
                "overseas_adjustment": item.overseas_adjustment,
                "opportunity_score": item.opportunity_score,
                "warnings": item.warnings,
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
        },
        "source_status": source_status or {"label": "未知"},
        "alerts": alerts or [],
        "watch_reviews": watch_reviews or [],
        "summary": {
            "scanned": len(rows),
            "valid": len(valid),
            "a_grade": sum(1 for row in valid if row["grade"] == "A"),
            "b_grade": sum(1 for row in valid if row["grade"] == "B"),
            "data_insufficient": len(rows) - len(valid),
        },
        "rows": rows,
    }


def write_dashboard(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dashboard_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "dashboard.html").write_text(_html(), encoding="utf-8")


def write_performance(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "performance_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "performance.html").write_text(_performance_html(), encoding="utf-8")


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
    .metrics { display:grid; grid-template-columns: repeat(5, minmax(120px,1fr)); gap:10px; margin-bottom:16px; }
    .metric { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }
    .metric b { display:block; font-size:22px; margin-bottom:2px; }
    .metric span { color:var(--muted); font-size:13px; }
    .bands { display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:16px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }
    h2 { font-size:16px; margin:0 0 10px; }
    .line { color:var(--muted); margin:5px 0; font-size:14px; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:14px 0; flex-wrap:wrap; }
    input, select { border:1px solid var(--line); border-radius:6px; padding:9px 10px; background:white; min-height:38px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; font-size:12px; color:#475467; }
    .grade { font-weight:700; border-radius:999px; padding:3px 8px; display:inline-block; min-width:32px; text-align:center; }
    .grade-A { color:white; background:var(--good); }
    .grade-B { color:#3b2f00; background:#f6d365; }
    .grade-C { color:#344054; background:#e4e7ec; }
    .grade-- { color:#667085; background:#f2f4f7; }
    .small { color:var(--muted); font-size:12px; margin-top:3px; }
    .themes { color:#175cd3; }
    a.stock-link { color:#0b4a8b; text-decoration:none; }
    a.stock-link:hover { text-decoration:underline; }
    .bad { color:var(--bad); }
    .status-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; background:#98a2b3; }
    .status-ok { background:var(--good); }
    .status-warn { background:var(--warn); }
    .status-bad { background:var(--bad); }
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
    <div class="toolbar"><a class="stock-link" href="performance.html">查看訊號成效追蹤</a></div>
    <div class="metrics" id="metrics"></div>
    <div class="bands">
      <section><h2>市場風向</h2><div id="market"></div></section>
      <section><h2>新聞題材</h2><div id="themes"></div></section>
      <section><h2>異常提醒</h2><div id="alerts"></div></section>
      <section><h2>觀察追蹤</h2><div id="watchReviews"></div></section>
    </div>
    <div class="toolbar">
      <input id="search" placeholder="搜尋股票、題材、訊號..." />
      <select id="grade"><option value="">全部級別</option><option>A</option><option>B</option><option>C</option><option>-">資料不足</option></select>
    </div>
    <table>
      <thead><tr><th>級別</th><th>股票</th><th>分數</th><th>操作</th><th>題材</th><th>技術</th><th>籌碼</th><th>基本</th><th>風險</th><th>進場/停損</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    let data = null;
    const cls = g => "grade grade-" + (g === "-" ? "-" : g);
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
    function render() {
      const q = document.querySelector("#search").value.trim().toLowerCase();
      const g = document.querySelector("#grade").value;
      document.querySelector("#subtitle").textContent = `${data.as_of}｜僅供研究追蹤，不是投資建議`;
      document.querySelector("#metrics").innerHTML = [
        ["掃描", data.summary.scanned], ["有效", data.summary.valid], ["A級", data.summary.a_grade], ["B級", data.summary.b_grade], ["資料不足", data.summary.data_insufficient]
      ].map(([k,v]) => `<div class="metric"><b>${v}</b><span>${k}</span></div>`).join("");
      document.querySelector("#market").innerHTML = `
        <div class="line">台股：${esc(data.market.summary)}</div>
        <div class="line">海外：${esc(data.overseas.label)}｜${esc(data.overseas.summary)}</div>
        <div class="line"><span class="${sourceClass(data.source_status.label)}"></span>資料源：${esc(data.source_status.label)}｜API ${data.source_status.api || 0}｜快取 ${data.source_status.cache || 0}｜限流 ${data.source_status.quota || 0}</div>
        ${data.market.warning ? `<div class="line bad">提醒：${esc(data.market.warning)}</div>` : ""}`;
      const themeRank = Object.entries(data.themes.scores || {})
        .filter(([,score]) => score > 0)
        .sort((a,b) => b[1] - a[1])
        .slice(0,5)
        .map(([key,score]) => `<div class="line">${esc(data.themes.names[key] || key)}：${score} 則｜股票池 ${data.themes.pool_counts?.[key] || 0} 檔</div>`)
        .join("");
      document.querySelector("#themes").innerHTML = `
        <div class="line">熱門：${esc(data.themes.summary)}</div>
        ${themeRank}
        ${data.themes.headlines.slice(0,3).map(h => `<div class="line">- ${esc(h)}</div>`).join("")}`;
      document.querySelector("#alerts").innerHTML = (data.alerts || []).length
        ? data.alerts.map(a => `<div class="line bad">- ${esc(a)}</div>`).join("")
        : `<div class="line">目前無重大異常</div>`;
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
          <td data-label="分數"><b>${r.score}/100</b><div class="small">海外 ${r.overseas_adjustment >= 0 ? "+" : ""}${r.overseas_adjustment}｜異常 ${r.opportunity_score}</div></td>
          <td data-label="操作"><b>${esc(r.action || "只觀察")}</b><div class="small">${esc(r.opportunity || "資料不足，暫不建議")}</div></td>
          <td data-label="題材" class="themes">${esc((r.theme_tiers || []).join(" / ") || (r.themes || []).join(" / ") || "-")}</td>
          <td data-label="技術">${esc(r.technical || "無明顯訊號")}</td><td data-label="籌碼">${esc(r.chip || "無明顯訊號")}</td><td data-label="基本">${esc(r.fundamental || "無明顯訊號")}</td><td data-label="風險">${esc(r.risk || "無明顯訊號")}</td><td data-label="進場/停損">${esc(r.entry_condition || "資料不足，暫不設進場條件")}<div class="small">${esc(r.stop_reference || "資料不足，暫不設停損參考")}</div></td>
        </tr>`).join("");
    }
    function sourceClass(label) {
      const base = "status-dot ";
      if (label === "正常") return base + "status-ok";
      if (label === "部分限流" || label === "限流") return base + "status-warn";
      if (label === "錯誤") return base + "status-bad";
      return base;
    }
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
    document.querySelector("#search").addEventListener("input", render);
    document.querySelector("#grade").addEventListener("change", render);
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
    .metric b { display:block; font-size:22px; margin-bottom:2px; }
    .toolbar { display:flex; gap:10px; align-items:center; margin:14px 0; flex-wrap:wrap; }
    input, select { border:1px solid var(--line); border-radius:6px; padding:9px 10px; background:white; min-height:38px; }
    input { min-width:260px; flex:1; }
    table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#eef1f5; font-size:12px; color:#475467; }
    a { color:#0b4a8b; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .pos { color:var(--good); font-weight:700; }
    .neg { color:var(--bad); font-weight:700; }
    @media (max-width:900px) {
      main, header { padding-left:12px; padding-right:12px; }
      .metrics { grid-template-columns:1fr 1fr; }
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
    <div class="toolbar"><a href="index.html">返回監控頁</a></div>
    <div class="metrics" id="metrics"></div>
    <div class="toolbar">
      <input id="search" placeholder="搜尋股票、日期、狀態..." />
      <select id="grade"><option value="">全部級別</option><option>A</option><option>B</option><option>C</option></select>
      <select id="status"><option value="">全部狀態</option><option>已完成</option><option>進行中</option></select>
    </div>
    <table>
      <thead><tr><th>訊號日</th><th>股票</th><th>級別</th><th>分數</th><th>訊號價</th><th>進場觸發</th><th>3日漲跌</th><th>5日漲跌</th><th>停損觸及</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    let data = null;
    const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
    const fmtPct = value => value === null || value === undefined ? "—" : `<span class="${value >= 0 ? "pos" : "neg"}">${value >= 0 ? "+" : ""}${Number(value).toFixed(1)}%</span>`;
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
        metric("停損觸及", stats.stop_hit_rate?.toFixed(1), "%"),
        metric("A級5日勝率", stats.a_win_rate_5d?.toFixed(1), "%"),
      ].join("");
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
          <td data-label="5日漲跌">${fmtPct(r.return_5d)}</td>
          <td data-label="停損觸及">${fmtBool(r.stop_hit)}</td>
        </tr>
      `).join("");
    }
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
    document.querySelector("#search").addEventListener("input", render);
    document.querySelector("#grade").addEventListener("change", render);
    document.querySelector("#status").addEventListener("change", render);
  </script>
</body>
</html>"""
