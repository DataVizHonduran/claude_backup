"""
CTA Exhaustion Signal Generator - Dual Mode (Fast & Slow)
Fetches FX data, calculates CTA positioning, and generates exhaustion signals.

Improvements (v2):
  P1 - Vectorized position filter (replaces slow df.apply loop)
  P2 - Rolling 500-day percentile thresholds (no look-ahead bias)
  P3 - Rate-of-change confirmation filter (signal fires only when positioning is moving away)
  P4 - Signal strength score 0-100 (Extremity 40 + Speed 40 + Consensus 20)
  P5 - RSI of positioning filter (confirms overbought/oversold state)
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import os
import json
from datetime import datetime

# Configuration
FX_DATA_URL = "https://raw.githubusercontent.com/DataVizHonduran/EMFX_risk_diffusion/main/fx_data_raw.csv"
OUTPUT_DIR = "reports/cta-signals"
GAP = 5              # Hysteresis band for exhaustion signals
WINDOW = 2500        # Rolling window for position normalization
ROLLING_PCT_WINDOW = 500   # ~2 years rolling window for percentile thresholds (P2)
ROLLING_PCT_MINPERIODS = 252  # Minimum days before rolling percentile is valid
RSI_PERIOD = 14      # RSI lookback for positioning series (P5)
CONSENSUS_WINDOW_DAYS = 5   # Max days apart for fast/slow signals to count as consensus (P4)
MA_WINDOWS = [5, 10, 20, 50, 60, 100, 200]  # N-day MA windows for scatter chart tab

# CTA mode configurations
CTA_MODES = {
    'fast': {'short': 20, 'mid': 50, 'long': 100},
    'slow': {'short': 50, 'mid': 100, 'long': 200}
}

print(f"Loading FX data from {FX_DATA_URL}...")
df_fx = pd.read_csv(FX_DATA_URL, index_col=0, parse_dates=True)
df_fx = df_fx.apply(pd.to_numeric, errors='coerce')
print(f"Loaded {len(df_fx)} rows and {len(df_fx.columns)} currencies")

# Process currencies
inverse = ["EUR", "GBP", "AUD", "NZD"]
df_fx[inverse] = 1 / df_fx[inverse]
euroy = ["GBP", "SEK", "NOK", "HUF", "PLN", "CZK"]
df_fx[euroy] = df_fx[euroy].multiply(df_fx["EUR"], axis=0)

# Prepare display data
inverse_display = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"]
df_display = df_fx.copy()
df_display[inverse] = 1 / df_display[inverse]
# Filter to start from 2016
df_display = df_display[df_display.index >= '2016-01-01']

os.makedirs(OUTPUT_DIR, exist_ok=True)


def calculate_rsi(series, period=RSI_PERIOD):
    """Calculate RSI of a series (P5)"""
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_positions(df_fx, short_window, mid_window, long_window):
    """Calculate CTA positioning for all currencies.

    P1: Vectorized position filter replaces slow df.apply() row-by-row loop.
    P5: RSI of positioning series computed per currency.

    Returns:
        positions_latest: dict of {currency: latest_position}
        positions_df:     DataFrame of position_size per currency (cols = {ccy}_posy)
        rsi_df:           DataFrame of positioning RSI per currency (same col names)
    """
    positions_latest = {}
    positions_df = pd.DataFrame()
    rsi_df = pd.DataFrame()

    for currency in df_fx.columns:
        price_series = df_fx[currency].dropna()
        if len(price_series) < long_window:
            continue

        df = pd.DataFrame(index=price_series.index)
        df['price'] = price_series
        df['ema_short'] = df['price'].ewm(span=short_window, adjust=False).mean()
        df['ema_mid']   = df['price'].ewm(span=mid_window,   adjust=False).mean()
        df['ema_long']  = df['price'].ewm(span=long_window,  adjust=False).mean()
        df['ema_convergence'] = df['ema_short'] - df['ema_long']

        rolling_max_abs_conv = df['ema_convergence'].abs().rolling(window=WINDOW, min_periods=1).max()
        rolling_max_abs_conv = rolling_max_abs_conv.replace(0, np.nan).bfill().ffill()
        raw_position_rolling = (df['ema_convergence'] / rolling_max_abs_conv) * 50

        # P1: Vectorized position filter (~50x faster than df.apply)
        trending_up   = (df['ema_short'] > df['ema_mid']) & (df['ema_mid'] > df['ema_long'])
        trending_down = (df['ema_short'] < df['ema_mid']) & (df['ema_mid'] < df['ema_long'])
        df['position_size'] = np.where(
            trending_up,   np.maximum(0, raw_position_rolling),
            np.where(trending_down, np.minimum(0, raw_position_rolling), 0)
        )

        # P5: RSI of the positioning series
        df['rsi_pos'] = calculate_rsi(df['position_size'])

        df.dropna(subset=['position_size'], inplace=True)

        if not df.empty:
            col = f"{currency}_posy"
            positions_latest[currency] = df['position_size'].iloc[-1]
            positions_df[col] = df['position_size']
            rsi_df[col] = df['rsi_pos']

    return positions_latest, positions_df, rsi_df


def generate_exhaustion_signals(positions_df, rolling_upper, rolling_lower, rsi_df):
    """Generate directional exhaustion signals.

    P2: Uses per-date rolling percentile thresholds (no look-ahead bias).
    P3: Only fires when positioning is moving in the correct direction (ROC filter).
    P4: Computes signal strength components (extremity + speed; consensus added later).
    P5: Requires RSI of positioning to confirm overbought/oversold state.

    Returns:
        signals:         DataFrame of 0/1 signals, same shape as positions_df
        signal_metadata: list of dicts with signal details for P4/P6
    """
    signals = pd.DataFrame(0, index=positions_df.index,
                           columns=positions_df.columns, dtype=int)
    signal_metadata = []

    # P3: 1-day rate of change in positioning
    pos_roc = positions_df.diff(1)

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

            # P2: Rolling threshold at this date
            upper_enter = rolling_upper.iloc[i][col] if col in rolling_upper.columns else np.nan
            lower_enter = rolling_lower.iloc[i][col] if col in rolling_lower.columns else np.nan

            # Skip during percentile warmup period
            if pd.isna(upper_enter) or pd.isna(lower_enter):
                continue

            upper_exit = upper_enter - GAP if upper_enter - GAP > 0 else upper_enter - 3
            lower_exit = lower_enter + GAP if lower_enter + GAP < 0 else lower_enter + 3

            roc     = pos_roc.iloc[i][col]
            rsi_val = rsi_df.iloc[i][col] if has_rsi else np.nan

            # ── Not in extreme mode ──────────────────────────────────────────
            if extreme_mode[col] is None:
                if pos >= upper_enter:
                    extreme_mode[col]   = 'long'
                    extreme_peak[col]   = pos
                    # P5: Confirm RSI at entry (NaN = no filter applied)
                    extreme_rsi_ok[col] = pd.isna(rsi_val) or (rsi_val > 70)
                elif pos <= lower_enter:
                    extreme_mode[col]   = 'short'
                    extreme_peak[col]   = pos
                    extreme_rsi_ok[col] = pd.isna(rsi_val) or (rsi_val < 30)

            # ── Long exhaustion watch ────────────────────────────────────────
            elif extreme_mode[col] == 'long':
                if pos > extreme_peak[col]:
                    extreme_peak[col] = pos

                # P5: Track RSI confirmation throughout the extreme phase
                if not extreme_rsi_ok[col]:
                    if pd.isna(rsi_val) or rsi_val > 70:
                        extreme_rsi_ok[col] = True

                # P3: ROC must be negative (positioning declining)
                # P5: RSI must have confirmed overbought state
                roc_ok = pd.isna(roc) or (roc < 0)
                if pos < upper_exit and roc_ok and extreme_rsi_ok[col]:
                    signals.iloc[i, col_idx] = 1

                    # P4: Extremity score (0–40)
                    extremity_range = max(1, 50.0 - float(upper_enter))
                    extremity = min(40.0, (float(extreme_peak[col]) - float(upper_enter))
                                    / extremity_range * 40.0)

                    # P4: Speed score (0–40) — scaled so 3 units/day = max
                    speed = min(40.0, abs(float(roc)) / 3.0 * 40.0) if not pd.isna(roc) else 0.0

                    signal_metadata.append({
                        'date':           positions_df.index[i].strftime('%Y-%m-%d'),
                        'currency':       col.replace('_posy', ''),
                        'direction':      'Long',
                        'peak_position':  round(float(extreme_peak[col]), 2),
                        'threshold':      round(float(upper_enter), 2),
                        'roc_at_signal':  round(float(roc), 4) if not pd.isna(roc) else None,
                        'rsi_at_signal':  round(float(rsi_val), 1) if not pd.isna(rsi_val) else None,
                        'extremity_score': round(extremity, 1),
                        'speed_score':     round(speed, 1),
                        'consensus_score': 0,          # filled in by add_consensus_scores()
                        'strength_score':  round(extremity + speed, 1),
                    })
                    extreme_mode[col]   = None
                    extreme_peak[col]   = None
                    extreme_rsi_ok[col] = False

            # ── Short exhaustion watch ───────────────────────────────────────
            elif extreme_mode[col] == 'short':
                if pos < extreme_peak[col]:
                    extreme_peak[col] = pos

                # P5: Track RSI confirmation throughout the extreme phase
                if not extreme_rsi_ok[col]:
                    if pd.isna(rsi_val) or rsi_val < 30:
                        extreme_rsi_ok[col] = True

                # P3: ROC must be positive (positioning rising)
                roc_ok = pd.isna(roc) or (roc > 0)
                if pos > lower_exit and roc_ok and extreme_rsi_ok[col]:
                    signals.iloc[i, col_idx] = 1

                    # P4: Extremity score (0–40)
                    extremity_range = max(1, float(lower_enter) - (-50.0))
                    extremity = min(40.0, (float(lower_enter) - float(extreme_peak[col]))
                                    / extremity_range * 40.0)

                    # P4: Speed score (0–40)
                    speed = min(40.0, abs(float(roc)) / 3.0 * 40.0) if not pd.isna(roc) else 0.0

                    signal_metadata.append({
                        'date':           positions_df.index[i].strftime('%Y-%m-%d'),
                        'currency':       col.replace('_posy', ''),
                        'direction':      'Short',
                        'peak_position':  round(float(extreme_peak[col]), 2),
                        'threshold':      round(float(lower_enter), 2),
                        'roc_at_signal':  round(float(roc), 4) if not pd.isna(roc) else None,
                        'rsi_at_signal':  round(float(rsi_val), 1) if not pd.isna(rsi_val) else None,
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
            sig_date = datetime.strptime(sig['date'], '%Y-%m-%d')
            ccy       = sig['currency']
            direction = sig['direction']
            for other in signals_b:
                if other['currency'] == ccy and other['direction'] == direction:
                    other_date = datetime.strptime(other['date'], '%Y-%m-%d')
                    if abs((sig_date - other_date).days) <= CONSENSUS_WINDOW_DAYS:
                        sig['consensus_score'] = 20
                        sig['strength_score']  = round(sig['strength_score'] + 20, 1)
                        break
        return signals_a

    fast_metadata = find_consensus(fast_metadata, slow_metadata)
    slow_metadata = find_consensus(slow_metadata, fast_metadata)
    return fast_metadata, slow_metadata


def create_exhaustion_chart(df, ccy, currency, positions_df, signals_df,
                            signal_metadata, mode, windows):
    """Create exhaustion model chart with signal strength score labels (P4)."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df.index, y=df[ccy], mode='lines',
        name='Price', line=dict(color='teal', width=2), yaxis='y1'
    ))

    # Filter positioning to match price data timeframe
    pos_filtered = positions_df[positions_df.index.isin(df.index)]

    fig.add_trace(go.Scatter(
        x=pos_filtered.index, y=pos_filtered[currency], mode='lines',
        name='CTA Positioning', line=dict(color='orange', width=1.5),
        yaxis='y2', opacity=0.6
    ))

    if currency in signals_df.columns:
        signal_points = signals_df[currency] == 1
        signal_dates  = signals_df.index[signal_points].intersection(df.index)
        signal_prices = df.loc[signal_dates, ccy]

        # Build lookup: date string → signal record for strength score labels
        sig_lookup = {s['date']: s for s in signal_metadata if s['currency'] == ccy}
        text_labels = [
            str(int(sig_lookup[d.strftime('%Y-%m-%d')]['strength_score']))
            if d.strftime('%Y-%m-%d') in sig_lookup else ''
            for d in signal_dates
        ]

        fig.add_trace(go.Scatter(
            x=signal_dates, y=signal_prices, mode='markers+text',
            marker=dict(color='red', size=10, line=dict(color='black', width=1)),
            text=text_labels,
            textposition='top center',
            textfont=dict(size=10, color='darkred'),
            name='Exhaustion Signals', yaxis='y1'
        ))

    fig.update_layout(
        title=dict(
            text=f"{ccy} - CTA {mode.upper()} ({windows}) - Positioning & Exhaustion Signals",
            x=0.5, xanchor='center', font=dict(size=18, color='darkblue')
        ),
        xaxis=dict(title="Date", showgrid=True, gridcolor='lightgrey',
                   zeroline=False, tickformat='%Y', dtick='M12', tickangle=0),
        yaxis=dict(title="Price", tickfont=dict(color='teal'),
                   showgrid=True, zeroline=False),
        yaxis2=dict(title="CTA Positioning", tickfont=dict(color='goldenrod'),
                    overlaying='y', side='right', showgrid=False, zeroline=False),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)',
                    bordercolor='black', borderwidth=1),
        hovermode='x unified', plot_bgcolor='white',
        width=1000, height=600
    )
    return fig


