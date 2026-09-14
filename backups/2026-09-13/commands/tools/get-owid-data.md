---
description: Fetch Our World in Data datasets via owid-catalog — search charts/tables/indicators, retrieve DataFrame, optionally chart
---

You are a data analyst. Fetch data from Our World in Data using the `owid-catalog` Python library and produce clean DataFrames, optionally charted.

# Path Formats

| Kind | Example |
|------|---------|
| Chart slug | `"life-expectancy"` |
| Chart slug + params | `"years-of-schooling?metric_type=expected_years_schooling&level=primary&sex=boys"` |
| Full URL | `"https://ourworldindata.org/grapher/life-expectancy"` |
| Table path | `"garden/un/2024-07-12/un_wpp/population"` |
| Indicator path | `"garden/un/2024-07-12/un_wpp/population#population"` |

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Topic or path**: plain-English topic (e.g. "CO2 emissions", "child mortality") OR an exact slug/path
- **Kind**: `chart` (default, most user-facing), `table` (raw catalog data), or `indicator`
- **Chart**: does the user want a visualization?

If ambiguous, ask before proceeding.

## Step 2: Install + Search (skip if exact path provided)

```python
import subprocess
subprocess.run(["pip", "install", "-q", "owid-catalog"], check=True)

from owid.catalog import search

results = search("population", kind="chart", limit=10)
for r in results:
    print(r.slug, "|", getattr(r, "title", ""))
```

- Default `kind="chart"` — returns slugs usable directly with `fetch()`
- Use `kind="table"` for raw ETL catalog access (filter by namespace/version/dataset)
- Use `kind="indicator"` for individual variables
- Show top results, confirm with user if ambiguous, then proceed to Step 3

## Step 3: Fetch the Data

```python
from owid.catalog import fetch

# Chart slug (most common)
tb = fetch("life-expectancy")

# Table path
tb = fetch("garden/un/2024-07-12/un_wpp/population")

# Indicator
tb = fetch("garden/un/2024-07-12/un_wpp/population#population")

print(tb.shape)
print(tb.columns.tolist())
print(tb.head(10))
print(tb.metadata)
```

Returns a `Table` object — pandas DataFrame subclass with `.metadata` attribute. Use standard pandas operations to filter, pivot, or resample.

### Common filtering pattern
```python
# Filter to specific countries
df = tb.reset_index()
df_filtered = df[df["country"].isin(["United States", "China", "Germany"])]
```

## Step 4: Chart (optional) + Save

If the user wants a chart, use FredPlotter (already installed):

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from fred_client import FredPlotter
import pandas as pd

# Pivot to wide format: one column per country (or entity)
entity_col = "country" if "country" in df.columns else df.columns[0]
value_col = [c for c in df.columns if df[c].dtype in ["float64", "int64"]][0]
pivot = df.pivot_table(index="year", columns=entity_col, values=value_col)

plotter = FredPlotter(pivot, title="Chart Title")
fig = plotter.line(y_label="Value")
fig.show()
```

Save all outputs to `/Users/macproajb/claude_projects/owid/` using naming convention `TOPIC_DATE.html`:

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/owid/TOPIC_{date.today()}.html"
fig.write_html(fname)
```

Then open with: `open <fname>`

# Common Chart Slugs

| Topic | Slug |
|-------|------|
| Life expectancy | `life-expectancy` |
| GDP per capita | `gdp-per-capita-worldbank` |
| Extreme poverty share | `share-of-population-in-extreme-poverty` |
| CO2 emissions | `co2-emissions-per-capita` |
| Population (UN projections) | `total-population-with-un-projections` |
| Child mortality | `child-mortality` |
| Literacy rate | `literacy-rate` |
| Access to electricity | `share-of-the-population-with-access-to-electricity` |
| Vaccination coverage | `share-of-children-vaccinated-dtp3` |
| Internet users | `share-of-individuals-using-the-internet` |

# Guidelines

- Always check Common Chart Slugs first — skip search if slug is known
- `search()` default is `kind="chart"`; only switch to `kind="table"` if user needs raw ETL-level data
- `tb.metadata` and `tb[col].metadata` are available immediately (no extra fetch needed)
- If `fetch()` returns a multi-entity table, always filter to relevant countries before charting
- `owid-catalog` install is idempotent — always run `pip install -q owid-catalog` at top of script
- Save all outputs to `/Users/macproajb/claude_projects/owid/` (never `/tmp/`)
