"""
30-Year Treasury Momentum Divergence Signals
=============================================
Replicates a JPMorgan-style "momentum divergence buy signal" chart on the
weekly 30Y Treasury yield (FRED DGS30).

Signal logic: bearish price/momentum divergence — the weekly yield makes a
higher high while a momentum oscillator (RSI-14 or MACD histogram 12/26/9)
makes a lower high. That divergence flags exhausted upside momentum in
yields and has historically preceded multi-month reversals to LOWER yields
(a bond buy signal). Both oscillators are computed; whichever produces a
signal cadence closer to a "handful of times per decade" is used for the
published chart.

A companion study compares the vol-adjusted 13-week forward yield change
after each signal against a random-date baseline (1000 seeded draws).

Required env var:
  FRED_API_KEY   (get one free at https://fred.stlouisfed.org/docs/api/api_key.html)

Run:
  FRED_API_KEY=xxx python3 scripts/generate_treasury_momentum_divergence.py
"""

import os
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from fredapi import Fred
from scipy.signal import argrelextrema

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set. "
                            "Export it before running: export FRED_API_KEY=your_key")

SERIES_ID = "DGS30"
START_DATE = "1977-01-01"          # 30Y issuance began 1977 (gap 2002-2006)
RESAMPLE_RULE = "W-FRI"

RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

PIVOT_ORDER = 4                    # weeks either side for local-high detection
MIN_PIVOT_SPACING_WEEKS = 8        # collapse highs closer than this
TARGET_SIGNAL_RATE_PER_YR = 0.2    # "handful of times" over decades ≈ 1 per 5yrs

FWD_WEEKS = 13
VOL_LOOKBACK_WEEKS = 52
RANDOM_DRAWS = 1000
RANDOM_SEED = 42

OUTPUT_DIR = "reports/treasury-momentum-divergence"
OUTPUT_PATH = f"{OUTPUT_DIR}/index.html"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def pull_weekly_yield(fred: Fred) -> pd.Series:
    s = fred.get_series(SERIES_ID, observation_start=START_DATE)
    s.index = pd.to_datetime(s.index)
    s = s.dropna()
    weekly = s.resample(RESAMPLE_RULE).last().dropna()
    weekly.name = "yield"
    return weekly


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------

def calculate_rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_macd_hist(series: pd.Series, fast=MACD_FAST, slow=MACD_SLOW, sig=MACD_SIGNAL) -> pd.Series:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=sig, adjust=False).mean()
    return macd_line - signal_line


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------

def find_local_highs(series: pd.Series, order: int = PIVOT_ORDER) -> list:
    """Integer positions of local highs, deduped by minimum spacing."""
    idx = argrelextrema(series.values, np.greater_equal, order=order)[0]
    highs = []
    for i in idx:
        if highs and i - highs[-1] < MIN_PIVOT_SPACING_WEEKS:
            if series.values[i] >= series.values[highs[-1]]:
                highs[-1] = i
        else:
            highs.append(i)
    return highs


def detect_bearish_divergence(yield_s: pd.Series, osc_s: pd.Series, high_idx: list) -> list:
    """Yield higher high + oscillator lower high -> bond buy signal."""
    signals = []
    valid = [i for i in high_idx if not pd.isna(osc_s.iloc[i])]
    for a, b in zip(valid[:-1], valid[1:]):
        y_a, y_b = yield_s.iloc[a], yield_s.iloc[b]
        o_a, o_b = osc_s.iloc[a], osc_s.iloc[b]
        if y_b > y_a and o_b < o_a:
            signals.append({
                "date": yield_s.index[b],
                "yield_at_signal": float(y_b),
                "osc_at_signal": float(o_b),
                "prior_high_date": yield_s.index[a],
            })
    return signals


