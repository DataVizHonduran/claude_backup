"""RBA RDP 2015-12 style AUD real exchange rate cointegration model.

Regresses ln(Real TWI) on ln(Terms of Trade) and a G3 real interest rate
differential (RIRD), then reports the implied equilibrium exchange rate
and current misalignment.

Note: uses the RBA/ABS *Total* Terms of Trade (ANA_AGG, TTR) as a proxy
for the goods-only ToT deflator referenced in RDP 2015-12 — a clean
goods-only series isn't available via the public ABS Data API.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from eurostat_client import EurostatClient
from fred_client import FredClient
from oecd_client import OecdClient

from .client import AbsClient, RbaClient

_G3_WEIGHTS = {"US": 0.45, "EZ": 0.35, "JP": 0.20}

# RDP 2015-12 baseline cointegrating-vector coefficients.
RDP_ALPHA = 2.10
RDP_BETA_TOT = 0.60
RDP_BETA_RIRD = 2.00


def _to_quarterly(s: pd.Series) -> pd.Series:
    """Bin a series of any frequency into quarter-end means."""
    return s.resample("QE").mean()


def fetch_raw_data() -> pd.DataFrame:
    """Fetch and align all model inputs onto a quarterly DatetimeIndex.

    Returns:
        DataFrame[RTWI, ToT, AU_Cash, AU_CPI, US_Cash, US_CPI,
        EZ_Cash, EZ_CPI, JP_Cash, JP_CPI], one row per quarter.
    """
    rba = RbaClient()
    abs_c = AbsClient()
    fred = FredClient()
    eurostat = EurostatClient()
    oecd = OecdClient()

    rtwi = _to_quarterly(rba.get_series("F15", "FRERTWI"))

    tot = _to_quarterly(abs_c.get_data("ANA_AGG", "M5.TTR.20.AUS.Q", version="1.0.0")["value"])

    au_cash = _to_quarterly(rba.get_series("F1.1", "FIRMMCRT"))
    au_cpi = _to_quarterly(rba.get_series("G1", "GCPIOCPMTMYP"))

    us_cash = _to_quarterly(fred.get_series("FEDFUNDS")["FEDFUNDS"])
    us_cpi_yoy = fred.get_series("CPILFESL")["CPILFESL"].pct_change(12, fill_method=None) * 100
    us_cpi = _to_quarterly(us_cpi_yoy)

    ez_cash = _to_quarterly(fred.get_series("ECBDFR")["ECBDFR"])
    ez_cpi = _to_quarterly(eurostat.get_data("prc_hicp_manr", coicop="TOT_X_NRG_FOOD", geo="EA20")["value"])

    jp_cash = _to_quarterly(fred.get_series("IRSTCI01JPM156N")["IRSTCI01JPM156N"])
    jp_cpi = _to_quarterly(
        oecd.get_data(
            "OECD.SDD.TPS",
            "DSD_PRICES_COICOP2018@DF_PRICES_C2018_ALL",
            filters="JPN.M..CPI.._TXCP01_NRG..GY",
            version="1.0",
        )["OBS_VALUE"]
    )

    df = pd.concat(
        {
            "RTWI": rtwi,
            "ToT": tot,
            "AU_Cash": au_cash,
            "AU_CPI": au_cpi,
            "US_Cash": us_cash,
            "US_CPI": us_cpi,
            "EZ_Cash": ez_cash,
            "EZ_CPI": ez_cpi,
            "JP_Cash": jp_cash,
            "JP_CPI": jp_cpi,
        },
        axis=1,
    )
    return df.dropna()


def compute_model(df: pd.DataFrame) -> pd.DataFrame:
    """Run the cointegration pipeline on aligned quarterly data.

    Equilibrium/misalignment use the RDP 2015-12 baseline elasticities
    (``RDP_BETA_TOT``, ``RDP_BETA_RIRD``) for fidelity to the published
    model's slope coefficients. RIRD is converted to "percentage point
    decimal" form (1pp -> 0.01) before applying ``RDP_BETA_RIRD``, per the
    RDP 2015-12 specification ("2.00, equivalent to 0.02 per 100bps").

    The intercept is recalibrated (mean misalignment = 0 over the sample)
    rather than using the published ``RDP_ALPHA`` directly, since our
    ln_RTWI/ln_ToT series use different index bases/vintages than RDP
    2015-12's (RBA F15 and ABS ANA_AGG have both been rebased since 2015,
    and ToT here is the Total — not goods-only — series). Using the
    published constant verbatim would shift the whole misalignment series
    by a near-constant offset without changing its shape.

    An OLS refit of all three coefficients on the same (correctly-scaled)
    regressors is also computed for comparison and stored in
    ``result.attrs`` alongside the RDP elasticities and recalibrated
    intercept.
    """
    out = df.copy()

    out["Real_AU"] = out["AU_Cash"] - out["AU_CPI"]
    out["Real_US"] = out["US_Cash"] - out["US_CPI"]
    out["Real_EZ"] = out["EZ_Cash"] - out["EZ_CPI"]
    out["Real_JP"] = out["JP_Cash"] - out["JP_CPI"]

    out["Real_G3"] = (
        _G3_WEIGHTS["US"] * out["Real_US"]
        + _G3_WEIGHTS["EZ"] * out["Real_EZ"]
        + _G3_WEIGHTS["JP"] * out["Real_JP"]
    )
    out["RIRD"] = out["Real_AU"] - out["Real_G3"]
    out["RIRD_decimal"] = out["RIRD"] / 100

    out["ln_RTWI"] = np.log(out["RTWI"])
    out["ln_ToT"] = np.log(out["ToT"])

    alpha = (out["ln_RTWI"] - RDP_BETA_TOT * out["ln_ToT"] - RDP_BETA_RIRD * out["RIRD_decimal"]).mean()

    out["ln_RTWI_Equilibrium"] = (
        alpha + RDP_BETA_TOT * out["ln_ToT"] + RDP_BETA_RIRD * out["RIRD_decimal"]
    )
    out["RTWI_Equilibrium"] = np.exp(out["ln_RTWI_Equilibrium"])
    out["Misalignment"] = out["ln_RTWI"] - out["ln_RTWI_Equilibrium"]
    out["Implied_Next_Quarter_Adjustment"] = -0.15 * out["Misalignment"]

    X = np.column_stack([np.ones(len(out)), out["ln_ToT"], out["RIRD_decimal"]])
    y = out["ln_RTWI"].to_numpy()
    (ols_alpha, ols_beta_1, ols_beta_2), *_ = np.linalg.lstsq(X, y, rcond=None)

    out.attrs["alpha"] = alpha
    out.attrs["beta_1"] = RDP_BETA_TOT
    out.attrs["beta_2"] = RDP_BETA_RIRD
    out.attrs["rdp_alpha_published"] = RDP_ALPHA
    out.attrs["ols_alpha"] = ols_alpha
    out.attrs["ols_beta_1"] = ols_beta_1
    out.attrs["ols_beta_2"] = ols_beta_2
    return out


def plot_cointegration(res: pd.DataFrame) -> go.Figure:
    """Two-panel chart: Real TWI actual vs. equilibrium, and misalignment (%).

    White background, shared x-axis with a range selector for 1/2/3/5/10/15/20-year
    and full-history horizons.
    """
    pct_dev = (np.exp(res["Misalignment"]) - 1) * 100

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
        row_heights=[0.6, 0.4],
        subplot_titles=("AUD Real TWI: Actual vs. Equilibrium", "Misalignment vs. Equilibrium (%)"),
    )

    std_dev = pct_dev.std()
    band_upper = res["RTWI_Equilibrium"] * (1 + std_dev / 100)
    band_lower = res["RTWI_Equilibrium"] * (1 - std_dev / 100)

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
        x=res.index, y=res["RTWI"], name="Real TWI (actual)",
        mode="lines", line=dict(color="#0057A8", width=2),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=res.index, y=res["RTWI_Equilibrium"], name="Real TWI (equilibrium)",
        mode="lines", line=dict(color="#F5A623", width=2, dash="dash"),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=res.index, y=pct_dev, name="Misalignment (%)",
        mode="lines", line=dict(color="#00843D", width=2), fill="tozeroy",
    ), row=2, col=1)
    fig.add_hline(y=0, line=dict(color="#888888", width=1, dash="dot"), row=2, col=1)

    horizon_buttons = [
        dict(count=n, label=f"{n}Y", step="year", stepmode="backward")
        for n in (1, 2, 3, 5, 10, 15, 20)
    ]
    horizon_buttons.append(dict(step="all", label="All"))

    fig.update_xaxes(
        rangeselector=dict(buttons=horizon_buttons, bgcolor="#f0f0f0"),
        row=1, col=1,
    )
    fig.update_yaxes(title_text="Index", gridcolor="#e5e5e5", row=1, col=1)
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
