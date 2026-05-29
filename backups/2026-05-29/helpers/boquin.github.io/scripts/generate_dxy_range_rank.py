#!/usr/bin/env python3
"""
DXY Range Rank — rolling percentile of DXY within N-year high/low range.
Formula: (close - rolling_min) / (rolling_max - rolling_min) * 100
Supports 3yr / 4yr / 5yr lookback toggle via Plotly updatemenus.
"""

import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Config ─────────────────────────────────────────────────────────────────────
WINDOWS = {"3-Year": 252 * 3, "4-Year": 252 * 4, "5-Year": 252 * 5}
DEFAULT  = "4-Year"
OS_THRESHOLD = 10
CLUSTER_DAYS = 1260   # ~5 years between distinct OS cycle troughs
OUTPUT_DIR   = os.path.expanduser("~/boquin.github.io/reports/dxy-range-rank")
OUTPUT_FILE  = os.path.join(OUTPUT_DIR, "index.html")

# ── Data ───────────────────────────────────────────────────────────────────────
print("Fetching DXY data from Yahoo Finance…")
raw = yf.download("DX-Y.NYB", period="max", auto_adjust=True, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
close = raw["Close"].dropna()
print(f"  {close.index[0].date()} → {close.index[-1].date()}  ({len(close)} rows)")

current_price = close.iloc[-1]
last_date     = close.index[-1]

# ── Compute rank + troughs for each window ──────────────────────────────────────
def compute_rank(close, window):
    rmin = close.rolling(window, min_periods=int(window * 0.25)).min()
    rmax = close.rolling(window, min_periods=int(window * 0.25)).max()
    return ((close - rmin) / (rmax - rmin) * 100).clip(0, 100)

def detect_troughs(rank, threshold, cluster_days):
    os_days = rank.index[rank < threshold]
    troughs, cluster_start, c_idx, c_val = [], None, None, None
    for dt in os_days:
        if cluster_start is None:
            cluster_start, c_idx, c_val = dt, dt, rank[dt]
        elif (dt - cluster_start).days <= cluster_days:
            if rank[dt] < c_val:
                c_idx, c_val = dt, rank[dt]
        else:
            troughs.append(c_idx)
            cluster_start, c_idx, c_val = dt, dt, rank[dt]
    if c_idx is not None:
        troughs.append(c_idx)
    return troughs

computed = {}
for label, w in WINDOWS.items():
    r = compute_rank(close, w)
    t = detect_troughs(r, OS_THRESHOLD, CLUSTER_DAYS)
    computed[label] = {"rank": r, "troughs": t, "current": r.iloc[-1]}
    print(f"  {label}: rank={r.iloc[-1]:.2f}  troughs={len(t)}")

# ── Build figure ───────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    row_heights=[0.60, 0.40],
    shared_xaxes=True,
    vertical_spacing=0.06,
)

# Trace 0 — DXY price (always visible)
fig.add_trace(go.Scatter(
    x=close.index, y=close.values,
    mode="lines",
    line=dict(color="#111111", width=1.2),
    name="DXY",
    hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>",
), row=1, col=1)

# Per-window traces: rank oscillator + trough dots + vlines
trace_indices = {}   # label → list of trace indices that belong to this window

for label, data in computed.items():
    rank    = data["rank"]
    troughs = data["troughs"]
    visible = (label == DEFAULT)
    indices = []

    # Rank oscillator (row 2)
    fig.add_trace(go.Scatter(
        x=rank.index, y=rank.values,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(100,149,237,0.30)",
        line=dict(color="cornflowerblue", width=1.4),
        name=f"Range Rank ({label})",
        visible=visible,
        hovertemplate="%{x|%Y-%m-%d}<br>Rank: %{y:.1f}<extra></extra>",
    ), row=2, col=1)
    indices.append(len(fig.data) - 1)

    # Trough dots + date labels on price panel (row 1)
    for dt in troughs:
        px_val = close.loc[dt]
        fig.add_trace(go.Scatter(
            x=[dt], y=[px_val],
            mode="markers+text",
            marker=dict(color="red", size=10),
            text=[dt.strftime("%m/%d/%Y")],
            textposition="top right",
            textfont=dict(size=9, color="#333333"),
            showlegend=False,
            visible=visible,
            hovertemplate=f"{dt.strftime('%Y-%m-%d')}<br>DXY: {px_val:.2f}<extra></extra>",
        ), row=1, col=1)
        indices.append(len(fig.data) - 1)

    # Vlines on oscillator panel as scatter traces (row 2)
    for dt in troughs:
        fig.add_trace(go.Scatter(
            x=[dt, dt], y=[0, 100],
            mode="lines",
            line=dict(color="rgba(200,0,0,0.55)", width=1.2, dash="dash"),
            showlegend=False,
            visible=visible,
            hoverinfo="skip",
        ), row=2, col=1)
        indices.append(len(fig.data) - 1)

    trace_indices[label] = indices

