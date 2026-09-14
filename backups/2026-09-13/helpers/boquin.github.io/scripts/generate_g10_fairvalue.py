"""
G10 FX Rates Fair Value Generator
Fetches 5Y bond yields + FX data, runs OLS fair-value models,
and generates a self-contained interactive HTML dashboard.

Run from the repo root:
    python3 scripts/generate_g10_fairvalue.py
"""

import datetime
from datetime import date
import sys
import io
import time
import pandas as pd
import numpy as np
import statsmodels.api as sm
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import json
import warnings
import requests
from fredapi import Fred

warnings.filterwarnings("ignore")

fred = Fred(api_key=os.environ.get("FRED_API_KEY"))

# ── Config ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "reports/g10-fairvalue"
YEARS = 20
FX_DATA_URL = "https://raw.githubusercontent.com/DataVizHonduran/EMFX_risk_diffusion/main/fx_data_raw.csv"

# Stooq tickers kept only for CHF/NZD current-day override
STOOQ_CURRENT = {
    "CHF": "5ychy.b",
    "NZD": "5ynzy.b",
}

# FX pair → non-USD rate currency
FX_TO_RATE = {
    "AUDUSD": "AUD",
    "NZDUSD": "NZD",
    "EURUSD": "EUR",
    "GBPUSD": "GBP",
    "USDCAD": "CAD",
    "USDCHF": "CHF",
    "USDJPY": "JPY",
    "USDNOK": "NOK",
    "USDSEK": "SEK",
}

# Pairs quoted as units of foreign per USD (residual sign is conventional)
USD_BASE_PAIRS = {"USDCAD", "USDCHF", "USDJPY", "USDNOK", "USDSEK"}

os.makedirs(OUTPUT_DIR, exist_ok=True)

start_dt = (datetime.datetime.now() - datetime.timedelta(days=365 * YEARS)).strftime("%Y%m%d")
end_dt = date.today().strftime("%Y%m%d")


# ── 1. Bond Yields ────────────────────────────────────────────────────────────
print("Fetching 5Y bond yields from central bank APIs...")

start_date = (datetime.datetime.now() - datetime.timedelta(days=365 * YEARS)).strftime("%Y-%m-%d")
end_date = date.today().strftime("%Y-%m-%d")
frames = {}

# USD — FRED DGS5 (daily 5Y Treasury)
try:
    s = fred.get_series("DGS5", observation_start=start_date, observation_end=end_date).dropna()
    frames["USD"] = s
    print("  ✓ USD (FRED DGS5)")
except Exception as e:
    print(f"  ✗ USD: {e}")

# EUR — ECB SDW yield curve 5Y spot rate
try:
    ecb_url = (
        "https://data-api.ecb.europa.eu/service/data/YC/"
        "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y"
        f"?startPeriod={start_date}&format=csvdata"
    )
    r = requests.get(ecb_url, timeout=30)
    r.raise_for_status()
    ecb_df = pd.read_csv(io.StringIO(r.text))
    ecb_df["date"] = pd.to_datetime(ecb_df["TIME_PERIOD"])
    ecb_df = ecb_df.set_index("date")["OBS_VALUE"].astype(float)
    frames["EUR"] = ecb_df
    print("  ✓ EUR (ECB SDW)")
except Exception as e:
    print(f"  ✗ EUR: {e}")

# CAD — Bank of Canada Valet API (5Y benchmark bond yield)
try:
    boc_url = (
        f"https://www.bankofcanada.ca/valet/observations/BD.CDN.5YR.DQ.YLD/json"
        f"?start_date={start_date}&end_date={end_date}"
    )
    r = requests.get(boc_url, timeout=30)
    r.raise_for_status()
    obs = r.json()["observations"]
    cad_data = {
        pd.Timestamp(o["d"]): float(o["BD.CDN.5YR.DQ.YLD"]["v"])
        for o in obs
        if o.get("BD.CDN.5YR.DQ.YLD", {}).get("v") not in (None, "", "nan")
    }
    frames["CAD"] = pd.Series(cad_data)
    print("  ✓ CAD (Bank of Canada)")
except Exception as e:
    print(f"  ✗ CAD: {e}")

