"""
Country Equity ETF vs FX Fair Value Dashboard
==============================================
Uses country equity ETF performance (relative to US) as LASSO predictors
for FX fair value estimation. LassoCV selects optimal alpha; top 5 features
are selected and the model is refit on those alone.

Outputs:
  reports/country-equity-fx/index.html          — main summary bar chart
  reports/country-equity-fx/{CCY}_analysis.html — per-currency 2×2 detail
  reports/country-equity-fx/network.html         — cosine similarity graph
  reports/country-equity-fx/country_equity_fx_data.json

Data sources:
  - Country ETFs: yfinance (US-listed ETFs)
  - FX rates:     GitHub raw CSV (EMFX_risk_diffusion repo)
"""

import os
import sys
import json
import datetime
from datetime import date

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.offline as pyo
from plotly.subplots import make_subplots
import yfinance as yf
import requests
from sklearn.linear_model import LassoCV, Lasso
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score

# ── Configuration ────────────────────────────────────────────────────────────

YEARS = 10
LOOKBACK_YEARS = 5        # window for model fitting
MAX_NA_ROWS = 100         # drop ETF columns with more NAs than this
TEST_SIZE = 0.25
RANDOM_STATE = 42
TOP_N_FEATURES = 5
LASSO_MAX_ITER = 10000
LASSO_CV_FOLDS = 5

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports", "country-equity-fx")
OUTPUT_DIR = os.path.normpath(OUTPUT_DIR)

FX_CSV_URL = (
    "https://raw.githubusercontent.com/DataVizHonduran/EMFX_risk_diffusion"
    "/main/fx_data_raw.csv"
)

# ETF → country name mapping (universe)
COUNTRY_ETF_MAP = {
    "EWA": "Australia", "EWO": "Austria", "EWK": "Belgium", "EWZ": "Brazil",
    "EWC": "Canada", "ECH": "Chile", "GXC": "China", "GXG": "Colombia",
    "EGPT": "Egypt", "EWQ": "France", "EWG": "Germany", "EWH": "Hong Kong",
    "PIN": "India", "IDX": "Indonesia", "EIRL": "Ireland", "EIS": "Israel",
    "EWI": "Italy", "EWM": "Malaysia", "EWW": "Mexico", "EWN": "Netherlands",
    "EPU": "Peru", "EPOL": "Poland", "EWS": "Singapore", "EZA": "South Africa",
    "EWY": "South Korea", "EWP": "Spain", "EWD": "Sweden", "EWL": "Switzerland",
    "EWT": "Taiwan", "THD": "Thailand", "TUR": "Turkey", "EWU": "United Kingdom",
    "EUSA": "United States", "VNM": "Vietnam", "ENZL": "New Zealand",
    "NORW": "Norway", "EPHE": "Philippines", "PGAL": "Portugal", "NGE": "Nigeria",
    "QAT": "Qatar", "UAE": "United Arab Emirates", "GREK": "Greece",
    "EWJ": "Japan", "KSA": "Saudi Arabia", "PAK": "Pakistan",
    "ARGT": "Argentina", "EDEN": "Denmark", "EFNL": "Finland", "KWT": "Kuwait",
}

# Subset of 25 well-covered countries used as model predictors
PREDICTOR_COUNTRIES = [
    "Australia", "Brazil", "Canada", "Chile", "China", "Colombia", "France",
    "Germany", "Hong Kong", "India", "Indonesia", "Japan", "Mexico",
    "New Zealand", "Norway", "Peru", "Poland", "South Africa", "South Korea",
    "Sweden", "Switzerland", "Taiwan", "Turkey", "United Kingdom", "United States",
]

INVERSE_MAP = {v: k for k, v in COUNTRY_ETF_MAP.items()}
ETF_LIST = [INVERSE_MAP[c] for c in PREDICTOR_COUNTRIES]  # 25 tickers


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_equity_data():
    """Fetch country equity ETF closes via yfinance, index to 100."""
    start_date = datetime.datetime.now() - datetime.timedelta(days=365 * YEARS)
    print(f"Fetching {len(ETF_LIST)} country ETFs from yfinance …")
    raw = yf.download(ETF_LIST, start=start_date, end=date.today(),
                      auto_adjust=False, progress=False)
    closes = raw["Close"].sort_index(ascending=True)

    # Drop last day (may be incomplete)
    closes = closes.iloc[:-1]
    print(f"  Equity data: {closes.shape[0]} rows, {closes.shape[1]} tickers")

    # Index to 100 at first valid observation
    indexed = closes.apply(lambda col: col / col.dropna().iloc[0] * 100)
    indexed = indexed.bfill()

    # Compute ratios relative to the US ETF (EUSA)
    for ticker in ETF_LIST:
        if ticker in indexed.columns and "EUSA" in indexed.columns:
            indexed[f"{ticker}/EUSA"] = indexed[ticker] / indexed["EUSA"] * 100

    ratios = [f"{t}/EUSA" for t in ETF_LIST if f"{t}/EUSA" in indexed.columns]
    print(f"  Computed {len(ratios)} country/US ratios")
    return indexed, ratios


