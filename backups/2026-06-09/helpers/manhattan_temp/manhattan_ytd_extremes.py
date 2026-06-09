"""Hot days (above 90th pct) Jan 1–May 18, each year 2006–2026.
   20-year rolling lookback baseline: year Y uses Y-20 to Y-1.
"""
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import date
from pathlib import Path

# ── fetch data back to 1985 ───────────────────────────────────────────────────
CSV = Path("/Users/macproajb/claude_projects/manhattan_daily_temp_40yr.csv")

def fetch():
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": 40.7829, "longitude": -73.9654,
            "start_date": "1985-01-01",
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

# ── 20-year rolling lookback percentile, Jan 1–May 18 ────────────────────────
CUTOFF_DOY = 138   # May 18
CHART_YEARS = list(range(2006, 2027))

window = df[df["doy"] <= CUTOFF_DOY].copy()

# pre-group all DOY values by year for fast lookup
by_doy_year = window.groupby(["doy", "year"])["tmean_f"].first()

def pct_rank(base_vals, val):
    n = len(base_vals)
    return sum(b <= val for b in base_vals) / n * 100 if n else np.nan

hot_counts = {}
for yr in CHART_YEARS:
    base_years = list(range(yr - 20, yr))   # strict 20-year lookback
    hot = 0
    for doy in range(1, CUTOFF_DOY + 1):
        try:
            val = by_doy_year.loc[(doy, yr)]
        except KeyError:
            continue
        base_vals = [by_doy_year.loc[(doy, by)] for by in base_years
                     if (doy, by) in by_doy_year.index]
        if len(base_vals) >= 10:   # require at least 10 years of history
            if pct_rank(base_vals, val) > 90:
                hot += 1
    hot_counts[yr] = hot

counts = pd.DataFrame({"year": list(hot_counts.keys()),
                        "hot_days": list(hot_counts.values())})

# ── palette ───────────────────────────────────────────────────────────────────
BG   = "#ffffff"
DARK = "#111111"
DIM  = "#666666"
GRID = "#e5e7eb"
RED  = "#dc2626"
GREY = "#94a3b8"

colors = [RED if y == 2026 else GREY for y in counts["year"]]

# ── figure ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 6), facecolor=BG)
ax.set_facecolor(BG)

bars = ax.bar(counts["year"], counts["hot_days"], color=colors, width=0.7, zorder=3)

for bar, val in zip(bars, counts["hot_days"]):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
            str(int(val)), ha="center", va="bottom", fontsize=9.5, color=DIM)

mean_excl = counts[counts["year"] < 2026]["hot_days"].mean()
ax.axhline(mean_excl, color="#aaaaaa", linewidth=1.0, linestyle="--", zorder=2)
ax.text(counts["year"].max() + 0.4, mean_excl,
        f" avg\n ({mean_excl:.0f})", fontsize=9, color="#aaaaaa", va="center")

# ── axes ─────────────────────────────────────────────────────────────────────
ax.set_xticks(counts["year"])
ax.set_xticklabels(counts["year"], fontsize=11, color=DARK)
ax.set_ylim(0, counts["hot_days"].max() + 8)
ax.set_ylabel("Days above 90th percentile", fontsize=11, color=DIM)
ax.tick_params(axis="both", length=0, labelsize=11)
ax.tick_params(axis="y", colors=DIM)

for spine in ax.spines.values():
    spine.set_visible(False)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

# ── titles ────────────────────────────────────────────────────────────────────
ax.set_title("Manhattan: Days Above 90th Percentile, Jan 1 – May 18",
             fontsize=18, fontweight="bold", color=DARK, pad=14, loc="left")
fig.text(0.065, 0.915,
         "Same 138-day window each year  ·  20-year rolling lookback baseline  ·  ERA5",
         fontsize=11, color=DIM)
fig.text(0.5, 0.01,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", fontsize=10, color="#aaaaaa")

plt.tight_layout(rect=[0, 0.03, 1, 1])

out = "/Users/macproajb/claude_projects/manhattan_ytd_extremes.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
print(counts.to_string(index=False))
