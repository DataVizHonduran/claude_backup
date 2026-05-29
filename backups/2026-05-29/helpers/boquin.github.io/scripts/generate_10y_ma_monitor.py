"""
10Y Treasury Yield / Real Rate — MA Monitor
=============================================
Two-panel interactive dashboard with dropdown to switch between:
  • Nominal 10Y (DGS10) or Real 10Y TIPS (DFII10)
  × 200-Day / 200-Week / 200-Month MA

Each view shows:
  Panel 1 — yield vs selected MA
  Panel 2 — Residual with ±1σ and ±2σ mean-reversion bands

Output: reports/10y-ma-monitor/index.html
Requires: FRED_API_KEY environment variable
"""

import os
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date
from dateutil.relativedelta import relativedelta
from fredapi import Fred

OUTPUT_PATH = "reports/10y-ma-monitor/index.html"
YEARS       = 40

FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set.")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
fred = Fred(api_key=FRED_API_KEY)

# ── Fetch raw daily series ───────────────────────────────────────────────────
start_nominal = date.today() - relativedelta(years=YEARS)
raw_n = fred.get_series("DGS10",  observation_start=start_nominal).dropna()
raw_r = fred.get_series("DFII10").dropna()   # full history from Jan 2003

raw_n.index = pd.to_datetime(raw_n.index)
raw_r.index = pd.to_datetime(raw_r.index)
raw_n.name = "10Y Nominal Yield"
raw_r.name = "10Y Real Rate (TIPS)"

latest_n      = raw_n.iloc[-1]
latest_r      = raw_r.iloc[-1]
latest_n_date = raw_n.index[-1].strftime("%Y-%m-%d")
latest_r_date = raw_r.index[-1].strftime("%Y-%m-%d")

# ── Compute MAs + residuals for one series ───────────────────────────────────
def compute_ma(series, freq, window):
    """Resample → rolling MA → reindex back to daily (ffill)."""
    resampled = series.resample(freq).last()
    ma = resampled.rolling(window).mean()
    return ma.reindex(series.index, method="ffill")

def sigma_stats(res, ma):
    s    = res.std()
    last = res.iloc[-1]
    return dict(sigma=s, latest_residual=last, zscore=last / s,
                latest_ma=ma.dropna().iloc[-1])

def make_series_configs(raw, series_id, series_label):
    ma_d = raw.rolling(200).mean()
    ma_w = compute_ma(raw, "W",  200)
    res_d = (raw - ma_d).dropna()
    res_w = (raw - ma_w).dropna()
    return [
        dict(series_id=series_id, series_label=series_label,
             label=f"{series_label} — 200-Day MA",
             res=res_d, ma=ma_d, stats=sigma_stats(res_d, ma_d),
             ma_label="200d MA", raw=raw),
        dict(series_id=series_id, series_label=series_label,
             label=f"{series_label} — 200-Week MA",
             res=res_w, ma=ma_w, stats=sigma_stats(res_w, ma_w),
             ma_label="200w MA", raw=raw),
    ]

configs_n = make_series_configs(raw_n, "DGS10",  "Nominal 10Y")
configs_r = make_series_configs(raw_r, "DFII10", "Real 10Y (TIPS)")

# Flat list: indices 0-2 = nominal, 3-5 = real
# Within each group: 0=200d, 1=200w, 2=200m
configs = configs_n + configs_r   # 6 total

MA_COLORS    = ["firebrick", "#e07b00", "#6a0dad"]
YIELD_COLORS = ["#2c7bb6", "#2ca02c"]   # nominal=blue, real=green
FILL_COLORS  = ["rgba(44,123,182,0.15)", "rgba(44,160,44,0.15)"]
BAND_COLS    = ("#d62728", "#1f77b4")   # +/- bands (same for both series)

# ── Trace index layout ───────────────────────────────────────────────────────
# s = series index (0=nominal, 1=real)
# m = MA index    (0=200d, 1=200w)
#
# 0-1    : Yield lines         (one per series)
# 2-5    : MA lines            (s*2 + m + 2)
# 6-9    : Residual fills      (s*2 + m + 6)
# 10-25  : σ band traces       (s*8 + m*4 + k + 10)  — 4 per config
# 26-29  : Latest dot          (s*2 + m + 26)
# Total  : 30

TOTAL_TRACES = 30