def load_fx_data():
    """Load FX rates from the EMFX_risk_diffusion GitHub CSV."""
    print(f"Loading FX data from GitHub CSV …")
    df = pd.read_csv(FX_CSV_URL, index_col=0, parse_dates=True)
    df = df.bfill().ffill()
    print(f"  FX data: {df.shape[0]} rows, {df.shape[1]} currencies")
    return df


# ── Model ────────────────────────────────────────────────────────────────────

def fit_currency_model(currency, indexed_df, df_fx, ratios):
    """
    Fit a LASSO model for one currency.
    1. LassoCV to find optimal alpha
    2. Select top-N features by |coeff|
    3. Refit on top-N features only
    Returns a result dict or None on failure.
    """
    try:
        # Drop ratio columns that are mostly NA
        valid_ratios = [
            r for r in ratios
            if r in indexed_df.columns and indexed_df[r].isna().sum() <= MAX_NA_ROWS
        ]

        # Merge equity features with FX target
        test_df = (
            indexed_df[valid_ratios]
            .merge(df_fx[[currency]], left_index=True, right_index=True, how="inner")
        )
        test_df = test_df.tail(252 * LOOKBACK_YEARS)

        y = test_df[currency]
        X = test_df[valid_ratios].bfill().ffill()

        if len(X) < 120:
            print(f"  [{currency}] insufficient rows ({len(X)}), skipping")
            return None

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE
        )

        # Step 1: LassoCV to find best alpha
        lasso_cv = LassoCV(max_iter=LASSO_MAX_ITER, cv=LASSO_CV_FOLDS)
        lasso_cv.fit(X_train, y_train)
        best_alpha = lasso_cv.alpha_

        # Step 2: Fit to get feature importances
        lasso_full = Lasso(max_iter=LASSO_MAX_ITER, alpha=best_alpha)
        lasso_full.fit(X_train, y_train)

        coef_series = pd.Series(lasso_full.coef_, index=X_train.columns)
        top_features = (
            coef_series.abs().sort_values(ascending=False).head(TOP_N_FEATURES).index.tolist()
        )

        # Step 3: Refit on top features only
        X_train_top = X_train[top_features]
        X_test_top = X_test[top_features]

        lasso_top = Lasso(max_iter=LASSO_MAX_ITER, alpha=best_alpha)
        lasso_top.fit(X_train_top, y_train)

        y_pred_test = lasso_top.predict(X_test_top)
        mse = mean_squared_error(y_test, y_pred_test)
        r_squared = r2_score(y_test, y_pred_test)

        # Predict on full dataset
        X_full_top = test_df[top_features].bfill().ffill()
        test_df = test_df.copy()
        test_df["ypred"] = lasso_top.predict(X_full_top)
        test_df["resids"] = (test_df[currency] - test_df["ypred"]) / test_df[currency] * 100

        # Residual percentile bands
        p10 = test_df["resids"].quantile(0.10)
        p90 = test_df["resids"].quantile(0.90)

        # Coefficients
        coeffs = lasso_top.coef_
        coef_pairs = [
            (top_features[i], round(coeffs[i], 4))
            for i in range(len(coeffs)) if coeffs[i] != 0
        ]
        coef_pairs.sort(key=lambda x: abs(x[1]), reverse=True)

        current_actual = float(test_df[currency].iloc[-1])
        current_predicted = float(test_df["ypred"].iloc[-1])
        current_residual = float(test_df["resids"].iloc[-1])

        print(f"  {currency}: R²={r_squared:.3f}, resid={current_residual:.1f}%, "
              f"alpha={best_alpha:.4f}, n_predictors={len(coef_pairs)}")

        return {
            "currency": currency,
            "current_actual": current_actual,
            "current_predicted": current_predicted,
            "current_residual": current_residual,
            "r_squared": r_squared,
            "mse": mse,
            "best_alpha": best_alpha,
            "chart_data": test_df,
            "top_features": top_features,
            "coef_pairs": coef_pairs,
            "p10": p10,
            "p90": p90,
        }

    except Exception as exc:
        print(f"  [{currency}] error: {exc}")
        return None


