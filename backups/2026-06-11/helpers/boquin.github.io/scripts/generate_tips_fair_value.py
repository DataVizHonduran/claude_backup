"""
10-Year TIPS Fair Value Model (DFII10)
=======================================
Estimates the fair value of the 10-year TIPS (real) yield via OLS regression:

  DFII10_t = α + β₁·R*_t + β₂·TP_t + ε_t

Where:
  R*   = Laubach-Williams neutral real rate (NY Fed, quarterly → monthly)
  TP   = ACM 10-Year Term Premium (THREEFYTP10, from FRED)
  ε_t  = residual (actual minus fair value)

Statistical coherence checks are embedded in the HTML output:
  - OLS coefficients, t-stats, p-values
  - R² / Adj. R², F-statistic
  - ADF test on residuals (stationarity / cointegration check)
  - Durbin-Watson statistic

Required env vars (optional — falls back to hardcoded key):
  FRED_API_KEY
"""

import io
import os
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import statsmodels.api as sm
from fredapi import Fred
from plotly.subplots import make_subplots
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import adfuller

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_FRED_KEY_DEFAULT = "a68d4b16dd1984d0c8455381a79a8b6e"
FRED_API_KEY = os.environ.get("FRED_API_KEY", _FRED_KEY_DEFAULT)

START_DATE = "2006-01-01"  # DFII10 available from Apr 2006

NYFED_LW_URL = (
    "https://www.newyorkfed.org/medialibrary/media/research/economists/"
    "williams/data/Laubach_Williams_current_estimates.xlsx"
)
NYFED_LW_SHEET = "data"

OUTPUT_PATH = os.path.expanduser(
    "~/boquin.github.io/reports/tips-fair-value/index.html"
)

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_fred_series(fred: Fred, series_id: str) -> pd.Series:
    print(f"  Fetching {series_id} from FRED...")
    s = fred.get_series(series_id, observation_start=START_DATE)
    s.index = pd.to_datetime(s.index)
    return s.dropna()


def _parse_lw_quarter(date_str: str) -> pd.Timestamp:
    """Convert 'YYYY QN' → last day of that quarter."""
    parts = str(date_str).strip().split()
    year = int(parts[0])
    qtr = int(parts[1].replace("Q", ""))
    # Last month of the quarter
    end_month = qtr * 3
    return pd.Timestamp(year=year, month=end_month, day=1) + pd.offsets.MonthEnd(0)


def fetch_nyfed_rstar() -> pd.Series:
    """
    Download the Laubach-Williams current estimates Excel from NY Fed.
    Returns a monthly Series of two-sided r* estimates, forward-filled.

    Excel structure (sheet: 'data'):
      Rows 0-3: header text
      Row 4:    group labels ("One-Sided Estimates", "Two-Sided Estimates")
      Row 5:    column names ("Date", NaN, "rstar", "g", "z", "Output gap",
                               NaN, "rstar", "g", "z", "Output gap")
      Row 6+:   data (Date is a datetime object; columns 0-indexed)
      Column 0: Date, col 2: one-sided rstar, col 7: two-sided rstar
    """
    print(f"  Fetching NY Fed LW r* from {NYFED_LW_URL}...")
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    resp = requests.get(NYFED_LW_URL, headers={"User-Agent": ua}, timeout=60)
    resp.raise_for_status()

    content = io.BytesIO(resp.content)

    # Read raw without any header to inspect layout
    raw = pd.read_excel(content, sheet_name=NYFED_LW_SHEET, header=None)

    # Find the row index where "Date" appears in column 0 (that's the column header row)
    # Based on observed structure, row 5 (0-indexed) contains the column headers.
    header_row_idx = None
    for i, val in enumerate(raw.iloc[:, 0]):
        if str(val).strip().lower() == "date":
            header_row_idx = i
            break

    if header_row_idx is None:
        raise ValueError(
            f"Could not find 'Date' header row in LW Excel sheet '{NYFED_LW_SHEET}'. "
            f"First 8 rows col-0 values: {raw.iloc[:8, 0].tolist()}"
        )

    # Data starts one row after the header row
    data = pd.read_excel(
        io.BytesIO(resp.content),
        sheet_name=NYFED_LW_SHEET,
        header=None,
        skiprows=header_row_idx + 1,  # skip everything up to and including header
    )

    # Column layout (0-indexed): 0=Date, 1=NaN, 2=rstar(1s), 3=g(1s), 4=z(1s), 5=OutGap(1s),
    #                             6=NaN, 7=rstar(2s), 8=g(2s), 9=z(2s), 10=OutGap(2s)
    TWO_SIDED_RSTAR_COL = 7
    DATE_COL = 0

    # Drop rows where Date is NaN
    data = data.dropna(subset=[DATE_COL])
    # Keep only rows where Date looks like a datetime (filter out any leftover text)
    data = data[pd.to_datetime(data[DATE_COL], errors="coerce").notna()]

    dates = pd.to_datetime(data[DATE_COL])
    rstar_vals = pd.to_numeric(data[TWO_SIDED_RSTAR_COL], errors="coerce")

    rstar_q = pd.Series(rstar_vals.values, index=dates).dropna()
    rstar_q.index = rstar_q.index + pd.offsets.QuarterEnd(0)  # snap to quarter-end

    print(f"  LW r* loaded: {len(rstar_q)} quarterly obs "
          f"({rstar_q.index[0].strftime('%Y Q%q') if hasattr(rstar_q.index[0], 'quarter') else rstar_q.index[0].strftime('%b %Y')} "
          f"– {rstar_q.index[-1].strftime('%b %Y')})")
    print(f"  Latest r* (two-sided) = {rstar_q.iloc[-1]:.3f}%")

    # Forward-fill quarterly to monthly
    rstar_m = rstar_q.resample("ME").last().ffill()
    return rstar_m.rename("rstar")


