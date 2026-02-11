from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

from flask import Flask, Response, jsonify, render_template_string, request

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "meals.db"

app = Flask(__name__)


# ==================== DB ====================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              day TEXT NOT NULL,              -- YYYY-MM-DD
              meal TEXT NOT NULL,
              ts INTEGER NOT NULL,            -- unix ms (client local time)
              note TEXT NOT NULL DEFAULT ''
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_day ON entries(day);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts);")

        # ---- schema migration: add calories column if missing ----
        if not _column_exists(conn, "entries", "calories"):
            conn.execute("ALTER TABLE entries ADD COLUMN calories INTEGER NOT NULL DEFAULT 0;")


def iso_today() -> str:
    return date.today().isoformat()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ==================== date helpers ====================
def parse_iso_day(day: str) -> date:
    return datetime.strptime(day, "%Y-%m-%d").date()


def week_bounds(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())  # Monday
    end = start + timedelta(days=6)
    return start, end


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    end = next_month - timedelta(days=1)
    return start, end


def sum_calories_between(conn: sqlite3.Connection, start_day: date, end_day: date) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(calories),0) AS total FROM entries WHERE day BETWEEN ? AND ?",
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchone()
    return int(row["total"] or 0)


# ==================== UI ====================
PAGE = r"""
<!doctype html>
<html lang="en" data-theme="auto">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Meal Time Tracker</title>

  <style>
    :root{
      --radius:22px;
      --rowH:44px;
      --wheelH:238px;
      --wheelW:140px;
      --wheelW2:95px;
      --accent:#5b8cff;
      --danger:#ff5b5b;
      --ok:#4cd964;
    }

    /* Dark */
    :root[data-theme="dark"], :root[data-theme="auto"]{
      --bg:#0b0b10;
      --bg2:rgba(255,255,255,.06);
      --card1:rgba(255,255,255,.07);
      --card2:rgba(255,255,255,.03);
      --stroke:rgba(255,255,255,.12);
      --stroke2:rgba(255,255,255,.18);
      --text:#f2f2f7;
      --muted:rgba(242,242,247,.60);
      --muted2:rgba(242,242,247,.38);
      --shadow:rgba(0,0,0,.40);
      --fadeA:rgba(11,11,16,.88);
      --fadeB:rgba(11,11,16,0);
      --inputBg:rgba(0,0,0,.18);
      --chartBg:rgba(0,0,0,.16);
      --bar:rgba(255,255,255,.78);
      --barTop:rgba(91,140,255,.24);
      --grid:rgba(255,255,255,.14);
      --selA:rgba(91,140,255,.16);
      --selB:rgba(91,140,255,.08);
      --chip:rgba(255,255,255,.07);
    }

    @media (prefers-color-scheme: light){
      :root[data-theme="auto"]{
        --bg:#f5f6fb;
        --bg2:rgba(0,0,0,.04);
        --card1:rgba(255,255,255,.90);
        --card2:rgba(255,255,255,.70);
        --stroke:rgba(0,0,0,.10);
        --stroke2:rgba(0,0,0,.16);
        --text:#101018;
        --muted:rgba(16,16,24,.60);
        --muted2:rgba(16,16,24,.40);
        --shadow:rgba(0,0,0,.10);
        --fadeA:rgba(245,246,251,.92);
        --fadeB:rgba(245,246,251,0);
        --inputBg:rgba(255,255,255,.75);
        --chartBg:rgba(255,255,255,.65);
        --bar:rgba(16,16,24,.78);
        --barTop:rgba(91,140,255,.32);
        --grid:rgba(16,16,24,.12);
        --selA:rgba(91,140,255,.18);
        --selB:rgba(91,140,255,.10);
        --chip:rgba(0,0,0,.04);
      }
    }

    :root[data-theme="light"]{
      --bg:#f5f6fb;
      --bg2:rgba(0,0,0,.04);
      --card1:rgba(255,255,255,.90);
      --card2:rgba(255,255,255,.70);
      --stroke:rgba(0,0,0,.10);
      --stroke2:rgba(0,0,0,.16);
      --text:#101018;
      --muted:rgba(16,16,24,.60);
      --muted2:rgba(16,16,24,.40);
      --shadow:rgba(0,0,0,.10);
      --fadeA:rgba(245,246,251,.92);
      --fadeB:rgba(245,246,251,0);
      --inputBg:rgba(255,255,255,.75);
      --chartBg:rgba(255,255,255,.65);
      --bar:rgba(16,16,24,.78);
      --barTop:rgba(91,140,255,.32);
      --grid:rgba(16,16,24,.12);
      --selA:rgba(91,140,255,.18);
      --selB:rgba(91,140,255,.10);
      --chip:rgba(0,0,0,.04);
    }

    *{box-sizing:border-box}
    html,body{height:100%}
    body{
      margin:0;
      font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;
      color:var(--text);
      background:
        radial-gradient(900px 600px at 20% 0%, rgba(91,140,255,.18) 0%, rgba(91,140,255,0) 60%),
        radial-gradient(900px 600px at 80% 20%, rgba(255,255,255,.10) 0%, rgba(255,255,255,0) 60%),
        var(--bg);
    }

    .wrap{max-width:1080px;margin:0 auto;padding:22px 18px 60px}
    .topbar{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}
    h1{font-size:22px;margin:0 0 6px}
    p{margin:0;color:var(--muted);line-height:1.45}

    .grid{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-top:16px}
    @media (max-width:900px){.grid{grid-template-columns:1fr}}

    .card{
      border:1px solid var(--stroke);
      background:linear-gradient(180deg, var(--card1), var(--card2));
      border-radius:var(--radius);
      padding:16px;
      box-shadow:0 18px 55px var(--shadow);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
    }

    .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
    .divider{height:1px;background:color-mix(in oklab, var(--stroke) 70%, transparent);margin:14px 0}
    .sub{color:var(--muted);font-size:13px}
    .timeDisplay{font-size:44px;font-weight:900;letter-spacing:.3px;margin:6px 0 12px}

    .pill{
      border:1px solid color-mix(in oklab, var(--stroke2) 70%, transparent);
      background:var(--bg2);
      color:var(--text);
      padding:10px 12px;
      border-radius:999px;
      cursor:pointer;
      user-select:none;
    }
    .pill[aria-pressed="true"]{
      border-color:color-mix(in oklab, var(--accent) 70%, transparent);
      box-shadow:0 0 0 3px color-mix(in oklab, var(--accent) 25%, transparent) inset;
    }

    .btn{
      border:0;
      background:var(--accent);
      color:white;
      padding:12px 16px;
      border-radius:18px;
      cursor:pointer;
      font-weight:900;
      font-size:16px;
      box-shadow:0 10px 24px color-mix(in oklab, var(--accent) 28%, transparent);
    }
    .btn.secondary{
      background:var(--bg2);
      color:var(--text);
      border:1px solid var(--stroke);
      box-shadow:none;
    }
    .btn.danger{
      background:color-mix(in oklab, var(--danger) 90%, black 10%);
      box-shadow:none;
    }
    .btn:active{transform:translateY(1px)}

    .iconBtn{
      border:1px solid var(--stroke);
      background:var(--bg2);
      color:var(--text);
      padding:8px 10px;
      border-radius:12px;
      cursor:pointer;
      user-select:none;
    }
    .iconBtn:hover{border-color:var(--stroke2)}

    input[type="text"], input[type="number"]{
      width:100%;
      padding:14px 14px;
      border-radius:18px;
      border:1px solid var(--stroke);
      background:var(--inputBg);
      color:var(--text);
      outline:none;
      font-size:16px;
    }
    input::placeholder{color:var(--muted2)}

    /* Wheel */
    .wheelWrap{display:flex;gap:12px;align-items:center;justify-content:flex-start}
    .wheelOuter{
      position:relative;
      width:var(--wheelW);
      height:var(--wheelH);
      border-radius:22px;
      border:1px solid var(--stroke);
      background:var(--inputBg);
      overflow:hidden;
      box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--stroke) 35%, transparent);
    }
    .wheelOuter.ampm{width:var(--wheelW2)}
    .wheelScroll{
      height:100%;
      overflow:auto;
      scroll-snap-type:y mandatory;
      scroll-snap-stop:always;
      -webkit-overflow-scrolling: touch;
      scrollbar-width:none;
      overscroll-behavior: contain;
      will-change: scroll-position;
    }
    .wheelScroll::-webkit-scrollbar{display:none}
    .spacer{height:calc((var(--wheelH) - var(--rowH)) / 2);}
    .opt{
      height:var(--rowH);
      display:flex;
      align-items:center;
      justify-content:center;
      scroll-snap-align:center;
      color:var(--muted2);
      font-size:20px;
      letter-spacing:.3px;
      user-select:none;
    }
    .opt.active{color:var(--text);font-weight:900}
    .selectBand{
      pointer-events:none;
      position:absolute;
      left:10px; right:10px;
      top:50%;
      transform:translateY(-50%);
      height:var(--rowH);
      border-radius:14px;
      border:1px solid color-mix(in oklab, var(--stroke) 70%, transparent);
      background:linear-gradient(180deg, var(--selA), var(--selB));
      box-shadow: 0 10px 40px color-mix(in oklab, var(--shadow) 85%, transparent),
                  inset 0 1px 0 color-mix(in oklab, var(--stroke2) 35%, transparent);
    }
    .fadeTop,.fadeBot{pointer-events:none;position:absolute;left:0;right:0;height:74px;}
    .fadeTop{top:0; background:linear-gradient(180deg, var(--fadeA), var(--fadeB));}
    .fadeBot{bottom:0; background:linear-gradient(0deg, var(--fadeA), var(--fadeB));}

    /* Summary cards */
    .summaryGrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:10px}
    @media (max-width:900px){.summaryGrid{grid-template-columns:repeat(2,1fr)}}
    .kpi{
      border:1px solid var(--stroke);
      background:var(--bg2);
      border-radius:16px;
      padding:10px 12px;
      min-height:64px;
    }
    .kpi .label{font-size:12px;color:var(--muted)}
    .kpi .value{font-size:18px;font-weight:900;margin-top:4px}

    /* Edit banner */
    .editBanner{
      display:none;
      border:1px solid color-mix(in oklab, var(--accent) 55%, transparent);
      background:color-mix(in oklab, var(--accent) 12%, var(--chip));
      border-radius:16px;
      padding:10px 12px;
      margin-top:12px;
    }
    .editBanner strong{font-weight:900}
    .editBanner .hint{color:var(--muted);font-size:13px;margin-top:2px}
    .editBanner .row{margin-top:10px}

    /* Log + Chart */
    .logItem{display:flex;justify-content:space-between;gap:12px;padding:10px 10px;border-radius:14px}
    .logItem:nth-child(odd){background:color-mix(in oklab, var(--bg2) 60%, transparent)}
    .logItem b{font-weight:900}
    .logItem small{color:var(--muted)}
    .actions{display:flex;gap:8px}
    canvas{display:block}
    .chartCanvas{
      width:100%;
      height:230px;
      border-radius:18px;
      border:1px solid var(--stroke);
      background:var(--chartBg);
    }
  </style>
</head>

<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <h1>Meal Time Tracker</h1>
        <p>All-time histogram + calories totals. Now includes editing (update existing meals).</p>
      </div>
      <div class="row">
        <button class="iconBtn" id="themeToggle" title="Toggle light/dark/auto">Theme</button>
      </div>
    </div>

    <div class="grid">
      <!-- LEFT: Picker -->
      <div class="card">
        <div class="row" id="mealRow" role="group" aria-label="Meal type">
          <button class="pill" data-meal="Breakfast" aria-pressed="true">Breakfast</button>
          <button class="pill" data-meal="Lunch" aria-pressed="false">Lunch</button>
          <button class="pill" data-meal="Dinner" aria-pressed="false">Dinner</button>
          <button class="pill" data-meal="Snack" aria-pressed="false">Snack</button>
        </div>

        <div class="divider"></div>

        <div class="sub">Selected time</div>
        <div class="timeDisplay" id="timeDisplay">08:00 AM</div>

        <div class="wheelWrap">
          <div class="wheelOuter">
            <div class="wheelScroll" id="wheelHour"></div>
            <div class="selectBand"></div>
            <div class="fadeTop"></div><div class="fadeBot"></div>
          </div>

          <div class="wheelOuter">
            <div class="wheelScroll" id="wheelMin"></div>
            <div class="selectBand"></div>
            <div class="fadeTop"></div><div class="fadeBot"></div>
          </div>

          <div class="wheelOuter ampm">
            <div class="wheelScroll" id="wheelAmPm"></div>
            <div class="selectBand"></div>
            <div class="fadeTop"></div><div class="fadeBot"></div>
          </div>
        </div>

        <div style="margin-top:12px; display:grid; grid-template-columns: 1fr 160px; gap:10px;">
          <input id="note" type="text" placeholder="Optional note (e.g., salmon + rice)" />
          <input id="calories" type="number" inputmode="numeric" min="0" step="1" placeholder="kcal" />
        </div>

        <!-- Edit banner -->
        <div class="editBanner" id="editBanner">
          <div><strong>Editing entry</strong> <span id="editMeta" class="sub"></span></div>
          <div class="hint">Change the meal/time/note/calories, then press <b>Update</b>. Or cancel.</div>
          <div class="row">
            <button class="btn secondary" id="cancelEditBtn">Cancel edit</button>
          </div>
        </div>

        <div class="row" style="margin-top:14px">
          <button class="btn" id="saveBtn">Save</button>
          <button class="btn secondary" id="saveNowBtn">Save Now</button>
          <button class="btn secondary" id="clearDayBtn">Clear Day</button>
        </div>

        <div class="sub" style="margin-top:10px">Tip: click “Edit” on a log item to load it into the picker.</div>
      </div>

      <!-- RIGHT: Log + Chart + Totals -->
      <div class="card">
        <div class="row" style="justify-content:space-between;align-items:baseline">
          <div>
            <div class="sub">Log (selected day)</div>
            <div style="font-size:18px;font-weight:900;margin-top:2px" id="logTitle">Today</div>
          </div>
          <div class="row">
            <button class="iconBtn" id="prevDay">←</button>
            <button class="iconBtn" id="nextDay">→</button>
          </div>
        </div>

        <div class="summaryGrid" aria-label="Calorie totals">
          <div class="kpi"><div class="label">Day total</div><div class="value" id="kpiDay">—</div></div>
          <div class="kpi"><div class="label">Week total</div><div class="value" id="kpiWeek">—</div></div>
          <div class="kpi"><div class="label">Month total</div><div class="value" id="kpiMonth">—</div></div>
          <div class="kpi"><div class="label">All time</div><div class="value" id="kpiAll">—</div></div>
        </div>

        <div class="divider"></div>

        <div class="sub" id="chartTitle">Meals by hour (24 bars) — All time</div>
        <canvas id="hourChart" class="chartCanvas"></canvas>

        <div class="divider"></div>

        <div id="log"></div>
        <div class="sub" id="emptyMsg" style="display:none;margin-top:10px">No entries yet.</div>
      </div>
    </div>
  </div>

<script>
  // ===================== Theme toggle =====================
  const THEME_KEY = "meal_tracker_theme";
  function getTheme(){ return localStorage.getItem(THEME_KEY) || "auto"; }
  function setTheme(t){
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem(THEME_KEY, t);
  }
  function cycleTheme(){
    const cur = getTheme();
    const next = cur === "auto" ? "dark" : (cur === "dark" ? "light" : "auto");
    setTheme(next);
  }
  document.getElementById("themeToggle").addEventListener("click", cycleTheme);
  setTheme(getTheme());

  // ===================== helpers =====================
  const pad2 = n => String(n).padStart(2,'0');
  function format12h(hour24, min){
    const am = hour24 < 12;
    let h = hour24 % 12; if (h === 0) h = 12;
    return `${pad2(h)}:${pad2(min)} ${am ? 'AM' : 'PM'}`;
  }
  function to24h(hour12, ampm){
    if (ampm === 'AM') return hour12 === 12 ? 0 : hour12;
    return hour12 === 12 ? 12 : hour12 + 12;
  }
  function isoDate(d){
    const x = new Date(d);
    x.setHours(0,0,0,0);
    return x.toISOString().slice(0,10);
  }
  function humanDate(d){
    return d.toLocaleDateString(undefined, { weekday:'long', year:'numeric', month:'short', day:'numeric' });
  }
  function clampInt(v, def=0){
    const n = Number(v);
    if (!Number.isFinite(n)) return def;
    return Math.max(0, Math.floor(n));
  }
  function kcal(n){ return `${clampInt(n)} kcal`; }

  // ===================== wheel (smooth) =====================
  const ROW_H = 44;
  const OUTER_H = 238;
  const SPACER_H = (OUTER_H - ROW_H) / 2;

  function buildWheel(scrollEl, items){
    scrollEl.innerHTML = '';
    const top = document.createElement('div'); top.className='spacer';
    const bot = document.createElement('div'); bot.className='spacer';
    scrollEl.appendChild(top);
    for (const val of items){
      const div = document.createElement('div');
      div.className='opt';
      div.textContent=val;
      div.dataset.value=val;
      scrollEl.appendChild(div);
    }
    scrollEl.appendChild(bot);
  }
  function getOpts(scrollEl){ return [...scrollEl.querySelectorAll('.opt')]; }
  function selectedIndex(scrollEl, count){
    const center = scrollEl.scrollTop + OUTER_H/2;
    const raw = (center - SPACER_H - ROW_H/2) / ROW_H;
    const idx = Math.round(raw);
    return Math.max(0, Math.min(count-1, idx));
  }
  function setActiveIndex(scrollEl, idx){
    const opts = getOpts(scrollEl);
    for (let i=0;i<opts.length;i++){
      if (i===idx) opts[i].classList.add('active');
      else opts[i].classList.remove('active');
    }
    return opts[idx]?.dataset.value;
  }
  function scrollToIndex(scrollEl, idx, smooth=false){
    const targetCenter = SPACER_H + idx*ROW_H + ROW_H/2;
    const targetTop = targetCenter - OUTER_H/2;
    scrollEl.scrollTo({ top: targetTop, behavior: smooth ? 'smooth' : 'auto' });
    setActiveIndex(scrollEl, idx);
  }
  function scrollToValue(scrollEl, value, smooth=false){
    const opts = getOpts(scrollEl);
    const idx = opts.findIndex(o => o.dataset.value == value);
    if (idx>=0) scrollToIndex(scrollEl, idx, smooth);
  }
  function attachWheel(scrollEl, onValue){
    const opts = getOpts(scrollEl);
    let raf = false;
    let lastIdx = -1;
    let snapTimer = null;

    function tick(){
      raf = false;
      const idx = selectedIndex(scrollEl, opts.length);
      if (idx !== lastIdx){
        lastIdx = idx;
        const val = setActiveIndex(scrollEl, idx);
        if (val != null) onValue(val);
      }
    }
    function requestTick(){
      if (raf) return;
      raf = true;
      requestAnimationFrame(tick);
    }
    function scheduleSnap(){
      if (snapTimer) clearTimeout(snapTimer);
      snapTimer = setTimeout(() => {
        const idx = selectedIndex(scrollEl, opts.length);
        scrollToIndex(scrollEl, idx, true);
      }, 140);
    }

    scrollEl.addEventListener('scroll', () => { requestTick(); scheduleSnap(); }, {passive:true});
    scrollEl.addEventListener('scrollend', () => {
      const idx = selectedIndex(scrollEl, opts.length);
      scrollToIndex(scrollEl, idx, true);
    });
    scrollEl.addEventListener('click', (e) => {
      const opt = e.target.closest('.opt');
      if (!opt) return;
      const idx = opts.indexOf(opt);
      if (idx>=0) scrollToIndex(scrollEl, idx, true);
    });
  }

  // ===================== chart (ALL-TIME histogram) =====================
  function getCssVar(name){
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function drawHourChart(counts){
    const canvas = document.getElementById('hourChart');
    const ctx = canvas.getContext('2d');

    const cssW = canvas.clientWidth || 800;
    const cssH = canvas.clientHeight || 230;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const W = cssW, H = cssH;
    ctx.clearRect(0, 0, W, H);

    const padL = 34, padR = 14, padT = 14, padB = 28;
    const chartW = W - padL - padR;
    const chartH = H - padT - padB;

    const maxVal = Math.max(1, ...counts);
    const bars = 24;
    const gap = 4;
    const barW = (chartW - gap*(bars-1)) / bars;

    const gridColor = getCssVar('--grid');
    const barColor = getCssVar('--bar');
    const barTopColor = getCssVar('--barTop');
    const labelColor = getCssVar('--muted');
    const axisLabelColor = getCssVar('--muted2');

    ctx.lineWidth = 1;
    ctx.strokeStyle = gridColor;
    const gridLines = Math.min(4, maxVal);
    for (let i=0;i<=gridLines;i++){
      const y = padT + chartH - (i/gridLines)*chartH;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(W-padR, y);
      ctx.stroke();

      ctx.fillStyle = labelColor;
      ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";
      const val = Math.round((i/gridLines)*maxVal);
      ctx.fillText(String(val), 6, y+4);
    }

    for (let h=0; h<24; h++){
      const v = counts[h];
      const x = padL + h*(barW+gap);
      const bh = (v/maxVal)*chartH;
      const y = padT + (chartH - bh);

      ctx.fillStyle = barColor;
      ctx.fillRect(x, y, barW, bh);

      ctx.fillStyle = barTopColor;
      ctx.fillRect(x, y, barW, 2);
    }

    ctx.fillStyle = axisLabelColor;
    ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";
    ctx.textAlign = "center";
    for (let h=0; h<24; h+=3){
      const x = padL + h*(barW+gap) + barW/2;
      ctx.fillText(String(h).padStart(2,'0'), x, H-10);
    }
    ctx.textAlign = "start";
  }

  // ===================== API =====================
  async function apiGetEntries(dayIso){
    const r = await fetch(`/api/entries?day=${encodeURIComponent(dayIso)}`);
    if (!r.ok) throw new Error("Failed to load entries");
    return await r.json();
  }
  async function apiAddEntry(payload){
    const r = await fetch('/api/entries', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error("Failed to add entry");
    return await r.json();
  }
  async function apiUpdateEntry(id, payload){
    const r = await fetch(`/api/entries/${id}`, {
      method:'PUT', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error("Failed to update entry");
    return await r.json();
  }
  async function apiDeleteEntry(id){
    const r = await fetch(`/api/entries/${id}`, { method:'DELETE' });
    if (!r.ok) throw new Error("Failed to delete entry");
    return await r.json();
  }
  async function apiClearDay(dayIso){
    const r = await fetch(`/api/entries/clear?day=${encodeURIComponent(dayIso)}`, { method:'POST' });
    if (!r.ok) throw new Error("Failed to clear day");
    return await r.json();
  }
  async function apiGetHistogramAll(){
    const r = await fetch(`/api/histogram/all`);
    if (!r.ok) throw new Error("Failed to load histogram");
    return await r.json();
  }
  async function apiGetSummary(dayIso){
    const r = await fetch(`/api/summary?day=${encodeURIComponent(dayIso)}`);
    if (!r.ok) throw new Error("Failed to load summary");
    return await r.json();
  }

  // ===================== app state =====================
  const state = {
    meal: 'Breakfast',
    date: new Date(),      // selected day for log view + summary
    hour12: 8,
    minute: 0,
    ampm: 'AM',
    editingId: null,       // <- when set, left panel is in "edit mode"
  };

  // Wheels
  const wheelHour = document.getElementById('wheelHour');
  const wheelMin  = document.getElementById('wheelMin');
  const wheelAmPm = document.getElementById('wheelAmPm');

  buildWheel(wheelHour, Array.from({length:12}, (_,i)=>String(i+1)));
  buildWheel(wheelMin,  Array.from({length:60}, (_,i)=>String(i).padStart(2,'0')));
  buildWheel(wheelAmPm, ['AM','PM']);

  function updateDisplay(){
    const hour24 = to24h(state.hour12, state.ampm);
    document.getElementById('timeDisplay').textContent = format12h(hour24, state.minute);
  }

  attachWheel(wheelHour, (v)=>{ state.hour12 = parseInt(v,10); updateDisplay(); });
  attachWheel(wheelMin,  (v)=>{ state.minute = parseInt(v,10); updateDisplay(); });
  attachWheel(wheelAmPm, (v)=>{ state.ampm = v; updateDisplay(); });

  // Meal buttons
  function setMealUI(meal){
    state.meal = meal;
    [...document.querySelectorAll('#mealRow .pill')].forEach(b => b.setAttribute('aria-pressed','false'));
    const btn = [...document.querySelectorAll('#mealRow .pill')].find(b => b.dataset.meal === meal);
    if (btn) btn.setAttribute('aria-pressed','true');
  }

  document.getElementById('mealRow').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-meal]');
    if (!btn) return;
    setMealUI(btn.dataset.meal);
  });

  // ===================== edit mode UI =====================
  function enterEditMode(entry){
    state.editingId = entry.id;

    // load meal + inputs
    setMealUI(entry.meal);
    document.getElementById('note').value = entry.note || '';
    document.getElementById('calories').value = clampInt(entry.calories);

    // load time into wheels
    const t = new Date(entry.ts);
    const h24 = t.getHours();
    state.ampm = h24 < 12 ? 'AM' : 'PM';
    let h12 = h24 % 12; if (h12 === 0) h12 = 12;
    state.hour12 = h12;
    state.minute = t.getMinutes();

    scrollToValue(wheelHour, String(state.hour12), true);
    scrollToValue(wheelMin, pad2(state.minute), true);
    scrollToValue(wheelAmPm, state.ampm, true);
    updateDisplay();

    // buttons
    document.getElementById('saveBtn').textContent = 'Update';
    document.getElementById('saveNowBtn').style.display = 'none';

    // banner
    const banner = document.getElementById('editBanner');
    banner.style.display = 'block';
    const meta = document.getElementById('editMeta');
    meta.textContent = `#${entry.id}`;
  }

  function exitEditMode(){
    state.editingId = null;
    document.getElementById('saveBtn').textContent = 'Save';
    document.getElementById('saveNowBtn').style.display = '';
    document.getElementById('editBanner').style.display = 'none';
    document.getElementById('editMeta').textContent = '';
    // keep current wheel selections; just stop editing
  }

  document.getElementById('cancelEditBtn').onclick = () => exitEditMode();

  // ===================== rendering =====================
  async function renderLog(){
    const dayIso = isoDate(state.date);
    document.getElementById('logTitle').textContent = humanDate(state.date);

    const entries = (await apiGetEntries(dayIso)).entries;
    entries.sort((a,b)=>a.ts-b.ts);

    const log = document.getElementById('log');
    log.innerHTML = '';
    document.getElementById('emptyMsg').style.display = entries.length ? 'none' : 'block';

    for (const entry of entries){
      const div = document.createElement('div');
      div.className = 'logItem';

      const left = document.createElement('div');
      const t = new Date(entry.ts);
      const timeStr = format12h(t.getHours(), t.getMinutes());
      const note = entry.note ? ` · ${entry.note}` : '';
      const cal = clampInt(entry.calories);
      left.innerHTML = `<b>${entry.meal}</b><br><small>${timeStr} · ${cal} kcal${note}</small>`;

      const actions = document.createElement('div');
      actions.className = 'actions';

      const edit = document.createElement('button');
      edit.className = 'iconBtn';
      edit.textContent = 'Edit';
      edit.onclick = () => enterEditMode(entry);

      const del = document.createElement('button');
      del.className = 'iconBtn';
      del.textContent = 'Delete';
      del.onclick = async () => {
        // If deleting the item you’re editing, exit edit mode
        if (state.editingId === entry.id) exitEditMode();
        await apiDeleteEntry(entry.id);
        await refreshAll();
      };

      actions.appendChild(edit);
      actions.appendChild(del);

      div.appendChild(left);
      div.appendChild(actions);
      log.appendChild(div);
    }
  }

  async function renderHistogramAllTime(){
    const hist = await apiGetHistogramAll();
    drawHourChart(hist.counts);
    document.getElementById('chartTitle').textContent =
      `Meals by hour (24 bars) — All time (${hist.total_entries} entries)`;
  }

  async function renderSummary(){
    const dayIso = isoDate(state.date);
    const s = await apiGetSummary(dayIso);
    document.getElementById('kpiDay').textContent = kcal(s.day_total);
    document.getElementById('kpiWeek').textContent = kcal(s.week_total);
    document.getElementById('kpiMonth').textContent = kcal(s.month_total);
    document.getElementById('kpiAll').textContent = kcal(s.all_total);
  }

  async function refreshAll(){
    await renderLog();
    await renderSummary();
    await renderHistogramAllTime();
  }

  // ===================== actions =====================
  async function saveOrUpdate(){
    const dayIso = isoDate(state.date);
    const hour24 = to24h(state.hour12, state.ampm);

    const ts = new Date(dayIso + "T00:00:00");
    ts.setHours(hour24, state.minute, 0, 0);

    const payload = {
      day: dayIso,
      meal: state.meal,
      ts: ts.getTime(),
      note: document.getElementById('note').value || '',
      calories: clampInt(document.getElementById('calories').value, 0)
    };

    if (state.editingId != null){
      await apiUpdateEntry(state.editingId, payload);
      exitEditMode();
    } else {
      await apiAddEntry(payload);
    }

    document.getElementById('note').value = '';
    document.getElementById('calories').value = '';
    await refreshAll();
  }

  document.getElementById('saveBtn').onclick = saveOrUpdate;

  document.getElementById('saveNowBtn').onclick = async () => {
    // Only for "add" mode
    if (state.editingId != null) return;

    const dayIso = isoDate(state.date);
    const now = new Date();

    const ts = new Date(dayIso + "T00:00:00");
    if (isoDate(now) === dayIso){
      ts.setHours(now.getHours(), now.getMinutes(), 0, 0);
    } else {
      ts.setHours(12, 0, 0, 0);
    }

    await apiAddEntry({
      day: dayIso,
      meal: state.meal,
      ts: ts.getTime(),
      note: document.getElementById('note').value || '',
      calories: clampInt(document.getElementById('calories').value, 0)
    });

    document.getElementById('note').value = '';
    document.getElementById('calories').value = '';
    await refreshAll();
  };

  document.getElementById('clearDayBtn').onclick = async () => {
    const dayIso = isoDate(state.date);
    if (!confirm('Clear all entries for this day?')) return;
    // If you're editing something on this day, exit edit mode
    exitEditMode();
    await apiClearDay(dayIso);
    await refreshAll();
  };

  document.getElementById('prevDay').onclick = async () => {
    exitEditMode();
    state.date = new Date(state.date.getTime() - 86400000);
    await refreshAll();
  };

  document.getElementById('nextDay').onclick = async () => {
    exitEditMode();
    state.date = new Date(state.date.getTime() + 86400000);
    await refreshAll();
  };

  // keep chart crisp on resize + after theme changes
  window.addEventListener('resize', () => { renderHistogramAllTime(); });
  const obs = new MutationObserver(() => { renderHistogramAllTime(); });
  obs.observe(document.documentElement, { attributes:true, attributeFilter:["data-theme"] });

  // ===================== mount =====================
  requestAnimationFrame(async () => {
    scrollToValue(wheelHour, String(state.hour12), false);
    scrollToValue(wheelMin, String(state.minute).padStart(2,'0'), false);
    scrollToValue(wheelAmPm, state.ampm, false);
    updateDisplay();
    await refreshAll();
  });
</script>
</body>
</html>
"""


