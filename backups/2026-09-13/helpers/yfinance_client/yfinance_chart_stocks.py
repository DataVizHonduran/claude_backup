#!/usr/bin/env python3
"""
yfinance_chart_stocks.py  TICKER [TICKER2 ...] [--period 1y] [--interval 1d] [--out PATH]
                          [--drawdown] [--correlation] [--window N]

Defaults: period=1y, interval=1d
Periods:  1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max
Intervals: 1m 2m 5m 15m 30m 60m 90m 1h 1d 5d 1wk 1mo 3mo
--correlation: rolling Pearson r between exactly 2 tickers (requires --window, default 200)
"""

import sys
import argparse
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

COLORS = ["#0057A8", "#E8630A", "#00875A", "#C8102E", "#7B2D8B", "#C0A000", "#00A8A8"]


def fetch(ticker: str, period: str, interval: str) -> tuple:
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data returned for {ticker}")
    name = t.info.get("shortName") or ticker
    return df, name


def add_trace(fig, df, label, color, row, show_volume: bool):
    fig.add_trace(
        go.Scatter(x=df.index, y=df["Close"], name=label,
                   line=dict(color=color, width=1.8), mode="lines"),
        row=row, col=1
    )
    if show_volume:
        fig.add_trace(
            go.Bar(x=df.index, y=df["Volume"], name=f"{label} Vol",
                   marker_color=color, opacity=0.35, showlegend=False),
            row=row + 1, col=1
        )


def add_drawdown_trace(fig, df, label, color, row):
    rolling_high = df["Close"].cummax()
    dd = (df["Close"] - rolling_high) / rolling_high * 100
    fig.add_trace(
        go.Scatter(x=df.index, y=dd, name=label,
                   line=dict(color=color, width=1.4), mode="lines",
                   fill="tozeroy", fillcolor=color.replace(")", ",0.18)").replace("rgb", "rgba") if color.startswith("rgb") else color),
        row=row, col=1
    )


def build_chart(tickers: list[str], period: str, interval: str, drawdown: bool = False) -> tuple[go.Figure, str]:
    single = len(tickers) == 1
    show_vol = single and not drawdown

    rows = 2 if show_vol else 1
    row_heights = [0.75, 0.25] if show_vol else [1.0]

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        row_heights=row_heights,
        vertical_spacing=0.03,
    )

    names = []
    for i, ticker in enumerate(tickers):
        df, name = fetch(ticker.upper(), period, interval)
        color = COLORS[i % len(COLORS)]
        label = f"{ticker.upper()} — {name}"
        if drawdown:
            add_drawdown_trace(fig, df, label, color, row=1)
        else:
            add_trace(fig, df, label, color, row=1, show_volume=show_vol)
        names.append(ticker.upper())

    title_tickers = " / ".join(names)
    dd_suffix = "  ·  Drawdown from Rolling High (%)" if drawdown else ""
    title = f"{title_tickers}{dd_suffix}  ·  {period} ({interval} bars)"

    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=40, t=80, b=40),
        height=520 if show_vol else 440,
    )
    if drawdown:
        fig.update_yaxes(title_text="% below rolling high", ticksuffix="%", row=1, col=1)
    else:
        fig.update_yaxes(title_text="Price (USD)", row=1, col=1)
    if show_vol:
        fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_xaxes(rangeslider_visible=False)

    return fig, "_".join(names)


def build_ratio_chart(tickers: list[str], period: str, interval: str) -> tuple[go.Figure, str]:
    if len(tickers) != 2:
        raise ValueError("--ratio requires exactly 2 tickers")
    t1, t2 = [t.upper() for t in tickers]
    closes = {}
    for t in (t1, t2):
        df = yf.Ticker(t).history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No data for {t}")
        closes[t] = df["Close"]
    prices = pd.DataFrame(closes).dropna()
    ratio = prices[t1] / prices[t2]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ratio.index, y=ratio.values,
        mode="lines", line=dict(color="#0057A8", width=1.5),
        name=f"{t1}/{t2} ratio",
    ))
    fig.update_layout(
        template="plotly_dark",
        title=f"{t1} / {t2} — Price Ratio  ·  {period} ({interval} bars)",
        xaxis_title=None,
        yaxis=dict(title=f"{t1}/{t2}", tickformat=".4f"),
        height=480,
        margin=dict(l=60, r=30, t=60, b=40),
        hovermode="x unified",
    )
    tag = f"{t1}_{t2}_ratio"
    return fig, tag


def build_correlation_chart(tickers: list[str], period: str, interval: str, window: int) -> tuple[go.Figure, str]:
    if len(tickers) != 2:
        raise ValueError("--correlation requires exactly 2 tickers")
    t1, t2 = [t.upper() for t in tickers]
    closes = {}
    for t in (t1, t2):
        df = yf.Ticker(t).history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No data for {t}")
        closes[t] = df["Close"]
    prices = pd.DataFrame(closes).dropna()
    rets = prices.pct_change()
    corr = rets[t1].rolling(window).corr(rets[t2]).dropna()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=corr.index, y=corr.values,
        mode="lines", line=dict(color="#0057A8", width=1.5),
        name=f"{window}-day rolling corr",
    ))
    fig.add_hline(y=0, line=dict(color="gray", dash="dash", width=1))
    fig.add_hline(y=1, line=dict(color="#555", dash="dot", width=0.8))
    fig.update_layout(
        template="plotly_dark",
        title=f"{t1} / {t2} — {window}-Day Rolling Correlation  ·  {period} ({interval} bars)",
        xaxis_title=None,
        yaxis=dict(title="Pearson r", range=[-0.3, 1.1], tickformat=".2f"),
        height=480,
        margin=dict(l=60, r=30, t=60, b=40),
        hovermode="x unified",
    )
    tag = f"{t1}_{t2}_{window}d_corr"
    return fig, tag


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+", help="One or more ticker symbols")
    parser.add_argument("--period", default="1y",
                        choices=["1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"])
    parser.add_argument("--interval", default="1d",
                        choices=["1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo"])
    parser.add_argument("--out", default=None, help="Output HTML path (auto-generated if omitted)")
    parser.add_argument("--drawdown", action="store_true", help="Plot % drawdown from rolling high instead of price")
    parser.add_argument("--correlation", action="store_true", help="Plot rolling Pearson r between 2 tickers")
    parser.add_argument("--ratio", action="store_true", help="Plot price ratio of exactly 2 tickers")
    parser.add_argument("--window", type=int, default=200, help="Rolling window for --correlation (default 200)")
    args = parser.parse_args()

    if args.correlation:
        fig, tag = build_correlation_chart(args.tickers, args.period, args.interval, args.window)
    elif args.ratio:
        fig, tag = build_ratio_chart(args.tickers, args.period, args.interval)
    else:
        fig, tag = build_chart(args.tickers, args.period, args.interval, drawdown=args.drawdown)

    out = args.out or f"/Users/macproajb/claude_projects/yfinance_client/{tag}_{date.today()}.html"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(out)
    print(out)


if __name__ == "__main__":
    main()
