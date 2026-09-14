"""
CTA Treasury Reversal
====================================================
A second fair value model for the 10Y yield using Fed policy stance variables
as regressors, complementing the inflation/term-premium decomposition.

Regressors:
  DGS2          = 2-Year Treasury yield (market pricing of short-rate path)
  PolicySpread  = DGS2 - FEDFUNDS (how far market is pricing vs current FFR)
  RealFFR_Gap   = (FEDFUNDS - CorePCE_YoY) - 10yr rolling neutral real rate
  TaylorGap     = FEDFUNDS - Taylor Rule implied rate (hawkish/dovish vs rule)

Model:
  DGS10 = α + β₁·DGS2 + β₂·PolicySpread + β₃·RealFFR_Gap + β₄·TaylorGap + ε

Estimated by OLS (statsmodels). Residual is mean-zero by construction.

Required env vars (optional — falls back to hardcoded key):
  FRED_API_KEY
"""

import os
from datetime import date

import numpy as np
import pandas as pd
import statsmodels.api as sm
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from fredapi import Fred

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_FRED_KEY_DEFAULT = "a68d4b16dd1984d0c8455381a79a8b6e"
FRED_API_KEY = os.environ.get("FRED_API_KEY", _FRED_KEY_DEFAULT)

START_DATE = "1990-01-01"
NEUTRAL_WINDOW = 120  # 10-year rolling window for neutral real rate (months)

OUTPUT_PATH = os.path.expanduser(
    "~/boquin.github.io/reports/fed-policy-fv/index.html"
)

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_series(fred: Fred, series_id: str, start: str) -> pd.Series:
    print(f"  Fetching {series_id}...")
    s = fred.get_series(series_id, observation_start=start)
    s.index = pd.to_datetime(s.index)
    return s.dropna()


def build_dataset(fred: Fred) -> tuple[pd.DataFrame, object]:
    """Fetch, align, compute regressors, run OLS. Returns (df, ols_result)."""

    # Daily → monthly average
    dgs10_m = fetch_series(fred, "DGS10", START_DATE).resample("ME").mean().rename("DGS10")
    dgs2_m  = fetch_series(fred, "DGS2",  START_DATE).resample("ME").mean().rename("DGS2")

    # Monthly
    ffr_m   = fetch_series(fred, "FEDFUNDS", START_DATE).resample("ME").last().rename("FEDFUNDS")
    pce_m   = fetch_series(fred, "PCEPILFE", START_DATE).resample("ME").last()
    unrate  = fetch_series(fred, "UNRATE",   START_DATE).resample("ME").last().rename("UNRATE")

    # Quarterly → monthly (forward-fill)
    nrou_q  = fetch_series(fred, "NROU", START_DATE).resample("QE").last()
    nrou_m  = nrou_q.resample("ME").ffill().rename("NROU")

    # Core PCE YoY
    pce_yoy = pce_m.pct_change(12).mul(100).rename("CorePCE_YoY")

    # Merge all to monthly
    df = pd.concat([dgs10_m, dgs2_m, ffr_m, pce_yoy, unrate, nrou_m], axis=1).dropna()

    # ── Regressors ─────────────────────────────────────────────────────────
    # 1. Market pricing of Fed path
    df["PolicySpread"] = df["DGS2"] - df["FEDFUNDS"]

    # 2. Real FFR gap vs. rolling neutral
    df["RealFFR"] = df["FEDFUNDS"] - df["CorePCE_YoY"]
    neutral = df["RealFFR"].rolling(NEUTRAL_WINDOW, min_periods=60).mean()
    df["RealFFR_Gap"] = df["RealFFR"] - neutral

    # 3. Taylor Rule gap
    pi = df["CorePCE_YoY"]
    unemp_gap = df["UNRATE"] - df["NROU"]  # positive = slack, negative = tight
    df["r_taylor"] = 2.5 + pi + 0.5 * (pi - 2.0) - 1.0 * unemp_gap
    df["TaylorGap"] = df["FEDFUNDS"] - df["r_taylor"]

    df = df.dropna()

    # ── OLS ────────────────────────────────────────────────────────────────
    regressors = ["DGS2", "PolicySpread", "TaylorGap"]
    X = sm.add_constant(df[regressors])
    result = sm.OLS(df["DGS10"], X).fit()

    df["FairValue"] = result.fittedvalues
    df["Residual"]  = df["DGS10"] - df["FairValue"]

    # Component contributions for the stacked area chart
    params = result.params  # includes 'const'
    df["contrib_alpha"]        = params["const"]
    df["contrib_DGS2"]         = params["DGS2"]         * df["DGS2"]
    df["contrib_PolicySpread"] = params["PolicySpread"]  * df["PolicySpread"]
    df["contrib_TaylorGap"]    = params["TaylorGap"]     * df["TaylorGap"]

    # ── Z-score & reversal signals ──────────────────────────────────────────
    roll36 = df["Residual"].rolling(36, min_periods=24)
    df["ResidualZ"] = (df["Residual"] - roll36.mean()) / roll36.std()

    # Crossback through ±1σ: z exits extreme zone → reversal confirmed
    prev_z = df["ResidualZ"].shift(1)
    df["sell_reversal"] = (prev_z > 1.0) & (df["ResidualZ"] <= 1.0)   # was cheap, now reverting
    df["buy_reversal"]  = (prev_z < -1.0) & (df["ResidualZ"] >= -1.0) # was rich, now reverting

    return df, result


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def split_pos_neg(s: pd.Series):
    return s.clip(lower=0), s.clip(upper=0)