# AUD — RBA F2 table (5Y Commonwealth Government bond, column index 2)
try:
    rba_url = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"
    r = requests.get(rba_url, timeout=30)
    r.raise_for_status()
    rba_df = pd.read_csv(io.StringIO(r.text), skiprows=1, index_col=0, parse_dates=True)
    rba_series = pd.to_numeric(rba_df.iloc[:, 2], errors="coerce").dropna()
    rba_series.index = pd.to_datetime(rba_series.index, dayfirst=True)
    rba_series = rba_series[rba_series.index >= pd.Timestamp(start_date)]
    frames["AUD"] = rba_series
    print("  ✓ AUD (RBA F2)")
except Exception as e:
    print(f"  ✗ AUD: {e}")

# JPY — Japan MOF historical JGB rates (5Y = column index 4)
try:
    mof_url = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; research/1.0)",
        "Referer": "https://www.mof.go.jp/english/",
    }
    r = requests.get(mof_url, headers=headers, timeout=30)
    r.raise_for_status()
    mof_df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True, encoding="utf-8")
    mof_series = pd.to_numeric(mof_df.iloc[:, 4], errors="coerce").dropna()
    mof_series.index = pd.to_datetime(mof_series.index, format="%Y/%m/%d", errors="coerce")
    mof_series = mof_series.dropna()
    mof_series = mof_series[mof_series.index >= pd.Timestamp(start_date)]
    frames["JPY"] = mof_series
    print("  ✓ JPY (Japan MOF)")
except Exception as e:
    print(f"  ✗ JPY: {e}")

# GBP — Riksbank API (UK 5Y gilt)
try:
    rb_url = f"https://api.riksbank.se/swea/v1/Observations/GBGVB5Y/{start_date}/{end_date}"
    r = requests.get(rb_url, timeout=30)
    r.raise_for_status()
    rb_data = {pd.Timestamp(o["date"]): float(o["value"]) for o in r.json() if o.get("value") is not None}
    frames["GBP"] = pd.Series(rb_data)
    print("  ✓ GBP (Riksbank GBGVB5Y)")
except Exception as e:
    print(f"  ✗ GBP: {e}")

time.sleep(0.5)

# SEK — Riksbank API (Sweden 5Y)
try:
    rb_url = f"https://api.riksbank.se/swea/v1/Observations/SEGVB5YC/{start_date}/{end_date}"
    r = requests.get(rb_url, timeout=30)
    r.raise_for_status()
    rb_data = {pd.Timestamp(o["date"]): float(o["value"]) for o in r.json() if o.get("value") is not None}
    frames["SEK"] = pd.Series(rb_data)
    print("  ✓ SEK (Riksbank SEGVB5YC)")
except Exception as e:
    print(f"  ✗ SEK: {e}")

time.sleep(0.5)

# NOK — Riksbank API (Norway 10Y as proxy for 5Y)
try:
    rb_url = f"https://api.riksbank.se/swea/v1/Observations/NOGVB10Y/{start_date}/{end_date}"
    r = requests.get(rb_url, timeout=30)
    r.raise_for_status()
    rb_data = {pd.Timestamp(o["date"]): float(o["value"]) for o in r.json() if o.get("value") is not None}
    frames["NOK"] = pd.Series(rb_data)
    print("  ✓ NOK (Riksbank NOGVB10Y)")
except Exception as e:
    print(f"  ✗ NOK: {e}")

# CHF — FRED monthly (10Y) forward-filled to daily + Stooq current override
try:
    chf_monthly = fred.get_series("IRLTLT01CHM156N", observation_start=start_date, observation_end=end_date).dropna()
    chf_daily = chf_monthly.resample("D").interpolate(method="linear")
    # Override today's value with Stooq current quote
    try:
        stooq_url = f"https://stooq.com/q/l/?s={STOOQ_CURRENT['CHF']}&f=sd2t2ohlc&h&e=csv"
        r = requests.get(stooq_url, timeout=10)
        stooq_df = pd.read_csv(io.StringIO(r.text))
        if not stooq_df.empty and "Close" in stooq_df.columns:
            chf_today = float(stooq_df["Close"].iloc[0])
            chf_daily[pd.Timestamp(date.today())] = chf_today
    except Exception:
        pass
    frames["CHF"] = chf_daily
    print("  ✓ CHF (FRED monthly + Stooq current)")
except Exception as e:
    print(f"  ✗ CHF: {e}")

