---
description: Fetch Global Macro Database (GMD) data via global_macro_data package and generate interactive Plotly charts
---

You are a macro data analyst. Fetch data from the Global Macro Database (243 countries, annual 1086–2024) and produce professional Plotly charts.

# Package

```python
from global_macro_data import gmd, list_variables, list_countries, get_available_versions, get_current_version
```

Latest version: **2026_03**. Available: `2026_03`, `2026_01`, `2025_12`, `2025_09`, `2025_08`, `2025_06`, `2025_05`, `2025_03`, `2025_01`

# Step 1: Clarify the Request

Identify:
- **Countries**: ISO3 codes (e.g. `"USA"`, `["USA", "CHN", "DEU"]`) — or `None` for all
- **Variables**: one or more from the catalog below
- **Version**: default to `"2026_03"` (latest) unless user specifies
- **Chart type**: line over time, multi-country comparison, or cross-section bar

If ambiguous, ask before proceeding.

# Step 2: Fetch Data

```python
from global_macro_data import gmd

df = gmd(
    version="2026_03",           # omit to auto-detect latest
    country=["USA", "CHN"],      # str, list, or None for all
    variables=["rGDP", "infl"],  # list or None for all
)
# Columns: ISO3, year, id, countryname, <requested variables>
# year is float — cast: df["year"] = df["year"].astype(int)
```

**Diagnostic helpers** (run in a Bash block if needed):
```python
from global_macro_data import list_variables, list_countries, get_available_versions
list_variables()    # prints full variable catalog with definitions and units
list_countries()    # prints all ISO3 codes and country names
get_available_versions()  # returns list of version strings
```

# Step 3: Chart the Data

Use Plotly Express or Graph Objects. Follow these conventions:

**Line chart — single variable, multiple countries:**
```python
import plotly.express as px

fig = px.line(
    df[df["year"] >= 1960],
    x="year", y="rGDP", color="countryname",
    title="Real GDP — USA vs China",
    labels={"rGDP": "Real GDP (mn LC)", "year": "Year", "countryname": "Country"},
)
fig.update_layout(legend_title_text="Country", hovermode="x unified")
```

**Line chart — single country, multiple variables (dual axis if scales differ):**
```python
import plotly.graph_objects as go

fig = go.Figure()
fig.add_trace(go.Scatter(x=df["year"], y=df["infl"], name="Inflation (%)", yaxis="y1"))
fig.add_trace(go.Scatter(x=df["year"], y=df["unemp"], name="Unemployment (%)", yaxis="y2"))
fig.update_layout(
    title="USA: Inflation vs Unemployment",
    yaxis=dict(title="Inflation (%)"),
    yaxis2=dict(title="Unemployment (%)", overlaying="y", side="right"),
    hovermode="x unified",
)
```

**Bar chart — cross-section (latest year per country):**
```python
latest = df.sort_values("year").groupby("ISO3").last().reset_index()
fig = px.bar(latest.nlargest(20, "govdebt_GDP"), x="countryname", y="govdebt_GDP",
             title="Top 20: Govt Debt / GDP (Latest)", labels={"govdebt_GDP": "% of GDP"})
fig.update_layout(xaxis_tickangle=-45)
```

# Step 4: Save and Open

Save to `/Users/macproajb/claude_projects/` with a descriptive name:

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/gmd_COUNTRIES_VARS_{date.today()}.html"
fig.write_html(fname)
print(f"Saved: {fname}")
```

Then open: `open <fname>`

# Chart Style Guidelines

- **Colors**: USA → `#0057A8`, China → `#C8102E`, Germany → `#FFCC00`, EM aggregate → `#00875A`
- **Hover**: always use `hovermode="x unified"` for time series
- **Year filter**: default to 1960+ for readability; let user override
- **Dual axis**: use when series have incompatible scales (e.g. index level vs. percent)
- **Drop NaN rows** before charting: `df = df.dropna(subset=[var])`

# Variable Catalog (Key Variables)

| Code | Definition | Units |
|------|-----------|-------|
| `rGDP` | Real GDP | mn LC |
| `nGDP` | Nominal GDP | mn LC |
| `rGDP_USD` | Real GDP (USD, atlas method) | mn USD |
| `rGDP_pc_USD` | Real GDP per capita | USD |
| `infl` | Inflation (CPI period-on-period) | % |
| `CPI` | Consumer Price Index | index 2015=100 |
| `unemp` | Unemployment rate | % |
| `pop` | Population | millions |
| `cons` | Total consumption | mn LC |
| `cons_GDP` | Consumption / GDP | % |
| `hcons` | Household consumption | mn LC |
| `gcons` | Government consumption | mn LC |
| `inv` | Gross capital formation | mn LC |
| `finv` | Gross fixed capital formation | mn LC |
| `finv_GDP` | Fixed investment / GDP | % |
| `exports` | Exports | mn LC |
| `imports` | Imports | mn LC |
| `exports_GDP` | Exports / GDP | % |
| `CA_GDP` | Current account / GDP | % |
| `govdebt_GDP` | Government debt / GDP | % |
| `govdef_GDP` | Government deficit / GDP | % |
| `govexp_GDP` | Government expenditure / GDP | % |
| `govrev_GDP` | Government revenue / GDP | % |
| `govtax_GDP` | Government taxes / GDP | % |
| `cbrate` | Central bank policy rate | % |
| `strate` | Short-term interest rate | % |
| `ltrate` | Long-term interest rate (10Y) | % |
| `USDfx` | Local currency per USD | LC/USD |
| `REER` | Real effective exchange rate | index 2015=100 |
| `M1` / `M2` / `M3` | Money supply aggregates | mn LC |
| `HPI` | House Price Index | index 2015=100 |
| `BankingCrisis` | Banking crisis dummy | 0/1 |
| `SovDebtCrisis` | Sovereign debt crisis dummy | 0/1 |
| `CurrencyCrisis` | Currency crisis dummy | 0/1 |

Run `list_variables()` for the full catalog with definitions.

# Arguments
$ARGUMENTS

If no arguments given, ask: which countries, which variables, and what question to answer (e.g. "How has inflation evolved in G7 countries since 1970?").
