#!/usr/bin/env python3
"""
Brazil IPCA Apr 2026 — Interactive Inflation Report
Recreates GS Economics Research charts using BCB SGS data.
"""

import os
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
import sgs

OUTPUT_DIR = "/Users/macproajb/boquin.github.io/reports/brasil-macro"
OUTPUT_FILE = "ipca15_apr2026.html"

SERIES = {
    433:   "IPCA Headline",
    4447:  "Tradable Goods",
    4448:  "Non-Tradable Goods",
    4449:  "Administered Prices",
    10844: "Services",
    11427: "Core EX0",
    16121: "Core EX1",
    16122: "Core Trimmed Mean",
    11426: "Core Smoothed Trimmed Mean",
    28751: "Core Excl Food & Energy",
    1644:  "Food at Home",
    1645:  "Food Away from Home",
    28647: "Fuel",
}

GS_NAVY = "#003d79"
GS_RED  = "#c0392b"
GS_BLUE = "#2980b9"
GS_LTBLUE = "#85c1e9"
GS_GRAY = "#808080"

CHART_START = "2018-01-01"
CHART_END   = "2027-01-01"


def pull_all(years=15):
    today = datetime.today()
    start = (today - relativedelta(years=years)).strftime("%d/%m/%Y")
    end   = today.strftime("%d/%m/%Y")

    codes = list(SERIES.keys())
    df = sgs.dataframe(codes, start=start, end=end)
    df.columns = [SERIES[c] for c in codes]
    df.index = df.index.to_timestamp() if hasattr(df.index, "to_timestamp") else df.index
    return df


def mom_to_yoy(s, max_mom_pct=15.0):
    """Convert mom % series to yoy % via cumproduct.
    Clips implausible monthly values (>max_mom_pct%) to NaN before compounding
    to avoid distortion from non-mom% series or data errors.
    """
    s_clean = s.copy().astype(float)
    s_clean[s_clean.abs() > max_mom_pct] = float("nan")
    s_clean = s_clean.clip(lower=-0.999).fillna(0)
    cum = (1 + s_clean / 100).cumprod() * 100
    return cum.pct_change(12) * 100


def apply_yoy(df):
    return df.apply(mom_to_yoy)


def three_mma(s):
    """3-month moving average (unannualized)."""
    return s.rolling(3).mean()


def compute_derived(raw, yoy):
    """Add derived columns."""
    # Core average of 5 measures
    core_cols = ["Core EX0", "Core EX1", "Core Trimmed Mean",
                 "Core Smoothed Trimmed Mean", "Core Excl Food & Energy"]
    yoy["Core Avg-5"] = yoy[core_cols].mean(axis=1)

    # Freely determined prices (approx): headline back-solved from 75.2% free / 24.8% administered
    free_raw = (raw["IPCA Headline"] - 0.248 * raw["Administered Prices"]) / 0.752
    yoy["Freely Determined Prices"] = mom_to_yoy(free_raw)

    # 3MMA of services (not annualized, just smoothed yoy)
    yoy["Services 3MMA"] = three_mma(yoy["Services"])
    yoy["Core Services 3MMA"] = three_mma(yoy["Non-Tradable Goods"])

    return yoy


def band(fig, ymin, ymax, color="rgba(200,200,200,0.18)", row=1, col=1):
    fig.add_hrect(y0=ymin, y1=ymax, fillcolor=color, line_width=0, row=row, col=col)


def add_target_band(fig, row=1, col=1):
    band(fig, 1.5, 4.5, row=row, col=col)
    fig.add_hline(y=3.0, line_dash="dot", line_color="gray", line_width=1, row=row, col=col)


def line_chart(yoy, cols, colors, title, years=9):
    cutoff = pd.Timestamp(CHART_START)
    sub = yoy.loc[cutoff:][cols].dropna(how="all")
    fig = go.Figure()
    for col, color in zip(cols, colors):
        s = sub[col].dropna()
        last_val = s.iloc[-1] if len(s) else None
        label = f"{col}: {last_val:.1f}%" if last_val is not None else col
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, name=label,
            line=dict(color=color, width=2),
        ))
    add_target_band(fig)
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#222")),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=50, r=20, t=50, b=40),
        legend=dict(orientation="h", y=-0.15, x=0),
        hovermode="x unified",
        yaxis=dict(ticksuffix="%", gridcolor="#eeeeee"),
        xaxis=dict(range=[CHART_START, CHART_END], gridcolor="#eeeeee"),
    )
    return fig


