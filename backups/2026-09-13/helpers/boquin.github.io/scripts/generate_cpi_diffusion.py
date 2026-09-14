"""
CPI Diffusion Indices
Dynamically discovers every U.S. city average CPI sub-item from BLS flat files,
fetches index levels back to 2000, computes YoY % changes, and builds:
  broad_di  — % of items with positive YoY inflation
  accel_di  — % of items where YoY is rising vs prior month

Run from repo root:
    BLS_API_KEY=xxx python3 scripts/generate_cpi_diffusion.py
"""
import io
import os
import sys
import time
import requests
import numpy as np
import pandas as pd
from datetime import date, datetime
from pathlib import Path

BLS_API_KEY = os.environ.get("BLS_API_KEY")
if not BLS_API_KEY:
    raise EnvironmentError("BLS_API_KEY environment variable is not set.")

OUTPUT_FILE = Path(__file__).parent.parent / "cpi_diffusion.html"

RECESSIONS = [
    ("2001-03-01", "2001-11-30"),
    ("2007-12-01", "2009-06-30"),
    ("2020-02-01", "2020-04-30"),
]


# ── Step 1: Discover all CPI series ──────────────────────────────────────────

def get_cpi_series_list() -> pd.DataFrame:
    """Download BLS flat files and return all U.S. city average NSA monthly CPI series."""
    print("Downloading BLS CPI series catalog...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0; +https://boquin.xyz)"}
    r_series = requests.get(
        "https://download.bls.gov/pub/time.series/cu/cu.series", timeout=60, headers=headers
    )
    r_series.raise_for_status()
    series_df = pd.read_csv(io.StringIO(r_series.text), sep="\t", dtype=str)
    series_df.columns = series_df.columns.str.strip()
    for col in series_df.select_dtypes("object").columns:
        series_df[col] = series_df[col].str.strip()

    r_item = requests.get(
        "https://download.bls.gov/pub/time.series/cu/cu.item", timeout=30, headers=headers
    )
    r_item.raise_for_status()
    item_df = pd.read_csv(io.StringIO(r_item.text), sep="\t", dtype=str)
    item_df.columns = item_df.columns.str.strip()
    for col in item_df.select_dtypes("object").columns:
        item_df[col] = item_df[col].str.strip()

    # U.S. city average, Not Seasonally Adjusted, monthly
    mask = (
        (series_df["area_code"] == "0000")
        & (series_df["seasonal"] == "U")
        & (series_df["periodicity_code"] == "R")
    )
    filtered = series_df[mask].copy()

    # Only keep series with data starting by 2010 so we have ≥15 years
    filtered["begin_year"] = pd.to_numeric(filtered["begin_year"], errors="coerce")
    filtered = filtered[filtered["begin_year"] <= 2010].copy()

    filtered = filtered.merge(
        item_df[["item_code", "item_name"]], on="item_code", how="left"
    )

    print(f"  → {len(filtered)} U.S. city average NSA monthly series (begin ≤ 2010)")
    return filtered[["series_id", "item_code", "item_name"]].reset_index(drop=True)


# ── Step 2: Batch fetch ───────────────────────────────────────────────────────

def _fetch_bls_batch(series_ids: list, start_year: int, end_year: int) -> dict:
    payload = {
        "seriesid":        series_ids,
        "startyear":       str(start_year),
        "endyear":         str(end_year),
        "registrationkey": BLS_API_KEY,
    }
    r = requests.post(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=90,
    )
    r.raise_for_status()
    result = r.json()
    if result.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API: {result.get('message', [])}")

    out = {}
    for series in result.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        rows = []
        for obs in series.get("data", []):
            try:
                if not obs["period"].startswith("M"):
                    continue
                rows.append(
                    (pd.Timestamp(int(obs["year"]), int(obs["period"][1:]), 1), float(obs["value"]))
                )
            except (ValueError, KeyError):
                continue
        if rows:
            rows.sort()
            idx, vals = zip(*rows)
            out[sid] = pd.Series(vals, index=pd.DatetimeIndex(idx))
    return out


