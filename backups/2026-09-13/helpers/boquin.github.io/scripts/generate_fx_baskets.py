#!/usr/bin/env python3
"""
FX Baskets Interactive Dashboard Generator
Fetches daily FX rates from Alpha Vantage and generates a self-contained
HTML dashboard showing currency relative strength vs a customizable basket.

Run from the repo root:
    ALPHA_VANTAGE_API_KEY=your_key python3 scripts/generate_fx_baskets.py

Data is cached in reports/fx-baskets/fx_cache.csv and refreshed when
older than CACHE_MAX_AGE_DAYS. Pass --cache-only to skip API calls.

The core metric: basket_norm / em_norm * 100
  > 100 = currency outperformed basket (strengthened vs basket)
  < 100 = currency underperformed basket (weakened vs basket)
"""

import requests
import pandas as pd
import numpy as np
import json
import os
import sys
import time
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────

START_DATE = "2014-01-01"
CACHE_MAX_AGE_DAYS = 7

SYMBOLS = [
    "EUR", "AUD", "CAD", "GBP", "JPY", "SEK", "NOK", "NZD", "CHF",
    "MXN", "CLP", "BRL", "COP", "PEN",
    "KRW", "IDR", "INR", "THB", "PHP", "SGD",
    "PLN", "HUF", "CZK", "ZAR", "TRY",
]

DEFAULT_BASKET = ["EUR", "GBP", "AUD", "JPY", "CHF"]

CCY_NAMES = {
    "EUR": "Euro", "GBP": "British Pound", "AUD": "Australian Dollar",
    "NZD": "New Zealand Dollar", "CAD": "Canadian Dollar", "CHF": "Swiss Franc",
    "JPY": "Japanese Yen", "SEK": "Swedish Krona", "NOK": "Norwegian Krone",
    "MXN": "Mexican Peso", "CLP": "Chilean Peso", "BRL": "Brazilian Real",
    "COP": "Colombian Peso", "PEN": "Peruvian Sol", "KRW": "Korean Won",
    "IDR": "Indonesian Rupiah", "INR": "Indian Rupee", "THB": "Thai Baht",
    "PHP": "Philippine Peso", "SGD": "Singapore Dollar", "PLN": "Polish Zloty",
    "HUF": "Hungarian Forint", "CZK": "Czech Koruna", "ZAR": "South African Rand",
    "TRY": "Turkish Lira",
}

CCY_REGION = {
    "EUR": "DM", "GBP": "DM", "AUD": "DM", "NZD": "DM", "CAD": "DM",
    "CHF": "DM", "JPY": "DM", "SEK": "DM", "NOK": "DM",
    "MXN": "LATAM", "CLP": "LATAM", "BRL": "LATAM", "COP": "LATAM", "PEN": "LATAM",
    "KRW": "Asia", "IDR": "Asia", "INR": "Asia", "THB": "Asia",
    "PHP": "Asia", "SGD": "Asia",
    "PLN": "EMEA", "HUF": "EMEA", "CZK": "EMEA", "ZAR": "EMEA", "TRY": "EMEA",
}

CCY_COLORS = {
    "EUR": "#1565c0", "GBP": "#1976d2", "AUD": "#2196f3", "NZD": "#42a5f5",
    "CAD": "#0d47a1", "CHF": "#0277bd", "JPY": "#0288d1",
    "SEK": "#26c6da", "NOK": "#00838f",
    "MXN": "#b71c1c", "CLP": "#c62828", "BRL": "#e53935",
    "COP": "#f44336", "PEN": "#ff7043",
    "KRW": "#2e7d32", "IDR": "#388e3c", "INR": "#43a047",
    "THB": "#66bb6a", "PHP": "#81c784", "SGD": "#00897b",
    "PLN": "#6a1b9a", "HUF": "#7b1fa2", "CZK": "#8e24aa",
    "ZAR": "#ab47bc", "TRY": "#ce93d8",
}

OUTPUT_DIR = "reports/fx-baskets"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")
CACHE_FILE = os.path.join(OUTPUT_DIR, "fx_cache.csv")


