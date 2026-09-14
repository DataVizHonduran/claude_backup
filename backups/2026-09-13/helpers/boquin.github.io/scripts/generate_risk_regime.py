"""
Daily Global Risk Regime Indicator for GitHub Actions
Tries Stooq first; falls back to yfinance if Stooq is unavailable.
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
    'reports', 'risk-regimes', 'us_regime.html'
)

# Friendly name → (stooq ticker, yfinance ticker)
tickers = {
    "SPX":    ("SPY.US",  "SPY"),
    "DAX":    ("EWG.US",  "EWG"),
    "NIKKEI": ("EWJ.US",  "EWJ"),
    "EMEQ":   ("EEM.US",  "EEM"),
    "HYG":    ("HYG.US",  "HYG"),
    "LQD":    ("LQD.US",  "LQD"),
    "TLT":    ("TLT.US",  "TLT"),
    "VIX":    ("VIXY.US", "VIXY"),
    "DBC":    ("DBC.US",  "DBC"),
    "GLD":    ("GLD.US",  "GLD"),
    "USO":    ("USO.US",  "USO"),
    "CPER":   ("CPER.US", "CPER"),
    "VNQ":    ("VNQ.US",  "VNQ"),
    "UUP":    ("UUP.US",  "UUP"),
}

invert_list = ["VIX", "TLT", "GLD", "UUP"]

start = datetime.datetime(2002, 1, 1)
end = datetime.datetime.today()

n_day = 100
n_smooth = 20


# ---------------------------------------------------------
# DATA FETCH — Stooq first, yfinance fallback
# ---------------------------------------------------------
def fetch_stooq():
    import requests, io
    d1 = pd.Timestamp(start).strftime("%Y%m%d")
    d2 = pd.Timestamp(end).strftime("%Y%m%d")
    frames = {}
    for name, (stooq_ticker, _) in tickers.items():
        url = f"https://stooq.com/q/d/l/?s={stooq_ticker}&d1={d1}&d2={d2}&i=d"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True)
        df = df[::-1]  # oldest to newest (matches original script)
        frames[name] = df["Close"]
    close = pd.concat(frames.values(), axis=1)
    close.columns = list(frames.keys())
    if close.dropna().empty:
        raise ValueError("Stooq returned no usable data")
    return close


def fetch_yfinance():
    yf_tickers = [v[1] for v in tickers.values()]
    name_list = list(tickers.keys())
    raw = yf.download(yf_tickers, start=start, end=end, auto_adjust=False, progress=False)
    close = raw["Close"].sort_index()
    # yfinance sorts columns alphabetically — rename via explicit mapping
    yf_to_name = {v[1]: k for k, v in tickers.items()}
    close = close.rename(columns=yf_to_name)
    return close[name_list]


try:
    print("Trying Stooq...")
    close = fetch_stooq()
    print("Stooq data loaded.")
except Exception as e:
    print(f"Stooq failed ({e}), falling back to yfinance...")
    close = fetch_yfinance()
    print("yfinance data loaded.")

df_all = close.dropna()
print(f"Combined data shape: {df_all.shape}")


# ---------------------------------------------------------
# Z-SCORE REGIME
# ---------------------------------------------------------
z_scores = pd.DataFrame(index=df_all.index)

for col in df_all.columns:
    price = df_all[col]
    ma = price.rolling(n_day).mean()
    std = price.rolling(90).std()
    z = (price - ma) / std
    if col in invert_list:
        z = -z
    z_scores[col] = z

z_scores["Risk_Regime_Score"] = z_scores.median(axis=1)
z_scores["Risk_Regime_Score_Smoothed"] = z_scores["Risk_Regime_Score"].rolling(n_smooth).mean()

current_score = z_scores["Risk_Regime_Score_Smoothed"].iloc[-1]
if current_score > 1:
    current_regime = "RISK-ON"
elif current_score < -1:
    current_regime = "RISK-OFF"
else:
    current_regime = "NEUTRAL"

print(f"Current Risk Regime: {current_regime} (Score: {current_score:.2f})")


# ---------------------------------------------------------
# CHART
# ---------------------------------------------------------
last_updated = datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=z_scores.index,
    y=z_scores["Risk_Regime_Score"],
    mode="lines",
    name="Raw Score",
    line=dict(width=1, color='lightblue'),
    opacity=0.6
))

fig.add_trace(go.Scatter(
    x=z_scores.index,
    y=z_scores["Risk_Regime_Score_Smoothed"],
    mode="lines",
    name="Smoothed (20d)",
    line=dict(width=3, color='darkblue')
))

fig.add_hline(y=1, line_dash="dash", line_color="green",
              annotation_text="Risk-On", annotation_position="top right")
fig.add_hline(y=0, line_dash="dash", line_color="gray",
              annotation_text="Neutral", annotation_position="top right")
fig.add_hline(y=-1, line_dash="dash", line_color="red",
              annotation_text="Risk-Off", annotation_position="bottom right")

fig.update_layout(
    title={
        'text': "Risk Regime Dashboard",
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
