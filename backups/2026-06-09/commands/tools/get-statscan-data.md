---
description: Fetch Statistics Canada macroeconomic data and generate financial charts using StatsCanClient + StatsCanPlotter
---

You are a macro data analyst. Fetch one or more StatsCan series, clean them, and produce professional financial charts.

# Module Locations
- Client + Plotter: `/Users/macproajb/claude_projects/statscan_client/`
- Import: `from statscan_client import StatsCanClient, StatsCanPlotter`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Vector IDs**: StatsCan series identifiers (e.g. `v2062811`). Use the reference table below or call `get_table(pid)` to discover them.
- **Chart type**: `line`, `dual_axis`, or `with_trend`
- **Lookback**: `n_periods` observations (default 200 — no date ceiling in the API, just use a large N)
- **Frequency**: determined by the series (monthly, quarterly, annual)

If the user describes a concept, map it to a vector ID using the reference below. If unknown, use `get_table()` to explore.

## Step 2: Fetch the Data

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from statscan_client import StatsCanClient, StatsCanPlotter

client = StatsCanClient()

# Single series
s = client.get_series("v2062811", n_periods=200)

# Multiple series → DataFrame
df = client.get_multi(["v2062811", "v2062815"], n_periods=200)
```

## Step 3: Transform (if needed)

```python
# YoY % change (monthly series)
yoy = s.pct_change(12) * 100

# QoQ annualized % change (quarterly)
qoq_ann = s.pct_change(1) * 400

# Resample quarterly → monthly interpolation (for mixing frequencies)
s_m = s.resample("MS").interpolate()
```

## Step 4: Chart the Data

**Single series:**
```python
plotter = StatsCanPlotter(s, title="Canada Employment, SA")
fig = plotter.line(value_fmt="%{y:,.1f}", y_label="Persons (000s)")
fig.show()
```

**Two series, different scales:**
```python
plotter = StatsCanPlotter(df, title="Employment vs Unemployment Rate")
fig = plotter.dual_axis(
    left_col="v2062811", right_col="v2062815",
    left_fmt="%{y:,.1f}", right_fmt="%{y:.1f}%",
    left_label="Employment (000s)", right_label="Unemployment Rate (%)"
)
fig.show()
```

**Series with trend overlay:**
```python
plotter = StatsCanPlotter(s, title="CPI All-items with 12M Trend")
fig = plotter.with_trend(window=12, value_fmt="%{y:.1f}", y_label="Index (2002=100)")
fig.show()
```

## Step 5: Save and Open
Always save to `/Users/macproajb/claude_projects/statscan_client/` using:
`SERIES_TRANSFORM_DATE.html`

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/statscan_client/v2062811_{date.today()}.html"
fig.write_html(fname)
```

Then open with: `open <fname>`

# Discovering Unknown Vector IDs

When a series isn't in the reference table below:

```python
# 1. Search for the table
results = client.search("retail trade")
print(results[["productId", "cubeTitleEn"]])

# 2. Download full table CSV (cached locally after first download)
df = client.get_table(20100056)
print(df.columns.tolist())

# 3. Filter to find your series and get VECTOR column
mask = (df["GEO"] == "Canada") & (df["REF_DATE"] == df["REF_DATE"].max())
print(df[mask][["Sales, adjusted", "VECTOR", "VALUE"]].to_string())
```

# Chart Strategy Guidelines

- **No API key required** — fully public
- **Vector ID format**: `v2062811` or integer `2062811` — both accepted
- **Large N for full history**: `n_periods=600` → monthly series back to 1970s; API returns all available data
- **Dual axis**: rate (%) + level (thousands, index points)
- **Trend overlay**: noisy monthly series (CPI components, retail)
- **YoY**: `s.pct_change(12) * 100` for monthly; `s.pct_change(4) * 100` for quarterly
- **Color**: Labour → `#FF0000` (Canada red), price series → `#FFFFFF`, GDP → `#0057A8`
- **Hover format**: rates use `%{y:.1f}%`, thousands use `%{y:,.1f}`, index use `%{y:.1f}`

# Common Vector IDs

## Labour Force (Table 14100287 — monthly, SA)
| Series | Vector |
|--------|--------|
| Employment, Canada, 15+, SA | `v2062811` |
| Unemployment Rate, Canada, 15+, SA | `v2062815` |
| Participation Rate, Canada, 15+, SA | `v2062816` |
| Employment Rate, Canada, 15+, SA | `v2062817` |
| Full-time Employment, Canada, SA | `v2062812` |
| Part-time Employment, Canada, SA | `v2062813` |
| Labour Force, Canada, 15+, SA | `v2062810` |
| Unemployment, Canada, 15+, SA | `v2062814` |

## Consumer Price Index (Table 18100004 — monthly, NSA)
| Series | Vector |
|--------|--------|
| CPI All-items, Canada | `v41690973` |
| CPI Food, Canada | `v41690974` |
| CPI Shelter, Canada | `v41691050` |
| CPI Energy, Canada | `v41691239` |
| CPI ex Food & Energy (Core), Canada | `v41691233` |

## GDP (Table 36100104 — quarterly, SA)
| Series | Vector |
|--------|--------|
| Real GDP at market prices (Chained 2017$, SA) | `v62305752` |
| Nominal GDP at market prices (Current $, SA) | `v62305783` |
| Household Final Consumption, Real, SA | `v62305724` |
| Gross Fixed Capital Formation, Real, SA | `v62305732` |

## Key Table PIDs for Exploration
| Table | PID | Frequency |
|-------|-----|-----------|
| Labour Force Survey (LFS) | `14100287` | Monthly |
| Consumer Price Index | `18100004` | Monthly |
| GDP expenditure-based | `36100104` | Quarterly |
| Monthly retail trade sales | `20100056` | Monthly |
| Housing starts (urban) | `34100158` | Monthly |
| Merchandise trade | `12100119` | Monthly |
| Building permits | `34100066` | Monthly |

Execute the fetch and chart, then show the figure.