# ==================== routes ====================
@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/api/entries")
def get_entries():
    day = request.args.get("day") or iso_today()
    with db() as conn:
        rows = conn.execute(
            "SELECT id, day, meal, ts, note, calories FROM entries WHERE day=? ORDER BY ts ASC",
            (day,),
        ).fetchall()
    return jsonify({"day": day, "entries": rows_to_dicts(rows)})


@app.post("/api/entries")
def add_entry():
    data = request.get_json(force=True, silent=False)

    day = str(data.get("day") or "").strip()
    meal = str(data.get("meal") or "").strip()
    ts = data.get("ts")
    note = str(data.get("note") or "").strip()
    calories = data.get("calories", 0)

    if not day or not meal or ts is None:
        return jsonify({"error": "Missing day/meal/ts"}), 400

    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return jsonify({"error": "ts must be an integer (unix ms)"}), 400

    try:
        cal_int = int(calories)
        if cal_int < 0:
            cal_int = 0
    except (TypeError, ValueError):
        cal_int = 0

    with db() as conn:
        cur = conn.execute(
            "INSERT INTO entries(day, meal, ts, note, calories) VALUES(?,?,?,?,?)",
            (day, meal, ts_int, note, cal_int),
        )
        new_id = cur.lastrowid

    return jsonify({"ok": True, "id": new_id})