def select_method(yield_s: pd.Series, rsi_s: pd.Series, macd_s: pd.Series, highs: list):
    rsi_signals = detect_bearish_divergence(yield_s, rsi_s, highs)
    macd_signals = detect_bearish_divergence(yield_s, macd_s, highs)
    years = (yield_s.index[-1] - yield_s.index[0]).days / 365.25

    rsi_rate = len(rsi_signals) / years
    macd_rate = len(macd_signals) / years
    print(f"      RSI-14 divergence:    {len(rsi_signals)} signals ({rsi_rate:.2f}/yr)")
    print(f"      MACD-hist divergence: {len(macd_signals)} signals ({macd_rate:.2f}/yr)")

    candidates = [
        ("RSI-14", rsi_signals, rsi_rate),
        ("MACD Histogram (12/26/9)", macd_signals, macd_rate),
    ]
    name, signals, rate = min(candidates, key=lambda c: abs(c[2] - TARGET_SIGNAL_RATE_PER_YR))
    print(f"      Selected: {name} ({len(signals)} signals, {rate:.2f}/yr)")
    return name, signals


# ---------------------------------------------------------------------------
# Forward-return study
# ---------------------------------------------------------------------------

def compute_weekly_vol(yield_s: pd.Series, lookback: int = VOL_LOOKBACK_WEEKS) -> pd.Series:
    return yield_s.diff().rolling(lookback).std()


def compute_vol_adj_forward_change(yield_s: pd.Series, vol_s: pd.Series, fwd_weeks: int = FWD_WEEKS) -> pd.Series:
    fwd_change = yield_s.shift(-fwd_weeks) - yield_s
    return fwd_change / vol_s


def signal_forward_stats(signal_dates: list, vol_adj_fwd: pd.Series) -> dict:
    vals = vol_adj_fwd.reindex(signal_dates).dropna()
    return {"n": int(len(vals)), "mean": float(vals.mean()) if len(vals) else float("nan"),
            "std": float(vals.std()) if len(vals) > 1 else float("nan"), "values": vals}


def random_baseline_stats(vol_adj_fwd: pd.Series, exclude_dates: list, n_signals: int,
                           n_draws: int = RANDOM_DRAWS, seed: int = RANDOM_SEED) -> dict:
    pool = vol_adj_fwd.dropna()
    pool = pool[~pool.index.isin(exclude_dates)]
    rng = np.random.default_rng(seed)
    n = max(1, min(n_signals, len(pool)))
    values = pool.values
    draw_means = np.array([rng.choice(values, size=n, replace=False).mean() for _ in range(n_draws)])
    return {"draw_means": draw_means, "mean": float(draw_means.mean()), "std": float(draw_means.std())}


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _range_selector() -> dict:
    """1y/2y/3y/5y/10y/20y/All zoom buttons + a scrub slider, for time-series charts."""
    return dict(
        buttons=[
            dict(count=1, label="1y", step="year", stepmode="backward"),
            dict(count=2, label="2y", step="year", stepmode="backward"),
            dict(count=3, label="3y", step="year", stepmode="backward"),
            dict(count=5, label="5y", step="year", stepmode="backward"),
            dict(count=10, label="10y", step="year", stepmode="backward"),
            dict(count=20, label="20y", step="year", stepmode="backward"),
            dict(step="all", label="All"),
        ],
        bgcolor="#f0f0f0", activecolor="#c8d8ea", font=dict(size=11),
    )


def build_fig2(yield_s: pd.Series, signals: list, osc_name: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=yield_s.index, y=yield_s.values, mode="lines",
        name="30Y Treasury Yield",
        line=dict(color="steelblue", width=1.8),
        hovertemplate="%{x|%b %Y}<br>%{y:.2f}%<extra></extra>",
    ))
    if signals:
        fig.add_trace(go.Scatter(
            x=[s["date"] for s in signals],
            y=[s["yield_at_signal"] * 1.03 for s in signals],
            mode="markers", name="Momentum Divergence Buy Signal",
            marker=dict(symbol="triangle-down", size=13, color="red",
                        line=dict(width=1, color="darkred")),
            hovertemplate="%{x|%b %d, %Y}<br>Signal<extra></extra>",
        ))
    fig.update_layout(
        title=dict(
            text=f"30Y Treasury Yield — Weekly Bearish {osc_name} Divergence (Bond Buy) Signals",
            x=0.5, xanchor="center", font=dict(size=18, color="#1a1a2e"),
        ),
        xaxis=dict(title="Date", showgrid=True, gridcolor="lightgrey",
                    rangeselector=_range_selector(), rangeslider=dict(visible=True, thickness=0.06)),
        yaxis=dict(title="Yield (%)", ticksuffix="%", showgrid=True, zeroline=False),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.85)",
                    bordercolor="black", borderwidth=1),
        hovermode="x unified", plot_bgcolor="white", width=1100, height=680,
        annotations=[dict(
            text=(f"Source: FRED {SERIES_ID}, weekly ({RESAMPLE_RULE}) resample. Signal = weekly yield "
                  f"higher high with {osc_name} lower high (bearish divergence)."),
            xref="paper", yref="paper", x=0.5, y=-0.09, showarrow=False,
            font=dict(size=11, color="grey"), align="center",
        )],
    )
    return fig