# ── HTML Generation ───────────────────────────────────────────────────────────

def _etf_to_country(ticker_ratio):
    """'EWG/EUSA' → 'Germany'"""
    ticker = ticker_ratio.split("/")[0]
    return COUNTRY_ETF_MAP.get(ticker, ticker)


def create_main_dashboard(summary_df, last_updated):
    """
    Returns (fig, html_str) where html_str is a complete page with a real
    HTML sidebar so links open in the same tab (SVG annotation links cannot
    be forced to stay in the same tab across browsers).
    """
    colors = ["#d62728" if x > 0 else "#2ca02c" for x in summary_df["Residual_%"]]

    hover_text = []
    for _, row in summary_df.iterrows():
        top_p = row.get("Top_Predictors", "")
        hover_text.append(
            f"<b>{row['Currency']}</b><br>"
            f"Actual: {row['Current_Rate']:.4f}<br>"
            f"Fair Value: {row['Fair_Value']:.4f}<br>"
            f"Residual: {row['Residual_%']:.1f}%<br>"
            f"R²: {row['R_Squared']:.3f}<br>"
            f"Top predictors: {top_p}<br>"
            f"<i>Click bar to open detail</i>"
        )

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=summary_df["Currency"],
        x=summary_df["Residual_%"],
        orientation="h",
        marker_color=colors,
        text=[f"{x:.1f}%" for x in summary_df["Residual_%"]],
        textposition="outside",
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_text,
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="gray", line_width=1)

    fig.update_layout(
        title={
            "text": "FX Fair Value: Country Equity ETF Model",
            "x": 0.5, "xanchor": "center", "font": {"size": 22},
        },
        xaxis_title="Residual (% deviation from fair value)",
        yaxis_title="",
        height=max(520, len(summary_df) * 26),
        template="plotly_white",
        hovermode="closest",
        showlegend=False,
        margin=dict(l=80, r=40, t=60, b=50),
    )

    # ── Build sidebar link items ─────────────────────────────────────────
    sidebar_links = "\n".join([
        f'<a href="{c}_analysis.html">{c}</a>'
        for c in summary_df["Currency"]
    ])

    import plotly.io as _pio
    chart_div = _pio.to_html(
        fig, div_id="main-chart",
        include_plotlyjs=True, full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )

    html_str = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FX Country Equity Fair Value</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #f8f9fa; display: flex; min-height: 100vh; }}
  #sidebar {{
    width: 160px; min-width: 140px; background: #fff;
    border-right: 1px solid #e0e0e0; padding: 16px 12px;
    display: flex; flex-direction: column; gap: 4px;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
  }}
  #sidebar h3 {{ font-size: 12px; color: #888; text-transform: uppercase;
                 letter-spacing: .05em; margin-bottom: 8px; }}
  #sidebar a {{
    display: block; padding: 5px 8px; border-radius: 4px;
    text-decoration: none; font-size: 13px; font-weight: 500; color: #1f77b4;
    transition: background .15s;
  }}
  #sidebar a:hover {{ background: #eef4fb; }}
  #sidebar .network-link {{ color: #9467bd; margin-top: 10px;
                             border-top: 1px solid #eee; padding-top: 10px; }}
  #sidebar .note {{
    font-size: 10px; color: #888; margin-top: auto; padding-top: 12px;
    border-top: 1px solid #eee; line-height: 1.5;
  }}
  #chart-wrap {{ flex: 1; padding: 8px 4px; }}
  #main-chart {{ width: 100% !important; }}
  #main-chart:hover {{ cursor: pointer; }}
</style>
</head>
<body>
<nav id="sidebar">
  <h3>Currencies</h3>
  {sidebar_links}
  <a href="network.html" class="network-link">🔗 Network graph</a>
  <div class="note">
    LASSO (LassoCV)<br>
    Top-5 country ETF<br>
    predictors vs US<br>
    5-year lookback<br><br>
    🟢 below fair value<br>
    🔴 above fair value<br><br>
    Updated:<br>{last_updated}
  </div>