# NZD — FRED monthly (10Y) forward-filled to daily + Stooq current override
try:
    nzd_monthly = fred.get_series("IRLTLT01NZM156N", observation_start=start_date, observation_end=end_date).dropna()
    nzd_daily = nzd_monthly.resample("D").interpolate(method="linear")
    # Override today's value with Stooq current quote
    try:
        stooq_url = f"https://stooq.com/q/l/?s={STOOQ_CURRENT['NZD']}&f=sd2t2ohlc&h&e=csv"
        r = requests.get(stooq_url, timeout=10)
        stooq_df = pd.read_csv(io.StringIO(r.text))
        if not stooq_df.empty and "Close" in stooq_df.columns:
            nzd_today = float(stooq_df["Close"].iloc[0])
            nzd_daily[pd.Timestamp(date.today())] = nzd_today
    except Exception:
        pass
    frames["NZD"] = nzd_daily
    print("  ✓ NZD (FRED monthly + Stooq current)")
except Exception as e:
    print(f"  ✗ NZD: {e}")

df_rates = pd.DataFrame(frames).sort_index()
df_rates = df_rates.apply(pd.to_numeric, errors="coerce").interpolate(method="linear")
df_rates.index = pd.to_datetime(df_rates.index)


# ── 2. FX Data ────────────────────────────────────────────────────────────────
print("\nFetching FX data...")
df_fx_raw = pd.read_csv(FX_DATA_URL, index_col=0, parse_dates=True)
df_fx_raw = df_fx_raw.apply(pd.to_numeric, errors="coerce")

fx_cols = {}
for fx_pair in FX_TO_RATE:
    base = fx_pair[:3]
    # EUR/GBP/AUD/NZD stored as USD per 1 unit base (e.g. EURUSD ≈ 1.05)
    # USD-base pairs stored as units per 1 USD (e.g. USDJPY ≈ 150)
    col = base if base in ["EUR", "GBP", "AUD", "NZD"] else fx_pair.replace("USD", "")
    if col in df_fx_raw.columns:
        fx_cols[fx_pair] = df_fx_raw[col]
    else:
        print(f"  ✗ {fx_pair}: column '{col}' not found in FX CSV")

df_fx = pd.DataFrame(fx_cols).sort_index()
df_fx.index = pd.to_datetime(df_fx.index)
df_fx = df_fx.apply(pd.to_numeric, errors="coerce").interpolate(method="linear")

# Align on intersection
df_fx, df_rates = df_fx.align(df_rates, join="inner", axis=0)

if df_fx.empty or df_rates.empty:
    print("\nNo data after alignment — skipping run.")
    sys.exit(0)

print(f"\nData aligned: {len(df_fx)} rows  |  {df_fx.index[0].date()} → {df_fx.index[-1].date()}")


# ── 3. Rate Spreads (USD minus foreign) ──────────────────────────────────────
for ccy in [c for c in df_rates.columns if c != "USD"]:
    df_rates[f"USD{ccy}"] = df_rates["USD"] - df_rates[ccy]


# ── 4. OLS Model: FX ~ All G10 Rate Spreads ──────────────────────────────────
print("\nRunning multi-factor OLS models...")
ndays = 252 * YEARS
ols_results = {}
residuals_dict = {}

for fx_pair, rate_ccy in FX_TO_RATE.items():
    if fx_pair not in df_fx.columns:
        continue
    try:
        y = df_fx[fx_pair].tail(ndays).dropna()
        X = df_rates.drop(columns=[rate_ccy], errors="ignore").tail(ndays).loc[y.index].copy()
        # Drop rows where X or y has NaN/inf
        X = X.replace([np.inf, -np.inf], np.nan)
        valid = X.notna().all(axis=1) & y.notna()
        y, X = y[valid], X[valid]
        X = sm.add_constant(X)
        model = sm.OLS(y, X).fit()
        pred = model.predict(X)
        resid = (y - pred) / y

        residuals_dict[fx_pair] = pd.Series(resid.values, index=y.index)
        ols_results[fx_pair] = {
            "actual": y.values.tolist(),
            "predicted": pred.values.tolist(),
            "residuals": resid.values.tolist(),
            "dates": y.index.strftime("%Y-%m-%d").tolist(),
            "r_squared": round(model.rsquared, 4),
        }
        print(f"  ✓ {fx_pair}  R²={model.rsquared:.3f}")
    except Exception as e:
        print(f"  ✗ {fx_pair}: {e}")

