"""
U.S. Inflation Monitor
Sources:
  - BLS Public Data API v2 (CPI series, seasonally adjusted)

Required env vars:
  BLS_API_KEY  — free registration at https://www.bls.gov/developers/

Run from repo root:
    BLS_API_KEY=xxx python3 scripts/generate_us_inflation_monitor.py
"""

import os
import json
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, date
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BLS_API_KEY = os.environ.get("BLS_API_KEY")
if not BLS_API_KEY:
    raise EnvironmentError("BLS_API_KEY environment variable is not set.")

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "us-inflation-monitor"
OUTPUT_FILE = OUTPUT_DIR / "index.html"

# ── BLS Series ────────────────────────────────────────────────────────────────
SERIES = {
    "cpi":              "CUUR0000SA0",     # All items (NSA)
    "core_cpi":         "CUUR0000SA0L1E",  # Less food & energy (NSA)
    "shelter":          "CUUR0000SAH1",    # Shelter (NSA)
    "cpi_ex_shelter":   "CUUR0000SA0L2",   # Less shelter (NSA)
    "food":             "CUUR0000SAF1",    # Food (NSA)
    "food_home":        "CUUR0000SAF11",   # Food at home (NSA)
    "food_away":        "CUUR0000SEFV",    # Food away from home (NSA)
    "energy":           "CUUR0000SA0E",    # Energy (NSA)
    "energy_goods":     "CUUR0000SACL2",   # Energy commodities/gasoline (NSA)
    "energy_services":  "CUUR0000SAHE",    # Household energy services (NSA)
    "core_goods":       "CUUR0000SACL1E",  # Commodities less food & energy (NSA)
    "core_services":    "CUUR0000SASLE",   # Services less energy services (NSA)
    "housing":          "CUUR0000SAH",     # Housing major group (NSA)
    "food_bev":         "CUUR0000SAF",     # Food and beverages (NSA)
    "medical":          "CUUR0000SAM",     # Medical care (NSA)
    "transportation":   "CUUR0000SAT",     # Transportation (NSA)
    "apparel":          "CUUR0000SAA",     # Apparel (NSA)
    "edu_comm":         "CUUR0000SAE",     # Education & communication (NSA)
    "recreation":       "CUUR0000SAR",     # Recreation (NSA)
    "other":            "CUUR0000SAG",     # Other goods and services (NSA)
}

# ── Weights (BLS Relative Importance, Jan 2025) ───────────────────────────────
WEIGHTS = {
    "cpi":             100.0,  # Total
    # Table 1 — Major groups
    "housing":          44.5,
    "food_bev":         14.5,
    "transportation":   16.2,
    "medical":           8.4,
    "recreation":        5.1,
    "edu_comm":          5.8,
    "apparel":           2.5,
    "other":             2.9,
    # Table 2 — Food/Energy/Core breakdown
    "food":             13.7,
    "food_home":         8.3,
    "food_away":         5.4,
    "energy":            6.4,
    "energy_goods":      3.1,
    "energy_services":   3.3,
    "core_cpi":         79.9,
    "core_goods":       19.1,
    "core_services":    60.8,
    # Table 3 — Shelter split
    "shelter":          35.5,
    "cpi_ex_shelter":   64.4,
}

# ── NBER Recession bands ──────────────────────────────────────────────────────
RECESSIONS = [
    ("2001-03-01", "2001-11-30"),
    ("2007-12-01", "2009-06-30"),
    ("2020-02-01", "2020-04-30"),
]


# ── Fetch BLS data ────────────────────────────────────────────────────────────
def fetch_bls_batch(series_ids: list, start_year: int, end_year: int) -> dict:
    """POST one BLS API v2 request for up to 50 series. Returns {series_id: pd.Series}."""
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
        "registrationkey": BLS_API_KEY,
    }
    resp = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()

    if result.get("status") != "REQUEST_SUCCEEDED":
        msgs = result.get("message", [])
        raise RuntimeError(f"BLS API error: {msgs}")

    out = {}
    for series in result.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        rows = []
        for obs in series.get("data", []):
            try:
                yr = int(obs["year"])
                period = obs["period"]  # e.g. "M01"
                if not period.startswith("M"):
                    continue
                mo = int(period[1:])
                val = float(obs["value"])
                rows.append((pd.Timestamp(yr, mo, 1), val))
            except (ValueError, KeyError):
                continue
        if rows:
            rows.sort(key=lambda x: x[0])
            idx, vals = zip(*rows)
            out[sid] = pd.Series(vals, index=pd.DatetimeIndex(idx))
    return out


