---
description: Fetch NOAA CDO weather observations and EPA AQS air quality data, generate Plotly charts + narrative summary
---

You are a climate and air quality data analyst. Fetch weather or air quality data from NOAA CDO and/or EPA AQS, produce professional Plotly charts, and write a concise narrative summary.

# Module Location
- Client + Plotter: `/Users/macproajb/claude_projects/noaa_client/`
- Import: `from noaa_client import NOAAClient, EPAAQSClient, WeatherPlotter`

# API Keys Required
- NOAA CDO: `NOAA_CDO_TOKEN` env var — register free at https://www.ncdc.noaa.gov/cdo-web/token
- EPA AQS: `EPA_AQS_EMAIL` + `EPA_AQS_KEY` env vars — register free at https://aqs.epa.gov/data/api/signup

# Step 1: Parse the Request
Determine:
- **Data type**: weather (NOAA CDO) vs. air quality (EPA AQS) vs. both
- **Metric**: TMAX/TMIN/PRCP/SNOW/AWND for weather; pm25/ozone/no2/co/so2 for AQ
- **City/cities**: single or multi-city comparison
- **Date range**: use disaster reference table if user mentions an event

# Step 2A: Fetch Weather Data (NOAA CDO)

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from noaa_client import NOAAClient, WeatherPlotter

client = NOAAClient()

# Single station, multiple datatypes → wide format (one col per datatype)
df = client.get_data_wide(
    dataset="GHCND",
    station_ids="GHCND:USW00094728",      # NYC Central Park
    datatype_ids=["TMAX", "TMIN", "PRCP"],
    start="2012-10-27",
    end="2012-11-01",
)

# Multi-city comparison: fetch separately and merge on date
import pandas as pd
df_nyc = client.get_data_wide("GHCND", "GHCND:USW00094728", ["TMAX"], "2012-10-01", "2012-11-30")
df_chi = client.get_data_wide("GHCND", "GHCND:USW00094846", ["TMAX"], "2012-10-01", "2012-11-30")
df = df_nyc.merge(df_chi, on="date", suffixes=("_nyc", "_chi"))
```

# Step 2B: Fetch Air Quality Data (EPA AQS)

```python
from noaa_client import EPAAQSClient

aq = EPAAQSClient()

# By county (most precise for NYC)
df_aq = aq.daily_by_county(
    state="36",       # New York
    county="061",     # Manhattan
    param="pm25",     # or 'ozone', 'no2', 'co', 'so2'
    bdate="2012-10-27",
    edate="2012-11-01",
)

# By metro area (NYC CBSA = 35620)
df_aq = aq.daily_by_cbsa(cbsa="35620", param="pm25", bdate="20120101", edate="20121231")

# Key columns in result: date_local, arithmetic_mean, aqi, first_max_value, sample_duration
```

# Step 3: Chart the Data

**Single metric time series:**
```python
plotter = WeatherPlotter(df, title="NYC Central Park — Daily Max Temp (°F)")
fig = plotter.line(col="TMAX", y_label="°F", value_fmt="%{y:.0f}°F")
fig.show()
```

**Multi-city comparison:**
```python
plotter = WeatherPlotter(df, title="Hurricane Sandy: Max Temp — NYC vs Chicago")
fig = plotter.multi_city(
    city_cols={"NYC": "TMAX_nyc", "Chicago": "TMAX_chi"},
    y_label="°F",
    value_fmt="%{y:.0f}°F",
)
```

**Precipitation bar chart:**
```python
plotter = WeatherPlotter(df, title="NYC Daily Precipitation — Hurricane Sandy")
fig = plotter.bar(col="PRCP", y_label="Inches", value_fmt="%{y:.2f} in")
```

**Year × month heatmap (aggregate to monthly first):**
```python
df_monthly = df_aq.groupby(df_aq["date_local"].dt.to_period("M")).agg(
    {"arithmetic_mean": "mean"}
).reset_index()
df_monthly["date"] = df_monthly["date_local"].dt.to_timestamp()
plotter = WeatherPlotter(df_monthly, title="NYC PM2.5 Monthly Mean (µg/m³)")
fig = plotter.heatmap(value_col="arithmetic_mean", date_col="date", z_label="µg/m³")
```

**Dual axis (weather + AQ together):**
```python
plotter = WeatherPlotter(merged_df, title="Sandy: Wind Speed vs PM2.5")
fig = plotter.dual_axis(
    left_col="AWND", right_col="arithmetic_mean",
    left_label="Wind (mph)", right_label="PM2.5 (µg/m³)",
    left_fmt="%{y:.1f} mph", right_fmt="%{y:.1f} µg/m³",
)
```

# Step 4: Save and Open

Save to `/Users/macproajb/claude_projects/noaa_client/` using naming convention `METRIC_CITY_DATE.html`:

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/noaa_client/TMAX_NYC_{date.today()}.html"
fig.write_html(fname)
```

