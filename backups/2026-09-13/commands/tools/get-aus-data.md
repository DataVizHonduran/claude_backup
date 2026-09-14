---
description: Fetch Australian macro data (RBA statistical tables + ABS SDMX Data API) and generate financial charts using AbsClient/RbaClient + AusPlotter
---

You are a macro data analyst. Fetch Australian data from the RBA or ABS, clean it, and produce professional financial charts.

# Module Locations
- Client + Plotter: `/Users/macproajb/claude_projects/aus_client/`
- Import: `from aus_client import AbsClient, RbaClient, AusPlotter`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Source**: RBA (interest rates, exchange rates, CPI summary) or ABS (CPI, labour force, GDP, wages, retail trade — finer detail/SA splits)
- **Series**: map to the reference tables below, or discover (Step 2)
- **Chart type**: `line`, `dual_axis`, or `with_trend`

## Step 2a: ABS — Discover (if needed)

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from aus_client import AbsClient
c = AbsClient()

# Find a dataflow
results = c.search_dataflows("labour force")
print(results[["id", "version", "name"]])

# Inspect dimensions to build a key (dot-separated, in dimension order)
dims = c.get_dimensions("LF", version="1.0.0")
for dim_id, codes in dims.items():
    print(f"\n{dim_id}:")
    for code, label in list(codes.items())[:10]:
        print(f"  {code}: {label}")
```

## Step 2b: ABS — Fetch

```python
df = c.get_data("LF", "M13.3.1599.20.AUS.M", version="1.0.0", start_period="2010-01")
ts = df[["value"]].rename(columns={"value": "Unemployment Rate"})
```

## Step 2c: RBA — Fetch

```python
from aus_client import RbaClient
rba = RbaClient()

# Full table (all series in one DataFrame, columns = Series IDs)
table = rba.get_table("F1")

# Single series
cash = rba.get_series("F1", "FIRMMCRTD")
```

## Step 3: Transform (if needed)

```python
# YoY % change (monthly series)
yoy = s.pct_change(12) * 100

# QoQ annualized % change (quarterly)
qoq_ann = s.pct_change(1) * 400

# Resample to align mixed frequencies (e.g. daily RBA + quarterly ABS)
s_m = s.resample("MS").last()   # or .ffill() for stock-like series
```

## Step 4: Chart the Data

**Single series:**
```python
plotter = AusPlotter(ts, title="Australia: Unemployment Rate (SA)")
fig = plotter.line(value_fmt="%{y:.1f}%", y_label="Per cent")
fig.show()
```

**Two series, different scales:**
```python
import pandas as pd
df = pd.concat([cash.resample("MS").last().rename("Cash Rate Target"),
                rba.get_series("G1", "GCPIAGYP").resample("MS").ffill().rename("CPI YoY")], axis=1).dropna()

plotter = AusPlotter(df, title="Australia: Cash Rate vs CPI Inflation (YoY)")
fig = plotter.dual_axis(
    left_col="Cash Rate Target", right_col="CPI YoY",
    left_fmt="%{y:.2f}%", right_fmt="%{y:.1f}%",
    left_label="Cash Rate Target (%)", right_label="CPI YoY (%)",
)
```

**Series with trend overlay:**
```python
plotter = AusPlotter(ts, title="AUD/USD with 12M Trend")
fig = plotter.with_trend(window=12, value_fmt="%{y:.4f}", y_label="AUD/USD")
```

## Step 5: Save and Open

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/aus_client/SERIES_TRANSFORM_{date.today()}.html"
fig.write_html(fname)
```

Then open with: `open <fname>`

# Chart Strategy Guidelines

- **No API key required** for either source — fully public
- **Colors**: AU green/gold primary (`#00843D` / `#FFCD00`), rates → blue `#0057A8`
- **Hover format**: rates/inflation → `%{y:.1f}%` or `%{y:.2f}%`, FX → `%{y:.4f}`, index levels → `%{y:.1f}`
- **Frequency mismatches**: RBA F-tables are daily/monthly, ABS national accounts/CPI are quarterly — `.resample("MS")` to align before `dual_axis`
- **Trend overlay**: noisy monthly/quarterly series (CPI components, retail trade)

# Reference: ABS Dataflows (SDMX key = dot-separated dims, in dimension order)

| Dataflow | Version | Dims (order) | Example key | Series |
|----------|---------|--------------|-------------|--------|
| `LF` | 1.0.0 | MEASURE.SEX.AGE.TSEST.REGION.FREQ | `M13.3.1599.20.AUS.M` | Unemployment rate, Persons, Total, SA, Australia, Monthly |
| `LF` | 1.0.0 | (same) | `M3.3.1599.20.AUS.M` | Employed persons, Persons, SA, Australia |
| `LF` | 1.0.0 | (same) | `M12.3.1599.20.AUS.M` | Participation rate, Persons, SA, Australia |
| `CPI_Q` | 1.0.0 | MEASURE.INDEX.TSEST.REGION.FREQ | `1.10001.10.50.Q` | CPI index, All groups, Original, Weighted avg 8 capitals |
| `ANA_AGG` | 1.0.0 | MEASURE.DATA_ITEM.TSEST.REGION.FREQ | `M1.GPM.20.AUS.Q` | Real GDP, chain volume, SA, Australia, Quarterly |
| `WPI` | 1.2.0 | — | use `search_dataflows("wage")` + `get_dimensions` | Wage Price Index |
| `RT` | 1.0.0 | — | use `search_dataflows("retail")` + `get_dimensions` | Retail Trade |

`MEASURE` codes for `LF`: `M13`=Unemployment rate, `M3`=Employed persons, `M9`=Labour force, `M12`=Participation rate, `M11`=Civilian population. `TSEST`: `10`=Original, `20`=Seasonally Adjusted, `30`=Trend. `REGION`: `AUS`=Australia, `1`-`8`=states/territories.

# Reference: RBA Statistical Tables (CSV, columns = Series ID)

| Table | Content | Frequency | Key Series IDs |
|-------|---------|-----------|----------------|
| `F1` | Interest rates & money market | Daily | `FIRMMCRTD`=Cash Rate Target, `FIRMMCRID`=Interbank Overnight Cash Rate |
| `F11` | Exchange rates | Monthly | columns named `A$1=USD`, `A$1=EUR`, `A$1=CNY`, etc.; `Trade-weighted Index May 1970 = 100`=TWI |
| `G1` | CPI inflation summary | Quarterly | `GCPIAG`=CPI index, `GCPIAGYP`=Headline CPI YoY %, `GCPIOCPMTMYP`=Trimmed mean YoY %, `GCPIAGSAQP`=Headline QoQ % SA |

Run `RbaClient().get_table("<table>").columns.tolist()` to list all Series IDs in a table.

Execute the fetch and chart, then show the figure.
