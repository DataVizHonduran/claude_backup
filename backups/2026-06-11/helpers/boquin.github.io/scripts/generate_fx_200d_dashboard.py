#!/usr/bin/env python3
"""
FX 200-Day Moving Average Extension Dashboard
Replicates the methodology from 200d extensions.ipynb:
  - 25 currencies via yfinance
  - % distance from 200d moving average
  - 25th/75th percentile bands per currency
  - Extremes table (currencies outside percentile bands)
  - Broad USD (DTWEXBGS) with 90th/10th percentile bands
  - Median composite gauge across all currencies

Run:
    FRED_API_KEY=your_key python3 scripts/generate_fx_200d_dashboard.py
    python3 scripts/generate_fx_200d_dashboard.py  # skips Broad USD chart if no key
"""

import os
import sys
import datetime
from datetime import date, timedelta
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

# ── Config ─────────────────────────────────────────────────────────────────────

YEARS_FX  = 20
YEARS_USD = 30
Z_THRESHOLD = 2  # same as notebook: delete_outliers(df_a, 2)

CCY_LIST = [
    "BRL", "MXN", "CLP", "ZAR", "TRY", "PLN", "HUF", "CZK",
    "CNY", "KRW", "SGD", "MYR", "IDR", "INR", "PHP", "THB",
    "EUR", "JPY", "GBP", "CAD", "AUD", "NZD", "SEK", "NOK", "COP",
]

# These are quoted as USD/CCY on Yahoo (EURUSD=x), so they get double-inverted
# and stay as USD/CCY in df. Positive 200d extension = CCY stronger than avg.
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
    "COP": "Colombian Peso",
}

REGION = {
    "EUR": "DM", "JPY": "DM", "GBP": "DM", "CAD": "DM", "AUD": "DM",
    "NZD": "DM", "SEK": "DM", "NOK": "DM",
    "BRL": "EM", "MXN": "EM", "CLP": "EM", "ZAR": "EM", "TRY": "EM",
    "PLN": "EM", "HUF": "EM", "CZK": "EM", "CNY": "EM", "KRW": "EM",
    "SGD": "EM", "MYR": "EM", "IDR": "EM", "INR": "EM", "PHP": "EM",
    "THB": "EM", "COP": "EM",
}

