"""
Weekly Crude Oil Stocks by PAD District — EIA-Style Multi-Panel Chart
======================================================================
Fetches EIA Weekly Petroleum Status Report crude stocks for U.S. total
and PAD Districts 1–5, then generates a 3×2 panel PNG matching the
EIA's own chart style:
  - Gradient grey 5-year seasonal range band (dark top → light bottom)
  - Blue weekly line
  - MM/DD x-axis with year-span labels below
  - White background, horizontal grid lines only

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_crude_stocks_weekly.py
Output: reports/crude-stocks/Crude_Stocks_Weekly_YYYY_MM_DD.png
"""

import os
import sys
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import matplotlib.lines as mlines
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from datetime import date

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE  = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
OUTPUT_DIR    = os.path.join(os.path.dirname(__file__), "..", "reports", "crude-stocks")
WINDOW_DAYS   = 365
HISTORY_YEARS = 7

PANELS = [
    ("NUS", "U.S. Crude Oil Stocks"),
    ("R10", "PADD 1 Crude Oil Stocks"),
    ("R20", "PADD 2 Crude Oil Stocks"),
    ("R30", "PADD 3 Crude Oil Stocks"),
    ("R40", "PADD 4 Crude Oil Stocks"),
    ("R50", "PADD 5 Crude Oil Stocks"),
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


def _query_one(api_key: str, duoarea: str, process: str) -> pd.Series:
    """Fetch one duoarea+process combination. Returns empty Series if no data."""
    weeks = HISTORY_YEARS * 53 + 10
    qs = (
        f"api_key={api_key}"
        f"&frequency=weekly"
        f"&data[0]=value"
        f"&facets[product][]=EPC0"
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
        print(f"  WARNING: {duoarea}/{process} failed — {e}")
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


def fetch_area(api_key: str, duoarea: str) -> pd.Series:
    """
    Fetch HISTORY_YEARS of weekly commercial crude stocks for one duoarea.
    Queries with explicit process filter so all 381 rows come from one series.
    SAX (ex-SPR) is preferred — critical for PADD 3 (Gulf Coast) which holds
    ~300 MMBbl of SPR that would otherwise inflate the values. Falls back to
    SAE if SAX is unavailable for that area.
    """
    for process in ("SAX", "SAE"):
        s = _query_one(api_key, duoarea, process)
        if not s.empty:
            print(f"  {duoarea} [{process}]: {len(s)} weeks  "
                  f"{s.index[0].date()} – {s.index[-1].date()}  "
                  f"range [{s.min():.1f}, {s.max():.1f}] MMBbl")
            return s

    print(f"  WARNING: no data returned for {duoarea}")
    return pd.Series(dtype=float)


def fetch_all_areas(api_key: str) -> dict[str, pd.Series]:
    """Fetch each PADD area separately so every area gets its full history."""
    result = {}
    for da, title in PANELS:
        print(f"  Fetching {da} ({title})...")
        s = fetch_area(api_key, da)
        if not s.empty:
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
    """
    Calculates the 5-year seasonal envelope using Day-of-Year normalization.
    Aligns historical data by relative calendar position to ensure a smooth
    continuous range, mitigating weekly date-shift jitter.
    """
    end_date = window.index.min() - pd.Timedelta(days=1)
    start_date = end_date - pd.DateOffset(years=5)
    hist_data = s[start_date:end_date].copy()

    df_hist = hist_data.to_frame(name='value')
    df_hist['doy'] = df_hist.index.dayofyear
    df_hist['year'] = df_hist.index.year

    lo_vals, hi_vals = [], []

    for dt in window.index:
        target_doy = dt.dayofyear
        doy_min = target_doy - 7
        doy_max = target_doy + 7
        mask = (df_hist['doy'] >= doy_min) & (df_hist['doy'] <= doy_max)
        bucket = df_hist.loc[mask, 'value']

        if len(bucket) >= 3:
            lo_vals.append(bucket.min())
            hi_vals.append(bucket.max())
        else:
            lo_vals.append(np.nan)
            hi_vals.append(np.nan)

    lo_series = pd.Series(lo_vals).interpolate(limit_direction='both').values
    hi_series = pd.Series(hi_vals).interpolate(limit_direction='both').values

    return lo_series, hi_series


# ---------------------------------------------------------------------------
# Single panel
# ---------------------------------------------------------------------------
def draw_panel(ax, s: pd.Series, title: str) -> None:
    cutoff  = s.index.max() - pd.Timedelta(days=WINDOW_DAYS)
    current = s[s.index >= cutoff]
    lo, hi  = seasonal_band(s, current)

    ax_xmin = mdates.date2num(current.index[0].to_pydatetime())
    ax_xmax = mdates.date2num(current.index[-1].to_pydatetime())

    # ---- gradient grey band (80 strips, dark at top → white at bottom) ---
  # Use a single fill_between with a fixed alpha for a uniform look
    ax.fill_between(
          current.index, 
          lo, 
          hi, 
          color="#E0E0E0",  # A light, professional grey
          alpha=1.0,       # Fully opaque (or use 0.5 if you want it softer)
          linewidth=0, 
          zorder=2
      )
    # ---- blue weekly line ------------------------------------------------
    ax.plot(current.index, current.values,
            color="#2196F3", linewidth=1.2, zorder=4)

    # ---- axes style -------------------------------------------------------
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

    # ---- x-axis: MM/DD ticks + year labels below -------------------------
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

    # Interval=2 sets the "every two months" frequency
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    
    # %b is short month (Jul), %y is short year (26)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b%y"))

    ## original way Claude was having me do the x axis
    # trans = ax.get_xaxis_transform()
    # for yr in sorted(set(current.index.year)):
    #     yr_start = mdates.date2num(pd.Timestamp(f"{yr}-01-01").to_pydatetime())
    #     yr_end   = mdates.date2num(pd.Timestamp(f"{yr}-12-31").to_pydatetime())
    #     xl = max(yr_start, ax_xmin)
    #     xr = min(yr_end,   ax_xmax)
    #     if xr <= xl:
    #         continue
    #     xmid = (xl + xr) / 2
    #     xmid_frac = (xmid - ax_xmin) / (ax_xmax - ax_xmin)
    #     ln = mlines.Line2D([xl, xr], [-0.10, -0.10],
    #                        transform=trans, color="#555", lw=0.7, clip_on=False)
    #     ax.add_line(ln)
    #     ax.text(xmid_frac, -0.16, str(yr), transform=ax.transAxes,
    #             ha="center", va="top", fontsize=7, color="#333")

    # ---- panel title ------------------------------------------------------
    ax.set_title(title, fontsize=8.5, color="#222", pad=4)

    # ---- per-panel legend -------------------------------------------------
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
def build_figure(series_dict: dict) -> plt.Figure:
    fig, axes = plt.subplots(3, 2, figsize=(11, 10), facecolor="white")
    fig.patch.set_facecolor("white")

    for ax, (da, title) in zip(axes.flat, PANELS):
        if da not in series_dict:
            ax.set_visible(False)
            continue
        draw_panel(ax, series_dict[da], title)

    latest = max(s.index.max() for s in series_dict.values())
    fig.suptitle(
        f"Figure 1. Stocks of Crude Oil by PAD District — Last 365 Days",
        fontsize=10, color="#222", y=1.01,
    )
    fig.text(0.5, -0.01,
             f"Source: EIA Weekly Petroleum Status Report  |  Week ending {latest.strftime('%B %d, %Y')}",
             ha="center", fontsize=7.5, color="#666")

    plt.tight_layout(h_pad=3.5, w_pad=2.5)
    return fig


# ---------------------------------------------------------------------------
# HTML wrapper
# ---------------------------------------------------------------------------
def generate_index_html(filename: str, latest_date_str: str, output_dir: str, ts: str = "") -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Crude Oil Stocks by PAD District — {latest_date_str}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#f5f5f5;font-family:Arial,sans-serif;display:flex;
         flex-direction:column;align-items:center;padding:2rem 1rem;min-height:100vh}}
    header{{text-align:center;margin-bottom:1.5rem}}
    header h1{{font-size:1.3rem;font-weight:bold;color:#222}}
    header p{{color:#555;font-size:.85rem;margin-top:.4rem}}
    .chart-wrapper{{width:100%;max-width:960px;background:#fff;
                   border:1px solid #ddd;border-radius:4px;padding:1rem}}
    .chart-wrapper img{{width:100%;height:auto;display:block}}
    footer{{margin-top:1.5rem;font-size:.8rem;color:#888;text-align:center}}
    footer a{{color:#2196F3;text-decoration:none}}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F6E2;&#xFE0F; Crude Oil Stocks by PAD District</h1>
    <p>Last {WINDOW_DAYS} days with 5-year seasonal range &mdash; week ending {latest_date_str}</p>
  </header>
  <div class="chart-wrapper">
    <img src="{filename}?v={ts}" alt="Crude Oil Stocks by PADD {latest_date_str}" />
  </div>
  <footer>
    Source: <a href="https://www.eia.gov/petroleum/supply/weekly/" target="_blank">EIA Weekly Petroleum Status Report</a>
    &nbsp;&bull;&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_crude_stocks_weekly.py" target="_blank">Source Code</a>
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

    print("Fetching crude oil stock data from EIA API...")
    series_dict = fetch_all_areas(api_key)
    check_freshness(series_dict)

    print("Building chart...")
    fig = build_figure(series_dict)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today_str  = date.today().strftime("%Y_%m_%d")
    filename   = f"Crude_Stocks_Weekly_{today_str}.png"
    out_path   = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {out_path}")

    latest_str = max(s.index.max() for s in series_dict.values()).strftime("%Y-%m-%d")
    import time
    generate_index_html(filename, latest_str, OUTPUT_DIR, ts=str(int(time.time())))


if __name__ == "__main__":
    main()
