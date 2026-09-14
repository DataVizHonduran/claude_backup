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

# ── 1825-day rolling min/max/median on daily data ─────────────────────────────
print("Computing rolling percentiles (may take a moment)…")
roll = df["tmean_f"].rolling(1825, center=True, min_periods=365)
df["p10"] = roll.quantile(0.10)
df["p90"] = roll.quantile(0.90)

# ── figure ────────────────────────────────────────────────────────────────────
fig = go.Figure()

# p90 upper bound (invisible anchor)
fig.add_trace(go.Scatter(
    x=df["date"], y=df["p90"],
    mode="lines", line=dict(width=0),
    showlegend=False, hoverinfo="skip",
))

# p10 lower bound with fill
fig.add_trace(go.Scatter(
    x=df["date"], y=df["p10"],
    mode="lines", line=dict(width=0),
    fill="tonexty",
    fillcolor="rgba(214,39,40,0.25)",
    name="5-yr 10–90th percentile",
    hovertemplate="%{x|%b %Y}<br>p10: %{y:.1f}°F<extra></extra>",
))

fig.update_layout(
    width=1100, height=500,
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#F7F7F7",
    title=dict(
        text=(
            "<b>NYC Temperature · 5-Year Rolling 10–90th Percentile Band</b><br>"
            "<sup>1970–2026 · °F · ERA5 reanalysis · Central Park</sup>"
        ),
        x=0.5, xanchor="center",
        font=dict(size=16, color="#222"),
    ),
    xaxis=dict(
        showgrid=True, gridcolor="rgba(180,180,180,0.4)",
        tickfont=dict(size=12), dtick=5,
    ),
    yaxis=dict(
        title="Median daily temperature (°F)",
        showgrid=True, gridcolor="rgba(180,180,180,0.4)",
        ticksuffix="°",
        tickfont=dict(size=11),
    ),
    legend=dict(
        x=0.02, y=0.98,
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="#ccc", borderwidth=1,
        font=dict(size=11),
    ),
    hovermode="x unified",
)

out = "/Users/macproajb/claude_projects/nyc_5yr_median.html"
fig.write_html(out)
print(f"Saved → {out}")
