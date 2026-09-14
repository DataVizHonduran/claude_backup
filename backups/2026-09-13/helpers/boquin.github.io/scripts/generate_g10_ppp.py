"""
G10 Classic PPP Fair Value Generator

Relative-PPP model for EUR/USD + 8 other G10 pairs back to 1990. Self-contained
(no dependency on local fred_client/eurostat_client/oecd_client packages) so it
can run unattended in GitHub Actions — uses fredapi + plain requests instead.

EUR/USD is the one bespoke case: pre-1999 EUR/USD is synthetic, derived from
the Deutsche Mark/USD rate via the official irrevocable conversion rate
(1 EUR = 1.95583 DEM), fixed on 1998-12-31. Every other G10 pair has a single
continuous FRED spot-rate series back to 1971, so no splice is needed — only
a quote-direction normalization to market convention.

Non-US CPI is sourced from OECD's live SDMX prices API (not FRED's stale "MEI"
CPI mirrors). Filter pattern for the all-items index level:
"{AREA}.{FREQ}.N.CPI.IX._T.N._Z" — Japan needs the newer COICOP2018 dataflow
(its legacy COICOP99 series stopped in 2021-06); the rest use the legacy one.

Run from the repo root:
    python3 scripts/generate_g10_ppp.py
"""
import io
import itertools
import os
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from fredapi import Fred
from plotly.subplots import make_subplots

fred = Fred(api_key=os.environ.get("FRED_API_KEY"))

OUTPUT_DIR = "reports/g10-ppp"
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEM_PER_EUR = 1.95583
EURO_LAUNCH = "1999-01-01"

_LEGACY_PRICES = "DSD_PRICES@DF_PRICES_ALL"
_COICOP2018_PRICES = "DSD_PRICES_COICOP2018@DF_PRICES_C2018_ALL"

PAIRS = {
    "JPY": dict(fred_fx="EXJPUS", invert=True, oecd_area="JPN", oecd_flow=_COICOP2018_PRICES, freq="MS"),
    "GBP": dict(fred_fx="EXUSUK", invert=False, oecd_area="GBR", oecd_flow=_LEGACY_PRICES, freq="MS"),
    "CHF": dict(fred_fx="EXSZUS", invert=True, oecd_area="CHE", oecd_flow=_LEGACY_PRICES, freq="MS"),
    "CAD": dict(fred_fx="EXCAUS", invert=True, oecd_area="CAN", oecd_flow=_LEGACY_PRICES, freq="MS"),
    "AUD": dict(fred_fx="DEXUSAL", invert=False, oecd_area="AUS", oecd_flow=_LEGACY_PRICES, freq="QS"),
    "NZD": dict(fred_fx="DEXUSNZ", invert=False, oecd_area="NZL", oecd_flow=_LEGACY_PRICES, freq="QS"),
    "SEK": dict(fred_fx="EXSDUS", invert=True, oecd_area="SWE", oecd_flow=_LEGACY_PRICES, freq="MS"),
    "NOK": dict(fred_fx="EXNOUS", invert=True, oecd_area="NOR", oecd_flow=_LEGACY_PRICES, freq="MS"),
}
ALL_PAIRS = ["EUR"] + list(PAIRS)

# "Adjusted PPP" overlay: relative-PPP + terms of trade + productivity
# (Balassa-Samuelson proxy), annual frequency. Only pairs with genuinely
# current data on both factors are included:
#   - ToT: IMF ITG export/import *unit value* indices (value ÷ volume,
#     since several countries' published price indices stopped updating
#     years ago — Germany 2017, UK 2019, Japan 2021). Switzerland and
#     Norway report no ITG trade data at all; Sweden's volume index itself
#     stopped in 2021 (a real reporting gap, not a methodology fix).
#   - Productivity: World Bank GDP-per-person-employed (constant PPP$),
#     complete for all G10 countries but annual-only, 1991-2024.
# CHF, NOK (no ToT) and SEK (stale ToT) are excluded.
ADJUSTED_AREA = {"EUR": "DEU", "GBP": "GBR", "JPY": "JPN", "AUD": "AUS", "NZD": "NZL", "CAD": "CAN"}