def services_3mma_chart(yoy):
    cutoff = pd.Timestamp(CHART_START)
    sub = yoy.loc[cutoff:]
    cols = ["Services 3MMA", "Core Services 3MMA"]
    colors = [GS_NAVY, GS_RED]
    display = ["Services", "Core Services (Non-Tradable proxy)"]
    fig = go.Figure()
    for col, color, disp in zip(cols, colors, display):
        s = sub[col].dropna()
        last_val = s.iloc[-1] if len(s) else None
        label = f"{disp}: {last_val:.1f}%" if last_val is not None else disp
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=label,
                                 line=dict(color=color, width=2)))
    add_target_band(fig)
    fig.update_layout(
        title=dict(text="Services Inflation — 3MMA (YoY)", font=dict(size=13, color="#222")),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=50, r=20, t=50, b=40),
        legend=dict(orientation="h", y=-0.15, x=0),
        hovermode="x unified",
        yaxis=dict(ticksuffix="%", gridcolor="#eeeeee"),
        xaxis=dict(range=[CHART_START, CHART_END], gridcolor="#eeeeee"),
    )
    return fig


def food_fuel_chart(yoy):
    cutoff = pd.Timestamp(CHART_START)
    sub = yoy.loc[cutoff:]
    cols   = ["Food at Home", "Food Away from Home", "Fuel"]
    colors = [GS_NAVY, GS_LTBLUE, GS_RED]
    fig = go.Figure()
    for col, color in zip(cols, colors):
        s = sub[col].dropna()
        last_val = s.iloc[-1] if len(s) else None
        label = f"{col}: {last_val:.1f}%" if last_val is not None else col
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=label,
                                 line=dict(color=color, width=2)))
    add_target_band(fig)
    fig.update_layout(
        title=dict(text="Food at Home / Food Away / Fuel — %YoY", font=dict(size=13, color="#222")),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=50, r=20, t=50, b=40),
        legend=dict(orientation="h", y=-0.15, x=0),
        hovermode="x unified",
        yaxis=dict(ticksuffix="%", gridcolor="#eeeeee"),
        xaxis=dict(range=[CHART_START, CHART_END], gridcolor="#eeeeee"),
    )
    return fig


def contribution_bar(yoy):
    """Horizontal bar: latest yoy contribution by IPCA group (approximate weights)."""
    weights = {
        "Food at Home":       0.158,
        "Food Away from Home": 0.058,
        "Fuel":               0.057,
        "Services":           0.347,
        "Tradable Goods":     0.322,
        "Administered Prices":0.248,
    }
    latest = yoy.dropna(subset=["IPCA Headline"]).iloc[-1]
    contribs = {}
    for col, w in weights.items():
        if col in yoy.columns:
            val = yoy[col].dropna().iloc[-1] if col in yoy.columns else None
            if val is not None and not np.isnan(val):
                contribs[col] = round(w * val, 2)  # pp contribution

    cats = list(contribs.keys())
    vals = [contribs[c] for c in cats]
    colors = [GS_RED if v > 0 else GS_NAVY for v in vals]

    # Sort by value
    paired = sorted(zip(vals, cats), key=lambda x: x[0])
    vals_s = [p[0] for p in paired]
    cats_s = [p[1] for p in paired]
    colors_s = [GS_RED if v > 0 else GS_NAVY for v in vals_s]

    fig = go.Figure(go.Bar(
        x=vals_s, y=cats_s, orientation="h",
        marker_color=colors_s,
        text=[f"{v:.2f}" for v in vals_s],
        textposition="outside",
    ))
    fig.update_layout(
        title=dict(text="IPCA — YoY Contribution by Component (approx. pp)", font=dict(size=13, color="#222")),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=150, r=60, t=50, b=40),
        xaxis=dict(title="Contribution (percentage points)", ticksuffix="pp", gridcolor="#eeeeee"),
        yaxis=dict(gridcolor="#eeeeee"),
    )
    return fig


