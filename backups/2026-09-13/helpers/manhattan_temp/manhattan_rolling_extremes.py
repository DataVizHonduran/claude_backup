"""Rolling 100-day max and min daily avg temperature — Manhattan 2006–2026."""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# ── data ─────────────────────────────────────────────────────────────────────
CSV = Path("/Users/macproajb/claude_projects/manhattan_daily_temp_40yr.csv")
df  = pd.read_csv(CSV, parse_dates=["date"])
df  = df.sort_values("date").set_index("date")

# rolling 100-day max and min (trailing window)
df["roll_max"] = df["tmean_f"].rolling(30, min_periods=15).max()
df["roll_min"] = df["tmean_f"].rolling(30, min_periods=15).min()
df["spread"]   = df["roll_max"] - df["roll_min"]

# trim to 2006 onward
plot = df["2006":].copy()

# ── palette ───────────────────────────────────────────────────────────────────
BG   = "#ffffff"
DARK = "#111111"
DIM  = "#666666"
GRID = "#e5e7eb"
RED  = "#dc2626"
BLUE = "#2563eb"

# ── figure ────────────────────────────────────────────────────────────────────
fig, ax2 = plt.subplots(figsize=(16, 6), facecolor=BG)
ax2.set_facecolor(BG)
for spine in ax2.spines.values():
    spine.set_visible(False)
ax2.tick_params(length=0)
ax2.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

# ── spread panel ─────────────────────────────────────────────────────────────
ax2.fill_between(plot.index, plot["spread"], color="#d1d5db", alpha=0.7, zorder=1)
ax2.plot(plot.index, plot["spread"], color=DARK, linewidth=1.0, zorder=2)

spread_mean = plot["spread"].mean()
ax2.axhline(spread_mean, color="#aaaaaa", linewidth=0.8, linestyle="--")
ax2.text(plot.index.max(), spread_mean, f"  avg ({spread_mean:.0f}°)",
         fontsize=9, color="#aaaaaa", va="center")
ax2.set_ylabel("Spread (°F)", fontsize=11, color=DIM)
ax2.set_yticks([20, 30, 40, 50, 60, 70])
ax2.set_yticklabels(["20°", "30°", "40°", "50°", "60°", "70°"], fontsize=11, color=DIM)

ax2.set_xlim(plot.index.min(), plot.index.max())
ax2.xaxis.set_major_locator(mdates.YearLocator())
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax2.tick_params(axis="x", labelsize=11, colors=DARK)

# ── titles ────────────────────────────────────────────────────────────────────
ax2.set_title("Manhattan: 30-Day Temperature Spread (Max minus Min)",
              fontsize=18, fontweight="bold", color=DARK, pad=14, loc="left")
fig.text(0.065, 0.93,
         "Trailing 30-day range of daily avg temperature  ·  ERA5  ·  Central Park",
         fontsize=11, color=DIM)
fig.text(0.5, 0.01,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", fontsize=10, color="#aaaaaa")

out = "/Users/macproajb/claude_projects/manhattan_rolling_extremes.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
