import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.colors as pcolors
from plotly.subplots import make_subplots


STATE_LABELS = {
    3: ["Down", "Flat", "Up"],
    4: ["Strong Down", "Down", "Up", "Strong Up"],
    5: ["Strong Down", "Down", "Flat", "Up", "Strong Up"],
}

STATE_COLORS = {
    3: ["#d62728", "#7f7f7f", "#2ca02c"],
    4: ["#d62728", "#ff7f0e", "#2ca02c", "#1a7a1a"],
    5: ["#d62728", "#ff7f0e", "#7f7f7f", "#2ca02c", "#1a7a1a"],
}


def fetch_data(ticker: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


def build_states_quantile(returns: pd.Series, n_states: int):
    states, bins = pd.qcut(returns, n_states, labels=False, retbins=True, duplicates="drop")
    n_actual = len(bins) - 1
    labels = STATE_LABELS.get(n_actual, [f"Q{i + 1}" for i in range(n_actual)])
    return states, bins, labels, n_actual


def build_states_trend(close: pd.Series, ma_window: int, band: float):
    """Down/Neutral/Up regime from price vs. its moving average, with a
    hysteresis deadband so the state only flips on a sustained move."""
    ma = close.rolling(ma_window).mean()
    pct = (close - ma) / ma

    state = pd.Series(np.nan, index=close.index)
    cur = 1  # start neutral
    for ts, v in pct.items():
        if np.isnan(v):
            continue
        if cur != 2 and v > band:
            cur = 2
        elif cur != 0 and v < -band:
            cur = 0
        elif cur != 1 and abs(v) < band / 2:
            cur = 1
        state[ts] = cur

    labels = ["Downtrend", "Neutral", "Uptrend"]
    return state, labels, 3


def transition_matrix(states: pd.Series, n_states: int):
    counts = np.zeros((n_states, n_states))
    s = states.dropna().astype(int).to_numpy()
    for i in range(len(s) - 1):
        counts[s[i], s[i + 1]] += 1
    row_sums = counts.sum(axis=1, keepdims=True)
    P = np.divide(counts, row_sums, out=np.zeros_like(counts), where=row_sums != 0)
    for i in range(n_states):
        if row_sums[i, 0] == 0:
            P[i, i] = 1.0
    return P, counts


def stationary_distribution(P: np.ndarray) -> np.ndarray:
    """Solve pi = pi P, sum(pi) = 1 via least squares (robust for
    near-reducible / high-persistence matrices where eig() is unstable)."""
    n = P.shape[0]
    A = np.vstack([P.T - np.eye(n), np.ones(n)])
    b = np.zeros(n + 1)
    b[-1] = 1.0
    pi, *_ = np.linalg.lstsq(A, b, rcond=None)
    pi = np.clip(pi, 0, None)
    return pi / pi.sum()


def build_figure(df, states, labels, n_actual, P, pi, ticker, state_desc):
    colors = STATE_COLORS.get(n_actual) or pcolors.sample_colorscale(
        "Turbo", [i / (n_actual - 1) for i in range(n_actual)]
    )

    fig = make_subplots(
        rows=3,
        cols=1,
        row_heights=[0.5, 0.3, 0.2],
        vertical_spacing=0.08,
        subplot_titles=(
            f"{ticker} price colored by {state_desc}",
            "Transition probability matrix",
            "Stationary distribution vs. next-period forecast",
        ),
    )

    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["Close"], mode="lines",
            line=dict(color="rgba(0,0,0,0.25)", width=1),
            name="Price", showlegend=False,
        ),
        row=1, col=1,
    )
    for i, label in enumerate(labels):
        mask = states == i
        fig.add_trace(
            go.Scatter(
                x=df.index[mask], y=df["Close"][mask], mode="markers",
                marker=dict(color=colors[i], size=5),
                name=label,
            ),
            row=1, col=1,
        )

    fig.add_trace(
        go.Heatmap(
            z=P, x=labels, y=labels,
            colorscale="Blues", zmin=0, zmax=1,
            text=P, texttemplate="%{text:.1%}",
            showscale=False,
        ),
        row=2, col=1,
    )
    fig.update_yaxes(autorange="reversed", title_text="From state", row=2, col=1)
    fig.update_xaxes(title_text="To state", row=2, col=1)

    current_state = int(states.dropna().iloc[-1])
    forecast = P[current_state]
    fig.add_trace(
        go.Bar(x=labels, y=pi, name="Stationary (long-run)", marker_color="#7f7f7f"),
        row=3, col=1,
    )
    fig.add_trace(
        go.Bar(
            x=labels, y=forecast,
            name=f"Next-period forecast (current: {labels[current_state]})",
            marker_color="#1f77b4",
        ),
        row=3, col=1,
    )
    fig.update_layout(barmode="group")

    fig.update_layout(
        template="plotly_white",
        height=1100,
        title=f"Markov Chain Analysis — {ticker}",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig, current_state, forecast


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Markov chain regime analysis for a ticker")
    parser.add_argument("ticker", nargs="?", default="MXN=X", help="Ticker symbol (default: MXN=X, i.e. USDMXN)")
    parser.add_argument("--period", default="10y", help="yfinance period (default: 10y)")
    parser.add_argument("--interval", default="1d", help="yfinance interval (default: 1d)")
    parser.add_argument("--mode", choices=["trend", "quantile"], default="trend",
                         help="State definition: 'trend' = price vs. moving average with hysteresis "
                              "(few regime changes/year), 'quantile' = daily return quantiles "
                              "(many changes/year). Default: trend")
    parser.add_argument("--ma-window", type=int, default=200, help="[trend mode] moving average window (default: 200)")
    parser.add_argument("--band", type=float, default=0.035,
                         help="[trend mode] hysteresis band as fraction of MA, e.g. 0.035 = 3.5%% (default: 0.035)")
    parser.add_argument("--states", type=int, default=5, help="[quantile mode] number of return states (default: 5)")
    parser.add_argument("--out", default=None, help="Output HTML path")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    df = fetch_data(ticker, args.period, args.interval)

    if args.mode == "trend":
        if len(df) < args.ma_window * 2:
            raise SystemExit(f"Not enough data ({len(df)} rows) for a {args.ma_window}-period moving average")
        states, labels, n_actual = build_states_trend(df["Close"], args.ma_window, args.band)
        state_desc = f"{args.ma_window}-period MA trend (±{args.band:.1%} band)"
    else:
        if len(df) < args.states * 10:
            raise SystemExit(f"Not enough data ({len(df)} rows) for {args.states} states")
        returns = np.log(df["Close"]).diff()
        states, bins, labels, n_actual = build_states_quantile(returns, args.states)
        state_desc = "return-state"

    P, counts = transition_matrix(states, n_actual)
    pi = stationary_distribution(P)

    fig, current_state, forecast = build_figure(df, states, labels, n_actual, P, pi, ticker, state_desc)

    print(f"Ticker: {ticker}  Period: {args.period}  Interval: {args.interval}  Mode: {args.mode}")
    print(f"Date range: {df.index[0].date()} to {df.index[-1].date()}  ({len(df)} obs)")

    if args.mode == "trend":
        years = (df.index[-1] - df.index[0]).days / 365.25
        s = states.dropna().astype(int).to_numpy()
        n_changes = int((np.diff(s) != 0).sum())
        print(f"\nState changes: {n_changes} over {years:.1f} years  ({n_changes / years:.1f} / year)")
    else:
        print(f"\nReturn bin edges: {np.round(bins, 5).tolist()}")

    print("\nTransition matrix:")
    print(pd.DataFrame(P, index=labels, columns=labels).round(3))

    print("\nStationary distribution:")
    print(pd.Series(pi, index=labels).round(3))

    print("\nDiagonal persistence (P[state, same state]):")
    print(pd.Series(np.diag(P), index=labels).round(3))

    print(f"\nCurrent state ({df.index[-1].date()}): {labels[current_state]}")
    print("Next-period forecast:")
    print(pd.Series(forecast, index=labels).round(3))

    out = args.out or f"markov_{ticker}.html"
    fig.write_html(out)
    print(f"\n{out}")


if __name__ == "__main__":
    main()
