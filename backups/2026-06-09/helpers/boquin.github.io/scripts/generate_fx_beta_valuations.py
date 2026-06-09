#!/usr/bin/env python3
"""
FX Beta Valuations Dashboard
OLS peer-beta fair-value model for 25 currencies.
Three pre-computed training windows selectable in the browser.

Run:
    python3 scripts/generate_fx_beta_valuations.py
"""

import os
import json
import datetime
from datetime import date, timedelta
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf
import statsmodels.api as sm

# ── Config ─────────────────────────────────────────────────────────────────────

CHART_START = "2015-01-01"
N_PEERS = 6
YEARS_FX = 12

TRAIN_WINDOWS = [
    ("2014-2017", "2014-01-01", "2017-12-31"),
    ("2016-2019", "2016-01-01", "2019-12-31"),
    ("2018-2021", "2018-01-01", "2021-12-31"),
]

CCY_LIST = [
    "BRL", "MXN", "CLP", "ZAR", "TRY", "PLN", "HUF", "CZK",
    "CNY", "KRW", "SGD", "MYR", "IDR", "INR", "PHP", "THB",
    "EUR", "JPY", "GBP", "CAD", "AUD", "NZD", "SEK", "NOK", "CHF",
]

EXCEPTIONS = ["EUR", "GBP", "NZD", "AUD"]

CCY_NAMES = {
    "BRL": "Brazilian Real",      "MXN": "Mexican Peso",        "CLP": "Chilean Peso",
    "ZAR": "South African Rand",  "TRY": "Turkish Lira",        "PLN": "Polish Zloty",
    "HUF": "Hungarian Forint",    "CZK": "Czech Koruna",        "CNY": "Chinese Yuan",
    "KRW": "Korean Won",          "SGD": "Singapore Dollar",    "MYR": "Malaysian Ringgit",
    "IDR": "Indonesian Rupiah",   "INR": "Indian Rupee",        "PHP": "Philippine Peso",
    "THB": "Thai Baht",           "EUR": "Euro",                "JPY": "Japanese Yen",
    "GBP": "British Pound",       "CAD": "Canadian Dollar",     "AUD": "Australian Dollar",
    "NZD": "New Zealand Dollar",  "SEK": "Swedish Krona",       "NOK": "Norwegian Krone",
    "CHF": "Swiss Franc",
}

REGION = {
    "EUR": "DM", "JPY": "DM", "GBP": "DM", "CAD": "DM", "AUD": "DM",
    "NZD": "DM", "SEK": "DM", "NOK": "DM", "CHF": "DM",
    "BRL": "EM", "MXN": "EM", "CLP": "EM", "ZAR": "EM", "TRY": "EM",
    "PLN": "EM", "HUF": "EM", "CZK": "EM", "CNY": "EM", "KRW": "EM",
    "SGD": "EM", "MYR": "EM", "IDR": "EM", "INR": "EM", "PHP": "EM",
    "THB": "EM",
}

OUTPUT_DIR  = os.environ.get("OUTPUT_DIR") or os.path.expanduser("~/boquin.github.io/reports/fx-beta-valuations")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# ── Data fetch ──────────────────────────────────────────────────────────────────

def fetch_fx_data():
    print(f"Fetching {YEARS_FX}Y FX data for {len(CCY_LIST)} currencies via yfinance…")
    start_date = datetime.datetime.now() - timedelta(days=365 * YEARS_FX)
    tickers    = [f"{c}USD=X" for c in CCY_LIST]

    data = yf.download(tickers, start=start_date, end=date.today(),
                       group_by="ticker", auto_adjust=True, progress=False)

    frames = []
    for ccy, ticker in zip(CCY_LIST, tickers):
        try:
            s = data[ticker]["Close"] if ticker in data.columns.get_level_values(0) else data["Close"]
            frames.append(s.rename(ccy))
        except Exception:
            print(f"  Warning: could not extract {ccy}")

    df = pd.concat(frames, axis=1)

    # Exceptions (EUR/GBP/NZD/AUD) come as USD-per-CCY → invert to CCY-per-USD for uniformity
    for c in EXCEPTIONS:
        if c in df.columns:
            df[c] = 1.0 / df[c]

    # Invert everything: EM → CCY/USD; exceptions double-inverted → USD/CCY
    df = 1.0 / df

    df = df[df.index >= CHART_START]
    print(f"  Date range: {df.index[0].date()} → {df.index[-1].date()}")
    return df


