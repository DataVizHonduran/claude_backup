"""
EIA Weekly U.S. Imports of Total Gasoline — Seasonal Chart
Data: EIA API v2, series PET.WGTIMUS2.W (NUS-Z00, product EPM0, process IM0)
"""
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date

TODAY = date.today()
API_KEY = "DEMO_KEY"
WINDOW_DAYS = 365
HISTORY_YEARS = 5

# ── 1. Fetch weekly imports series ──────────────────────────────────────
print("Fetching EIA weekly gasoline imports (PET.WGTIMUS2.W)...")
params = {"api_key": API_KEY}
r = requests.get("https://api.eia.gov/v2/seriesid/PET.WGTIMUS2.W", params=params, timeout=30)
r.raise_for_status()
rows = r.json()["response"]["data"]

df = pd.DataFrame(rows)
df["date"] = pd.to_datetime(df["period"])
df["value"] = pd.to_numeric(df["value"], errors="coerce")
s = df.set_index("date")["value"].sort_index().dropna()
print(f"  {len(s)} weekly obs  |  {s.index[0].date()} – {s.index[-1].date()}")
print(f"  Latest: {s.iloc[-1]:,.0f} thousand barrels/day")

# ── 2. Seasonal band — 5yr min/max by day-of-year, ±7 day window ───────
cutoff = s.index.max() - pd.Timedelta(days=WINDOW_DAYS)
current = s[s.index >= cutoff]

end_date = current.index.min() - pd.Timedelta(days=1)
start_date = end_date - pd.DateOffset(years=HISTORY_YEARS)
hist = s[start_date:end_date]
hist_doy = hist.index.dayofyear

lo_vals, hi_vals = [], []
for dt in current.index:
    target_doy = dt.dayofyear
    mask = (hist_doy >= target_doy - 7) & (hist_doy <= target_doy + 7)
    bucket = hist[mask]
    if len(bucket) >= 3:
        lo_vals.append(bucket.min())
        hi_vals.append(bucket.max())
    else:
        lo_vals.append(np.nan)
        hi_vals.append(np.nan)

lo = pd.Series(lo_vals, index=current.index).interpolate(limit_direction="both")
hi = pd.Series(hi_vals, index=current.index).interpolate(limit_direction="both")

# ── 3. Chart ─────────────────────────────────────────────────────────────
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=current.index, y=hi, mode="lines", line=dict(width=0),
    showlegend=False, hoverinfo="skip",
))
fig.add_trace(go.Scatter(
    x=current.index, y=lo, mode="lines", line=dict(width=0),
    fill="tonexty", fillcolor="rgba(128,128,128,0.35)",
    name=f"{HISTORY_YEARS}-Year Range", hoverinfo="skip",
))
fig.add_trace(go.Scatter(
    x=current.index, y=current.values, mode="lines",
    name="Weekly Imports", line=dict(color="#2196F3", width=2),
    hovertemplate="%{x|%b %d, %Y}<br>%{y:,.0f} KB/D<extra></extra>",
))

fig.update_layout(
    title="U.S. Imports of Total Gasoline — Last 52 Weeks vs. 5-Year Range",
    height=520, template="plotly_white",
    legend=dict(orientation="h", y=1.08), hovermode="x unified",
    font=dict(family="Arial"),
)
fig.update_yaxes(title_text="Thousand Barrels per Day", tickformat=",")
fig.add_annotation(
    text="Source: EIA Weekly Petroleum Status Report",
    xref="paper", yref="paper", x=0.5, y=-0.18, showarrow=False,
    font=dict(size=10, color="#666"),
)

fname = f"/Users/macproajb/claude_projects/fred_client/EIA_GAS_IMPORTS_SEASONAL_{TODAY}.html"
fig.write_html(fname)
print(f"\nSaved: {fname}")