# ── 5. Residuals Summary ─────────────────────────────────────────────────────
residuals_summary = {}
for fx_pair, resids in residuals_dict.items():
    latest = float(resids.iloc[-1])
    # For USD-base pairs, positive residual means USD expensive → flip sign for "USD richness"
    sign = -1 if fx_pair in USD_BASE_PAIRS else 1
    residuals_summary[fx_pair] = {
        "latest": latest,
        "latest_pct": round(latest * 100, 2),
        "p90": float(np.percentile(resids.values, 90)),
        "p10": float(np.percentile(resids.values, 10)),
        "mean": float(np.mean(resids.values)),
        "std": float(np.std(resids.values)),
        "z_score": round((latest - float(np.mean(resids.values))) / float(np.std(resids.values)), 2),
        "usd_richness_sign": sign,
    }


# ── 6. Annual Fair Value Bands ───────────────────────────────────────────────
print("\nComputing annual fair value bands...")
fair_value_bands = {}
for fx_pair, rate_ccy in FX_TO_RATE.items():
    if fx_pair not in df_fx.columns or rate_ccy not in df_rates.columns:
        continue
    df_tmp = pd.DataFrame({"fx": df_fx[fx_pair], "rate": df_rates[rate_ccy]}).dropna()
    df_tmp["year"] = df_tmp.index.year
    yearly_fv = {}
    for year, grp in df_tmp.groupby("year"):
        if len(grp) < 20:
            continue
        X = sm.add_constant(grp["rate"])
        mdl = sm.OLS(grp["fx"], X).fit()
        fv = mdl.params["const"] + mdl.params["rate"] * grp["rate"].iloc[-1]
        yearly_fv[int(year)] = round(float(fv), 6)

    fv_vals = list(yearly_fv.values())
    mean_fv = float(np.mean(fv_vals))
    std_fv = float(np.std(fv_vals))

    last_year = int(df_tmp.index.year.max())
    last_yr_dates = df_fx.index[df_fx.index.year == last_year].strftime("%Y-%m-%d").tolist()

    fair_value_bands[fx_pair] = {
        "mean_fv": round(mean_fv, 6),
        "std_fv": round(std_fv, 6),
        "upper2": round(mean_fv + 2 * std_fv, 6),
        "upper1": round(mean_fv + std_fv, 6),
        "lower1": round(mean_fv - std_fv, 6),
        "lower2": round(mean_fv - 2 * std_fv, 6),
        "last_year_dates": last_yr_dates,
        "yearly_fv": yearly_fv,
    }
    print(f"  ✓ {fx_pair}  FV={mean_fv:.4f} ± {std_fv:.4f}")


# ── 7. USD Misvaluation Index ─────────────────────────────────────────────────
# residuals_dict values are now pd.Series with DatetimeIndex
residuals_df = pd.DataFrame(residuals_dict)
# Flip sign so positive = USD is expensive across the board
for pair in USD_BASE_PAIRS:
    if pair in residuals_df.columns:
        residuals_df[pair] = residuals_df[pair] * -1
for pair in ["AUDUSD", "NZDUSD", "EURUSD", "GBPUSD"]:
    if pair in residuals_df.columns:
        residuals_df[pair] = residuals_df[pair] * -1

avg_misval = residuals_df.mean(axis=1) * 100  # in %

misval_payload = {
    "dates": avg_misval.index.strftime("%Y-%m-%d").tolist(),
    "values": [round(v, 4) for v in avg_misval.tolist()],
}


# ── 8. Assemble per-pair payload ─────────────────────────────────────────────
pair_payload = {}
for fx_pair in FX_TO_RATE:
    if fx_pair not in ols_results:
        continue
    all_dates = df_fx.index.strftime("%Y-%m-%d").tolist()
    all_prices = [round(v, 6) if not np.isnan(v) else None for v in df_fx[fx_pair].tolist()]
    pair_payload[fx_pair] = {
        "ols": ols_results[fx_pair],
        "summary": residuals_summary.get(fx_pair, {}),
        "fair_value": fair_value_bands.get(fx_pair, {}),
        "all_dates": all_dates,
        "all_prices": all_prices,
    }