@app.put("/api/entries/<int:entry_id>")
def update_entry(entry_id: int):
    data = request.get_json(force=True, silent=False)

    day = str(data.get("day") or "").strip()
    meal = str(data.get("meal") or "").strip()
    ts = data.get("ts")
    note = str(data.get("note") or "").strip()
    calories = data.get("calories", 0)

    if not day or not meal or ts is None:
        return jsonify({"error": "Missing day/meal/ts"}), 400

    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return jsonify({"error": "ts must be an integer (unix ms)"}), 400

    try:
        cal_int = int(calories)
        if cal_int < 0:
            cal_int = 0
    except (TypeError, ValueError):
        cal_int = 0

    with db() as conn:
        cur = conn.execute(
            "UPDATE entries SET day=?, meal=?, ts=?, note=?, calories=? WHERE id=?",
            (day, meal, ts_int, note, cal_int, entry_id),
        )
        if cur.rowcount == 0:
            return jsonify({"error": "Entry not found"}), 404

    return jsonify({"ok": True})


@app.delete("/api/entries/<int:entry_id>")
def delete_entry(entry_id: int):
    with db() as conn:
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
    return jsonify({"ok": True})


@app.post("/api/entries/clear")
def clear_day():
    day = request.args.get("day") or iso_today()
    with db() as conn:
        conn.execute("DELETE FROM entries WHERE day=?", (day,))
    return jsonify({"ok": True, "day": day})