def build_dataset(fred: Fred):
    """
    Fetch and align all series; run OLS regression.
    Returns (df, ols_result, adf_result, dw_stat).
    """
    # TIPS yield: daily → monthly mean
    dfii10_d = fetch_fred_series(fred, "DFII10")
    dfii10_m = dfii10_d.resample("ME").mean().rename("DFII10")

    # ACM term premium: daily → monthly mean
    tp_d = fetch_fred_series(fred, "THREEFYTP10")
    tp_m = tp_d.resample("ME").mean().rename("TP")

    # NY Fed r* (already monthly after forward-fill)
    rstar_m = fetch_nyfed_rstar()

    # Merge on monthly index, drop any NaN
    df = pd.concat([dfii10_m, tp_m, rstar_m], axis=1).dropna()

    print(f"  Aligned dataset: {len(df)} monthly observations "
          f"({df.index[0].strftime('%b %Y')} – {df.index[-1].strftime('%b %Y')})")

    # ── OLS regression ─────────────────────────────────────────────────────
    X = sm.add_constant(df[["rstar", "TP"]])
    y = df["DFII10"]
    ols_result = sm.OLS(y, X).fit()

    df["FairValue"] = ols_result.fittedvalues
    df["Residual"] = ols_result.resid

    # Component contributions: α, β₁·R*, β₂·TP
    alpha_hat = ols_result.params["const"]
    beta_rstar = ols_result.params["rstar"]
    beta_tp = ols_result.params["TP"]

    df["contrib_alpha"] = alpha_hat
    df["contrib_rstar"] = beta_rstar * df["rstar"]
    df["contrib_tp"] = beta_tp * df["TP"]

    # ── Diagnostic stats ───────────────────────────────────────────────────
    adf_result = adfuller(df["Residual"], autolag="AIC")
    dw_stat = durbin_watson(ols_result.resid)

    return df, ols_result, adf_result, dw_stat


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def split_positive_negative(series: pd.Series):
    return series.clip(lower=0), series.clip(upper=0)


