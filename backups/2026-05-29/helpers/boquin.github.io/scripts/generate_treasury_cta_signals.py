"""
Treasury CTA Exhaustion Signal Generator - Dual Mode (Fast & Slow)
Fetches 2Y/5Y/10Y/30Y Treasury yield data from FRED, calculates CTA positioning,
and generates exhaustion signals using the same methodology as FX CTA.

Positive position  → CTAs positioned for RISING yields (short duration / short bonds)
Negative position  → CTAs positioned for FALLING yields (long duration / long bonds)

Filters (same as FX version):
  P1 - Vectorized position filter
  P2 - Rolling 500-day percentile thresholds (no look-ahead bias)
  P3 - Rate-of-change confirmation filter
  P4 - Signal strength score 0-100 (Extremity 40 + Speed 40 + Consensus 20)
  P5 - RSI of positioning filter
"""

import sys
import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta
from fredapi import Fred

# ── FRED API key — set FRED_API_KEY environment variable ─────────────────────
FRED_API_KEY = os.environ.get('FRED_API_KEY')
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set. "
                           "Export it before running: export FRED_API_KEY=your_key")


def pull_data(series_dict, years=16):
    """Fetch FRED series and return a merged, forward-filled DataFrame."""
    fred       = Fred(api_key=FRED_API_KEY)
    end_date   = datetime.now()
    start_date = end_date - relativedelta(years=years)
    frames     = []
    for sid, label in series_dict.items():
        try:
            s = fred.get_series(sid, observation_start=start_date,
                                observation_end=end_date)
            frames.append(s.to_frame(name=label))
        except Exception as e:
            print(f"  ⚠️  Failed to fetch {sid}: {e}")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, axis=1)
    df.ffill(inplace=True)
    df.dropna(inplace=True)
    return df

# ── Configuration ─────────────────────────────────────────────────────────────
OUTPUT_DIR           = "reports/treasury-cta-signals"
GAP                  = 3              # Hysteresis band (smaller than FX; yields move in tighter ranges)
WINDOW               = 750            # Rolling window for position normalization (~3 years)
ROLLING_PCT_WINDOW   = 500            # ~2 years rolling window for percentile thresholds (P2)
ROLLING_PCT_MINPERIODS = 252          # Minimum days before rolling percentile is valid
RSI_PERIOD           = 14             # RSI lookback for positioning series (P5)
CONSENSUS_WINDOW_DAYS = 5             # Max days apart for fast/slow signals to count as consensus
YEARS_HISTORY        = 16            # Years of FRED data to pull

# Treasury tenors
TREASURIES = {
    'DGS2':  '2Y',
    'DGS5':  '5Y',
    'DGS10': '10Y',
    'DGS30': '30Y',
}

# CTA mode configurations (same windows as FX model)
CTA_MODES = {
    'fast': {'short': 20, 'mid': 50,  'long': 100},
    'slow': {'short': 50, 'mid': 100, 'long': 200},
}

# ── Data loading ──────────────────────────────────────────────────────────────
print(f"Fetching Treasury yield data from FRED ({YEARS_HISTORY} years)...")
df_raw = pull_data(TREASURIES, years=YEARS_HISTORY)
# Rename columns to short labels: '2Y', '5Y', '10Y', '30Y'
df_raw.columns = [TREASURIES[k] for k in TREASURIES]
# Drop any all-NaN rows (weekends already forward-filled by pull_data, but double-check)
df_raw = df_raw.dropna(how='all')
print(f"Loaded {len(df_raw)} rows | {df_raw.index.min().date()} to {df_raw.index.max().date()}")
print(f"Latest yields: " + " | ".join(f"{c}: {df_raw[c].iloc[-1]:.2f}%" for c in df_raw.columns))

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Display-filtered copy (from 2016 onward, matching FX chart horizon)
df_display = df_raw[df_raw.index >= '2016-01-01'].copy()


# ── Helper functions (identical logic to generate_cta_signals.py) ─────────────

