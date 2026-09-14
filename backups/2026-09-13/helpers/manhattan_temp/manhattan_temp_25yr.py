"""Manhattan radial chart — full 2006-2025 daily range as grey band + 2026 YTD."""
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import date
from pathlib import Path

# ── data ─────────────────────────────────────────────────────────────────────
CSV = Path("/Users/macproajb/claude_projects/manhattan_daily_temp_25yr.csv")

def fetch():
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": 40.7829, "longitude": -73.9654,
            "start_date": "2001-01-01",
            "end_date": date.today().isoformat(),
            "daily": "temperature_2m_mean",
            "timezone": "America/New_York",
            "temperature_unit": "fahrenheit",
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame({"date": pd.to_datetime(d["time"]), "tmean_f": d["temperature_2m_mean"]})
    df.to_csv(CSV, index=False)
    return df

df = fetch() if not CSV.exists() else pd.read_csv(CSV, parse_dates=["date"])
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365]

# ── historical range (2006–2025) ──────────────────────────────────────────────
doys   = np.arange(1, 366)
angles = (doys - 1) / 365 * 2 * np.pi

hist = df[(df["year"] >= 2006) & (df["year"] <= 2025)]
grp  = hist.groupby("doy")["tmean_f"]
lo   = grp.min().reindex(doys).values.astype(float)
hi   = grp.max().reindex(doys).values.astype(float)

# closed loops for fill_between
ang_c = np.append(angles, angles[0])
lo_c  = np.append(lo, lo[0])
hi_c  = np.append(hi, hi[0])

# 2026 YTD raw daily
yr26 = df[df["year"] == 2026].sort_values("doy").copy()
yr26["angle"] = (yr26["doy"] - 1) / 365 * 2 * np.pi

# ── palette ───────────────────────────────────────────────────────────────────
BG       = "#ffffff"
POLAR_BG = "#f8f9fa"
RED      = "#dc2626"
DARK     = "#111111"
DIM      = "#555555"
GRID     = "#e2e8f0"

# ── figure ────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 16), facecolor=BG)

fig.text(0.5, 0.96, "Manhattan's Wild 2026",
         ha="center", va="top", fontsize=34, fontweight="bold",
         color=DARK, fontfamily="DejaVu Sans")
fig.text(0.5, 0.925,
         "Daily avg temperature · 2026 vs. full 20-year range (2006–2025) · °F · Central Park",
         ha="center", va="top", fontsize=14, color=DIM)

ax = fig.add_axes([0.08, 0.10, 0.84, 0.80], polar=True, facecolor=POLAR_BG)
ax.set_theta_zero_location("N")
ax.set_theta_direction(-1)

# ── grey range band ───────────────────────────────────────────────────────────
ax.fill_between(ang_c, lo_c, hi_c, color="#d1d5db", alpha=0.6, zorder=2)

# ── 2026 YTD ─────────────────────────────────────────────────────────────────
ax.plot(yr26["angle"], yr26["tmean_f"], color=RED, linewidth=2.8, zorder=4,
        label="2026 (YTD)")

# ── radial axis ───────────────────────────────────────────────────────────────
ax.set_rmin(0)
ax.set_rmax(97)
ax.set_rticks([20, 40, 60, 80])
ax.set_yticklabels(["20°", "40°", "60°", "80°"], fontsize=11, color=DIM)
ax.set_rlabel_position(0)

# ── month labels ──────────────────────────────────────────────────────────────
month_names = ["Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]
month_doys  = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
month_angs  = [(d - 1) / 365 * 2 * np.pi for d in month_doys]
ax.set_xticks(month_angs)
ax.set_xticklabels(month_names, fontsize=15, color=DARK, fontweight="bold")

ax.grid(color=GRID, linewidth=0.8, linestyle="-")
ax.spines["polar"].set_visible(False)

# ── legend ────────────────────────────────────────────────────────────────────
import matplotlib.patches as mpatches
handles = [
    mpatches.Patch(color="#d1d5db", alpha=0.6, label="2006–2025 daily range"),
    plt.Line2D([0],[0], color=RED, linewidth=2.8, label="2026 (YTD)"),
]
ax.legend(handles=handles, loc="lower center",
          bbox_to_anchor=(0.5, -0.11), ncol=2,
          frameon=False, fontsize=13, labelcolor=DIM)

# ── source ────────────────────────────────────────────────────────────────────
fig.text(0.5, 0.02,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", va="bottom", fontsize=11, color="#999999")

out = "/Users/macproajb/claude_projects/manhattan_temp_25yr.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