def build_chart(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.42, 0.25, 0.33],
        vertical_spacing=0.05,
        subplot_titles=(
            "10-Year TIPS Yield vs. Model Fair Value",
            "Residual (Actual − Fair Value)",
            "Fair Value Decomposition (Component Contributions)",
        ),
    )

    dates = df.index

    # ── Row 1: Actual vs Fair Value ──────────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=dates, y=df["DFII10"],
            name="Actual TIPS Yield",
            legendgroup="p1_actual",
            legendgrouptitle=dict(text="<b>Yield vs. Fair Value</b>", font=dict(size=12)),
            line=dict(color="#1f77b4", width=2),
            hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra>Actual DFII10</extra>",
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

    # ── Row 2: Residual ──────────────────────────────────────────────────────
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

    # ±1σ and ±2σ bands on residual panel
    resid_std = resid.std()
    for n, dash, opacity in [(1, "dash", 0.6), (2, "dot", 0.45)]:
        for sign, label in [(1, f"+{n}σ"), (-1, f"−{n}σ")]:
            fig.add_hline(
                y=sign * n * resid_std,
                line=dict(color="#888", width=1, dash=dash),
                opacity=opacity,
                annotation_text=label,
                annotation_position="right" if sign == 1 else "right",
                annotation_font=dict(size=10, color="#666"),
                row=2, col=1,
            )

    # ── Row 3: Stacked component contributions ───────────────────────────────
    components = [
        ("p3_alpha", df["contrib_alpha"], "α  Intercept",           "rgba(150, 100, 200, 0.55)", "#7b52ab"),
        ("p3_rstar", df["contrib_rstar"], "β₁·R*  (Neutral rate)",  "rgba( 31, 119, 180, 0.55)", "#1f77b4"),
        ("p3_tp",    df["contrib_tp"],    "β₂·TP  (Term premium)",  "rgba( 44, 160,  44, 0.55)", "#2ca02c"),
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
    latest_resid = df["Residual"].iloc[-1]
    latest_fv = df["FairValue"].iloc[-1]
    latest_actual = df["DFII10"].iloc[-1]
    latest_date = df.index[-1]
    bias = "Cheap / Undervalued" if latest_resid > 0 else "Rich / Overvalued"
    bias_color = "#2ca02c" if latest_resid > 0 else "#d62728"

    fig.add_annotation(
        x=0.01, y=0.99, xref="paper", yref="paper",
        text=(
            f"<b>As of {latest_date.strftime('%b %Y')}</b><br>"
            f"Actual DFII10: <b>{latest_actual:.2f}%</b><br>"
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
            text="10-Year TIPS: Fair Value Model (R* + Term Premium)",
            x=0.5, xanchor="center",
            font=dict(size=20, color="#1a1a2e"),
        ),
        height=950,
        template="plotly_white",
        legend=dict(
            orientation="v",
            x=1.01, xanchor="left",
            y=0.5, yanchor="middle",
            font=dict(size=12),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#ddd",
            borderwidth=1,
            tracegroupgap=12,
        ),
        margin=dict(t=90, l=60, r=190, b=60),
        hovermode="x unified",
    )

    fig.update_yaxes(title_text="Real Yield (%)", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(title_text="Residual (pp)", ticksuffix="pp", row=2, col=1)
    fig.update_yaxes(title_text="Contribution (%)", ticksuffix="%", row=3, col=1)
    fig.update_xaxes(title_text="", row=3, col=1)

    return fig


# ---------------------------------------------------------------------------
# Stats table HTML
# ---------------------------------------------------------------------------

def build_stats_table(ols_result, adf_result, dw_stat: float) -> str:
    params = ols_result.params
    tvals = ols_result.tvalues
    pvals = ols_result.pvalues
    conf = ols_result.conf_int()

    adf_stat, adf_pval = adf_result[0], adf_result[1]
    adf_pass = adf_pval < 0.10
    adf_color = "#2ca02c" if adf_pass else "#d62728"
    adf_label = "Stationary ✓" if adf_pass else "Non-stationary ✗"

    dw_ok = 1.5 <= dw_stat <= 2.5
    dw_color = "#2ca02c" if dw_ok else "#e67e22"

    def pval_badge(p):
        if p < 0.01:
            return f'<span style="color:#2ca02c;font-weight:600">{p:.4f} ***</span>'
        elif p < 0.05:
            return f'<span style="color:#2ca02c">{p:.4f} **</span>'
        elif p < 0.10:
            return f'<span style="color:#e67e22">{p:.4f} *</span>'
        else:
            return f'<span style="color:#d62728">{p:.4f}</span>'

    rows = ""
    labels = {"const": "α  (Intercept)", "rstar": "β₁  R* (Laubach-Williams)", "TP": "β₂  TP (THREEFYTP10)"}
    for var, label in labels.items():
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border:1px solid #ddd;">{label}</td>
          <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;">{params[var]:.4f}</td>
          <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;">{tvals[var]:.2f}</td>
          <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;">{pval_badge(pvals[var])}</td>
          <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;">[{conf.loc[var, 0]:.3f}, {conf.loc[var, 1]:.3f}]</td>
        </tr>"""

    return f"""
<div style="max-width:900px;margin:0 auto 32px;padding:0 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#333;line-height:1.7;">
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:40px;">Regression Statistics</h2>
  <p>OLS regression: <code>DFII10 = α + β₁·R* + β₂·TP + ε</code> &nbsp;|&nbsp; N = {int(ols_result.nobs)} monthly observations</p>

  <table style="width:100%;border-collapse:collapse;margin:12px 0 20px;">
    <thead>
      <tr style="background:#f5f5f5;">
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Variable</th>
        <th style="text-align:right;padding:8px 12px;border:1px solid #ddd;">Coeff.</th>
        <th style="text-align:right;padding:8px 12px;border:1px solid #ddd;">t-stat</th>
        <th style="text-align:right;padding:8px 12px;border:1px solid #ddd;">p-value</th>
        <th style="text-align:right;padding:8px 12px;border:1px solid #ddd;">95% CI</th>
      </tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>

  <table style="width:100%;border-collapse:collapse;margin:0 0 20px;">
    <thead>
      <tr style="background:#f5f5f5;">
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Fit Statistic</th>
        <th style="text-align:right;padding:8px 12px;border:1px solid #ddd;">Value</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Interpretation</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;">R²</td>
        <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;"><b>{ols_result.rsquared:.4f}</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Share of DFII10 variance explained</td>
      </tr>
      <tr style="background:#fafafa;">
        <td style="padding:8px 12px;border:1px solid #ddd;">Adj. R²</td>
        <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;"><b>{ols_result.rsquared_adj:.4f}</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Penalised for number of regressors</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;">F-statistic</td>
        <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;"><b>{ols_result.fvalue:.2f}</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Joint significance (p = {ols_result.f_pvalue:.4g})</td>
      </tr>
      <tr style="background:#fafafa;">
        <td style="padding:8px 12px;border:1px solid #ddd;">ADF on residuals</td>
        <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;"><b style="color:{adf_color}">{adf_stat:.3f}  (p = {adf_pval:.3f})</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;"><b style="color:{adf_color}">{adf_label}</b> — {'residuals are I(0); regression is not spurious' if adf_pass else 'residuals may be non-stationary; interpret with caution'}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;">Durbin-Watson</td>
        <td style="padding:8px 12px;border:1px solid #ddd;text-align:right;"><b style="color:{dw_color}">{dw_stat:.3f}</b></td>
        <td style="padding:8px 12px;border:1px solid #ddd;">{'Near 2 — no severe autocorrelation' if dw_ok else 'Deviates from 2 — residuals show autocorrelation (expected in levels)'}</td>
      </tr>
    </tbody>
  </table>
  <p style="font-size:13px;color:#555;">*** p&lt;0.01 &nbsp; ** p&lt;0.05 &nbsp; * p&lt;0.10. &nbsp; OLS standard errors are not HAC-adjusted; given the autocorrelated nature of macro time series, t-statistics are indicative rather than exact.</p>
</div>
"""


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

METHODOLOGY_HTML = """
<div style="max-width:900px;margin:0 auto 48px;padding:0 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;color:#333;line-height:1.7;">
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:40px;">Model Methodology</h2>
  <p>This model estimates the fair value of the 10-year TIPS yield (DFII10) via OLS regression on two theoretically motivated inputs:</p>
  <table style="width:100%;border-collapse:collapse;margin:12px 0 20px;">
    <thead>
      <tr style="background:#f5f5f5;">
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Component</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Proxy</th>
        <th style="text-align:left;padding:8px 12px;border:1px solid #ddd;">Source</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>R*</b> — Neutral real rate</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Laubach-Williams two-sided estimate (quarterly, interpolated monthly)</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">Federal Reserve Bank of New York</td>
      </tr>
      <tr style="background:#fafafa;">
        <td style="padding:8px 12px;border:1px solid #ddd;"><b>TP</b> — Term premium</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">ACM 10-Year Term Premium on Zero Coupon Bond (THREEFYTP10)</td>
        <td style="padding:8px 12px;border:1px solid #ddd;">FRED (Adrian-Crump-Moench model)</td>
      </tr>
    </tbody>
  </table>
  <p><b>Regression:</b> DFII10 = α + β₁·R* + β₂·TP + ε</p>
  <p style="margin-top:4px;font-size:13px;color:#555;">OLS coefficients are estimated over the full available sample. Fair value at each date is the in-sample fitted value. Unlike a calibrated mean-zero intercept, regression-estimated coefficients allow the data to determine how much each factor loads onto the real yield — which may deviate from 1:1 due to inflation risk premium, liquidity effects, and other wedges between nominal and real term premia.</p>
  <p><b>Residual</b> = Actual DFII10 − Fair Value</p>
  <ul style="margin:8px 0 16px 20px;">
    <li><span style="color:#2ca02c;font-weight:600;">Residual &gt; 0</span>: Real yield trades above fair value → market is <b>cheap / undervalued</b></li>
    <li><span style="color:#d62728;font-weight:600;">Residual &lt; 0</span>: Real yield trades below fair value → market is <b>rich / overvalued</b></li>
  </ul>
  <p><b>ADF test on residuals:</b> Stationarity of ε confirms the regression is not spurious (cointegrating relationship between DFII10, R*, and TP).</p>
  <h2 style="font-size:17px;border-bottom:1px solid #ddd;padding-bottom:8px;margin-top:32px;">Notes &amp; Caveats</h2>
  <ul style="margin:8px 0 0 20px;">
    <li>Sample is constrained by DFII10 availability (from April 2006 onwards).</li>
    <li>R* is the Laubach-Williams <em>two-sided</em> (smoothed) estimate; it is revised retrospectively each quarter. Real-time r* is subject to significant uncertainty and revision.</li>
    <li>THREEFYTP10 is the ACM nominal term premium; it reflects both real term risk and inflation risk premium. The regression intercept and β₂ absorb these wedges relative to the TIPS market.</li>
    <li>Daily series (DFII10, THREEFYTP10) are averaged to monthly; quarterly r* is forward-filled to monthly.</li>
    <li>This is an in-sample fit. The model is not estimated on a rolling or expanding basis — residuals should not be used as a standalone trading signal without out-of-sample validation.</li>
  </ul>
  <p style="margin-top:20px;color:#888;font-size:12px;">Sources: Federal Reserve Bank of New York (Laubach-Williams r* estimates), Federal Reserve Bank of New York via FRED (ACM Term Premium, THREEFYTP10), Federal Reserve H.15 via FRED (DFII10). DFII10 is the 10-Year Treasury Inflation-Indexed Constant Maturity yield.</p>
</div>
"""


def build_html(fig: go.Figure, df: pd.DataFrame, ols_result, adf_result, dw_stat: float) -> str:
    today = date.today().strftime("%B %d, %Y")
    latest_date = df.index[-1].strftime("%B %Y")
    latest_resid = df["Residual"].iloc[-1]
    bias = "Cheap / Undervalued" if latest_resid > 0 else "Rich / Overvalued"

    chart_div = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": True, "displaylogo": False},
    )
    stats_html = build_stats_table(ols_result, adf_result, dw_stat)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>10Y TIPS Fair Value Model</title>
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
  <h1>10-Year TIPS: Fair Value Model</h1>
  <p class="subtitle">
    Signal as of {latest_date}: <strong>{bias}</strong> ({latest_resid:+.2f}pp vs. fair value) &nbsp;|&nbsp; Updated {today}
  </p>
  <div class="chart-wrap">
    {chart_div}
  </div>
  {stats_html}
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
    df, ols_result, adf_result, dw_stat = build_dataset(fred)

    alpha = ols_result.params["const"]
    beta_rstar = ols_result.params["rstar"]
    beta_tp = ols_result.params["TP"]
    latest = df.iloc[-1]

    print(f"\n  OLS results:")
    print(f"    α  = {alpha:+.4f}  (t = {ols_result.tvalues['const']:.2f}, p = {ols_result.pvalues['const']:.4f})")
    print(f"    β₁ = {beta_rstar:+.4f}  (t = {ols_result.tvalues['rstar']:.2f}, p = {ols_result.pvalues['rstar']:.4f})  [R*]")
    print(f"    β₂ = {beta_tp:+.4f}  (t = {ols_result.tvalues['TP']:.2f}, p = {ols_result.pvalues['TP']:.4f})  [TP]")
    print(f"    R² = {ols_result.rsquared:.4f}  |  Adj. R² = {ols_result.rsquared_adj:.4f}")
    print(f"    F-stat = {ols_result.fvalue:.2f}  (p = {ols_result.f_pvalue:.4g})")
    print(f"    ADF on residuals: stat = {adf_result[0]:.3f}, p = {adf_result[1]:.3f}  "
          f"({'STATIONARY' if adf_result[1] < 0.10 else 'NON-STATIONARY'})")
    print(f"    Durbin-Watson = {dw_stat:.3f}")
    print(f"\n  Latest ({df.index[-1].strftime('%b %Y')}):")
    print(f"    R*         = {latest['rstar']:.2f}%")
    print(f"    TP         = {latest['TP']:.2f}%")
    print(f"    Fair Value = {latest['FairValue']:.2f}%")
    print(f"    Actual     = {latest['DFII10']:.2f}%")
    print(f"    Residual   = {latest['Residual']:+.2f}pp  ({'CHEAP' if latest['Residual'] > 0 else 'RICH'})")

    print("\n[3/4] Building chart...")
    fig = build_chart(df)

    print("[4/4] Writing HTML report...")
    html = build_html(fig, df, ols_result, adf_result, dw_stat)
    os.makedirs(os.path.dirname(os.path.expanduser(OUTPUT_PATH)), exist_ok=True)
    with open(os.path.expanduser(OUTPUT_PATH), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  Done → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