def stacked_area_chart(yoy):
    """Stacked area: food at home, food away, fuel, other contributions over time."""
    weights = {
        "Food at Home":        0.158,
        "Food Away from Home": 0.058,
        "Fuel":                0.057,
    }
    cutoff = pd.Timestamp(CHART_START)
    sub = yoy.loc[cutoff:]

    contribs = pd.DataFrame(index=sub.index)
    for col, w in weights.items():
        contribs[col] = sub[col] * w  # contribution in pp (yoy% × weight)

    # "Other" = headline - sum of tracked components
    contribs["Other"] = sub["IPCA Headline"] - contribs.sum(axis=1)

    contribs = contribs.dropna()

    colors_map = {
        "Food at Home":        ("rgba(0,61,121,0.7)",   GS_NAVY),
        "Food Away from Home": ("rgba(133,193,233,0.7)", GS_LTBLUE),
        "Fuel":                ("rgba(192,57,43,0.7)",  GS_RED),
        "Other":               ("rgba(128,128,128,0.5)", GS_GRAY),
    }

    fig = go.Figure()
    for col in ["Food at Home", "Food Away from Home", "Fuel", "Other"]:
        fill_color, line_color = colors_map[col]
        fig.add_trace(go.Scatter(
            x=contribs.index, y=contribs[col],
            name=col,
            fill="tonexty" if col != "Food at Home" else "tozeroy",
            line=dict(color=line_color, width=0.5),
            fillcolor=fill_color,
            stackgroup="one",
        ))
    # Overlay headline yoy line (in pp for same axis)
    fig.add_trace(go.Scatter(
        x=sub["IPCA Headline"].dropna().index,
        y=sub["IPCA Headline"].dropna().values,
        name="IPCA %YoY",
        line=dict(color=GS_NAVY, width=2, dash="dot"),
    ))
    fig.update_layout(
        title=dict(text="IPCA — YoY Contribution: Food & Fuel vs Other (stacked, pp)", font=dict(size=13, color="#222")),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=50, r=20, t=50, b=40),
        legend=dict(orientation="h", y=-0.15, x=0),
        hovermode="x unified",
        yaxis=dict(ticksuffix="pp", gridcolor="#eeeeee"),
        xaxis=dict(range=[CHART_START, CHART_END], gridcolor="#eeeeee"),
    )
    return fig


def build_heatmap_table(yoy):
    """Heat-map table: Brazil Inflation Dynamics."""
    col_map = {
        "Headline":      "IPCA Headline",
        "Core":          "Core Avg-5",
        "Services":      "Services",
        "Core Services": "Non-Tradable Goods",
        "Tradable":      "Tradable Goods",
        "Food at Home":  "Food at Home",
        "Food Away":     "Food Away from Home",
        "Fuel":          "Fuel",
    }

    # Select snapshot rows
    snapshots = []
    for year in range(2018, 2025):
        snapshots.append(f"{year}-12")
    for q in ["03", "06", "09", "12"]:
        snapshots.append(f"2025-{q}")
    for m in ["01", "02", "03"]:
        snapshots.append(f"2026-{m}")

    rows = []
    for snap in snapshots:
        try:
            row_data = yoy.loc[snap]
            if isinstance(row_data, pd.DataFrame):
                row_data = row_data.iloc[-1]
            label = pd.Period(snap, freq="M").strftime("%b-%y")
            row = {"Period": label}
            for disp_col, src_col in col_map.items():
                if src_col in row_data.index:
                    v = row_data[src_col]
                    row[disp_col] = round(float(v), 2) if not pd.isna(v) else None
                else:
                    row[disp_col] = None
            rows.append(row)
        except (KeyError, IndexError):
            continue

    df_table = pd.DataFrame(rows).set_index("Period")

    # Color scale: 0%=green, 8%=red
    def cell_color(val):
        if val is None or pd.isna(val):
            return "#ffffff"
        v = max(0, min(float(val), 10))
        r = int(255 * v / 10 + 240 * (1 - v / 10))
        g = int(240 * (1 - v / 10) + 255 * v / 10 * 0)
        b = int(240 * (1 - v / 10))
        # Simple red-yellow-green: low=green, high=red
        ratio = min(max((v - 1.5) / 6.5, 0), 1)
        r2 = int(80 + 175 * ratio)
        g2 = int(200 - 150 * ratio)
        b2 = int(80 + 10 * ratio)
        return f"rgb({r2},{g2},{b2})"

    # Build HTML table
    display_cols = list(col_map.keys())
    weights_row = {
        "Headline": "—", "Core": "57.5%", "Services": "34.7%",
        "Core Services": "20.6%", "Tradable": "32.2%",
        "Food at Home": "15.8%", "Food Away": "5.8%", "Fuel": "5.7%",
    }

    header_cells = "".join(
        f'<th style="background:{GS_NAVY};color:white;padding:5px 8px;font-size:11px;white-space:nowrap">{c}</th>'
        for c in ["Period"] + display_cols
    )
    weight_cells = '<td style="padding:4px 8px;font-size:10px;background:#f0f0f0;font-weight:bold">CPI Weights</td>' + "".join(
        f'<td style="padding:4px 8px;font-size:10px;background:#f0f0f0;text-align:center">{weights_row.get(c,"")}</td>'
        for c in display_cols
    )

    data_rows = ""
    for period, row in df_table.iterrows():
        cells = f'<td style="padding:4px 8px;font-size:11px;font-weight:bold;white-space:nowrap">{period}</td>'
        for col in display_cols:
            val = row.get(col)
            bg = cell_color(val)
            txt = f"{val:.2f}" if val is not None else "—"
            cells += f'<td style="padding:4px 8px;font-size:11px;text-align:center;background:{bg};color:white;font-weight:bold">{txt}</td>'
        data_rows += f"<tr>{cells}</tr>\n"

    table_html = f"""
<div style="overflow-x:auto;margin:20px 0">
  <p style="font-weight:bold;font-size:13px;text-align:center;margin-bottom:4px">
    Brazil: IPCA Inflation Dynamics (% YoY)
  </p>
  <p style="font-size:10px;text-align:center;color:#666;margin-bottom:8px">
    Source: BCB SGS / IBGE via python-sgs &nbsp;|&nbsp; Core = avg of 5 BCB core measures &nbsp;|&nbsp; Core Services ≈ Non-Tradable Goods (proxy)
  </p>
  <table style="border-collapse:collapse;width:100%;min-width:700px">
    <thead><tr>{header_cells}</tr><tr>{weight_cells}</tr></thead>
    <tbody>{data_rows}</tbody>
  </table>
</div>"""
    return table_html


