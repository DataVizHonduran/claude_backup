---
description: Fetch OECD data via SDMX REST API using OecdClient — search by description, retrieve DataFrame
---

You are a macro data analyst. Fetch OECD datasets by natural-language description and return clean DataFrames, optionally charted.

# Module Location
- Client: `/Users/macproajb/claude_projects/oecd_client/`
- Import: `from oecd_client import OecdClient`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Topic**: plain-English description of the data (e.g. "unemployment rate", "GDP growth", "CPI inflation")
- **Countries**: ISO2 codes or "all" (e.g. `USA`, `DEU`, `GBR+FRA+DEU`)
- **Date range**: `startPeriod` / `endPeriod` (default: last 10 years)
- **Frequency**: monthly (`M`), quarterly (`Q`), annual (`A`) — let the data decide if unclear

If ambiguous, ask before proceeding.

## Step 2: Search for the Dataflow

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from oecd_client import OecdClient

c = OecdClient()
hits = c.search("unemployment rate", top_n=10)
print(hits[["score", "id", "name", "agency"]].to_string())
```

Pick the best match. Use score + name to judge. If the top result is ambiguous, show the user the top 3–5 and ask which one they want.

## Step 3: Fetch the Data

```python
# Use id and agency from the search result
row = hits.iloc[0]

df = c.get_data(
    agency=row["agency"],
    dataflow=row["id"],
    filters="",           # empty = all dimensions; refine if too large
    startPeriod="2015-01",
)
print(df.shape)
print(df.head())
```

### Refining filters (optional)
Filters are dot-separated dimension values. Each dot = one dimension. Empty segment = all values for that dimension.

Examples:
- `.M.` → all areas, monthly frequency
- `USA+GBR.A.` → US and UK, annual
- Leave all empty (`""`) if unsure — then inspect the columns and filter programmatically in pandas.

### Programmatic filtering (preferred over SDMX filters when structure is unknown)
```python
# After fetching all data, filter in pandas
df_usa = df[df["REF_AREA"] == "USA"] if "REF_AREA" in df.columns else df
```

## Step 4: Chart (optional)
If the user asks for a chart, use FredPlotter since the data is already a pandas DataFrame:

```python
from fred_client import FredPlotter
import pandas as pd

# Pivot to wide format: one column per country
pivot = df.pivot_table(index=df.index, columns="Reference area", values="OBS_VALUE")

plotter = FredPlotter(pivot, title="Chart Title")
fig = plotter.line(y_label="Value")
fig.show()
```

# Key Dataflows (Common Reference)

| Topic | agency | dataflow id | Key dimensions to filter |
|-------|--------|-------------|--------------------------|
| Composite leading indicators | `OECD.SDD.STES` | `DSD_STES@DF_CLI` | — |
| Monthly unemployment rates | `OECD.SDD.TPS` | `DSD_LFS@DF_IALFS_UNE_M` | `SEX=_T`, `ADJUSTMENT=Y`, filter `FREQ=M` in pandas |
| Business tendency surveys (BCI) | `OECD.SDD.STES` | `DSD_STES@DF_BTS` | `MEASURE=BCICP` (composite confidence); sectors: `C` mfg, `F` construction, `G47` retail, `GTU` services |
| Quarterly GDP growth (OECD) | `OECD.SDD.NAD` | `DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD` | — |
| Quarterly GDP growth (G20) | `OECD.SDD.NAD` | `DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_G20` | — |
| Inflation contribution (COICOP) | `OECD.SDD.TPS` | `DSD_PRICES@DF_PRICES_CONTRIB` | — |
| Productivity growth rates | `OECD.SDD.TPS` | `DSD_PDB@DF_PDB_GR` | — |
| Balance of payments / Current account | `OECD.SDD.TPS` | `DSD_BOP@DF_BOP` | `MEASURE=CA`, `ACCOUNTING_ENTRY=B` (balance), `UNIT_MEASURE=PT_B1GQ` (% GDP) or `USD_EXC`; dims: REF_AREA·COUNTERPART_AREA·MEASURE·ACCOUNTING_ENTRY·FS_ENTRY·FREQ·UNIT_MEASURE·ADJUSTMENT (8 total) |

# `key` param — targeted fetching (preferred over `filters=""`)
Use `key={"MEASURE": "BCICP"}` instead of `filters=""` to pin dimensions server-side and reduce rows fetched by up to 6×.
```python
df = c.get_data(agency="OECD.SDD.STES", dataflow="DSD_STES@DF_BTS",
                key={"MEASURE": "BCICP"}, startPeriod="1988-01")
```
Fetches DSD structure once per dataflow (cached in-session) to resolve dimension positions automatically.

# Guidelines
- Check the Key Dataflows table first — skip `search()` if the dataflow is already known
- For unfamiliar topics, run `/tools:search-oecd` first to find the mnemonic, then come back here to fetch
- Never guess a dataflow ID
- If `get_data()` returns >50k rows, use `key=` to pin dimensions server-side, then `startPeriod`
- `OBS_VALUE` is the numeric observation column; `Reference area` is the country label
- The catalog is lazy-loaded once per session — `search()` after the first call is instant (in-memory)
- Save all outputs to `/Users/macproajb/claude_projects/oecd/` (not `/tmp/`)
