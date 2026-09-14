import argparse
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from ta.volatility import BollingerBands
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, SMAIndicator


def compute_indicators(df: pd.DataFrame, args) -> pd.DataFrame:
    close, high, low = df["Close"], df["High"], df["Low"]

    bb = BollingerBands(close, window=args.bb, window_dev=args.bb_std)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_mid"]   = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_pband"] = bb.bollinger_pband()
    df["bb_width"] = bb.bollinger_wband()

    df["rsi"] = RSIIndicator(close, window=args.rsi).rsi()

    stoch = StochasticOscillator(high, low, close,
                                  window=args.stoch_k, smooth_window=args.stoch_d)
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    macd_obj = MACD(close, window_fast=args.macd_fast,
                    window_slow=args.macd_slow, window_sign=args.macd_signal)
    df["macd"]        = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_hist"]   = macd_obj.macd_diff()

    df["sma20"]  = SMAIndicator(close, window=20).sma_indicator()
    df["sma50"]  = SMAIndicator(close, window=50).sma_indicator()
    df["sma200"] = SMAIndicator(close, window=200).sma_indicator()

    return df


def build_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        row_heights=[0.42, 0.17, 0.14, 0.14, 0.13],
        vertical_spacing=0.025,
        subplot_titles=("Price + BB + MAs", "MACD", "RSI (14)", "Slow Stoch (14,3)", "BB Width"),
    )

    # — Panel 1: Candlestick + Bollinger Band fill + MAs —
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        name="Price", showlegend=False,
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_upper"], line=dict(color="rgba(100,149,237,0.6)", width=1),
        name="BB Upper", showlegend=True,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_lower"], line=dict(color="rgba(100,149,237,0.6)", width=1),
        fill="tonexty", fillcolor="rgba(100,149,237,0.08)",
        name="BB Lower", showlegend=True,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_mid"], line=dict(color="rgba(100,149,237,0.9)", width=1, dash="dot"),
        name="BB Mid", showlegend=True,
    ), row=1, col=1)

    ma_colors = {"sma20": "#FFD700", "sma50": "#FF8C00", "sma200": "#DC143C"}
    ma_labels = {"sma20": "SMA 20", "sma50": "SMA 50", "sma200": "SMA 200"}
    for col, color in ma_colors.items():
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col], line=dict(color=color, width=1),
            name=ma_labels[col],
        ), row=1, col=1)

    # — Panel 2: MACD —
    hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["macd_hist"].fillna(0)]
    fig.add_trace(go.Bar(
        x=df.index, y=df["macd_hist"], marker_color=hist_colors,
        name="MACD Hist", showlegend=False,
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["macd"], line=dict(color="#2196F3", width=1.2),
        name="MACD",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["macd_signal"], line=dict(color="#FF9800", width=1.2),
        name="Signal",
    ), row=2, col=1)

    # — Panel 3: RSI —
    fig.add_trace(go.Scatter(
        x=df.index, y=df["rsi"], line=dict(color="#AB47BC", width=1.5),
        name="RSI",
    ), row=3, col=1)
    for level, dash in [(70, "dash"), (30, "dash"), (50, "dot")]:
        fig.add_hline(y=level, line_dash=dash, line_color="#888888",
                      line_width=0.8, row=3, col=1)

    # — Panel 4: Slow Stochastics —
    fig.add_trace(go.Scatter(
        x=df.index, y=df["stoch_k"], line=dict(color="#42A5F5", width=1.5),
        name="%K",
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["stoch_d"], line=dict(color="#EF5350", width=1.2, dash="dot"),
        name="%D",
    ), row=4, col=1)
    for level in (80, 20):
        fig.add_hline(y=level, line_dash="dash", line_color="#888888",
                      line_width=0.8, row=4, col=1)

    fig.update_layout(
        title=f"Technical Analysis — {ticker}",
        template="plotly_white",
        height=900,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0, font_size=11),
        margin=dict(t=80, b=40, l=60, r=20),
    )
    fig.update_yaxes(title_text="Price",  row=1, col=1)
    fig.update_yaxes(title_text="MACD",   row=2, col=1)
    fig.update_yaxes(title_text="RSI",    row=3, col=1, range=[0, 100])
    fig.update_yaxes(title_text="Stoch",  row=4, col=1, range=[0, 100])

    # — Panel 5: BB Width —
    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_width"], line=dict(color="#78909C", width=1.5),
        fill="tozeroy", fillcolor="rgba(120,144,156,0.15)",
        name="BB Width", showlegend=True,
    ), row=5, col=1)
    fig.update_yaxes(title_text="BB Width", row=5, col=1)

    return fig


def print_snapshot(df: pd.DataFrame, ticker: str) -> None:
    last = df.iloc[-1]
    print(f"\n{'─'*46}")
    print(f"  {ticker} — latest indicator readings")
    print(f"{'─'*46}")
    print(f"  RSI (14)         : {last['rsi']:.1f}")
    print(f"  MACD hist        : {last['macd_hist']:+.4f}")
    print(f"  MACD / Signal    : {last['macd']:.4f} / {last['macd_signal']:.4f}")
    print(f"  Stoch %K / %D   : {last['stoch_k']:.1f} / {last['stoch_d']:.1f}")
    print(f"  BB %B            : {last['bb_pband']:.2f}  (>1=above upper, <0=below lower)")
    print(f"  SMA 20/50/200   : {last['sma20']:.2f} / {last['sma50']:.2f} / {last['sma200']:.2f}")
    print(f"{'─'*46}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-indicator technical analysis chart")
    parser.add_argument("ticker",                          help="Ticker (e.g. SPY, EURUSD=X, BTC-USD)")
    parser.add_argument("--period",      default="3y",    help="yfinance period (default: 3y)")
    parser.add_argument("--interval",    default="1d",    help="yfinance interval (default: 1d)")
    parser.add_argument("--bb",          type=int,   default=20,   help="Bollinger Band window")
    parser.add_argument("--bb-std",      type=float, default=2.0,  help="BB std deviation multiplier")
    parser.add_argument("--rsi",         type=int,   default=14,   help="RSI window")
    parser.add_argument("--macd-fast",   type=int,   default=12,   help="MACD fast EMA window")
    parser.add_argument("--macd-slow",   type=int,   default=26,   help="MACD slow EMA window")
    parser.add_argument("--macd-signal", type=int,   default=9,    help="MACD signal EMA window")
    parser.add_argument("--stoch-k",     type=int,   default=14,   help="Stoch %K window")
    parser.add_argument("--stoch-d",     type=int,   default=3,    help="Stoch %D smoothing window")
    parser.add_argument("--out",         default=None,              help="Output HTML path")
    args = parser.parse_args()

    TICKER = args.ticker.upper()
    print(f"Fetching {TICKER} ({args.period} / {args.interval})...")

    raw = yf.download(TICKER, period=args.period, interval=args.interval,
                      auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)

    df = compute_indicators(raw, args)
    print_snapshot(df, TICKER)

    fig = build_chart(df, TICKER)
    out = args.out or f"technical_{TICKER}.html"
    fig.write_html(out)
    print(f"Chart saved → {out}")
