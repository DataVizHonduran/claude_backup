import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date
from noaa_client import EPAAQSClient

aq = EPAAQSClient()

all_daily = []

for yr in range(1970, 2027):
    bdate = f"{yr}0101"
    edate = f"{yr}1231" if yr < 2026 else "20260719"
    params = ["ozone", "no2", "co", "so2"]
    if yr >= 1999:
        params.append("pm25")
    print(f"Fetching {yr}...", flush=True)
    for param in params:
        try:
            df = aq.daily_by_cbsa(cbsa="35620", param=param, bdate=bdate, edate=edate)
            if df.empty:
                continue
            df["param"] = param
            all_daily.append(df[["date_local", "aqi", "param"]])
            print(f"  {param}: {df['date_local'].nunique()} days", flush=True)
        except Exception as e:
            print(f"  {param}: ERROR {e}", flush=True)
    print(f"  {yr} done", flush=True)

if not all_daily:
    print("No data returned.")
    sys.exit(1)

daily = pd.concat(all_daily, ignore_index=True).dropna(subset=["aqi"])

# Composite AQI = max across all pollutants per day
daily_max = (
    daily.groupby("date_local")["aqi"]
    .max()
    .reset_index()
    .rename(columns={"aqi": "aqi_composite"})
    .sort_values("date_local")
    .reset_index(drop=True)
)

print(f"\nTotal days: {len(daily_max)}", flush=True)
print(f"Date range: {daily_max['date_local'].min().date()} → {daily_max['date_local'].max().date()}", flush=True)
print(f"Max AQI: {daily_max['aqi_composite'].max():.0f} on {daily_max.loc[daily_max['aqi_composite'].idxmax(), 'date_local'].date()}", flush=True)

csv_path = "/Users/macproajb/claude_projects/noaa_client/AQI_NYC_composite_daily.csv"
daily_max["date"] = daily_max["date_local"].dt.strftime("%Y-%m-%d")
daily_max[["date", "aqi_composite"]].rename(columns={"aqi_composite": "aqi"}).to_csv(csv_path, index=False)
print(f"CSV saved: {csv_path}", flush=True)

# 30-day rolling average
daily_max["rolling30"] = daily_max["aqi_composite"].rolling(30, center=True).mean()

# Trend line
x_num = (daily_max["date_local"] - daily_max["date_local"].min()).dt.days.astype(float)
z = np.polyfit(x_num, daily_max["aqi_composite"], 1)
p = np.poly1d(z)

# Color each point by AQI category
def aqi_color(val):
    if val <= 50:  return "#00e400"
    if val <= 100: return "#ffff00"
    if val <= 150: return "#ff7e00"
    if val <= 200: return "#ff0000"
    return "#8f3f97"

colors = [aqi_color(v) for v in daily_max["aqi_composite"]]

fig = go.Figure()

# AQI category bands
for lo, hi, color, label in [
    (0,   50,  "#00e400", "Good"),
    (50,  100, "#ffff00", "Moderate"),
    (100, 150, "#ff7e00", "Unhealthy for Sensitive Groups"),
    (150, 200, "#ff0000", "Unhealthy"),
    (200, 300, "#8f3f97", "Very Unhealthy"),
]:
    fig.add_hrect(y0=lo, y1=hi, fillcolor=color, opacity=0.06, line_width=0,
                  annotation_text=label, annotation_position="right",
                  annotation_font_size=10, annotation_font_color="#777")

# Daily dots
fig.add_trace(go.Scatter(
    x=daily_max["date_local"],
    y=daily_max["aqi_composite"],
    mode="markers",
    marker=dict(size=3, color=colors, opacity=0.45),
    name="Daily AQI",
    hovertemplate="<b>%{x|%b %d, %Y}</b><br>AQI: %{y:.0f}<extra></extra>",
))

# 30-day rolling avg
fig.add_trace(go.Scatter(
    x=daily_max["date_local"],
    y=daily_max["rolling30"],
    mode="lines",
    line=dict(color="#2c5f8a", width=2),
    name="30-day avg",
    hovertemplate="30-day avg: %{y:.1f}<extra></extra>",
))

# Trend
fig.add_trace(go.Scatter(
    x=daily_max["date_local"],
    y=p(x_num),
    mode="lines",
    line=dict(color="#e74c3c", width=1.5, dash="dash"),
    name=f"Trend ({z[0]*365:+.2f} AQI/yr)",
    hoverinfo="skip",
))

fig.update_layout(
    title=dict(
        text="<b>NYC Metro Daily AQI — 30 Years (1996–2026)</b><br>"
             "<sup>Composite AQI (max of PM2.5, Ozone, NO₂, CO, SO₂) · EPA AQS CBSA 35620 · dots=daily, line=30-day avg</sup>",
        x=0.5, xanchor="center", font_size=17,
    ),
    xaxis=dict(title="Date", showgrid=True, gridcolor="#eee", rangeslider=dict(visible=True)),
    yaxis=dict(title="AQI", showgrid=True, gridcolor="#eee"),
    plot_bgcolor="white",
    paper_bgcolor="white",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=60, r=160, t=100, b=80),
    hovermode="x unified",
    width=1200, height=600,
)

fname = f"/Users/macproajb/claude_projects/noaa_client/AQI_NYC_composite_daily_55yr_{date.today()}.html"
fig.write_html(fname)
print(f"\nSaved: {fname}")