def fetch_all_series() -> dict:
    """Fetch all series covering 2000–present in two API calls per batch."""
    current_year = date.today().year
    series_ids = list(SERIES.values())
    id_to_key = {v: k for k, v in SERIES.items()}

    # BLS API max is 20 years per request. Fetch in two windows:
    # 2000-2019 and 2020-present (≤20 years each)
    windows = [
        (2000, 2019),
        (2020, current_year),
    ]

    combined: dict = {}  # series_id → concatenated pd.Series

    for start, end in windows:
        # Fetch in batches of 50 (API max with key)
        for i in range(0, len(series_ids), 50):
            batch = series_ids[i : i + 50]
            print(f"  Fetching {len(batch)} series [{start}-{end}]...")
            batch_result = fetch_bls_batch(batch, start, end)
            for sid, s in batch_result.items():
                if sid in combined:
                    combined[sid] = pd.concat([combined[sid], s]).sort_index()
                else:
                    combined[sid] = s
            if i + 50 < len(series_ids):
                time.sleep(0.5)
        time.sleep(0.5)

    # Deduplicate index (keep last in case of overlap)
    result = {}
    for sid, s in combined.items():
        key = id_to_key.get(sid, sid)
        deduped = s[~s.index.duplicated(keep="last")].sort_index()
        result[key] = deduped

    return result


# ── Compute YoY ───────────────────────────────────────────────────────────────
def compute_yoy(s: pd.Series) -> pd.Series:
    """(current / lag(12 months) - 1) * 100
    Resample to uniform monthly freq first so shift(12) always means
    exactly 12 calendar months, even if source data has gaps.
    """
    s = s.resample("MS").last()
    return (s / s.shift(12) - 1) * 100