def to_div(fig, div_id, first=False):
    js = "cdn" if first else False
    return pio.to_html(fig, full_html=False, include_plotlyjs=js, div_id=div_id)


def key_numbers_html(yoy):
    latest = {}
    for col in yoy.columns:
        s = yoy[col].dropna()
        if len(s):
            latest[col] = s.iloc[-1]

    def fmt(col, default="—"):
        v = latest.get(col)
        return f"{v:.2f}%" if v is not None else default

    return f"""
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin:20px 0">
  {kpi("IPCA Headline", fmt("IPCA Headline"), "% YoY")}
  {kpi("Core Avg-5", fmt("Core Avg-5"), "% YoY | avg 5 measures")}
  {kpi("Services", fmt("Services"), "% YoY")}
  {kpi("Core Services", fmt("Non-Tradable Goods"), "% YoY | non-tradable proxy")}
  {kpi("Tradable Goods", fmt("Tradable Goods"), "% YoY")}
  {kpi("Food at Home", fmt("Food at Home"), "% YoY")}
  {kpi("Food Away", fmt("Food Away from Home"), "% YoY")}
  {kpi("Fuel", fmt("Fuel"), "% YoY")}
</div>"""


def kpi(label, value, sub=""):
    return f"""
  <div style="background:white;border-radius:8px;padding:14px;box-shadow:0 2px 6px rgba(0,0,0,0.08);border-left:4px solid {GS_NAVY}">
    <div style="font-size:10px;color:#666;text-transform:uppercase;letter-spacing:.5px">{label}</div>
    <div style="font-size:22px;font-weight:bold;color:{GS_NAVY};margin:4px 0">{value}</div>
    <div style="font-size:10px;color:#999">{sub}</div>
  </div>"""