# ── 9. Build HTML ─────────────────────────────────────────────────────────────
last_updated = date.today().strftime("%B %d, %Y")

DATA_JSON = json.dumps(
    {
        "summary": residuals_summary,
        "misval": misval_payload,
        "pairs": pair_payload,
        "last_updated": last_updated,
        "pairs_order": list(FX_TO_RATE.keys()),
    },
    allow_nan=False,
)

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>G10 FX Rates Fair Value</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22253a;
    --border: #2d3148;
    --accent: #6366f1;
    --accent2: #818cf8;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #f59e0b;
    --text: #e2e8f0;
    --muted: #94a3b8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; }}
  header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; }}
  header h1 {{ font-size: 1.25rem; font-weight: 700; color: var(--accent2); }}
  header .meta {{ color: var(--muted); font-size: 0.8rem; }}
  .tabs {{ display: flex; gap: 4px; padding: 16px 32px 0; border-bottom: 1px solid var(--border); background: var(--surface); }}
  .tab {{ padding: 8px 20px; border-radius: 6px 6px 0 0; cursor: pointer; color: var(--muted); border: 1px solid transparent; border-bottom: none; transition: all .2s; font-weight: 500; }}
  .tab:hover {{ color: var(--text); background: var(--surface2); }}
  .tab.active {{ color: var(--accent2); border-color: var(--border); background: var(--bg); }}
  .view {{ display: none; padding: 24px 32px; }}
  .view.active {{ display: block; }}
  .section-title {{ font-size: 0.75rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; margin-bottom: 12px; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .chart-full {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
  .scoreboard {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; margin-bottom: 20px; }}
  .score-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; cursor: pointer; transition: border-color .2s; }}
  .score-card:hover {{ border-color: var(--accent); }}
  .score-card.rich {{ border-left: 3px solid var(--red); }}
  .score-card.cheap {{ border-left: 3px solid var(--green); }}
  .score-card .pair {{ font-size: 0.85rem; font-weight: 600; color: var(--text); margin-bottom: 4px; }}
  .score-card .residual {{ font-size: 1.2rem; font-weight: 700; }}
  .score-card .zscore {{ font-size: 0.75rem; color: var(--muted); }}
  .pair-selector {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
  .pair-btn {{ padding: 6px 14px; border-radius: 20px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); cursor: pointer; font-size: 0.8rem; transition: all .2s; }}
  .pair-btn:hover, .pair-btn.active {{ background: var(--accent); border-color: var(--accent); color: white; }}
  .metric-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }}
  .metric {{ background: var(--surface2); border-radius: 6px; padding: 10px 14px; }}
  .metric .label {{ font-size: 0.7rem; color: var(--muted); margin-bottom: 4px; text-transform: uppercase; }}
  .metric .value {{ font-size: 1.1rem; font-weight: 600; }}
  .red {{ color: var(--red); }} .green {{ color: var(--green); }} .yellow {{ color: var(--yellow); }}
  @media (max-width: 768px) {{
    .grid2 {{ grid-template-columns: 1fr; }}
    .metric-row {{ grid-template-columns: repeat(2, 1fr); }}
    header, .tabs, .view {{ padding-left: 16px; padding-right: 16px; }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>G10 FX Rates Fair Value</h1>
    <div style="color:var(--muted);font-size:.75rem;margin-top:2px;">OLS fair-value model using 5Y rate differentials · 20yr history</div>
  </div>
  <div class="meta">Updated: {last_updated}</div>
</header>

<div class="tabs">
  <div class="tab active" onclick="switchTab('summary')">Overview</div>
  <div class="tab" onclick="switchTab('pair')">Pair Analysis</div>
  <div class="tab" onclick="switchTab('fairvalue')">Fair Value Bands</div>
</div>

<!-- ── SUMMARY VIEW ── -->
<div id="view-summary" class="view active">
  <p class="section-title">USD Misvaluation Index — average residual across G10 pairs (positive = USD expensive)</p>
  <div class="chart-full" id="misval-chart" style="height:280px;"></div>

  <p class="section-title">Latest Residual vs Historical Range (10th–90th pct)</p>
  <div class="chart-full" id="residual-bar" style="height:340px;"></div>

  <p class="section-title">Pair Scoreboard — click a card to open pair analysis</p>
  <div class="scoreboard" id="scoreboard"></div>
</div>

<!-- ── PAIR VIEW ── -->
<div id="view-pair" class="view">
  <div class="pair-selector" id="pair-selector"></div>
  <div class="metric-row" id="pair-metrics"></div>
  <div class="grid2">
    <div class="card" id="actual-pred-chart" style="height:320px;"></div>
    <div class="card" id="residual-ts-chart" style="height:320px;"></div>
  </div>
</div>

<!-- ── FAIR VALUE BANDS VIEW ── -->
<div id="view-fairvalue" class="view">
  <div class="pair-selector" id="fv-pair-selector"></div>
  <div class="card" id="fv-chart" style="height:420px;"></div>
</div>

<script>
const DATA = {DATA_JSON};

const PAIRS = DATA.pairs_order;
let activePair = PAIRS[0];
let activeFVPair = PAIRS[0];

// ── Plotly theme ──────────────────────────────────────────────────────────────
const LAYOUT_BASE = {{
  paper_bgcolor: 'transparent',
  plot_bgcolor: 'transparent',
  font: {{ color: '#e2e8f0', size: 11 }},
  margin: {{ l: 50, r: 20, t: 30, b: 40 }},
  xaxis: {{ gridcolor: '#2d3148', zerolinecolor: '#2d3148' }},
  yaxis: {{ gridcolor: '#2d3148', zerolinecolor: '#2d3148' }},
  legend: {{ bgcolor: 'transparent', font: {{ size: 10 }} }},
}};

const CFG = {{ responsive: true, displayModeBar: false }};

// ── Tab switcher ───────────────────────────────────────────────────────────────
function switchTab(name) {{
  document.querySelectorAll('.tab').forEach((t, i) => {{
    const names = ['summary','pair','fairvalue'];
    t.classList.toggle('active', names[i] === name);
  }});
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  if (name === 'pair') renderPairView(activePair);
  if (name === 'fairvalue') renderFVView(activeFVPair);
}}

// ── Summary: Misvaluation Index ───────────────────────────────────────────────
function renderMisval() {{
  const d = DATA.misval;
  const vals = d.values;
  const colors = vals.map(v => v > 0 ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)');
  Plotly.newPlot('misval-chart', [
    {{
      x: d.dates, y: d.values, type: 'scatter', mode: 'lines',
      line: {{ color: '#818cf8', width: 1.5 }},
      fill: 'tozeroy',
      fillcolor: 'rgba(99,102,241,0.1)',
      name: 'USD Misvaluation %',
    }},
    {{
      x: d.dates, y: Array(d.dates.length).fill(0),
      mode: 'lines', line: {{ color: '#2d3148', width: 1, dash: 'dot' }},
      showlegend: false,
    }}
  ], {{
    ...LAYOUT_BASE,
    margin: {{ l: 50, r: 20, t: 20, b: 40 }},
    yaxis: {{ ...LAYOUT_BASE.yaxis, ticksuffix: '%', title: '% misval' }},
    annotations: [{{
      x: d.dates[d.dates.length - 1],
      y: vals[vals.length - 1],
      text: vals[vals.length - 1].toFixed(2) + '%',
      showarrow: false,
      xanchor: 'right',
      font: {{ color: vals[vals.length - 1] > 0 ? '#ef4444' : '#22c55e', size: 12, weight: 700 }}
    }}]
  }}, CFG);
}}

// ── Summary: Residual Bar Chart ───────────────────────────────────────────────
function renderResidualBar() {{
  const s = DATA.summary;
  const pairs = Object.keys(s).sort((a, b) => s[a].latest_pct - s[b].latest_pct);
  const latest = pairs.map(p => s[p].latest_pct);
  const p90 = pairs.map(p => s[p].p90 * 100);
  const p10 = pairs.map(p => s[p].p10 * 100);
  const barColors = latest.map(v => v > 0 ? '#ef4444' : '#22c55e');

  Plotly.newPlot('residual-bar', [
    {{
      x: pairs, y: latest, type: 'bar', name: 'Latest residual',
      marker: {{ color: barColors }},
    }},
    {{
      x: pairs, y: p90, type: 'scatter', mode: 'markers',
      name: '90th pct', marker: {{ color: '#ef4444', symbol: 'triangle-up', size: 10 }},
    }},
    {{
      x: pairs, y: p10, type: 'scatter', mode: 'markers',
      name: '10th pct', marker: {{ color: '#22c55e', symbol: 'triangle-down', size: 10 }},
    }},
  ], {{
    ...LAYOUT_BASE,
    margin: {{ l: 50, r: 20, t: 20, b: 40 }},
    yaxis: {{ ...LAYOUT_BASE.yaxis, ticksuffix: '%', title: 'Residual %' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
  }}, CFG);
}}

// ── Summary: Scoreboard ───────────────────────────────────────────────────────
function renderScoreboard() {{
  const s = DATA.summary;
  const el = document.getElementById('scoreboard');
  el.innerHTML = '';
  const pairs = Object.keys(s).sort((a,b) => s[a].latest_pct - s[b].latest_pct);
  pairs.forEach(pair => {{
    const d = s[pair];
    const isRich = d.latest_pct > 0;
    const color = isRich ? '#ef4444' : '#22c55e';
    const card = document.createElement('div');
    card.className = 'score-card ' + (isRich ? 'rich' : 'cheap');
    card.innerHTML = `
      <div class="pair">${{pair}}</div>
      <div class="residual" style="color:${{color}}">${{d.latest_pct > 0 ? '+' : ''}}${{d.latest_pct.toFixed(2)}}%</div>
      <div class="zscore">Z-score: ${{d.z_score > 0 ? '+' : ''}}${{d.z_score.toFixed(1)}}</div>
    `;
    card.onclick = () => {{ activePair = pair; switchTab('pair'); }};
    el.appendChild(card);
  }});
}}

// ── Pair Selector Buttons ─────────────────────────────────────────────────────
function buildPairSelector(containerId, activeVar, onSelect) {{
  const el = document.getElementById(containerId);
  el.innerHTML = '';
  PAIRS.forEach(pair => {{
    if (!DATA.pairs[pair]) return;
    const btn = document.createElement('div');
    btn.className = 'pair-btn' + (pair === activeVar ? ' active' : '');
    btn.textContent = pair;
    btn.id = containerId + '-' + pair;
    btn.onclick = () => onSelect(pair);
    el.appendChild(btn);
  }});
}}

function setActivePairBtn(containerId, pair) {{
  document.querySelectorAll('#' + containerId + ' .pair-btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById(containerId + '-' + pair);
  if (btn) btn.classList.add('active');
}}

// ── Pair View ─────────────────────────────────────────────────────────────────
function renderPairView(pair) {{
  activePair = pair;
  if (!DATA.pairs[pair]) return;
  buildPairSelector('pair-selector', pair, p => renderPairView(p));
  setActivePairBtn('pair-selector', pair);
  const d = DATA.pairs[pair];
  const s = d.summary;

  // Metrics
  const color = s.latest_pct > 0 ? 'red' : 'green';
  const zColor = Math.abs(s.z_score) > 2 ? 'red' : Math.abs(s.z_score) > 1 ? 'yellow' : 'green';
  document.getElementById('pair-metrics').innerHTML = `
    <div class="metric"><div class="label">Latest Residual</div><div class="value ${{color}}">${{s.latest_pct > 0 ? '+' : ''}}${{s.latest_pct.toFixed(2)}}%</div></div>
    <div class="metric"><div class="label">Z-Score</div><div class="value ${{zColor}}">${{s.z_score > 0 ? '+' : ''}}${{s.z_score.toFixed(2)}}</div></div>
    <div class="metric"><div class="label">Model R²</div><div class="value">${{d.ols.r_squared}}</div></div>
    <div class="metric"><div class="label">10th / 90th pct</div><div class="value" style="font-size:.9rem">${{(s.p10*100).toFixed(2)}}% / ${{(s.p90*100).toFixed(2)}}%</div></div>
  `;

  // Actual vs Predicted
  const ols = d.ols;
  Plotly.newPlot('actual-pred-chart', [
    {{ x: ols.dates, y: ols.actual, mode: 'lines', name: 'Actual', line: {{ color: '#818cf8', width: 1.5 }} }},
    {{ x: ols.dates, y: ols.predicted, mode: 'lines', name: 'Predicted', line: {{ color: '#f59e0b', width: 1.5, dash: 'dash' }} }},
  ], {{
    ...LAYOUT_BASE,
    title: {{ text: pair + ' · Actual vs Predicted', font: {{ size: 12 }} }},
    margin: {{ l: 50, r: 10, t: 35, b: 40 }},
  }}, CFG);

  // Residuals Time Series
  const resids = ols.residuals.map(v => v * 100);
  const resColors = resids.map(v => v > 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)');
  Plotly.newPlot('residual-ts-chart', [
    {{
      x: ols.dates, y: resids, type: 'scatter', mode: 'lines',
      fill: 'tozeroy',
      line: {{ color: '#6366f1', width: 1 }},
      fillcolor: 'rgba(99,102,241,0.15)',
      name: 'Residual %',
    }},
    {{
      x: ols.dates, y: Array(ols.dates.length).fill(s.p90 * 100),
      mode: 'lines', line: {{ color: '#ef4444', width: 1, dash: 'dot' }},
      name: '90th pct',
    }},
    {{
      x: ols.dates, y: Array(ols.dates.length).fill(s.p10 * 100),
      mode: 'lines', line: {{ color: '#22c55e', width: 1, dash: 'dot' }},
      name: '10th pct',
    }},
  ], {{
    ...LAYOUT_BASE,
    title: {{ text: pair + ' · Residual %', font: {{ size: 12 }} }},
    margin: {{ l: 50, r: 10, t: 35, b: 40 }},
    yaxis: {{ ...LAYOUT_BASE.yaxis, ticksuffix: '%' }},
  }}, CFG);
}}

// ── Fair Value Bands View ─────────────────────────────────────────────────────
function renderFVView(pair) {{
  activeFVPair = pair;
  if (!DATA.pairs[pair]) return;
  buildPairSelector('fv-pair-selector', pair, p => renderFVView(p));
  setActivePairBtn('fv-pair-selector', pair);

  const d = DATA.pairs[pair];
  const fv = d.fair_value;
  const all_dates = d.all_dates;
  const all_prices = d.all_prices;

  const traces = [
    {{
      x: all_dates, y: all_prices, mode: 'lines', name: pair,
      line: {{ color: '#818cf8', width: 1.5 }},
    }},
  ];

  if (fv && fv.last_year_dates && fv.last_year_dates.length) {{
    const n = fv.last_year_dates.length;
    // ±2σ outer band — amber tint with visible border
    traces.push({{
      x: [...fv.last_year_dates, ...fv.last_year_dates.slice().reverse()],
      y: [...Array(n).fill(fv.upper2), ...Array(n).fill(fv.lower2)],
      fill: 'toself', fillcolor: 'rgba(245,158,11,0.12)',
      line: {{ color: 'rgba(245,158,11,0.5)', width: 1 }}, name: '±2σ', showlegend: true,
    }});
    // ±1σ inner band — teal tint with visible border
    traces.push({{
      x: [...fv.last_year_dates, ...fv.last_year_dates.slice().reverse()],
      y: [...Array(n).fill(fv.upper1), ...Array(n).fill(fv.lower1)],
      fill: 'toself', fillcolor: 'rgba(20,184,166,0.18)',
      line: {{ color: 'rgba(20,184,166,0.6)', width: 1 }}, name: '±1σ', showlegend: true,
    }});
    // Mean fair value — bright solid line
    traces.push({{
      x: fv.last_year_dates,
      y: Array(n).fill(fv.mean_fv),
      mode: 'lines', line: {{ color: '#facc15', width: 2 }},
      name: 'Mean Fair Value',
    }});
  }}

  Plotly.newPlot('fv-chart', traces, {{
    ...LAYOUT_BASE,
    title: {{ text: pair + ' · Annual Fair Value Bands (current year)', font: {{ size: 13 }} }},
    margin: {{ l: 55, r: 20, t: 45, b: 40 }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.08 }},
    xaxis: {{ ...LAYOUT_BASE.xaxis, range: ['2016-01-01', all_dates[all_dates.length - 1]] }},
  }}, CFG);
}}

// ── Init ──────────────────────────────────────────────────────────────────────
renderMisval();
renderResidualBar();
renderScoreboard();
</script>
</body>
</html>"""

out_path = os.path.join(OUTPUT_DIR, "index.html")
with open(out_path, "w") as f:
    f.write(HTML)

print(f"\n✅ Dashboard saved → {os.path.abspath(out_path)}")
