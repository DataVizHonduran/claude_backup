import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _wilder_rma(arr: np.ndarray, n: int) -> np.ndarray:
    """Wilder's RMA (SMMA): seed=mean of first n, then EWM alpha=1/n."""
    result = np.full(len(arr), np.nan)
    start = 0
    while start < len(arr) and np.isnan(arr[start]):
        start += 1
    if start + n > len(arr):
        return result
    result[start + n - 1] = np.nanmean(arr[start : start + n])
    alpha = 1.0 / n
    for i in range(start + n, len(arr)):
        v = arr[i]
        result[i] = result[i - 1] * (1 - alpha) + (v if not np.isnan(v) else result[i - 1]) * alpha
    return result


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    high, low, close = df["High"], df["Low"], df["Close"]

    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)

    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)

    # Wilder's smoothed SUM = n * RMA
    sm_tr = period * _wilder_rma(tr.values, period)
    sm_plus = period * _wilder_rma(plus_dm.values, period)
    sm_minus = period * _wilder_rma(minus_dm.values, period)

    plus_di = 100.0 * sm_plus / np.where(sm_tr == 0, np.nan, sm_tr)
    minus_di = 100.0 * sm_minus / np.where(sm_tr == 0, np.nan, sm_tr)

    denom = plus_di + minus_di
    dx = 100.0 * np.abs(plus_di - minus_di) / np.where(denom == 0, np.nan, denom)

    # ADX = RMA of DX (not sum — gives 0-100 range)
    adx = _wilder_rma(dx, period)

    df["adx"] = adx
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    return df


def trendstall(
    df: pd.DataFrame,
    adx_period: int = 14,
    roc_period: int = 10,
    ma_period: int = 5,
    threshold: float = 0.5,
) -> pd.DataFrame:
    df = calculate_adx(df, adx_period)

    adx = df["adx"]
    adx_roc = (adx - adx.shift(roc_period)) / adx.shift(roc_period) * 100
    ma_roc = adx_roc.rolling(ma_period).mean()

    df["adx_roc"] = adx_roc
    df["ma_roc"] = ma_roc

    # stall bar: roc crosses below ma_roc while previous bar had roc > threshold
    crossed_below = (
        (adx_roc < ma_roc)
        & (adx_roc.shift(1) >= ma_roc.shift(1))
        & (adx_roc.shift(1) > threshold)
    )

    stall_signal = pd.Series(None, index=df.index, dtype=object)
    stall_signal[crossed_below & (df["plus_di"] > df["minus_di"])] = "up"
    stall_signal[crossed_below & (df["plus_di"] <= df["minus_di"])] = "down"

    # Vectorized bar states (priority: stall > post_stall > pre_stall)
    bar_state = pd.Series(None, index=df.index, dtype=object)
    valid = adx_roc.notna() & ma_roc.notna()
    bar_state[valid & (adx_roc > threshold)]               = "pre_stall"
    bar_state[valid & (adx_roc < ma_roc)]                  = "post_stall"
    bar_state[crossed_below]                               = "stall"

    df["bar_state"] = bar_state
    df["stall_signal"] = stall_signal
    return df


def plot_trendstall(df: pd.DataFrame, ticker: str = "", threshold: float = 0.5) -> go.Figure:
    color_map = {
        "pre_stall":  "#F4A460",
        "stall":      "#FF4500",
        "post_stall": "#9370DB",
        None:         "#4682B4",
    }

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

    for state, color in color_map.items():
        mask = df["bar_state"] == state if state is not None else df["bar_state"].isna()
        sub = df[mask]
        if sub.empty:
            continue
        fig.add_trace(
            go.Bar(
                x=sub.index,
                y=sub["High"] - sub["Low"],
                base=sub["Low"],
                marker_color=color,
                marker_opacity=0.40,
                name=state if state else "normal",
                showlegend=state is not None,
            ),
            row=1, col=1,
        )

    up_stalls = df[df["stall_signal"] == "up"]
    down_stalls = df[df["stall_signal"] == "down"]

    if not up_stalls.empty:
        fig.add_trace(
            go.Scatter(
                x=up_stalls.index,
                y=up_stalls["High"] * 1.005,
                mode="markers",
                marker=dict(symbol="triangle-down", size=12, color="red"),
                name="Stall ▼ (up-trend)",
            ),
            row=1, col=1,
        )

    if not down_stalls.empty:
        fig.add_trace(
            go.Scatter(
                x=down_stalls.index,
                y=down_stalls["Low"] * 0.995,
                mode="markers",
                marker=dict(symbol="triangle-up", size=12, color="lime"),
                name="Stall ▲ (down-trend)",
            ),
            row=1, col=1,
        )

    roc_vals = df["adx_roc"].values
    hist_colors = np.where(roc_vals >= 0, "#2ECC71", "#E74C3C")
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["adx_roc"],
            marker_color=hist_colors,
            name="ADX ROC",
            showlegend=False,
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["ma_roc"],
            line=dict(color="white", width=1.5),
            name="MA(ROC)",
        ),
        row=2, col=1,
    )
    fig.add_hline(y=0,         line_dash="dot",  line_color="gray",    row=2, col=1)
    fig.add_hline(y=threshold, line_dash="dash", line_color="#F4A460", row=2, col=1)

    fig.update_layout(
        title=f"TrendStall — {ticker}",
        template="plotly_dark",
        height=750,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0),
    )
    fig.update_yaxes(title_text="Price",       row=1, col=1)
    fig.update_yaxes(title_text="ADX ROC (%)", row=2, col=1)
    return fig


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TrendStall indicator")
    parser.add_argument("ticker",                    help="Ticker symbol (e.g. SPY, EURUSD=X)")
    parser.add_argument("--period",     default="1y", help="yfinance period (default: 1y)")
    parser.add_argument("--interval",   default="1d", help="yfinance interval (default: 1d)")
    parser.add_argument("--adx",        type=int,   default=14,  help="ADX period")
    parser.add_argument("--roc",        type=int,   default=10,  help="ROC lookback")
    parser.add_argument("--ma",         type=int,   default=5,   help="MA of ROC period")
    parser.add_argument("--threshold",  type=float, default=0.5, help="ROC threshold")
    parser.add_argument("--out",        default=None, help="Output HTML path")
    args = parser.parse_args()

    TICKER    = args.ticker.upper()
    THRESHOLD = args.threshold

    print(f"Fetching {TICKER} ({args.period} / {args.interval})...")
    raw = yf.download(TICKER, period=args.period, interval=args.interval,
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)

    df = trendstall(raw, args.adx, args.roc, args.ma, THRESHOLD)

    stall_count = df["stall_signal"].notna().sum()
    pre_count   = (df["bar_state"] == "pre_stall").sum()
    post_count  = (df["bar_state"] == "post_stall").sum()
    print(f"Stall signals: {stall_count} | Pre-stall bars: {pre_count} | Post-stall bars: {post_count}")

    fig = plot_trendstall(df, TICKER, threshold=THRESHOLD)
    out = args.out or f"trendstall_{TICKER}.html"
    fig.write_html(out)
    print(f"Chart saved → {out}")