def build_fig_osc(yield_s: pd.Series, osc_s: pd.Series, signals: list, osc_name: str) -> go.Figure:
    """Oscillator panel with each divergence window shaded and the two pivot
    points connected by a dashed line, so the 'lower high' is visible."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=osc_s.index, y=osc_s.values, mode="lines",
        name=osc_name, line=dict(color="#7b52ab", width=1.6),
        hovertemplate="%{x|%b %Y}<br>%{y:.2f}<extra></extra>",
    ))
    if osc_name == "RSI-14":
        fig.add_hline(y=70, line_dash="dot", line_color="grey", opacity=0.5)
        fig.add_hline(y=30, line_dash="dot", line_color="grey", opacity=0.5)
    else:
        fig.add_hline(y=0, line_dash="dot", line_color="grey", opacity=0.5)

    for i, s in enumerate(signals):
        fig.add_vrect(x0=s["prior_high_date"], x1=s["date"],
                      fillcolor="rgba(220,53,69,0.12)", line_width=0, layer="below")
        osc_at_prior = float(osc_s.loc[s["prior_high_date"]])
        fig.add_trace(go.Scatter(
            x=[s["prior_high_date"], s["date"]],
            y=[osc_at_prior, s["osc_at_signal"]],
            mode="lines+markers",
            line=dict(color="red", width=1.5, dash="dash"),
            marker=dict(size=6, color="red"),
            showlegend=(i == 0), name="Divergence pivots",
            hoverinfo="skip",
        ))

    fig.update_layout(
        title=dict(
            text=f"{osc_name} — Divergence Windows Shaded",
            x=0.5, xanchor="center", font=dict(size=18, color="#1a1a2e"),
        ),
        xaxis=dict(title="Date", showgrid=True, gridcolor="lightgrey",
                    rangeselector=_range_selector(), rangeslider=dict(visible=True, thickness=0.08)),
        yaxis=dict(title=osc_name, showgrid=True, zeroline=False),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.85)",
                    bordercolor="black", borderwidth=1),
        plot_bgcolor="white", width=1100, height=480, hovermode="x unified",
        annotations=[dict(
            text=("Shaded red spans mark each divergence window: yield made a higher high while "
                  f"{osc_name} made a lower high (red dashed line connects the two pivot points)."),
            xref="paper", yref="paper", x=0.5, y=-0.16, showarrow=False,
            font=dict(size=11, color="grey"), align="center",
        )],
    )
    return fig


def build_fig3(signal_stats: dict, random_stats: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=random_stats["draw_means"], nbinsx=40, name="Random Baseline (draw means)",
        marker_color="rgba(150,150,150,0.6)",
    ))
    fig.add_vline(x=signal_stats["mean"], line_color="red", line_width=2.5,
                  annotation_text=f"Signal mean: {signal_stats['mean']:.2f}",
                  annotation_position="top")
    fig.add_vline(x=random_stats["mean"], line_color="grey", line_dash="dash",
                  annotation_text=f"Random mean: {random_stats['mean']:.2f}",
                  annotation_position="bottom")
    fig.update_layout(
        title=dict(
            text=f"Vol-Adjusted {FWD_WEEKS}-Week Forward Yield Change: Signal vs. Random Baseline",
            x=0.5, xanchor="center", font=dict(size=18, color="#1a1a2e"),
        ),
        xaxis=dict(title="Vol-adjusted forward yield change (13w change ÷ 52w realized vol)"),
        yaxis=dict(title=f"Frequency ({RANDOM_DRAWS} random draws)"),
        plot_bgcolor="white", width=1100, height=520,
        annotations=[dict(
            text=(f"Signal: n={signal_stats['n']}, mean={signal_stats['mean']:.2f}, "
                  f"std={signal_stats['std']:.2f}  |  Random: mean={random_stats['mean']:.2f}, "
                  f"std={random_stats['std']:.2f}. Negative = yields fell over the following "
                  f"{FWD_WEEKS} weeks."),
            xref="paper", yref="paper", x=0.5, y=-0.16, showarrow=False,
            font=dict(size=11, color="grey"), align="center",
        )],
    )
    return fig


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

def methodology_html(osc_name: str, signals: list, signal_stats: dict, random_stats: dict) -> str:
    rows = "".join(
        f"<tr{' style=\"background:#fafafa;\"' if i % 2 else ''}>"
        f"<td style='padding:6px 12px;border:1px solid #ddd;'>{s['date'].strftime('%Y-%m-%d')}</td>"
        f"<td style='padding:6px 12px;border:1px solid #ddd;'>{s['yield_at_signal']:.2f}%</td>"
        f"<td style='padding:6px 12px;border:1px solid #ddd;'>{s['osc_at_signal']:.2f}</td>"
        f"<td style='padding:6px 12px;border:1px solid #ddd;'>{s['prior_high_date'].strftime('%Y-%m-%d')}</td>"
        f"</tr>"
        for i, s in enumerate(signals)
    )
    return f"""