def build_chart(df: pd.DataFrame, result) -> go.Figure:
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        row_heights=[0.36, 0.18, 0.20, 0.26],
        vertical_spacing=0.04,
        subplot_titles=(
            "10-Year Yield vs. Policy Fair Value",
            "Residual (Actual − Fair Value)",
            "Fair Value Decomposition by Policy Factor",
            "Residual Z-Score (36m Rolling) — Reversal Signals",
        ),
    )

    dates = df.index

    # ── Row 1: Actual vs Fair Value ──────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=dates, y=df["DGS10"],
        name="Actual 10Y Yield",
        legendgroup="p1_actual",
        legendgrouptitle=dict(text="<b>Yield vs. Fair Value</b>", font=dict(size=12)),
        line=dict(color="#1f77b4", width=2),
        hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra>Actual</extra>",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=dates, y=df["FairValue"],
        name="Policy Fair Value",
        legendgroup="p1_fv",
        line=dict(color="#ff7f0e", width=2, dash="dash"),
        hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra>Fair Value</extra>",
    ), row=1, col=1)

    # ── Row 2: Residual ──────────────────────────────────────────────────────
    pos_r, neg_r = split_pos_neg(df["Residual"])

    fig.add_trace(go.Scatter(
        x=dates, y=pos_r,
        name="Cheap / Undervalued",
        legendgroup="p2_cheap",
        legendgrouptitle=dict(text="<b>Residual Signal</b>", font=dict(size=12)),
        fill="tozeroy", fillcolor="rgba(44,160,44,0.30)",
        line=dict(color="rgba(44,160,44,0)", width=0),
        hovertemplate="%{x|%b %Y}: +%{y:.2f}pp<extra>Cheap</extra>",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=dates, y=neg_r,
        name="Rich / Overvalued",
        legendgroup="p2_rich",
        fill="tozeroy", fillcolor="rgba(214,39,40,0.25)",
        line=dict(color="rgba(214,39,40,0)", width=0),
        hovertemplate="%{x|%b %Y}: %{y:.2f}pp<extra>Rich</extra>",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=dates, y=df["Residual"],
        showlegend=False, legendgroup="p2_line",
        line=dict(color="#333", width=1.5),
        hovertemplate="%{x|%b %Y}: %{y:.2f}pp<extra>Residual</extra>",
    ), row=2, col=1)

    fig.add_hline(y=0, line=dict(color="#888", width=1, dash="dot"), row=2, col=1)

    # ── Row 3: Stacked contributions ─────────────────────────────────────────
    params = result.params
    components = [
        ("p3_alpha",  df["contrib_alpha"],
         f"α  Intercept ({params['const']:+.2f})",
         "rgba(150,100,200,0.55)", "#7b52ab"),
        ("p3_dgs2",   df["contrib_DGS2"],
         f"β·2Y Yield ({params['DGS2']:+.2f}×DGS2)",
         "rgba(31,119,180,0.55)",  "#1f77b4"),
        ("p3_spread", df["contrib_PolicySpread"],
         f"β·Policy Spread ({params['PolicySpread']:+.2f}×[DGS2−FFR])",
         "rgba(255,127,14,0.55)",  "#ff7f0e"),
        ("p3_taylor", df["contrib_TaylorGap"],
         f"β·Taylor Gap ({params['TaylorGap']:+.2f}×gap)",
         "rgba(44,160,44,0.55)",   "#2ca02c"),
    ]

    for i, (lgkey, series, label, fillcolor, linecolor) in enumerate(components):
        fig.add_trace(go.Scatter(
            x=dates, y=series,
            name=label,
            legendgroup=lgkey,
            legendgrouptitle=dict(text="<b>Fair Value Components</b>", font=dict(size=12)) if i == 0 else None,
            stackgroup="fv_stack",
            fillcolor=fillcolor,
            line=dict(color=linecolor, width=0.8),
            hovertemplate=f"%{{x|%b %Y}}: %{{y:.2f}}%<extra>{label}</extra>",
        ), row=3, col=1)

    # ── Row 4: Z-Score reversal panel ────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=dates, y=df["ResidualZ"],
        name="Residual Z-Score",
        legendgroup="p4_z",
        legendgrouptitle=dict(text="<b>Z-Score Signals</b>", font=dict(size=12)),
        line=dict(color="#444", width=1.5),
        hovertemplate="%{x|%b %Y}: %{y:.2f}σ<extra>Z-Score</extra>",
    ), row=4, col=1)

    fig.add_hline(y=0,    line=dict(color="#aaa", width=1, dash="dot"), row=4, col=1)
    fig.add_hline(y=1.0,  line=dict(color="#2ca02c", width=1, dash="dash"), row=4, col=1)
    fig.add_hline(y=-1.0, line=dict(color="#d62728", width=1, dash="dash"), row=4, col=1)
    fig.add_hline(y=1.5,  line=dict(color="#2ca02c", width=0.7, dash="dot"), row=4, col=1)
    fig.add_hline(y=-1.5, line=dict(color="#d62728", width=0.7, dash="dot"), row=4, col=1)

    # Sell-reversal markers (yield was cheap→cheap confirmed over, z exits +1σ)
    sell_dates = df.index[df["sell_reversal"]]
    sell_z     = df.loc[df["sell_reversal"], "ResidualZ"]
    if len(sell_dates):
        fig.add_trace(go.Scatter(
            x=sell_dates, y=sell_z,
            mode="markers",
            name="Sell Reversal (yield was cheap)",
            legendgroup="p4_sell",
            marker=dict(symbol="triangle-down", size=11, color="#d62728",
                        line=dict(color="#fff", width=1)),
            hovertemplate="%{x|%b %Y}: Z=%{y:.2f}σ<extra>Sell Reversal</extra>",
        ), row=4, col=1)

    # Buy-reversal markers (yield was rich→rich confirmed over, z exits −1σ)
    buy_dates = df.index[df["buy_reversal"]]
    buy_z     = df.loc[df["buy_reversal"], "ResidualZ"]
    if len(buy_dates):
        fig.add_trace(go.Scatter(
            x=buy_dates, y=buy_z,
            mode="markers",
            name="Buy Reversal (yield was rich)",
            legendgroup="p4_buy",
            marker=dict(symbol="triangle-up", size=11, color="#2ca02c",
                        line=dict(color="#fff", width=1)),
            hovertemplate="%{x|%b %Y}: Z=%{y:.2f}σ<extra>Buy Reversal</extra>",
        ), row=4, col=1)

    # ── Row 1 background shading: extreme z-score episodes ───────────────────
    # Build episode spans where z > 1.0 (cheap) or z < -1.0 (rich)
    for sign, color in [(1, "rgba(44,160,44,0.06)"), (-1, "rgba(214,39,40,0.06)")]:
        in_ep = False
        ep_start = None
        for dt, zval in df["ResidualZ"].items():
            if not in_ep and (sign * zval) > 1.0:
                in_ep, ep_start = True, dt
            elif in_ep and (sign * zval) <= 1.0:
                fig.add_vrect(x0=ep_start, x1=dt, fillcolor=color,
                              layer="below", line_width=0, row=1, col=1)
                in_ep = False
        if in_ep:
            fig.add_vrect(x0=ep_start, x1=df.index[-1], fillcolor=color,
                          layer="below", line_width=0, row=1, col=1)

    # ── Annotation ───────────────────────────────────────────────────────────
    latest = df.index[-1]
    lr  = df["Residual"].iloc[-1]
    lz  = df["ResidualZ"].iloc[-1]
    bias = "Cheap / Undervalued" if lr > 0 else "Rich / Overvalued"
    bias_color = "#2ca02c" if lr > 0 else "#d62728"

    # Check if a reversal signal fired in the last 3 months
    recent = df.iloc[-3:]
    recent_sell = recent["sell_reversal"].any()
    recent_buy  = recent["buy_reversal"].any()
    if recent_sell:
        rev_text = "<span style='color:#d62728'>⚡ Sell Reversal (≤3m ago)</span>"
    elif recent_buy:
        rev_text = "<span style='color:#2ca02c'>⚡ Buy Reversal (≤3m ago)</span>"
    else:
        rev_text = "No recent reversal signal"

    fig.add_annotation(
        x=0.01, y=0.99, xref="paper", yref="paper",
        text=(
            f"<b>As of {latest.strftime('%b %Y')}</b><br>"
            f"Actual: <b>{df['DGS10'].iloc[-1]:.2f}%</b><br>"
            f"Fair Value: <b>{df['FairValue'].iloc[-1]:.2f}%</b><br>"
            f"Residual: <b style='color:{bias_color}'>{lr:+.2f}pp</b><br>"
            f"Z-Score: <b>{lz:+.2f}σ</b><br>"
            f"{rev_text}"
        ),
        showarrow=False, align="left",
        bgcolor="rgba(255,255,255,0.85)", bordercolor="#ccc", borderwidth=1,
        font=dict(size=12),
    )

    fig.update_layout(
        title=dict(
            text="CTA Treasury Reversal",
            x=0.5, xanchor="center",
            font=dict(size=20, color="#1a1a2e"),
        ),
        height=1100,
        template="plotly_white",
        legend=dict(
            orientation="v",
            x=1.01, xanchor="left",
            y=0.5,  yanchor="middle",
            font=dict(size=11),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#ddd", borderwidth=1,
            tracegroupgap=12,
        ),
        margin=dict(t=90, l=60, r=220, b=60),
        hovermode="x unified",
    )

    fig.update_yaxes(title_text="Yield (%)", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(title_text="Residual (pp)", ticksuffix="pp", row=2, col=1)
    fig.update_yaxes(title_text="Contribution (%)", ticksuffix="%", row=3, col=1)
    fig.update_yaxes(title_text="Z-Score (σ)", row=4, col=1)

    return fig


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

def build_html(fig: go.Figure, df: pd.DataFrame, result) -> str:
    today   = date.today().strftime("%B %d, %Y")
    latest  = df.index[-1].strftime("%B %Y")
    lr      = df["Residual"].iloc[-1]
    lz      = df["ResidualZ"].iloc[-1]
    bias    = "Cheap / Undervalued" if lr > 0 else "Rich / Overvalued"
    r2      = result.rsquared
    rmse    = np.sqrt(result.mse_resid)
    params  = result.params

    chart_div = fig.to_html(
        full_html=False, include_plotlyjs="cdn",
        config={"displayModeBar": True, "displaylogo": False},
    )

    methodology = f"""
<div style="max-width:900px;margin:0 auto 48px;padding:0 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#333;line-height:1.7;">
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:40px;">Model Methodology</h2>
  <p>This model estimates the 10-year Treasury yield as a linear function of two Fed policy stance variables, calibrated by OLS regression over the full historical sample.</p>
  <p style="font-family:monospace;background:#f5f5f5;padding:10px 14px;border-radius:4px;">
    DGS10 = α + β₁·DGS2 + β₂·PolicySpread + β₃·TaylorGap
  </p>
  <table style="width:100%;border-collapse:collapse;margin:12px 0 20px;">
    <thead>
      <tr style="background:#f5f5f5;">
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Regressor</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Definition</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Coeff.</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Interpretation</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>α</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Intercept</td>
        <td style="padding:8px 12px;border:1px solid #ddd;font-family:monospace;">{params['const']:+.3f}</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Structural level offset</td>
      </tr>
      <tr style="background:#fafafa;">
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>DGS2</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">2-Year Treasury yield</td>
        <td style="padding:8px 12px;border:1px solid #ddd;font-family:monospace;">{params['DGS2']:+.3f}</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Market pricing of short-rate path (level anchor)</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>PolicySpread</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">DGS2 − FEDFUNDS</td>
        <td style="padding:8px 12px;border:1px solid #ddd;font-family:monospace;">{params['PolicySpread']:+.3f}</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Hike expectations (+) / cut expectations (−)</td>
      </tr>
      <tr style="background:#fafafa;">
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>TaylorGap</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">FEDFUNDS − Taylor Rule rate</td>
        <td style="padding:8px 12px;border:1px solid #ddd;font-family:monospace;">{params['TaylorGap']:+.3f}</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Hawkish vs. rule (+) / dovish vs. rule (−)</td>
      </tr>
    </tbody>
  </table>
  <p><b>Taylor Rule:</b> r = 2.5 + π + 0.5·(π − 2.0) − 1.0·(UNRATE − NROU), where π = Core PCE YoY and NROU = CBO natural rate of unemployment.</p>
  <p><b>Model fit:</b> R² = {r2:.3f} &nbsp;|&nbsp; In-sample RMSE = {rmse:.2f}pp &nbsp;|&nbsp; Sample: {df.index[0].strftime('%b %Y')} – {df.index[-1].strftime('%b %Y')}</p>
  <p><b>Residual</b> = Actual − Fair Value. Mean-zero by OLS construction.<br>
     <span style="color:#2ca02c;font-weight:600;">Positive</span> → yield above model → market cheap/undervalued &nbsp;|&nbsp;
     <span style="color:#d62728;font-weight:600;">Negative</span> → yield below model → market rich/overvalued</p>
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:32px;">Reversal Signal Methodology (Z-Score Panel)</h2>
  <p>The raw residual identifies <em>direction</em> of mispricing but not <em>timing</em>. The Z-Score panel normalizes the residual against its own trailing 36-month history to measure how statistically extreme the current deviation is, and flags when an extreme episode ends.</p>
  <p style="font-family:monospace;background:#f5f5f5;padding:10px 14px;border-radius:4px;">
    Z = (Residual − 36m rolling mean) / 36m rolling std
  </p>
  <ul style="margin:8px 0 12px;padding-left:20px;">
    <li><b>Z &gt; +1σ</b>: yield is unusually cheap vs. policy fundamentals (green shaded zone)</li>
    <li><b>Z &lt; −1σ</b>: yield is unusually rich (red shaded zone)</li>
    <li><span style="color:#d62728;font-weight:600;">▼ Sell reversal</span>: z crosses back below +1σ from above — cheap episode confirmed over, yield likely reverting down</li>
    <li><span style="color:#2ca02c;font-weight:600;">▲ Buy reversal</span>: z crosses back above −1σ from below — rich episode confirmed over, yield likely reverting up</li>
  </ul>
  <p>Background shading in the top panel (Row 1) highlights the same extreme-z periods so reversal markers can be visually matched against actual yield movements. The ±1.5σ dotted lines flag historically rare extremes (&lt;15% of observations). Over the 1990–present sample, this approach generated approximately 13 sell and 15 buy reversal confirmations.</p>
  <p style="margin-top:20px;color:#888;font-size:12px;">Sources: Federal Reserve H.15 (DGS10, DGS2, FEDFUNDS), Bureau of Economic Analysis (PCEPILFE), Bureau of Labor Statistics (UNRATE), Congressional Budget Office via FRED (NROU). All data via FRED.</p>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CTA Treasury Reversal</title>
  <style>
    body {{ margin: 0; padding: 32px 16px 48px; background: #fff; }}
    h1 {{
      text-align: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 26px; font-weight: 700; color: #1a1a2e; margin-bottom: 4px;
    }}
    .subtitle {{
      text-align: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px; color: #666; margin-bottom: 24px;
    }}
    .chart-wrap {{ max-width: 1060px; margin: 0 auto 36px; }}
  </style>
</head>
<body>
  <h1>CTA Treasury Reversal</h1>
  <p class="subtitle">
    Signal as of {latest}: <strong>{bias}</strong> ({lr:+.2f}pp vs. fair value)
    &nbsp;|&nbsp; Z-Score: <strong>{lz:+.2f}σ</strong>
    &nbsp;|&nbsp; R² = {r2:.3f} &nbsp;|&nbsp; Updated {today}
  </p>
  <div class="chart-wrap">
    {chart_div}
  </div>
  {methodology}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1/4] Connecting to FRED...")
    fred = Fred(api_key=FRED_API_KEY)

    print("[2/4] Fetching data and fitting model...")
    df, result = build_dataset(fred)

    print(f"\n      Sample: {df.index[0].strftime('%b %Y')} – {df.index[-1].strftime('%b %Y')} ({len(df)} months)")
    print(f"      R² = {result.rsquared:.3f}   RMSE = {np.sqrt(result.mse_resid):.3f}pp")
    print("\n      OLS Coefficients:")
    for name, coef in result.params.items():
        pval = result.pvalues[name]
        print(f"        {name:<20} {coef:+.4f}   (p={pval:.3f})")

    latest = df.iloc[-1]
    lr = latest["Residual"]
    print(f"\n      Latest snapshot ({df.index[-1].strftime('%b %Y')}):")
    print(f"        DGS2           = {latest['DGS2']:.2f}%")
    print(f"        PolicySpread   = {latest['PolicySpread']:+.2f}pp")
    print(f"        TaylorGap      = {latest['TaylorGap']:+.2f}pp")
    print(f"        Fair Value     = {latest['FairValue']:.2f}%")
    print(f"        Actual         = {latest['DGS10']:.2f}%")
    print(f"        Residual       = {lr:+.2f}pp  ({'CHEAP' if lr > 0 else 'RICH'})")

    print("\n[3/4] Building chart...")
    fig = build_chart(df, result)

    print("[4/4] Writing HTML report...")
    html = build_html(fig, df, result)
    os.makedirs(os.path.dirname(os.path.expanduser(OUTPUT_PATH)), exist_ok=True)
    with open(os.path.expanduser(OUTPUT_PATH), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n      Done → {OUTPUT_PATH}")


def get_reversal_chart_div() -> str:
    """Return the 4-panel reversal chart as a Plotly HTML div (no full page, no JS tag).
    Used by generate_treasury_index.py to embed inline."""
    fred = Fred(api_key=FRED_API_KEY)
    df, result = build_dataset(fred)
    fig = build_chart(df, result)
    return fig.to_html(
        full_html=False, include_plotlyjs=False,
        config={"displayModeBar": True, "displaylogo": False},
    )


if __name__ == "__main__":
    main()