# ── Build Plotly chart JSON ───────────────────────────────────────────────────
def build_chart_json(yoy: dict) -> str:
    """Returns Plotly figure JSON for 4 stacked subplots."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # Colors
    STEEL   = "#4C72B0"
    NAVY    = "#003399"
    RED     = "#C44E52"
    LT_BLUE = "#64B5CD"
    GRAY    = "#888888"
    PINK    = "#CC79A7"
    LT_GRAY = "#AAAAAA"

    subplot_titles = [
        "CPI & Core CPI",
        "Core CPI Breakdown",
        "Shelter Decomposition",
        "Food & Energy",
    ]

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=subplot_titles,
    )

    # Panel 1: CPI + Core CPI
    _add_line(fig, yoy, "cpi",       "CPI",       STEEL,   1)
    _add_line(fig, yoy, "core_cpi",  "Core CPI",  NAVY,    1)

    # Panel 2: Core CPI + Core Services + Core Goods
    _add_line(fig, yoy, "core_cpi",      "Core CPI",      NAVY,    2)
    _add_line(fig, yoy, "core_services", "Core Services", RED,     2)
    _add_line(fig, yoy, "core_goods",    "Core Goods",    LT_BLUE, 2)

    # Panel 3: CPI + Shelter + CPI ex-Shelter
    _add_line(fig, yoy, "cpi",           "CPI",           STEEL,   3)
    _add_line(fig, yoy, "shelter",       "Shelter",       RED,     3)
    _add_line(fig, yoy, "cpi_ex_shelter","CPI ex-Shelter",GRAY,    3)

    # Panel 4: CPI + Food + Energy
    _add_line(fig, yoy, "cpi",    "CPI",    STEEL,   4)
    _add_line(fig, yoy, "food",   "Food",   PINK,    4)
    _add_line(fig, yoy, "energy", "Energy", LT_GRAY, 4)

    # Recession shading on all panels
    for row in range(1, 5):
        for rec_start, rec_end in RECESSIONS:
            fig.add_vrect(
                x0=rec_start, x1=rec_end,
                fillcolor="rgba(180,180,180,0.20)",
                line_width=0,
                row=row, col=1,
            )

    # Zero line on all panels
    for row in range(1, 5):
        fig.add_hline(y=0, line_dash="dot", line_color="rgba(0,0,0,0.25)", line_width=1, row=row, col=1)

    # Latest-value annotations
    _add_latest_annotations(fig, yoy, [
        (1, ["cpi", "core_cpi"], [STEEL, NAVY]),
        (2, ["core_cpi", "core_services", "core_goods"], [NAVY, RED, LT_BLUE]),
        (3, ["cpi", "shelter", "cpi_ex_shelter"], [STEEL, RED, GRAY]),
        (4, ["cpi", "food", "energy"], [STEEL, PINK, LT_GRAY]),
    ])

    fig.update_layout(
        height=900,
        margin=dict(l=55, r=120, t=30, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend_tracegroupgap=0,
        showlegend=True,
        legend=dict(
            orientation="v",
            x=1.01, y=1,
            xanchor="left",
            font=dict(size=11),
        ),
        font=dict(family="DM Sans, sans-serif", size=12),
        hovermode="x unified",
    )

    # Y-axis ranges
    for row in range(1, 5):
        fig.update_yaxes(range=[-4, 14], row=row, col=1, ticksuffix="%", gridcolor="rgba(0,0,0,0.06)")

    # X-axis
    fig.update_xaxes(
        range=["2000-01-01", None],
        showgrid=False,
        row=4, col=1,
    )

    # Source note as annotation
    fig.add_annotation(
        text="Source: Bureau of Labor Statistics (BLS). Seasonally adjusted. Shaded = NBER recessions.",
        xref="paper", yref="paper",
        x=0, y=-0.045,
        showarrow=False,
        font=dict(size=10, color="#666666"),
        align="left",
        xanchor="left",
    )

    return fig.to_json()


def _add_line(fig, yoy: dict, key: str, name: str, color: str, row: int):
    import plotly.graph_objects as go
    s = yoy.get(key)
    if s is None or len(s) == 0:
        return
    # Only show legend on first panel
    showlegend = (row == 1) or (key not in ["cpi", "core_cpi"])
    # Actually show legend for each panel but group by key
    fig.add_trace(
        go.Scatter(
            x=s.index,
            y=s.values.round(2),
            name=name,
            line=dict(color=color, width=1.8),
            showlegend=True,
            legendgroup=key,
            legendgrouptitle_text=None,
        ),
        row=row, col=1,
    )


def _add_latest_annotations(fig, yoy: dict, panels: list):
    """Add right-edge value labels to each panel."""
    for row, keys, colors in panels:
        for key, color in zip(keys, colors):
            s = yoy.get(key)
            if s is None or len(s) == 0:
                continue
            s_clean = s.dropna()
            if len(s_clean) == 0:
                continue
            val = s_clean.iloc[-1]
            dt  = s_clean.index[-1]
            fig.add_annotation(
                x=dt,
                y=val,
                text=f"<b>{val:.1f}%</b>",
                showarrow=False,
                xanchor="left",
                xshift=6,
                font=dict(size=10, color=color),
                row=row, col=1,
            )


# ── Build HTML tables ─────────────────────────────────────────────────────────
def _bar_html(value: float, max_abs: float, pos_color: str = "#4CAF50", neg_color: str = "#F44336") -> str:
    """Inline bar proportional to value, max width 80px."""
    if value is None or np.isnan(value):
        return ""
    width = min(abs(value) / max(max_abs, 0.01) * 80, 80)
    color = pos_color if value >= 0 else neg_color
    return (
        f'<span style="display:inline-block;width:{width:.1f}px;height:10px;'
        f'background:{color};border-radius:2px;vertical-align:middle;"></span>'
    )


def _weight_bar(weight: float) -> str:
    """Dark bar for weight column, max 80px at 50%."""
    width = min(weight / 50 * 80, 80)
    return (
        f'<span style="display:inline-block;width:{width:.1f}px;height:10px;'
        f'background:#1a3a2f;border-radius:2px;vertical-align:middle;opacity:0.7;"></span>'
    )


def build_table_html(title: str, rows: list, yoy: dict, max_abs: float = 10.0, max_contrib: float = 5.0) -> str:
    """
    rows: list of (label, key, indent_level)
    key = None means the row is a header/total with special styling
    """
    rows_html = []
    for label, key, indent in rows:
        if key is None:
            # Section divider / header row
            rows_html.append(
                f'<tr style="background:#f5f5f5;font-weight:700;font-size:0.82rem;">'
                f'<td colspan="8" style="padding:6px 10px;color:#1a3a2f;">{label}</td></tr>'
            )
            continue

        s = yoy.get(key)
        val = float(s.dropna().iloc[-1]) if s is not None and len(s.dropna()) > 0 else None
        weight = WEIGHTS.get(key, 0.0)
        contrib = round(val * weight / 100, 3) if val is not None else None

        val_str    = f"{val:+.1f}%" if val is not None else "—"
        weight_str = f"{weight:.1f}%"
        contr_str  = f"{contrib:+.1f}%" if contrib is not None else "—"

        bar_yoy    = _bar_html(val, max_abs) if val is not None else ""
        bar_weight = _weight_bar(weight)
        bar_contrib = _bar_html(contrib, max_contrib) if contrib is not None else ""

        indent_px = indent * 16
        color = "#4CAF50" if (val is not None and val >= 0) else "#F44336"
        val_color = color if val is not None else "#999"

        rows_html.append(
            f'<tr style="border-bottom:1px solid #f0f0f0;">'
            f'<td style="padding:5px 10px 5px {10+indent_px}px;font-size:0.82rem;color:#333;">{label}</td>'
            f'<td style="padding:5px 6px;text-align:right;font-size:0.82rem;font-weight:600;color:{val_color};white-space:nowrap;">{val_str}</td>'
            f'<td style="padding:5px 6px;text-align:left;">{bar_yoy}</td>'
            f'<td style="padding:5px 6px;text-align:right;font-size:0.82rem;color:#555;white-space:nowrap;">{weight_str}</td>'
            f'<td style="padding:5px 6px;text-align:left;">{bar_weight}</td>'
            f'<td style="padding:5px 6px;text-align:right;font-size:0.82rem;font-weight:600;color:{val_color};white-space:nowrap;">{contr_str}</td>'
            f'<td style="padding:5px 6px;text-align:left;">{bar_contrib}</td>'
            f'</tr>'
        )

    rows_joined = "\n".join(rows_html)
    return f"""