# ── Model helpers ───────────────────────────────────────────────────────────────

def get_top_peers(df, ccy, n=N_PEERS):
    """Return the n currencies most correlated with ccy (by univariate R²)."""
    df_full = df.dropna(subset=[ccy])
    r2 = {}
    for c in df.columns:
        if c == ccy:
            continue
        tmp = df_full[[ccy, c]].dropna()
        if len(tmp) < 50:
            continue
        model = sm.OLS(tmp[ccy], sm.add_constant(tmp[c])).fit()
        r2[c] = model.rsquared
    return [k for k, _ in sorted(r2.items(), key=lambda x: x[1], reverse=True)[:n]]


def run_beta_model(df, ccy, peers, train_start, train_end):
    """
    Fit OLS on train window, project out-of-sample.
    Returns dict with arrays ready to embed in HTML.
    """
    cols = peers + [ccy]
    sub  = df[cols].dropna()

    if len(sub) < 50:
        return None

    # Save last values for rescaling
    last_vals = sub.iloc[-1].copy()

    # Normalize to 100 at last value (removes scale bias)
    sub_norm = sub / last_vals * 100

    # Training slice
    train = sub_norm.loc[train_start:train_end]
    if len(train) < 60:
        return None

    X_train = sm.add_constant(train[peers])
    y_train = train[ccy]
    model   = sm.OLS(y_train, X_train).fit()

    # Project full history
    X_full      = sm.add_constant(sub_norm[peers], has_constant="add")
    predicted_n = model.predict(X_full)
    residual    = ((sub_norm[ccy] - predicted_n) / sub_norm[ccy] * 100).round(3)

    p10 = float(residual.quantile(0.10))
    p90 = float(residual.quantile(0.90))

    # Rescale actual + predicted back to original FX level
    actual_orig    = (sub_norm[ccy]  * last_vals[ccy]  / 100).round(4)
    predicted_orig = (predicted_n    * last_vals[ccy]  / 100).round(4)

    # Align to shared CHART_START date range; fill gaps with None
    idx = sub.index
    dates = idx.strftime("%Y-%m-%d").tolist()

    return {
        "dates":     dates,
        "actual":    actual_orig.tolist(),
        "predicted": predicted_orig.tolist(),
        "residual":  residual.tolist(),
        "p10":       round(p10, 2),
        "p90":       round(p90, 2),
        "r2":        round(model.rsquared, 3),
        "peers":     peers,
        "last_dev":  round(float(residual.iloc[-1]), 2),
        "last_date": idx[-1].strftime("%Y-%m-%d"),
    }


def compute_all_models(df):
    print(f"Computing {len(CCY_LIST)} × {len(TRAIN_WINDOWS)} models…")
    result = {}

    for ccy in CCY_LIST:
        if ccy not in df.columns:
            continue
        peers = get_top_peers(df, ccy)
        print(f"  {ccy:4s}  peers: {', '.join(peers)}")
        result[ccy] = {}
        for label, t0, t1 in TRAIN_WINDOWS:
            m = run_beta_model(df, ccy, peers, t0, t1)
            if m:
                result[ccy][label] = m
            else:
                print(f"    Warning: insufficient data for {ccy} / {label}")

    return result


# ── HTML generation ─────────────────────────────────────────────────────────────

def generate_html(data, today_str, last_date):
    data_json = json.dumps(data, separators=(",", ":"))

    # KPI counts using default window "2016-2019"
    default_win = "2016-2019"
    devs = [v[default_win]["last_dev"] for v in data.values() if default_win in v]
    p90s = [v[default_win]["p90"] for v in data.values() if default_win in v]
    p10s = [v[default_win]["p10"] for v in data.values() if default_win in v]
    n_rich  = sum(d > p for d, p in zip(devs, p90s))
    n_cheap = sum(d < p for d, p in zip(devs, p10s))
    n_total = len(devs)
    median_dev = round(float(np.median(devs)), 1)
    med_sign   = "+" if median_dev >= 0 else ""

    ccy_list_js = json.dumps(CCY_LIST)
    ccy_names_js = json.dumps(CCY_NAMES)
    region_js    = json.dumps(REGION)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FX Beta Valuations — boquin.xyz</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f7fa;color:#1a1a1a;font-size:14px}}