def build_html(charts_divs, table_html, kpi_html, as_of):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Brazil IPCA Apr 2026 | boquin.xyz</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
           max-width:1200px;margin:0 auto;padding:20px;background:#f4f6f9; }}
    h1 {{ color:{GS_NAVY};border-bottom:3px solid {GS_NAVY};padding-bottom:8px;font-size:1.4em; }}
    h2 {{ color:{GS_NAVY};font-size:1.1em;margin-top:30px; }}
    .meta {{ font-size:12px;color:#666;margin-bottom:12px; }}
    .bottom-line {{ background:white;border-left:4px solid {GS_NAVY};padding:14px 18px;
                   border-radius:0 8px 8px 0;margin:20px 0;font-size:13px;line-height:1.6; }}
    .charts-grid {{ display:grid;grid-template-columns:repeat(auto-fill,minmax(540px,1fr));gap:20px;margin:20px 0; }}
    .chart-box {{ background:white;border-radius:8px;padding:12px;box-shadow:0 2px 6px rgba(0,0,0,0.08); }}
    .note {{ font-size:11px;color:#888;margin-top:4px; }}
    footer {{ margin-top:40px;font-size:11px;color:#999;border-top:1px solid #ddd;padding-top:12px; }}
  </style>
</head>
<body>
<h1>Brazil: IPCA Apr 2026 — Inflation Dashboard</h1>
<div class="meta">
  As of <strong>{as_of}</strong> &nbsp;|&nbsp; Data: BCB SGS / IBGE via python-sgs &nbsp;|&nbsp;
  Inspired by Goldman Sachs Economics Research (28 Apr 2026)
</div>

<div class="bottom-line">
  <strong>Bottom line:</strong>
  IPCA printed at <strong>0.89% mom (4.37% yoy)</strong>, below the 0.98% consensus, driven by an unexpected large decline in airfares (−14.32% vs consensus for a small increase).
  Core inflation averaged <strong>0.46% mom (4.33% yoy)</strong>. Core services printed 0.45% mom (<strong>5.32% yoy</strong>), with upside in car rental, insurance, medical services and food-away-from-home.
  Services pressures remain elevated with 3MMA SA tracking at 6.6% (from 6.5% in Mar).
  Fuel and food-away-from-home continue to press while food-at-home remains benign.
</div>

<h2>Key Numbers (Latest Available)</h2>
{kpi_html}

<h2>Inflation Dynamics Table</h2>
{table_html}

<h2>Charts</h2>
<div class="charts-grid">
  <div class="chart-box">{charts_divs[0]}</div>
  <div class="chart-box">{charts_divs[1]}</div>
  <div class="chart-box">{charts_divs[2]}</div>
  <div class="chart-box">{charts_divs[3]}</div>
  <div class="chart-box">{charts_divs[4]}</div>
  <div class="chart-box">{charts_divs[5]}</div>
  <div class="chart-box">{charts_divs[6]}</div>
</div>

<p class="note">
  ⚠ Notes: "Core Services" proxied by Non-Tradable Goods (BCB 4448). "Freely Determined Prices" back-solved from headline and administered series using ~75%/25% weights.
  3MMA charts show 3-month moving average of YoY (not seasonally adjusted). Labor/Inertia/Slack-Sensitive services use GS-proprietary classification unavailable from BCB SGS.
  Source: BCB SGS / IBGE via python-sgs.
</p>

<footer>
  <a href="/reports/brasil-macro/">← Brasil Macro Archive</a> &nbsp;|&nbsp;
  Generated {as_of} &nbsp;|&nbsp; boquin.xyz
</footer>
</body>
</html>"""


def main():
    print("Fetching BCB SGS series…")
    raw = pull_all(years=15)
    print(f"Pulled {len(raw.columns)} series, {len(raw)} months of data")
    print(raw.tail(3).to_string())

    print("\nComputing YoY transforms…")
    yoy = apply_yoy(raw)
    yoy = compute_derived(raw, yoy)

    # Print latest snapshot
    snapshot_cols = ["IPCA Headline", "Core Avg-5", "Services", "Tradable Goods",
                     "Administered Prices", "Food at Home", "Food Away from Home", "Fuel"]
    print("\nLatest YoY values:")
    for col in snapshot_cols:
        if col in yoy.columns:
            s = yoy[col].dropna()
            if len(s):
                print(f"  {col:30s}: {s.index[-1].date()} → {s.iloc[-1]:.2f}%")

    as_of = datetime.today().strftime("%d %b %Y")

    print("\nBuilding charts…")

    c1 = line_chart(yoy,
        cols=["Freely Determined Prices", "Administered Prices"],
        colors=[GS_NAVY, GS_RED],
        title="High Administered Prices Inflation (%YoY)",
        years=9)

    c2 = line_chart(yoy,
        cols=["Services", "Core Avg-5"],
        colors=[GS_NAVY, GS_RED],
        title="Core and Services Inflationary Pressures (%YoY)",
        years=9)

    c3 = line_chart(yoy,
        cols=["Tradable Goods", "Non-Tradable Goods"],
        colors=[GS_NAVY, GS_RED],
        title="Tradables vs Non-Tradables Inflation (%YoY)",
        years=9)

    c4 = food_fuel_chart(yoy)
    c5 = services_3mma_chart(yoy)
    c6 = contribution_bar(yoy)
    c7 = stacked_area_chart(yoy)

    print("Building heatmap table…")
    table_html = build_heatmap_table(yoy)

    print("Building KPI cards…")
    kpi_html = key_numbers_html(yoy)

    print("Assembling HTML…")
    figs = [c1, c2, c3, c4, c5, c6, c7]
    divs = [to_div(fig, f"chart{i+1}", first=(i == 0)) for i, fig in enumerate(figs)]
    html = build_html(divs, table_html, kpi_html, as_of)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✓ Saved: {out_path}")
    print(f"  Open: open \"{out_path}\"")


if __name__ == "__main__":
    main()
