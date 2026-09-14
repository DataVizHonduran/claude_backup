"""Manhattan rolling 365-day temperature percentile rank vs. 20-year baseline."""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date, timedelta
from pathlib import Path

# ── data ─────────────────────────────────────────────────────────────────────
CSV = Path("/Users/macproajb/claude_projects/manhattan_daily_temp_25yr.csv")
df  = pd.read_csv(CSV, parse_dates=["date"])
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365]

today    = pd.Timestamp(date.today())
window   = df[(df["date"] > today - pd.Timedelta(days=365*10)) & (df["date"] <= today)].sort_values("date").copy()

# ── percentile rank ───────────────────────────────────────────────────────────
# baseline: 2006–2025, excluding the row's own year (leave-one-out for 2025)
# 100 = hottest that DOY has ever been in baseline, 0 = coldest

def pct_rank(hist_vals, val):
    n = len(hist_vals)
    if n == 0:
        return np.nan
    return sum(h <= val for h in hist_vals) / n * 100

baseline = df[(df["year"] >= 2006) & (df["year"] <= 2025)]

def row_pct(row):
    excl_year = row["year"] if 2006 <= row["year"] <= 2025 else None
    hist = baseline[baseline["year"] != excl_year] if excl_year else baseline
    vals = hist[hist["doy"] == row["doy"]]["tmean_f"].tolist()
    return pct_rank(vals, row["tmean_f"])

window["pct"]     = window.apply(row_pct, axis=1)
window["pct_raw"] = window["pct"]
window["pct"]     = window["pct"].rolling(30, center=True, min_periods=1).mean()

# ── palette ───────────────────────────────────────────────────────────────────
BG   = "#ffffff"
DARK = "#111111"
DIM  = "#666666"
GRID = "#e5e7eb"
RED  = "#dc2626"
BLUE = "#2563eb"

# ── figure ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(16, 7), facecolor=BG)
ax.set_facecolor(BG)

# extreme zones
ax.axhspan(90, 100, color="#fee2e2", alpha=0.5, zorder=1)
ax.axhspan(0,   10, color="#dbeafe", alpha=0.5, zorder=1)

# reference lines
ax.axhline(50,  color=DIM,  linewidth=0.8, linestyle="--", zorder=2)
ax.axhline(90,  color=RED,  linewidth=0.5, linestyle=":",  zorder=2, alpha=0.5)
ax.axhline(10,  color=BLUE, linewidth=0.5, linestyle=":",  zorder=2, alpha=0.5)

# year boundary lines
for yr in range(2017, 2027):
    ax.axvline(pd.Timestamp(f"{yr}-01-01"), color="#cccccc", linewidth=0.7,
               linestyle="-", zorder=2, alpha=0.6)
    ax.text(pd.Timestamp(f"{yr}-01-15"), 102, str(yr), fontsize=9,
            color="#999999", va="top")

# fills
ax.fill_between(window["date"], 50, window["pct"],
                where=window["pct"] >= 50,
                color=RED, alpha=0.08, zorder=2)
ax.fill_between(window["date"], window["pct"], 50,
                where=window["pct"] < 50,
                color=BLUE, alpha=0.08, zorder=2)

ax.plot(window["date"], window["pct"], color=DARK, linewidth=0.6, zorder=3)

# ── annotations ───────────────────────────────────────────────────────────────
pct_arr  = window["pct"].values
date_arr = window["date"].values

# April heat peak (search in Apr window)
apr_mask = (window["date"] >= "2026-04-01") & (window["date"] <= "2026-04-30")
apr_idx  = window[apr_mask]["pct"].idxmax()
apr_pos  = window.index.get_loc(apr_idx)
ax.annotate(
    "Apr 15–16\n100th pct",
    xy=(date_arr[apr_pos], pct_arr[apr_pos]),
    xytext=(0, -38), textcoords="offset points",
    fontsize=10, color=RED, ha="center",
    arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.0),
    bbox=dict(boxstyle="round,pad=0.3", fc="#fff8f8", ec=RED, lw=0.8, alpha=0.9),
)

# Jan-Feb cold trough
jf_mask = (window["date"] >= "2026-01-01") & (window["date"] <= "2026-02-28")
jf_idx  = window[jf_mask]["pct"].idxmin()
jf_pos  = window.index.get_loc(jf_idx)
ax.annotate(
    "Jan–Feb\ncold streak\n0th pct",
    xy=(date_arr[jf_pos], pct_arr[jf_pos]),
    xytext=(40, 20), textcoords="offset points",
    fontsize=10, color=BLUE,
    arrowprops=dict(arrowstyle="-|>", color=BLUE, lw=1.0),
    bbox=dict(boxstyle="round,pad=0.3", fc="#f0f6ff", ec=BLUE, lw=0.8, alpha=0.9),
)

# ── axes ─────────────────────────────────────────────────────────────────────
ax.set_xlim(window["date"].min(), window["date"].max())
ax.set_ylim(-5, 107)
ax.set_yticks([0, 10, 25, 50, 75, 90, 100])
ax.set_yticklabels(["0  (coldest on record)", "10th", "25th", "50th",
                    "75th", "90th", "100  (hottest on record)"],
                   fontsize=11, color=DIM)
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter(""))   # labels handled by axvline text
ax.tick_params(axis="x", labelsize=11, colors=DARK, rotation=0, length=0)
ax.tick_params(axis="y", length=0)

for spine in ax.spines.values():
    spine.set_visible(False)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

# ── titles ────────────────────────────────────────────────────────────────────
ax.set_title("Manhattan: How Extreme Was Each Day? (Last 10 Years)",
             fontsize=20, fontweight="bold", color=DARK, pad=14, loc="left")
fig.text(0.065, 0.88,
         "30-day smoothed percentile rank of daily avg temperature vs. same calendar day, 2006–2025  ·  Central Park  ·  ERA5",
         fontsize=11, color=DIM)
fig.text(0.5, 0.01,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", fontsize=10, color="#aaaaaa")

plt.tight_layout(rect=[0, 0.03, 1, 1])

out = "/Users/macproajb/claude_projects/manhattan_temp_percentile.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