.hdr{{background:#1a3a2f;color:#fff;padding:20px 32px}}
.hdr h1{{font-size:1.4rem;font-weight:700;letter-spacing:-.4px}}
.hdr .sub{{font-size:.82rem;opacity:.72;margin-top:5px}}
.hdr .meta{{font-size:.75rem;opacity:.55;margin-top:3px}}

.kpi-bar{{background:#fff;border-bottom:1px solid #e4e8ec;padding:12px 32px;display:flex;gap:32px;flex-wrap:wrap}}
.kpi{{display:flex;flex-direction:column;gap:2px}}
.kpi-lbl{{font-size:.68rem;text-transform:uppercase;letter-spacing:.5px;color:#999;font-weight:600}}
.kpi-val{{font-size:1.2rem;font-weight:700}}
.kpi-val.red{{color:#c62828}}.kpi-val.blue{{color:#1565c0}}.kpi-val.green{{color:#2e7d32}}.kpi-val.neu{{color:#555}}

.ctrl-bar{{background:#fff;border-bottom:1px solid #e4e8ec;padding:10px 32px;display:flex;gap:20px;align-items:center;flex-wrap:wrap}}
.ctrl-lbl{{font-size:.75rem;color:#666;font-weight:600;white-space:nowrap}}
.btn-grp{{display:flex;gap:3px}}
.btn{{padding:4px 11px;border:1px solid #cdd4db;border-radius:5px;background:#fff;cursor:pointer;font-size:.78rem;color:#555;transition:background .12s,color .12s;white-space:nowrap}}
.btn.active{{background:#1a3a2f;color:#fff;border-color:#1a3a2f}}
.btn:hover:not(.active){{background:#f0f5f0}}
.ctrl-note{{font-size:.72rem;color:#aaa;margin-left:auto}}

.tabs{{background:#fff;border-bottom:1px solid #e4e8ec;padding:0 32px;display:flex}}
.tab{{padding:11px 18px;font-size:.85rem;cursor:pointer;border-bottom:3px solid transparent;color:#666;white-space:nowrap;transition:all .12s}}
.tab.active{{color:#1a3a2f;border-bottom-color:#1a3a2f;font-weight:600}}
.tab:hover:not(.active){{background:#f8faf8;color:#333}}

.content{{padding:20px 32px;max-width:1440px;margin:0 auto}}
.panel{{display:none}}.panel.active{{display:block}}
.card{{background:#fff;border:1px solid #e4e8ec;border-radius:10px;padding:16px 20px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.card-title{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:4px}}
.card-note{{font-size:.75rem;color:#aaa;margin-bottom:12px}}

.sc-hdr{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;flex-wrap:wrap;gap:12px}}
.sc-pick{{padding:6px 10px;border:1px solid #cdd4db;border-radius:6px;font-size:.85rem;min-width:220px}}
.sc-stats{{display:flex;gap:20px;flex-wrap:wrap;margin-top:2px}}
.sc-stat{{display:flex;flex-direction:column}}
.sc-stat-lbl{{font-size:.68rem;text-transform:uppercase;letter-spacing:.5px;color:#999;font-weight:600}}
.sc-stat-val{{font-size:1rem;font-weight:700;margin-top:2px}}
.sc-stat-val.pos{{color:#2e7d32}}.sc-stat-val.neg{{color:#c62828}}.sc-stat-val.neu{{color:#555}}

.reg-badge{{display:inline-block;padding:2px 7px;border-radius:10px;font-size:.68rem;font-weight:700}}
.reg-badge.em{{background:#fff3e0;color:#e65100}}
.reg-badge.dm{{background:#e8f0ec;color:#1a3a2f}}

.quoting-note{{font-size:.75rem;color:#888;background:#fafbfc;border:1px solid #e8eaec;border-radius:6px;padding:8px 12px;margin-bottom:14px;line-height:1.5}}

@media(max-width:640px){{
  .hdr,.kpi-bar,.ctrl-bar,.content,.tabs{{padding-left:14px;padding-right:14px}}
}}
</style>
</head>
<body>

<div class="hdr">
  <h1>FX Beta Valuations</h1>
  <div class="sub">OLS peer-beta fair-value model for {n_total} currencies — spot vs. model-implied level</div>
  <div class="meta">Data: Yahoo Finance · Top-{N_PEERS} peer regressors by R² · Last observation: {last_date} · Generated: {today_str}</div>
</div>

<div class="kpi-bar" id="kpi-bar">
  <div class="kpi"><span class="kpi-lbl">Rich vs model</span><span class="kpi-val red" id="kpi-rich">{n_rich}</span></div>
  <div class="kpi"><span class="kpi-lbl">Cheap vs model</span><span class="kpi-val blue" id="kpi-cheap">{n_cheap}</span></div>
  <div class="kpi"><span class="kpi-lbl">Near fair value</span><span class="kpi-val neu" id="kpi-fair">{n_total - n_rich - n_cheap}</span></div>
  <div class="kpi"><span class="kpi-lbl">Median deviation</span><span class="kpi-val {'red' if median_dev > 0 else 'green'}" id="kpi-median">{med_sign}{median_dev}%</span></div>
</div>

<div class="ctrl-bar">
  <span class="ctrl-lbl">Training window:</span>
  <div class="btn-grp">
    <button class="btn" onclick="setWindow('2014-2017')">2014–17</button>
    <button class="btn active" onclick="setWindow('2016-2019')">2016–19</button>
    <button class="btn" onclick="setWindow('2018-2021')">2018–21</button>
  </div>
  <span class="ctrl-note">Model fit on selected pre-crisis window · projected out-of-sample · top-{N_PEERS} peer betas by R²</span>
</div>

<div class="tabs">
  <div class="tab active" onclick="setTab('rankings')">Rankings</div>
  <div class="tab" onclick="setTab('single')">Single Currency</div>
</div>

<div class="content">
  <div class="quoting-note">
    <strong>Convention:</strong>
    EM currencies (BRL, MXN, etc.) quoted as <em>CCY per USD</em> — positive deviation means the CCY is weaker than model implies.
    EUR, GBP, AUD, NZD quoted as <em>USD per CCY</em> — positive deviation means the CCY is stronger than model implies.
    Deviation = (actual − model) / actual × 100.
  </div>

  <div class="panel active" id="panel-rankings">
    <div class="card">
      <div class="card-title">Current Deviation vs Fair Value — All Currencies</div>
      <div class="card-note">Red = rich (above 90th percentile band) · Blue = cheap (below 10th percentile) · Grey = within range · Click a bar to open in Single Currency</div>
      <div id="chart-rankings"></div>
    </div>
  </div>

  <div class="panel" id="panel-single">
    <div class="card">
      <div class="sc-hdr">
        <div>
          <select class="sc-pick" id="ccy-picker" onchange="setCCY(this.value)"></select>
          <div class="sc-stats" id="sc-stats"></div>
        </div>
      </div>
      <div id="chart-single"></div>
    </div>
  </div>
</div>

<script>
var DATA   = {data_json};
var CCYS   = {ccy_list_js};
var NAMES  = {ccy_names_js};
var REGION = {region_js};

var currentWindow = "2016-2019";
var currentCCY    = CCYS[0];

// ── Tab switching ──────────────────────────────────────────────────────────────
function setTab(tab) {{
  document.querySelectorAll(".tab").forEach(function(t, i) {{
    t.classList.toggle("active", (i === 0 && tab === "rankings") || (i === 1 && tab === "single"));
  }});
  document.getElementById("panel-rankings").classList.toggle("active", tab === "rankings");
  document.getElementById("panel-single").classList.toggle("active",   tab === "single");
  if (tab === "single") drawSingle();
}}

// ── Window switching ───────────────────────────────────────────────────────────
function setWindow(w) {{
  currentWindow = w;
  document.querySelectorAll(".btn-grp .btn").forEach(function(b) {{
    var label = b.textContent.trim();
    var map = {{"2014–17": "2014-2017", "2016–19": "2016-2019", "2018–21": "2018-2021"}};
    b.classList.toggle("active", map[label] === w);
  }});
  updateKPIs();
  drawRankings();
  if (document.getElementById("panel-single").classList.contains("active")) drawSingle();
}}

// ── KPI bar update ─────────────────────────────────────────────────────────────
function updateKPIs() {{
  var nRich = 0, nCheap = 0, devs = [];
  CCYS.forEach(function(c) {{
    if (!DATA[c] || !DATA[c][currentWindow]) return;
    var d = DATA[c][currentWindow];
    var dev = d.last_dev;
    devs.push(dev);
    if (dev > d.p90) nRich++;
    else if (dev < d.p10) nCheap++;
  }});
  var nFair = devs.length - nRich - nCheap;
  var med   = devs.sort(function(a,b){{return a-b;}})[Math.floor(devs.length/2)];
  document.getElementById("kpi-rich").textContent  = nRich;
  document.getElementById("kpi-cheap").textContent = nCheap;
  document.getElementById("kpi-fair").textContent  = nFair;
  var el = document.getElementById("kpi-median");
  el.textContent = (med >= 0 ? "+" : "") + med.toFixed(1) + "%";
  el.className = "kpi-val " + (med > 0.5 ? "red" : med < -0.5 ? "green" : "neu");
}}

// ── Rankings chart ─────────────────────────────────────────────────────────────
function drawRankings() {{
  var pairs = [];
  CCYS.forEach(function(c) {{
    if (!DATA[c] || !DATA[c][currentWindow]) return;
    var d = DATA[c][currentWindow];
    pairs.push({{ccy: c, dev: d.last_dev, p10: d.p10, p90: d.p90}});
  }});
  pairs.sort(function(a, b) {{ return b.dev - a.dev; }});

  var x     = pairs.map(function(p) {{ return p.dev; }});
  var y     = pairs.map(function(p) {{ return p.ccy + " — " + (NAMES[p.ccy] || p.ccy); }});
  var colors = pairs.map(function(p) {{
    return p.dev > p.p90 ? "#c62828" : p.dev < p.p10 ? "#1565c0" : "#78909c";
  }});
  var htext = pairs.map(function(p) {{
    return "<b>" + p.ccy + "</b><br>Deviation: " + p.dev.toFixed(1) +
           "%<br>10th: " + p.p10.toFixed(1) + "% · 90th: " + p.p90.toFixed(1) + "%";
  }});

  var trace = {{
    type: "bar", orientation: "h",
    x: x, y: y,
    marker: {{ color: colors }},
    hovertemplate: "%{{customdata}}<extra></extra>",
    customdata: htext
  }};

  var layout = {{
    height: Math.max(480, pairs.length * 24 + 60),
    margin: {{ l: 10, r: 30, t: 20, b: 40 }},
    xaxis: {{ title: "% deviation (actual vs model)", gridcolor: "#f0f0f0", zeroline: true, zerolinecolor: "#aaa" }},
    yaxis: {{ tickfont: {{ size: 11 }}, automargin: true }},
    plot_bgcolor: "#fff", paper_bgcolor: "#fff",
    hovermode: "closest"
  }};

  Plotly.react("chart-rankings", [trace], layout, {{responsive: true, displayModeBar: false}});

  // Click handler
  var el = document.getElementById("chart-rankings");
  el.on("plotly_click", function(d) {{
    var label = d.points[0].y;
    var c = label.split(" — ")[0];
    currentCCY = c;
    document.getElementById("ccy-picker").value = c;
    setTab("single");
  }});
}}

// ── Single currency chart ─────────────────────────────────────────────────────
function buildPicker() {{
  var sel = document.getElementById("ccy-picker");
  sel.innerHTML = "";
  CCYS.forEach(function(c) {{
    if (!DATA[c]) return;
    var opt = document.createElement("option");
    opt.value = c;
    var reg = REGION[c] || "EM";
    opt.text = c + " — " + (NAMES[c] || c) + " [" + reg + "]";
    sel.appendChild(opt);
  }});
  sel.value = currentCCY;
}}

function setCCY(c) {{
  currentCCY = c;
  drawSingle();
}}

function drawSingle() {{
  var c = currentCCY;
  if (!DATA[c] || !DATA[c][currentWindow]) return;
  var d = DATA[c][currentWindow];

  // Stats row
  var reg = REGION[c] || "EM";
  var devCls = d.last_dev > d.p90 ? "neg" : d.last_dev < d.p10 ? "pos" : "neu";
  document.getElementById("sc-stats").innerHTML =
    '<span class="reg-badge ' + reg.toLowerCase() + '">' + reg + '</span>&nbsp;&nbsp;' +
    '<div class="sc-stat"><span class="sc-stat-lbl">Current deviation</span>' +
    '<span class="sc-stat-val ' + devCls + '">' + (d.last_dev >= 0 ? "+" : "") + d.last_dev.toFixed(1) + '%</span></div>' +
    '<div class="sc-stat"><span class="sc-stat-lbl">R²</span>' +
    '<span class="sc-stat-val neu">' + d.r2.toFixed(3) + '</span></div>' +
    '<div class="sc-stat"><span class="sc-stat-lbl">Training window</span>' +
    '<span class="sc-stat-val neu">' + currentWindow + '</span></div>' +
    '<div class="sc-stat"><span class="sc-stat-lbl">Top peers</span>' +
    '<span class="sc-stat-val neu" style="font-size:.82rem">' + d.peers.join(", ") + '</span></div>';

  // Left: actual vs model
  var t1 = {{
    type: "scatter", mode: "lines",
    x: d.dates, y: d.actual,
    name: c + " Actual",
    line: {{ color: "#1565c0", width: 2 }}
  }};
  var t2 = {{
    type: "scatter", mode: "lines",
    x: d.dates, y: d.predicted,
    name: "Model (" + currentWindow + ")",
    line: {{ color: "#c62828", width: 2, dash: "dash" }}
  }};

  // Right: residual + bands
  var nDates = d.dates.length;
  var t3 = {{
    type: "scatter", mode: "lines",
    x: d.dates, y: d.residual,
    name: "Deviation (%)",
    line: {{ color: "#2e7d32", width: 1.5 }},
    xaxis: "x2", yaxis: "y2"
  }};
  var t4 = {{
    type: "scatter", mode: "lines",
    x: [d.dates[0], d.dates[nDates-1]], y: [d.p90, d.p90],
    name: "90th pct",
    line: {{ color: "#1565c0", width: 1.5, dash: "dot" }},
    xaxis: "x2", yaxis: "y2"
  }};
  var t5 = {{
    type: "scatter", mode: "lines",
    x: [d.dates[0], d.dates[nDates-1]], y: [d.p10, d.p10],
    name: "10th pct",
    line: {{ color: "#1565c0", width: 1.5, dash: "dot" }},
    xaxis: "x2", yaxis: "y2"
  }};

  var layout = {{
    grid: {{ rows: 1, columns: 2, pattern: "independent" }},
    height: 460,
    margin: {{ l: 10, r: 60, t: 40, b: 50 }},
    plot_bgcolor: "#fff", paper_bgcolor: "#fff",
    title: {{
      text: c + " — " + (NAMES[c] || c) + " vs. Beta Model (" + currentWindow + ") · R² = " + d.r2.toFixed(3),
      font: {{ size: 13 }}, x: 0
    }},
    xaxis:  {{ gridcolor: "#f0f0f0", domain: [0, 0.48] }},
    yaxis:  {{ gridcolor: "#f0f0f0", title: c + " (original scale)", side: "left" }},
    xaxis2: {{ gridcolor: "#f0f0f0", domain: [0.52, 1.0] }},
    yaxis2: {{ gridcolor: "#f0f0f0", title: "Deviation (%)", side: "right",
               zeroline: true, zerolinecolor: "#aaa", zerolinewidth: 1 }},
    legend: {{ orientation: "h", y: -0.12 }},
    annotations: [
      {{ x: d.dates[nDates-1], y: d.p90, xref: "x2", yref: "y2",
         text: "90th: " + d.p90.toFixed(1) + "%", showarrow: false,
         font: {{ color: "#1565c0", size: 10 }}, xanchor: "right", yanchor: "bottom" }},
      {{ x: d.dates[nDates-1], y: d.p10, xref: "x2", yref: "y2",
         text: "10th: " + d.p10.toFixed(1) + "%", showarrow: false,
         font: {{ color: "#1565c0", size: 10 }}, xanchor: "right", yanchor: "top" }}
    ]
  }};

  Plotly.react("chart-single", [t1, t2, t3, t4, t5], layout, {{responsive: true, displayModeBar: true}});
}}

// ── Init ───────────────────────────────────────────────────────────────────────
buildPicker();
drawRankings();
</script>

</body>
</html>"""
    return html


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df   = fetch_fx_data()
    data = compute_all_models(df)

    last_dates = [v[list(v.keys())[0]]["last_date"] for v in data.values() if v]
    last_date  = max(last_dates) if last_dates else today_str

    print("Building HTML…")
    html = generate_html(data, today_str, last_date)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Written to: {OUTPUT_FILE}")

    # Quick summary
    win = "2016-2019"
    rich  = [(c, v[win]["last_dev"]) for c, v in data.items() if win in v and v[win]["last_dev"] > v[win]["p90"]]
    cheap = [(c, v[win]["last_dev"]) for c, v in data.items() if win in v and v[win]["last_dev"] < v[win]["p10"]]
    if rich:
        print(f"Rich  ({win}): " + ", ".join(f"{c} ({d:+.1f}%)" for c, d in sorted(rich, key=lambda x: -x[1])))
    if cheap:
        print(f"Cheap ({win}): " + ", ".join(f"{c} ({d:+.1f}%)" for c, d in sorted(cheap, key=lambda x: x[1])))


if __name__ == "__main__":
    main()
