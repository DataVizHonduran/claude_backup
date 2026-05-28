import pandas as pd
import plotly.graph_objects as go

df = pd.read_csv(
    "/Users/macproajb/claude_projects/manhattan_temp/manhattan_daily_temp_56yr.csv",
    parse_dates=["date"],
)
df = df[df["date"].dt.dayofyear <= 365].sort_values("date").reset_index(drop=True)

df["mean100"]   = df["tmean_f"].rolling(100, center=True, min_periods=50).mean()
df["median100"] = df["tmean_f"].rolling(100, center=True, min_periods=50).median()

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=df["date"], y=df["mean100"],
    mode="lines",
    line=dict(color="#D62728", width=1.5),
    name="100-day mean",
    hovertemplate="%{x|%b %d %Y}<br>Mean: %{y:.1f}°F<extra></extra>",
))

fig.add_trace(go.Scatter(
    x=df["date"], y=df["median100"],
    mode="lines",
    line=dict(color="#4E79A7", width=1.5),
    name="100-day median",
    hovertemplate="%{x|%b %d %Y}<br>Median: %{y:.1f}°F<extra></extra>",
))

fig.update_layout(
    width=1100, height=480,
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#F7F7F7",
    title=dict(
        text=(
            "<b>NYC Temperature · 100-Day Rolling Mean & Median</b><br>"
            "<sup>1970–2026 · °F · ERA5 reanalysis · Central Park</sup>"
        ),
        x=0.5, xanchor="center",
        font=dict(size=16, color="#222"),
    ),
    xaxis=dict(showgrid=True, gridcolor="rgba(180,180,180,0.4)", tickfont=dict(size=12)),
    yaxis=dict(
        title="°F", ticksuffix="°",
        showgrid=True, gridcolor="rgba(180,180,180,0.4)",
        tickfont=dict(size=11),
    ),
    legend=dict(x=0.02, y=0.98, bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#ccc", borderwidth=1, font=dict(size=11)),
    hovermode="x unified",
)

out = "/Users/macproajb/claude_projects/nyc_100d_roll.html"
fig.write_html(out)
print(f"Saved → {out}")
