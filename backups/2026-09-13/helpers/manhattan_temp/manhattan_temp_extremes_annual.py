"""Annual count of days above 90th / below 10th percentile — Manhattan 2006-2026."""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

# ── data ─────────────────────────────────────────────────────────────────────
CSV = Path("/Users/macproajb/claude_projects/manhattan_daily_temp_25yr.csv")
df  = pd.read_csv(CSV, parse_dates=["date"])
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[(df["doy"] <= 365) & (df["year"] >= 2006)]

baseline_years = list(range(2006, 2026))
all_years      = list(range(2006, 2027))

# ── compute leave-one-out percentile rank for every day ───────────────────────
records = []
for doy, grp in df.groupby("doy"):
    hist = grp[grp["year"].isin(baseline_years)].set_index("year")["tmean_f"]
    for _, row in grp.iterrows():
        yr  = row["year"]
        val = row["tmean_f"]
        if yr in baseline_years:
            base = hist.drop(index=yr, errors="ignore").values
        else:
            base = hist.values
        n   = len(base)
        pct = sum(b <= val for b in base) / n * 100 if n else np.nan
        records.append({"year": yr, "doy": doy, "pct": pct})

pct_df = pd.DataFrame(records)

# ── count extremes per year ───────────────────────────────────────────────────
counts = (
    pct_df.groupby("year")["pct"]
    .agg(hot=lambda s: (s > 90).sum(), cold=lambda s: (s < 10).sum())
    .reset_index()
)

# 2026 is partial — note how many days are in the dataset
days_2026 = pct_df[pct_df["year"] == 2026]["doy"].nunique()
partial_note = f"2026 partial\n({days_2026} days)"

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

years = counts["year"].values
x     = np.arange(len(years))
w     = 0.38

bars_hot  = ax.bar(x + w/2, counts["hot"],  width=w, color=RED,  alpha=0.8, label="Days above 90th pct")
bars_cold = ax.bar(x - w/2, counts["cold"], width=w, color=BLUE, alpha=0.8, label="Days below 10th pct")

# expected baseline (~36-37 days per threshold for a full year)
ax.axhline(36.5, color="#aaaaaa", linewidth=1.0, linestyle="--", zorder=2)
ax.text(x[-1] + 0.6, 36.5, " expected\n (~36)", fontsize=9, color="#aaaaaa", va="center")

# mark 2026 as partial
ax.axvline(x[-1] - 0.5, color="#cccccc", linewidth=0.8, linestyle=":")
ax.text(x[-1], counts["hot"].iloc[-1] + 2, partial_note,
        ha="center", fontsize=8.5, color=DIM)

# value labels on bars
for bar in list(bars_hot) + list(bars_cold):
    h = bar.get_height()
    if h > 0:
        ax.text(bar.get_x() + bar.get_width() / 2, h + 0.5,
                str(int(h)), ha="center", va="bottom", fontsize=8, color=DIM)

# ── axes ─────────────────────────────────────────────────────────────────────
ax.set_xticks(x)
ax.set_xticklabels(years, fontsize=11, color=DARK)
ax.set_ylim(0, counts[["hot","cold"]].max().max() + 12)
ax.set_ylabel("Days per year", fontsize=12, color=DIM)
ax.tick_params(axis="y", labelsize=11, colors=DIM, length=0)
ax.tick_params(axis="x", length=0)

for spine in ax.spines.values():
    spine.set_visible(False)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

ax.legend(frameon=False, fontsize=12, labelcolor=DIM, loc="upper left")

# ── titles ────────────────────────────────────────────────────────────────────
ax.set_title("Are Extreme Temperature Days Becoming More Common in Manhattan?",
             fontsize=18, fontweight="bold", color=DARK, pad=14, loc="left")
fig.text(0.065, 0.895,
         "Count of days above the 90th / below the 10th historical percentile for that calendar day  ·  2006–2025 baseline  ·  ERA5",
         fontsize=11, color=DIM)
fig.text(0.5, 0.01,
         "Source: open-meteo ERA5 archive · Central Park, NYC (40.78°N, 73.97°W)",
         ha="center", fontsize=10, color="#aaaaaa")

plt.tight_layout(rect=[0, 0.03, 1, 1])

out = "/Users/macproajb/claude_projects/manhattan_temp_extremes_annual.png"
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"Saved → {out}")
