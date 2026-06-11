"""
Fetch 20 years of daily temperature data for Manhattan (Central Park)
from the open-meteo ERA5 archive API — no API key required.
Saves: manhattan_daily_temperature.csv
"""
import requests
import pandas as pd
from datetime import date

LAT = 40.7829   # Central Park
LON = -73.9654

START = "2006-05-15"
END   = "2026-05-15"

url = "https://archive-api.open-meteo.com/v1/archive"
params = {
    "latitude":  LAT,
    "longitude": LON,
    "start_date": START,
    "end_date":   END,
    "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean",
    "timezone": "America/New_York",
    "temperature_unit": "fahrenheit",
}

print(f"Fetching daily temperature {START} → {END}  (lat={LAT}, lon={LON}) ...")
r = requests.get(url, params=params, timeout=60)
r.raise_for_status()
data = r.json()

daily = data["daily"]
df = pd.DataFrame({
    "date":       pd.to_datetime(daily["time"]),
    "tmax_f":     daily["temperature_2m_max"],
    "tmin_f":     daily["temperature_2m_min"],
    "tmean_f":    daily["temperature_2m_mean"],
})

out = "/Users/macproajb/claude_projects/manhattan_daily_temperature.csv"
df.to_csv(out, index=False)

print(f"Shape: {df.shape}")
print(df.head(10).to_string(index=False))
print(f"\nSaved → {out}")