n_total = len(fig.data)

# OB / OS reference lines (layout hlines — always visible, not toggleable)
for level in [90, 10]:
    fig.add_hline(y=level, line=dict(color="rgba(200,50,50,0.35)", width=1, dash="dot"), row=2, col=1)

# ── updatemenus buttons ────────────────────────────────────────────────────────
buttons = []
for label, data in computed.items():
    vis = [True] + [i in trace_indices[label] for i in range(1, n_total)]

    cur = data["current"]
    subtitle = (
        f"DXY · {label} Range Rank  "
        f"<b style='color:red'>{cur:.2f}</b>"
    )
    buttons.append(dict(
        label=label,
        method="update",
        args=[
            {"visible": vis},
            {"title.text": (
                "<b>The U.S. Dollar Index sits at a crucial inflection point</b><br>"
                f"<span style='font-size:13px;color:#555'>{subtitle}</span>"
            )},
        ],
    ))

fig.update_layout(
    updatemenus=[dict(
        type="buttons",
        direction="right",
        x=0.01, y=1.08,
        xanchor="left", yanchor="top",
        buttons=buttons,
        bgcolor="#f0f0f0",
        bordercolor="#cccccc",
        font=dict(size=12),
        showactive=True,
        active=list(WINDOWS.keys()).index(DEFAULT),
    )],
)

# ── Static annotations ─────────────────────────────────────────────────────────
default_rank = computed[DEFAULT]["current"]

fig.add_annotation(
    text=(
        f"<b>{DEFAULT} Range Rank</b>  "
        f"<span style='color:cornflowerblue'>{default_rank:.2f}</span>"
    ),
    xref="paper", yref="paper",
    x=0.01, y=0.01,
    xanchor="left", yanchor="bottom",
    showarrow=False,
    font=dict(size=12),
    bgcolor="rgba(255,255,255,0.75)",
    borderpad=4,
)

fig.add_annotation(
    text=f"<b>{current_price:.2f}</b>",
    xref="paper", yref="y",
    x=1.01, y=current_price,
    xanchor="left", yanchor="middle",
    showarrow=False,
    font=dict(size=11, color="red"),
)

# ── Layout ─────────────────────────────────────────────────────────────────────
fig.update_layout(
    title=dict(
        text=(
            "<b>The U.S. Dollar Index sits at a crucial inflection point</b><br>"
            f"<span style='font-size:13px;color:#555'>DXY · {DEFAULT} Range Rank  "
            f"<b style='color:red'>{default_rank:.2f}</b></span>"
        ),
        x=0.01, xanchor="left",
        font=dict(size=16),
    ),
    height=720,
    paper_bgcolor="#ffffff",
    plot_bgcolor="#f9f9f9",
    hovermode="x unified",
    showlegend=False,
    margin=dict(l=40, r=80, t=110, b=40),
    font=dict(family="Inter, sans-serif", size=11),
)

fig.update_yaxes(side="right", showgrid=True, gridcolor="#e5e5e5", row=1, col=1)
fig.update_yaxes(
    side="right", showgrid=True, gridcolor="#e5e5e5",
    range=[-2, 105], tickvals=[10, 30, 50, 70, 90],
    row=2, col=1,
)
fig.update_xaxes(showgrid=False, rangeslider_visible=False)

# ── Write HTML ─────────────────────────────────────────────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)

html_body = fig.to_html(
    include_plotlyjs="cdn",
    full_html=False,
    config={"displayModeBar": True, "scrollZoom": True},
)

updated = last_date.strftime("%B %d, %Y")
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DXY Range Rank | boquin.xyz</title>
<style>
  body {{ margin: 0; font-family: Inter, sans-serif; background: #fff; color: #111; }}
  .header {{ padding: 18px 24px 0; border-bottom: 1px solid #eee; }}
  .header a {{ text-decoration: none; color: #0066cc; font-size: 13px; }}
  .meta {{ padding: 6px 24px 12px; font-size: 12px; color: #888; }}
  .chart-wrap {{ padding: 0 16px 24px; }}
  .footnote {{ padding: 0 24px 24px; font-size: 11px; color: #aaa; }}
</style>
</head>
<body>
<div class="header"><a href="/">← boquin.xyz</a></div>
<div class="meta">Last updated: {updated} &nbsp;·&nbsp; Data: Yahoo Finance (DX-Y.NYB)</div>
<div class="chart-wrap">{html_body}</div>
<div class="footnote">
  Range Rank = (close − N-year low) / (N-year high − N-year low) × 100.
  OB ≥ 90 · OS ≤ 10. Red dashed verticals mark OS cycle troughs (5-year cluster window).
  Toggle 3yr / 4yr / 5yr lookback with the buttons above the chart.
</div>
</body>
</html>"""

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Written → {OUTPUT_FILE}")
