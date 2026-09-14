"""
Weekly Petroleum Stocks by PAD District — EIA-Style Multi-Panel Chart
======================================================================
Fetches EIA Weekly Petroleum Status Report stocks for crude oil, total
motor gasoline, and distillate fuel oil across U.S. total and PAD
Districts 1-5, then generates one 3x2 panel PNG per product:
  - Grey 5-year seasonal range band
  - Blue weekly line
  - BiMonthly x-axis (MonYY format)
  - White background, horizontal grid lines only

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_petroleum_stocks_weekly.py
Output: reports/petroleum-stocks/Crude_Stocks_Weekly_YYYY_MM_DD.png
        reports/petroleum-stocks/Gasoline_Stocks_Weekly_YYYY_MM_DD.png
        reports/petroleum-stocks/Distillate_Stocks_Weekly_YYYY_MM_DD.png
        reports/petroleum-stocks/index.html
"""

import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from datetime import date

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE  = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
OUTPUT_DIR    = os.path.join(os.path.dirname(__file__), "..", "reports", "petroleum-stocks")
WINDOW_DAYS   = 365
HISTORY_YEARS = 7

PANELS = [
    ("NUS", "U.S. Total"),
    ("R10", "PADD 1"),
    ("R20", "PADD 2"),
    ("R30", "PADD 3"),
    ("R40", "PADD 4"),
    ("R50", "PADD 5"),
]

# processes: list tried in order; first non-empty result wins.
# Crude uses SAX (ex-SPR) first — critical for PADD 3 Gulf Coast.
# Petroleum products have no SPR, so SAE only.
PRODUCTS = [
    {
        "id":        "crude",
        "code":      "EPC0",
        "label":     "Crude Oil",
        "tab":       "Crude Oil",
        "figure":    "Crude Oil Stocks by PAD District",
        "processes": ["SAX", "SAE"],
    },
    {
        "id":        "gasoline",
        "code":      "EPM0",
        "label":     "Total Motor Gasoline",
        "tab":       "Motor Gasoline",
        "figure":    "Motor Gasoline Stocks by PAD District",
        "processes": ["SAE"],
    },
    {
        "id":        "distillate",
        "code":      "EPD0",
        "label":     "Distillate Fuel Oil",
        "tab":       "Distillate Fuel Oil",
        "figure":    "Distillate Fuel Oil Stocks by PAD District",
        "processes": ["SAE"],
    },
]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def get_api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        print(
            "WARNING: EIA_API_KEY not set. Using DEMO_KEY (heavily rate-limited).\n"
            "Register at https://www.eia.gov/opendata/register.php"
        )
        return "DEMO_KEY"
    return key