# Market convention quotes these 5 as USD-base (USDJPY, USDCHF, USDCAD,
# USDSEK, USDNOK = foreign units per 1 USD); EUR/GBP/AUD/NZD already quote
# USD per 1 foreign unit. The model always works in USD-per-foreign terms
# internally so Misalignment stays currency-centric — this only affects display.
USD_BASE_PAIRS = {"JPY", "CHF", "CAD", "SEK", "NOK"}


def market_label(pair: str) -> str:
    return f"USD/{pair}" if pair in USD_BASE_PAIRS else f"{pair}/USD"


def to_market_convention(x, pair: str):
    return 1 / x if pair in USD_BASE_PAIRS else x


# ── Data fetch helpers (no local *_client packages) ─────────────────────────

def fred_series(series_id: str, freq: str, start: str) -> pd.Series:
    s = fred.get_series(series_id, observation_start=start)
    s.index = pd.to_datetime(s.index)
    return s.dropna().resample(freq).last()


def oecd_cpi_level(area: str, dataflow: str, freq: str, start: str = "1990-01") -> pd.Series:
    freq_code = "Q" if freq == "QS" else "M"
    url = (
        f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,{dataflow},1.0/"
        f"{area}.{freq_code}.N.CPI.IX._T.N._Z"
    )
    resp = requests.get(
        url,
        params={"format": "csvfilewithlabels", "dimensionAtObservation": "AllDimensions", "startPeriod": start},
        timeout=30,
    )
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"], format="mixed")
    df = df.set_index("TIME_PERIOD").sort_index()
    return df["OBS_VALUE"].astype(float).resample(freq).last()


