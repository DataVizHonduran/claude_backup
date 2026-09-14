"""High-res PNG for r/dataisbeautiful — Manhattan 2026 temperature wheel."""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

# ── data ─────────────────────────────────────────────────────────────────────
df = pd.read_csv("/Users/macproajb/claude_projects/manhattan_daily_temperature.csv", parse_dates=["date"])
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365]

hist = df[df["year"] < 2026]
grp  = hist.groupby("doy")["tmean_f"]

def smooth(arr):
    p = np.concatenate([arr[-3:], arr, arr[:3]])
    return pd.Series(p).rolling(7, center=True, min_periods=1).mean().values[3:-3]

doys   = np.arange(1, 366)
angles = (doys - 1) / 365 * 2 * np.pi   # 0 = Jan 1, increases clockwise

median = grp.median().reindex(doys).values.astype(float)
p80    = grp.quantile(0.80).reindex(doys).values.astype(float)
p90    = grp.quantile(0.90).reindex(doys).values.astype(float)
p100   = grp.max().reindex(doys).values.astype(float)

yr26 = df[df["year"] == 2026].sort_values("doy").copy()
yr26["angle"] = (yr26["doy"] - 1) / 365 * 2 * np.pi

# close loops
ang_c  = np.append(angles, angles[0])
med_c  = np.append(median, median[0])
p80_c  = np.append(p80,  p80[0])
p90_c  = np.append(p90,  p90[0])
p100_c = np.append(p100, p100[0])

# ── figure ────────────────────────────────────────────────────────────────────
BG       = "#ffffff"
POLAR_BG = "#f8f9fa"
BLUE     = "#2563eb"
RED      = "#dc2626"
WHITE    = "#111111"
DIM      = "#555555"
GRID     = "#e2e8f0"

fig = plt.figure(figsize=(14, 16), facecolor=BG)

# title block
fig.text(0.5, 0.96, "Manhattan's Wild 2026",
         ha="center", va="top",
         fontsize=34, fontweight="bold", color=WHITE,
         fontfamily="DejaVu Sans")
fig.text(0.5, 0.925,
         "Daily average temperature · Jan–May 2026 vs. 20-year baseline · °F · unsmoothed",
         ha="center", va="top",
         fontsize=14, color=DIM)

# polar axes
ax = fig.add_axes([0.08, 0.10, 0.84, 0.80], polar=True, facecolor=POLAR_BG)
ax.set_theta_zero_location("N")   # Jan at top
ax.set_theta_direction(-1)        # clockwise


# ── median ────────────────────────────────────────────────────────────────────
ax.plot(ang_c, med_c, color=BLUE, linewidth=2, zorder=3, label="20-yr median (2006–2025)")

# ── 2026 ──────────────────────────────────────────────────────────────────────
ax.plot(yr26["angle"], yr26["tmean_f"], color=RED, linewidth=2.8, zorder=4,
        label="2026 (YTD through May 15)")

# ── radial axis ───────────────────────────────────────────────────────────────
ax.set_rmin(0)
ax.set_rmax(97)
ax.set_rticks([20, 40, 60, 80])
ax.set_yticklabels(["20°", "40°", "60°", "80°"],
                   fontsize=11, color=DIM)
ax.yaxis.set_tick_params(labelcolor=DIM)
ax.set_rlabel_position(0)   # labels at top (Jan position)

# ── month labels ──────────────────────────────────────────────────────────────
month_names = ["Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]
month_doys  = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
month_angs  = [(d - 1) / 365 * 2 * np.pi for d in month_doys]

ax.set_xticks(month_angs)
ax.set_xticklabels(month_names, fontsize=15, color=WHITE, fontweight="bold")

# grid
ax.grid(color=GRID, linewidth=0.8, linestyle="-")
ax.spines["polar"].set_visible(False)

# ── annotations ───────────────────────────────────────────────────────────────
# Apr heat — convert DOY 106, r≈80 to axes coords for arrow
ang_apr = (106 - 1) / 365 * 2 * np.pi
ax.annotate(
    "Apr 15: 90°F\n+32°F above median\nBroke 85-yr record",
    xy=(ang_apr, 80), xycoords="data",
    xytext=(0.78, 0.25), textcoords="figure fraction",
    fontsize=12, color=RED, ha="left",
    arrowprops=dict(arrowstyle="-|>", color=RED, lw=1.2,
                    connectionstyle="arc3,rad=0.2"),
    bbox=dict(boxstyle="round,pad=0.3", fc="#fff8f8", ec=RED, lw=0.8, alpha=0.9),
)

# Jan-Feb cold — DOY 39, r≈7
ang_cold = (39 - 1) / 365 * 2 * np.pi
ax.annotate(
    "Jan 24–Feb 8\n16 days below 20°F avg\nColdest since 1982",
    xy=(ang_cold, 7), xycoords="data",
    xytext=(0.05, 0.62), textcoords="figure fraction",
    fontsize=12, color=BLUE, ha="left",
    arrowprops=dict(arrowstyle="-|>", color=BLUE, lw=1.2,
                    connectionstyle="arc3,rad=-0.25"),
    bbox=dict(boxstyle="round,pad=0.3", fc="#f0f6ff", ec=BLUE, lw=0.8, alpha=0.9),
)

# ── legend ────────────────────────────────────────────────────────────────────
handles = [
    plt.Line2D([0], [0], color=BLUE, linewidth=2,   label="20-yr median (2006–2025)"),
    plt.Line2D([0], [0], color=RED,  linewidth=2.8, label="2026  (YTD through May 15)"),
]
leg = ax.legend(handles=handles, loc="lower center",
                bbox_to_anchor=(0.5, -0.13), ncol=3,
                frameon=False, fontsize=13,
                labelcolor=DIM)

# ── source ────────────────────────────────────────────────────────────────────
fig.text(0.5, 0.02,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", va="bottom", fontsize=11, color="#999999")

out = "/Users/macproajb/claude_projects/manhattan_temp_poster.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
