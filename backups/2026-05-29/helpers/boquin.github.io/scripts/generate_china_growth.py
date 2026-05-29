"""
Daily China Growth Regime Dashboard for GitHub Actions
Tries Stooq first (individual fetches); falls back to yfinance.
"""

import os
import warnings
import pandas as pd
import yfinance as yf
import datetime
import plotly.graph_objects as go

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'reports', 'risk-regimes', 'china_growth.html'
)

# Stooq ticker → yfinance ticker
tickers = {
    "FXI.US":  "FXI",
    "MCHI.US": "MCHI",
    "KWEB.US": "KWEB",
    "ASHR.US": "ASHR",
    "AIA.US":  "AIA",
    "EEM.US":  "EEM",
    "CPER.US": "CPER",
    "BNO.US":  "BNO",
    "SLX.US":  "SLX",
    "WOOD.US": "WOOD",
    "XME.US":  "XME",
    "XLI.US":  "XLI",
    "IYT.US":  "IYT",
    "CNYB.US": "CNYB",
    "DBC.US":  "DBC",
    "SEA.US":  "SEA",
    "VAW.US":  "VAW",
    "VWO.US":  "VWO",
    "EWT.US":  "EWT",
    "KORU.US": "KORU",
}

invert_list = ["CNYB.US"]

bucket_map = {
    "China_Equities":    ["FXI.US", "MCHI.US", "KWEB.US", "ASHR.US"],
    "Regional_Equities": ["AIA.US", "EEM.US", "VWO.US", "EWT.US", "KORU.US"],
    "Commodities":       ["CPER.US", "BNO.US", "SLX.US", "WOOD.US", "XME.US", "DBC.US", "VAW.US"],
    "Industrials_Trade": ["XLI.US", "IYT.US", "SEA.US"],
    "Rates_Bonds":       ["CNYB.US"],
}

start = "1995-01-01"
end = datetime.datetime.today().strftime("%Y-%m-%d")

n_day = 200
n_smooth = 30


# ---------------------------------------------------------
# DATA FETCH — Stooq first, yfinance fallback
# ---------------------------------------------------------
def fetch_stooq():
    import requests, io
    d1 = pd.Timestamp(start).strftime("%Y%m%d")
    d2 = pd.Timestamp(end).strftime("%Y%m%d")
    df_all = pd.DataFrame()
    for stooq_ticker in tickers:
        url = f"https://stooq.com/q/d/l/?s={stooq_ticker}&d1={d1}&d2={d2}&i=d"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True)
        df = df[::-1]
        df_all[stooq_ticker] = df["Close"]
        print(f"Loaded {stooq_ticker}")
    if df_all.empty:
        raise ValueError("Stooq returned no data")
    return df_all


def fetch_yfinance():
    yf_tickers = list(tickers.values())
    stooq_names = list(tickers.keys())
    raw = yf.download(yf_tickers, start=start, end=end, auto_adjust=False, progress=False)
    close = raw["Close"].sort_index()
    # yfinance sorts columns alphabetically — rename via explicit mapping
    yf_to_stooq = {v: k for k, v in tickers.items()}
    close = close.rename(columns=yf_to_stooq)
    return close[stooq_names]


try:
    print("Trying Stooq...")
    df_all = fetch_stooq()
    print("Stooq data loaded.")
except Exception as e:
    print(f"Stooq failed ({e}), falling back to yfinance...")
    df_all = fetch_yfinance()
    print("yfinance data loaded.")

# Drop tickers with less than 75% data coverage
df_all = df_all.dropna(axis=1, thresh=int(len(df_all) * 0.75))
print(f"Combined data shape: {df_all.shape}")


# ---------------------------------------------------------
# Z-SCORE REGIME
# ---------------------------------------------------------
z_scores = pd.DataFrame(index=df_all.index)

for col in df_all.columns:
    price = df_all[col]
    ma = price.rolling(n_day).mean()
    std = price.rolling(n_day).std()
    z = (price - ma) / std
    if col in invert_list:
        z = -z
    z_scores[col] = z

# Bucket → equal-weight across buckets
bucket_scores = pd.DataFrame(index=z_scores.index)
for bucket, bucket_tickers in bucket_map.items():
    valid = [t for t in bucket_tickers if t in z_scores.columns]
    if valid:
        bucket_scores[bucket] = z_scores[valid].mean(axis=1)

z_scores["China_Growth_Score"] = bucket_scores.mean(axis=1)
z_scores["China_Growth_Score_Smoothed"] = z_scores["China_Growth_Score"].rolling(n_smooth).mean()

current_score = z_scores["China_Growth_Score_Smoothed"].iloc[-1]
n_high = z_scores["China_Growth_Score"].quantile(0.8)
n_low = z_scores["China_Growth_Score"].quantile(0.2)

if current_score > n_high:
    current_regime = "GROWTH-ON"
elif current_score < n_low:
    current_regime = "GROWTH-OFF"
else:
    current_regime = "NEUTRAL"

print(f"Current China Growth Regime: {current_regime} (Score: {current_score:.2f})")


# ---------------------------------------------------------
# CHART
# ---------------------------------------------------------
last_updated = datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=z_scores.index,
    y=z_scores["China_Growth_Score"],
    mode="lines",
    name="Raw Score",
    line=dict(width=1, color='lightcoral'),
    opacity=0.6
))

fig.add_trace(go.Scatter(
    x=z_scores.index,
    y=z_scores["China_Growth_Score_Smoothed"],
    mode="lines",
    name="Smoothed (30d)",
    line=dict(width=3, color='darkred')
))

fig.add_hline(y=n_high, line_dash="dash", line_color="green",
              annotation_text="Growth-On", annotation_position="top right")
fig.add_hline(y=0, line_dash="dash", line_color="gray",
              annotation_text="Neutral", annotation_position="top right")
fig.add_hline(y=n_low, line_dash="dash", line_color="red",
              annotation_text="Growth-Off", annotation_position="bottom right")

fig.update_layout(
    title={
        'text': "China Growth Regime Dashboard",
        'x': 0.5,
        'xanchor': 'center',
        'font': {'size': 24}
    },
    xaxis_title="Date",
    yaxis_title="Z-Score",
    height=600,
    template="plotly_white",
    hovermode='x unified',
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)

fig.add_annotation(
    text=f"Last Updated: {last_updated}",
    xref="paper", yref="paper",
    x=1, y=-0.1,
    xanchor='right', yanchor='top',
    showarrow=False,
    font=dict(size=12, color="gray")
)

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
fig.write_html(OUTPUT_PATH, config={'displayModeBar': False, 'responsive': True})
print(f"✅ Dashboard saved to {OUTPUT_PATH}")
