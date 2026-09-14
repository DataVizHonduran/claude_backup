# Regional Fed Manufacturing New Orders Dashboard

Fetch and chart two charts:
1. Current vs future new orders composite (3M smoothed, dual-axis)
2. Lead-time chart: future orders shifted forward by the empirically derived lead (cross-correlation), dual-axis, full history back to 1968 using whatever districts are available at each date

**Districts covered:** Philadelphia Fed (from May 1968), NY Empire State (from Jul 2001), Dallas Fed (from Jun 2004)  
**Note:** ISM New Orders PMI was removed from FRED due to licensing. Richmond and Kansas City don't publish new orders components on FRED. Composite uses mean of available districts at each date.

---

## Module setup

```python
import sys, requests, pandas as pd
import plotly.graph_objects as go
from datetime import date

API_KEY = "a68d4b16dd1984d0c8455381a79a8b6e"

def fetch(sid, start="1968-01-01"):
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": sid, "api_key": API_KEY, "file_type": "json",
                "observation_start": start, "frequency": "m"}
    )
    obs = r.json()["observations"]
    s = pd.Series({o["date"]: float(o["value"]) for o in obs if o["value"] != "."})
    s.index = pd.to_datetime(s.index)
    return s
```

> **Note:** Use plain `requests` — `requests_cache` breaks on Python 3.13. Never use `FredClient.get_series()` directly.

---

## Series IDs

| District | Current New Orders | Future New Orders |
|---|---|---|
| NY Empire State | `NOCDISA066MSFRBNY` | `NOFDISA066MSFRBNY` |
| Philadelphia Fed | `NOCDFSA066MSFRBPHI` | `NOFDFSA066MSFRBPHI` |
| Dallas Fed | `VNWOSAMFRBDAL` | `FVNWOSAMFRBDAL` |

All series are seasonally adjusted diffusion indices (>0 = expanding, <0 = contracting).

---

## Build composites and chart

```python
current = pd.concat([
    fetch("NOCDISA066MSFRBNY"),
    fetch("NOCDFSA066MSFRBPHI"),
    fetch("VNWOSAMFRBDAL"),
], axis=1).mean(axis=1).rolling(3, min_periods=2).mean()

future = pd.concat([
    fetch("NOFDISA066MSFRBNY"),
    fetch("NOFDFSA066MSFRBPHI"),
    fetch("FVNWOSAMFRBDAL"),
], axis=1).mean(axis=1).rolling(3, min_periods=2).mean()

fig = go.Figure()

for s, e in [("2007-12-01","2009-06-01"), ("2020-02-01","2020-04-01")]:
    fig.add_vrect(x0=s, x1=e, fillcolor="lightgrey", opacity=0.35, layer="below", line_width=0)

fig.add_trace(go.Scatter(
    x=current.index, y=current,
    name="Current New Orders",
    line=dict(color="#4E79A7", width=2),
    yaxis="y1",
    hovertemplate="<b>Current</b> %{x|%b %Y}: %{y:.1f}<extra></extra>",
))

fig.add_trace(go.Scatter(
    x=future.index, y=future,
    name="Future New Orders (6M Outlook)",
    line=dict(color="#E15759", width=2),
    yaxis="y2",
    hovertemplate="<b>Future</b> %{x|%b %Y}: %{y:.1f}<extra></extra>",
))

fig.add_hline(y=0, line_dash="dash", line_color="#333", line_width=1, opacity=0.5)

fig.update_layout(
    title=dict(
        text="Regional Fed Manufacturing New Orders — Current vs Future Composite (3M Smoothed)",
        font=dict(size=16, family="Arial"),
        x=0.5, xanchor="center",
    ),
    yaxis=dict(
        title="Current (Diffusion Index)",
        title_font=dict(color="#4E79A7"),
        tickfont=dict(color="#4E79A7"),
        gridcolor="#eee",
        zeroline=True, zerolinecolor="#4E79A7", zerolinewidth=1,
    ),
    yaxis2=dict(
        title="Future (Diffusion Index)",
        title_font=dict(color="#E15759"),
        tickfont=dict(color="#E15759"),
        overlaying="y", side="right",
        zeroline=True, zerolinecolor="#E15759", zerolinewidth=1,
        showgrid=False,
    ),
    xaxis=dict(showgrid=False),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5,
        font=dict(size=13), bgcolor="rgba(255,255,255,0.85)",
        bordercolor="#ccc", borderwidth=1,
    ),
    plot_bgcolor="white", paper_bgcolor="white",
    hovermode="x unified",
    margin=dict(t=100, b=60, l=60, r=60),
)

fname = f"/Users/macproajb/claude_projects/fred_client/REGIONAL_MFG_NEWORDERS_{date.today()}.html"
fig.write_html(fname)
```

---

## Chart 2: Lead-time chart (full history, dynamic composition)

Compute cross-correlation (lags 0–18m) to find the empirical lead of future over current, then plot both on dual axes with future shifted forward by that lag. Use all available districts at each date (mean of non-NaN). Annotate when each district joined with dotted vlines + labels. Add full-history NBER recessions. Footnote the composition changes and lead calculation.

```python
# Fetch with start="1968-01-01" so Philly history included
cur_df = pd.concat([fetch("NOCDFSA066MSFRBPHI"), fetch("NOCDISA066MSFRBNY"), fetch("VNWOSAMFRBDAL")], axis=1)
fut_df = pd.concat([fetch("NOFDFSA066MSFRBPHI"), fetch("NOFDISA066MSFRBNY"), fetch("FVNWOSAMFRBDAL")], axis=1)

current2 = cur_df.mean(axis=1).rolling(3, min_periods=2).mean()
future2  = fut_df.mean(axis=1).rolling(3, min_periods=2).mean()
df2 = pd.DataFrame({"current": current2, "future": future2}).dropna()

best_lag, best_r = max(
    ((lag, pd.concat([df2["current"], df2["future"].shift(lag)], axis=1).dropna().corr().iloc[0,1])
     for lag in range(0, 19)),
    key=lambda x: x[1]
)
future_shifted = df2["future"].shift(best_lag)

# NBER recessions (full set back to 1968)
recessions = [
    ("1969-12-01","1970-11-01"),("1973-11-01","1975-03-01"),
    ("1980-01-01","1980-07-01"),("1981-07-01","1982-11-01"),
    ("1990-07-01","1991-03-01"),("2001-03-01","2001-11-01"),
    ("2007-12-01","2009-06-01"),("2020-02-01","2020-04-01"),
]

# Dotted vlines when each district joined
addition_events = [("2001-07-01","NY added"), ("2004-06-01","Dallas added")]

footnote = (
    f"Composite average of available districts at each date. "
    f"Philadelphia Fed from May 1968; NY Empire State from Jul 2001; Dallas Fed from Jun 2004. "
    f"Future orders shifted {best_lag}m forward (peak cross-correlation r={best_r:.2f}). "
    "3-month rolling average applied. Shaded areas = NBER recessions."
)

fname2 = f"/Users/macproajb/claude_projects/fred_client/REGIONAL_MFG_LEADTIME_{date.today()}.html"
```

---

## Open charts

```bash
open /Users/macproajb/claude_projects/fred_client/REGIONAL_MFG_NEWORDERS_<date>.html
open /Users/macproajb/claude_projects/fred_client/REGIONAL_MFG_LEADTIME_<date>.html
```