def calculate_rsi(series, period=RSI_PERIOD):
    """Calculate RSI of a series (P5)."""
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_positions(df, short_window, mid_window, long_window):
    """
    Calculate CTA positioning for all Treasury tenors.

    Returns:
        positions_latest : dict {tenor: latest_position}
        positions_df     : DataFrame of position_size per tenor
        rsi_df           : DataFrame of positioning RSI per tenor
    """
    positions_latest = {}
    positions_df     = pd.DataFrame()
    rsi_df           = pd.DataFrame()

    for tenor in df.columns:
        series = df[tenor].dropna()
        if len(series) < long_window:
            continue

        d = pd.DataFrame(index=series.index)
        d['price']     = series
        d['ema_short'] = d['price'].ewm(span=short_window, adjust=False).mean()
        d['ema_mid']   = d['price'].ewm(span=mid_window,   adjust=False).mean()
        d['ema_long']  = d['price'].ewm(span=long_window,  adjust=False).mean()
        d['ema_convergence'] = d['ema_short'] - d['ema_long']

        rolling_max_abs = (d['ema_convergence'].abs()
                           .rolling(window=WINDOW, min_periods=1).quantile(0.95)
                           .replace(0, np.nan).bfill().ffill())
        raw_pos = (d['ema_convergence'] / rolling_max_abs) * 50

        # P1: Vectorized trend filter
        up   = (d['ema_short'] > d['ema_mid']) & (d['ema_mid'] > d['ema_long'])
        down = (d['ema_short'] < d['ema_mid']) & (d['ema_mid'] < d['ema_long'])
        d['position_size'] = np.where(
            up,   np.maximum(0, raw_pos),
            np.where(down, np.minimum(0, raw_pos), 0)
        )

        # P5: RSI of positioning
        d['rsi_pos'] = calculate_rsi(d['position_size'])
        d.dropna(subset=['position_size'], inplace=True)

        if not d.empty:
            col = f"{tenor}_posy"
            positions_latest[tenor]  = d['position_size'].iloc[-1]
            positions_df[col]        = d['position_size']
            rsi_df[col]              = d['rsi_pos']

    return positions_latest, positions_df, rsi_df


