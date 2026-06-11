import numpy as np
import pandas as pd
import yfinance as yf

from ma_ribbon_momentum import compute_mas, compute_momentum_score

TICKER = "DX-Y.NYB"
START = "2004-01-01"
SMOOTH = 5
MIN_GAP = 60  # trading days; debounce repeated crossings of the same threshold
HORIZONS = [20, 40, 60, 90, 120, 180, 240, 300, 360]

print(f"Fetching {TICKER} (from {START})...")
raw = yf.download(TICKER, start=START, interval="1d", auto_adjust=True, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
close = raw["Close"].dropna()
print(f"  {close.index[0].date()} -> {close.index[-1].date()}  ({len(close)} rows)\n")

periods = list(range(10, 201, 10))
ma_df = compute_mas(close, periods, "sma")
score = compute_momentum_score(ma_df).ewm(span=SMOOTH, adjust=False).mean()
prev = score.shift(1)

fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}


def find_events(cond, min_gap):
    dates = score.index[cond.fillna(False)]
    kept = []
    last = None
    for d in dates:
        if last is None or (d - last).days >= min_gap:
            kept.append(d)
            last = d
    return kept


event_defs = [
    ("Cross UP through +0.50 (-> Bullish)", (prev < 0.5) & (score >= 0.5), 1),
    ("Cross UP through +0.85 (-> Strong Bullish)", (prev < 0.85) & (score >= 0.85), 1),
    ("Cross DOWN through -0.50 (-> Bearish)", (prev > -0.5) & (score <= -0.5), -1),
    ("Cross DOWN through -0.85 (-> Strong Bearish)", (prev > -0.85) & (score <= -0.85), -1),
]

for label, cond, direction in event_defs:
    events = find_events(cond, MIN_GAP)
    print(f"=== {label} ===")
    print(f"Events (n={len(events)}): " + ", ".join(d.strftime("%Y-%m-%d") for d in events))
    print(f"{'Horizon':>8} {'N':>6} {'HitRate':>8} {'AvgRet':>8} {'MedRet':>8}")
    for h in HORIZONS:
        r = fwd[h].reindex(events).dropna()
        if len(r) == 0:
            continue
        hit = ((r > 0) if direction == 1 else (r < 0)).mean() * 100
        print(f"{h:>7}d {len(r):>6} {hit:>7.1f}% {r.mean()*100:>7.2f}% {r.median()*100:>7.2f}%")
    print()