# ── Data Loading ───────────────────────────────────────────────────────────────

def fetch_from_alpha_vantage(api_key):
    """Fetch daily FX close prices from Alpha Vantage (from_symbol=USD)."""
    close_data = {}
    for i, symbol in enumerate(SYMBOLS):
        print(f"  [{i+1}/{len(SYMBOLS)}] USD/{symbol}...", end=" ")
        try:
            resp = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "FX_DAILY",
                    "from_symbol": "USD",
                    "to_symbol": symbol,
                    "outputsize": "full",
                    "apikey": api_key,
                },
                timeout=30,
            )
            data = resp.json()
            ts = data["Time Series FX (Daily)"]
            s = pd.Series(
                {k: float(v["4. close"]) for k, v in ts.items()},
                name=symbol,
            )
            s.index = pd.to_datetime(s.index)
            s = s.sort_index().loc[START_DATE:]
            close_data[symbol] = s
            print("ok")
        except Exception as e:
            msg = data.get("Note") or data.get("Error Message") or str(e)
            print(f"FAILED: {msg}")
        if i < len(SYMBOLS) - 1:
            time.sleep(15)  # 5 calls/min on free tier

    df = pd.DataFrame(close_data)
    df.index.name = "date"
    return df


def load_data():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Use cache only if fresh
    if os.path.exists(CACHE_FILE):
        age = (datetime.now() - datetime.fromtimestamp(
            os.path.getmtime(CACHE_FILE))).days
        if age < CACHE_MAX_AGE_DAYS:
            print(f"Loading from cache (age: {age}d)...")
            df = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
            df = df.apply(pd.to_numeric, errors="coerce")
            print(f"  {len(df)} days × {len(df.columns)} currencies")
            return df
        print(f"Cache is {age}d old — fetching fresh data...")

    # Require API key — no fallback to stale local files
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("ERROR: ALPHA_VANTAGE_API_KEY not set. Data not available.")
        sys.exit(1)

    print(f"Fetching {len(SYMBOLS)} currencies from Alpha Vantage (~6 min)...")
    df = fetch_from_alpha_vantage(api_key)

    if df.empty or len(df.columns) == 0:
        print("ERROR: No data returned from Alpha Vantage. Data not available.")
        sys.exit(1)

    df.to_csv(CACHE_FILE)
    print(f"  Saved cache → {CACHE_FILE}")
    return df


def prepare_weekly(df):
    """Forward-fill gaps, resample to weekly Friday close."""
    df = df.ffill().bfill()
    df = df.resample("W-FRI").last()
    df = df.dropna(how="all")
    # Keep only symbols with ≥50% coverage
    coverage = df.notna().mean()
    df = df[coverage[coverage >= 0.5].index]
    df = df[[c for c in SYMBOLS if c in df.columns]]
    print(f"Weekly: {len(df)} weeks × {len(df.columns)} currencies  "
          f"({df.index[0].strftime('%b %Y')} → {df.index[-1].strftime('%b %Y')})")
    return df


# ── HTML Generation ────────────────────────────────────────────────────────────

def generate_html(df):
    last_date = df.index[-1].strftime("%B %Y")
    generated = datetime.now().strftime("%Y-%m-%d")

    available = list(df.columns)
    dates_list = [d.strftime("%Y-%m-%d") for d in df.index]
    fx_data = {
        c: [round(v, 6) if pd.notna(v) else None for v in df[c]]
        for c in available
    }

    data_json        = json.dumps({"dates": dates_list, "fx": fx_data}, separators=(",", ":"))
    ccys_json        = json.dumps(available)
    names_json       = json.dumps({c: CCY_NAMES.get(c, c) for c in available})
    regions_json     = json.dumps({c: CCY_REGION.get(c, "Other") for c in available})
    colors_json      = json.dumps({c: CCY_COLORS.get(c, "#888") for c in available})
    basket_json      = json.dumps([c for c in DEFAULT_BASKET if c in available])
    em_json          = json.dumps([c for c in available if CCY_REGION.get(c) != "DM"])
    dm_json          = json.dumps([c for c in available if CCY_REGION.get(c) == "DM"])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FX Baskets Dashboard — boquin.xyz</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f7fa;color:#1a1a1a;font-size:14px}}

