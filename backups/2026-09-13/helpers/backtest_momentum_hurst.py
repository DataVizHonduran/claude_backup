import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import linregress

from ma_ribbon_momentum import compute_mas, compute_momentum_score, classify

TICKER = "DX-Y.NYB"
START = "2004-01-01"
THRESHOLD = 0.85
SMOOTH = 5
STRIDE = 10
HORIZONS = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
HURST_WINDOW = 100
MIN_LAG, MAX_LAG = 2, 20

CATS = ["Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish"]
DIRECTION = {"Strong Bullish": 1, "Bullish": 1, "Neutral": 0, "Bearish": -1, "Strong Bearish": -1}


def hurst_exponent(ts, min_lag, max_lag):
    ts = ts[~np.isnan(ts)]
    rs_medians, valid_lags = [], []
    for lag in range(min_lag, max_lag):
        n_segs = len(ts) // lag
        if n_segs < 2:
            break
        rs_vals = []
        for i in range(n_segs):
            seg = ts[i * lag:(i + 1) * lag]
            cum_dev = np.cumsum(seg - seg.mean())
            R = cum_dev.max() - cum_dev.min()
            S = seg.std(ddof=1)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            rs_medians.append(np.median(rs_vals))
            valid_lags.append(lag)
    if len(rs_medians) < 2:
        return np.nan
    slope, *_ = linregress(np.log10(valid_lags), np.log10(rs_medians))
    return slope


print(f"Fetching {TICKER} (from {START})...")
raw = yf.download(TICKER, start=START, interval="1d", auto_adjust=True, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
close = raw["Close"].dropna()
print(f"  {close.index[0].date()} -> {close.index[-1].date()}  ({len(close)} rows)")

print(f"Computing rolling Hurst on log returns (window={HURST_WINDOW}, lags {MIN_LAG}-{MAX_LAG})...")
log_ret = np.log(close).diff().dropna()
rolling_h = log_ret.rolling(HURST_WINDOW).apply(lambda x: hurst_exponent(x, MIN_LAG, MAX_LAG), raw=True)
rolling_h = rolling_h.reindex(close.index)

periods = list(range(10, 201, 10))
ma_df = compute_mas(close, periods, "sma")
score = compute_momentum_score(ma_df).ewm(span=SMOOTH, adjust=False).mean()
cat = score.apply(lambda s: classify(s, THRESHOLD))

fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}

idx = cat.index[::STRIDE]
cat_s = cat.loc[idx]
hurst_s = rolling_h.loc[idx]
hurst_median = rolling_h.dropna().median()
trending = hurst_s > hurst_median
print(f"\nHurst median (relative split point): {hurst_median:.3f}")
print(f"Sampled days: {len(idx)} | High-H (>median): {trending.sum()} | Low-H (<=median): {(~trending).sum()}")

print("\n--- Combined trend rule (long Bullish/Strong Bullish, short Bearish/Strong Bearish) ---")
long_mask = cat_s.isin(["Strong Bullish", "Bullish"])
short_mask = cat_s.isin(["Strong Bearish", "Bearish"])

for label, regime_mask in [("ALL", pd.Series(True, index=idx)), ("High-H (>median, more trending)", trending), ("Low-H (<=median, more mean-reverting)", ~trending)]:
    lm = long_mask & regime_mask
    sm = short_mask & regime_mask
    n = int(lm.sum() + sm.sum())
    print(f"\n{label}  (n_long={int(lm.sum())}, n_short={int(sm.sum())})")
    print(f"{'Horizon':>8} {'N':>6} {'HitRate':>8} {'AvgRet':>8} {'MedRet':>8}")
    for h in HORIZONS:
        r_h = fwd[h].reindex(idx)
        r_long = r_h[lm].dropna()
        r_short = r_h[sm].dropna()
        pnl = pd.concat([r_long, -r_short])
        if len(pnl) == 0:
            continue
        hit = pd.concat([(r_long > 0), (r_short < 0)]).mean() * 100
        print(f"{h:>7}d {len(pnl):>6} {hit:>7.1f}% {pnl.mean()*100:>7.2f}% {pnl.median()*100:>7.2f}%")