<div style="max-width:900px;margin:0 auto 48px;padding:0 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#333;line-height:1.7;">
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:40px;">Methodology</h2>
  <p>Replicates a JPMorgan Global Markets Strategy chart concept: weekly bearish price/momentum
  divergence on the 30-year Treasury yield as a bond-buy (lower-yield) signal. JPM did not publish
  its exact formula, so two standard oscillators were computed on <b>{SERIES_ID}</b> resampled to
  weekly ({RESAMPLE_RULE}) bars — RSI-14 and MACD histogram (12/26/9) — and the one whose signal
  cadence better matched a "handful of times per decade" framing was used: <b>{osc_name}</b>.</p>
  <p><b>Signal rule</b>: at each pair of consecutive local highs in the weekly yield (window ±{PIVOT_ORDER}
  weeks, merged if closer than {MIN_PIVOT_SPACING_WEEKS} weeks), a signal fires if the yield makes a
  <i>higher high</i> while {osc_name} makes a <i>lower high</i> — bearish divergence, signaling exhausted
  upside momentum in yields and an impending decline.</p>
  <p><b>Forward-return study</b>: for each signal, the yield change over the following {FWD_WEEKS} weeks is
  divided by the trailing {VOL_LOOKBACK_WEEKS}-week realized volatility of weekly yield changes (vol-adjusted).
  This is compared against a random baseline: {RANDOM_DRAWS} draws of {signal_stats['n']} random non-signal
  dates each, same vol-adjusted forward-change statistic, mean of each draw collected into a null distribution.</p>
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:32px;">Signals ({len(signals)})</h2>
  <table style="width:100%;border-collapse:collapse;margin:12px 0 20px;font-size:13px;">
    <thead><tr style="background:#f5f5f5;">
      <th style="text-align:left;padding:6px 12px;border:1px solid #ddd;">Date</th>
      <th style="text-align:left;padding:6px 12px;border:1px solid #ddd;">Yield</th>
      <th style="text-align:left;padding:6px 12px;border:1px solid #ddd;">{osc_name}</th>
      <th style="text-align:left;padding:6px 12px;border:1px solid #ddd;">Prior High</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:32px;">Notes &amp; Caveats</h2>
  <ul style="margin:8px 0 0 20px;">
    <li>This is a reverse-engineered replication, not JPM's actual model — divergence rule, pivot window,
    and forward-return methodology are standard-technical-analysis choices, not disclosed JPM parameters.</li>
    <li>{SERIES_ID} has a gap from Feb 2002 to Feb 2006 (Treasury suspended 30Y issuance); no signals can
    be detected spanning that gap.</li>
    <li>Small sample size (a handful of signals over decades) means the random-baseline comparison should
    be read directionally, not as a statistically robust backtest.</li>
  </ul>
  <p style="margin-top:20px;color:#888;font-size:12px;">Source: FRED {SERIES_ID}, Federal Reserve H.15.</p>