def trace_yield(s):      return s
def trace_ma(s, m):      return 2 + s*2 + m
def trace_res(s, m):     return 6 + s*2 + m
def trace_band(s, m, k): return 10 + s*8 + m*4 + k
def trace_dot(s, m):     return 26 + s*2 + m

def vis(s, m):
    v = [False] * TOTAL_TRACES
    v[trace_yield(s)] = True
    v[trace_ma(s, m)] = True
    v[trace_res(s, m)] = True
    for k in range(4):
        v[trace_band(s, m, k)] = True
    v[trace_dot(s, m)] = True
    return v

def make_title(cfg, latest_yield, latest_date):
    st = cfg["stats"]
    return (
        f"{cfg['label']} Monitor<br>"
        f"<sub>Latest: {latest_yield:.2f}%  |  "
        f"{cfg['ma_label']}: {st['latest_ma']:.2f}%  |  "
        f"Residual: {st['latest_residual']:+.3f} pp  "
        f"(z = {st['zscore']:+.2f}σ)  |  Updated {latest_date}</sub>"
    )

# ── Build figure ─────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.55, 0.45],
    vertical_spacing=0.07,
    subplot_titles=["Yield vs Moving Average", "Residual (Yield − MA)"]
)

# Traces 0-1 — yield lines
for s, (raw, name, color) in enumerate([(raw_n, "10Y Nominal Yield", YIELD_COLORS[0]),
                                         (raw_r, "10Y Real Rate (TIPS)", YIELD_COLORS[1])]):
    fig.add_trace(go.Scatter(
        x=raw.index, y=raw.values,
        mode="lines", line=dict(color=color, width=1.3),
        name=name, visible=(s == 0),
        hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra>" + name + "</extra>"
    ), row=1, col=1)

# Traces 2-5 — MA lines
for s in range(2):
    for m in range(2):
        cfg = configs[s*2 + m]
        fig.add_trace(go.Scatter(
            x=cfg["ma"].index, y=cfg["ma"].values,
            mode="lines", line=dict(color=MA_COLORS[m], width=2, dash="dot"),
            name=cfg["ma_label"], visible=(s == 0 and m == 0),
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra>" + cfg["label"] + "</extra>"
        ), row=1, col=1)

# Traces 6-9 — Residual fills
for s in range(2):
    for m in range(2):
        cfg = configs[s*2 + m]
        fig.add_trace(go.Scatter(
            x=cfg["res"].index, y=cfg["res"].values,
            mode="lines", line=dict(color=YIELD_COLORS[s], width=0.9),
            fill="tozeroy", fillcolor=FILL_COLORS[s],
            name="Residual", visible=(s == 0 and m == 0),
            showlegend=False,
            hovertemplate="%{x|%Y-%m-%d}: %{y:+.3f} pp<extra>Residual</extra>"
        ), row=2, col=1)

# Traces 10-25 — sigma bands (4 per config: +1σ,-1σ,+2σ,-2σ)
for s in range(2):
    for m in range(2):
        cfg = configs[s*2 + m]
        st  = cfg["stats"]
        sig = st["sigma"]
        rc, bc = BAND_COLS
        x0, xend = cfg["res"].index[0], cfg["res"].index[-1]
        for k, (val, color, dash, lbl) in enumerate([
            ( sig,    rc, "dash", "+1σ"),
            (-sig,    bc, "dash", "−1σ"),
            ( 2*sig,  rc, "dot",  "+2σ"),
            (-2*sig,  bc, "dot",  "−2σ"),
        ]):
            fig.add_trace(go.Scatter(
                x=[x0, xend], y=[val, val],
                mode="lines+text",
                text=["", lbl],
                textposition="middle right",
                textfont=dict(color=color, size=10),
                line=dict(color=color, width=1 if "1σ" in lbl else 1.4, dash=dash),
                showlegend=False, visible=(s == 0 and m == 0),
                hoverinfo="skip"
            ), row=2, col=1)

# Traces 26-29 — latest dot
for s in range(2):
    latest_yield = latest_n if s == 0 else latest_r
    latest_date  = latest_n_date if s == 0 else latest_r_date
    for m in range(2):
        cfg = configs[s*2 + m]
        st  = cfg["stats"]
        dot_color = "#d62728" if st["latest_residual"] >= 0 else "#1f77b4"
        fig.add_trace(go.Scatter(
            x=[cfg["res"].index[-1]], y=[st["latest_residual"]],
            mode="markers",
            marker=dict(color=dot_color, size=8,
                        line=dict(color="white", width=1.5)),
            name=f"Latest: {st['latest_residual']:+.3f} pp",
            visible=(s == 0 and m == 0),
            hovertemplate=(
                f"{latest_date}: {st['latest_residual']:+.3f} pp "
                f"(z={st['zscore']:+.2f}σ)<extra></extra>"
            )
        ), row=2, col=1)

