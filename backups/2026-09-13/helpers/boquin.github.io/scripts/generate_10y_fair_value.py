"""
US 10-Year Treasury Fair Value Model
=====================================
Decomposes the 10Y yield into three components:
  r*    = 10-year rolling average of Real GDP growth (long-run real rate proxy)
  E[π]  = NY Fed 1-Year Ahead Expected Inflation (EXPINF1YR)
  TP    = Kim-Wright 10-Year Term Premium on Zero Coupon Bond (THREEFYTP10)

Fair Value = r* + E[π] + TP
Residual   = Actual Yield (DGS10) - Fair Value

Required env vars (optional — falls back to hardcoded key):
  FRED_API_KEY
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from fredapi import Fred

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_FRED_KEY_DEFAULT = "a68d4b16dd1984d0c8455381a79a8b6e"
FRED_API_KEY = os.environ.get("FRED_API_KEY", _FRED_KEY_DEFAULT)

START_DATE = "1990-01-01"
RSTAR_WINDOW_QUARTERS = 40  # 10-year rolling window for r*

OUTPUT_PATH = "reports/us-10y-fair-value/index.html"

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_series(fred: Fred, series_id: str, start: str) -> pd.Series:
    print(f"  Fetching {series_id}...")
    s = fred.get_series(series_id, observation_start=start)
    s.index = pd.to_datetime(s.index)
    return s.dropna()


def build_dataset(fred: Fred) -> pd.DataFrame:
    """Fetch and align all series to a monthly DataFrame."""

    # Daily series → monthly average
    dgs10_d = fetch_series(fred, "DGS10", START_DATE)
    tp_d = fetch_series(fred, "THREEFYTP10", START_DATE)

    dgs10_m = dgs10_d.resample("ME").mean().rename("DGS10")
    acmtp10_m = tp_d.resample("ME").mean().rename("ACMTP10")

    # Monthly — already at right frequency
    expinf_m = fetch_series(fred, "EXPINF10YR", START_DATE).resample("ME").last().rename("EXPINF10YR")

    # Quarterly GDP → compute r* then forward-fill to monthly
    gdp_q = fetch_series(fred, "A191RO1Q156NBEA", START_DATE)
    gdp_q = gdp_q.resample("QE").last()  # ensure quarterly index
    rstar_q = gdp_q.rolling(window=RSTAR_WINDOW_QUARTERS, min_periods=20).mean().rename("rstar")
    rstar_m = rstar_q.resample("ME").ffill()

    # Merge on monthly index; drop rows with any NaN
    df = pd.concat([dgs10_m, expinf_m, acmtp10_m, rstar_m], axis=1)
    df = df.dropna()

    # Model — calibrated with a constant intercept so the residual is mean-zero
    # over the full sample. Without this, GDP-based r* chronically overstates
    # the true neutral real rate, producing a persistent level bias.
    raw_composite = df["rstar"] + df["EXPINF10YR"] + df["ACMTP10"]
    alpha = (df["DGS10"] - raw_composite).mean()
    df["alpha"] = alpha
    df["FairValue"] = alpha + raw_composite
    df["Residual"] = df["DGS10"] - df["FairValue"]

    return df


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def split_positive_negative(series: pd.Series):
    """Return two series: positive values (neg set to 0) and negative (pos set to 0)."""
    pos = series.clip(lower=0)
    neg = series.clip(upper=0)
    return pos, neg


def build_chart(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.42, 0.25, 0.33],
        vertical_spacing=0.05,
        subplot_titles=(
            "10-Year Yield vs. Model Fair Value",
            "Residual (Actual − Fair Value)",
            "Fair Value Decomposition",
        ),
    )

    dates = df.index

    # ── Row 1: Actual vs Fair Value ──────────────────────────────────────────
    # Each trace gets a unique legendgroup so it can be toggled independently.
    # legendgrouptitle on the first trace of each section renders the section header.
    fig.add_trace(
        go.Scatter(
            x=dates, y=df["DGS10"],
            name="Actual 10Y Yield",
            legendgroup="p1_actual",
            legendgrouptitle=dict(text="<b>Yield vs. Fair Value</b>", font=dict(size=12)),
            line=dict(color="#1f77b4", width=2),
            hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra>Actual</extra>",
        ),
        row=1, col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=dates, y=df["FairValue"],
            name="Model Fair Value",
            legendgroup="p1_fv",
            line=dict(color="#ff7f0e", width=2, dash="dash"),
            hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra>Fair Value</extra>",
        ),
        row=1, col=1,
    )

    # ── Row 2: Residual with green/red fill ─────────────────────────────────
    resid = df["Residual"]
    pos_resid, neg_resid = split_positive_negative(resid)

    fig.add_trace(
        go.Scatter(
            x=dates, y=pos_resid,
            name="Cheap / Undervalued",
            legendgroup="p2_cheap",
            legendgrouptitle=dict(text="<b>Residual Signal</b>", font=dict(size=12)),
            fill="tozeroy",
            fillcolor="rgba(44, 160, 44, 0.30)",
            line=dict(color="rgba(44, 160, 44, 0.0)", width=0),
            hovertemplate="%{x|%b %Y}: +%{y:.2f}pp<extra>Cheap</extra>",
        ),
        row=2, col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=dates, y=neg_resid,
            name="Rich / Overvalued",
            legendgroup="p2_rich",
            fill="tozeroy",
            fillcolor="rgba(214, 39, 40, 0.25)",
            line=dict(color="rgba(214, 39, 40, 0.0)", width=0),
            hovertemplate="%{x|%b %Y}: %{y:.2f}pp<extra>Rich</extra>",
        ),
        row=2, col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=dates, y=resid,
            name="Residual",
            legendgroup="p2_resid",
            line=dict(color="#333333", width=1.5),
            showlegend=False,
            hovertemplate="%{x|%b %Y}: %{y:.2f}pp<extra>Residual</extra>",
        ),
        row=2, col=1,
    )

    fig.add_hline(y=0, line=dict(color="#888", width=1, dash="dot"), row=2, col=1)

    # ── Row 3: Stacked area — component contributions ────────────────────────
    # α is a constant — broadcast to a Series aligned with dates
    alpha_s = pd.Series(df["alpha"].iloc[0], index=dates)

    components = [
        ("p3_alpha", alpha_s,          "α  Intercept",             "rgba(150, 100, 200, 0.55)", "#7b52ab"),
        ("p3_rstar", df["rstar"],      "r*  Rolling GDP trend",     "rgba( 31, 119, 180, 0.55)", "#1f77b4"),
        ("p3_expinf",df["EXPINF10YR"], "E[π]  10Y Inflation exp.",  "rgba(214,  39,  40, 0.55)", "#d62728"),
        ("p3_tp",    df["ACMTP10"],    "TP  Term premium",           "rgba( 44, 160,  44, 0.55)", "#2ca02c"),
    ]

    for i, (lgkey, series, label, fillcolor, linecolor) in enumerate(components):
        fig.add_trace(
            go.Scatter(
                x=dates, y=series,
                name=label,
                legendgroup=lgkey,
                legendgrouptitle=dict(text="<b>Fair Value Components</b>", font=dict(size=12)) if i == 0 else None,
                stackgroup="fv_stack",
                fillcolor=fillcolor,
                line=dict(color=linecolor, width=0.8),
                hovertemplate=f"%{{x|%b %Y}}: %{{y:.2f}}%<extra>{label}</extra>",
            ),
            row=3, col=1,
        )

    # ── Annotation box ───────────────────────────────────────────────────────
    latest = df.index[-1]
    latest_resid = df["Residual"].iloc[-1]
    latest_fv = df["FairValue"].iloc[-1]
    latest_actual = df["DGS10"].iloc[-1]
    bias = "Cheap / Undervalued" if latest_resid > 0 else "Rich / Overvalued"
    bias_color = "#2ca02c" if latest_resid > 0 else "#d62728"

    fig.add_annotation(
        x=0.01, y=0.99, xref="paper", yref="paper",
        text=(
            f"<b>As of {latest.strftime('%b %Y')}</b><br>"
            f"Actual: <b>{latest_actual:.2f}%</b><br>"
            f"Fair Value: <b>{latest_fv:.2f}%</b><br>"
            f"Residual: <b style='color:{bias_color}'>{latest_resid:+.2f}pp</b><br>"
            f"Signal: <b>{bias}</b>"
        ),
        showarrow=False,
        align="left",
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="#ccc",
        borderwidth=1,
        font=dict(size=12),
    )

    fig.update_layout(
        title=dict(
            text="US 10-Year Treasury: Parsimonious Fair Value Model",
            x=0.5, xanchor="center",
            font=dict(size=20, color="#1a1a2e"),
        ),
        height=950,
        template="plotly_white",
        legend=dict(
            orientation="v",
            x=1.01, xanchor="left",
            y=0.5,  yanchor="middle",
            font=dict(size=12),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#ddd",
            borderwidth=1,
            tracegroupgap=12,
        ),
        margin=dict(t=90, l=60, r=180, b=60),
        hovermode="x unified",
    )

    fig.update_yaxes(title_text="Yield (%)", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(title_text="Residual (pp)", ticksuffix="pp", row=2, col=1)
    fig.update_yaxes(title_text="Contribution (%)", ticksuffix="%", row=3, col=1)
    fig.update_xaxes(title_text="", row=3, col=1)

    return fig


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

METHODOLOGY_HTML = """
<div style="max-width:900px;margin:0 auto 48px;padding:0 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#333;line-height:1.7;">
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:40px;">Model Methodology</h2>
  <p>This model decomposes the 10-year US Treasury yield into three theoretically motivated components:</p>
  <table style="width:100%;border-collapse:collapse;margin:12px 0 20px;">
    <thead>
      <tr style="background:#f5f5f5;">
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Component</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Proxy</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">FRED Series</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>r*</b> — Long-run real rate</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">10-year (40-quarter) rolling average of Real GDP growth (YoY%)</td>
        <td style="padding:8px 12px;border:1px solid #ddd;font-family:monospace;">A191RO1Q156NBEA</td>
      </tr>
      <tr style="background:#fafafa;">
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>E[π]</b> — Inflation expectations</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">NY Fed 10-Year Expected Inflation</td>
        <td style="padding:8px 12px;border:1px solid #ddd;font-family:monospace;">EXPINF10YR</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>TP</b> — Term premium</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Kim-Wright Term Premium on 10-Year Zero Coupon Bond</td>
        <td style="padding:8px 12px;border:1px solid #ddd;font-family:monospace;">THREEFYTP10</td>
      </tr>
    </tbody>
  </table>
  <p><b>Fair Value</b> = α + r* + E[π] + TP</p>
  <p style="margin-top:4px;font-size:13px;color:#555;">where <b>α</b> is a calibration constant equal to the historical mean of (Actual − raw composite), ensuring the residual is mean-zero over the full sample. Without this intercept, GDP-based r* chronically overstates the true neutral real rate — particularly post-GFC — producing a persistent level bias in the raw model.</p>
  <p><b>Residual</b> = Actual Yield (DGS10) − Fair Value</p>
  <ul style="margin:8px 0 16px 20px;">
    <li><span style="color:#2ca02c;font-weight:600;">Residual &gt; 0</span>: Yield trades above fair value → market is <b>cheap / undervalued</b> relative to fundamentals</li>
    <li><span style="color:#d62728;font-weight:600;">Residual &lt; 0</span>: Yield trades below fair value → market is <b>rich / overvalued</b> relative to fundamentals</li>
  </ul>
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:32px;">Notes &amp; Caveats</h2>
  <ul style="margin:8px 0 0 20px;">
    <li>r* uses a 10-year backward-looking window, making it a lagging proxy; structural breaks in potential growth may not be captured promptly.</li>
    <li>The model carries no free parameters — all three components are pulled directly from FRED without calibration.</li>
    <li>Data availability limits the sample: the earliest fully-populated observation depends on the ACM term premium series (available from 1961 on a limited basis; EXPINF1YR from ~1978).</li>
    <li>Daily series (DGS10, ACMTP10) are averaged to monthly; quarterly GDP is forward-filled.</li>
  </ul>
  <p style="margin-top:20px;color:#888;font-size:12px;">Sources: Federal Reserve Board (Kim-Wright term premium, THREEFYTP10), Federal Reserve Bank of New York (inflation expectations, EXPINF1YR), Bureau of Economic Analysis (Real GDP, A191RO1Q156NBEA), Federal Reserve H.15 (DGS10). All data via FRED.</p>
