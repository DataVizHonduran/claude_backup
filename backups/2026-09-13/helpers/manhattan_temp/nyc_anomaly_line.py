import pandas as pd
import numpy as np
import plotly.graph_objects as go

# ── load ──────────────────────────────────────────────────────────────────────
df = pd.read_csv(
    "/Users/macproajb/claude_projects/manhattan_temp/manhattan_daily_temp_56yr.csv",
    parse_dates=["date"],
)
df["doy"]  = df["date"].dt.dayofyear
df["year"] = df["date"].dt.year
df = df[df["doy"] <= 365].sort_values("date").reset_index(drop=True)

# ── 1970s baseline (per DOY, 7-day circular smooth) ───────────────────────────
def smooth(arr, window=7, pad=3):
    a = np.array(arr, dtype=float)
    padded = np.concatenate([a[-pad:], a, a[:pad]])
    s = pd.Series(padded).rolling(window, center=True, min_periods=1).mean().values
    return s[pad:-pad]

doys = np.arange(1, 366)
base_raw = (
    df[df["year"].between(1970, 1979)]
    .groupby("doy")["tmean_f"]
    .median()
    .reindex(doys)
    .values
)
base_smooth = smooth(base_raw)
baseline = dict(zip(doys, base_smooth))   # {doy: baseline_temp}

# ── anomaly + 365-day rolling mean ────────────────────────────────────────────
df["anomaly"] = df["doy"].map(baseline).rsub(df["tmean_f"])  # tmean - baseline
df["roll"]    = df["anomaly"].rolling(365, center=True, min_periods=180).mean()

dates = df["date"]
roll  = df["roll"]

pos = roll.clip(lower=0)
neg = roll.clip(upper=0)

# ── figure ────────────────────────────────────────────────────────────────────
fig = go.Figure()

# above-zero (warm) fill
fig.add_trace(go.Scatter(
    x=dates, y=pos,
    fill="tozeroy",
    fillcolor="rgba(214,39,40,0.30)",
    line=dict(width=0),
    name="Above baseline",
    hoverinfo="skip",
))

# below-zero (cool) fill
fig.add_trace(go.Scatter(
    x=dates, y=neg,
    fill="tozeroy",
    fillcolor="rgba(78,121,167,0.30)",
    line=dict(width=0),
    name="Below baseline",
    hoverinfo="skip",
))

# main rolling line
fig.add_trace(go.Scatter(
    x=dates, y=roll,
    mode="lines",
    line=dict(color="#333333", width=1.8),
    name="365-day rolling mean",
    hovertemplate="%{x|%b %Y}<br>%{y:+.2f}°F<extra></extra>",
))

# zero reference
fig.add_hline(y=0, line_dash="dash", line_color="#888888", line_width=1)

# annotate latest value
last = df[["date","roll"]].dropna().iloc[-1]
fig.add_annotation(
    x=last["date"], y=last["roll"],
    text=f"<b>{last['roll']:+.1f}°F</b>",
    showarrow=True, arrowhead=2, arrowcolor="#D62728",
    font=dict(size=12, color="#D62728"),
    ax=40, ay=-30,
)

fig.update_layout(
    width=1100, height=520,
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#F7F7F7",
    title=dict(
        text=(
            "<b>NYC Daily Temperature Anomaly vs. 1970s Median</b><br>"
            "<sup>365-day rolling mean · °F · ERA5 reanalysis · Central Park</sup>"
        ),
        x=0.5, xanchor="center",
        font=dict(size=16, color="#222"),
    ),
    xaxis=dict(
        showgrid=True, gridcolor="rgba(180,180,180,0.4)",
        tickfont=dict(size=12),
    ),
    yaxis=dict(
        title="°F above / below 1970s median",
        showgrid=True, gridcolor="rgba(180,180,180,0.4)",
        ticksuffix="°",
        zeroline=False,
        tickfont=dict(size=11),
    ),
    legend=dict(
        x=0.01, y=0.99,
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="#ccc", borderwidth=1,
        font=dict(size=11),
    ),
    hovermode="x unified",
)

out = "/Users/macproajb/claude_projects/nyc_anomaly_line.html"
fig.write_html(out)
print(f"Saved → {out}")
