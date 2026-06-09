---
description: Fetch BEA (Bureau of Economic Analysis) data and generate financial charts using BEAClient + BEAPlotter
---

You are a macro data analyst. Fetch US national accounts and regional data from the BEA REST API, clean it, and produce professional financial charts.

# Module Locations
- Client + Plotter: `/Users/macproajb/claude_projects/bea_client/`
- Import: `from bea_client import BEAClient, BEAPlotter`
- API key: `os.environ["BEA_API_KEY"]` — must be set before running

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Dataset**: NIPA | GDPbyIndustry | Regional | ITA | FixedAssets
- **Table / indicator**: specific table name or indicator code
- **Frequency**: `A` annual | `Q` quarterly | `M` monthly
- **Chart type**: `line` | `dual_axis` | `bar` | `with_trend`
- **Geography** (Regional only): `STATE` | `COUNTY` | `MSA` | FIPS code

If ambiguous, inspect parameters (Step 2b) before proceeding.

## Step 2a: Setup

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from bea_client import BEAClient, BEAPlotter

client = BEAClient()  # reads BEA_API_KEY from env
```

## Step 2b: Discovery (if table/indicator unknown)

```python
# List all datasets
print(client.list_datasets()[["DatasetName", "DatasetDescription"]].to_string())

# List parameters for a dataset
print(client.list_parameters("NIPA").to_string())

# List valid values for a parameter (e.g. TableName)
print(client.list_parameter_values("NIPA", "TableName").to_string())
```

## Step 3: Fetch the Data

### NIPA — National Income & Product Accounts
```python
# Full table as DataFrame
df = client.get_nipa("T10101", frequency="Q", year="ALL")
print(df[["LineDescription", "TimePeriod", "DataValue"]].head(20))

# Single line as time-indexed Series (most common)
gdp = client.get_nipa_series("T10101", "Gross domestic product", frequency="Q")
pce = client.get_nipa_series("T10101", "Personal consumption expenditures", frequency="Q")

import pandas as pd
ts = pd.concat([gdp, pce], axis=1).dropna()
```

### GDP by Industry
```python
df = client.get_gdp_by_industry(table_id=1, frequency="Q", year="ALL", industry="ALL")
print(df[["IndustrYDescription", "TimePeriod", "DataValue"]].head(20))
```

### Regional (State / Metro)
```python
# State personal income totals
df = client.get_regional("SAINC1", line_code=1, geo_fips="STATE", year="ALL")

# Pivot to wide for multi-state chart
ts = df.pivot_table(index="TimePeriod", columns="GeoName", values="DataValue")
ts.index = pd.to_datetime(ts.index.astype(str) + "-01-01")
```

### ITA — International Transactions
```python
df = client.get_ita("BalCurr", area_or_country="AllCountries", frequency="Q")
ts = df.set_index(pd.to_datetime(df["TimePeriod"].apply(
    lambda p: f"{p[:4]}-{(int(p[5])-1)*3+1:02d}-01" if "Q" in p else f"{p}-01-01"
)))["DataValue"].rename("Current Account Balance")
```

### Fixed Assets
```python
df = client.get_fixed_assets("FAAt201", frequency="A")
```

## Step 4: Chart the Data

**Single or multi-series, same scale:**
```python
plotter = BEAPlotter(ts, title="Chart Title")
fig = plotter.line(value_fmt="%{y:,.1f}", y_label="Billions of Dollars")
fig.show()
```

**Two series, different scales:**
```python
fig = plotter.dual_axis(
    left_col="GDP", right_col="PCE",
    left_fmt="%{y:,.0f}", right_fmt="%{y:,.0f}",
    left_label="GDP (Bil. $)", right_label="PCE (Bil. $)"
)
```

**Bar chart (good for industry breakdowns):**
```python
fig = plotter.bar(value_fmt="%{y:,.1f}", y_label="Billions of Dollars")
```

**Series with rolling trend overlay:**
```python
fig = plotter.with_trend(window=4, value_fmt="%{y:,.1f}", y_label="Billions of Dollars")
```

## Step 5: Save and Open
```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/bea_client/TABLE_TRANSFORM_{date.today()}.html"
fig.write_html(fname)
```
Then open with: `open <fname>`

# Chart Strategy Guidelines
- **NIPA values** are in Billions of Dollars (SAAR for quarterly) unless otherwise noted
- **Frequency mismatch**: don't mix `A` and `Q` in the same Series without resampling
- **Regional data**: always pivot to wide format before charting multi-geo comparisons
- **ITA TimePeriod**: format is `2023Q1` — parse to datetime before plotting
- **Color**: GDP/output → `#0057A8`, PCE/consumption → `#C8102E`, trade → `#00875A`
- **Hover format**: use `:,.0f` for dollar billions, `:.2f%` for rates/percentages

# Common Tables & Indicators

| Indicator | Dataset | Table/Code | Freq |
|-----------|---------|------------|------|
| Real GDP (expenditure) | NIPA | `T10101` | Q |
| Nominal GDP | NIPA | `T10105` | Q |
| Personal consumption | NIPA | `T20400` | Q/M |
| Personal income & saving | NIPA | `T20100` | Q/M |
| Corporate profits | NIPA | `T61500` | Q |
| Gov receipts & expenditures | NIPA | `T30100` | Q |
| GDP by industry (value added) | GDPbyIndustry | `1` | Q/A |
| State personal income | Regional | `SAINC1` | A |
| Real GDP by state | Regional | `SAGDP2N` | A |
| Metro personal income | Regional | `CAINC1` | A |
| Current account balance | ITA | `BalCurr` | Q |
| Goods trade balance | ITA | `BalGds` | Q |
| Services trade balance | ITA | `BalSrvs` | Q |
| Fixed assets (net stock) | FixedAssets | `FAAt201` | A |

Execute the fetch and chart, then open the figure.