def _query_one(api_key: str, product: str, duoarea: str, process: str) -> pd.Series:
    weeks = HISTORY_YEARS * 53 + 10
    qs = (
        f"api_key={api_key}"
        f"&frequency=weekly"
        f"&data[0]=value"
        f"&facets[product][]={product}"
        f"&facets[duoarea][]={duoarea}"
        f"&facets[process][]={process}"
        f"&sort[0][column]=period"
        f"&sort[0][direction]=desc"
        f"&length={weeks}"
    )
    try:
        resp = requests.get(f"{EIA_API_BASE}?{qs}", timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  WARNING: {product}/{duoarea}/{process} failed — {e}")
        return pd.Series(dtype=float)

    rows = resp.json().get("response", {}).get("data", [])
    records = [
        {"date": pd.to_datetime(r["period"]), "value": float(r["value"]) / 1_000.0}
        for r in rows
        if r.get("duoarea") == duoarea and r.get("value") not in (None, "")
    ]
    if not records:
        return pd.Series(dtype=float)
    return (
        pd.DataFrame(records)
        .drop_duplicates("date")
        .set_index("date")["value"]
        .sort_index()
    )


def fetch_area(api_key: str, product: str, duoarea: str, processes: list) -> pd.Series:
    for proc in processes:
        s = _query_one(api_key, product, duoarea, proc)
        if not s.empty:
            return s
    print(f"    WARNING: no data for {duoarea}")
    return pd.Series(dtype=float)


def fetch_all_areas(api_key: str, product: str, processes: list) -> dict[str, pd.Series]:
    result = {}
    for da, title in PANELS:
        print(f"  Fetching {da} ({title})...")
        s = fetch_area(api_key, product, da, processes)
        if not s.empty:
            print(f"    {da}: {len(s)} weeks  "
                  f"{s.index[0].date()} – {s.index[-1].date()}  "
                  f"range [{s.min():.1f}, {s.max():.1f}] MMBbl")
            result[da] = s
    return result


def check_freshness(series_dict: dict) -> None:
    latest = max(s.index.max() for s in series_dict.values())
    age = (pd.Timestamp(date.today()) - latest).days
    if age > 14:
        print(
            f"EIA update not yet available. Most recent: {latest.date()} "
            f"({age} days ago). Check back after Wednesday 10:30 AM ET."
        )
        sys.exit(0)
    print(f"  Most recent EIA data: week ending {latest.date()}")


# ---------------------------------------------------------------------------
# Seasonal band
# ---------------------------------------------------------------------------
def seasonal_band(s: pd.Series, window: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    end_date   = window.index.min() - pd.Timedelta(days=1)
    start_date = end_date - pd.DateOffset(years=5)
    hist_data  = s[start_date:end_date].copy()

    df_hist        = hist_data.to_frame(name="value")
    df_hist["doy"] = df_hist.index.dayofyear

    lo_vals, hi_vals = [], []
    for dt in window.index:
        doy    = dt.dayofyear
        mask   = (df_hist["doy"] >= doy - 7) & (df_hist["doy"] <= doy + 7)
        bucket = df_hist.loc[mask, "value"]
        if len(bucket) >= 3:
            lo_vals.append(bucket.min())
            hi_vals.append(bucket.max())
        else:
            lo_vals.append(np.nan)
            hi_vals.append(np.nan)

    lo = pd.Series(lo_vals).interpolate(limit_direction="both").values
    hi = pd.Series(hi_vals).interpolate(limit_direction="both").values
    return lo, hi


# ---------------------------------------------------------------------------
# Single panel
# ---------------------------------------------------------------------------
def draw_panel(ax, s: pd.Series, title: str) -> None:
    cutoff  = s.index.max() - pd.Timedelta(days=WINDOW_DAYS)
    current = s[s.index >= cutoff]
    lo, hi  = seasonal_band(s, current)

    ax.fill_between(
        current.index, lo, hi,
        color="#E0E0E0", alpha=1.0, linewidth=0, zorder=2,
    )
    ax.plot(current.index, current.values,
            color="#2196F3", linewidth=1.2, zorder=4)

    ax.set_facecolor("white")
    ax.set_xlim(current.index[0], current.index[-1])

    y_min = min(np.nanmin(lo), current.min())
    y_max = max(np.nanmax(hi), current.max())
    pad   = (y_max - y_min) * 0.10
    ax.set_ylim(y_min - pad, y_max + pad * 1.5)

    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5, integer=True))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.tick_params(axis="y", labelsize=7, length=0, colors="#333")
    ax.tick_params(axis="x", labelsize=7, length=3, colors="#333")

    ax.text(0.0, 1.02, "Million Barrels", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=7, color="#333")

    ax.yaxis.grid(True, color="#cccccc", linewidth=0.5, zorder=0)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#cccccc")
    ax.spines["bottom"].set_color("#555555")

    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b%y"))

    ax.set_title(title, fontsize=8.5, color="#222", pad=4)

    legend_elements = [
        Patch(facecolor="#888", edgecolor="none", label="5-yr Range"),
        Line2D([0], [0], color="#2196F3", linewidth=1.2, label="Weekly"),
    ]
    ax.legend(handles=legend_elements, loc="lower center",
              bbox_to_anchor=(0.5, -0.32), ncol=2,
              frameon=False, fontsize=7, handlelength=1.2,
              handleheight=0.8, columnspacing=0.8)


