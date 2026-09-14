"""Classic relative-PPP model for G10/USD pairs, 1990-present.

EUR/USD is the one bespoke case: pre-1999 EUR/USD is synthetic, derived
from the Deutsche Mark/USD rate via the official irrevocable conversion
rate (1 EUR = 1.95583 DEM), fixed on 1998-12-31 (FRED itself derives
EXGEUS the same way for dates >= 1999). Every other G10 pair has a single
continuous FRED spot-rate series back to 1971, so no splice is needed —
only a quote-direction normalization (USD per 1 unit of foreign currency).

Non-US CPI is sourced from OECD's live SDMX prices API rather than FRED's
"MEI" CPI mirrors, which are stale for most non-US countries (some stop
updating as early as 2021). Filter pattern for the all-items index level:
"{AREA}.{FREQ}.N.CPI.IX._T.N._Z" — Japan needs the newer COICOP2018
dataflow (its legacy COICOP99 series stopped in 2021-06); the rest use
the legacy dataflow, which is current.
"""
import argparse

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# requests 2.34's models.py only imports HTTPAdapter/RequestsCookieJar/CookieJar
# under `if TYPE_CHECKING:`, but cattrs's MRO type-hint resolution (via
# requests_cache, walking Response's annotations) needs them at runtime.
# Inject the same names get_type_hints() will look for before any cached
# request fires.
import http.cookiejar
import requests.models
from requests.adapters import HTTPAdapter
from requests.cookies import RequestsCookieJar
requests.models.RequestsCookieJar = RequestsCookieJar
requests.models.HTTPAdapter = HTTPAdapter
requests.models.CookieJar = http.cookiejar.CookieJar

from eurostat_client import EurostatClient
from fred_client import FredClient
from oecd_client import OecdClient

DEM_PER_EUR = 1.95583
EURO_LAUNCH = "1999-01-01"

_LEGACY_PRICES = "DSD_PRICES@DF_PRICES_ALL"
_COICOP2018_PRICES = "DSD_PRICES_COICOP2018@DF_PRICES_C2018_ALL"

# Non-EUR G10 pairs: FRED spot-rate series, whether it quotes foreign-per-USD
# (needs inverting to USD-per-foreign), and the OECD area/dataflow/frequency
# for current, continuous CPI history back to 1990.
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
# USDSEK, USDNOK = foreign units per 1 USD); EUR/GBP/AUD/NZD already
# quote USD per 1 foreign unit. The model itself always works in USD-per-
# foreign terms internally (so Misalignment stays currency-centric,
# independent of quote direction) — this only affects what's displayed.
USD_BASE_PAIRS = {"JPY", "CHF", "CAD", "SEK", "NOK"}


def market_label(pair: str) -> str:
    return f"USD/{pair}" if pair in USD_BASE_PAIRS else f"{pair}/USD"


def to_market_convention(x, pair: str):
    return 1 / x if pair in USD_BASE_PAIRS else x


def _fetch_eur() -> pd.DataFrame:
    """EUR/USD: synthetic pre-1999 rate + spliced EA HICP (see module docstring)."""
    fred = FredClient()
    eurostat = EurostatClient()

    exgeus = fred.get_series("EXGEUS", observation_start="1990-01-01")["EXGEUS"]
    exuseu = fred.get_series("EXUSEU", observation_start="1999-01-01")["EXUSEU"]
    us_cpi = fred.get_series("CPIAUCSL", observation_start="1990-01-01")["CPIAUCSL"]
    ea_cpi_oecd = fred.get_series("EA19CPHPTT01IXEBM", observation_start="1990-01-01")["EA19CPHPTT01IXEBM"]

    ea_cpi_eurostat = (
        eurostat.get_data("prc_hicp_midx", coicop="CP00", geo="EA19", unit="I15")["value"]
        .resample("MS").last()
    )

    synthetic_eurusd = DEM_PER_EUR / exgeus
    fx = pd.concat([synthetic_eurusd[:EURO_LAUNCH].iloc[:-1], exuseu]).sort_index()

    splice_month = "1996-01-01"
    scale = ea_cpi_eurostat.loc[splice_month] / ea_cpi_oecd.loc[splice_month]
    foreign_cpi = pd.concat([ea_cpi_oecd[:splice_month].iloc[:-1] * scale, ea_cpi_eurostat]).sort_index()

    df = pd.concat({"FX": fx, "US_CPI": us_cpi, "FOREIGN_CPI": foreign_cpi}, axis=1)
    return df.dropna()