</nav>
<div id="chart-wrap">
  {chart_div}
</div>
<script>
document.getElementById("main-chart").on("plotly_click", function(data) {{
  if (data.points && data.points.length > 0) {{
    window.location.href = data.points[0].y + "_analysis.html";
  }}
}});
</script>
</body>
</html>"""

    return html_str


def create_currency_page(result, back_link="index.html"):
    """2×2 subplot: actual vs model, residuals with bands, coeff table."""
    currency = result["currency"]
    chart_data = result["chart_data"].copy()

    # Small white-space buffer at the right
    buffer_periods = max(1, int(len(chart_data) * 0.04))
    new_idx = pd.date_range(
        start=chart_data.index[-1] + pd.Timedelta(days=1),
        periods=buffer_periods, freq="D"
    )
    chart_data = pd.concat([chart_data, pd.DataFrame(index=new_idx)])

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            f"{currency} vs Fair Value Model",
            "Residual % (deviation from fair value)",
            "Top Country Equity Predictors",
        ),
        specs=[
            [{"type": "scatter"}, {"type": "scatter"}],
            [{"type": "table", "colspan": 2}, None],
        ],
        row_heights=[0.60, 0.40],
        vertical_spacing=0.14,
        horizontal_spacing=0.08,
    )

    # ── Panel 1: Actual vs Model ──────────────────────────────────────────
    fig.add_scatter(
        x=chart_data.index, y=chart_data[currency],
        mode="lines", name=currency,
        line=dict(color="#1f77b4", width=2),
        row=1, col=1,
    )
    fig.add_scatter(
        x=chart_data.index, y=chart_data["ypred"],
        mode="lines", name="Fair Value",
        line=dict(color="#d62728", width=2, dash="dash"),
        row=1, col=1,
    )

    # ── Panel 2: Residuals + percentile bands ─────────────────────────────
    fig.add_scatter(
        x=chart_data.index, y=chart_data["resids"],
        mode="lines", name="Residual (%)",
        line=dict(color="#2ca02c", width=2),
        row=1, col=2,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1, row=1, col=2)

    p10, p90 = result["p10"], result["p90"]
    for level, label in [(p10, "10th"), (p90, "90th")]:
        fig.add_hline(
            y=level, line=dict(color="#7f7f7f", dash="dot", width=1),
            row=1, col=2,
        )
        fig.add_annotation(
            x=chart_data.index[int(len(chart_data) * 0.98)],
            y=level,
            text=label, showarrow=False,
            font=dict(color="#7f7f7f", size=9),
            xanchor="right",
            row=1, col=2,
        )


    # X-axis: year ticks
    for col in [1, 2]:
        fig.update_xaxes(
            tickformat="%Y", dtick="M12", tickangle=0, row=1, col=col,
        )

    # ── Panel 3: Coefficient table ────────────────────────────────────────
    coef_pairs = result["coef_pairs"]
    if coef_pairs:
        countries = [_etf_to_country(pair[0]) for pair in coef_pairs]
        tickers = [pair[0].split("/")[0] for pair in coef_pairs]
        coeffs = [f"{pair[1]:+.4f}" for pair in coef_pairs]

        fig.add_trace(go.Table(
            header=dict(
                values=["<b>Country</b>", "<b>ETF</b>", "<b>Coefficient</b>"],
                fill_color="#f0f0f0", align="left", font=dict(size=12),
            ),
            cells=dict(
                values=[countries, tickers, coeffs],
                fill_color="white", align="left", font=dict(size=11),
                height=24,
            ),
        ), row=2, col=1)

    # ── Model info box ─────────────────────────────────────────────────────
    cur_actual = result["current_actual"]
    cur_pred = result["current_predicted"]
    cur_resid = result["current_residual"]
    r2 = result["r_squared"]
    mse = result["mse"]
    interp = "BELOW FAIR VALUE" if cur_resid < 0 else "ABOVE FAIR VALUE"
    icolor = "#2ca02c" if cur_resid < 0 else "#d62728"
    n_pred = len(coef_pairs)

    model_info = (
        f"<b>Current Status</b><br>"
        f"Actual: {cur_actual:.4f}<br>"
        f"Fair Value: {cur_pred:.4f}<br>"
        f"Residual: <span style='color:{icolor}'><b>{cur_resid:.1f}%</b></span><br>"
        f"Signal: <span style='color:{icolor}'><b>{interp}</b></span><br>"
        f"<br><b>Model</b><br>"
        f"R²: {r2:.3f}<br>"
        f"MSE: {mse:.4f}<br>"
        f"Alpha (CV): {result['best_alpha']:.4f}<br>"
        f"Predictors: {n_pred}/{TOP_N_FEATURES}"
    )
    fig.add_annotation(
        text=model_info,
        xref="paper", yref="paper", x=1.01, y=1,
        xanchor="left", yanchor="top", showarrow=False,
        font=dict(size=11), align="left",
        bgcolor="rgba(255,255,255,0.9)", bordercolor="#cccccc", borderwidth=1,
    )

    # Back link
    fig.add_annotation(
        text=f'<a href="{back_link}" style="color:#1f77b4; font-size:13px;">← Back to Overview</a>',
        xref="paper", yref="paper", x=0, y=1.07,
        xanchor="left", yanchor="bottom", showarrow=False,
    )

    fig.update_layout(
        title={
            "text": f"{currency} — Country Equity Fair Value Model  (R² = {r2:.3f})",
            "x": 0.5, "xanchor": "center", "font": {"size": 18},
        },
        width=1420,
        height=920,
        template="plotly_white",
        showlegend=True,
        legend=dict(orientation="h", y=1.03, x=0.5, xanchor="center"),
        margin=dict(l=60, r=240, t=90, b=40),
    )
    return fig


def create_network_page(coeff_df, back_link="index.html"):
    """
    Build a ForceAtlas2 currency relationship graph from the coefficient matrix.
    Falls back to a spring-layout if `fa2` is not installed.
    """
    from sklearn.metrics.pairwise import cosine_similarity

    sim_matrix = cosine_similarity(coeff_df)
    currencies = coeff_df.index.tolist()
    N = len(currencies)
    threshold = 0.20

    edges = [
        (i, j, sim_matrix[i, j])
        for i in range(N) for j in range(i + 1, N)
        if sim_matrix[i, j] > threshold
    ]

    # ── Layout: try ForceAtlas2, fall back to a simple circular layout ───
    try:
        from fa2 import ForceAtlas2
        adjacency = np.zeros((N, N))
        for i, j, w in edges:
            adjacency[i, j] = adjacency[j, i] = w
        fa2 = ForceAtlas2(
            outboundAttractionDistribution=True,
            barnesHutOptimize=True,
            barnesHutTheta=1.2,
            scalingRatio=2.0,
            edgeWeightInfluence=1.0,
            jitterTolerance=1.0,
        )
        positions = fa2.forceatlas2(adjacency, iterations=2000)
        node_x = [positions[i][0] for i in range(N)]
        node_y = [positions[i][1] for i in range(N)]
        layout_name = "ForceAtlas2"
    except ImportError:
        print("  fa2 not found — using circular fallback layout")
        angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
        node_x = np.cos(angles).tolist()
        node_y = np.sin(angles).tolist()
        layout_name = "Circular"

    # ── Edge traces ───────────────────────────────────────────────────────
    edge_traces = []
    for i, j, weight in edges:
        edge_traces.append(go.Scatter(
            x=[node_x[i], node_x[j], None],
            y=[node_y[i], node_y[j], None],
            mode="lines",
            line=dict(width=weight * 5, color="lightgray"),
            opacity=0.6,
            hoverinfo="text",
            text=f"{currencies[i]} ↔ {currencies[j]}: {weight:.2f}",
            showlegend=False,
        ))

    # ── Node trace ────────────────────────────────────────────────────────
    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=currencies,
        textposition="top center",
        hoverinfo="text",
        marker=dict(size=16, color="#1f77b4", line=dict(width=1.5, color="white")),
        showlegend=False,
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        title={
            "text": (
                f"Currency Relationship Graph — Country Equity Drivers  "
                f"({layout_name}, threshold={threshold})"
            ),
            "x": 0.5, "xanchor": "center", "font": {"size": 20},
        },
        showlegend=False,
        hovermode="closest",
        width=960, height=960,
        margin=dict(l=20, r=20, t=70, b=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        template="plotly_white",
    )
    fig.add_annotation(
        text=f'<a href="{back_link}" style="color:#1f77b4; font-size:13px;">← Back to Overview</a>',
        xref="paper", yref="paper", x=0, y=1.04,
        xanchor="left", yanchor="bottom", showarrow=False,
    )
    return fig


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("COUNTRY EQUITY vs FX — FAIR VALUE DASHBOARD")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Load data
    indexed_df, ratios = load_equity_data()
    df_fx = load_fx_data()

    currencies = [c for c in df_fx.columns if c not in ["Date"]]
    print(f"\nModelling {len(currencies)} currencies …\n")

    # 2. Fit models
    results = {}
    coefficients_dict = {}   # {currency: {ticker_ratio: coeff}}

    for currency in currencies:
        result = fit_currency_model(currency, indexed_df, df_fx, ratios)
        if result:
            results[currency] = result
            coefficients_dict[currency] = {
                pair[0]: pair[1] for pair in result["coef_pairs"]
            }

    if not results:
        print("ERROR: no currencies modelled successfully. Exiting.")
        sys.exit(1)

    # 3. Summary DataFrame
    summary_rows = []
    for currency, r in results.items():
        top_labels = ", ".join([_etf_to_country(p[0]) for p in r["coef_pairs"][:3]])
        summary_rows.append({
            "Currency": currency,
            "Current_Rate": r["current_actual"],
            "Fair_Value": r["current_predicted"],
            "Residual_%": r["current_residual"],
            "R_Squared": r["r_squared"],
            "Num_Predictors": len(r["coef_pairs"]),
            "Top_Predictors": top_labels,
        })

    summary_df = (
        pd.DataFrame(summary_rows)
        .sort_values("Residual_%", ascending=True)
        .reset_index(drop=True)
    )

    print(f"\n{'='*60}")
    print(f"Modelled {len(summary_df)} currencies successfully")
    print("=" * 60)
    print(summary_df[["Currency", "Residual_%", "R_Squared", "Top_Predictors"]].to_string(index=False))

    # 4. Coefficient matrix for cross-currency analysis
    coeff_df = pd.DataFrame(coefficients_dict).T.fillna(0)

    last_updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    config = {"displayModeBar": False, "responsive": True}

    # 5. Main dashboard — custom HTML layout with real sidebar links
    print("\nGenerating main dashboard …")
    main_html = create_main_dashboard(summary_df, last_updated)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w") as f:
        f.write(main_html)
    print("  ✓ index.html")

    # 6. Individual currency pages
    print("Generating currency detail pages …")
    for currency, result in results.items():
        fig = create_currency_page(result, back_link="index.html")
        fname = os.path.join(OUTPUT_DIR, f"{currency}_analysis.html")
        pyo.plot(fig, filename=fname, auto_open=False, config=config)
        print(f"  ✓ {currency}_analysis.html")

    # 7. Network graph
    print("Generating currency network graph …")
    try:
        net_fig = create_network_page(coeff_df, back_link="index.html")
        pyo.plot(
            net_fig,
            filename=os.path.join(OUTPUT_DIR, "network.html"),
            auto_open=False, config=config,
        )
        print("  ✓ network.html")
    except Exception as exc:
        print(f"  network.html skipped: {exc}")

    # 8. JSON metadata
    feature_counts = (coeff_df != 0).sum().sort_values(ascending=False)
    avg_coeff = pd.to_numeric(coeff_df.replace(0, pd.NA).mean(), errors="coerce")
    feature_summary = pd.DataFrame({
        "Count": feature_counts,
        "Avg_Coeff": avg_coeff.round(4),
    }).dropna(subset=["Avg_Coeff"])
    feature_summary.index = feature_summary.index.map(_etf_to_country)

    metadata = {
        "last_updated": last_updated,
        "currencies_analysed": len(summary_df),
        "fair_value_summary": summary_df.to_dict("records"),
        "top_global_predictors": feature_summary.head(10).reset_index().to_dict("records"),
        "methodology": {
            "model": "LASSO Regression (LassoCV, top-5 features refit)",
            "predictors": "Country equity ETF performance relative to US (EUSA)",
            "countries": PREDICTOR_COUNTRIES,
            "lookback_years": LOOKBACK_YEARS,
            "test_size": TEST_SIZE,
            "cv_folds": LASSO_CV_FOLDS,
        },
    }

    json_path = os.path.join(OUTPUT_DIR, "country_equity_fx_data.json")
    with open(json_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    print("  ✓ country_equity_fx_data.json")

    print(f"\n{'='*60}")
    print("DONE")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
