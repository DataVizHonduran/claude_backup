import pandas as pd
import numpy as np
import plotly.graph_objects as go

df = pd.read_csv("/Users/macproajb/claude_projects/manhattan_daily_temperature.csv", parse_dates=["date"])
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365]  # drop leap day (Feb 29)

# ── stats over full 20-year history ──────────────────────────────────────────
grp = df.groupby("doy")["tmean_f"]
stats = pd.DataFrame({
    "doy":    np.arange(1, 366),
    "median": grp.median().reindex(range(1, 366)).values,
    "p20":    grp.quantile(0.20).reindex(range(1, 366)).values,
    "p80":    grp.quantile(0.80).reindex(range(1, 366)).values,
})

# 7-day rolling smooth for clean curves (wrap edges to avoid boundary artifacts)
for col in ("median", "p20", "p80"):
    arr = stats[col].values
    padded = np.concatenate([arr[-3:], arr, arr[:3]])
    smoothed = pd.Series(padded).rolling(7, center=True, min_periods=1).mean().values
    stats[col] = smoothed[3:-3]

# 2026 (YTD)
yr26 = df[df["year"] == 2026].sort_values("doy").copy()
yr26["smooth"] = yr26["tmean_f"].rolling(7, center=True, min_periods=1).mean()

# ── angle: DOY → degrees (Jan 1 = 0° = 12 o'clock, clockwise) ──────────────
stats["angle"] = (stats["doy"] - 1) / 365 * 360
yr26["angle"]  = (yr26["doy"]  - 1) / 365 * 360

# ── percentile band polygon ───────────────────────────────────────────────────
# Outer ring (p80) clockwise 0→360, inner ring (p20) counterclockwise 360→0
outer_theta = list(stats["angle"]) + [360.0]
outer_r     = list(stats["p80"])   + [stats["p80"].iloc[0]]

inner_theta = list(stats["angle"].iloc[::-1])
inner_r     = list(stats["p20"].iloc[::-1])

band_theta = outer_theta + inner_theta
band_r     = outer_r     + inner_r

# ── median / 2026 closed loops ───────────────────────────────────────────────
med_theta = list(stats["angle"]) + [360.0]
med_r     = list(stats["median"]) + [stats["median"].iloc[0]]

# ── month tick labels ─────────────────────────────────────────────────────────
months     = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
month_doy  = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
month_ang  = [(d - 1) / 365 * 360 for d in month_doy]

# ── build figure ─────────────────────────────────────────────────────────────
fig = go.Figure()

# 1. Shaded band
fig.add_trace(go.Scatterpolar(
    theta=band_theta,
    r=band_r,
    fill="toself",
    fillcolor="rgba(150,150,150,0.30)",
    line=dict(width=0),
    name="20–80th pct",
    hoverinfo="skip",
))

# 2. Median (light blue)
fig.add_trace(go.Scatterpolar(
    theta=med_theta,
    r=med_r,
    mode="lines",
    line=dict(color="#5BB8D4", width=2.5),
    name="Median  (2006–2025)",
))

# 3. 2026 (red, YTD)
fig.add_trace(go.Scatterpolar(
    theta=list(yr26["angle"]),
    r=list(yr26["smooth"]),
    mode="lines",
    line=dict(color="#D62728", width=2.5),
    name="2026 (YTD)",
))

# ── layout ────────────────────────────────────────────────────────────────────
fig.update_layout(
    width=820, height=820,
    paper_bgcolor="#FFFFFF",
    title=dict(
        text="<b>Manhattan Daily Temperature</b><br>"
             "<sup>20-yr median · 20–80th percentile · 2026 YTD · °F (7-day smooth)</sup>",
        x=0.5, xanchor="center",
        font=dict(size=16, color="#222"),
        y=0.97,
    ),
    legend=dict(
        x=0.80, y=0.10,
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="#ccc", borderwidth=1,
        font=dict(size=12),
    ),
    polar=dict(
        bgcolor="#F7F7F7",
        angularaxis=dict(
            direction="clockwise",
            rotation=90,           # 0° → 12 o'clock
            tickmode="array",
            tickvals=month_ang,
            ticktext=months,
            tickfont=dict(size=13, color="#333"),
            showline=True,
            linecolor="#bbb",
            showgrid=True,
            gridcolor="rgba(180,180,180,0.4)",
            gridwidth=1,
        ),
        radialaxis=dict(
            range=[0, 97],
            ticksuffix="°",
            tickvals=[20, 40, 60, 80],
            tickfont=dict(size=10, color="#555"),
            showgrid=True,
            gridcolor="rgba(180,180,180,0.4)",
            gridwidth=1,
            showline=False,
            angle=0,               # radial labels at 12 o'clock
        ),
    ),
)

out = "/Users/macproajb/claude_projects/manhattan_temp_radial.html"
fig.write_html(out)
print(f"Saved → {out}")