</div>
"""


def _auto_yaxis_script(div_id: str) -> str:
    """Rescale the y-axis to the data visible in the x-range after any zoom
    (rangeslider drag, rangeselector button, or box-zoom) — Plotly does not
    do this on its own; it only ever auto-fits the y-axis to the full series."""
    return f"""
<script>
(function() {{
  function attach() {{
    var gd = document.getElementById('{div_id}');
    if (!gd || !gd.data || !gd.data.length) {{ setTimeout(attach, 60); return; }}
    // Pandas serializes timestamps with nanosecond precision
    // ("...T00:00:00.000000000"); JS Date only understands up to
    // milliseconds and silently returns Invalid Date on the rest,
    // so trim any fractional-seconds digits past the first 3.
    function parseDate(v) {{
      if (typeof v === 'number') return v;
      return new Date(String(v).replace(/(\\.\\d{{3}})\\d+/, '$1')).getTime();
    }}
    var traces = gd.data.filter(function(t) {{ return t.x && t.y; }})
                         .map(function(t) {{
                           return {{x: t.x.map(parseDate), y: t.y}};
                         }});
    function rescale(x0, x1) {{
      var ymin = Infinity, ymax = -Infinity;
      traces.forEach(function(tr) {{
        for (var i = 0; i < tr.x.length; i++) {{
          if (tr.x[i] >= x0 && tr.x[i] <= x1) {{
            if (tr.y[i] < ymin) ymin = tr.y[i];
            if (tr.y[i] > ymax) ymax = tr.y[i];
          }}
        }}
      }});
      if (ymin === Infinity) return;
      var pad = (ymax - ymin) * 0.08 || Math.abs(ymax) * 0.08 || 1;
      Plotly.relayout(gd, {{'yaxis.range': [ymin - pad, ymax + pad], 'yaxis.autorange': false}});
    }}
    gd.on('plotly_relayout', function(ev) {{
      if (ev['xaxis.autorange']) {{
        Plotly.relayout(gd, {{'yaxis.autorange': true}});
        return;
      }}
      var x0, x1;
      if (ev['xaxis.range[0]'] !== undefined && ev['xaxis.range[1]'] !== undefined) {{
        x0 = parseDate(ev['xaxis.range[0]']);
        x1 = parseDate(ev['xaxis.range[1]']);
      }} else if (ev['xaxis.range']) {{
        x0 = parseDate(ev['xaxis.range'][0]);
        x1 = parseDate(ev['xaxis.range'][1]);
      }} else {{
        return;
      }}
      rescale(x0, x1);
    }});
  }}
  attach();
}})();
</script>
"""


def build_html(fig2: go.Figure, fig_osc: go.Figure, fig3: go.Figure, osc_name: str, signals: list,
                signal_stats: dict, random_stats: dict, yield_s: pd.Series) -> str:
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    latest = yield_s.index[-1].strftime("%B %d, %Y")
    latest_yield = yield_s.iloc[-1]

    chart2_div = fig2.to_html(full_html=False, include_plotlyjs="cdn", div_id="yield-chart",
                               config={"displayModeBar": True, "displaylogo": False})
    chart2_div += _auto_yaxis_script("yield-chart")
    chart_osc_div = fig_osc.to_html(full_html=False, include_plotlyjs=False, div_id="rsi-chart",
                                     config={"displayModeBar": True, "displaylogo": False})
    chart_osc_div += _auto_yaxis_script("rsi-chart")
    chart3_div = fig3.to_html(full_html=False, include_plotlyjs=False,
                               config={"displayModeBar": True, "displaylogo": False})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>30Y Treasury Momentum Divergence Signals</title>
  <style>
    body {{ margin: 0; padding: 32px 16px 48px; background: #fff; }}
    h1 {{
      text-align: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 26px; font-weight: 700; color: #1a1a2e;
      margin-bottom: 4px;
    }}
    .subtitle {{
      text-align: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px; color: #666; margin-bottom: 24px;
    }}
    .chart-wrap {{ max-width: 1140px; margin: 0 auto 36px; }}
  </style>
</head>
<body>
  <h1>30-Year Treasury: Momentum Divergence Signals</h1>
  <p class="subtitle">
    Latest ({latest}): <strong>{latest_yield:.2f}%</strong> &nbsp;|&nbsp;
    Method: <strong>{osc_name}</strong> &nbsp;|&nbsp; {len(signals)} historical signals &nbsp;|&nbsp;
    Updated {today}
  </p>
  <div class="chart-wrap">{chart2_div}</div>
  <div class="chart-wrap">{chart_osc_div}</div>
  <div class="chart-wrap">{chart3_div}</div>
  {methodology_html(osc_name, signals, signal_stats, random_stats)}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1/5] Connecting to FRED...")
    fred = Fred(api_key=FRED_API_KEY)

    print("[2/5] Fetching DGS30, resampling to weekly...")
    yield_s = pull_weekly_yield(fred)
    print(f"      {len(yield_s)} weekly obs | {yield_s.index[0].date()} - {yield_s.index[-1].date()}")

    print("[3/5] Computing oscillators and divergence signals...")
    rsi_s = calculate_rsi(yield_s)
    macd_s = calculate_macd_hist(yield_s)
    highs = find_local_highs(yield_s)
    osc_name, signals = select_method(yield_s, rsi_s, macd_s, highs)
    osc_s = rsi_s if osc_name == "RSI-14" else macd_s
    for s in signals:
        print(f"      {s['date'].date()}  yield={s['yield_at_signal']:.2f}%  "
              f"prior high={s['prior_high_date'].date()}")

    print("[4/5] Forward-return study...")
    vol_s = compute_weekly_vol(yield_s)
    vol_adj_fwd = compute_vol_adj_forward_change(yield_s, vol_s)
    signal_dates = [s["date"] for s in signals]
    signal_stats = signal_forward_stats(signal_dates, vol_adj_fwd)
    random_stats = random_baseline_stats(vol_adj_fwd, signal_dates, signal_stats["n"])
    print(f"      Signal: n={signal_stats['n']} mean={signal_stats['mean']:.2f} std={signal_stats['std']:.2f}")
    print(f"      Random: mean={random_stats['mean']:.2f} std={random_stats['std']:.2f}")

    print("[5/5] Building charts and writing report...")
    fig2 = build_fig2(yield_s, signals, osc_name)
    fig_osc = build_fig_osc(yield_s, osc_s, signals, osc_name)
    fig3 = build_fig3(signal_stats, random_stats)
    html = build_html(fig2, fig_osc, fig3, osc_name, signals, signal_stats, random_stats, yield_s)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    summary = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "series": SERIES_ID,
        "method": osc_name,
        "data_range": [yield_s.index[0].strftime("%Y-%m-%d"), yield_s.index[-1].strftime("%Y-%m-%d")],
        "signal_count": len(signals),
        "signals": [{
            "date": s["date"].strftime("%Y-%m-%d"),
            "yield_at_signal": round(s["yield_at_signal"], 2),
            "osc_at_signal": round(s["osc_at_signal"], 2),
            "prior_high_date": s["prior_high_date"].strftime("%Y-%m-%d"),
        } for s in signals],
        "signal_stats": {"n": signal_stats["n"], "mean": signal_stats["mean"], "std": signal_stats["std"]},
        "random_baseline": {"draws": RANDOM_DRAWS, "mean": random_stats["mean"], "std": random_stats["std"]},
    }
    with open(os.path.join(OUTPUT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    out_df = pd.DataFrame({"yield": yield_s, "rsi": rsi_s, "macd_hist": macd_s})
    out_df.to_csv(os.path.join(OUTPUT_DIR, "dgs30_weekly.csv"))

    print(f"\nDone -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
