"""Rolling 100-day temperature volatility — z-score std dev, 2006–2026."""
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

# ── 20-year rolling lookback z-score for each day ────────────────────────────
by_doy_year = df.groupby(["doy", "year"])["tmean_f"].first()

def lookback_stats(doy, yr):
    vals = [by_doy_year.loc[(doy, y)] for y in range(yr - 20, yr)
            if (doy, y) in by_doy_year.index]
    if len(vals) < 10:
        return np.nan, np.nan
    return np.median(vals), np.std(vals, ddof=1)

stats          = df.apply(lambda r: lookback_stats(r["doy"], r["year"]), axis=1)
df["baseline"] = stats.apply(lambda x: x[0])
df["std"]      = stats.apply(lambda x: x[1])
df["zscore"]   = (df["tmean_f"] - df["baseline"]) / df["std"]

# ── 100-day rolling std of z-scores ──────────────────────────────────────────
df = df.set_index("date")
df["vol"] = df["zscore"].rolling(100, min_periods=50).std()

plot = df["2006":].copy()

# ── palette ───────────────────────────────────────────────────────────────────
BG   = "#ffffff"
DARK = "#111111"
DIM  = "#666666"
GRID = "#e5e7eb"
RED  = "#dc2626"
BLUE = "#2563eb"

# ── figure ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(16, 6), facecolor=BG)
ax.set_facecolor(BG)
for spine in ax.spines.values():
    spine.set_visible(False)
ax.tick_params(length=0)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

ax.plot(plot.index, plot["vol"], color=DARK, linewidth=1.2, zorder=3)

vol_mean = plot["vol"].mean()
ax.axhline(vol_mean, color="#aaaaaa", linewidth=0.8, linestyle="--", zorder=2)
ax.text(plot.index.max(), vol_mean, f"  avg ({vol_mean:.2f})",
        fontsize=9, color="#aaaaaa", va="center")

# annotate peak
peak_date = plot["vol"].idxmax()
peak_val  = plot["vol"].max()
ax.annotate(
    f"{peak_date.strftime('%b %Y')}\n{peak_val:.2f}σ",
    xy=(peak_date, peak_val),
    xytext=(20, -30), textcoords="offset points",
    fontsize=10, color=RED,
    arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.0),
    bbox=dict(boxstyle="round,pad=0.3", fc="#fff8f8", ec=RED, lw=0.8, alpha=0.9),
)

ax.set_xlim(plot.index.min(), plot.index.max())
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.tick_params(axis="x", labelsize=11, colors=DARK)
ax.set_ylabel("Volatility (std deviations)", fontsize=11, color=DIM)
ax.tick_params(axis="y", labelsize=11, colors=DIM)

ax.set_title("Manhattan: Rolling 100-Day Temperature Volatility",
             fontsize=18, fontweight="bold", color=DARK, pad=14, loc="left")
fig.text(0.065, 0.93,
         "100-day rolling std dev of daily z-scores (anomaly ÷ historical std dev per calendar day)  ·  20-yr lookback  ·  ERA5",
         fontsize=11, color=DIM)
fig.text(0.5, 0.01,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", fontsize=10, color="#aaaaaa")

plt.tight_layout(rect=[0, 0.03, 1, 1])

out = "/Users/macproajb/claude_projects/manhattan_temp/manhattan_volatility_100d.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
