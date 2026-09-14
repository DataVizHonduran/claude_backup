#!/usr/bin/env python3
"""
factor_map.py  [--factors "F1,F2,..."] [--rebase YYYY-MM-DD]
               [--rel-a FACTOR] [--rel-b FACTOR] [--out PATH]

Outputs a standalone HTML with 4 panels:
  1. Indexed performance (rebased to 100)
  2. 12M rolling correlation heatmap
  3. Factor scorecard (1M/3M/12M/3Y returns)
  4. Relative strength A/B ratio
"""

import sys
import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px

FACTOR_MAP = {
    "US Momentum":      "MTUM",
    "EU Momentum":      "IEFM",
    "JP Momentum":      "MSJP",
    "EM Momentum":      "EMO",
    "US Value":         "VLUE",
    "EU Value":         "IVEU",
    "JP Value":         "EWJV",
    "EM Value":         "EMVL",
    "US Quality":       "QUAL",
    "EU Quality":       "QVEU",
    "JP Quality":       "QUAL",
    "EM Quality":       "EQLT",
    "US Low Vol":       "USMV",
    "EU Low Vol":       "EUMV",
    "JP Low Vol":       "JPMV",
    "EM Low Vol":       "EEMV",
    "US Small Cap":     "IJR",
    "EU Small Cap":     "SMEU",
    "JP Small Cap":     "SCJ",
    "EM Small Cap":     "DGS",
    "EU Banks":         "EXV1.DE",
    "EU Resources":     "EXW1.DE",
    "Brazil Proxy":     "EWZ",
    "JP Governance":    "JPXN",
    "JP Hedged Export": "DXJ",
    "S&P 500":          "SPY",
}

VALID_NAMES = list(FACTOR_MAP.keys())
DEFAULT_FACTORS = ["US Momentum", "US Value", "EU Banks", "Brazil Proxy"]


def _ticker_of(name: str) -> str:
    return FACTOR_MAP[name]


def _name_of(ticker: str) -> str:
    for k, v in FACTOR_MAP.items():
        if v == ticker:
            return k
    return ticker


