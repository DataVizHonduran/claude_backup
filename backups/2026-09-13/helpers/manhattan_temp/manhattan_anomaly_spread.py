"""30-day spread of daily temperature anomalies — seasonality removed.
   Anomaly = actual temp minus 20-year rolling lookback median for that DOY.
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# ── data ─────────────────────────────────────────────────────────────────────
CSV = Path("/Users/macproajb/claude_projects/manhattan_temp/manhattan_daily_temp_40yr.csv")
df  = pd.read_csv(CSV, parse_dates=["date"])
df  = df.sort_values("date").copy()
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365]

# ── 20-year rolling lookback median per DOY ───────────────────────────────────
# For each row: median of same DOY over the prior 20 years
by_doy_year = df.groupby(["doy", "year"])["tmean_f"].first()

def lookback_stats(doy, yr):
    years = range(yr - 20, yr)
    vals  = [by_doy_year.loc[(doy, y)] for y in years if (doy, y) in by_doy_year.index]
    if len(vals) < 10:
        return np.nan, np.nan
    return np.median(vals), np.std(vals, ddof=1)

stats = df.apply(lambda r: lookback_stats(r["doy"], r["year"]), axis=1)
df["baseline"] = stats.apply(lambda x: x[0])
df["std"]      = stats.apply(lambda x: x[1])
# z-score: anomaly in units of historical standard deviations for that DOY
df["anomaly"]  = (df["tmean_f"] - df["baseline"]) / df["std"]

# ── 30-day rolling spread of anomalies ───────────────────────────────────────
df = df.set_index("date")
df["roll_max"] = df["anomaly"].rolling(30, min_periods=15).max()
df["roll_min"] = df["anomaly"].rolling(30, min_periods=15).min()
df["spread"]   = df["roll_max"] - df["roll_min"]

plot = df["2006":].copy()

# ── palette ───────────────────────────────────────────────────────────────────
BG   = "#ffffff"
DARK = "#111111"
DIM  = "#666666"
GRID = "#e5e7eb"
RED  = "#dc2626"

# ── figure ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(16, 6), facecolor=BG)
ax.set_facecolor(BG)
for spine in ax.spines.values():
    spine.set_visible(False)
ax.tick_params(length=0)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

ax.fill_between(plot.index, plot["spread"], color="#d1d5db", alpha=0.7, zorder=1)
ax.plot(plot.index, plot["spread"], color=DARK, linewidth=0.9, zorder=2)

spread_mean = plot["spread"].mean()
ax.axhline(spread_mean, color="#aaaaaa", linewidth=0.8, linestyle="--")
ax.text(plot.index.max(), spread_mean, f"  avg ({spread_mean:.1f}σ)",
        fontsize=9, color="#aaaaaa", va="center")

# annotate the 2026 spike
spike_date = plot["spread"].idxmax()
spike_val  = plot["spread"].max()
ax.annotate(
    f"{spike_date.strftime('%b %Y')}\n{spike_val:.1f}σ range",
    xy=(spike_date, spike_val),
    xytext=(-60, -30), textcoords="offset points",
    fontsize=10, color=RED,
    arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.0),
    bbox=dict(boxstyle="round,pad=0.3", fc="#fff8f8", ec=RED, lw=0.8, alpha=0.9),
)

ax.set_xlim(plot.index.min(), plot.index.max())
ax.set_ylim(0, spike_val + 10)
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.tick_params(axis="x", labelsize=11, colors=DARK)
ax.set_ylabel("Spread (std deviations)", fontsize=11, color=DIM)
ax.tick_params(axis="y", labelsize=11, colors=DIM)

ax.set_title("Manhattan: 30-Day Temperature Volatility (Seasonally Adjusted)",
             fontsize=18, fontweight="bold", color=DARK, pad=14, loc="left")
fig.text(0.065, 0.93,
         "Trailing 30-day spread of daily z-scores (anomaly ÷ historical std dev for that calendar day)  ·  ERA5",
         fontsize=11, color=DIM)
fig.text(0.5, 0.01,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", fontsize=10, color="#aaaaaa")

plt.tight_layout(rect=[0, 0.03, 1, 1])

out = "/Users/macproajb/claude_projects/manhattan_temp/manhattan_anomaly_spread.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