.hdr{{background:#1a3a2f;color:#fff;padding:20px 32px}}
.hdr h1{{font-size:1.4rem;font-weight:700;letter-spacing:-.4px}}
.hdr .sub{{font-size:.82rem;opacity:.72;margin-top:5px}}
.hdr .meta{{font-size:.75rem;opacity:.55;margin-top:3px}}

.ctrl-bar{{background:#fff;border-bottom:1px solid #e4e8ec;padding:10px 32px;display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}}
.ctrl-group{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
.ctrl-lbl{{font-size:.75rem;color:#666;font-weight:600;white-space:nowrap}}
.btn-grp{{display:flex;gap:3px}}
.btn{{padding:4px 11px;border:1px solid #cdd4db;border-radius:5px;background:#fff;cursor:pointer;font-size:.78rem;color:#555;transition:background .12s,color .12s;white-space:nowrap}}
.btn.active{{background:#1a3a2f;color:#fff;border-color:#1a3a2f}}
.btn:hover:not(.active){{background:#f0f5f0}}
.btn.sm{{padding:3px 8px;font-size:.72rem}}

/* Basket chips */
.basket-wrap{{display:flex;flex-wrap:wrap;gap:5px;align-items:center}}
.b-chip{{display:inline-flex;align-items:center;gap:3px;padding:3px 8px 3px 10px;border-radius:20px;font-size:.75rem;font-weight:600;cursor:default;border:1px solid transparent}}
.b-chip .bx{{opacity:.6;cursor:pointer;font-size:.65rem;margin-left:1px;padding:0 2px}}
.b-chip .bx:hover{{opacity:1}}
.b-add-wrap{{position:relative}}
.b-add{{padding:3px 9px;border:1px dashed #aaa;border-radius:20px;font-size:.75rem;color:#555;cursor:pointer;background:transparent}}
.b-add:hover{{border-color:#1a3a2f;color:#1a3a2f}}
.b-dropdown{{display:none;position:absolute;top:calc(100% + 4px);left:0;background:#fff;border:1px solid #ddd;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:100;min-width:160px;max-height:260px;overflow-y:auto}}
.b-dropdown.open{{display:block}}
.b-dropdown-item{{padding:7px 14px;font-size:.8rem;cursor:pointer;display:flex;justify-content:space-between;align-items:center}}
.b-dropdown-item:hover{{background:#f0f5f0}}
.b-dropdown-item.in-basket{{opacity:.4;cursor:not-allowed;pointer-events:none}}
.b-region-hdr{{padding:4px 14px 2px;font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#aaa;background:#fafafa;border-top:1px solid #f0f0f0}}

/* Tabs */
.tabs{{background:#fff;border-bottom:1px solid #e4e8ec;padding:0 32px;display:flex;overflow-x:auto}}
.tab{{padding:11px 18px;font-size:.85rem;cursor:pointer;border-bottom:3px solid transparent;color:#666;white-space:nowrap;transition:all .12s}}
.tab.active{{color:#1a3a2f;border-bottom-color:#1a3a2f;font-weight:600}}
.tab:hover:not(.active){{background:#f8faf8;color:#333}}

.content{{padding:20px 32px;max-width:1440px;margin:0 auto}}
.panel{{display:none}}.panel.active{{display:block}}
.card{{background:#fff;border:1px solid #e4e8ec;border-radius:10px;padding:16px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.card-title{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:12px}}

/* Single currency */
.sc-hdr{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;flex-wrap:wrap;gap:12px}}
.sc-name{{font-size:1.2rem;font-weight:700}}
.sc-region{{display:inline-block;font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:20px;margin-left:8px;vertical-align:middle;opacity:.85}}
.sc-stats{{display:flex;gap:20px;margin-top:6px;flex-wrap:wrap}}
.sc-stat{{display:flex;flex-direction:column}}
.sc-stat-lbl{{font-size:.68rem;text-transform:uppercase;letter-spacing:.5px;color:#999;font-weight:600}}
.sc-stat-val{{font-size:1rem;font-weight:700;margin-top:2px}}
.sc-stat-val.pos{{color:#2e7d32}}.sc-stat-val.neg{{color:#c62828}}.sc-stat-val.neu{{color:#555}}
.sc-pick{{padding:6px 10px;border:1px solid #cdd4db;border-radius:6px;font-size:.82rem;min-width:170px}}

/* Main chart hint */
.chart-hint{{font-size:.74rem;color:#999;margin-bottom:8px;display:flex;align-items:center;gap:5px}}

@media(max-width:640px){{
  .hdr,.ctrl-bar,.content,.tabs{{padding-left:12px;padding-right:12px}}
}}
</style>
</head>
<body>

<div class="hdr">
  <h1>FX Baskets — Currency Relative Strength</h1>
  <div class="sub">Performance of 25 currencies vs a customizable basket of majors · indexed to 100 at start date</div>
  <div class="meta">Source: Alpha Vantage FX Daily · Last data point: {last_date} · Generated: {generated}</div>
</div>

<div class="ctrl-bar">
  <div class="ctrl-group">
    <span class="ctrl-lbl">Period:</span>
    <div class="btn-grp" id="period-grp">
      <button class="btn" data-p="1Y"  onclick="setPeriod('1Y')">1Y</button>
      <button class="btn active" data-p="3Y"  onclick="setPeriod('3Y')">3Y</button>
      <button class="btn" data-p="5Y"  onclick="setPeriod('5Y')">5Y</button>
      <button class="btn" data-p="Max" onclick="setPeriod('Max')">Max</button>
    </div>
  </div>

  <div class="ctrl-group">
    <span class="ctrl-lbl">Show:</span>
    <div class="btn-grp" id="show-grp">
      <button class="btn active" data-s="EM"  onclick="setShow('EM')">EM</button>
      <button class="btn"        data-s="DM"  onclick="setShow('DM')">DM</button>
      <button class="btn"        data-s="All" onclick="setShow('All')">All</button>
    </div>
  </div>

  <div class="ctrl-group" style="flex:1;min-width:260px">
    <span class="ctrl-lbl">Basket:</span>
    <div class="basket-wrap" id="basket-chips"></div>
    <div class="b-add-wrap">
      <button class="b-add" onclick="toggleDropdown()">+ Add ▾</button>
      <div class="b-dropdown" id="basket-dropdown"></div>
    </div>
    <div class="btn-grp" style="margin-left:6px">
      <button class="btn sm" onclick="setPreset('dm5')" title="EUR GBP AUD JPY CHF">DM Majors</button>
      <button class="btn sm" onclick="setPreset('g10')" title="EUR GBP AUD NZD CAD CHF JPY SEK NOK">G10</button>
    </div>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('main')">Relative Strength</div>
  <div class="tab"        onclick="showTab('rankings')">Rankings</div>
  <div class="tab"        onclick="showTab('single')">Single Currency</div>
</div>

<div class="content">

  <!-- RELATIVE STRENGTH -->
  <div class="panel active" id="panel-main">
    <div class="card">
      <div class="card-title" id="main-title">EM Currencies vs DM Majors Basket · 3-year window</div>
      <div class="chart-hint">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        Above 100 = outperformed basket &nbsp;·&nbsp; Below 100 = underperformed basket &nbsp;·&nbsp; Click any line to open in Single Currency
      </div>
      <div id="chart-main" style="height:500px"></div>
    </div>
  </div>

  <!-- RANKINGS -->
  <div class="panel" id="panel-rankings">
    <div class="card">
      <div class="card-title" id="rankings-title">Current relative strength vs basket — sorted best to worst</div>
      <div class="chart-hint">Click any bar to open in Single Currency</div>
      <div id="chart-rankings" style="height:560px"></div>
    </div>
  </div>

  <!-- SINGLE CURRENCY -->
  <div class="panel" id="panel-single">
    <div class="card">
      <div class="sc-hdr">
        <div>
          <span class="sc-name" id="sc-name">—</span>
          <span class="sc-region" id="sc-region-badge"></span>
          <div class="sc-stats" id="sc-stats"></div>
        </div>
        <select class="sc-pick" id="sc-picker" onchange="goToSingle(this.value)"></select>
      </div>
      <div id="chart-single" style="height:440px"></div>
    </div>
  </div>

</div>

<script>
// ── Embedded data ──────────────────────────────────────────────────────────────
const D = {data_json};
const DATES = D.dates;
const FX    = D.fx;
const CCYS  = {ccys_json};
const NAMES = {names_json};
const REGIONS = {regions_json};
const COLORS  = {colors_json};
const EM_LIST = {em_json};
const DM_LIST = {dm_json};

// ── State ──────────────────────────────────────────────────────────────────────
let BASKET  = {basket_json}.slice();
let PERIOD  = '3Y';
let SHOW    = 'EM';
let SC_CCY  = EM_LIST[0] || CCYS[0];
const TABS  = ['main','rankings','single'];
let SC_INIT = false, RANK_INIT = false;

// ── Helpers ────────────────────────────────────────────────────────────────────
function startIdx() {{
  const n = DATES.length;
  const steps = {{'1Y':52,'3Y':156,'5Y':260,'Max':n}};
  return Math.max(0, n - (steps[PERIOD] || n));
}}

function showCcys() {{
  if(SHOW==='EM') return EM_LIST.filter(c=>FX[c]);
  if(SHOW==='DM') return DM_LIST.filter(c=>FX[c]);
  return CCYS.filter(c=>FX[c]);
}}

// Core formula: basket_norm / em_norm * 100
// (all FX data = FCY per USD; ratio inversion gives "higher = stronger vs basket")
function computeRS(si, basket, targets) {{
  if(!basket.length) return {{}};
  const n = DATES.length;

  // Normalise each basket currency to 100 at si
  const bNorms = basket.map(c => {{
    if(!FX[c]) return null;
    const base = FX[c][si];
    if(!base) return null;
    return FX[c].map(v => v != null ? v / base * 100 : null);
  }}).filter(Boolean);
  if(!bNorms.length) return {{}};

  // Basket average
  const bAvg = Array.from({{length:n}}, (_,i) => {{
    const vals = bNorms.map(bn=>bn[i]).filter(v=>v!=null);
    return vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null;
  }});

  // Relative strength for each target
  const result = {{}};
  for(const ccy of targets) {{
    if(!FX[ccy]) continue;
    const base = FX[ccy][si];
    if(!base) continue;
    const norm = FX[ccy].map(v => v!=null ? v/base*100 : null);
    result[ccy] = norm.map((v,i) => (v!=null && bAvg[i]!=null) ? bAvg[i]/v*100 : null);
  }}
  return result;
}}

function getLatestRS(ccy, si) {{
  const rs = computeRS(si, BASKET, [ccy]);
  const vals = rs[ccy];
  if(!vals) return null;
  for(let i=vals.length-1; i>=0; i--) if(vals[i]!=null) return vals[i];
  return null;
}}

// ── Tab navigation ─────────────────────────────────────────────────────────────
function showTab(name) {{
  TABS.forEach((t,i) => {{
    document.getElementById('panel-'+t).classList.toggle('active', t===name);
    document.querySelectorAll('.tab')[i].classList.toggle('active', t===name);
  }});
  if(name==='rankings') drawRankings();
  if(name==='single') {{ if(!SC_INIT) initSingle(); else drawSingle(); }}
}}

// ── Controls ───────────────────────────────────────────────────────────────────
function setPeriod(p) {{
  PERIOD = p;
  document.querySelectorAll('#period-grp .btn').forEach(b=>b.classList.toggle('active', b.dataset.p===p));
  refreshAll();
}}
function setShow(s) {{
  SHOW = s;
  document.querySelectorAll('#show-grp .btn').forEach(b=>b.classList.toggle('active', b.dataset.s===s));
  refreshAll();
}}
function setPreset(preset) {{
  const presets = {{
    dm5: ['EUR','GBP','AUD','JPY','CHF'],
    g10: ['EUR','GBP','AUD','NZD','CAD','CHF','JPY','SEK','NOK'],
  }};
  BASKET = (presets[preset]||[]).filter(c=>FX[c]);
  renderBasketChips();
  refreshAll();
}}
function refreshAll() {{
  drawMain();
  if(RANK_INIT) drawRankings();
  if(SC_INIT) drawSingle();
  updateTitles();
}}
function updateTitles() {{
  const showLabel = SHOW==='EM'?'EM':'DM'==='DM'?'DM':'All';
  const basketStr = BASKET.join(', ');
  document.getElementById('main-title').textContent =
    `${{SHOW}} currencies vs basket (${{basketStr}}) · ${{PERIOD}} window`;
  document.getElementById('rankings-title').textContent =
    `Current relative strength vs basket (${{basketStr}}) — sorted best to worst`;
}}

// ── Basket chip UI ─────────────────────────────────────────────────────────────
function renderBasketChips() {{
  const wrap = document.getElementById('basket-chips');
  wrap.innerHTML = '';
  BASKET.forEach(ccy => {{
    const chip = document.createElement('div');
    chip.className = 'b-chip';
    chip.style.cssText = `background:${{COLORS[ccy]}}20;border-color:${{COLORS[ccy]}};color:${{COLORS[ccy]}}`;
    chip.innerHTML = `${{ccy}}<span class="bx" onclick="removeFromBasket('${{ccy}}')" title="Remove">✕</span>`;
    wrap.appendChild(chip);
  }});
  renderDropdown();
}}
function removeFromBasket(ccy) {{
  if(BASKET.length <= 1) return; // keep at least 1
  BASKET = BASKET.filter(c=>c!==ccy);
  renderBasketChips();
  refreshAll();
}}
function addToBasket(ccy) {{
  if(!BASKET.includes(ccy)) {{ BASKET.push(ccy); }}
  renderBasketChips();
  closeDropdown();
  refreshAll();
}}
function toggleDropdown() {{
  document.getElementById('basket-dropdown').classList.toggle('open');
}}
function closeDropdown() {{
  document.getElementById('basket-dropdown').classList.remove('open');
}}
function renderDropdown() {{
  const dd = document.getElementById('basket-dropdown');
  const regions = [{{'label':'DM','items':DM_LIST}},{{'label':'LATAM','items':['MXN','CLP','BRL','COP','PEN']}},{{'label':'Asia','items':['KRW','IDR','INR','THB','PHP','SGD']}},{{'label':'EMEA','items':['PLN','HUF','CZK','ZAR','TRY']}}];
  dd.innerHTML = '';
  regions.forEach(rg => {{
    const avail = rg.items.filter(c=>FX[c]);
    if(!avail.length) return;
    const hdr = document.createElement('div');
    hdr.className = 'b-region-hdr';
    hdr.textContent = rg.label;
    dd.appendChild(hdr);
    avail.forEach(ccy => {{
      const item = document.createElement('div');
      item.className = 'b-dropdown-item' + (BASKET.includes(ccy) ? ' in-basket' : '');
      item.innerHTML = `<span>${{ccy}}</span><span style="font-size:.72rem;color:#999">${{NAMES[ccy]||''}}</span>`;
      item.onclick = () => addToBasket(ccy);
      dd.appendChild(item);
    }});
  }});
}}
document.addEventListener('click', e => {{
  if(!e.target.closest('.b-add-wrap')) closeDropdown();
}});

// ── Main chart ─────────────────────────────────────────────────────────────────
function drawMain() {{
  const si = startIdx();
  const targets = showCcys();
  const rs = computeRS(si, BASKET, targets);
  const dates = DATES.slice(si);

  const traces = targets.map(ccy => ({{
    type: 'scatter', mode: 'lines',
    name: ccy,
    x: dates,
    y: (rs[ccy]||[]).slice(si),
    line: {{color: COLORS[ccy]||'#888', width:2}},
    hovertemplate: `<b>${{ccy}}</b> (${{NAMES[ccy]||''}})<br>%{{x|%b %Y}}: %{{y:.1f}}<extra></extra>`,
  }}));

  const layout = {{
    height: 500,
    plot_bgcolor:'white', paper_bgcolor:'white',
    xaxis: {{gridcolor:'#f0f0f0',title:''}},
    yaxis: {{gridcolor:'#f0f0f0',title:'Relative strength (start = 100)',zerolinecolor:'#ccc'}},
    legend: {{orientation:'v',x:1.01,y:1,font:{{size:11}}}},
    margin: {{l:60,r:120,t:16,b:40}},
    hovermode: 'x unified',
    shapes: [{{
      type:'line',xref:'paper',yref:'y',
      x0:0,x1:1,y0:100,y1:100,
      line:{{color:'#555',width:1,dash:'dash'}}
    }}],
  }};

  Plotly.react('chart-main', traces, layout, {{responsive:true}}).then(() => {{
    document.getElementById('chart-main').on('plotly_click', data => {{
      if(!data.points.length) return;
      goToSingle(data.points[0].data.name);
    }});
  }});
}}

// ── Rankings chart ─────────────────────────────────────────────────────────────
function drawRankings() {{
  RANK_INIT = true;
  const si = startIdx();
  const targets = CCYS.filter(c=>FX[c] && !BASKET.includes(c)).concat(
    BASKET.filter(c=>FX[c])  // basket at end, slightly muted
  );
  const rs = computeRS(si, BASKET, targets);

  const entries = targets
    .map(ccy => ({{ ccy, val: getLatestRS(ccy, si) }}))
    .filter(e => e.val != null)
    .sort((a,b) => b.val - a.val);

  const colors = entries.map(e => COLORS[e.ccy]||'#888');
  const isBasket = entries.map(e => BASKET.includes(e.ccy));

  const tr = {{
    type:'bar', orientation:'h',
    x: entries.map(e => e.val),
    y: entries.map(e => e.ccy),
    marker: {{
      color: colors,
      opacity: entries.map((_,i) => isBasket[i] ? 0.4 : 0.85),
    }},
    hovertemplate: entries.map(e =>
      `<b>${{e.ccy}}</b> (${{NAMES[e.ccy]||''}})  ${{e.val.toFixed(1)}}<extra></extra>`
    ),
    customdata: entries.map(e=>e.ccy),
  }};

  const layout = {{
    height: Math.max(400, entries.length * 18 + 60),
    plot_bgcolor:'white', paper_bgcolor:'white',
    xaxis: {{gridcolor:'#f0f0f0', title:'Relative strength index (start = 100)', zerolinecolor:'#ccc'}},
    yaxis: {{tickfont:{{size:11}}}},
    margin: {{l:50,r:20,t:20,b:40}},
    shapes: [{{
      type:'line',xref:'x',yref:'paper',
      x0:100,x1:100,y0:0,y1:1,
      line:{{color:'#555',width:1,dash:'dash'}}
    }}],
  }};

  Plotly.react('chart-rankings', [tr], layout, {{responsive:true}}).then(() => {{
    document.getElementById('chart-rankings').on('plotly_click', data => {{
      if(!data.points.length) return;
      goToSingle(data.points[0].customdata);
    }});
  }});
}}

// ── Single currency ────────────────────────────────────────────────────────────
function initSingle() {{
  SC_INIT = true;
  const sel = document.getElementById('sc-picker');
  CCYS.forEach(c => {{
    const o = document.createElement('option');
    o.value=c; o.textContent=`${{c}} — ${{NAMES[c]||c}}`;
    if(c===SC_CCY) o.selected=true;
    sel.appendChild(o);
  }});
  drawSingle();
}}
function goToSingle(ccy) {{
  SC_CCY = ccy;
  showTab('single');
  const sel = document.getElementById('sc-picker');
  if(sel) sel.value = ccy;
  drawSingle();
}}
function drawSingle() {{
  if(!FX[SC_CCY]) return;
  const si = startIdx();
  const rs = computeRS(si, BASKET, [SC_CCY]);
  const rsVals = (rs[SC_CCY]||[]);
  const rawVals = FX[SC_CCY];
  const dates = DATES.slice(si);
  const rsSlice  = rsVals.slice(si);
  const rawSlice = rawVals.slice(si);

  const col = COLORS[SC_CCY]||'#1565c0';
  const reg = REGIONS[SC_CCY]||'';

  // Stats
  const latestRS = rsSlice.filter(v=>v!=null).slice(-1)[0];
  const yearAgoIdx = Math.max(0, rsSlice.length - 52);
  const yearAgoRS  = rsSlice.slice(yearAgoIdx).filter(v=>v!=null)[0];
  const chg1y = (latestRS!=null && yearAgoRS!=null) ? latestRS - yearAgoRS : null;
  const minRS  = Math.min(...rsSlice.filter(v=>v!=null));
  const maxRS  = Math.max(...rsSlice.filter(v=>v!=null));

  document.getElementById('sc-name').textContent = SC_CCY;
  const badge = document.getElementById('sc-region-badge');
  badge.textContent = reg;
  badge.style.cssText = `background:${{col}}20;color:${{col}};border:1px solid ${{col}}40`;

  const sign = v => v>0?'+':'';
  const cls  = v => v>0?'pos':v<0?'neg':'neu';
  document.getElementById('sc-stats').innerHTML = `
    <div class="sc-stat">
      <span class="sc-stat-lbl">vs Basket (latest)</span>
      <span class="sc-stat-val ${{cls(latestRS-100)}}">${{latestRS!=null?latestRS.toFixed(1):'—'}}</span>
    </div>
    <div class="sc-stat">
      <span class="sc-stat-lbl">1Y change</span>
      <span class="sc-stat-val ${{chg1y!=null?cls(chg1y):'neu'}}">${{chg1y!=null?sign(chg1y)+chg1y.toFixed(1):'—'}}</span>
    </div>
    <div class="sc-stat">
      <span class="sc-stat-lbl">Range (period)</span>
      <span class="sc-stat-val neu">${{minRS.toFixed(1)}} – ${{maxRS.toFixed(1)}}</span>
    </div>`;

  const trRS = {{
    type:'scatter', mode:'lines', name:'vs Basket',
    x:dates, y:rsSlice,
    line:{{color:col,width:2.5}},
    hovertemplate:'%{{x|%b %Y}}: %{{y:.1f}}<extra></extra>',
    yaxis:'y',
  }};
  const trRaw = {{
    type:'scatter', mode:'lines', name:'FCY per USD (raw)',
    x:dates, y:rawSlice,
    line:{{color:'#aaa',width:1.5,dash:'dot'}},
    hovertemplate:'%{{x|%b %Y}}: %{{y:.4f}}<extra></extra>',
    yaxis:'y2',
  }};

  const layout = {{
    height:440,
    plot_bgcolor:'white', paper_bgcolor:'white',
    xaxis:{{gridcolor:'#f0f0f0',title:''}},
    yaxis:{{
      gridcolor:'#f0f0f0',zerolinecolor:'#ccc',
      title:'vs Basket (100 = start)', titlefont:{{size:11}},
    }},
    yaxis2:{{
      overlaying:'y', side:'right', showgrid:false,
      title:'FCY per USD', titlefont:{{size:11,color:'#bbb'}},
      tickfont:{{color:'#bbb'}},
    }},
    legend:{{orientation:'h',x:0,y:1.08,font:{{size:11}}}},
    margin:{{l:60,r:70,t:30,b:40}},
    hovermode:'x unified',
    shapes:[{{
      type:'line',xref:'paper',yref:'y',
      x0:0,x1:1,y0:100,y1:100,
      line:{{color:'#555',width:1,dash:'dash'}}
    }}],
  }};

  Plotly.react('chart-single',[trRS,trRaw],layout,{{responsive:true}});
}}

// ── Init ───────────────────────────────────────────────────────────────────────
renderBasketChips();
drawMain();
updateTitles();
</script>
</body>
</html>"""
    return html


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    cache_only = "--cache-only" in sys.argv

    df_raw = load_data(cache_only=cache_only)
    df = prepare_weekly(df_raw)

    print("Generating HTML...")
    html = generate_html(df)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"Report saved → {OUTPUT_FILE}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
