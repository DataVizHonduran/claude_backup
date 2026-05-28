"""
Patch summary.json with ma_positions data for the scatter chart tab.
Run once after updating generate_index.py — no need to regenerate all charts.
Future runs of generate_cta_signals.py will include this data automatically.
"""

import pandas as pd
import numpy as np
import json
import os

FX_DATA_URL = "https://raw.githubusercontent.com/DataVizHonduran/EMFX_risk_diffusion/main/fx_data_raw.csv"
OUTPUT_DIR  = "reports/cta-signals"
MA_WINDOWS  = [5, 10, 20, 50, 60, 100, 200]
WINDOW      = 2500
CTA_MODES   = {
    'fast': {'short': 20, 'mid': 50,  'long': 100},
    'slow': {'short': 50, 'mid': 100, 'long': 200},
}

print(f"Loading FX data from {FX_DATA_URL}...")
df_fx = pd.read_csv(FX_DATA_URL, index_col=0, parse_dates=True)
df_fx = df_fx.apply(pd.to_numeric, errors='coerce')
print(f"Loaded {len(df_fx)} rows, {len(df_fx.columns)} currencies")

inverse = ["EUR", "GBP", "AUD", "NZD"]
df_fx[inverse] = 1 / df_fx[inverse]
euroy = ["GBP", "SEK", "NOK", "HUF", "PLN", "CZK"]
df_fx[euroy] = df_fx[euroy].multiply(df_fx["EUR"], axis=0)


def compute_positions_df(df_fx, short_w, mid_w, long_w):
    positions_df = pd.DataFrame()
    for ccy in df_fx.columns:
        s = df_fx[ccy].dropna()
        if len(s) < long_w:
            continue
        df = pd.DataFrame({'price': s})
        df['ema_short'] = df['price'].ewm(span=short_w, adjust=False).mean()
        df['ema_mid']   = df['price'].ewm(span=mid_w,   adjust=False).mean()
        df['ema_long']  = df['price'].ewm(span=long_w,  adjust=False).mean()
        df['ema_conv']  = df['ema_short'] - df['ema_long']
        rolling_max = df['ema_conv'].abs().rolling(WINDOW, min_periods=1).max()
        rolling_max = rolling_max.replace(0, np.nan).bfill().ffill()
        raw = (df['ema_conv'] / rolling_max) * 50
        up   = (df['ema_short'] > df['ema_mid']) & (df['ema_mid'] > df['ema_long'])
        down = (df['ema_short'] < df['ema_mid']) & (df['ema_mid'] < df['ema_long'])
        df['pos'] = np.where(up,   np.maximum(0, raw),
                    np.where(down, np.minimum(0, raw), 0))
        positions_df[ccy + '_posy'] = df['pos']
    return positions_df


summary_path = os.path.join(OUTPUT_DIR, 'summary.json')
with open(summary_path) as f:
    summary = json.load(f)

for mode, w in CTA_MODES.items():
    print(f"\nComputing {mode.upper()} positions ({w['short']}/{w['mid']}/{w['long']})...")
    pos_df = compute_positions_df(df_fx, w['short'], w['mid'], w['long'])
    ma_pos = {}
    for n in MA_WINDOWS:
        row = pos_df.rolling(n, min_periods=1).mean().iloc[-1]
        ma_pos[str(n)] = {
            col.replace('_posy', ''): round(float(v), 4)
            for col, v in row.items()
            if not pd.isna(v)
        }
    summary[mode]['ma_positions'] = ma_pos
    print(f"  Added MA windows {MA_WINDOWS} for {len(ma_pos['20'])} currencies")

with open(summary_path, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n✅ Patched {summary_path} with ma_positions")
print("   Now run: python3 scripts/generate_index.py")