def _fetch_generic(pair: str) -> pd.DataFrame:
    """Any G10 pair besides EUR: one continuous FRED spot rate, no splice needed."""
    cfg = PAIRS[pair]
    fred = FredClient()
    oecd = OecdClient()

    fx = fred.get_series(cfg["fred_fx"], freq=cfg["freq"], observation_start="1990-01-01")[cfg["fred_fx"]]
    if cfg["invert"]:
        fx = 1 / fx

    us_cpi = fred.get_series("CPIAUCSL", freq=cfg["freq"], observation_start="1990-01-01")["CPIAUCSL"]

    oecd_freq_code = "Q" if cfg["freq"] == "QS" else "M"
    foreign_cpi = (
        oecd.get_data(
            "OECD.SDD.TPS", cfg["oecd_flow"],
            filters=f"{cfg['oecd_area']}.{oecd_freq_code}.N.CPI.IX._T.N._Z",
            version="1.0", startPeriod="1990-01",
        )["OBS_VALUE"]
        .resample(cfg["freq"]).last()
    )

    df = pd.concat({"FX": fx, "US_CPI": us_cpi, "FOREIGN_CPI": foreign_cpi}, axis=1)
    return df.dropna()


def _imf_period_to_date(period: str) -> str:
    if "-Q" in period:
        y, q = period.split("-Q")
        return f"{y}-{(int(q) - 1) * 3 + 1:02d}-01"
    if "-M" in period:
        y, m = period.split("-M")
        return f"{y}-{m}-01"
    return f"{period}-01-01"


def imf_itg_series(area: str, indicator: str, transformation: str, freq: str = "A", start: str = "2000") -> pd.Series:
    import requests
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
    unit-value series's level using their overlap period's mean ratio,
    then splices: rescaled price-index before the unit-value series
    starts, unit-value (current) from then on.
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
    import requests
    url = f"https://api.worldbank.org/v2/country/{area}/indicator/SL.GDP.PCAP.EM.KD"
    resp = requests.get(url, params={"format": "json", "per_page": "500", "date": f"{start}:2030"}, timeout=30)
    resp.raise_for_status()
    rows = resp.json()[1]
    s = pd.Series({pd.Timestamp(f"{r['date']}-01-01"): r["value"] for r in rows if r["value"] is not None})
    return s.sort_index()


def compute_adjusted_model(raw: pd.DataFrame, area: str):
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


def fetch_raw_data(pair: str = "EUR") -> pd.DataFrame:
    """Fetch and align spot FX + US/foreign CPI for ``pair`` onto a DatetimeIndex.

    Returns:
        DataFrame[FX, US_CPI, FOREIGN_CPI], FX quoted as USD per 1 unit of
        the foreign currency, one row per period from ~1990 onward.
    """
    return _fetch_eur() if pair == "EUR" else _fetch_generic(pair)


def compute_model(df: pd.DataFrame) -> pd.DataFrame:
    """Run the relative-PPP pipeline.

    Primary equilibrium line restricts beta=1 (strict relative PPP) with
    the intercept recalibrated so mean misalignment = 0 over the sample.
    An unrestricted OLS fit (beta free) is also computed for comparison
    and stored in ``result.attrs``, alongside an AR(1) half-life of
    mean reversion on the misalignment series.
    """
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
    half_life_periods = np.log(0.5) / np.log(rho) if 0 < rho < 1 else np.nan

    out.attrs["alpha"] = alpha
    out.attrs["ols_alpha"] = ols_alpha
    out.attrs["ols_beta"] = ols_beta
    out.attrs["ar1_rho"] = rho
    out.attrs["half_life_periods"] = half_life_periods
    return out


