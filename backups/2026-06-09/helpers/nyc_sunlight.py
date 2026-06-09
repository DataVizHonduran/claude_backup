import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
import pandas as pd
import math
import plotly.graph_objects as go
from datetime import date, timedelta

NYC_LAT = 40.7128
LON_LAT = 51.5074

def daylight_minutes(d, lat_deg):
    doy = d.timetuple().tm_yday
    decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (doy - 81))))
    lat = math.radians(lat_deg)
    cos_ha = -math.tan(lat) * math.tan(decl)
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.degrees(math.acos(cos_ha))
    return round(ha / 180 * 24 * 60, 1)

dates, nyc_min, lon_min = [], [], []
cur = date(2026, 1, 1)
end = date(2026, 12, 31)
while cur <= end:
    dates.append(cur)
    nyc_min.append(daylight_minutes(cur, NYC_LAT))
    lon_min.append(daylight_minutes(cur, LON_LAT))
    cur += timedelta(days=1)

df = pd.DataFrame({"date": dates, "nyc": nyc_min, "london": lon_min})
print(df.shape)
print(df.head())

dates_str = df["date"].astype(str)

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=dates_str, y=df["nyc"],
    name="NYC (40.7°N)", mode="lines",
    line=dict(color="#F4A136", width=2.5),
    hovertemplate="NYC: %{y:.0f} min<extra></extra>",
))
fig.add_trace(go.Scatter(
    x=dates_str, y=df["london"],
    name="London (51.5°N)", mode="lines",
    line=dict(color="#5BA4CF", width=2.5),
    hovertemplate="London: %{y:.0f} min<extra></extra>",
))

# Shade difference (London > NYC in summer, NYC > London in winter)
fig.add_trace(go.Scatter(
    x=list(dates_str) + list(dates_str[::-1]),
    y=list(df["london"]) + list(df["nyc"][::-1]),
    fill="toself",
    fillcolor="rgba(91,164,207,0.12)",
    line=dict(color="rgba(0,0,0,0)"),
    showlegend=False, hoverinfo="skip",
))

equinox_y = (df[df.date == date(2026,3,20)]["nyc"].values[0] +
             df[df.date == date(2026,3,20)]["london"].values[0]) / 2
annotations = [
    dict(x="2026-03-20", y=equinox_y, text="Spring Equinox", showarrow=True, arrowhead=2, ay=-50, ax=0),
    dict(x="2026-06-21", y=df[df.date == date(2026,6,21)]["london"].values[0],
         text="Summer Solstice", showarrow=True, arrowhead=2, ay=-40, ax=0),
    dict(x="2026-12-21", y=df[df.date == date(2026,12,21)]["nyc"].values[0],
         text="Winter Solstice", showarrow=True, arrowhead=2, ay=40, ax=0),
]

fig.update_layout(
    title=dict(text="Daily Sunlight: NYC vs London — 2026", font=dict(size=20), x=0.5),
    xaxis=dict(title="Date", tickformat="%b", dtick="M1"),
    yaxis=dict(title="Daylight (minutes)", range=[400, 1050]),
    annotations=annotations,
    plot_bgcolor="#0f0f0f",
    paper_bgcolor="#0f0f0f",
    font=dict(color="#e0e0e0"),
    legend=dict(x=0.02, y=0.98),
    hovermode="x unified",
    height=520,
)

out = "/Users/macproajb/claude_projects/nyc_london_sunlight_2026.html"
fig.write_html(out)
print(f"Chart saved: {out}")