<div class="table-block">
  <div class="table-title">{title}</div>
  <table>
    <thead>
      <tr>
        <th style="text-align:left;width:30%">Category</th>
        <th style="text-align:right;width:8%">YoY%</th>
        <th style="width:10%"></th>
        <th style="text-align:right;width:8%">Weight</th>
        <th style="width:10%"></th>
        <th style="text-align:right;width:10%">Contrib.</th>
        <th style="width:10%"></th>
      </tr>
    </thead>
    <tbody>
{rows_joined}
    </tbody>
  </table>
</div>"""


def build_all_tables(yoy: dict) -> str:
    """Build all 3 component tables."""

    # Compute max abs YoY for bar scaling (across all displayed series)
    all_vals = []
    for key in yoy:
        s = yoy[key].dropna()
        if len(s) > 0:
            all_vals.append(abs(float(s.iloc[-1])))
    max_abs = max(all_vals) if all_vals else 10.0

    # Also get the latest CPI date for display
    cpi_s = yoy.get("cpi", pd.Series()).dropna()
    latest_date = cpi_s.index[-1].strftime("%B %Y") if len(cpi_s) > 0 else ""

    # Table 1: Major groups
    t1_rows = [
        ("Total CPI",          "cpi",          0),
        ("Housing",            "housing",       1),
        ("Food & Beverages",   "food_bev",      1),
        ("Transportation",     "transportation",1),
        ("Medical Care",       "medical",       1),
        ("Recreation",         "recreation",    1),
        ("Education & Comm.",  "edu_comm",      1),
        ("Apparel",            "apparel",       1),
        ("Other",              "other",         1),
    ]

    # Table 2: Food / Energy / Core
    t2_rows = [
        ("Total CPI",              "cpi",             0),
        ("Food",                   "food",             1),
        ("  Food at Home",         "food_home",        2),
        ("  Food Away from Home",  "food_away",        2),
        ("Energy",                 "energy",           1),
        ("  Energy Commodities",   "energy_goods",     2),
        ("  Energy Services",      "energy_services",  2),
        ("Core CPI",               "core_cpi",         1),
        ("  Core Goods",           "core_goods",       2),
        ("  Core Services",        "core_services",    2),
    ]

    # Table 3: Shelter split
    t3_rows = [
        ("Total CPI",       "cpi",           0),
        ("Shelter",         "shelter",       1),
        ("CPI ex-Shelter",  "cpi_ex_shelter",1),
    ]

    # Max contribution for bar scaling: largest absolute contrib across all displayed rows
    all_keys = [k for _, k, _ in t1_rows + t2_rows + t3_rows if k is not None]
    contribs = []
    for k in all_keys:
        s = yoy.get(k, pd.Series()).dropna()
        if len(s) > 0:
            val = float(s.iloc[-1])
            w = WEIGHTS.get(k, 0.0)
            contribs.append(abs(val * w / 100))
    max_contrib = max(contribs) if contribs else 5.0

    t1 = build_table_html(f"Major Components — {latest_date}", t1_rows, yoy, max_abs, max_contrib)
    t2 = build_table_html(f"Food, Energy &amp; Core — {latest_date}", t2_rows, yoy, max_abs, max_contrib)
    t3 = build_table_html(f"Shelter Decomposition — {latest_date}", t3_rows, yoy, max_abs, max_contrib)

    return t1 + t2 + t3


# ── Assemble HTML ─────────────────────────────────────────────────────────────
def build_html(chart_json: str, tables_html: str, last_updated: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>U.S. Inflation Monitor</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;700&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  :root {{
    --forest: #1a3a2f;
    --forest-light: #2d5a47;
    --moss: #3d6b56;
    --sage: #7a9e8e;
    --mint: #e8f0ec;
    --cream: #faf9f7;
    --charcoal: #1a1a1a;
    --warm-gray: #6b6b6b;
    --text: #333;
    --border: #e0e0e0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--cream);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }}
  header {{
    background: var(--forest);
    color: #fff;
    padding: 20px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
  }}
  header h1 {{
    font-family: 'Fraunces', serif;
    font-size: 1.45rem;
    font-weight: 700;
    letter-spacing: -0.01em;
  }}
  header .meta {{
    font-size: 0.8rem;
    color: rgba(255,255,255,0.7);
    text-align: right;
  }}
  .container {{
    display: grid;
    grid-template-columns: 60% 40%;
    gap: 0;
    min-height: calc(100vh - 80px);
  }}
  .left-panel {{
    padding: 20px 16px 20px 24px;
    border-right: 1px solid var(--border);
    background: white;
  }}
  .right-panel {{
    padding: 16px 20px;
    background: var(--cream);
    overflow-y: auto;
  }}
  #chart-div {{
    width: 100%;
  }}
  .table-block {{
    background: white;
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 16px;
    overflow: hidden;
  }}
  .table-title {{
    background: var(--forest);
    color: white;
    padding: 8px 14px;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
  }}
  thead tr {{
    background: #f8f8f8;
    border-bottom: 2px solid var(--border);
  }}
  thead th {{
    padding: 6px 6px;
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--warm-gray);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  tbody tr:hover {{
    background: var(--mint);
  }}
  @media (max-width: 900px) {{
    .container {{
      grid-template-columns: 1fr;
    }}
    .left-panel {{
      border-right: none;
      border-bottom: 1px solid var(--border);
      padding: 16px;
    }}
    .right-panel {{
      padding: 16px;
    }}
    header {{
      padding: 16px;
    }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>🇺🇸 U.S. Inflation Monitor</h1>
    <div style="font-size:0.78rem;color:rgba(255,255,255,0.65);margin-top:3px;">
      Bureau of Labor Statistics · Consumer Price Index (Not Seasonally Adjusted, 12-month change)
    </div>
  </div>
  <div class="meta">
    Updated: {last_updated}<br>
    <a href="https://boquin.xyz" style="color:rgba(255,255,255,0.6);font-size:0.75rem;text-decoration:none;">← boquin.xyz</a>
  </div>
</header>

<div class="container">
  <div class="left-panel">
    <div id="chart-div"></div>
  </div>
  <div class="right-panel">
    {tables_html}
  </div>
</div>

<script>
var figData = {chart_json};
Plotly.newPlot('chart-div', figData.data, figData.layout, {{
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['lasso2d','select2d','toggleSpikelines'],
  displaylogo: false
}});
</script>

</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Fetching BLS CPI data...")
    raw = fetch_all_series()

    print(f"Fetched {len(raw)} series. Computing YoY...")
    yoy = {k: compute_yoy(v) for k, v in raw.items()}

    # Filter to 2000-present
    start = pd.Timestamp("2000-01-01")
    yoy = {k: v[v.index >= start] for k, v in yoy.items()}

    print("Building chart...")
    chart_json = build_chart_json(yoy)

    print("Building tables...")
    tables_html = build_all_tables(yoy)

    last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(chart_json, tables_html, last_updated)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE}")

    # Quick sanity check
    cpi_s = yoy.get("cpi", pd.Series()).dropna()
    core_s = yoy.get("core_cpi", pd.Series()).dropna()
    shelter_s = yoy.get("shelter", pd.Series()).dropna()
    if len(cpi_s) > 0:
        print(f"Latest CPI YoY:     {cpi_s.iloc[-1]:.2f}% ({cpi_s.index[-1].strftime('%Y-%m')})")
    if len(core_s) > 0:
        print(f"Latest Core CPI:    {core_s.iloc[-1]:.2f}%")
    if len(shelter_s) > 0:
        print(f"Latest Shelter CPI: {shelter_s.iloc[-1]:.2f}%")


if __name__ == "__main__":
    main()
