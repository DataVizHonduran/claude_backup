#!/usr/bin/env python3
import argparse
import sys
import re
import numpy as np
import pandas as pd
from scipy.stats import linregress
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def hurst_exponent(ts, min_lag, max_lag):
    if isinstance(ts, pd.Series):
        ts = ts.values
    ts = ts[~np.isnan(ts)]
    lags = range(min_lag, max_lag)
    rs_medians = []
    valid_lags = []
    for lag in lags:
        n_segs = len(ts) // lag
        if n_segs < 2:
            break
        rs_vals = []
        for i in range(n_segs):
            seg = ts[i * lag:(i + 1) * lag]
            mean = np.mean(seg)
            cum_dev = np.cumsum(seg - mean)
            R = np.max(cum_dev) - np.min(cum_dev)
            S = np.std(seg, ddof=1)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            rs_medians.append(np.median(rs_vals))
            valid_lags.append(lag)
    if len(rs_medians) < 2:
        return np.nan
    slope, *_ = linregress(np.log10(valid_lags), np.log10(rs_medians))
    return slope


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("--period", default="5y")
    p.add_argument("--interval", default="1wk")
    p.add_argument("--window", type=int, default=40)
    p.add_argument("--min-lag", type=int, default=2, dest="min_lag")
    p.add_argument("--max-lag", type=int, default=20, dest="max_lag")
    p.add_argument("--log-returns", action="store_true", dest="log_returns")
    args = p.parse_args()

    ticker = args.ticker.upper()
    data = yf.download(ticker, period=args.period, interval=args.interval, progress=False)
    price = data["Close"].dropna()
    if isinstance(price.columns if hasattr(price, "columns") else None, pd.Index):
        price = price.iloc[:, 0]
    if hasattr(price, "squeeze"):
        price = price.squeeze()

    if args.log_returns:
        series = np.log(price).diff().dropna()
        series_label = "Log Returns"
    else:
        series = price
        series_label = "Price"

    rolling_h = series.rolling(window=args.window).apply(
        lambda x: hurst_exponent(x, args.min_lag, args.max_lag), raw=True
    )

    last_h = rolling_h.dropna().iloc[-1] if rolling_h.dropna().shape[0] > 0 else np.nan
    if last_h > 0.55:
        regime = "TRENDING"
        regime_color = "#00e676"
    elif last_h < 0.45:
        regime = "MEAN-REVERTING"
        regime_color = "#ff5252"
    else:
        regime = "RANDOM WALK"
        regime_color = "#90a4ae"

    # build color array for Hurst trace
    h_vals = rolling_h.values
    colors = []
    for v in h_vals:
        if np.isnan(v):
            colors.append("#90a4ae")
        elif v > 0.5:
            colors.append("#00e676")
        else:
            colors.append("#ff5252")

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.4, 0.6],
        subplot_titles=(series_label, "Rolling Hurst Exponent (R/S)")
    )

    fig.add_trace(go.Scatter(
        x=series.index, y=series.values,
        line=dict(color="#64b5f6", width=1.2),
        name=series_label, showlegend=False
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=rolling_h.index, y=rolling_h.values,
        marker_color=colors,
        name="Hurst H", showlegend=False
    ), row=2, col=1)

    fig.add_hline(y=0.5, line_dash="dash", line_color="#ef5350", line_width=1.5,
                  annotation_text="H = 0.5", annotation_position="right",
                  row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        title=dict(
            text=f"{ticker} · Rolling Hurst Exponent ({args.window}-bar window)  "
                 f"<span style='color:{regime_color}'>H={last_h:.3f} · {regime}</span>",
            font=dict(size=14)
        ),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        margin=dict(l=50, r=50, t=60, b=40),
        height=600,
    )
    fig.update_yaxes(gridcolor="#1e2a35")
    fig.update_xaxes(gridcolor="#1e2a35")

    safe = re.sub(r"[^\w\-.]", "_", ticker)
    out = f"/Users/macproajb/claude_projects/hurst_{safe}.html"
    fig.write_html(out)
    print(out)


if __name__ == "__main__":
    main()
