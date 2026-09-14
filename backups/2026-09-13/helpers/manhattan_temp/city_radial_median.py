"""Radial chart: 5-year median temperature for 5 US cities."""
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

CITIES = {
    "Miami":         (25.7617, -80.1918),
    "San Francisco": (37.7749, -122.4194),
    "New York":      (40.7829, -73.9654),
    "Boston":        (42.3601, -71.0589),
    "Minneapolis":   (44.9778, -93.2650),
}

COLORS = {
    "Miami":         "#f59e0b",
    "San Francisco": "#7c3aed",
    "New York":      "#dc2626",
    "Boston":        "#2563eb",
    "Minneapolis":   "#16a34a",
}

START = "2021-01-01"
END   = "2025-12-31"


def fetch(lat, lon):
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat, "longitude": lon,
            "start_date": START, "end_date": END,
            "daily": "temperature_2m_mean",
            "timezone": "America/New_York",
            "temperature_unit": "fahrenheit",
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame({"date": pd.to_datetime(d["time"]), "tmean_f": d["temperature_2m_mean"]})
    df["doy"] = df["date"].dt.dayofyear
    return df[df["doy"] <= 365]


def smooth_circular(arr):
    a = np.array(arr, dtype=float)
    padded = np.concatenate([a[-7:], a, a[:7]])
    smoothed = pd.Series(padded).rolling(15, center=True, min_periods=1).mean().values
    return smoothed[7:-7]


print("Fetching data for 5 cities…")
medians = {}
for city, (lat, lon) in CITIES.items():
    print(f"  {city}…")
    df = fetch(lat, lon)
    med = df.groupby("doy")["tmean_f"].median().reindex(range(1, 366))
    medians[city] = smooth_circular(med.values)

# ── polar setup ───────────────────────────────────────────────────────────────
doys = np.arange(1, 366)
angles = (doys - 1) / 365 * 2 * np.pi

# close each loop
angles_c = np.append(angles, angles[0])

BG   = "#ffffff"
DARK = "#111111"
DIM  = "#666666"

fig = plt.figure(figsize=(11, 11), facecolor=BG)
ax  = fig.add_subplot(111, projection="polar", facecolor="#f8f9fa")

ax.set_theta_zero_location("N")
ax.set_theta_direction(-1)

for city, med in medians.items():
    vals_c = np.append(med, med[0])
    ax.plot(angles_c, vals_c,
            color=COLORS[city], linewidth=2.4,
            label=city, zorder=3)

# ── radial axis ───────────────────────────────────────────────────────────────
ax.set_rlabel_position(135)
ax.yaxis.set_tick_params(labelsize=9, colors=DIM)
tick_vals = [20, 40, 60, 80]
ax.set_yticks(tick_vals)
ax.set_yticklabels([f"{v}°F" for v in tick_vals], fontsize=9, color=DIM)
ax.set_ylim(0, 95)

# ── month labels ─────────────────────────────────────────────────────────────
months    = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
month_doy = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
month_ang = [(d - 1) / 365 * 2 * np.pi for d in month_doy]

ax.set_xticks(month_ang)
ax.set_xticklabels(months, fontsize=12, color=DARK)

ax.grid(color="#d1d5db", linewidth=0.6, alpha=0.8)
ax.spines["polar"].set_visible(False)

# ── legend ────────────────────────────────────────────────────────────────────
leg = ax.legend(
    loc="lower center",
    bbox_to_anchor=(0.5, -0.09),
    ncol=5,
    frameon=False,
    fontsize=12,
    labelcolor=DARK,
)
for line in leg.get_lines():
    line.set_linewidth(3)

# ── title ─────────────────────────────────────────────────────────────────────
fig.text(0.5, 0.97,
         "Annual Temperature Cycle by City",
         ha="center", va="top",
         fontsize=20, fontweight="bold", color=DARK)
fig.text(0.5, 0.94,
         "Median daily avg temp · 2021–2025 · ERA5 reanalysis",
         ha="center", va="top",
         fontsize=12, color=DIM)
fig.text(0.5, 0.02,
         "Source: open-meteo ERA5 archive",
         ha="center", fontsize=10, color="#aaaaaa")

out = Path("/Users/macproajb/claude_projects/manhattan_temp/city_radial_median.png")
fig.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
