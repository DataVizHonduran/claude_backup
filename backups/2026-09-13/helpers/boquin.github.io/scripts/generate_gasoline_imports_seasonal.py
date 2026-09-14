"""
Weekly U.S. Imports of Total Gasoline — EIA-Style Seasonal Chart
==================================================================
Fetches EIA Weekly Petroleum Status Report imports of total gasoline
(NUS-Z00, product EPM0, process IM0) and generates a single-panel PNG:
  - Grey 5-year seasonal range band
  - Blue weekly line
  - BiMonthly x-axis (MonYY format)
  - White background, horizontal grid lines only

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_gasoline_imports_seasonal.py
Output: reports/gasoline-imports/Gasoline_Imports_Weekly_YYYY_MM_DD.png
        reports/gasoline-imports/index.html
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
# PET.WGTIMUS2.W = "U.S. Imports of Total Gasoline" (NUS-Z00, EPM0, IM0).
# Weekly imports aren't exposed via /petroleum/move/imp/data/ (monthly/annual
# only) — the weekly series is only reachable through the seriesid shortcut.
SERIES_URL    = "https://api.eia.gov/v2/seriesid/PET.WGTIMUS2.W"
OUTPUT_DIR    = os.path.join(os.path.dirname(__file__), "..", "reports", "gasoline-imports")
WINDOW_DAYS   = 365
HISTORY_YEARS = 5


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


def fetch_imports(api_key: str) -> pd.Series:
    resp = requests.get(SERIES_URL, params={"api_key": api_key}, timeout=30)
    resp.raise_for_status()
    rows = resp.json().get("response", {}).get("data", [])

    records = [
        {"date": pd.to_datetime(r["period"]), "value": float(r["value"])}
        for r in rows
        if r.get("value") not in (None, "")
    ]
    if not records:
        print("ERROR: no data returned for gasoline imports.")
        sys.exit(1)

    s = (
        pd.DataFrame(records)
        .drop_duplicates("date")
        .set_index("date")["value"]
        .sort_index()
    )
    print(f"  {len(s)} weeks  {s.index[0].date()} – {s.index[-1].date()}  "
          f"range [{s.min():.0f}, {s.max():.0f}] KB/D")
    return s


def check_freshness(s: pd.Series) -> None:
    age = (pd.Timestamp(date.today()) - s.index.max()).days
    if age > 14:
        print(
            f"EIA update not yet available. Most recent: {s.index.max().date()} "
            f"({age} days ago). Check back after Wednesday 10:30 AM ET."
        )
        sys.exit(0)
    print(f"  Most recent EIA data: week ending {s.index.max().date()}")


# ---------------------------------------------------------------------------
# Seasonal band
# ---------------------------------------------------------------------------
def seasonal_band(s: pd.Series, window: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    end_date   = window.index.min() - pd.Timedelta(days=1)
    start_date = end_date - pd.DateOffset(years=HISTORY_YEARS)
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
# Chart
# ---------------------------------------------------------------------------
def build_figure(s: pd.Series) -> tuple[plt.Figure, pd.Timestamp]:
    cutoff  = s.index.max() - pd.Timedelta(days=WINDOW_DAYS)
    current = s[s.index >= cutoff]
    lo, hi  = seasonal_band(s, current)

    fig, ax = plt.subplots(figsize=(9, 5.5), facecolor="white")

    ax.fill_between(
        current.index, lo, hi,
        color="#E0E0E0", alpha=1.0, linewidth=0, zorder=2,
    )
    ax.plot(current.index, current.values,
            color="#2196F3", linewidth=1.4, zorder=4)

    ax.set_facecolor("white")
    ax.set_xlim(current.index[0], current.index[-1])

    y_min = min(np.nanmin(lo), current.min())
    y_max = max(np.nanmax(hi), current.max())
    pad   = (y_max - y_min) * 0.10
    ax.set_ylim(y_min - pad, y_max + pad * 1.5)

    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=6, integer=True))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.tick_params(axis="y", labelsize=8, length=0, colors="#333")
    ax.tick_params(axis="x", labelsize=8, length=3, colors="#333")

    ax.text(0.0, 1.02, "Thousand Barrels per Day", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=8, color="#333")

    ax.yaxis.grid(True, color="#cccccc", linewidth=0.5, zorder=0)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#cccccc")
    ax.spines["bottom"].set_color("#555555")

    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b%y"))

    ax.set_title("U.S. Imports of Total Gasoline", fontsize=11, color="#222", pad=10)

    legend_elements = [
        Patch(facecolor="#888", edgecolor="none", label="5-yr Range"),
        Line2D([0], [0], color="#2196F3", linewidth=1.4, label="Weekly Imports"),
    ]
    ax.legend(handles=legend_elements, loc="lower center",
              bbox_to_anchor=(0.5, -0.22), ncol=2,
              frameon=False, fontsize=8.5, handlelength=1.4,
              handleheight=0.9, columnspacing=1.0)

    fig.text(
        0.5, -0.02,
        f"Source: EIA Weekly Petroleum Status Report  |  "
        f"Week ending {current.index.max().strftime('%B %d, %Y')}",
        ha="center", fontsize=7.5, color="#666",
    )

    plt.tight_layout()
    return fig, current.index.max()


# ---------------------------------------------------------------------------
# HTML wrapper
# ---------------------------------------------------------------------------
def generate_index_html(filename: str, latest_date_str: str, output_dir: str, ts: str = "") -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>U.S. Imports of Total Gasoline — {latest_date_str}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#f5f5f5;font-family:Arial,sans-serif;display:flex;
         flex-direction:column;align-items:center;padding:2rem 1rem;min-height:100vh}}
    header{{text-align:center;margin-bottom:1.5rem}}
    header h1{{font-size:1.3rem;font-weight:bold;color:#222}}
    header p{{color:#555;font-size:.85rem;margin-top:.4rem}}
    .chart-wrapper{{width:100%;max-width:760px;background:#fff;
                   border:1px solid #ddd;border-radius:4px;padding:1rem}}
    .chart-wrapper img{{width:100%;height:auto;display:block}}
    footer{{margin-top:1.5rem;font-size:.8rem;color:#888;text-align:center}}
    footer a{{color:#2196F3;text-decoration:none}}
  </style>
</head>
<body>
  <header>
    <h1>&#x26FD; U.S. Imports of Total Gasoline</h1>
    <p>Last {WINDOW_DAYS} days with 5-year seasonal range &mdash; week ending {latest_date_str}</p>
  </header>
  <div class="chart-wrapper">
    <img src="{filename}?v={ts}" alt="U.S. Imports of Total Gasoline {latest_date_str}" />
  </div>
  <footer>
    Source: <a href="https://www.eia.gov/petroleum/supply/weekly/" target="_blank">EIA Weekly Petroleum Status Report</a>
    &nbsp;&bull;&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_gasoline_imports_seasonal.py" target="_blank">Source Code</a>
    &nbsp;&bull;&nbsp;
    <a href="https://boquin.xyz" target="_blank">boquin.xyz</a>
  </footer>
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
    api_key = get_api_key()

    print("Fetching EIA weekly gasoline imports data...")
    s = fetch_imports(api_key)
    check_freshness(s)

    print("Building chart...")
    fig, latest = build_figure(s)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today_str = date.today().strftime("%Y_%m_%d")
    filename  = f"Gasoline_Imports_Weekly_{today_str}.png"
    out_path  = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {out_path}")

    ts = str(int(time.time()))
    generate_index_html(filename, latest.strftime("%Y-%m-%d"), OUTPUT_DIR, ts=ts)


if __name__ == "__main__":
    main()