@app.get("/api/histogram/all")
def histogram_all():
    counts = [0] * 24
    with db() as conn:
        rows = conn.execute("SELECT ts FROM entries").fetchall()
    for r in rows:
        hour = datetime.fromtimestamp(int(r["ts"]) / 1000.0).hour
        counts[hour] += 1
    return jsonify({"counts": counts, "total_entries": sum(counts)})


@app.get("/api/summary")
def summary():
    day_str = request.args.get("day") or iso_today()
    try:
        d = parse_iso_day(day_str)
    except Exception:
        return jsonify({"error": "Invalid day. Use YYYY-MM-DD"}), 400

    w0, w1 = week_bounds(d)
    m0, m1 = month_bounds(d)

    with db() as conn:
        day_total = sum_calories_between(conn, d, d)
        week_total = sum_calories_between(conn, w0, w1)
        month_total = sum_calories_between(conn, m0, m1)
        all_total = int(
            conn.execute("SELECT COALESCE(SUM(calories),0) AS total FROM entries").fetchone()["total"] or 0
        )

    return jsonify(
        {
            "day": day_str,
            "day_total": day_total,
            "week_start": w0.isoformat(),
            "week_end": w1.isoformat(),
            "week_total": week_total,
            "month_start": m0.isoformat(),
            "month_end": m1.isoformat(),
            "month_total": month_total,
            "all_total": all_total,
        }
    )