def fetch_all(series_ids: list) -> dict:
    """Two-window fetch (2000-2019, 2020-present) in batches of 50."""
    current_year = date.today().year
    windows = [(2000, 2019), (2020, current_year)]
    combined: dict = {}
    total_batches = (-(-len(series_ids) // 50)) * len(windows)
    batch_num = 0

    for start, end in windows:
        for i in range(0, len(series_ids), 50):
            batch = series_ids[i : i + 50]
            batch_num += 1
            print(f"  [{start}-{end}] batch {batch_num}/{total_batches}: {len(batch)} series...", end=" ")
            try:
                data = _fetch_bls_batch(batch, start, end)
                for sid, s in data.items():
                    if sid in combined:
                        combined[sid] = pd.concat([combined[sid], s]).sort_index()
                    else:
                        combined[sid] = s
                print(f"ok ({len(data)} returned)")
            except Exception as e:
                print(f"WARN: {e}")
            time.sleep(0.5)
        time.sleep(0.5)

    # Deduplicate overlapping window months
    return {
        sid: s[~s.index.duplicated(keep="last")].sort_index()
        for sid, s in combined.items()
    }


# ── Step 3: Quality filter ────────────────────────────────────────────────────

def quality_filter(
    raw: dict,
    min_years: int = 10,
    max_missing_pct: float = 0.20,
    recency_months: int = 6,
) -> dict:
    cutoff = pd.Timestamp.now() - pd.DateOffset(months=recency_months)
    keep = {}
    for sid, s in raw.items():
        s = s.resample("MS").last()
        clean = s.dropna()
        if len(clean) < min_years * 12:
            continue
        if clean.index[-1] < cutoff:
            continue
        full_range = pd.date_range(s.index[0], s.index[-1], freq="MS")
        if len(full_range) == 0:
            continue
        if 1 - len(clean) / len(full_range) > max_missing_pct:
            continue
        keep[sid] = s
    print(f"Quality filter: {len(raw)} → {len(keep)} series retained")
    return keep


# ── Step 4: Change calculations + Diffusion ──────────────────────────────────

def compute_yoy(s: pd.Series) -> pd.Series:
    s = s.resample("MS").last()
    return (s / s.shift(12) - 1) * 100


def compute_mom(s: pd.Series) -> pd.Series:
    s = s.resample("MS").last()
    return (s / s.shift(1) - 1) * 100


def build_diffusion(df: pd.DataFrame) -> pd.DataFrame:
    n = df.notna().sum(axis=1).replace(0, np.nan)
    broad_raw = (df > 0).sum(axis=1) / n * 100
    accel_raw = (df > df.shift(1)).sum(axis=1) / n * 100
    return pd.DataFrame({
        "broad_raw": broad_raw,
        "accel_raw": accel_raw,
        "broad_3m":  broad_raw.rolling(3).mean(),
        "accel_3m":  accel_raw.rolling(3).mean(),
    })


# ── Step 5: Bucket distribution ───────────────────────────────────────────────

BUCKET_COLORS = [
    "#6A1B9A",  # purple  — deflation / very cold
    "#1565C0",  # dark blue
    "#42A5F5",  # light blue
    "#66BB6A",  # green
    "#FFA726",  # orange
    "#EF5350",  # red
    "#8B0000",  # dark red — very hot
]

BUCKETS_YOY = [
    ("<0%",    float("-inf"), 0),
    ("0–1%",   0,  1),
    ("1–2%",   1,  2),
    ("2–3%",   2,  3),
    ("3–4%",   3,  4),
    ("4–6%",   4,  6),
    ("≥6%",    6,  float("inf")),
]

BUCKETS_MOM = [
    ("<0%",      float("-inf"), 0),
    ("0–0.2%",   0,    0.2),
    ("0.2–0.4%", 0.2,  0.4),
    ("0.4–0.6%", 0.4,  0.6),
    ("0.6–1%",   0.6,  1.0),
    ("≥1%",      1.0,  float("inf")),
]

# MoM only has 6 buckets — drop the darkest red so colors still match 1-to-1
BUCKET_COLORS_MOM = BUCKET_COLORS[:6]


def build_bucket_df(df: pd.DataFrame, buckets: list) -> pd.DataFrame:
    """% of items in each bucket per month. Columns = bucket labels."""
    n = df.notna().sum(axis=1).replace(0, np.nan)
    out = {}
    for label, lo, hi in buckets:
        if lo == float("-inf"):
            mask = df < hi
        elif hi == float("inf"):
            mask = df >= lo
        else:
            mask = (df >= lo) & (df < hi)
        out[label] = mask.sum(axis=1) / n * 100
    return pd.DataFrame(out)


# ── Step 6: Chart ─────────────────────────────────────────────────────────────

def build_chart_json(
    di: pd.DataFrame,
    bucket_df: pd.DataFrame,
    buckets: list,
    bucket_colors: list,
    n_series: int,
    measure: str = "YoY",
) -> str:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    BLUE  = "#0057A8"
    RED   = "#C8102E"
    BLUE_FAINT = "rgba(0,87,168,0.25)"
    RED_FAINT  = "rgba(200,16,46,0.25)"
    CLIP_START = "2001-01-01"

    diff_panels = [
        (1, "broad_raw", "broad_3m", BLUE, BLUE_FAINT,
         f"CPI Breadth Diffusion — % of {n_series} Items with Positive {measure}"),
        (2, "accel_raw", "accel_3m", RED,  RED_FAINT,
         f"CPI Acceleration Diffusion — % of {n_series} Items Where {measure} Is Rising vs Prior Month"),
    ]

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.30, 0.30, 0.40],
        subplot_titles=[
            p[5] for p in diff_panels
        ] + [f"{measure} Distribution Across {n_series} CPI Items (% in Each Bucket)"],
    )

    # ── Panels 1 & 2: diffusion lines ────────────────────────────────────────
    for row, raw_col, smooth_col, color, faint, _ in diff_panels:
        s_raw    = di[raw_col].dropna()
        s_smooth = di[smooth_col].dropna()
        s_raw    = s_raw[s_raw.index >= CLIP_START]
        s_smooth = s_smooth[s_smooth.index >= CLIP_START]

        fig.add_trace(go.Scatter(
            x=s_raw.index, y=s_raw.values.round(1),
            name="Monthly",
            line=dict(color=faint, width=1),
            showlegend=(row == 1),
            legendgroup="raw",
            legendgrouptitle_text=None,
        ), row=row, col=1)

        fig.add_trace(go.Scatter(
            x=s_smooth.index, y=s_smooth.values.round(1),
            name="3-Month MA",
            line=dict(color=color, width=2.2),
            showlegend=(row == 1),
            legendgroup="smooth",
        ), row=row, col=1)

        fig.add_hline(
            y=50, line_dash="dash",
            line_color="rgba(0,0,0,0.28)", line_width=1,
            row=row, col=1,
        )

        for rec_start, rec_end in RECESSIONS:
            fig.add_vrect(
                x0=rec_start, x1=rec_end,
                fillcolor="rgba(180,180,180,0.18)",
                line_width=0, row=row, col=1,
            )

        if len(s_smooth) > 0:
            val = float(s_smooth.iloc[-1])
            fig.add_annotation(
                x=s_smooth.index[-1], y=val,
                text=f"<b>{val:.1f}%</b>",
                showarrow=False, xanchor="left", xshift=6,
                font=dict(size=11, color=color),
                row=row, col=1,
            )

    # ── Panel 3: stacked bar — bucket distribution ────────────────────────────
    bdf = bucket_df[bucket_df.index >= CLIP_START]
    for (label, _, _), color in zip(buckets, bucket_colors):
        col_data = bdf[label].round(1)
        fig.add_trace(go.Bar(
            x=bdf.index,
            y=col_data,
            name=label,
            marker_color=color,
            legendgroup=f"bucket_{label}",
            showlegend=True,
        ), row=3, col=1)

    for rec_start, rec_end in RECESSIONS:
        fig.add_vrect(
            x0=rec_start, x1=rec_end,
            fillcolor="rgba(180,180,180,0.18)",
            line_width=0, row=3, col=1,
        )

    fig.update_layout(
        height=1000,
        barmode="stack",
        margin=dict(l=55, r=20, t=55, b=60),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="DM Sans, sans-serif", size=12),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            x=0.01, y=-0.06,
            traceorder="normal",
        ),
        bargap=0,
    )

    for row in range(1, 3):
        fig.update_yaxes(
            range=[0, 100], row=row, col=1,
            ticksuffix="%",
            gridcolor="rgba(0,0,0,0.06)",
            dtick=25,
        )

    fig.update_yaxes(
        range=[0, 100], row=3, col=1,
        ticksuffix="%",
        gridcolor="rgba(0,0,0,0.06)",
        dtick=25,
        title_text="% of items",
        title_font=dict(size=10),
    )

    fig.update_xaxes(showgrid=False, row=3, col=1)

    fig.add_annotation(
        text=(
            f"Source: BLS CPI-U, U.S. City Average, NSA. {n_series} series after quality filter "
            "(begin ≤2010, ≥10yr history, ≤20% gaps). Shaded = NBER recessions."
        ),
        xref="paper", yref="paper", x=0, y=-0.07,
        showarrow=False,
        font=dict(size=10, color="#666666"),
        align="left", xanchor="left",
    )

    return fig.to_json()