OUTPUT_DIR  = os.environ.get("OUTPUT_DIR") or os.path.expanduser("~/boquin.github.io/reports/fx-200d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

FRED_API_KEY = os.environ.get("FRED_API_KEY")

# ── Helpers ─────────────────────────────────────────────────────────────────────

def delete_outliers(df, z_threshold=2):
    """Replace single-day spike outliers using daily-returns z-score.

    Operates on returns, not price levels, so sustained FX trends (e.g. JPY
    depreciating from 110 to 160 over two years) are preserved while genuine
    data glitches (a single day printing an implausible value) are replaced
    with the prior observation.
    """
    from scipy import stats
    cleaned_df = df.copy()
    for col in cleaned_df.columns:
        series = cleaned_df[col].ffill()
        if len(series.dropna()) < 10:
            continue
        daily_ret = series.pct_change()
        valid = daily_ret.dropna()
        if len(valid) < 10:
            continue
        z = np.abs(stats.zscore(valid))
        # Align z-scores back to the full index (first row has no return)
        z_series = pd.Series(np.nan, index=series.index)
        z_series.iloc[1:len(z) + 1] = z
        outlier_idx = np.where(z_series > z_threshold)[0]
        for idx in outlier_idx:
            if idx > 0:
                cleaned_df[col].iloc[idx] = cleaned_df[col].iloc[idx - 1]
    return cleaned_df


def fetch_fx_data(years=YEARS_FX):
    """Fetch 25-currency FX grid from Yahoo Finance, matching FXpricelist.ipynb logic."""
    print(f"Fetching {years}Y FX data for {len(CCY_LIST)} currencies from Yahoo Finance…")
    start_date = datetime.datetime.now() - timedelta(days=365 * years)
    end_date = date.today()

    # Build tickers: {CCY}USD=x (price of 1 CCY in USD)
    tickers = [f"{ccy}USD=X" for ccy in CCY_LIST]

    data = yf.download(tickers, start=start_date, end=end_date,
                       group_by="ticker", auto_adjust=True, progress=False)

    frames = []
    for ccy, ticker in zip(CCY_LIST, tickers):
        try:
            s = data[ticker]["Close"] if ticker in data else data["Close"]
            frames.append(s.rename(ccy))
        except Exception:
            print(f"  Warning: could not extract {ccy}")

    close_df = pd.concat(frames, axis=1)
    close_df = close_df.bfill().ffill()

    # Exceptions: EUR/GBP/NZD/AUD tickers return USD per CCY — invert to get CCY per USD
    close_df[EXCEPTIONS] = 1 / close_df[EXCEPTIONS]

    # Now invert everything: EM → CCY/USD; exceptions double-inverted → USD/CCY
    df_a = 1 / close_df

    return df_a


def compute_200d(df, z_threshold=Z_THRESHOLD):
    """Remove outliers and compute % distance from 200-day moving average."""
    df_clean = delete_outliers(df, z_threshold)
    df_200d  = round((df_clean / df_clean.rolling(200).mean() - 1) * 100, 2)
    return df_200d


def fetch_broad_usd(years=YEARS_USD):
    """Fetch DTWEXBGS (Broad USD Index) directly from the FRED API."""
    if not FRED_API_KEY:
        print("No FRED_API_KEY — skipping Broad USD chart.")
        return None
    try:
        import urllib.request
        start = (datetime.datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=DTWEXBGS&observation_start={start}"
            f"&api_key={FRED_API_KEY}&file_type=json"
        )
        with urllib.request.urlopen(url) as resp:
            payload = json.loads(resp.read())
        obs = payload["observations"]
        records = {o["date"]: float(o["value"]) for o in obs if o["value"] != "."}
        fred_df = pd.DataFrame.from_dict(records, orient="index", columns=["Broad USD"])
        fred_df.index = pd.to_datetime(fred_df.index)
        fred_df = fred_df.sort_index().bfill()
        usd_200d = (fred_df / fred_df.rolling(200).mean() - 1) * 100
        top    = usd_200d.quantile(0.90).iloc[0]
        bottom = usd_200d.quantile(0.10).iloc[0]
        return usd_200d, top, bottom
    except Exception as e:
        print(f"FRED fetch failed: {e}")
        return None


# ── Chart builders ──────────────────────────────────────────────────────────────

def make_snapshot_bar(df_200d, df_edges):
    """Horizontal bar chart of current 200d extension for all 25 currencies."""
    current = df_200d.iloc[-1].sort_values()
    colors  = []
    for ccy in current.index:
        val = current[ccy]
        p25 = df_edges[ccy]["25%"]
        p75 = df_edges[ccy]["75%"]
        if val > p75:
            colors.append("#c62828")  # red — stretched high
        elif val < p25:
            colors.append("#1565c0")  # blue — stretched low
        else:
            colors.append("#78909c")  # grey — within range

    labels = [f"{ccy} ({CCY_NAMES.get(ccy, ccy)})" for ccy in current.index]

    fig = go.Figure(go.Bar(
        x=current.tolist(),
        y=labels,
        orientation="h",
        marker_color=colors,
        hovertemplate="<b>%{y}</b><br>Distance from 200d: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Current 200d MA Extension — All 25 Currencies", font_size=14),
        xaxis_title="% distance from 200d moving average",
        yaxis=dict(tickfont_size=11),
        height=700,
        margin=dict(l=10, r=20, t=40, b=40),
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        xaxis=dict(gridcolor="#f0f0f0", zeroline=True, zerolinecolor="#aaa", zerolinewidth=1),
    )
    # Reference line at zero
    fig.add_vline(x=0, line_width=1, line_dash="solid", line_color="#aaa")
    return fig


def make_currency_explorer(df_200d, df_edges):
    """Plotly figure with dropdown to select any currency — shows full history + bands."""
    ccys = list(df_200d.columns)
    first_ccy = ccys[0]

    fig = go.Figure()

    for i, ccy in enumerate(ccys):
        visible = (i == 0)
        p25 = df_edges[ccy]["25%"]
        p75 = df_edges[ccy]["75%"]

        x_vals = df_200d.index.strftime("%Y-%m-%d").tolist()
        # Main series
        fig.add_trace(go.Scatter(
            x=x_vals, y=df_200d[ccy].tolist(),
            mode="lines", name=ccy,
            line=dict(color="#1a3a2f", width=1.5),
            visible=visible,
            hovertemplate="%{x}: %{y:.2f}%<extra></extra>",
        ))
        # 25th percentile band
        fig.add_trace(go.Scatter(
            x=x_vals, y=[float(p25)] * len(df_200d),
            mode="lines", name="25th pct",
            line=dict(color="#c62828", dash="dash", width=1),
            visible=visible,
            showlegend=True,
            hoverinfo="skip",
        ))
        # 75th percentile band
        fig.add_trace(go.Scatter(
            x=x_vals, y=[float(p75)] * len(df_200d),
            mode="lines", name="75th pct",
            line=dict(color="#c62828", dash="dash", width=1),
            visible=visible,
            showlegend=True,
            hoverinfo="skip",
        ))

    # Build dropdown buttons (3 traces per currency)
    buttons = []
    for i, ccy in enumerate(ccys):
        vis = [False] * (len(ccys) * 3)
        vis[i * 3]     = True
        vis[i * 3 + 1] = True
        vis[i * 3 + 2] = True
        p25 = df_edges[ccy]["25%"]
        p75 = df_edges[ccy]["75%"]
        buttons.append(dict(
            label=ccy,
            method="update",
            args=[
                {"visible": vis},
                {"title": f"{ccy} — {CCY_NAMES.get(ccy, ccy)}: % Distance from 200d MA",
                 "annotations": [
                     dict(x=df_200d.index[-1].strftime("%Y-%m-%d"), y=float(p25), xanchor="right", yanchor="top",
                          text=f"25th: {p25:.1f}%", font=dict(color="#c62828", size=11),
                          showarrow=False),
                     dict(x=df_200d.index[-1].strftime("%Y-%m-%d"), y=float(p75), xanchor="right", yanchor="bottom",
                          text=f"75th: {p75:.1f}%", font=dict(color="#c62828", size=11),
                          showarrow=False),
                 ]}
            ],
        ))

    fig.update_layout(
        updatemenus=[dict(
            buttons=buttons,
            direction="down",
            showactive=True,
            x=0.01, xanchor="left",
            y=1.12, yanchor="top",
            bgcolor="#fff",
            bordercolor="#cdd4db",
            font_size=13,
        )],
        title=f"{first_ccy} — {CCY_NAMES.get(first_ccy, first_ccy)}: % Distance from 200d MA",
        yaxis_title="% distance from 200d MA",
        xaxis_title="",
        height=420,
        margin=dict(l=10, r=20, t=80, b=40),
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        xaxis=dict(gridcolor="#f0f0f0"),
        yaxis=dict(gridcolor="#f0f0f0", zeroline=True, zerolinecolor="#999", zerolinewidth=1),
        legend=dict(orientation="h", y=-0.12),
        hovermode="x unified",
    )

    # First currency annotations
    p25_0 = df_edges[first_ccy]["25%"]
    p75_0 = df_edges[first_ccy]["75%"]
    last_x = df_200d.index[-1].strftime("%Y-%m-%d")
    fig.update_layout(annotations=[
        dict(x=last_x, y=float(p25_0), xanchor="right", yanchor="top",
             text=f"25th: {p25_0:.1f}%", font=dict(color="#c62828", size=11), showarrow=False),
        dict(x=last_x, y=float(p75_0), xanchor="right", yanchor="bottom",
             text=f"75th: {p75_0:.1f}%", font=dict(color="#c62828", size=11), showarrow=False),
    ])
    return fig


def make_broad_usd_chart(usd_200d, top, bottom):
    """Broad USD 200d extension with 90th/10th percentile bands."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=usd_200d.index.strftime("%Y-%m-%d").tolist(), y=usd_200d["Broad USD"].tolist(),
        mode="lines", name="Broad USD 200d ext.",
        line=dict(color="#1a3a2f", width=1.8),
        hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra></extra>",
    ))
    for level, label in [(top, f"90th pct: {top:.1f}%"), (bottom, f"10th pct: {bottom:.1f}%")]:
        fig.add_hline(y=level, line_dash="dash", line_color="#c62828", line_width=1.2,
                      annotation_text=label, annotation_position="left",
                      annotation_font=dict(color="#c62828", size=11))
    fig.update_layout(
        title="Broad USD Index (DTWEXBGS) — % Distance from 200d MA",
        yaxis_title="% distance from 200d MA",
        height=380,
        margin=dict(l=10, r=20, t=40, b=40),
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        xaxis=dict(gridcolor="#f0f0f0"),
        yaxis=dict(gridcolor="#f0f0f0", zeroline=True, zerolinecolor="#999", zerolinewidth=1),
        hovermode="x unified",
        showlegend=False,
    )
    return fig


def make_median_chart(df_200d):
    """Median 200d extension across all 25 currencies."""
    median_series = df_200d.median(axis=1)
    p25 = float(median_series.quantile(0.25))
    p75 = float(median_series.quantile(0.75))
    x_vals = median_series.index.strftime("%Y-%m-%d").tolist()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_vals, y=median_series.tolist(),
        mode="lines", name="Median",
        line=dict(color="#2e7d32", width=1.8),
        fill="tozeroy",
        fillcolor="rgba(46,125,50,0.08)",
        hovertemplate="%{x}: %{y:.2f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x_vals, y=[p25] * len(median_series),
        mode="lines", name=f"25th pct: {p25:.1f}%",
        line=dict(color="#c62828", dash="dash", width=1),
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=x_vals, y=[p75] * len(median_series),
        mode="lines", name=f"75th pct: {p75:.1f}%",
        line=dict(color="#c62828", dash="dash", width=1),
        hoverinfo="skip",
    ))
    last_x = x_vals[-1]
    fig.update_layout(
        title="Median 200d Extension — All 25 Currencies (EM + DM Composite Gauge)",
        yaxis_title="Median % distance from 200d MA",
        height=320,
        margin=dict(l=10, r=20, t=40, b=40),
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        xaxis=dict(gridcolor="#f0f0f0"),
        yaxis=dict(gridcolor="#f0f0f0", zeroline=True, zerolinecolor="#999", zerolinewidth=1),
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.18),
        annotations=[
            dict(x=last_x, y=p25, xanchor="right", yanchor="top",
                 text=f"25th: {p25:.1f}%", font=dict(color="#c62828", size=11), showarrow=False),
            dict(x=last_x, y=p75, xanchor="right", yanchor="bottom",
                 text=f"75th: {p75:.1f}%", font=dict(color="#c62828", size=11), showarrow=False),
        ],
    )
    return fig


# ── HTML generation ─────────────────────────────────────────────────────────────

def build_extremes_table(df_200d, df_edges):
    """HTML table of currencies outside their 25th/75th percentile bands."""
    current = df_200d.iloc[-1]
    rows = []
    for ccy in df_200d.columns:
        val  = current[ccy]
        p25  = df_edges[ccy]["25%"]
        p75  = df_edges[ccy]["75%"]
        if val > p75 or val < p25:
            status = "Above 75th" if val > p75 else "Below 25th"
            color  = "#c62828" if val > p75 else "#1565c0"
            rows.append((ccy, CCY_NAMES.get(ccy, ""), REGION.get(ccy, ""), val, p25, p75, status, color))

    if not rows:
        return "<p style='color:#666;font-size:.85rem;'>No currencies at extremes today.</p>"

    rows.sort(key=lambda r: r[3])

    html = """
    <table class="ext-table">
      <thead>
        <tr>
          <th>Currency</th><th>Name</th><th>Region</th>
          <th>Current</th><th>25th %ile</th><th>75th %ile</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
    """
    for ccy, name, region, val, p25, p75, status, color in rows:
        reg_class = "em" if region == "EM" else "dm"
        html += f"""
        <tr>
          <td><strong>{ccy}</strong></td>
          <td>{name}</td>
          <td><span class="reg-badge {reg_class}">{region}</span></td>
          <td style="color:{color};font-weight:700">{val:+.1f}%</td>
          <td>{p25:.1f}%</td>
          <td>{p75:.1f}%</td>
          <td style="color:{color};font-weight:600">{status}</td>
        </tr>"""
    html += "</tbody></table>"
    return html


def fig_to_json(fig):
    import plotly.io as pio
    return pio.to_json(fig, engine="json")  # force plain-JSON engine; avoids bdata binary encoding from Plotly 6.x


def generate_html(df_200d, df_edges, broad_usd_data, today_str):
    """Render the full dashboard as a self-contained HTML string."""

    fig_bar      = make_snapshot_bar(df_200d, df_edges)
    fig_explorer = make_currency_explorer(df_200d, df_edges)
    fig_median   = make_median_chart(df_200d)
    extremes_html = build_extremes_table(df_200d, df_edges)

    bar_json      = fig_to_json(fig_bar)
    explorer_json = fig_to_json(fig_explorer)
    median_json   = fig_to_json(fig_median)

    broad_usd_section = ""
    if broad_usd_data:
        usd_200d, top, bottom = broad_usd_data
        fig_usd = make_broad_usd_chart(usd_200d, top, bottom)
        usd_json = fig_to_json(fig_usd)
        broad_usd_section = f"""
        <div class="card">
          <div class="card-title">Broad USD Index — 30-Year History</div>
          <div class="card-note">DTWEXBGS from FRED · 90th/10th percentile bands shown</div>
          <div id="chart-usd"></div>
        </div>
        <script>Plotly.newPlot('chart-usd', {usd_json}.data, {usd_json}.layout, {{responsive:true,displayModeBar:false}});</script>
        """

    current = df_200d.iloc[-1]
    n_above = (current > df_edges.T["75%"]).sum()
    n_below = (current < df_edges.T["25%"]).sum()
    last_date = df_200d.index[-1].strftime("%B %d, %Y")
    median_now = round(df_200d.iloc[-1].median(), 1)
    median_sign = "+" if median_now >= 0 else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FX 200d MA Extension Dashboard — boquin.xyz</title>
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
.kpi-val.red{{color:#c62828}}.kpi-val.blue{{color:#1565c0}}.kpi-val.green{{color:#2e7d32}}

.content{{padding:20px 32px;max-width:1440px;margin:0 auto}}
.card{{background:#fff;border:1px solid #e4e8ec;border-radius:10px;padding:16px 20px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.card-title{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:4px}}
.card-note{{font-size:.75rem;color:#aaa;margin-bottom:12px}}

/* Extremes table */
.ext-table{{width:100%;border-collapse:collapse;font-size:.83rem}}
.ext-table th{{background:#f5f7fa;padding:8px 10px;text-align:left;font-size:.68rem;text-transform:uppercase;letter-spacing:.4px;color:#888;border-bottom:2px solid #e4e8ec}}
.ext-table td{{padding:9px 10px;border-bottom:1px solid #f0f0f0}}
.ext-table tr:hover td{{background:#fafbfc}}
.reg-badge{{display:inline-block;padding:2px 7px;border-radius:10px;font-size:.68rem;font-weight:700;letter-spacing:.3px}}
.reg-badge.em{{background:#fff3e0;color:#e65100}}
.reg-badge.dm{{background:#e8f0ec;color:#1a3a2f}}

.section-hdr{{font-size:1rem;font-weight:700;color:#1a3a2f;margin:24px 0 12px;border-left:4px solid #1a3a2f;padding-left:10px}}
.quoting-note{{font-size:.75rem;color:#888;background:#fafbfc;border:1px solid #e8eaec;border-radius:6px;padding:8px 12px;margin-bottom:14px;line-height:1.5}}

@media(max-width:640px){{
  .hdr,.kpi-bar,.content{{padding-left:14px;padding-right:14px}}
  .kpi-bar{{gap:18px}}
}}
</style>
</head>
<body>

<div class="hdr">
  <h1>FX 200-Day Moving Average Extension</h1>
  <div class="sub">% distance from the 200-day moving average · 25 currencies · EM + DM</div>
  <div class="meta">Data: Yahoo Finance (yfinance) · FRED (DTWEXBGS) · Last observation: {last_date} · Generated: {today_str}</div>
</div>

<div class="kpi-bar">
  <div class="kpi">
    <span class="kpi-lbl">Currencies at extremes</span>
    <span class="kpi-val">{n_above + n_below} / 25</span>
  </div>
  <div class="kpi">
    <span class="kpi-lbl">Above 75th percentile</span>
    <span class="kpi-val red">{n_above}</span>
  </div>
  <div class="kpi">
    <span class="kpi-lbl">Below 25th percentile</span>
    <span class="kpi-val blue">{n_below}</span>
  </div>
  <div class="kpi">
    <span class="kpi-lbl">Median 200d extension</span>
    <span class="kpi-val {'red' if median_now > 0 else 'green'}">{median_sign}{median_now}%</span>
  </div>
</div>

<div class="content">

  <div class="quoting-note">
    <strong>Quoting convention:</strong>
    EM currencies (BRL, MXN, etc.) are quoted as <em>CCY per USD</em> — positive extension means the USD is trading above its 200d average against that currency.
    EUR, GBP, AUD, NZD are quoted as <em>USD per CCY</em> — positive extension means the CCY is trading above its 200d average vs the USD.
    JPY, CAD, SEK, NOK are quoted as <em>CCY per USD</em>.
  </div>

  <div class="section-hdr">Currencies at Extremes</div>
  <div class="card">
    <div class="card-title">Flagged Currencies — Outside 25th/75th Percentile Bands</div>
    <div class="card-note">Based on full history since {df_200d.dropna().index[0].strftime("%Y")} · Red = stretched high (above 75th) · Blue = stretched low (below 25th)</div>
    {extremes_html}
  </div>

  <div class="section-hdr">Snapshot — All 25 Currencies</div>
  <div class="card">
    <div class="card-title">Today's 200d Extension</div>
    <div class="card-note">Red bars = above 75th percentile · Blue bars = below 25th percentile · Grey = within normal range</div>
    <div id="chart-bar"></div>
  </div>

  <div class="section-hdr">Currency Explorer</div>
  <div class="card">
    <div class="card-title">Individual Currency — Full History</div>
    <div class="card-note">Select any currency from the dropdown · Red dashed lines = 25th and 75th historical percentiles</div>
    <div id="chart-explorer"></div>
  </div>

  <div class="section-hdr">Composite Indicators</div>

  {broad_usd_section}

  <div class="card">
    <div class="card-title">Median 200d Extension — EM + DM Composite</div>
    <div class="card-note">Median across all 25 currencies · Positive = USD broadly above trend · Negative = USD broadly below trend</div>
    <div id="chart-median"></div>
  </div>

</div>

<script>
var bar_data = {bar_json};
var explorer_data = {explorer_json};
var median_data = {median_json};

Plotly.newPlot('chart-bar',      bar_data.data,      bar_data.layout,      {{responsive:true, displayModeBar:false}});
Plotly.newPlot('chart-explorer', explorer_data.data, explorer_data.layout, {{responsive:true, displayModeBar:true}});
Plotly.newPlot('chart-median',   median_data.data,   median_data.layout,   {{responsive:true, displayModeBar:false}});
</script>

</body>
</html>"""
    return html


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Fetch and process FX data
    df_raw   = fetch_fx_data(YEARS_FX)
    df_200d  = compute_200d(df_raw, Z_THRESHOLD)
    df_edges = df_200d.describe().loc[["25%", "75%"]]

    print(f"  200d extension computed for {len(df_200d.columns)} currencies")
    print(f"  Date range: {df_200d.dropna().index[0].date()} → {df_200d.index[-1].date()}")

    # 2. Fetch Broad USD from FRED
    broad_usd_data = fetch_broad_usd(YEARS_USD)

    # 3. Generate HTML
    print("Building dashboard HTML…")
    html = generate_html(df_200d, df_edges, broad_usd_data, today_str)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to: {OUTPUT_FILE}")

    # Summary
    current = df_200d.iloc[-1]
    above   = current[current > df_edges.T["75%"]]
    below   = current[current < df_edges.T["25%"]]
    print(f"\nExtremes ({df_200d.index[-1].date()}):")
    if len(above):
        print(f"  Above 75th: {', '.join(f'{c} ({v:+.1f}%)' for c, v in above.items())}")
    if len(below):
        print(f"  Below 25th: {', '.join(f'{c} ({v:+.1f}%)' for c, v in below.items())}")
    if not len(above) and not len(below):
        print("  No currencies at extremes today.")


if __name__ == "__main__":
    main()
