#!/usr/bin/env python3
"""
FX Factor Fair Value Dashboard
Lasso regression using factor/style ETF ratios vs SPY to estimate
fair value for 10 EM+G10 currency pairs.

Run:
    python3 scripts/generate_fx_factor_fairvalue.py
"""

import os
import json
import datetime
from datetime import date, timedelta
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf
from pandas_datareader import data as pdr
from sklearn.linear_model import Lasso
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

# ── Config ─────────────────────────────────────────────────────────────────────

YEARS = 10
OUTPUT_DIR = os.environ.get("OUTPUT_DIR") or os.path.expanduser(
    "~/boquin.github.io/reports/fx-factor-fairvalue"
)
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

FACTOR_TICKERS = [
    "MTUM", "SPHB", "IWC", "IVW", "IJT",
    "IJR", "IJS", "IJK", "QUAL", "IJJ",
    "VYM", "IVE", "USMV", "SPY"
]

FACTOR_LABELS = {
    "MTUM": "Momentum", "SPHB": "High Beta", "IWC": "Micro Cap",
    "IVW": "LG Growth", "IJT": "SC Growth", "IJR": "Small Cap",
    "IJS": "SC Value",  "IJK": "MC Growth",  "QUAL": "Quality",
    "IJJ": "MC Value",  "VYM": "High Div",   "IVE": "LG Value",
    "USMV": "Min Vol",  "SPY": "S&P 500"
}

FRED_SERIES = [
    "DEXNOUS", "DEXSDUS", "DEXMXUS", "DEXBZUS", "DEXSFUS",
    "DEXINUS", "DEXKOUS", "DEXTHUS", "DEXSIUS", "DEXCHUS",
]
FX_LABELS = [
    "USDNOK", "USDSEK", "USDMXN", "USDBRL", "USDZAR",
    "USDINR", "USDKRW", "USDTHB", "USDSGD", "USDCNH"
]

# ── Data fetch ─────────────────────────────────────────────────────────────────

def fetch_factor_data():
    start = datetime.datetime.now() - timedelta(days=365 * YEARS)
    print(f"Fetching factor ETF data ({YEARS}Y)…")
    raw = yf.download(FACTOR_TICKERS, start=start, end=date.today(),
                      auto_adjust=True, progress=False)
    close = raw["Close"][FACTOR_TICKERS].dropna(how="all").sort_index()
    # index to 100 from first valid observation
    indexed = close.apply(lambda col: col / col.dropna().iloc[0] * 100)
    indexed = indexed.bfill()
    # compute ratios vs SPY for each non-SPY factor
    ratios = []
    for t in FACTOR_TICKERS:
        if t == "SPY":
            continue
        col = f"{t}/SPY"
        indexed[col] = indexed[t] / indexed["SPY"] * 100
        ratios.append(col)
    return indexed, ratios


def fetch_fred_fx():
    end = date.today()
    start = end - timedelta(days=365 * YEARS)
    print("Fetching FX data from FRED…")
    df = pdr.DataReader(FRED_SERIES, "fred", start, end)
    df.columns = FX_LABELS
    df = df.apply(pd.to_numeric, errors="coerce")
    df.index = pd.to_datetime(df.index)
    df = df.bfill()
    return df


# ── Model ──────────────────────────────────────────────────────────────────────

def fit_currency(currency, indexed_df, fx_df, ratios):
    try:
        merged = indexed_df[ratios].merge(
            fx_df[[currency]], left_index=True, right_index=True, how="inner"
        ).bfill()
        merged = merged.loc[:, merged.isnull().sum() <= 10]

        valid_ratios = [c for c in ratios if c in merged.columns]
        X = merged[valid_ratios].bfill()
        y = merged[currency]

        if len(X) < 100:
            return None

        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, random_state=42)
        lasso = Lasso(alpha=0.9, max_iter=10000)
        lasso.fit(X_tr, y_tr)

        merged["ypred"] = lasso.predict(X[valid_ratios].bfill())
        merged["resid"] = (merged[currency] - merged["ypred"]) / merged[currency] * 100

        y_pred = lasso.predict(X_te)
        r2  = r2_score(y_te, y_pred)
        mse = mean_squared_error(y_te, y_pred)

        coefs = lasso.coef_
        selected = [valid_ratios[i] for i, c in enumerate(coefs) if c != 0]

        return {
            "currency": currency,
            "actual":   merged[currency].iloc[-1],
            "predicted": merged["ypred"].iloc[-1],
            "residual": merged["resid"].iloc[-1],
            "r2": r2, "mse": mse,
            "data": merged,
            "selected_vars": selected,
        }
    except Exception as e:
        print(f"  {currency} failed: {e}")
        return None


