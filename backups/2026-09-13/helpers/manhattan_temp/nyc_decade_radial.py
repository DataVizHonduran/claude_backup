import pandas as pd
import numpy as np
import plotly.graph_objects as go

# ── load & tag ────────────────────────────────────────────────────────────────
df = pd.read_csv(
    "/Users/macproajb/claude_projects/manhattan_temp/manhattan_daily_temp_56yr.csv",
    parse_dates=["date"],
)
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365]  # drop Feb 29

def decade_label(y):
    if 1970 <= y <= 1979: return "1970s"
    if 1980 <= y <= 1989: return "1980s"
    if 1990 <= y <= 1999: return "1990s"
    if 2000 <= y <= 2009: return "2000s"
    if 2010 <= y <= 2019: return "2010s"
    if 2020 <= y <= 2029: return "2020s"
    return None

df["decade"] = df["year"].map(decade_label)
df = df.dropna(subset=["decade"])

# ── helpers ───────────────────────────────────────────────────────────────────
def smooth(arr, window=7, pad=3):
    a = np.array(arr, dtype=float)
    padded = np.concatenate([a[-pad:], a, a[:pad]])
    s = pd.Series(padded).rolling(window, center=True, min_periods=1).mean().values
    return s[pad:-pad]

DECADES = ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]
LABELS  = ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s (to date)"]
COLORS  = {
    "1970s": "#1F77B4",
    "1980s": "#17BECF",
    "1990s": "#2CA02C",
    "2000s": "#BCBD22",
    "2010s": "#FF7F0E",
    "2020s": "#D62728",
}
doys   = np.arange(1, 366)
angles = (doys - 1) / 365 * 360   # 0° = Jan 1 = 12 o'clock

# ── month ticks ───────────────────────────────────────────────────────────────
months    = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
month_doy = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
month_ang = [(d - 1) / 365 * 360 for d in month_doy]

# ── build figure ──────────────────────────────────────────────────────────────
fig = go.Figure()

for dec, label in zip(DECADES, LABELS):
    sub = df[df["decade"] == dec]
    grp = sub.groupby("doy")["tmean_f"]

    p50 = smooth(grp.quantile(0.50).reindex(doys).values)

    med_theta = list(angles) + [angles[0]]
    med_r     = list(p50)    + [p50[0]]
    fig.add_trace(go.Scatterpolar(
        theta=med_theta,
        r=med_r,
        mode="lines",
        line=dict(color=COLORS[dec], width=2.5),
        name=label,
    ))

# ── layout ────────────────────────────────────────────────────────────────────
fig.update_layout(
    width=860, height=860,
    paper_bgcolor="#FFFFFF",
    title=dict(
        text=(
            "<b>NYC Temperature by Decade</b><br>"
            "<sup>10–90th percentile band · median line · °F (7-day smooth) · Central Park</sup>"
        ),
        x=0.5, xanchor="center",
        font=dict(size=16, color="#222"),
        y=0.97,
    ),
    legend=dict(
        x=0.78, y=0.12,
        bgcolor="rgba(255,255,255,0.90)",
        bordercolor="#ccc", borderwidth=1,
        font=dict(size=11),
        tracegroupgap=2,
    ),
    polar=dict(
        bgcolor="#F7F7F7",
        angularaxis=dict(
            direction="clockwise",
            rotation=90,
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
            angle=0,
        ),
    ),
)

out = "/Users/macproajb/claude_projects/nyc_decade_radial.html"
fig.write_html(out)
print(f"Saved → {out}")