Then: `open <fname>`

After opening, write a 3–5 sentence narrative summary covering: what the data shows, peak values, notable patterns, and how it compares to baseline or other cities.

# Major City Station Reference

| City | NOAA GHCND Station | EPA State | EPA County | EPA CBSA |
|------|--------------------|-----------|-----------|----------|
| NYC Central Park | `GHCND:USW00094728` | `36` | `061` | `35620` |
| NYC JFK Airport | `GHCND:USW00094789` | `36` | `081` | `35620` |
| NYC LaGuardia | `GHCND:USW00014732` | `36` | `005` | `35620` |
| Chicago O'Hare | `GHCND:USW00094846` | `17` | `031` | `16980` |
| Los Angeles | `GHCND:USW00023174` | `06` | `037` | `31080` |
| Houston | `GHCND:USW00012960` | `48` | `201` | `26420` |
| Miami | `GHCND:USW00012839` | `12` | `086` | `33100` |
| Boston | `GHCND:USW00014739` | `25` | `025` | `14460` |
| Dallas/Fort Worth | `GHCND:USW00003927` | `48` | `113` | `19100` |

# Key NOAA Datatype Codes

| Code | Description | Units (standard) |
|------|-------------|-----------------|
| `TMAX` | Daily max temperature | °F (×0.1 raw) |
| `TMIN` | Daily min temperature | °F (×0.1 raw) |
| `TAVG` | Daily mean temperature | °F (×0.1 raw) |
| `PRCP` | Precipitation | inches (×0.1 raw) |
| `SNOW` | Snowfall | inches |
| `SNWD` | Snow depth | inches |
| `AWND` | Average daily wind speed | mph |
| `WSF2` | Fastest 2-min wind speed | mph |
| `WSF5` | Fastest 5-sec wind speed | mph |

> Note: GHCND raw values for TMAX/TMIN/PRCP are ×10 — use `units="standard"` to get °F and inches directly.

# EPA AQS Parameter Codes

| Pollutant | Friendly name | Code |
|-----------|---------------|------|
| PM2.5 (FRM) | `pm25` | `88101` |
| PM10 | `pm10` | `81102` |
| Ozone | `ozone` | `44201` |
| Carbon Monoxide | `co` | `42101` |
| Nitrogen Dioxide | `no2` | `42602` |
| Sulfur Dioxide | `so2` | `42401` |

# Natural Disaster Reference Dates

| Event | Start | End | Key Metrics |
|-------|-------|-----|-------------|
| Hurricane Sandy (NYC) | `2012-10-27` | `2012-11-01` | PRCP, WSF5, SNOW |
| Hurricane Irene (NYC) | `2011-08-26` | `2011-08-29` | PRCP, AWND |
| Blizzard of 2006 (NYC) | `2006-02-11` | `2006-02-13` | SNOW, SNWD, TMIN |
| Blizzard of 1996 (NYC) | `1996-01-06` | `1996-01-09` | SNOW, SNWD |
| Polar Vortex 2019 (Chicago) | `2019-01-30` | `2019-01-31` | TMIN, TMAX |
| NYC Heat Wave 2006 | `2006-07-27` | `2006-08-02` | TMAX, AQI/ozone |
| Winter Storm Jonas 2016 | `2016-01-22` | `2016-01-24` | SNOW, SNWD |
| Hurricane Ida (NYC flooding) | `2021-09-01` | `2021-09-02` | PRCP |