</div>
"""


def build_html(fig: go.Figure, df: pd.DataFrame) -> str:
    today = date.today().strftime("%B %d, %Y")
    latest = df.index[-1].strftime("%B %Y")
    latest_resid = df["Residual"].iloc[-1]
    bias = "Cheap / Undervalued" if latest_resid > 0 else "Rich / Overvalued"

    chart_div = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": True, "displaylogo": False},
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>US 10Y Treasury Fair Value Model</title>
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
    .chart-wrap {{ max-width: 960px; margin: 0 auto 36px; }}
  </style>
</head>
<body>
  <h1>US 10-Year Treasury: Fair Value Model</h1>
  <p class="subtitle">
    Signal as of {latest}: <strong>{bias}</strong> ({latest_resid:+.2f}pp vs. fair value) &nbsp;|&nbsp; Updated {today}
  </p>
  <div class="chart-wrap">
    {chart_div}
  </div>
  {METHODOLOGY_HTML}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1/4] Connecting to FRED...")
    fred = Fred(api_key=FRED_API_KEY)

    print("[2/4] Fetching and aligning data...")
    df = build_dataset(fred)
    print(f"      Dataset: {len(df)} monthly observations ({df.index[0].strftime('%b %Y')} – {df.index[-1].strftime('%b %Y')})")

    latest = df.iloc[-1]
    print(f"\n      Calibration intercept (α) = {df['alpha'].iloc[-1]:+.2f}pp")
    print(f"      Latest snapshot ({df.index[-1].strftime('%b %Y')}):")
    print(f"        r*         = {latest['rstar']:.2f}%")
    print(f"        E[π]       = {latest['EXPINF10YR']:.2f}%")
    print(f"        TP         = {latest['ACMTP10']:.2f}%")
    print(f"        α          = {latest['alpha']:+.2f}pp")
    print(f"        Fair Value = {latest['FairValue']:.2f}%")
    print(f"        Actual     = {latest['DGS10']:.2f}%")
    print(f"        Residual   = {latest['Residual']:+.2f}pp  ({'CHEAP' if latest['Residual'] > 0 else 'RICH'})")

    print("\n[3/4] Building chart...")
    fig = build_chart(df)

    print("[4/4] Writing HTML report...")
    html = build_html(fig, df)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n      Done → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