# ── Zero line (always visible) ───────────────────────────────────────────────
fig.add_hline(y=0, line_color="black", line_width=1.5, row=2, col=1)

# ── Dropdown (6 options: 2 series × 3 MA types) ──────────────────────────────
buttons = []
SERIES_LATEST = [(latest_n, latest_n_date), (latest_r, latest_r_date)]
YAXIS_LABELS  = ["Yield (%)", "Real Rate (%)"]

for s in range(2):
    latest_yield, latest_date = SERIES_LATEST[s]
    for m in range(2):
        cfg = configs[s*2 + m]
        buttons.append(dict(
            label=cfg["label"],
            method="update",
            args=[
                {"visible": vis(s, m)},
                {
                    "title.text":       make_title(cfg, latest_yield, latest_date),
                    "yaxis.title.text": YAXIS_LABELS[s],
                }
            ]
        ))

fig.update_layout(
    updatemenus=[dict(
        buttons=buttons,
        direction="down",
        showactive=True,
        x=0.01, y=1.13,
        xanchor="left", yanchor="top",
        bgcolor="white",
        bordercolor="#ccc",
        font=dict(size=12)
    )],
    title=dict(text=make_title(configs[0], latest_n, latest_n_date),
               font=dict(size=17)),
    plot_bgcolor="white",
    paper_bgcolor="white",
    hovermode="x unified",
    height=720,
    margin=dict(l=60, r=80, t=110, b=50),
    legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#ccc", borderwidth=1),
    font=dict(family="Arial, sans-serif", size=12)
)

fig.update_xaxes(showgrid=True, gridcolor="#ebebeb", tickformat="%Y")
fig.update_yaxes(showgrid=True, gridcolor="#ebebeb")
fig.update_yaxes(title_text="Yield (%)",     row=1, col=1)
fig.update_yaxes(title_text="Residual (pp)", zeroline=False, row=2, col=1)

# ── Stats JSON for JS stats bar ───────────────────────────────────────────────
stats_json = json.dumps({
    cfg["label"]: {
        "ma":       f"{cfg['stats']['latest_ma']:.2f}%",
        "residual": f"{cfg['stats']['latest_residual']:+.3f} pp",
        "zscore":   f"{cfg['stats']['zscore']:+.2f}σ",
        "sigma":    f"{cfg['stats']['sigma']:.3f} pp",
        "pos":      bool(cfg['stats']['latest_residual'] >= 0),
        "yield":    f"{(latest_n if cfg['series_id']=='DGS10' else latest_r):.2f}%",
    }
    for cfg in configs
})

# Ordered label list matching dropdown button order
all_labels_json = json.dumps([cfg["label"] for cfg in configs])

sd = configs[0]["stats"]  # default: nominal 200d

chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="ma-chart")