def generate_exhaustion_signals(positions_df, rolling_upper, rolling_lower, rsi_df):
    """
    Generate directional exhaustion signals (P2–P5).

    Returns:
        signals         : DataFrame of 0/1 signals
        signal_metadata : list of dicts with signal details
    """
    signals = pd.DataFrame(0, index=positions_df.index,
                           columns=positions_df.columns, dtype=int)
    signal_metadata = []

    pos_roc        = positions_df.diff(1)
    extreme_mode   = {col: None  for col in positions_df.columns}
    extreme_peak   = {col: None  for col in positions_df.columns}
    extreme_rsi_ok = {col: False for col in positions_df.columns}

    for col in positions_df.columns:
        col_idx = signals.columns.get_loc(col)
        has_rsi = col in rsi_df.columns

        for i in range(len(positions_df)):
            pos = positions_df.iloc[i][col]
            if pd.isna(pos):
                continue

            upper_enter = rolling_upper.iloc[i][col] if col in rolling_upper.columns else np.nan
            lower_enter = rolling_lower.iloc[i][col] if col in rolling_lower.columns else np.nan

            if pd.isna(upper_enter) or pd.isna(lower_enter):
                continue

            upper_exit = upper_enter - GAP if upper_enter - GAP > 0 else upper_enter - 2
            lower_exit = lower_enter + GAP if lower_enter + GAP < 0 else lower_enter + 2

            roc     = pos_roc.iloc[i][col]
            rsi_val = rsi_df.iloc[i][col] if has_rsi else np.nan

            # ── Not in extreme mode ──────────────────────────────────────────
            if extreme_mode[col] is None:
                if pos >= upper_enter:
                    extreme_mode[col]   = 'long'
                    extreme_peak[col]   = pos
                    extreme_rsi_ok[col] = pd.isna(rsi_val) or (rsi_val > 70)
                elif pos <= lower_enter:
                    extreme_mode[col]   = 'short'
                    extreme_peak[col]   = pos
                    extreme_rsi_ok[col] = pd.isna(rsi_val) or (rsi_val < 30)

            # ── Long exhaustion watch (CTAs very short duration / yield rising) ─
            elif extreme_mode[col] == 'long':
                if pos > extreme_peak[col]:
                    extreme_peak[col] = pos
                if not extreme_rsi_ok[col]:
                    if pd.isna(rsi_val) or rsi_val > 70:
                        extreme_rsi_ok[col] = True

                roc_ok = pd.isna(roc) or (roc < 0)
                if pos < upper_exit and roc_ok and extreme_rsi_ok[col]:
                    signals.iloc[i, col_idx] = 1

                    extremity_range = max(1, 50.0 - float(upper_enter))
                    extremity = min(40.0, (float(extreme_peak[col]) - float(upper_enter))
                                    / extremity_range * 40.0)
                    speed = min(40.0, abs(float(roc)) / 3.0 * 40.0) if not pd.isna(roc) else 0.0

                    signal_metadata.append({
                        'date':            positions_df.index[i].strftime('%Y-%m-%d'),
                        'tenor':           col.replace('_posy', ''),
                        'direction':       'Short',      # short duration / rising yields
                        'peak_position':   round(float(extreme_peak[col]), 2),
                        'threshold':       round(float(upper_enter), 2),
                        'roc_at_signal':   round(float(roc), 4)   if not pd.isna(roc)     else None,
                        'rsi_at_signal':   round(float(rsi_val), 1) if not pd.isna(rsi_val) else None,
                        'extremity_score': round(extremity, 1),
                        'speed_score':     round(speed, 1),
                        'consensus_score': 0,
                        'strength_score':  round(extremity + speed, 1),
                    })
                    extreme_mode[col]   = None
                    extreme_peak[col]   = None
                    extreme_rsi_ok[col] = False

            # ── Short exhaustion watch (CTAs very long duration / yield falling) ─
            elif extreme_mode[col] == 'short':
                if pos < extreme_peak[col]:
                    extreme_peak[col] = pos
                if not extreme_rsi_ok[col]:
                    if pd.isna(rsi_val) or rsi_val < 30:
                        extreme_rsi_ok[col] = True

                roc_ok = pd.isna(roc) or (roc > 0)
                if pos > lower_exit and roc_ok and extreme_rsi_ok[col]:
                    signals.iloc[i, col_idx] = 1

                    extremity_range = max(1, float(lower_enter) - (-50.0))
                    extremity = min(40.0, (float(lower_enter) - float(extreme_peak[col]))
                                    / extremity_range * 40.0)
                    speed = min(40.0, abs(float(roc)) / 3.0 * 40.0) if not pd.isna(roc) else 0.0

                    signal_metadata.append({
                        'date':            positions_df.index[i].strftime('%Y-%m-%d'),
                        'tenor':           col.replace('_posy', ''),
                        'direction':       'Long',       # long duration / falling yields
                        'peak_position':   round(float(extreme_peak[col]), 2),
                        'threshold':       round(float(lower_enter), 2),
                        'roc_at_signal':   round(float(roc), 4)   if not pd.isna(roc)     else None,
                        'rsi_at_signal':   round(float(rsi_val), 1) if not pd.isna(rsi_val) else None,
                        'extremity_score': round(extremity, 1),
                        'speed_score':     round(speed, 1),
                        'consensus_score': 0,
                        'strength_score':  round(extremity + speed, 1),
                    })
                    extreme_mode[col]   = None
                    extreme_peak[col]   = None
                    extreme_rsi_ok[col] = False

    return signals, signal_metadata


def add_consensus_scores(fast_metadata, slow_metadata):
    """P4: Add 20-pt consensus bonus when fast & slow agree within CONSENSUS_WINDOW_DAYS."""

    def find_consensus(signals_a, signals_b):
        for sig in signals_a:
            sig_date  = datetime.strptime(sig['date'], '%Y-%m-%d')
            tenor     = sig['tenor']
            direction = sig['direction']
            for other in signals_b:
                if other['tenor'] == tenor and other['direction'] == direction:
                    other_date = datetime.strptime(other['date'], '%Y-%m-%d')
                    if abs((sig_date - other_date).days) <= CONSENSUS_WINDOW_DAYS:
                        sig['consensus_score'] = 20
                        sig['strength_score']  = round(sig['strength_score'] + 20, 1)
                        break
        return signals_a

    fast_metadata = find_consensus(fast_metadata, slow_metadata)
    slow_metadata = find_consensus(slow_metadata, fast_metadata)
    return fast_metadata, slow_metadata