def plot_ppp(res: pd.DataFrame, pair: str, adjusted: pd.DataFrame = None) -> go.Figure:
    """Two-panel chart: {pair} actual vs. PPP-implied (market convention), and misalignment (%)."""
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

    fig.add_trace(go.Scatter(
        x=res.index, y=band_upper, name="±1 SD band",
        mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=res.index, y=band_lower, name="±1 SD band",
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(136,136,136,0.15)",
        showlegend=True, hoverinfo="skip",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=res.index, y=disp_fx, name=f"{label} (actual)",
        mode="lines", line=dict(color="#0057A8", width=2),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=res.index, y=disp_fx_ppp, name=f"{label} (PPP-implied)",
        mode="lines", line=dict(color="#F5A623", width=2, dash="dash"),
    ), row=1, col=1)

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

    fig.add_trace(go.Scatter(
        x=res.index, y=pct_dev, name="Misalignment (%)",
        mode="lines", line=dict(color="#00843D", width=2), fill="tozeroy",
    ), row=2, col=1)
    fig.add_hline(y=0, line=dict(color="#888888", width=1, dash="dot"), row=2, col=1)

    horizon_buttons = [
        dict(count=n, label=f"{n}Y", step="year", stepmode="backward")
        for n in (1, 2, 3, 5, 10, 15, 20, 30)
    ]
    horizon_buttons.append(dict(step="all", label="All"))

    fig.update_xaxes(
        rangeselector=dict(buttons=horizon_buttons, bgcolor="#f0f0f0"),
        row=1, col=1,
    )
    axis_title = f"{pair} per USD" if pair in USD_BASE_PAIRS else f"USD per {pair}"
    fig.update_yaxes(title_text=axis_title, gridcolor="#e5e5e5", row=1, col=1)
    fig.update_yaxes(title_text="Per cent", gridcolor="#e5e5e5", row=2, col=1)
    fig.update_xaxes(gridcolor="#e5e5e5")

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=750,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
        margin=dict(t=110),
    )
    return fig


def run(pair: str) -> str:
    """Fetch, model, and plot one pair. Returns the output HTML path."""
    raw = fetch_raw_data(pair)

    if pair == "EUR":
        print("--- splice sanity check (1995-12 / 1996-01) ---")
        print(raw["FOREIGN_CPI"].loc["1995-11":"1996-02"])
        print("--- splice sanity check (1998-12 / 1999-01) ---")
        print(raw["FX"].loc["1998-11":"1999-02"])

    res = compute_model(raw)
    label = market_label(pair)

    print(f"\n--- {label} model summary ---")
    print(f"Restricted PPP intercept (alpha, beta=1): {res.attrs['alpha']:.4f}")
    print(f"Unrestricted OLS: alpha={res.attrs['ols_alpha']:.4f}, beta={res.attrs['ols_beta']:.4f}")
    print(f"AR(1) rho on misalignment: {res.attrs['ar1_rho']:.4f}")
    print(f"Half-life of mean reversion: {res.attrs['half_life_periods']:.1f} periods")
    print(f"Current {label}: {to_market_convention(res['FX'].iloc[-1], pair):.4f}")
    print(f"Current PPP-implied: {to_market_convention(res['FX_PPP'].iloc[-1], pair):.4f}")
    print(f"Current misalignment: {res['Pct_Misalignment'].iloc[-1]:+.1f}% (negative = {pair} cheap vs. USD)")

    adjusted = None
    if pair in ADJUSTED_AREA:
        try:
            adjusted = compute_adjusted_model(raw, ADJUSTED_AREA[pair])
        except Exception as e:
            print(f"Adjusted PPP failed: {e}")
        if adjusted is not None:
            print(f"Adjusted PPP ({adjusted.index[-1].year}): beta_ToT={adjusted.attrs['beta_tot']:.2f}, "
                  f"beta_Prod={adjusted.attrs['beta_prod']:.2f}, "
                  f"misalignment={adjusted['Pct_Misalignment_ADJ'].iloc[-1]:+.1f}%")

    fig = plot_ppp(res, pair, adjusted)
    out = f"/Users/macproajb/claude_projects/{label.replace('/', '')}_PPP_{pd.Timestamp.today().date()}.html"
    fig.write_html(out)
    print(f"Chart saved -> {out}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classic relative-PPP model for G10/USD pairs")
    parser.add_argument("--pair", default="EUR", choices=ALL_PAIRS, help="Currency to model vs. USD (default: EUR)")
    parser.add_argument("--all", action="store_true", help="Run every G10 pair and write one HTML each")
    args = parser.parse_args()

    pairs_to_run = ALL_PAIRS if args.all else [args.pair]
    for p in pairs_to_run:
        run(p)