# ── Chart helpers ──────────────────────────────────────────────────────────────

def fig_to_json(fig):
    return pio.to_json(fig, engine="json")


def make_overview_bar(summary):
    colors = ["#c62828" if r > 0 else "#1565c0" for r in summary["residual"]]
    fig = go.Figure(go.Bar(
        y=summary["currency"],
        x=summary["residual"],
        orientation="h",
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in summary["residual"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Residual: %{x:.1f}%<extra></extra>",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="#aaa", line_width=1)
    fig.update_layout(
        title=dict(text="FX Factor Fair Value — Residual Overview", font_size=14),
        xaxis_title="Residual % (positive = overvalued vs model, negative = undervalued)",
        height=500,
        margin=dict(l=10, r=80, t=40, b=40),
        plot_bgcolor="#fff", paper_bgcolor="#fff",
        xaxis=dict(gridcolor="#f0f0f0", zeroline=True, zerolinecolor="#aaa", zerolinewidth=1),
    )
    return fig


def make_explorer(results, summary):
    currencies = summary["currency"].tolist()
    fig = go.Figure()

    for i, ccy in enumerate(currencies):
        res = results[ccy]
        d   = res["data"]
        # pad right edge by 5%
        pad = pd.date_range(d.index[-1], periods=max(int(len(d) * 0.05), 5), freq="D")
        d   = pd.concat([d, pd.DataFrame(index=pad)])

        visible = (i == 0)
        x = d.index.strftime("%Y-%m-%d").tolist()

        # subplot 1: actual vs model
        fig.add_trace(go.Scatter(
            x=x, y=d[ccy].tolist(), mode="lines", name=ccy,
            line=dict(color="#1a3a2f", width=1.8),
            visible=visible,
            hovertemplate="%{x}: %{y:.4f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=x, y=d["ypred"].tolist(), mode="lines", name="Fair Value",
            line=dict(color="#e65100", width=1.5, dash="dash"),
            visible=visible,
            hovertemplate="%{x}: %{y:.4f}<extra></extra>",
        ))
        # subplot 2 (secondary y): residual
        fig.add_trace(go.Scatter(
            x=x, y=d["resid"].tolist(), mode="lines", name="Residual %",
            line=dict(color="#1565c0", width=1.4),
            visible=visible,
            yaxis="y2",
            hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
        ))

    # dropdown buttons (3 traces per currency)
    buttons = []
    for i, ccy in enumerate(currencies):
        res = results[ccy]
        vis = [False] * (len(currencies) * 3)
        vis[i*3] = vis[i*3+1] = vis[i*3+2] = True
        selected_str = ", ".join(
            v.replace("/SPY", "") for v in res["selected_vars"][:5]
        ) or "none"
        model_text = (
            f"R²: {res['r2']:.3f} | Residual: {res['residual']:+.1f}%<br>"
            f"Key factors: {selected_str}"
        )
        buttons.append(dict(
            label=ccy,
            method="update",
            args=[
                {"visible": vis},
                {
                    "title": f"{ccy} — Actual vs Factor Fair Value Model",
                    "annotations": [dict(
                        x=0.01, y=0.98, xref="paper", yref="paper",
                        text=model_text, showarrow=False,
                        font=dict(size=10), align="left",
                        bgcolor="rgba(255,255,255,0.85)",
                        bordercolor="#ccc", borderwidth=1,
                        xanchor="left", yanchor="top",
                    )],
                }
            ],
        ))

    first = currencies[0]
    first_res = results[first]
    selected_str0 = ", ".join(
        v.replace("/SPY", "") for v in first_res["selected_vars"][:5]
    ) or "none"

    fig.update_layout(
        updatemenus=[dict(
            buttons=buttons, direction="down", showactive=True,
            x=0.01, xanchor="left", y=1.12, yanchor="top",
            bgcolor="#fff", bordercolor="#cdd4db", font_size=13,
        )],
        title=f"{first} — Actual vs Factor Fair Value Model",
        yaxis=dict(title="FX Rate", gridcolor="#f0f0f0"),
        yaxis2=dict(
            title="Residual %", overlaying="y", side="right",
            gridcolor="#f0f0f0", zeroline=True, zerolinecolor="#999",
        ),
        height=460,
        margin=dict(l=10, r=60, t=80, b=40),
        plot_bgcolor="#fff", paper_bgcolor="#fff",
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.12),
        annotations=[dict(
            x=0.01, y=0.98, xref="paper", yref="paper",
            text=(
                f"R²: {first_res['r2']:.3f} | Residual: {first_res['residual']:+.1f}%<br>"
                f"Key factors: {selected_str0}"
            ),
            showarrow=False, font=dict(size=10), align="left",
            bgcolor="rgba(255,255,255,0.85)", bordercolor="#ccc", borderwidth=1,
            xanchor="left", yanchor="top",
        )],
    )
    return fig


# ── HTML ───────────────────────────────────────────────────────────────────────

def build_extremes_table(summary):
    rich  = summary[summary["residual"] > 0].sort_values("residual", ascending=False)
    cheap = summary[summary["residual"] < 0].sort_values("residual")

    def rows(df, label, color):
        out = ""
        for _, r in df.iterrows():
            out += f"""
        <tr>
          <td><strong>{r['currency']}</strong></td>
          <td style="color:{color};font-weight:700">{r['residual']:+.1f}%</td>
          <td>{r['r2']:.3f}</td>
          <td style="color:{color};font-weight:600">{label}</td>
        </tr>"""
        return out

    return f"""
    <table class="ext-table">
      <thead><tr>
        <th>Currency</th><th>Residual</th><th>R²</th><th>Signal</th>
      </tr></thead>
      <tbody>
        {rows(rich,  "Overvalued vs model", "#c62828")}
        {rows(cheap, "Undervalued vs model", "#1565c0")}
      </tbody>
    </table>"""


def generate_html(results, summary, today_str):
    fig_bar      = make_overview_bar(summary)
    fig_explorer = make_explorer(results, summary)

    bar_json      = fig_to_json(fig_bar)
    explorer_json = fig_to_json(fig_explorer)
    extremes_html = build_extremes_table(summary)

    n_total = len(summary)
    n_rich  = (summary["residual"] > 0).sum()
    n_cheap = (summary["residual"] < 0).sum()
    med_res = round(summary["residual"].median(), 1)
    med_sign = "+" if med_res >= 0 else ""
    med_color = "red" if med_res > 0 else "green"

    factor_list = ", ".join(
        f"{t} ({FACTOR_LABELS[t]})" for t in FACTOR_TICKERS if t != "SPY"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FX Factor Fair Value — boquin.xyz</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f7fa;color:#1a1a1a;font-size:14px}}
.hdr{{background:#1a3a2f;color:#fff;padding:20px 32px}}
.hdr h1{{font-size:1.4rem;font-weight:700;letter-spacing:-.4px}}
.hdr .sub{{font-size:.82rem;opacity:.72;margin-top:5px}}
.hdr .meta{{font-size:.75rem;opacity:.55;margin-top:3px}}
.kpi-bar{{background:#fff;border-bottom:1px solid #e4e8ec;padding:12px 32px;display:flex;gap:32px;flex-wrap:wrap}}
.kpi{{display:flex;flex-direction:column;gap:2px}}
.kpi-lbl{{font-size:.68rem;text-transform:uppercase;letter-spacing:.5px;color:#999;font-weight:600}}
.kpi-val{{font-size:1.2rem;font-weight:700}}
.kpi-val.red{{color:#c62828}}.kpi-val.blue{{color:#1565c0}}.kpi-val.green{{color:#2e7d32}}
.content{{padding:20px 32px;max-width:1440px;margin:0 auto}}
.card{{background:#fff;border:1px solid #e4e8ec;border-radius:10px;padding:16px 20px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.card-title{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:4px}}
.card-note{{font-size:.75rem;color:#aaa;margin-bottom:12px}}
.section-hdr{{font-size:1rem;font-weight:700;color:#1a3a2f;margin:24px 0 12px;border-left:4px solid #1a3a2f;padding-left:10px}}
.method-note{{font-size:.75rem;color:#888;background:#fafbfc;border:1px solid #e8eaec;border-radius:6px;padding:8px 12px;margin-bottom:14px;line-height:1.6}}
.ext-table{{width:100%;border-collapse:collapse;font-size:.83rem}}
.ext-table th{{background:#f5f7fa;padding:8px 10px;text-align:left;font-size:.68rem;text-transform:uppercase;letter-spacing:.4px;color:#888;border-bottom:2px solid #e4e8ec}}
.ext-table td{{padding:9px 10px;border-bottom:1px solid #f0f0f0}}
.ext-table tr:hover td{{background:#fafbfc}}
@media(max-width:640px){{.hdr,.kpi-bar,.content{{padding-left:14px;padding-right:14px}}.kpi-bar{{gap:18px}}}}
</style>
</head>
<body>

<div class="hdr">
  <h1>FX Factor Fair Value</h1>
  <div class="sub">Lasso regression · 13 factor/style ETF ratios vs SPY · 10 EM+G10 currency pairs</div>
  <div class="meta">Data: Yahoo Finance (yfinance) · FRED · Generated: {today_str}</div>
</div>

<div class="kpi-bar">
  <div class="kpi">
    <span class="kpi-lbl">Currencies analyzed</span>
    <span class="kpi-val">{n_total}</span>
  </div>
  <div class="kpi">
    <span class="kpi-lbl">Overvalued vs model</span>
    <span class="kpi-val red">{n_rich}</span>
  </div>
  <div class="kpi">
    <span class="kpi-lbl">Undervalued vs model</span>
    <span class="kpi-val blue">{n_cheap}</span>
  </div>
  <div class="kpi">
    <span class="kpi-lbl">Median residual</span>
    <span class="kpi-val {med_color}">{med_sign}{med_res}%</span>
  </div>
</div>

<div class="content">

  <div class="method-note">
    <strong>Methodology:</strong> Lasso regression (α=0.9, 10-year window) maps 13 factor/style ETF ratios vs SPY
    to each FX rate. Residual = (actual − model) / actual × 100.
    Positive residual → currency overvalued relative to factor signals; negative → undervalued.<br>
    <strong>Factors:</strong> {factor_list}.
  </div>

  <div class="section-hdr">Residual Scoreboard</div>
  <div class="card">
    <div class="card-title">Today's Cheap/Rich vs Factor Model</div>
    <div class="card-note">Red = positive residual (overvalued) · Blue = negative residual (undervalued)</div>
    <div id="chart-bar"></div>
  </div>

  <div class="section-hdr">Signal Table</div>
  <div class="card">
    <div class="card-title">All Currencies — Ranked by Signal Strength</div>
    <div class="card-note">R² = model fit on 30% holdout · Residual = current deviation from fair value</div>
    {extremes_html}
  </div>

  <div class="section-hdr">Currency Explorer</div>
  <div class="card">
    <div class="card-title">Actual vs Fair Value Model — Full History</div>
    <div class="card-note">Select currency from dropdown · Right axis = residual % · Red dashed = model fair value</div>
    <div id="chart-explorer"></div>
<!-- fx-factor-commentary-start --><!-- fx-factor-commentary-end -->
  </div>

</div>

<script>
var bar_data      = {bar_json};
var explorer_data = {explorer_json};
Plotly.newPlot('chart-bar',      bar_data.data,      bar_data.layout,      {{responsive:true, displayModeBar:false}});
Plotly.newPlot('chart-explorer', explorer_data.data, explorer_data.layout, {{responsive:true, displayModeBar:true}});
</script>

</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    indexed_df, ratios = fetch_factor_data()
    fx_df = fetch_fred_fx()

    results = {}
    rows = []
    for ccy in FX_LABELS:
        if ccy not in fx_df.columns:
            continue
        print(f"  Fitting {ccy}…")
        res = fit_currency(ccy, indexed_df, fx_df, ratios)
        if res:
            results[ccy] = res
            rows.append({
                "currency": ccy,
                "actual":   res["actual"],
                "predicted": res["predicted"],
                "residual": res["residual"],
                "r2":       res["r2"],
            })

    summary = pd.DataFrame(rows).sort_values("residual", ascending=True).reset_index(drop=True)
    print(f"\nFitted {len(summary)} currencies")
    print(summary[["currency", "residual", "r2"]].to_string(index=False))

    html = generate_html(results, summary, today_str)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard → {OUTPUT_FILE}")

    summary_data = []
    for _, row in summary.iterrows():
        ccy = row["currency"]
        res = results[ccy]
        summary_data.append({
            "currency": ccy,
            "residual": round(float(res["residual"]), 2),
            "r2": round(float(res["r2"]), 3),
            "actual": round(float(res["actual"]), 4),
            "predicted": round(float(res["predicted"]), 4),
            "selected_vars": res["selected_vars"][:6],
        })
    summary_json_path = os.path.join(OUTPUT_DIR, "summary.json")
    with open(summary_json_path, "w") as f:
        json.dump(summary_data, f, indent=2)
    print(f"Summary JSON → {summary_json_path}")


if __name__ == "__main__":
    main()