def eurostat_hicp_ea19(geo: str = "EA19", coicop: str = "CP00", unit: str = "I15", start: str = "1996") -> pd.Series:
    """Eurostat HICP all-items index for the euro area, minimal JSON-stat parse."""
    url = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_midx"
    resp = requests.get(
        url, params={"format": "JSON", "geo": geo, "coicop": coicop, "unit": unit, "sinceTimePeriod": start},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    ids = data["id"]
    dims = data["dimension"]
    raw_values = data["value"]
    value_lookup = {int(k): v for k, v in raw_values.items()} if isinstance(raw_values, dict) else None

    def _get(i):
        return value_lookup.get(i) if value_lookup is not None else (raw_values[i] if i < len(raw_values) else None)

    dim_codes = []
    for dim_id in ids:
        cat = dims[dim_id]["category"]
        pos_to_code = {v: k for k, v in cat["index"].items()}
        dim_codes.append([pos_to_code[i] for i in range(len(pos_to_code))])

    rows = []
    for flat_idx, combo in enumerate(itertools.product(*dim_codes)):
        val = _get(flat_idx)
        if val is None:
            continue
        row = dict(zip(ids, combo))
        row["value"] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    time_col = next(c for c in df.columns if c.lower() in ("time_period", "time"))
    df[time_col] = pd.to_datetime(df[time_col])
    s = df.set_index(time_col)["value"].sort_index()
    return s.resample("MS").last()


def _imf_period_to_date(period: str) -> str:
    if "-Q" in period:
        y, q = period.split("-Q")
        return f"{y}-{(int(q) - 1) * 3 + 1:02d}-01"
    if "-M" in period:
        y, m = period.split("-M")
        return f"{y}-{m}-01"
    return f"{period}-01-01"


def imf_itg_series(area: str, indicator: str, transformation: str, freq: str = "A", start: str = "2000") -> pd.Series:
    url = f"https://api.imf.org/external/sdmx/2.1/data/IMF.STA,ITG,4.0.0/{area}.{indicator}.{transformation}.{freq}"
    resp = requests.get(url, headers={"Accept": "application/json"}, params={"startPeriod": start}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    struct = data["structure"]
    times = [v["id"] for v in next(d for d in struct["dimensions"]["observation"] if d["id"] == "TIME_PERIOD")["values"]]
    series_key = next(iter(data["dataSets"][0]["series"]))
    obs = data["dataSets"][0]["series"][series_key]["observations"]
    idx = pd.to_datetime([_imf_period_to_date(times[int(k)]) for k in obs.keys()])
    return pd.Series([float(v[0]) for v in obs.values()], index=idx).sort_index()


def _terms_of_trade_price(area: str) -> pd.Series:
    """IMF's own export/import price indices (EPI/MPI) — back to 1990, but several
    G10 countries stopped reporting these years ago (Germany 2017, UK 2018, Japan 2020)."""
    epi = imf_itg_series(area, "EPI", "FOB_IX", start="1990")
    mpi = imf_itg_series(area, "MPI", "CIF_IX", start="1990")
    return (epi / mpi).dropna()


def _terms_of_trade_unit_value(area: str) -> pd.Series:
    """Unit-value-index ToT = (export value / export volume) / (import value / import volume).

    Only available from 2005, but current — trade value/volume indices keep
    updating even where the published price indices (EPI/MPI) have stopped.
    """
    xg = imf_itg_series(area, "XG", "FOB_USD")
    xg_vi = imf_itg_series(area, "XG_VI", "FOB_IX")
    mg = imf_itg_series(area, "MG", "CIF_USD")
    mg_vi = imf_itg_series(area, "MG_VI", "CIF_IX")
    return ((xg / xg_vi) / (mg / mg_vi)).dropna()


def terms_of_trade(area: str) -> pd.Series:
    """Spliced ToT: 1990s-present where possible.

    Rescales the price-index series (long history, often stale) to the
    unit-value series's level using their overlap period's mean ratio
    (overlap is checked to be tight — e.g. USA std=0.002 on mean 0.649,
    AUS std=0.009 on mean 1.049 — confirming the two methods track the
    same underlying ToT dynamics), then splices: rescaled price-index
    before the unit-value series starts, unit-value (current) from then on.
    """
    price, uv = _terms_of_trade_price(area), _terms_of_trade_unit_value(area)
    common = price.index.intersection(uv.index)
    if len(common) >= 3:
        scale = (uv.loc[common] / price.loc[common]).mean()
        pre = price[price.index < uv.index.min()] * scale
        return pd.concat([pre, uv]).sort_index()
    return uv


def wb_productivity(area: str, start: str = "1990") -> pd.Series:
    """World Bank GDP per person employed, constant 2017 PPP$ (SL.GDP.PCAP.EM.KD)."""
    url = f"https://api.worldbank.org/v2/country/{area}/indicator/SL.GDP.PCAP.EM.KD"
    resp = requests.get(url, params={"format": "json", "per_page": "500", "date": f"{start}:2030"}, timeout=30)
    resp.raise_for_status()
    rows = resp.json()[1]
    s = pd.Series({pd.Timestamp(f"{r['date']}-01-01"): r["value"] for r in rows if r["value"] is not None})
    return s.sort_index()


# ── Fetch + model (mirrors eurusd_ppp.py) ────────────────────────────────────

def fetch_eur() -> pd.DataFrame:
    exgeus = fred_series("EXGEUS", "MS", "1990-01-01")
    exuseu = fred_series("EXUSEU", "MS", "1999-01-01")
    us_cpi = fred_series("CPIAUCSL", "MS", "1990-01-01")
    ea_cpi_oecd = fred_series("EA19CPHPTT01IXEBM", "MS", "1990-01-01")
    ea_cpi_eurostat = eurostat_hicp_ea19()

    synthetic_eurusd = DEM_PER_EUR / exgeus
    fx = pd.concat([synthetic_eurusd[:EURO_LAUNCH].iloc[:-1], exuseu]).sort_index()

    splice_month = "1996-01-01"
    scale = ea_cpi_eurostat.loc[splice_month] / ea_cpi_oecd.loc[splice_month]
    foreign_cpi = pd.concat([ea_cpi_oecd[:splice_month].iloc[:-1] * scale, ea_cpi_eurostat]).sort_index()

    df = pd.concat({"FX": fx, "US_CPI": us_cpi, "FOREIGN_CPI": foreign_cpi}, axis=1)
    return df.dropna()


def fetch_generic(pair: str) -> pd.DataFrame:
    cfg = PAIRS[pair]
    fx = fred_series(cfg["fred_fx"], cfg["freq"], "1990-01-01")
    if cfg["invert"]:
        fx = 1 / fx
    us_cpi = fred_series("CPIAUCSL", cfg["freq"], "1990-01-01")
    foreign_cpi = oecd_cpi_level(cfg["oecd_area"], cfg["oecd_flow"], cfg["freq"])

    df = pd.concat({"FX": fx, "US_CPI": us_cpi, "FOREIGN_CPI": foreign_cpi}, axis=1)
    return df.dropna()


def fetch_raw_data(pair: str) -> pd.DataFrame:
    return fetch_eur() if pair == "EUR" else fetch_generic(pair)


def compute_model(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ln_FX"] = np.log(out["FX"])
    out["ln_relP"] = np.log(out["US_CPI"]) - np.log(out["FOREIGN_CPI"])

    alpha = (out["ln_FX"] - out["ln_relP"]).mean()
    out["ln_FX_PPP"] = alpha + out["ln_relP"]
    out["FX_PPP"] = np.exp(out["ln_FX_PPP"])
    out["Misalignment"] = out["ln_FX"] - out["ln_FX_PPP"]
    out["Pct_Misalignment"] = (np.exp(out["Misalignment"]) - 1) * 100

    X = np.column_stack([np.ones(len(out)), out["ln_relP"]])
    y = out["ln_FX"].to_numpy()
    (ols_alpha, ols_beta), *_ = np.linalg.lstsq(X, y, rcond=None)

    m = out["Misalignment"]
    m_lag = m.shift(1)
    valid = m_lag.notna()
    X_ar = np.column_stack([np.ones(int(valid.sum())), m_lag[valid].to_numpy()])
    y_ar = m[valid].to_numpy()
    (ar_const, rho), *_ = np.linalg.lstsq(X_ar, y_ar, rcond=None)
    half_life = np.log(0.5) / np.log(rho) if 0 < rho < 1 else np.nan

    out.attrs.update(alpha=alpha, ols_alpha=ols_alpha, ols_beta=ols_beta, ar1_rho=rho, half_life_periods=half_life)
    return out


def compute_adjusted_model(raw: pd.DataFrame, area: str) -> pd.DataFrame | None:
    """Annual relative-PPP + terms of trade + productivity (Balassa-Samuelson) OLS fit.

    Unlike classic PPP (beta fixed at 1, one variable), there's no textbook fixed
    coefficient for ToT/productivity — all three coefficients are freely estimated.
    Frequency is forced to annual since World Bank productivity has no sub-annual data.
    """
    annual = raw[["FX", "US_CPI", "FOREIGN_CPI"]].resample("YS").last()
    tot_us = terms_of_trade("USA").resample("YS").last()
    tot_foreign = terms_of_trade(area).resample("YS").last()
    prod_us = wb_productivity("USA").resample("YS").last()
    prod_foreign = wb_productivity(area).resample("YS").last()

    df = pd.concat({
        "FX": annual["FX"], "US_CPI": annual["US_CPI"], "FOREIGN_CPI": annual["FOREIGN_CPI"],
        "ToT_US": tot_us, "ToT_FOREIGN": tot_foreign,
        "Prod_US": prod_us, "Prod_FOREIGN": prod_foreign,
    }, axis=1).dropna()
    if len(df) < 8:
        return None

    df["ln_FX"] = np.log(df["FX"])
    df["ln_relP"] = np.log(df["US_CPI"]) - np.log(df["FOREIGN_CPI"])
    df["ln_relToT"] = np.log(df["ToT_FOREIGN"]) - np.log(df["ToT_US"])
    df["ln_relProd"] = np.log(df["Prod_FOREIGN"]) - np.log(df["Prod_US"])

    X = np.column_stack([np.ones(len(df)), df["ln_relP"], df["ln_relToT"], df["ln_relProd"]])
    y = df["ln_FX"].to_numpy()
    (alpha, b_p, b_tot, b_prod), *_ = np.linalg.lstsq(X, y, rcond=None)

    df["ln_FX_ADJ"] = X @ np.array([alpha, b_p, b_tot, b_prod])
    df["FX_ADJ"] = np.exp(df["ln_FX_ADJ"])
    df["Pct_Misalignment_ADJ"] = (np.exp(df["ln_FX"] - df["ln_FX_ADJ"]) - 1) * 100
    df.attrs.update(alpha=alpha, beta_relP=b_p, beta_tot=b_tot, beta_prod=b_prod)
    return df


def plot_ppp(res: pd.DataFrame, pair: str, adjusted: pd.DataFrame | None = None) -> go.Figure:
    pct_dev = res["Pct_Misalignment"]
    label = market_label(pair)
    disp_fx = to_market_convention(res["FX"], pair)
    disp_fx_ppp = to_market_convention(res["FX_PPP"], pair)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
        row_heights=[0.6, 0.4],
        subplot_titles=(f"{label}: Actual vs. PPP-Implied", "Misalignment vs. PPP (%)"),
    )

    std_dev = pct_dev.std()
    band_upper = disp_fx_ppp * (1 + std_dev / 100)
    band_lower = disp_fx_ppp * (1 - std_dev / 100)

    fig.add_trace(go.Scatter(x=res.index, y=band_upper, name="±1 SD band", mode="lines",
                              line=dict(width=0), showlegend=False, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter(x=res.index, y=band_lower, name="±1 SD band", mode="lines",
                              line=dict(width=0), fill="tonexty", fillcolor="rgba(136,136,136,0.15)",
                              showlegend=True, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter(x=res.index, y=disp_fx, name=f"{label} (actual)", mode="lines",
                              line=dict(color="#0057A8", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=res.index, y=disp_fx_ppp, name=f"{label} (PPP-implied)", mode="lines",
                              line=dict(color="#F5A623", width=2, dash="dash")), row=1, col=1)

    if adjusted is not None:
        disp_fx_adj = to_market_convention(adjusted["FX_ADJ"], pair)
        fig.add_trace(go.Scatter(
            x=adjusted.index, y=disp_fx_adj, name=f"{label} (Adjusted PPP: ToT + productivity)",
            mode="lines+markers", line=dict(color="#7B2CBF", width=2, dash="dot"),
            marker=dict(size=4), visible="legendonly",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=adjusted.index, y=adjusted["Pct_Misalignment_ADJ"], name="Adjusted Misalignment (%)",
            mode="lines+markers", line=dict(color="#7B2CBF", width=2, dash="dot"),
            marker=dict(size=4), visible="legendonly",
        ), row=2, col=1)

    fig.add_trace(go.Scatter(x=res.index, y=pct_dev, name="Misalignment (%)", mode="lines",
                              line=dict(color="#00843D", width=2), fill="tozeroy"), row=2, col=1)
    fig.add_hline(y=0, line=dict(color="#888888", width=1, dash="dot"), row=2, col=1)

    horizon_buttons = [dict(count=n, label=f"{n}Y", step="year", stepmode="backward")
                        for n in (1, 2, 3, 5, 10, 15, 20, 30)]
    horizon_buttons.append(dict(step="all", label="All"))
    fig.update_xaxes(rangeselector=dict(buttons=horizon_buttons, bgcolor="#f0f0f0"), row=1, col=1)

    axis_title = f"{pair} per USD" if pair in USD_BASE_PAIRS else f"USD per {pair}"
    fig.update_yaxes(title_text=axis_title, gridcolor="#e5e5e5", row=1, col=1)
    fig.update_yaxes(title_text="Per cent", gridcolor="#e5e5e5", row=2, col=1)
    fig.update_xaxes(gridcolor="#e5e5e5")
    fig.update_layout(
        template="plotly_white", paper_bgcolor="white", plot_bgcolor="white", height=750,
        hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
        margin=dict(t=110),
    )
    return fig


def run(pair: str) -> dict:
    print(f"Fetching {pair}...")
    raw = fetch_raw_data(pair)
    res = compute_model(raw)
    label = market_label(pair)

    current_fx = to_market_convention(res["FX"].iloc[-1], pair)
    current_ppp = to_market_convention(res["FX_PPP"].iloc[-1], pair)
    misalignment = res["Pct_Misalignment"].iloc[-1]
    half_life = res.attrs["half_life_periods"]

    adjusted = None
    adj_misalignment = None
    adj_year = None
    if pair in ADJUSTED_AREA:
        try:
            adjusted = compute_adjusted_model(raw, ADJUSTED_AREA[pair])
        except Exception as e:
            print(f"  ! Adjusted PPP failed for {pair}: {e}")
        if adjusted is not None:
            adj_misalignment = adjusted["Pct_Misalignment_ADJ"].iloc[-1]
            adj_year = adjusted.index[-1].year
            print(f"  Adjusted PPP ({adj_year}): beta_ToT={adjusted.attrs['beta_tot']:.2f}, "
                  f"beta_Prod={adjusted.attrs['beta_prod']:.2f}, misalignment={adj_misalignment:+.1f}%")

    fig = plot_ppp(res, pair, adjusted)
    slug = pair.lower()
    fig.write_html(os.path.join(OUTPUT_DIR, f"{slug}.html"))
    print(f"  {label}: {current_fx:.4f} vs PPP {current_ppp:.4f} ({misalignment:+.1f}%)")

    return dict(
        pair=pair, slug=slug, label=label, current_fx=current_fx, current_ppp=current_ppp,
        misalignment=misalignment, half_life=half_life,
        half_life_unit="qtr" if PAIRS.get(pair, {}).get("freq") == "QS" else "mo",
        adj_misalignment=adj_misalignment, adj_year=adj_year,
    )


def build_index_html(rows: list[dict]) -> str:
    rows_sorted = sorted(rows, key=lambda r: r["misalignment"], reverse=True)

    table_rows = []
    for r in rows_sorted:
        hl = f"{r['half_life']:.0f} {r['half_life_unit']}" if pd.notna(r["half_life"]) else "n/a*"
        adj_cell = f'{r["adj_misalignment"]:+.1f}% ({r["adj_year"]})' if r.get("adj_misalignment") is not None else "—"
        table_rows.append(
            f'<tr><td><a class="pair-link" href="{r["slug"]}.html">{r["label"]}</a></td>'
            f'<td class="num">{r["current_fx"]:.4f}</td><td class="num">{r["current_ppp"]:.4f}</td>'
            f'<td class="num misalign">{r["misalignment"]:+.1f}%</td><td class="num">{hl}</td>'
            f'<td class="num">{adj_cell}</td></tr>'
        )

    grid_links = "\n      ".join(f'<a href="{r["slug"]}.html">{r["label"]}</a>' for r in rows)
    has_no_half_life = any(pd.isna(r["half_life"]) for r in rows)
    footnote = (
        "<br>*One or more pairs show an AR(1) coefficient on misalignment ≥1 over the full sample "
        "(no finite half-life) — the most pronounced PPP breakdowns in G10." if has_no_half_life else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>G10 Classic PPP Fair Value — boquin.xyz</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f7fa;color:#1a1a1a;font-size:14px}}
.hdr{{background:#1a3a2f;color:#fff;padding:24px 32px}}
.hdr h1{{font-size:1.5rem;font-weight:700;letter-spacing:-.4px}}
.hdr .sub{{font-size:.85rem;opacity:.75;margin-top:6px;max-width:760px;line-height:1.5}}
.hdr .meta{{font-size:.75rem;opacity:.55;margin-top:8px}}
.content{{padding:24px 32px;max-width:1100px;margin:0 auto}}
.card{{background:#fff;border:1px solid #e4e8ec;border-radius:10px;padding:18px 20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.card-title{{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:12px}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #eef1f4}}
th{{color:#666;font-weight:600;font-size:.75rem;text-transform:uppercase;letter-spacing:.4px}}
td.num{{text-align:right;font-family:'SF Mono',Consolas,monospace}}
a.pair-link{{color:#1a3a2f;font-weight:600;text-decoration:none}}
a.pair-link:hover{{text-decoration:underline}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}}
.grid a{{display:block;text-align:center;padding:14px 8px;border:1px solid #dfe4e8;border-radius:8px;background:#fafbfc;color:#1a3a2f;font-weight:700;text-decoration:none;transition:all .12s}}
.grid a:hover{{background:#1a3a2f;color:#fff;border-color:#1a3a2f}}
.note{{font-size:.78rem;color:#888;margin-top:10px;line-height:1.5}}
</style>
</head>
<body>

<div class="hdr">
  <h1>🧮 G10 Classic PPP Fair Value</h1>
  <div class="sub">Relative purchasing-power-parity model for EUR/USD + 8 other G10 pairs, back to 1990. PPP-implied rate is calibrated so mean misalignment = 0 over the full sample (beta fixed at 1); an unrestricted OLS fit and an AR(1) half-life of mean reversion are reported alongside. EUR, GBP, JPY, AUD, NZD, and CAD also have an <strong>Adjusted PPP</strong> variant (annual, OLS-fit relative PPP + terms of trade + productivity/Balassa-Samuelson) — toggle it on via the legend on each pair's chart.</div>
  <div class="meta">Sources: FRED spot FX, OECD live CPI (Eurostat HICP for the euro area), US CPI (CPIAUCSL), IMF trade unit values (ToT), World Bank GDP-per-worker (productivity) · Updated {date.today().isoformat()}</div>
</div>

<div class="content">

  <div class="card">
    <div class="card-title">Current Misalignment vs. PPP</div>
    <table>
      <thead><tr><th>Pair</th><th class="num">Current Rate</th><th class="num">PPP-Implied</th><th class="num">Misalignment</th><th class="num">Half-Life</th><th class="num">Adj. Misalignment</th></tr></thead>
      <tbody>
        {''.join(table_rows)}
      </tbody>
    </table>
    <div class="note">Negative misalignment = foreign currency cheap vs. PPP (USD rich).{footnote}<br>
    AUD/NZD run on quarterly CPI (no monthly series exists for either); half-life units differ accordingly (qtr vs. mo).<br>
    Adjusted Misalignment is annual (year shown) — CHF, NOK have no IMF trade-price data, SEK's has a reporting gap since 2021, so all three are excluded from the adjusted variant.</div>
  </div>

  <div class="card">
    <div class="card-title">Launch Pair Chart</div>
    <div class="grid">
      {grid_links}
    </div>
  </div>

</div>
</body>
</html>"""


if __name__ == "__main__":
    results = [run(p) for p in ALL_PAIRS]

    html = build_index_html(results)
    out_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(out_path, "w") as f:
        f.write(html)

    print(f"\nDashboard saved -> {os.path.abspath(out_path)}")