# ── HTML wrapper ──────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>10Y Treasury MA Monitor — boquin.xyz</title>
  <style>
    body  {{ margin:0; background:#f9f9f9; font-family:Arial,sans-serif; }}
    .header {{
      background:#1a1a2e; color:#fff; padding:18px 28px 14px;
      display:flex; align-items:center; justify-content:space-between;
    }}
    .header h1 {{ margin:0; font-size:1.15rem; font-weight:600; }}
    .header a  {{ color:#7eb8f7; font-size:0.85rem; text-decoration:none; }}
    .header a:hover {{ text-decoration:underline; }}
    .stats {{
      display:flex; gap:28px; flex-wrap:wrap;
      background:#fff; border-bottom:1px solid #e0e0e0;
      padding:12px 28px; font-size:0.88rem; color:#444;
      align-items:flex-end;
    }}
    .stat {{ display:flex; flex-direction:column; }}
    .stat-label {{ font-size:0.72rem; color:#888; text-transform:uppercase;
                   letter-spacing:.05em; margin-bottom:2px; }}
    .stat-value {{ font-size:1.05rem; font-weight:600; color:#1a1a2e; }}
    .pos {{ color:#d62728 !important; }}
    .neg {{ color:#1f77b4 !important; }}
    .chart-wrap {{ padding:12px 16px 20px; }}
    .footer {{ text-align:center; padding:12px; font-size:0.78rem; color:#aaa; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>📈 10Y Treasury — MA Monitor</h1>
    <a href="/">← boquin.xyz</a>
  </div>

  <div class="stats">
    <div class="stat">
      <span class="stat-label" id="stat-series-label">10Y Yield</span>
      <span class="stat-value" id="stat-yield">{latest_n:.2f}%</span>
    </div>
    <div class="stat">
      <span class="stat-label">Selected MA</span>
      <span class="stat-value" id="stat-ma">{sd['latest_ma']:.2f}%</span>
    </div>
    <div class="stat">
      <span class="stat-label">Residual</span>
      <span class="stat-value {'pos' if sd['latest_residual'] >= 0 else 'neg'}" id="stat-res">{sd['latest_residual']:+.3f} pp</span>
    </div>
    <div class="stat">
      <span class="stat-label">Z-Score</span>
      <span class="stat-value {'pos' if sd['zscore'] >= 0 else 'neg'}" id="stat-z">{sd['zscore']:+.2f}σ</span>
    </div>
    <div class="stat">
      <span class="stat-label">σ (history)</span>
      <span class="stat-value" id="stat-sigma">{sd['sigma']:.3f} pp</span>
    </div>
    <div class="stat">
      <span class="stat-label">As of</span>
      <span class="stat-value" id="stat-date">{latest_n_date}</span>
    </div>
  </div>

  <div class="chart-wrap">
    {chart_html}
  </div>

  <div class="footer">
    Data: FRED (DGS10 · DFII10) · Updated daily on business days ·
    <a href="https://github.com/DataVizHonduran/boquin.github.io/tree/main/scripts/generate_10y_ma_monitor.py">Source code</a>
  </div>

  <script>
    const STATS      = {stats_json};
    const ALL_LABELS = {all_labels_json};
    // latest dates per series
    const DATES = {{ "DGS10": "{latest_n_date}", "DFII10": "{latest_r_date}" }};
    const SERIES_LABELS = {{ "DGS10": "10Y Yield", "DFII10": "10Y Real Rate" }};

    function seriesIdFromLabel(label) {{
      return label.includes("Real") ? "DFII10" : "DGS10";
    }}

    function updateStatsBar(label) {{
      const s = STATS[label];
      if (!s) return;
      const sid = seriesIdFromLabel(label);
      document.getElementById('stat-series-label').textContent = SERIES_LABELS[sid];
      document.getElementById('stat-yield').textContent  = s.yield;
      document.getElementById('stat-ma').textContent     = s.ma;
      document.getElementById('stat-res').textContent    = s.residual;
      document.getElementById('stat-z').textContent      = s.zscore;
      document.getElementById('stat-sigma').textContent  = s.sigma;
      document.getElementById('stat-date').textContent   = DATES[sid];
      ['stat-res','stat-z'].forEach(id => {{
        const el = document.getElementById(id);
        el.className = 'stat-value ' + (s.pos ? 'pos' : 'neg');
      }});
    }}

    // Detect Plotly dropdown selection via plotly_restyle event
    const div = document.getElementById('ma-chart');
    div.on('plotly_restyle', function() {{
      const menu = div._fullLayout.updatemenus[0];
      if (menu && typeof menu.active === 'number') {{
        updateStatsBar(ALL_LABELS[menu.active]);
      }}
    }});
  </script>
</body>
</html>"""

with open(OUTPUT_PATH, "w") as f:
    f.write(html)

print(f"✅  Saved: {OUTPUT_PATH}")
print(f"\nNominal 10Y (DGS10) — as of {latest_n_date}:")
for cfg in configs_n:
    st = cfg["stats"]
    print(f"   {cfg['label']:30s}  MA={st['latest_ma']:.2f}%  "
          f"res={st['latest_residual']:+.3f} pp  z={st['zscore']:+.2f}σ")
print(f"\nReal 10Y TIPS (DFII10) — as of {latest_r_date}:")
for cfg in configs_r:
    st = cfg["stats"]
    print(f"   {cfg['label']:30s}  MA={st['latest_ma']:.2f}%  "
          f"res={st['latest_residual']:+.3f} pp  z={st['zscore']:+.2f}σ")
