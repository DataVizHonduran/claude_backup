import numpy as np
import pandas as pd
import yfinance as yf

from ma_ribbon_momentum import compute_mas, compute_momentum_score, log_periods, classify

TICKER = "DX-Y.NYB"
START = "2004-01-01"
THRESHOLD = 0.85
SMOOTH = 5
HORIZONS = list(range(5, 61, 5))
STRIDE = 10  # sample every Nth day to reduce overlap

CATS = ["Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish"]
DIRECTION = {"Strong Bullish": 1, "Bullish": 1, "Neutral": 0, "Bearish": -1, "Strong Bearish": -1}

print(f"Fetching {TICKER} (from {START})...")
raw = yf.download(TICKER, start=START, interval="1d", auto_adjust=True, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
close = raw["Close"].dropna()
print(f"  {close.index[0].date()} -> {close.index[-1].date()}  ({len(close)} rows)\n")

fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}

variants = {
    "Linear (10-200 step10)": list(range(10, 201, 10)),
}

for vname, periods in variants.items():
    ma_df = compute_mas(close, periods, "sma")
    score = compute_momentum_score(ma_df).ewm(span=SMOOTH, adjust=False).mean()
    cat = score.apply(lambda s: classify(s, THRESHOLD)).iloc[::STRIDE]

    print(f"=== {vname} ===")
    for c in CATS:
        mask = cat == c
        n_total = int(mask.sum())
        if n_total == 0:
            continue
        d = DIRECTION[c]
        dir_label = "long-favored" if d == 1 else "short-favored" if d == -1 else "no bias"
        print(f"\n{c} (n={n_total} days, {n_total/len(cat)*100:.1f}% of sample, hit = correct {dir_label} direction)")
        print(f"{'Horizon':>8} {'N':>6} {'HitRate':>8} {'AvgRet':>8} {'MedRet':>8}")
        for h in HORIZONS:
            r = fwd[h].reindex(cat.index)[mask].dropna()
            if len(r) == 0:
                continue
            if d == 1:
                hit = (r > 0).mean() * 100
            elif d == -1:
                hit = (r < 0).mean() * 100
            else:
                hit = (r > 0).mean() * 100
            print(f"{h:>7}d {len(r):>6} {hit:>7.1f}% {r.mean()*100:>7.2f}% {r.median()*100:>7.2f}%")

    # Combined trend-following rule: long USD only when bullish, short USD only when bearish
    print(f"\n--- Combined: long when Bullish/Strong Bullish, short when Bearish/Strong Bearish ---")
    long_mask = cat.isin(["Strong Bullish", "Bullish"])
    short_mask = cat.isin(["Strong Bearish", "Bearish"])
    n_long, n_short = int(long_mask.sum()), int(short_mask.sum())
    print(f"(n_long={n_long}, n_short={n_short}, {(n_long+n_short)/len(cat)*100:.1f}% of sample in a trade)")
    print(f"{'Horizon':>8} {'N':>6} {'HitRate':>8} {'AvgRet':>8} {'MedRet':>8}")
    for h in HORIZONS:
        r_h = fwd[h].reindex(cat.index)
        r_long = r_h[long_mask].dropna()
        r_short = r_h[short_mask].dropna()
        # short USD profits when r < 0, so flip sign for short trades' P&L
        pnl = pd.concat([r_long, -r_short])
        hit = pd.concat([(r_long > 0), (r_short < 0)]).mean() * 100
        print(f"{h:>7}d {len(pnl):>6} {hit:>7.1f}% {pnl.mean()*100:>7.2f}% {pnl.median()*100:>7.2f}%")
    print()
