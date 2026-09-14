"""
Sweep CTA reversal signal across percentile thresholds to find best hit rate.
Reads existing position/yield CSVs — no FRED call required.

Usage:
    cd /Users/macproajb/boquin.github.io
    python scripts/pct_threshold_sweep.py
"""

import os
import numpy as np
import pandas as pd

OUTPUT_DIR = "reports/treasury-cta-signals"
TENORS     = ['2Y', '5Y', '10Y', '30Y']
HORIZONS   = [5, 10, 21, 63]
PCT_WINDOW = 252
MIN_P      = 126
THRESHOLDS = [0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]

yields_df = pd.read_csv(os.path.join(OUTPUT_DIR, 'yields.csv'), index_col=0, parse_dates=True)


def hit_rates_for_threshold(mode, pct_upper, pct_lower):
    pos_df = pd.read_csv(os.path.join(OUTPUT_DIR, f'positions_{mode}.csv'),
                         index_col=0, parse_dates=True)
    upper_val = pct_upper * 100
    lower_val = pct_lower * 100

    all_hits   = {h: [] for h in HORIZONS}
    all_avgs   = {h: [] for h in HORIZONS}
    total_sigs = 0

    for tenor in TENORS:
        if tenor not in pos_df.columns or tenor not in yields_df.columns:
            continue
        pos = pos_df[tenor].dropna()
        yld = yields_df[tenor].reindex(pos.index).ffill()
        pct = pos.rolling(PCT_WINDOW, min_periods=MIN_P).rank(pct=True) * 100
        prev_pct = pct.shift(1)

        signals = [
            (pos.index[(prev_pct > upper_val) & (pct <= upper_val)], -1),
            (pos.index[(prev_pct < lower_val) & (pct >= lower_val)],  1),
        ]

        for sig_idx, direction in signals:
            total_sigs += len(sig_idx)
            for h in HORIZONS:
                gains = []
                for dt in sig_idx:
                    loc = yld.index.get_loc(dt)
                    fwd = loc + h
                    if fwd >= len(yld):
                        continue
                    dy = yld.iloc[fwd] - yld.iloc[loc]
                    gains.append(-direction * dy * 100)
                if gains:
                    g = np.array(gains)
                    all_hits[h].append((g > 0).mean() * 100)
                    all_avgs[h].append(g.mean())

    avg_hit = {h: np.mean(all_hits[h]) if all_hits[h] else 0.0 for h in HORIZONS}
    avg_bps = {h: np.mean(all_avgs[h]) if all_avgs[h] else 0.0 for h in HORIZONS}
    return avg_hit, avg_bps, total_sigs


rows = []
for t in THRESHOLDS:
    lower = round(1 - t, 2)
    fh, fb, fn = hit_rates_for_threshold('fast', t, lower)
    sh, sb, sn = hit_rates_for_threshold('slow', t, lower)
    rows.append({
        'pct_upper': t,
        'pct_lower': lower,
        **{f'Hit{h}_fast': round(fh[h], 1) for h in HORIZONS},
        **{f'Avg{h}_fast': round(fb[h], 1) for h in HORIZONS},
        **{f'Hit{h}_slow': round(sh[h], 1) for h in HORIZONS},
        **{f'Avg{h}_slow': round(sb[h], 1) for h in HORIZONS},
        'N_fast': fn,
        'N_slow': sn,
        'composite': round(
            np.mean([fh[21], fh[63], sh[21], sh[63]]), 1
        ),
    })

df = pd.DataFrame(rows)
best_idx = df['composite'].idxmax()

# ── Print results ─────────────────────────────────────────────────────────────
H_LABELS = {5: '1W', 10: '2W', 21: '1M', 63: '3M'}

header = (
    f"{'Thresh':>8}  {'N_fast':>7}  {'N_slow':>7}  "
    + "  ".join(f"{'F-' + H_LABELS[h]:>6}" for h in HORIZONS)
    + "  "
    + "  ".join(f"{'S-' + H_LABELS[h]:>6}" for h in HORIZONS)
    + "  {'Comp':>6}"
)
print("\n" + "=" * len(header))
print("CTA REVERSAL — PERCENTILE THRESHOLD SWEEP  (hit rate %, avg across tenors & signals)")
print("=" * len(header))
print(
    f"{'Thresh':>8}  {'N_fast':>7}  {'N_slow':>7}  "
    + "  ".join(f"{'F-'+H_LABELS[h]:>6}" for h in HORIZONS)
    + "  "
    + "  ".join(f"{'S-'+H_LABELS[h]:>6}" for h in HORIZONS)
    + f"  {'Comp':>6}"
)
print("-" * len(header))

for i, r in df.iterrows():
    flag = " ◀ BEST" if i == best_idx else ""
    print(
        f"{int(r['pct_upper']*100):>7}%  {int(r['N_fast']):>7}  {int(r['N_slow']):>7}  "
        + "  ".join(f"{r[f'Hit{h}_fast']:>5.1f}%" for h in HORIZONS)
        + "  "
        + "  ".join(f"{r[f'Hit{h}_slow']:>5.1f}%" for h in HORIZONS)
        + f"  {r['composite']:>5.1f}%"
        + flag
    )

print("=" * len(header))
print(f"\nComposite = avg of Fast 1M, Fast 3M, Slow 1M, Slow 3M hit rates")
print(f"Best threshold: {int(df.loc[best_idx,'pct_upper']*100)}th / {int(df.loc[best_idx,'pct_lower']*100)}th percentile  (composite {df.loc[best_idx,'composite']:.1f}%)\n")

print("\nAvg bps at signal — Fast mode:")
bps_header = f"{'Thresh':>8}  " + "  ".join(f"{H_LABELS[h]:>8}" for h in HORIZONS)
print(bps_header)
for i, r in df.iterrows():
    print(f"{int(r['pct_upper']*100):>7}%  " + "  ".join(f"{r[f'Avg{h}_fast']:>+7.1f}bp" for h in HORIZONS))

print("\nAvg bps at signal — Slow mode:")
print(bps_header)
for i, r in df.iterrows():
    print(f"{int(r['pct_upper']*100):>7}%  " + "  ".join(f"{r[f'Avg{h}_slow']:>+7.1f}bp" for h in HORIZONS))
