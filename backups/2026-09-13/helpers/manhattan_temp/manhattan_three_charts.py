"""Three volatility charts for Manhattan 2026."""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

CSV = Path("/Users/macproajb/claude_projects/manhattan_temp/manhattan_daily_temp_40yr.csv")
df  = pd.read_csv(CSV, parse_dates=["date"])
df  = df.sort_values("date").copy()
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365]

BG   = "#ffffff"
DARK = "#111111"
DIM  = "#666666"
GRID = "#e5e7eb"
RED  = "#dc2626"

CUTOFF_DOY = 138   # May 18

# ═══════════════════════════════════════════════════════════════════════════════
# CHART 1 — 7-day temperature whiplash: 2026 vs historical average
# ═══════════════════════════════════════════════════════════════════════════════
ts = df.set_index("date")["tmean_f"]
ts_7d = ts.diff(7).abs()   # absolute 7-day change for every day in dataset

hist_swing = df[(df["year"] >= 2006) & (df["year"] <= 2025) & (df["doy"] <= CUTOFF_DOY)].copy()
hist_swing["swing"] = hist_swing["date"].map(ts_7d)
avg_swing_by_doy = hist_swing.groupby("doy")["swing"].mean()

yr26 = df[(df["year"] == 2026) & (df["doy"] <= CUTOFF_DOY)].copy()
yr26["swing"] = yr26["date"].map(ts_7d)
yr26["avg"]   = yr26["doy"].map(avg_swing_by_doy)
yr26 = yr26.set_index("date")

fig1, ax = plt.subplots(figsize=(14, 6), facecolor=BG)
ax.set_facecolor(BG)
for sp in ax.spines.values(): sp.set_visible(False)
ax.tick_params(length=0)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

ax.fill_between(yr26.index, yr26["avg"], yr26["swing"],
                where=yr26["swing"] >= yr26["avg"],
                color=RED, alpha=0.15, zorder=1)
ax.plot(yr26.index, yr26["avg"],   color="#94a3b8", linewidth=1.5,
        linestyle="--", zorder=2, label="2006–2025 avg")
ax.plot(yr26.index, yr26["swing"], color=RED, linewidth=2.0,
        zorder=3, label="2026")

# annotate biggest spike
peak_idx = yr26["swing"].idxmax()
peak_val = yr26["swing"].max()
ax.annotate(f"{peak_val:.0f}°F swing\nin 7 days",
            xy=(peak_idx, peak_val),
            xytext=(20, 10), textcoords="offset points",
            fontsize=11, color=RED,
            arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.0),
            bbox=dict(boxstyle="round,pad=0.3", fc="#fff8f8", ec=RED, lw=0.8, alpha=0.9))

ax.set_xlim(yr26.index.min(), yr26.index.max())
ax.set_ylim(0, peak_val + 12)
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.tick_params(axis="x", labelsize=12, colors=DARK)
ax.set_ylabel("Temp change (°F)", fontsize=11, color=DIM)
ax.tick_params(axis="y", labelsize=11, colors=DIM)
ax.legend(frameon=False, fontsize=12, labelcolor=DIM)
ax.set_title("Temperature Whiplash: How Much Did It Swing Week-to-Week?",
             fontsize=17, fontweight="bold", color=DARK, pad=12, loc="left")
fig1.text(0.065, 0.91, "Absolute 7-day temperature change · 2026 vs 2006–2025 average · Jan–May · ERA5",
          fontsize=11, color=DIM)
fig1.text(0.5, 0.01, "Source: open-meteo ERA5 archive · Central Park, NYC",
          ha="center", fontsize=10, color="#aaaaaa")
plt.tight_layout(rect=[0, 0.03, 1, 1])
fig1.savefig("/Users/macproajb/claude_projects/manhattan_temp/chart1_whiplash.png",
             dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print("Chart 1 saved.")


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 2 — Raw Jan–May temperature: all years grey, 2026 red
# ═══════════════════════════════════════════════════════════════════════════════
jan1 = pd.Timestamp("2000-01-01")  # dummy year for x-axis alignment

fig2, ax = plt.subplots(figsize=(14, 6), facecolor=BG)
ax.set_facecolor(BG)
for sp in ax.spines.values(): sp.set_visible(False)
ax.tick_params(length=0)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

for yr in range(2006, 2026):
    ydf = df[(df["year"] == yr) & (df["doy"] <= CUTOFF_DOY)].copy()
    dates = [jan1 + pd.Timedelta(days=int(d) - 1) for d in ydf["doy"]]
    ax.plot(dates, ydf["tmean_f"].values, color="#cbd5e1", linewidth=0.7,
            alpha=0.6, zorder=1)

ydf26 = df[(df["year"] == 2026) & (df["doy"] <= CUTOFF_DOY)].copy()
dates26 = [jan1 + pd.Timedelta(days=int(d) - 1) for d in ydf26["doy"]]
ax.plot(dates26, ydf26["tmean_f"].values, color=RED, linewidth=2.2, zorder=3, label="2026")

# annotate cold trough and heat spike
cold_pos = ydf26["tmean_f"].idxmin()
cold_date = jan1 + pd.Timedelta(days=int(ydf26.loc[cold_pos, "doy"]) - 1)
ax.annotate(f"{ydf26.loc[cold_pos,'tmean_f']:.0f}°F",
            xy=(cold_date, ydf26.loc[cold_pos, "tmean_f"]),
            xytext=(15, -20), textcoords="offset points",
            fontsize=10, color="#2563eb",
            arrowprops=dict(arrowstyle="-|>", color="#2563eb", lw=1.0),
            bbox=dict(boxstyle="round,pad=0.3", fc="#f0f6ff", ec="#2563eb", lw=0.8, alpha=0.9))

heat_pos = ydf26["tmean_f"].idxmax()
heat_date = jan1 + pd.Timedelta(days=int(ydf26.loc[heat_pos, "doy"]) - 1)
ax.annotate(f"{ydf26.loc[heat_pos,'tmean_f']:.0f}°F",
            xy=(heat_date, ydf26.loc[heat_pos, "tmean_f"]),
            xytext=(-50, 15), textcoords="offset points",
            fontsize=10, color=RED,
            arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.0),
            bbox=dict(boxstyle="round,pad=0.3", fc="#fff8f8", ec=RED, lw=0.8, alpha=0.9))