# ── Phase 1: Calculate positions + signals for both modes ────────────────────
mode_data = {}
all_summaries = {}

for mode, windows in CTA_MODES.items():
    print(f"\n{'='*60}")
    print(f"Processing {mode.upper()} mode ({windows['short']}/{windows['mid']}/{windows['long']})...")
    print(f"{'='*60}")

    # P1: Vectorized position calculation
    positions_latest, positions_df, rsi_df = calculate_positions(
        df_fx, windows['short'], windows['mid'], windows['long']
    )
    print(f"Calculated positioning for {len(positions_latest)} currencies")

    # P2: Rolling percentile thresholds (no look-ahead bias)
    rolling_upper = positions_df.rolling(
        window=ROLLING_PCT_WINDOW, min_periods=ROLLING_PCT_MINPERIODS
    ).quantile(0.85)
    rolling_lower = positions_df.rolling(
        window=ROLLING_PCT_WINDOW, min_periods=ROLLING_PCT_MINPERIODS
    ).quantile(0.15)
    print(f"Computed {ROLLING_PCT_WINDOW}-day rolling percentile thresholds")

    # P2 + P3 + P4 + P5: Generate signals
    signals_df, signal_metadata = generate_exhaustion_signals(
        positions_df, rolling_upper, rolling_lower, rsi_df
    )
    print(f"Generated {len(signal_metadata)} exhaustion signals")

    latest_positions = pd.Series(positions_latest).sort_values(ascending=False)

    mode_data[mode] = {
        'positions_df':    positions_df,
        'signals_df':      signals_df,
        'signal_metadata': signal_metadata,
        'positions_latest': positions_latest,
        'latest_positions': latest_positions,
    }

    all_summaries[mode] = {
        'generated_at':   datetime.now().isoformat(),
        'mode':           mode,
        'windows':        f"{windows['short']}/{windows['mid']}/{windows['long']}",
        'currencies':     len(positions_latest),
        'latest_positions': latest_positions.to_dict(),
    }

    print(f"Top 5 Long:  {list(latest_positions.head().items())}")
    print(f"Top 5 Short: {list(latest_positions.tail().items())}")


