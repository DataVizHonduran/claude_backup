"""
Mulliner-Harvey (2025) Regime Classifier — full FRED-MD implementation.

Loads all 126 series from the FRED-MD CSV, applies a greedy de-correlation
filter (priority = longest history), then runs the non-parametric Euclidean
similarity regime classifier on surviving series.

Usage:
    python regime_classifier.py                     # latest available month
    python regime_classifier.py --date 2009-01      # GFC
    python regime_classifier.py --date 2022-08      # inflation surge
    python regime_classifier.py --corr 0.60         # tighter filter
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent))
from fred_client import FredMDClient, FredClient

# ---------------------------------------------------------------------------
# Vertical labels for display (FRED-MD category mapping)
# ---------------------------------------------------------------------------
_VERTICAL = {
    # Output & Income
    **{s: "Output" for s in [
        "RPI", "W875RX1", "DPCERA3M086SBEA", "CMRMTSPLx", "RETAILx", "INDPRO",
        "IPFPNSS", "IPFINAL", "IPCONGD", "IPDCONGD", "IPNCONGD", "IPBUSEQ",
        "IPMAT", "IPDMAT", "IPNMAT", "IPMANSICS", "IPB51222S", "IPFUELS", "CUMFNS",
    ]},
    # Labor
    **{s: "Labor" for s in [
        "HWI", "HWIURATIO", "CLF16OV", "CE16OV", "UNRATE", "UEMPMEAN",
        "UEMPLT5", "UEMP5TO14", "UEMP15OV", "UEMP15T26", "UEMP27OV", "CLAIMSx",
        "PAYEMS", "USGOOD", "CES1021000001", "USCONS", "MANEMP", "DMANEMP",
        "NDMANEMP", "SRVPRD", "USTPU", "USWTRADE", "USTRADE", "USFIRE",
        "USGOVT", "CES0600000007", "AWOTMAN", "AWHMAN",
    ]},
    # Housing
    **{s: "Housing" for s in [
        "HOUST", "HOUSTNE", "HOUSTMW", "HOUSTS", "HOUSTW",
        "PERMIT", "PERMITNE", "PERMITMW", "PERMITS", "PERMITW",
    ]},
    # Orders & Inventories
    **{s: "Orders" for s in [
        "ACOGNO", "AMDMNOx", "ANDENOx", "AMDMUOx", "BUSINVx", "ISRATIOx",
    ]},
    # Money & Credit
    **{s: "Money" for s in [
        "M1SL", "M2SL", "M2REAL", "BOGMBASE", "TOTRESNS", "NONBORRES",
        "BUSLOANS", "REALLN", "NONREVSL", "CONSPI",
        "DTCOLNVHFNM", "DTCTHFNM", "INVEST",
    ]},
    # Stock Market
    **{s: "Equity" for s in [
        "S&P 500", "S&P div yield", "S&P PE ratio",
    ]},
    # Interest Rates
    **{s: "Rates" for s in [
        "FEDFUNDS", "CP3Mx", "TB3MS", "TB6MS", "GS1", "GS5", "GS10", "AAA", "BAA",
        "COMPAPFFx", "TB3SMFFM", "TB6SMFFM", "T1YFFM", "T5YFFM", "T10YFFM",
        "AAAFFM", "BAAFFM", "YIELD_CURVE", "CREDIT_SPREAD",
    ]},
    # Exchange Rates
    **{s: "FX" for s in [
        "TWEXAFEGSMTHx", "EXSZUSx", "EXJPUSx", "EXUSUKx", "EXCAUSx",
    ]},
    # Prices (PPI / CPI / PCE)
    **{s: "Prices" for s in [
        "WPSFD49207", "WPSFD49502", "WPSID61", "WPSID62", "OILPRICEx", "PPICMM",
        "CPIAUCSL", "CPIAPPSL", "CPITRNSL", "CPIMEDSL",
        "CUSR0000SAC", "CUSR0000SAD", "CUSR0000SAS", "CPIULFSL",
        "CUSR0000SA0L2", "CUSR0000SA0L5", "PCEPI",
        "DDURRG3M086SBEA", "DNDGRG3M086SBEA", "DSERRG3M086SBEA",
    ]},
    # Wages
    **{s: "Wages" for s in [
        "CES0600000008", "CES2000000008", "CES3000000008",
    ]},
    # Sentiment / Volatility
    **{s: "Sentiment" for s in ["UMCSENTx", "VIXCLSx"]},
}

LAG_MONTHS      = 12
LOOKBACK_MONTHS = 120
MOMENTUM_MASK   = 36
REGIME_PCT      = 0.10
CORR_THRESHOLD  = 0.55

# McCracken codes 4,5,6 → log-type series (take log before 12m diff)
_LOG_CODES = {4, 5, 6}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_fredmd() -> tuple[pd.DataFrame, dict]:
    client = FredMDClient()
    df, transforms = client.download()
    print(f"  FRED-MD: {df.shape[1]} series, {df.index[0].date()} → {df.index[-1].date()}")
    return df, transforms


def fetch_usrec() -> pd.Series | None:
    """Fetch NBER recession indicator for chart shading (optional)."""
    try:
        return FredClient().get_series("USREC", freq="MS")["USREC"]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# State variable construction
# ---------------------------------------------------------------------------

def build_state_vars(df: pd.DataFrame, transforms: dict) -> pd.DataFrame:
    sv = {}
    for col in df.columns:
        code = int(transforms.get(col, 1))
        s = df[col].replace(0, np.nan)
        if code in _LOG_CODES and (s.dropna() > 0).all():
            sv[col] = np.log(s)
        else:
            sv[col] = s

    # Derived spreads
    if "GS10" in df.columns and "TB3MS" in df.columns:
        sv["YIELD_CURVE"]   = df["GS10"] - df["TB3MS"]
    if "BAA" in df.columns and "GS10" in df.columns:
        sv["CREDIT_SPREAD"] = df["BAA"]  - df["GS10"]

    return pd.DataFrame(sv, index=df.index)


# ---------------------------------------------------------------------------
# Transformation: 12m diff → rolling z-score → winsorize ±3
# ---------------------------------------------------------------------------

def transform_vars(sv: pd.DataFrame) -> pd.DataFrame:
    chg = sv.diff(LAG_MONTHS)
    z = pd.DataFrame(index=chg.index, columns=chg.columns, dtype=float)
    for col in chg.columns:
        std = chg[col].rolling(LOOKBACK_MONTHS, min_periods=60).std()
        z[col] = (chg[col] / std).clip(-3, 3)
    return z.dropna(how="all")


# ---------------------------------------------------------------------------
# De-correlation filter
# ---------------------------------------------------------------------------

def select_variables(
    z: pd.DataFrame, threshold: float = CORR_THRESHOLD
) -> tuple[pd.DataFrame, list[str], dict]:
    """
    Greedy filter: try series in descending order of history length.
    Keep a series if |corr| with every already-kept series is below threshold.
    Returns (filtered_df, kept_ids, drop_log).
    """
    history_len = z.count()
    ordered = history_len.sort_values(ascending=False).index.tolist()

    z_tail = z.tail(240)   # last 20 years for correlations

    kept, drop_log = [], {}
    for sid in ordered:
        if not kept:
            kept.append(sid)
            continue
        max_corr_sid, max_corr_val = None, 0.0
        for k in kept:
            pair = z_tail[[sid, k]].dropna()
            if len(pair) < 60:
                continue
            c = pair.corr().iloc[0, 1]
            if abs(c) > abs(max_corr_val):
                max_corr_sid, max_corr_val = k, c
        if max_corr_sid and abs(max_corr_val) >= threshold:
            drop_log[sid] = (max_corr_sid, max_corr_val)
        else:
            kept.append(sid)

    return z[kept], kept, drop_log


# ---------------------------------------------------------------------------
# Similarity engine
# ---------------------------------------------------------------------------

def compute_global_scores(z: pd.DataFrame, ref_date: pd.Timestamp) -> pd.Series:
    if ref_date not in z.index:
        ref_date = z.index[z.index.get_indexer([ref_date], method="nearest")[0]]
    ref_vec = z.loc[ref_date].values
    scores = {}
    for dt in z.index:
        hv = z.loc[dt].values
        mask = ~(np.isnan(ref_vec) | np.isnan(hv))
        if mask.sum() < 4:
            continue
        scores[dt] = np.sqrt(np.sum((hv[mask] - ref_vec[mask]) ** 2))
    return pd.Series(scores).sort_index()


def identify_regime(
    scores: pd.Series, ref_date: pd.Timestamp, pct: float = REGIME_PCT
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    cutoff = ref_date - pd.DateOffset(months=MOMENTUM_MASK)
    eligible = scores[scores.index <= cutoff]
    n = max(1, int(len(eligible) * pct))
    return eligible.nsmallest(n).index.sort_values(), eligible.nlargest(n).index.sort_values()


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_snapshot(
    z: pd.DataFrame, scores: pd.Series,
    similar: pd.DatetimeIndex, anti: pd.DatetimeIndex,
    ref_date: pd.Timestamp, kept: list[str], drop_log: dict,
    threshold: float,
) -> None:
    ref_row = z.loc[ref_date] if ref_date in z.index else z.iloc[-1]

    print(f"\n{'='*65}")
    print(f"  REGIME SNAPSHOT  |  Reference: {ref_date.strftime('%Y-%m')}")
    print(f"{'='*65}")

    print(f"\nKept variables ({len(kept)} of {len(kept)+len(drop_log)} after de-correlation):\n")
    current_v = None
    for sid in sorted(kept, key=lambda s: (_VERTICAL.get(s, "ZZ"), s)):
        v = _VERTICAL.get(sid, "Other")
        if v != current_v:
            print(f"  [{v}]")
            current_v = v
        val = ref_row.get(sid, np.nan)
        if np.isnan(val):
            print(f"    {sid:<30}   n/a")
        else:
            bar = "█" * min(int(abs(val)), 3)
            print(f"    {sid:<30}  {val:+.2f}  {bar}")

    print(f"\nDropped ({len(drop_log)} series, |corr| ≥ {threshold}):")
    by_vertical = {}
    for sid, (with_sid, val) in drop_log.items():
        v = _VERTICAL.get(sid, "Other")
        by_vertical.setdefault(v, []).append(f"{sid} (corr={val:+.2f} w/ {with_sid})")
    for v in sorted(by_vertical):
        print(f"  [{v}] {' · '.join(by_vertical[v])}")

    print(f"\nTop 20 Most Similar (Regime Analogs):")
    for dt in similar[:20]:
        print(f"  {dt.strftime('%Y-%m')}   score={scores[dt]:.3f}")

    print(f"\nTop 20 Most Dissimilar (Anti-Regime):")
    for dt in anti[:20]:
        print(f"  {dt.strftime('%Y-%m')}   score={scores[dt]:.3f}")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def _date_bands(dates: pd.DatetimeIndex, color: str) -> list:
    shapes = []
    if not len(dates):
        return shapes
    sorted_dates = sorted(dates)
    groups, cur = [], [sorted_dates[0]]
    for d in sorted_dates[1:]:
        if (d - cur[-1]).days <= 35:
            cur.append(d)
        else:
            groups.append(cur); cur = [d]
    groups.append(cur)
    for g in groups:
        shapes.append(dict(
            type="rect", xref="x", yref="paper",
            x0=g[0] - pd.Timedelta(days=15),
            x1=g[-1] + pd.Timedelta(days=15),
            y0=0, y1=1, fillcolor=color,
            opacity=0.25, line_width=0, layer="below",
        ))
    return shapes


def plot_global_score(
    scores: pd.Series, similar: pd.DatetimeIndex, anti: pd.DatetimeIndex,
    ref_date: pd.Timestamp, usrec: "pd.Series | None",
    kept: list[str], out_dir: Path,
) -> Path:
    rec_shapes = []
    if usrec is not None:
        rec = usrec.reindex(scores.index).fillna(0)
        in_rec, r_start = False, None
        for dt, v in rec.items():
            if v == 1 and not in_rec:
                in_rec, r_start = True, dt
            elif v == 0 and in_rec:
                rec_shapes.append(dict(
                    type="rect", xref="x", yref="paper",
                    x0=r_start, x1=dt, y0=0, y1=1,
                    fillcolor="lightgray", opacity=0.4, line_width=0, layer="below",
                ))
                in_rec = False

    # Gray out the momentum mask period (last 36 months — excluded from selection)
    mask_start = ref_date - pd.DateOffset(months=MOMENTUM_MASK)
    mask_shape = [dict(
        type="rect", xref="x", yref="paper",
        x0=mask_start, x1=scores.index[-1] + pd.Timedelta(days=15),
        y0=0, y1=1,
        fillcolor="rgba(180,180,180,0.35)", line_width=0, layer="below",
    )]

    fig = go.Figure()
    fig.update_layout(shapes=(rec_shapes
                               + mask_shape
                               + _date_bands(similar, "rgba(30,100,200,0.3)")
                               + _date_bands(anti,    "rgba(200,40,40,0.3)")))

    fig.add_trace(go.Scatter(
        x=scores.index, y=scores.values, mode="lines",
        line=dict(color="black", width=1.5), name="Global Score",
        hovertemplate="%{x|%Y-%m}<br>Score: %{y:.3f}<extra></extra>",
    ))
    for label, color in [
        ("Regime (similar)",          "rgba(30,100,200,0.5)"),
        ("Anti-regime",               "rgba(200,40,40,0.5)"),
        ("NBER Recession",            "lightgray"),
        ("Momentum mask (excluded)",  "rgba(180,180,180,0.5)"),
    ]:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
            marker=dict(color=color, size=12, symbol="square"), name=label))

    fig.add_vline(
        x=ref_date.timestamp() * 1000,
        line=dict(color="orange", width=2, dash="dash"),
        annotation_text=f"Ref: {ref_date.strftime('%Y-%m')}",
        annotation_position="top right",
    )

    verticals = sorted(set(_VERTICAL.get(s, "Other") for s in kept))
    fig.update_layout(
        title=dict(
            text=(f"Regime Classifier — {ref_date.strftime('%Y-%m')}<br>"
                  f"<sub>{len(kept)} variables · Verticals: {' · '.join(verticals)}</sub>"),
            font_size=15,
        ),
        xaxis_title="Date",
        yaxis_title="Global Score (Euclidean Distance)",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=550, hovermode="x unified",
    )

    fname = out_dir / f"regime_global_score_{ref_date.strftime('%Y-%m')}.html"
    fig.write_html(str(fname))
    print(f"\nChart: {fname}")
    return fname


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Mulliner-Harvey Regime Classifier (FRED-MD)")
    parser.add_argument("--date", default=None, help="Reference YYYY-MM (default: latest)")
    parser.add_argument("--pct",  type=float, default=REGIME_PCT)
    parser.add_argument("--corr", type=float, default=CORR_THRESHOLD,
                        help="De-correlation threshold (default 0.70)")
    args = parser.parse_args()

    print("Loading FRED-MD...")
    df, transforms = load_fredmd()

    sv = build_state_vars(df, transforms)
    z  = transform_vars(sv)
    print(f"  Series available for filter: {z.shape[1]}")

    z_sel, kept, drop_log = select_variables(z, threshold=args.corr)
    print(f"  Kept after de-correlation:   {len(kept)}")

    # Trim to common non-NaN window across kept series
    z_sel = z_sel.dropna()
    print(f"  Usable history: {z_sel.index[0].date()} → {z_sel.index[-1].date()} ({len(z_sel)} months)")

    ref_date = pd.Timestamp(args.date) if args.date else z_sel.index[-1]
    if ref_date not in z_sel.index:
        ref_date = z_sel.index[z_sel.index.get_indexer([ref_date], method="nearest")[0]]
    print(f"  Reference date: {ref_date.strftime('%Y-%m')}")

    scores = compute_global_scores(z_sel, ref_date)
    similar, anti = identify_regime(scores, ref_date, pct=args.pct)

    print_snapshot(z_sel, scores, similar, anti, ref_date, kept, drop_log, args.corr)

    print("\nFetching NBER recession dates...")
    usrec = fetch_usrec()

    plot_global_score(scores, similar, anti, ref_date, usrec, kept, Path(__file__).parent)


if __name__ == "__main__":
    main()