ax.set_xlim(jan1, jan1 + pd.Timedelta(days=CUTOFF_DOY - 1))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.tick_params(axis="x", labelsize=12, colors=DARK)
ax.set_ylabel("Daily avg temp (°F)", fontsize=11, color=DIM)
ax.tick_params(axis="y", labelsize=11, colors=DIM)

from matplotlib.lines import Line2D
ax.legend(handles=[
    Line2D([0],[0], color="#cbd5e1", linewidth=2, label="2006–2025"),
    Line2D([0],[0], color=RED, linewidth=2.2, label="2026"),
], frameon=False, fontsize=12, labelcolor=DIM)

ax.set_title("2026 vs Every Year Since 2006 — Jan Through May",
             fontsize=17, fontweight="bold", color=DARK, pad=12, loc="left")
fig2.text(0.065, 0.91, "Daily avg temperature · Central Park · ERA5",
          fontsize=11, color=DIM)
fig2.text(0.5, 0.01, "Source: open-meteo ERA5 archive · Central Park, NYC",
          ha="center", fontsize=10, color="#aaaaaa")
plt.tight_layout(rect=[0, 0.03, 1, 1])
fig2.savefig("/Users/macproajb/claude_projects/manhattan_temp/chart2_overlay.png",
             dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print("Chart 2 saved.")


# ═══════════════════════════════════════════════════════════════════════════════
# CHART 3 — Biggest 30-day swing per year, Jan–May
# ═══════════════════════════════════════════════════════════════════════════════
records = []
for yr in range(2006, 2027):
    ydf = df[(df["year"] == yr) & (df["doy"] <= CUTOFF_DOY)].set_index("date")["tmean_f"]
    if len(ydf) < 15:
        continue
    roll_max = ydf.rolling(30, min_periods=15).max()
    roll_min = ydf.rolling(30, min_periods=15).min()
    swing    = (roll_max - roll_min).max()
    records.append({"year": yr, "swing": swing})

swings = pd.DataFrame(records)
colors = [RED if y == 2026 else "#94a3b8" for y in swings["year"]]

fig3, ax = plt.subplots(figsize=(14, 6), facecolor=BG)
ax.set_facecolor(BG)
for sp in ax.spines.values(): sp.set_visible(False)
ax.tick_params(length=0)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

bars = ax.bar(swings["year"], swings["swing"], color=colors, width=0.7, zorder=3)
for bar, val in zip(bars, swings["swing"]):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.4,
            f"{val:.0f}°", ha="center", va="bottom", fontsize=9.5, color=DIM)

avg = swings[swings["year"] < 2026]["swing"].mean()
ax.axhline(avg, color="#aaaaaa", linewidth=0.8, linestyle="--")
ax.text(swings["year"].max() + 0.5, avg, f"  avg ({avg:.0f}°)",
        fontsize=9, color="#aaaaaa", va="center")

ax.set_xticks(swings["year"])
ax.set_xticklabels(swings["year"], fontsize=11, color=DARK)
ax.set_ylim(0, swings["swing"].max() + 10)
ax.set_ylabel("Max 30-day temp swing (°F)", fontsize=11, color=DIM)
ax.tick_params(axis="y", labelsize=11, colors=DIM)

ax.set_title("Biggest Temperature Swing in Any 30-Day Window, Jan–May",
             fontsize=17, fontweight="bold", color=DARK, pad=12, loc="left")
fig3.text(0.065, 0.91, "Max of rolling 30-day (high minus low) · each year · ERA5",
          fontsize=11, color=DIM)
fig3.text(0.5, 0.01, "Source: open-meteo ERA5 archive · Central Park, NYC",
          ha="center", fontsize=10, color="#aaaaaa")
plt.tight_layout(rect=[0, 0.03, 1, 1])
fig3.savefig("/Users/macproajb/claude_projects/manhattan_temp/chart3_annual_swing.png",
             dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print("Chart 3 saved.")
