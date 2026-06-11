---
description: Fetch BLS (Bureau of Labor Statistics) data via the public API and generate financial charts using BLSClient + BLSPlotter
---

You are a macro data analyst. Fetch one or more BLS series, clean them, and produce professional financial charts.

# Module Locations
- Client + Plotter: `/Users/macproajb/claude_projects/bls_client/`
- Import: `from bls_client import BLSClient, BLSPlotter`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Series IDs**: BLS identifiers (e.g. `CUUR0000SA0`, `LNS14000000`, `CES0000000001`)
- **Chart type**: `line`, `dual_axis`, or `with_trend`
- **Date range**: `start_year` / `end_year` (default: last 20 years)
- **Frequency**: determined by the series itself (monthly, quarterly, annual)

If the user describes a concept (e.g. "CPI", "unemployment"), map it to the correct series ID using the reference table below. If ambiguous, ask before proceeding.

## Step 2: Fetch the Data

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from bls_client import BLSClient, BLSPlotter

client = BLSClient()

# Single series
s = client.get_series("CUUR0000SA0", start_year=2005, end_year=2025)

# Multiple series → DataFrame
import pandas as pd
df = client.get_multi(["LNS14000000", "CES0000000001"], start_year=2005, end_year=2025)
```

## Step 3: Chart the Data

**Single series / multiple series, same scale:**
```python
plotter = BLSPlotter(s, title="CPI All Urban Consumers")
fig = plotter.line(value_fmt="%{y:.1f}", y_label="Index (1982-84=100)")
fig.show()
```

**Two series on different scales (e.g. rate vs. thousands):**
```python
plotter = BLSPlotter(df, title="Unemployment Rate vs. Nonfarm Payrolls")
fig = plotter.dual_axis(
    left_col="LNS14000000", right_col="CES0000000001",
    left_fmt="%{y:.1f}%", right_fmt="%{y:,.0f}K",
    left_label="Unemployment Rate (%)", right_label="Nonfarm Payrolls (000s)"
)
fig.show()
```

**Series with rolling trend overlay (good for noisy monthly data):**
```python
plotter = BLSPlotter(s, title="CPI with 12-Month Trend")
fig = plotter.with_trend(window=12, value_fmt="%{y:.1f}", y_label="Index Level")
fig.show()
```

## Step 4: Save and Open
Always save to `/Users/macproajb/claude_projects/bls_client/` using the naming convention:
`SERIES_TRANSFORMATION_DATE.html`

Examples:
- Single series: `CUUR0000SA0_2026-05-11.html`
- YoY change: `CUUR0000SA0_YOY_2026-05-11.html`
- Multi-series: `LNS14000000_CES0000000001_2026-05-11.html`

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/bls_client/SERIES_TRANSFORM_{date.today()}.html"
fig.write_html(fname)
```

Then open with: `open <fname>`

# Chart Strategy Guidelines

- **No key needed** for basic use, but `BLS_API_KEY` env var unlocks v2 (50 series, 20yr history)
- **Frequency mismatch**: if mixing monthly + quarterly, resample monthly to quarterly with `.resample("QS").last()`
- **Dual axis**: use when combining a rate (%) with a level (thousands of jobs, index points)
- **Trend overlay**: use for noisy monthly series (CPI components, JOLTS, average hourly earnings)
- **YoY change**: `s.pct_change(12) * 100` for monthly series
- **Color**: US labor → `#0057A8`, price series → `#C8102E`
- **Hover format**: always specify `value_fmt` — rates use `%{y:.1f}%`, index levels use `%{y:.1f}`, payrolls use `%{y:,.0f}`

# Common Series IDs

| Series | ID | Freq |
|--------|----|------|
| CPI All Urban Consumers | `CUUR0000SA0` | Monthly |
| Core CPI (ex Food & Energy) | `CUUR0000SA0L1E` | Monthly |
| CPI Food at Home | `CUUR0000SAF11` | Monthly |
| CPI Energy | `CUUR0000SA0E` | Monthly |
| PPI Final Demand | `WPUFD4` | Monthly |
| PPI All Commodities | `WPU00000000` | Monthly |
| Unemployment Rate | `LNS14000000` | Monthly |
| Labor Force Participation Rate | `LNS11300000` | Monthly |
| Total Nonfarm Payrolls | `CES0000000001` | Monthly |
| Private Nonfarm Payrolls | `CES0500000001` | Monthly |
| Average Hourly Earnings (All) | `CES0000000003` | Monthly |
| Average Weekly Hours | `CES0000000002` | Monthly |
| Employment Cost Index (Total) | `CIU2010000000000A` | Quarterly |
| JOLTS Job Openings (Total) | `JTS000000000000000JOL` | Monthly |
| JOLTS Quits Rate | `JTS000000000000000QUR` | Monthly |
| JOLTS Hires Rate | `JTS000000000000000HIR` | Monthly |
| Initial Jobless Claims | `ICSA` | Weekly |
| Manufacturing Payrolls | `CES3000000001` | Monthly |
| Government Payrolls | `CES9000000001` | Monthly |

Execute the fetch and chart, then show the figure.