def fetch_data(tickers: list[str]) -> pd.DataFrame:
    unique = list(dict.fromkeys(tickers))
    raw = yf.download(unique, start="2021-01-01", actions=False, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        price_key = "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
        df = raw[price_key]
    else:
        df = raw
    if isinstance(df, pd.Series):
        df = df.to_frame(name=unique[0])
    return df


def calc_returns(series: pd.Series) -> dict:
    intervals = {"1M": 21, "3M": 63, "12M": 252, "3Y": 756}
    s = series.dropna()
    out = {}
    for label, days in intervals.items():
        if len(s) > days:
            r = (s.iloc[-1] / s.iloc[-days - 1]) - 1
            out[label] = f"{r:+.2%}"
        else:
            out[label] = "N/A"
    return out


def fig_performance(df: pd.DataFrame, factors: list[str], rebase: date) -> go.Figure:
    rebase_ts = pd.Timestamp(rebase)
    tickers = [_ticker_of(f) for f in factors]
    present = [t for t in tickers if t in df.columns]
    sub = df[df.index >= rebase_ts][present].dropna(how="all", axis=1)

    fig = go.Figure()
    if not sub.empty:
        indexed = (sub / sub.iloc[0]) * 100
        colors = px.colors.qualitative.Plotly
        for i, col in enumerate(indexed.columns):
            name = _name_of(col)
            fig.add_trace(go.Scatter(
                x=indexed.index, y=indexed[col], name=name,
                line=dict(color=colors[i % len(colors)], width=1.8),
            ))
    fig.update_layout(
        title=dict(text=f"Indexed Performance — base 100 on {rebase}", font=dict(size=15, color="#f0f0f0"), x=0.5),
        template="plotly_dark", hovermode="x unified", height=420,
        legend=dict(orientation="h", y=-0.18),
        margin=dict(t=50, b=80, l=60, r=20),
    )
    return fig


def fig_correlation(df: pd.DataFrame, factors: list[str]) -> go.Figure:
    tickers = [_ticker_of(f) for f in factors]
    present = [t for t in dict.fromkeys(tickers) if t in df.columns]
    if len(present) < 2:
        fig = go.Figure()
        fig.add_annotation(text="Need ≥2 factors for correlation", showarrow=False)
        fig.update_layout(template="plotly_dark", height=380)
        return fig

    corr = df[present].pct_change().tail(252).corr()
    labels = [_name_of(c) for c in corr.columns]
    corr.columns = labels
    corr.index = labels

    fig = px.imshow(
        corr, text_auto=".2f",
        color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
    )
    fig.update_layout(
        title=dict(text="Rolling 12M Correlation", font=dict(size=15, color="#f0f0f0"), x=0.5),
        template="plotly_dark", height=380,
        coloraxis_colorbar=dict(len=0.8),
        margin=dict(t=50, b=20, l=100, r=20),
    )
    return fig


def fig_scorecard(df: pd.DataFrame, factors: list[str]) -> go.Figure:
    rows = []
    for f in factors:
        t = _ticker_of(f)
        if t in df.columns:
            r = calc_returns(df[t])
            rows.append([f, r["1M"], r["3M"], r["12M"], r["3Y"]])

    if not rows:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        fig.update_layout(template="plotly_dark", height=200)
        return fig

    cols = ["Factor", "1M", "3M", "12M", "3Y"]
    transposed = list(zip(*rows))

    def cell_colors(col_data):
        colors = []
        for v in col_data:
            if v == "N/A":
                colors.append("#2a2a3a")
            elif v.startswith("+"):
                colors.append("#1a3a2a")
            else:
                colors.append("#3a1a1a")
        return colors

    fill_colors = ["#1e1e2e"] + [cell_colors(transposed[i]) for i in range(1, 5)]

    fig = go.Figure(go.Table(
        header=dict(
            values=[f"<b>{c}</b>" for c in cols],
            fill_color="#0f0f1a", font=dict(color="#e0e0e0", size=12),
            align="left", height=28,
        ),
        cells=dict(
            values=list(transposed),
            fill_color=fill_colors,
            font=dict(color="#e0e0e0", size=11),
            align=["left", "right", "right", "right", "right"],
            height=24,
        ),
    ))
    fig.update_layout(
        title=dict(text="Factor Scorecard", font=dict(size=15, color="#f0f0f0"), x=0.5),
        template="plotly_dark",
        height=max(200, 28 + len(rows) * 24 + 80),
        margin=dict(t=50, b=10, l=20, r=20),
    )
    return fig


def fig_relative(df: pd.DataFrame, rel_a: str, rel_b: str, rebase: date) -> go.Figure:
    ta, tb = _ticker_of(rel_a), _ticker_of(rel_b)
    fig = go.Figure()
    if ta in df.columns and tb in df.columns:
        rebase_ts = pd.Timestamp(rebase)
        rel = (df[ta] / df[tb]).dropna()
        rel = rel[rel.index >= rebase_ts]
        if not rel.empty:
            rel_norm = rel / rel.iloc[0]
            fig.add_trace(go.Scatter(
                x=rel_norm.index, y=rel_norm,
                fill="tozeroy", line=dict(color="gold", width=1.8),
                name=f"{rel_a} / {rel_b}",
            ))
            fig.add_hline(y=1.0, line_dash="dash", line_color="rgba(255,255,255,0.4)")
    else:
        missing = [n for n, t in [(rel_a, ta), (rel_b, tb)] if t not in df.columns]
        fig.add_annotation(text=f"No data for: {', '.join(missing)}", showarrow=False)

    fig.update_layout(
        title=dict(text=f"Relative Strength: {rel_a} / {rel_b}", font=dict(size=15, color="#f0f0f0"), x=0.5),
        template="plotly_dark", hovermode="x unified", height=320,
        yaxis_title="Ratio (norm. to 1.0)",
        margin=dict(t=50, b=40, l=60, r=20),
    )
    return fig


def combine_html(figures: list[go.Figure], out_path: Path) -> None:
    first = True
    divs = []
    for fig in figures:
        kwargs = dict(full_html=False)
        if first:
            kwargs["include_plotlyjs"] = "cdn"
            first = False
        else:
            kwargs["include_plotlyjs"] = False
        divs.append(fig.to_html(**kwargs))

    body = "\n".join(f'<div style="margin-bottom:32px">{d}</div>' for d in divs)
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Factor Map</title></head>
<body style="background:#0f0f1a;margin:0;padding:24px 32px;font-family:Arial,sans-serif">
<h2 style="color:#e0e0e0;margin-bottom:24px">Global Macro Factor Map</h2>
{body}
</body>
</html>"""
    out_path.write_text(html, encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--factors", default=",".join(DEFAULT_FACTORS),
                   help="Comma-separated factor names (use quotes)")
    p.add_argument("--rebase", default=str(date.today() - timedelta(days=365)),
                   help="Rebase date YYYY-MM-DD (default: 1y ago)")
    p.add_argument("--rel-a", default="US Momentum", dest="rel_a")
    p.add_argument("--rel-b", default="US Value", dest="rel_b")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    factors = [f.strip() for f in args.factors.split(",")]
    invalid = [f for f in factors if f not in FACTOR_MAP]
    if invalid:
        print(f"Unknown factors: {invalid}\nValid: {VALID_NAMES}", file=sys.stderr)
        sys.exit(1)
    if args.rel_a not in FACTOR_MAP:
        print(f"Unknown --rel-a: {args.rel_a}", file=sys.stderr); sys.exit(1)
    if args.rel_b not in FACTOR_MAP:
        print(f"Unknown --rel-b: {args.rel_b}", file=sys.stderr); sys.exit(1)

    try:
        rebase = date.fromisoformat(args.rebase)
    except ValueError:
        print(f"Bad --rebase date: {args.rebase}", file=sys.stderr); sys.exit(1)

    all_tickers = list(dict.fromkeys(
        [_ticker_of(f) for f in factors] +
        [_ticker_of(args.rel_a), _ticker_of(args.rel_b)]
    ))

    print("Fetching data…")
    df = fetch_data(all_tickers)
    if df.empty:
        print("No data returned.", file=sys.stderr); sys.exit(1)

    figs = [
        fig_performance(df, factors, rebase),
        fig_correlation(df, factors),
        fig_scorecard(df, factors),
        fig_relative(df, args.rel_a, args.rel_b, rebase),
    ]

    if args.out:
        out_path = Path(args.out)
    else:
        tag = date.today().strftime("%Y%m%d")
        out_path = Path(__file__).parent / f"factor_map_{tag}.html"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combine_html(figs, out_path)
    print(out_path)


if __name__ == "__main__":
    main()