# ── Phase 2: Cross-mode consensus scoring (P4) ───────────────────────────────
print("\nComputing cross-mode consensus scores...")
fast_meta, slow_meta = add_consensus_scores(
    mode_data['fast']['signal_metadata'],
    mode_data['slow']['signal_metadata']
)
mode_data['fast']['signal_metadata'] = fast_meta
mode_data['slow']['signal_metadata'] = slow_meta


# ── Phase 3: Generate charts with final metadata ─────────────────────────────
for mode, windows in CTA_MODES.items():
    data             = mode_data[mode]
    positions_df     = data['positions_df']
    signals_df       = data['signals_df']
    signal_metadata  = data['signal_metadata']
    positions_latest = data['positions_latest']

    chart_count = 0
    for ccy in df_display.columns:
        currency = ccy + "_posy"
        if currency not in positions_df.columns:
            continue
        try:
            fig = create_exhaustion_chart(
                df_display, ccy, currency, positions_df, signals_df,
                signal_metadata, mode,
                f"{CTA_MODES[mode]['short']}/{CTA_MODES[mode]['mid']}/{CTA_MODES[mode]['long']}"
            )
            filename = os.path.join(OUTPUT_DIR, f"{ccy}_exhaustion_{mode}.html")
            pio.write_html(fig, file=filename, auto_open=False)
            chart_count += 1
        except Exception as e:
            print(f"Failed on {currency}: {e}")

    print(f"Generated {chart_count} charts for {mode} mode")

    high_conviction = [s for s in signal_metadata if s.get('strength_score', 0) >= 60]
    all_summaries[mode]['charts_generated']      = chart_count
    all_summaries[mode]['signal_count']          = len(signal_metadata)
    all_summaries[mode]['high_conviction_count'] = len(high_conviction)
    # Store sorted metadata (most recent first) for generate_index.py
    all_summaries[mode]['signal_metadata'] = sorted(
        signal_metadata, key=lambda x: x['date'], reverse=True
    )

    # MA positions for scatter chart tab in generate_index.py
    ma_pos = {}
    for n in MA_WINDOWS:
        ma_row = positions_df.rolling(n, min_periods=1).mean().iloc[-1]
        ma_pos[str(n)] = {
            col.replace('_posy', ''): round(float(val), 4)
            for col, val in ma_row.items()
            if not pd.isna(val)
        }
    all_summaries[mode]['ma_positions'] = ma_pos


# ── Save combined summary ─────────────────────────────────────────────────────
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'w') as f:
    json.dump(all_summaries, f, indent=2)

print(f"\n{'='*60}")
print(f"✅ Complete! Generated charts for both FAST and SLOW modes")
print(f"   Fast signals: {all_summaries['fast']['signal_count']}  "
      f"(high conviction: {all_summaries['fast']['high_conviction_count']})")
print(f"   Slow signals: {all_summaries['slow']['signal_count']}  "
      f"(high conviction: {all_summaries['slow']['high_conviction_count']})")
print(f"Summary saved to {OUTPUT_DIR}/summary.json")
print(f"{'='*60}")
