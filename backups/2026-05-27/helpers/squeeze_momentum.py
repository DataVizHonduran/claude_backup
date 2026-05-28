import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _linreg(series: pd.Series, period: int) -> pd.Series:
    """Rolling linear regression — returns value at last bar of each window."""
    result = np.full(len(series), np.nan)
    vals = series.values
    x = np.arange(period)
    for i in range(period - 1, len(vals)):
        window = vals[i - period + 1 : i + 1]
        if np.any(np.isnan(window)):
            continue
        m, b = np.polyfit(x, window, 1)
        result[i] = m * (period - 1) + b
    return pd.Series(result, index=series.index)


def calculate_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_mult: float = 2.0,
    kc_mult: float = 1.5,
    mom_period: int = 20,
) -> pd.DataFrame:
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]
    n = bb_period

    # Bollinger Bands
    sma = close.rolling(n).mean()
    std = close.rolling(n).std(ddof=0)
    bb_upper = sma + bb_mult * std
    bb_lower = sma - bb_mult * std

    # Keltner Channel (SMA-based, LazyBear style)
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)
    atr = tr.rolling(n).mean()
    kc_upper = sma + kc_mult * atr
    kc_lower = sma - kc_mult * atr

    # Squeeze
    df["squeeze_on"] = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    # Momentum value (LazyBear formula)
    highest_high = high.rolling(n).max()
    lowest_low = low.rolling(n).min()
    delta = (highest_high + lowest_low) / 2
    val = close - (delta + sma) / 2

    df["momentum"] = _linreg(val, mom_period)
    df["mom_prev"] = df["momentum"].shift(1)
    return df


def _mom_colors(mom: pd.Series, mom_prev: pd.Series) -> list:
    colors = []
    for m, p in zip(mom, mom_prev):
        if pd.isna(m) or pd.isna(p):
            colors.append("#888888")
        elif m > 0:
            colors.append("#00E676" if m > p else "#006400")   # lime / dark green
        else:
            colors.append("#FF1744" if m < p else "#8B0000")   # red / maroon
    return colors


def plot_squeeze(df: pd.DataFrame, ticker: str = "") -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.03,
    )

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            increasing_line_color="#4682B4",
            decreasing_line_color="#4682B4",
            name="Price",
            showlegend=False,
        ),
        row=1, col=1,
    )

    # Momentum histogram
    hist_colors = _mom_colors(df["momentum"], df["mom_prev"])
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["momentum"],
            marker_color=hist_colors,
            name="Momentum",
            showlegend=False,
        ),
        row=2, col=1,
    )

    # Squeeze dots — only mark squeeze ON bars; absence = squeeze OFF
    sq_on = df[df["squeeze_on"] == True]
    if not sq_on.empty:
        fig.add_trace(
            go.Scatter(
                x=sq_on.index,
                y=[0] * len(sq_on),
                mode="markers",
                marker=dict(symbol="circle", size=7, color="#FF4500"),
                name="Squeeze ON",
            ),
            row=2, col=1,
        )

    fig.add_hline(y=0, line_dash="dot", line_color="#888888", row=2, col=1)

    fig.update_layout(
        title=f"Squeeze Momentum — {ticker}",
        template="plotly_white",
        height=750,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0),
    )
    fig.update_yaxes(title_text="Price",      row=1, col=1)
    fig.update_yaxes(title_text="Momentum",   row=2, col=1)
    return fig


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Squeeze Momentum indicator")
    parser.add_argument("ticker",                    help="Ticker symbol (e.g. SPY, EURUSD=X)")
    parser.add_argument("--period",   default="1y",  help="yfinance period (default: 1y)")
    parser.add_argument("--interval", default="1d",  help="yfinance interval (default: 1d)")
    parser.add_argument("--bb",       type=int,   default=20,  help="BB/KC period")
    parser.add_argument("--bb-mult",  type=float, default=2.0, help="BB std multiplier")
    parser.add_argument("--kc-mult",  type=float, default=1.5, help="KC ATR multiplier")
    parser.add_argument("--mom",      type=int,   default=20,  help="Momentum linreg period")
    parser.add_argument("--out",      default=None, help="Output HTML path")
    args = parser.parse_args()

    TICKER = args.ticker.upper()

    print(f"Fetching {TICKER} ({args.period} / {args.interval})...")
    raw = yf.download(TICKER, period=args.period, interval=args.interval,
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)

    df = calculate_squeeze(raw, args.bb, args.bb_mult, args.kc_mult, args.mom)

    sq_count  = df["squeeze_on"].sum()
    mom_valid = df["momentum"].notna().sum()
    print(f"Squeeze ON bars: {sq_count} | Momentum bars computed: {mom_valid}")

    fig = plot_squeeze(df, TICKER)
    out = args.out or f"squeeze_{TICKER}.html"
    fig.write_html(out)
    print(f"Chart saved → {out}")