# ---------------------------------------------------------------------------
# Full figure
# ---------------------------------------------------------------------------
def build_figure(series_dict: dict, figure_title: str) -> plt.Figure:
    fig, axes = plt.subplots(3, 2, figsize=(11, 10), facecolor="white")
    fig.patch.set_facecolor("white")

    for ax, (da, title) in zip(axes.flat, PANELS):
        if da not in series_dict:
            ax.set_visible(False)
            continue
        draw_panel(ax, series_dict[da], title)

    latest = max(s.index.max() for s in series_dict.values())
    fig.suptitle(
        f"Figure 1. {figure_title} — Last {WINDOW_DAYS} Days",
        fontsize=10, color="#222", y=1.01,
    )
    fig.text(
        0.5, -0.01,
        f"Source: EIA Weekly Petroleum Status Report  |  Week ending {latest.strftime('%B %d, %Y')}",
        ha="center", fontsize=7.5, color="#666",
    )

    plt.tight_layout(h_pad=3.5, w_pad=2.5)
    return fig


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "reports", "petroleum-stocks", "data")

def save_csvs(series_dict: dict, product_id: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    # -- raw: full history, long format (date, duoarea, value_mmbbl) ---------
    raw_rows = []
    for da, s in series_dict.items():
        for dt, val in s.items():
            raw_rows.append({"date": dt.date(), "duoarea": da, "value_mmbbl": round(val, 3)})
    raw_df = pd.DataFrame(raw_rows).sort_values(["date", "duoarea"])
    raw_path = os.path.join(DATA_DIR, f"{product_id}_raw.csv")
    raw_df.to_csv(raw_path, index=False)
    print(f"Saved: {raw_path}")

    # -- seasonal: last WINDOW_DAYS, includes lo/hi and % of range ----------
    seasonal_rows = []
    for da, s in series_dict.items():
        cutoff  = s.index.max() - pd.Timedelta(days=WINDOW_DAYS)
        current = s[s.index >= cutoff]
        lo, hi  = seasonal_band(s, current)
        for i, (dt, val) in enumerate(current.items()):
            lo_v = round(float(lo[i]), 3)
            hi_v = round(float(hi[i]), 3)
            spread = hi_v - lo_v
            pct = round((val - lo_v) / spread * 100, 1) if spread > 0 else None
            seasonal_rows.append({
                "date":         dt.date(),
                "duoarea":      da,
                "value_mmbbl":  round(val, 3),
                "seasonal_lo":  lo_v,
                "seasonal_hi":  hi_v,
                "pct_of_range": pct,
            })
    seasonal_df = pd.DataFrame(seasonal_rows).sort_values(["date", "duoarea"])
    seasonal_path = os.path.join(DATA_DIR, f"{product_id}_seasonal.csv")
    seasonal_df.to_csv(seasonal_path, index=False)
    print(f"Saved: {seasonal_path}")


# ---------------------------------------------------------------------------
# HTML wrapper (three tabs)
# ---------------------------------------------------------------------------
def generate_index_html(
    output_files: dict,
    latest_date_str: str,
    output_dir: str,
    ts: str = "",
) -> None:
    crude_file      = output_files["crude"]
    gasoline_file   = output_files["gasoline"]
    distillate_file = output_files["distillate"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Weekly Petroleum Stocks by PAD District — {latest_date_str}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#f5f5f5;font-family:Arial,sans-serif;display:flex;
         flex-direction:column;align-items:center;padding:2rem 1rem;min-height:100vh}}
    header{{text-align:center;margin-bottom:1.5rem}}
    header h1{{font-size:1.3rem;font-weight:bold;color:#222}}
    header p{{color:#555;font-size:.85rem;margin-top:.4rem}}
    .tab-bar{{display:flex;gap:8px;margin-bottom:1rem;flex-wrap:wrap;justify-content:center}}
    .tab-btn{{padding:7px 20px;border-radius:20px;cursor:pointer;
              border:2px solid #1565C0;background:white;
              font-weight:600;color:#1565C0;font-size:.88rem;
              transition:all .2s}}
    .tab-btn.active{{background:#1565C0;color:white}}
    .tab-pane{{display:none}}
    .tab-pane.active{{display:block}}
    .chart-wrapper{{width:100%;max-width:960px;background:#fff;
                   border:1px solid #ddd;border-radius:4px;padding:1rem}}
    .chart-wrapper img{{width:100%;height:auto;display:block}}
    footer{{margin-top:1.5rem;font-size:.8rem;color:#888;text-align:center}}
    footer a{{color:#2196F3;text-decoration:none}}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F6E2;&#xFE0F; Weekly Petroleum Stocks by PAD District</h1>
    <p>Last {WINDOW_DAYS} days with 5-year seasonal range &mdash; week ending {latest_date_str}</p>
  </header>
  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('crude', this)">Crude Oil</button>
    <button class="tab-btn"        onclick="switchTab('gasoline', this)">Motor Gasoline</button>
    <button class="tab-btn"        onclick="switchTab('distillate', this)">Distillate Fuel Oil</button>
  </div>
  <div id="tab-crude" class="tab-pane active">
    <div class="chart-wrapper">
      <img src="{crude_file}?v={ts}" alt="Crude Oil Stocks by PADD {latest_date_str}" />
    </div>
  </div>
  <div id="tab-gasoline" class="tab-pane">
    <div class="chart-wrapper">
      <img src="{gasoline_file}?v={ts}" alt="Motor Gasoline Stocks by PADD {latest_date_str}" />
    </div>
  </div>
  <div id="tab-distillate" class="tab-pane">
    <div class="chart-wrapper">
      <img src="{distillate_file}?v={ts}" alt="Distillate Fuel Oil Stocks by PADD {latest_date_str}" />
    </div>
  </div>
  <footer>
    Source: <a href="https://www.eia.gov/petroleum/supply/weekly/" target="_blank">EIA Weekly Petroleum Status Report</a>
    &nbsp;&bull;&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_petroleum_stocks_weekly.py" target="_blank">Source Code</a>
    &nbsp;&bull;&nbsp;
    <a href="https://boquin.xyz" target="_blank">boquin.xyz</a>
  </footer>
  <script>
    function switchTab(id, btn) {{
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.getElementById('tab-' + id).classList.add('active');
      btn.classList.add('active');
    }}
  </script>
</body>
</html>"""
    path = os.path.join(output_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    api_key   = get_api_key()
    today_str = date.today().strftime("%Y_%m_%d")
    ts        = str(int(time.time()))

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    output_files = {}
    latest_dates = []

    for product in PRODUCTS:
        print(f"\nFetching {product['label']} data from EIA API...")
        series_dict = fetch_all_areas(api_key, product["code"], product["processes"])
        if not series_dict:
            print(f"  ERROR: no data for {product['label']}, skipping.")
            continue

        check_freshness(series_dict)
        latest_dates.append(max(s.index.max() for s in series_dict.values()))

        print(f"Building chart for {product['label']}...")
        fig = build_figure(series_dict, product["figure"])

        filename = f"{product['id'].title()}_Stocks_Weekly_{today_str}.png"
        out_path = os.path.join(OUTPUT_DIR, filename)
        fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"Saved: {out_path}")

        save_csvs(series_dict, product["id"])
        output_files[product["id"]] = filename

    if len(output_files) == 3:
        latest_str = max(latest_dates).strftime("%Y-%m-%d")
        generate_index_html(output_files, latest_str, OUTPUT_DIR, ts=ts)


if __name__ == "__main__":
    main()