def create_exhaustion_chart(df_display, tenor, col, positions_df,
                             signals_df, signal_metadata, mode, windows_str):
    """Create exhaustion model chart for a Treasury tenor."""
    fig = go.Figure()

    # Yield line
    fig.add_trace(go.Scatter(
        x=df_display.index, y=df_display[tenor], mode='lines',
        name=f'{tenor} Yield (%)',
        line=dict(color='steelblue', width=2), yaxis='y1'
    ))

    # CTA positioning overlay
    pos_filtered = positions_df[positions_df.index.isin(df_display.index)]
    if col in pos_filtered.columns:
        fig.add_trace(go.Scatter(
            x=pos_filtered.index, y=pos_filtered[col], mode='lines',
            name='CTA Positioning',
            line=dict(color='orange', width=1.5),
            yaxis='y2', opacity=0.65
        ))

    # Exhaustion signal markers
    if col in signals_df.columns:
        signal_pts   = signals_df[col] == 1
        signal_dates = signals_df.index[signal_pts].intersection(df_display.index)
        signal_ylds  = df_display.loc[signal_dates, tenor]

        sig_lookup = {s['date']: s for s in signal_metadata if s['tenor'] == tenor}
        text_labels = [
            str(int(sig_lookup[d.strftime('%Y-%m-%d')]['strength_score']))
            if d.strftime('%Y-%m-%d') in sig_lookup else ''
            for d in signal_dates
        ]

        fig.add_trace(go.Scatter(
            x=signal_dates, y=signal_ylds, mode='markers+text',
            marker=dict(color='crimson', size=10, line=dict(color='black', width=1)),
            text=text_labels,
            textposition='top center',
            textfont=dict(size=10, color='darkred'),
            name='Exhaustion Signals', yaxis='y1'
        ))

    # Positioning zero-line reference
    fig.add_hline(y=0, line_dash='dash', line_color='grey',
                  line_width=0.8, yref='y2', opacity=0.5)

    fig.update_layout(
        title=dict(
            text=(f"US {tenor} Treasury — CTA {mode.upper()} ({windows_str})"
                  f" — Positioning & Exhaustion Signals"),
            x=0.5, xanchor='center', font=dict(size=18, color='#1a1a2e')
        ),
        xaxis=dict(
            title="Date", showgrid=True, gridcolor='lightgrey',
            zeroline=False, tickformat='%Y', dtick='M12', tickangle=0
        ),
        yaxis=dict(
            title="Yield (%)", tickfont=dict(color='steelblue'),
            ticksuffix='%', showgrid=True, zeroline=False
        ),
        yaxis2=dict(
            title="CTA Positioning", tickfont=dict(color='goldenrod'),
            overlaying='y', side='right', showgrid=False, zeroline=True,
            zerolinecolor='grey', zerolinewidth=1, range=[-60, 60]
        ),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.85)',
                    bordercolor='black', borderwidth=1),
        hovermode='x unified', plot_bgcolor='white',
        width=1100, height=620,
        annotations=[dict(
            text=("Positive = CTAs short duration (rising yields) | "
                  "Negative = CTAs long duration (falling yields)"),
            xref='paper', yref='paper', x=0.5, y=-0.08,
            showarrow=False, font=dict(size=11, color='grey'), align='center'
        )]
    )
    return fig


# ── Phase 1: Calculate positions + signals for both modes ─────────────────────
mode_data    = {}
all_summaries = {}

