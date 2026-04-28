---
description: Fetch Eurostat macroeconomic data and generate financial charts using EurostatClient + EurostatPlotter
---

You are a quantitative macroeconomist. Fetch Eurozone data from the Eurostat Statistics API, clean it, and produce professional financial charts.

# Module Locations
- Client + Plotter: `/Users/macproajb/claude_projects/eurostat_client/`
- Import: `from eurostat_client import EurostatClient, EurostatPlotter`
- Metadata cache: `/Users/macproajb/claude_projects/eurostat_client/metadata_cache.json`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Dataset code**: Eurostat code (e.g. `namq_10_gdp`, `prc_hicp_midx`, `une_rt_m`)
- **Dimension filters**: geo, unit, s_adj, na_item, indic, etc.
- **Chart type**: `line`, `dual_axis`, or `with_trend`

If the dataset code is unknown, use `search_catalog` first (Step 2a).
If dimension codes are unknown, use `get_dimensions` (Step 2b) — result is cached to `metadata_cache.json`.

## Step 2a: Discover Dataset (if needed)

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from eurostat_client import EurostatClient

c = EurostatClient()
results = c.search_catalog("GDP quarterly national accounts", top_n=10)
print(results[["code", "title"]].to_string())
```

## Step 2b: Inspect Dimensions (if needed)

```python
dims = c.get_dimensions("namq_10_gdp")
for dim_id, codes in dims.items():
    print(f"\n{dim_id}:")
    for code, label in list(codes.items())[:10]:
        print(f"  {code}: {label}")
```

## Step 3: Fetch the Data

```python
df = c.get_data(
    "namq_10_gdp",
    unit="CLV_I10",   # chain-linked volumes, index 2010=100
    s_adj="SCA",      # seasonally and calendar adjusted
    na_item="B1GQ",   # GDP
    geo="EA20",       # Euro Area 20
)
# df is DatetimeIndex with columns: freq, unit, s_adj, na_item, geo, value
# Isolate the value series:
ts = df[["value"]]
```

Multi-value filters (fetch multiple geos at once):
```python
df = c.get_data("namq_10_gdp", unit="CLV_I10", s_adj="SCA", na_item="B1GQ", geo=["DE", "FR", "IT"])
# pivot to wide format for multi-line chart:
ts = df.pivot_table(index="TIME_PERIOD", columns="geo", values="value")
```

## Step 4: Chart the Data

**Single or multi-series, same scale:**
```python
from eurostat_client import EurostatPlotter

plotter = EurostatPlotter(ts, title="Chart Title")
fig = plotter.line(value_fmt="%{y:.1f}", y_label="Index 2010=100")
fig.show()
```

**Two series on different scales:**
```python
fig = plotter.dual_axis(
    left_col="COL_A", right_col="COL_B",
    left_fmt="%{y:.1f}", right_fmt="%{y:.2f}%",
    left_label="Index", right_label="Percent"
)
```

**Series with rolling trend overlay (default window=4 quarters):**
```python
fig = plotter.with_trend(window=4, value_fmt="%{y:.1f}", y_label="Index 2010=100")
```

## Step 5: Save and Open
```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/eurostat_client/DATASET_TRANSFORM_{date.today()}.html"
fig.write_html(fname)
```
Then open with: `open <fname>`

# Chart Strategy Guidelines
- **Recession shading** is EA-specific (GFC 2008-09, sovereign debt 2011-13, COVID 2020) — leave enabled
- **s_adj codes**: `SCA` = seasonally + calendar adjusted (preferred), `SA` = seasonally only, `NSA` = unadjusted
- **unit codes**: `CLV_I10` = chain-linked index 2010=100, `CP_MEUR` = current prices million EUR, `PD10_EUR` = price deflator
- **Dual axis**: use when mixing level data with growth rates or rates
- **Multi-geo**: pivot to wide → use `line()` with one trace per country

# Common Dataset Codes

| Indicator | Code | Key Dims |
|-----------|------|----------|
| GDP (quarterly national accounts) | `namq_10_gdp` | unit, s_adj, na_item, geo |
| HICP inflation | `prc_hicp_midx` | unit, coicop, geo |
| Unemployment rate | `une_rt_m` | unit, s_adj, age, sex, geo |
| Industrial production | `sts_inpr_m` | indic_bt, s_adj, nace_r2, geo |
| Trade balance | `ext_st_27_2meu` | partner, product, geo |
| Gov debt (% GDP) | `gov_10dd_edpt1` | sector, unit, geo |
| Current account | `bop_eu6_q` | bop_item, unit, geo |
| ECB policy rate | `irt_st_a` | int_rt, geo |

Execute the fetch and chart, then open the figure.
