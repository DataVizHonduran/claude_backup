"""
Daily EMFX Risk Diffusion & Contrarian Signal Dashboard for GitHub Actions
Uses Alpha Vantage for FX data — requires ALPHA_VANTAGE_KEY env var
"""

import os
import time
import requests
import pandas as pd
import plotly.graph_objects as go
from scipy.signal import savgol_filter

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'reports', 'emfx-risk-diffusion', 'index.html'
)

api_key = os.environ.get("ALPHA_VANTAGE_KEY")
if not api_key:
    raise ValueError("ALPHA_VANTAGE_KEY environment variable is not set.")

symbols = [
    "EUR", "AUD", "CAD", "GBP", "JPY", "SEK", "NOK", "NZD", "CHF",
    "MXN", "CLP", "BRL", "COP", "PEN",
    "KRW", "IDR", "INR", "THB", "PHP", "SGD",
    "PLN", "HUF", "CZK", "ZAR", "TRY"
]

emfx = [
    "MXN", "CLP", "BRL", "COP", "PEN",
    "KRW", "IDR", "INR", "THB", "PHP", "SGD",
    "PLN", "HUF", "CZK", "ZAR", "TRY"
]

# ---------------------------------------------------------
# DATA FETCH
# ---------------------------------------------------------
data_dict = {}

print("Starting API fetch loop...")

for symbol in symbols:
    print(f"Fetching USD/{symbol}...")
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "FX_DAILY",
        "from_symbol": "USD",
        "to_symbol": symbol,
        "outputsize": "full",
        "apikey": api_key
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        if "Time Series FX (Daily)" in data:
            ts = data["Time Series FX (Daily)"]
            df_temp = pd.DataFrame.from_dict(ts, orient="index")
            df_temp.index = pd.to_datetime(df_temp.index)
            df_temp.columns = ["open", "high", "low", "close"]
            df_temp = df_temp.astype(float)
            for col in df_temp.columns:
                data_dict[(symbol, col)] = df_temp[col]
        else:
            print(f"Error fetching {symbol}: {data.get('Note') or data.get('Error Message')}")

    except Exception as e:
        print(f"Exception for {symbol}: {e}")

    time.sleep(15)  # Respect free-tier rate limit (5 calls/min)

combined_df = pd.DataFrame(data_dict)
combined_df.columns = pd.MultiIndex.from_tuples(combined_df.columns)
combined_df.sort_index(inplace=True)

df_close = combined_df.xs("close", axis=1, level=1)
print(f"Fetched FX data: {df_close.shape[0]} rows, {df_close.shape[1]} currencies")

# ---------------------------------------------------------
# ANALYSIS
# ---------------------------------------------------------
existing_emfx = [c for c in emfx if c in df_close.columns]
# limit=5 fills only weekends/short holidays; stale currencies stay NaN rather than
# being forward-filled indefinitely, which caused artificial "near 252d-high" readings
df_em = 1 / df_close[existing_emfx].ffill(limit=5).bfill(limit=5).loc["2014-11-01":]

window = 252
threshold = 0.05
diffusion_data = []

for i in range(window, len(df_em)):
    slice_df = df_em.iloc[:i + 1]
    highs = slice_df.rolling(window).max()
    lows = slice_df.rolling(window).min()
    latest_prices = slice_df.iloc[-1]
    latest_highs = highs.iloc[-1]
    latest_lows = lows.iloc[-1]

    near_high = (latest_highs - latest_prices) / latest_highs <= threshold
    near_low = (latest_prices - latest_lows) / latest_lows <= threshold

    # Only count currencies with valid (non-stale) data
    valid = latest_prices.notna()
    count_high = near_high[valid].sum()
    count_low = near_low[valid].sum()
    total = int(valid.sum())
    if total == 0:
        diffusion_data.append((slice_df.index[-1], float("nan")))
        continue

    diffusion_index = (count_high - count_low) / total
    diffusion_data.append((slice_df.index[-1], diffusion_index))

diffusion_df = pd.DataFrame(diffusion_data, columns=["Date", "Diffusion"]).set_index("Date")
# Interpolate any NaN (from zero-coverage days) before smoothing
diffusion_df["Diffusion"] = diffusion_df["Diffusion"].interpolate(limit_direction="both")
diffusion_df["Smoothed"] = savgol_filter(diffusion_df["Diffusion"], 11, 3)

valid_last = df_em.iloc[-1].notna().sum()
print(f"Coverage on last date: {valid_last}/{len(existing_emfx)} currencies")

em_fx = df_em.mean(axis=1)
em_fx = em_fx / em_fx.iloc[0] * 100
trend = em_fx - em_fx.rolling(100).mean()

# Contrarian signal
q10_c = diffusion_df["Diffusion"].quantile(0.06)
q90_c = diffusion_df["Diffusion"].quantile(0.94)
contrarian_signal = pd.Series(index=diffusion_df.index, dtype="float64")
last_signal_day = None
cooldown = pd.Timedelta(days=28)  # ~4 weeks; 5 days caused weekly signal spam

for date in diffusion_df.index:
    val = diffusion_df.loc[date, "Diffusion"]
    if last_signal_day is not None and (date - last_signal_day) < cooldown:
        contrarian_signal.loc[date] = 0
        continue
    if val >= q90_c:
        contrarian_signal.loc[date] = -1
        last_signal_day = date
    elif val <= q10_c:
        contrarian_signal.loc[date] = 1
        last_signal_day = date
    else:
        contrarian_signal.loc[date] = 0

# ---------------------------------------------------------
# CHART
# ---------------------------------------------------------
fig = go.Figure()

cs = contrarian_signal.copy()
cs = cs[cs != cs.shift(1)].to_frame(name="signal")
cs["start"] = cs.index
cs["end"] = cs["start"].shift(-1)
cs = cs.dropna()

for _, row in cs.iterrows():
    if row["signal"] == 1:
        color = "rgba(0,200,0,0.8)"
    elif row["signal"] == -1:
        color = "rgba(255,0,0,0.8)"
    else:
        continue
    fig.add_vrect(x0=row["start"], x1=row["end"], fillcolor=color, layer="below", line_width=0)

fig.add_trace(go.Scatter(
    x=diffusion_df.index, y=diffusion_df["Smoothed"],
    mode="lines", name="EM Diffusion",
    line=dict(color="#008080", width=2)
))

fx_change = em_fx.pct_change(window)
fig.add_trace(go.Scatter(
    x=fx_change.index, y=fx_change,
    mode="lines", name=f"EM FX Index ({window}d)",
    yaxis="y2",
    line=dict(color="#FF8C00", dash="solid", width=1.5)
))

fig.update_layout(
    title="Contrarian Signal: EM FX Diffusion vs. Index",
    yaxis=dict(title="Diffusion", range=[-1, 1]),
    yaxis2=dict(overlaying="y", side="right", showgrid=False),
    template="plotly_white",
    height=600
)

# ---------------------------------------------------------
# SAVE
# ---------------------------------------------------------
last_updated = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
with open(OUTPUT_PATH, "w") as f:
    f.write("<html><head><title>EM FX Z-Scores</title></head><body>")
    f.write('<h1 style="font-family:sans-serif; text-align:center;">EM FX Diffusion & Contrarian Signals</h1>')
    f.write(fig.to_html(full_html=False, include_plotlyjs="cdn"))
    f.write(f'<p style="text-align:center; font-family:sans-serif;">Last updated: {last_updated}</p>')
    f.write("</body></html>")

print(f"✅ Dashboard saved to {OUTPUT_PATH}")