# ==================== (optional) CSV exports ====================
@app.get("/export/entries.csv")
def export_entries_csv():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, day, meal, ts, note, calories FROM entries ORDER BY day ASC, ts ASC"
        ).fetchall()

    lines = ["id,day,meal,ts_iso,ts_ms,calories,note"]
    for r in rows:
        dt_local = datetime.fromtimestamp(int(r["ts"]) / 1000.0)
        ts_iso = dt_local.strftime("%Y-%m-%d %H:%M:%S")
        meal = (r["meal"] or "").replace('"', '""')
        note = (r["note"] or "").replace('"', '""')
        cal = int(r["calories"] or 0)
        lines.append(f'{r["id"]},{r["day"]},"{meal}",{ts_iso},{r["ts"]},{cal},"{note}"')

    data = "\n".join(lines) + "\n"
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="entries.csv"'},
    )


@app.get("/export/histogram_24h.csv")
def export_histogram_24h_csv():
    counts = [0] * 24
    with db() as conn:
        rows = conn.execute("SELECT ts FROM entries").fetchall()
    for r in rows:
        hour = datetime.fromtimestamp(int(r["ts"]) / 1000.0).hour
        counts[hour] += 1

    lines = ["hour,count"]
    for h in range(24):
        lines.append(f"{h},{counts[h]}")
    data = "\n".join(lines) + "\n"

    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="histogram_24h.csv"'},
    )

with app.app_context():
    init_db()

if __name__ == "__main__":
    # LAN hosting:
    app.run(host="0.0.0.0", port=5000)
