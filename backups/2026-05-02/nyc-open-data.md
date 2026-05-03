Fetch data from the NYC Open Data SODA API and generate an interactive Plotly chart using the nyc_open_data package at /Users/macproajb/claude_projects/nyc_open_data/.

## Package location
- Client: `/Users/macproajb/claude_projects/nyc_open_data/client.py` — `SodaClient`
- Plotter: `/Users/macproajb/claude_projects/nyc_open_data/plotter.py` — `SodaPlotter`

## How to use this skill

The user will describe what data they want. You must:

1. **Identify the dataset** — map the request to a 4x4 dataset ID:
   - `43nn-pn8j` NYC Restaurant Inspections (cols: `boro`, `inspection_date`, `grade`, `violation_code`, `dba`)
   - `833y-fsy8` NYC Motor Vehicle Collisions (cols: `crash_date`, `borough`, `number_of_persons_injured`, `contributing_factor_vehicle_1`)
   - `h9gi-nx95` NYC Motor Vehicle Crashes (cols: `crash_date`, `borough`, `number_of_persons_killed`)
   - `nc67-uf89` NYC 311 Service Requests (cols: `created_date`, `complaint_type`, `borough`, `status`)
   - `pvqr-7yc4` NYC Parking Violations (cols: `issue_date`, `violation_county`, `violation_description`)

2. **Build a SoQL query** — always filter server-side. Never pull raw rows and filter in pandas.
   - Use `where=` for row filters (e.g. `"boro = 'Bronx' AND inspection_date > '2023-01-01T00:00:00.000'"`)
   - Use `select=` + `group=` for aggregations (e.g. `"boro, COUNT(*) AS cnt"` + `group="boro"`)
   - Use `order=` to sort results

3. **Fetch with SodaClient**:
```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from nyc_open_data import SodaClient, SodaPlotter

client = SodaClient()
df = client.fetch(
    "<dataset_id>",
    where="<soql_where>",
    select="<soql_select>",
    group="<soql_group>",       # omit if not aggregating
    order="<soql_order>",
    limit=<row_limit>,
    numeric_cols=["<col>"],     # columns to cast to float
    datetime_col="<col>",       # date column to parse (omit if not needed)
    as_index=False,
)
```

4. **Plot with SodaPlotter** — choose the right chart type:
   - `.bar(x_col, y_col, horizontal=True, top_n=20)` — categorical aggregations (violations by borough, complaints by type)
   - `.line(x_col, y_col, x_label=..., y_label=...)` — trends over time
   - `.choropleth(geojson, locations_col, value_col)` — geographic distribution

5. **Write HTML output** — always save to the current working directory:
```python
output = "<descriptive_name>.html"
fig = SodaPlotter(df, "<Chart Title>").<method>(...)
fig.write_html(output)
print(f"Chart saved: {output}")
```

## Arguments
$ARGUMENTS

If the user provides specific instructions above, follow them precisely. If no arguments are given, ask the user: what dataset and what question they want to answer (e.g. "Which NYC borough has the most restaurant grade violations in 2024?").

## Rules
- SoQL first — all filtering and aggregation must happen in the API call, not in pandas
- Use `top_n=` in `.bar()` when there are many categories — keep charts readable
- Default `limit` to 50,000 unless the user specifies otherwise
- Save output HTML to `/Users/macproajb/claude_projects/` unless the user specifies a path
- Print the DataFrame shape and `.head()` before plotting so the user can verify the data
