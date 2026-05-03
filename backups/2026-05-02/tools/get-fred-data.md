---
description: Fetch FRED series and generate financial charts using FredClient + FredPlotter
---

You are a macro data analyst. Fetch one or more FRED series, clean them, and produce professional financial charts.

# Module Locations
- Client + Plotter: `/Users/macproajb/claude_projects/fred_client/`
- Import: `from fred_client import FredClient, FredPlotter`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Series IDs**: FRED identifiers (e.g. `GDP`, `UNRATE`, `FEDFUNDS`, `CPIAUCSL`)
- **Chart type**: `line`, `dual_axis`, or `with_trend`
- **Date range**: `observation_start` / `observation_end` (default: last 20 years)
- **Frequency**: default `MS` (month start); use `QS` for quarterly series like GDP

If ambiguous, ask before proceeding.

## Step 2: Fetch the Data

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from fred_client import FredClient, FredPlotter

client = FredClient()

# Fetch each series — adjust freq and date range as needed
df1 = client.get_series("SERIES_ID", freq="MS", observation_start="2005-01-01")

# For multivariate: merge on index
import pandas as pd
df = pd.concat([df1, df2], axis=1)
```

## Step 3: Chart the Data

**Single series / multiple series, same scale:**
```python
plotter = FredPlotter(df, title="Chart Title")
fig = plotter.line(value_fmt="%{y:.2f}%", y_label="Percent")
fig.show()
```

**Two series on different scales (e.g. rate vs. index):**
```python
plotter = FredPlotter(df, title="Chart Title")
fig = plotter.dual_axis(
    left_col="SERIES_A", right_col="SERIES_B",
    left_fmt="%{y:.2f}%", right_fmt="%{y:,.0f}",
    left_label="Rate (%)", right_label="Index Level"
)
fig.show()
```

**Series with rolling trend overlay:**
```python
plotter = FredPlotter(df, title="Chart Title")
fig = plotter.with_trend(window=12, value_fmt="%{y:.2f}%", y_label="Percent")
fig.show()
```

## Step 4: Save and Open
Always save to `/Users/macproajb/claude_projects/fred_client/` using the naming convention:
`SERIES_TRANSFORMATION_DATE.html`

Examples:
- Single series, no transform: `FEDFUNDS_2026-04-21.html`
- Deflated by CPI: `RSXFS_REAL_CPI_2026-04-21.html`
- YoY change: `CPIAUCSL_YOY_2026-04-21.html`
- Multi-series: `DGS10_DGS2_SPREAD_2026-04-21.html`

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/fred_client/SERIES_TRANSFORM_{date.today()}.html"
fig.write_html(fname)
```

Then open with: `open <fname>`

# Chart Strategy Guidelines

- **Recession shading** is on by default — always leave enabled for macro series
- **Frequency mismatch**: if mixing daily + monthly, fetch both at `MS` or explain the tradeoff
- **Dual axis**: use when series have incompatible scales (e.g. basis points vs. percent growth)
- **Trend overlay**: use for noisy monthly series (CPI components, trade data)
- **Color**: US series → `#0057A8`, China → `#C8102E`, EM → `#00875A`
- **Hover format**: always specify `value_fmt` — never leave default (too many decimals)

# Common Series IDs

| Series | ID | Freq |
|--------|----|------|
| Fed Funds Rate | `FEDFUNDS` | Monthly |
| CPI YoY | `CPIAUCSL` | Monthly |
| Unemployment | `UNRATE` | Monthly |
| GDP | `GDP` | Quarterly |
| 10Y Treasury | `DGS10` | Daily |
| 2Y Treasury | `DGS2` | Daily |
| 10Y-2Y Spread | `T10Y2Y` | Daily |
| PCE Inflation | `PCEPI` | Monthly |
| Core PCE | `PCEPILFE` | Monthly |
| M2 Money Supply | `M2SL` | Monthly |

Execute the fetch and chart, then show the figure.