# ── Step 7: HTML ──────────────────────────────────────────────────────────────

def build_html(yoy_chart_json: str, mom_chart_json: str, n_series: int, last_updated: str) -> str:
    PLOTLY_CONFIG = """{
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['lasso2d','select2d','toggleSpikelines'],
  displaylogo: false
}"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CPI Diffusion Indices</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;700&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  :root {{
    --forest: #1a3a2f;
    --forest-light: #2d5a47;
    --cream: #faf9f7;
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
  header .sub {{
    font-size: 0.78rem;
    color: rgba(255,255,255,0.65);
    margin-top: 3px;
  }}
  header .meta {{
    font-size: 0.8rem;
    color: rgba(255,255,255,0.7);
    text-align: right;
  }}
  .tab-bar {{
    background: var(--forest-light);
    display: flex;
    gap: 0;
    padding: 0 24px;
  }}
  .tab-btn {{
    padding: 10px 24px;
    border: none;
    background: transparent;
    color: rgba(255,255,255,0.65);
    font-family: 'DM Sans', sans-serif;
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
    border-bottom: 3px solid transparent;
    transition: color 0.15s, border-color 0.15s;
  }}
  .tab-btn.active {{
    color: #fff;
    border-bottom-color: #fff;
  }}
  .tab-btn:hover:not(.active) {{
    color: rgba(255,255,255,0.9);
  }}
  .chart-wrap {{
    background: white;
    padding: 20px 24px 24px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
  @media (max-width: 700px) {{
    header {{ padding: 16px; }}
    .chart-wrap {{ padding: 12px; }}
    .tab-bar {{ padding: 0 12px; }}
  }}
</style>
</head>
<body>
<header>
  <div>
    <h1>📊 CPI Diffusion Indices</h1>
    <div class="sub">{n_series} BLS CPI-U sub-items · U.S. City Average · Not Seasonally Adjusted</div>
  </div>
  <div class="meta">
    Updated: {last_updated}<br>
    <a href="https://boquin.xyz" style="color:rgba(255,255,255,0.6);font-size:0.75rem;text-decoration:none;">← boquin.xyz</a>
  </div>
</header>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('yoy', this)">Year-over-Year</button>
  <button class="tab-btn"        onclick="switchTab('mom', this)">Month-over-Month</button>
</div>

<div class="chart-wrap">
  <div id="tab-yoy" class="tab-panel active">
    <div id="chart-yoy"></div>
  </div>
  <div id="tab-mom" class="tab-panel">
    <div id="chart-mom"></div>
  </div>
</div>

<script>
var yoyData = {yoy_chart_json};
var momData = {mom_chart_json};
var rendered = {{ yoy: false, mom: false }};

function switchTab(tab, btn) {{
  document.querySelectorAll('.tab-panel').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  btn.classList.add('active');
  if (!rendered[tab]) {{
    var data = tab === 'yoy' ? yoyData : momData;
    Plotly.newPlot('chart-' + tab, data.data, data.layout, {PLOTLY_CONFIG});
    rendered[tab] = true;
  }} else {{
    Plotly.Plots.resize('chart-' + tab);
  }}
}}

// Render YoY on load
Plotly.newPlot('chart-yoy', yoyData.data, yoyData.layout, {PLOTLY_CONFIG});
rendered.yoy = true;
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # 1. Discover
    catalog = get_cpi_series_list()
    series_ids = catalog["series_id"].tolist()

    # 2. Fetch
    print(f"\nFetching {len(series_ids)} series from BLS API (2 windows × batches of 50)...")
    raw = fetch_all(series_ids)
    print(f"  → {len(raw)} series returned data")

    # 3. Quality filter
    print("\nApplying quality filter...")
    clean = quality_filter(raw)

    # 4. YoY + MoM matrices
    n_series = len(clean)
    yoy_df = pd.DataFrame({sid: compute_yoy(s) for sid, s in clean.items()})
    mom_df = pd.DataFrame({sid: compute_mom(s) for sid, s in clean.items()})
    yoy_df = yoy_df[yoy_df.index >= "2001-01-01"]
    mom_df = mom_df[mom_df.index >= "2001-01-01"]
    print(f"YoY matrix: {yoy_df.shape[0]} months × {yoy_df.shape[1]} series")
    print(f"MoM matrix: {mom_df.shape[0]} months × {mom_df.shape[1]} series")

    # 5. Diffusion + buckets
    print("Computing diffusion indices...")
    di_yoy    = build_diffusion(yoy_df)
    di_mom    = build_diffusion(mom_df)
    bkt_yoy   = build_bucket_df(yoy_df, BUCKETS_YOY)
    bkt_mom   = build_bucket_df(mom_df, BUCKETS_MOM)

    broad = di_yoy["broad_3m"].dropna()
    if len(broad):
        print(f"YoY broad_di (3m MA):  {broad.iloc[-1]:.1f}%  ({broad.index[-1].strftime('%Y-%m')})")
        peak = di_yoy.loc["2021-01-01":"2022-12-31", "broad_3m"].dropna()
        if len(peak):
            print(f"YoY peak (2021-22):    {peak.max():.1f}%")
    broad_m = di_mom["broad_3m"].dropna()
    if len(broad_m):
        print(f"MoM broad_di (3m MA):  {broad_m.iloc[-1]:.1f}%")

    # 6. Charts + HTML
    print("\nBuilding charts...")
    yoy_chart = build_chart_json(di_yoy, bkt_yoy, BUCKETS_YOY, BUCKET_COLORS, n_series, "YoY")
    mom_chart = build_chart_json(di_mom, bkt_mom, BUCKETS_MOM, BUCKET_COLORS_MOM, n_series, "MoM")
    last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(yoy_chart, mom_chart, n_series, last_updated)

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