for mode, windows in CTA_MODES.items():
    print(f"\n{'='*60}")
    print(f"Processing {mode.upper()} mode ({windows['short']}/{windows['mid']}/{windows['long']})...")
    print(f"{'='*60}")

    positions_latest, positions_df, rsi_df = calculate_positions(
        df_raw, windows['short'], windows['mid'], windows['long']
    )
    print(f"Calculated positioning for {len(positions_latest)} tenors")

    # P2: Rolling percentile thresholds
    rolling_upper = positions_df.rolling(
        window=ROLLING_PCT_WINDOW, min_periods=ROLLING_PCT_MINPERIODS
    ).quantile(0.85)
    rolling_lower = positions_df.rolling(
        window=ROLLING_PCT_WINDOW, min_periods=ROLLING_PCT_MINPERIODS
    ).quantile(0.15)
    print(f"Computed {ROLLING_PCT_WINDOW}-day rolling percentile thresholds")

    signals_df, signal_metadata = generate_exhaustion_signals(
        positions_df, rolling_upper, rolling_lower, rsi_df
    )
    print(f"Generated {len(signal_metadata)} exhaustion signals")

    latest_positions = pd.Series(positions_latest).sort_values(ascending=False)

    mode_data[mode] = {
        'positions_df':     positions_df,
        'signals_df':       signals_df,
        'signal_metadata':  signal_metadata,
        'positions_latest': positions_latest,
        'latest_positions': latest_positions,
    }

    all_summaries[mode] = {
        'generated_at':     datetime.now().isoformat(),
        'mode':             mode,
        'windows':          f"{windows['short']}/{windows['mid']}/{windows['long']}",
        'tenors':           len(positions_latest),
        'latest_positions': latest_positions.to_dict(),
        'latest_yields': {t: round(float(df_raw[t].iloc[-1]), 4)
                          for t in df_raw.columns},
        'data_as_of':       df_raw.index[-1].strftime('%Y-%m-%d'),
    }

    print(f"Positions: {dict(latest_positions.round(1))}")


# ── Phase 2: Cross-mode consensus scoring (P4) ────────────────────────────────
print("\nComputing cross-mode consensus scores...")
fast_meta, slow_meta = add_consensus_scores(
    mode_data['fast']['signal_metadata'],
    mode_data['slow']['signal_metadata']
)
mode_data['fast']['signal_metadata'] = fast_meta
mode_data['slow']['signal_metadata'] = slow_meta


# ── Phase 3: Generate charts ──────────────────────────────────────────────────
for mode, windows in CTA_MODES.items():
    data            = mode_data[mode]
    positions_df    = data['positions_df']
    signals_df      = data['signals_df']
    signal_metadata = data['signal_metadata']
    windows_str     = f"{CTA_MODES[mode]['short']}/{CTA_MODES[mode]['mid']}/{CTA_MODES[mode]['long']}"

    chart_count = 0
    for tenor in df_display.columns:
        col = f"{tenor}_posy"
        if col not in positions_df.columns:
            continue
        try:
            fig = create_exhaustion_chart(
                df_display, tenor, col, positions_df,
                signals_df, signal_metadata, mode, windows_str
            )
            filename = os.path.join(OUTPUT_DIR, f"{tenor}_exhaustion_{mode}.html")
            pio.write_html(fig, file=filename, auto_open=False)
            chart_count += 1
        except Exception as e:
            print(f"  Failed on {tenor}: {e}")

    print(f"Generated {chart_count} charts for {mode} mode")

    high_conviction = [s for s in signal_metadata if s.get('strength_score', 0) >= 60]
    all_summaries[mode]['charts_generated']      = chart_count
    all_summaries[mode]['signal_count']          = len(signal_metadata)
    all_summaries[mode]['high_conviction_count'] = len(high_conviction)
    all_summaries[mode]['signal_metadata']       = sorted(
        signal_metadata, key=lambda x: x['date'], reverse=True
    )


# ── Save combined summary ──────────────────────────────────────────────────────
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'w') as f:
    json.dump(all_summaries, f, indent=2)

print(f"\n{'='*60}")
print(f"✅ Treasury CTA Complete!")
print(f"   Fast signals: {all_summaries['fast']['signal_count']}"
      f"  (high conviction: {all_summaries['fast']['high_conviction_count']})")
print(f"   Slow signals: {all_summaries['slow']['signal_count']}"
      f"  (high conviction: {all_summaries['slow']['high_conviction_count']})")
print(f"   Output dir: {OUTPUT_DIR}/")
print(f"{'='*60}")
