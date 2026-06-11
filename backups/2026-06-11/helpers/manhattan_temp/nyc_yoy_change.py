import pandas as pd
import numpy as np
import plotly.graph_objects as go

df = pd.read_csv(
    "/Users/macproajb/claude_projects/manhattan_temp/manhattan_daily_temp_56yr.csv",
    parse_dates=["date"],
)
df["year"] = df["date"].dt.year
df = df[df["date"].dt.dayofyear <= 365]

annual = df.groupby("year")["tmean_f"].mean()
yoy    = annual.diff()          # current - previous year
yoy    = yoy.dropna()

colors = ["#D62728" if v >= 0 else "#4E79A7" for v in yoy]

fig = go.Figure()

fig.add_trace(go.Bar(
    x=yoy.index, y=yoy.values,
    marker_color=colors,
    name="YoY change",
    hovertemplate="Year %{x}<br>Change: %{y:+.2f}°F<extra></extra>",
))

fig.add_hline(y=0, line_color="#888", line_width=1)

# 5-yr rolling mean of the changes
smooth = yoy.rolling(5, center=True, min_periods=3).mean()
fig.add_trace(go.Scatter(
    x=smooth.index, y=smooth.values,
    mode="lines",
    line=dict(color="#222222", width=2.5),
    name="5-yr avg",
    hovertemplate="Year %{x}<br>5-yr avg: %{y:+.2f}°F<extra></extra>",
))

fig.update_layout(
    width=1100, height=500,
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#F7F7F7",
    title=dict(
        text=(
            "<b>NYC Year-on-Year Change in Average Daily Temperature</b><br>"
            "<sup>1971–2026 · °F · ERA5 reanalysis · Central Park</sup>"
        ),
        x=0.5, xanchor="center",
        font=dict(size=16, color="#222"),
    ),
    xaxis=dict(showgrid=False, tickfont=dict(size=12), dtick=5),
    yaxis=dict(
        title="°F change vs prior year",
        showgrid=True, gridcolor="rgba(180,180,180,0.4)",
        ticksuffix="°", zeroline=False,
        tickfont=dict(size=11),
    ),
    legend=dict(x=0.02, y=0.98, bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#ccc", borderwidth=1, font=dict(size=11)),
    bargap=0.2,
)

out = "/Users/macproajb/claude_projects/nyc_yoy_change.html"
fig.write_html(out)
print(f"Saved → {out}")
