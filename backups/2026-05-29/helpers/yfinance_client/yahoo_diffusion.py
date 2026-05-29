#!/usr/bin/env python3
"""
yahoo_diffusion.py  TICKER [TICKER2 ...] [--out PATH]

Computes a rolling diffusion index over 10y of daily data.
  near_high[t]: close >= 0.95 * 252d rolling max
  near_low[t]:  close <= 1.05 * 252d rolling min
  DI[t] = ((near_high_count - near_low_count) / N + 1) / 2 * 100
  Range: 0 (all near 52w lows) → 50 (neutral) → 100 (all near 52w highs)
"""

import sys
import argparse
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf
import plotly.graph_objects as go


WINDOW = 252  # trading days ≈ 1 year


def fetch_closes(tickers: list[str]) -> pd.DataFrame:
    raw = {}
    failed = []
    for t in tickers:
        df = yf.Ticker(t).history(period="10y", interval="1d", auto_adjust=True)
        if df.empty:
            failed.append(t)
            continue
        raw[t] = df["Close"]
    if failed:
        print(f"WARNING: no data for {failed}", file=sys.stderr)
    closes = pd.DataFrame(raw).ffill()
    return closes.dropna(how="all")


def compute_di(closes: pd.DataFrame) -> pd.Series:
    roll_high = closes.rolling(WINDOW, min_periods=WINDOW).max()
    roll_low  = closes.rolling(WINDOW, min_periods=WINDOW).min()
    near_high = (closes >= 0.95 * roll_high)
    near_low  = (closes <= 1.05 * roll_low)
    n = closes.shape[1]
    raw = (near_high.sum(axis=1) - near_low.sum(axis=1)) / n
    di = (raw + 1) / 2 * 100
    return di.dropna()


def snapshot(closes: pd.DataFrame, di: pd.Series) -> None:
    roll_high = closes.rolling(WINDOW, min_periods=WINDOW).max().iloc[-1]
    roll_low  = closes.rolling(WINDOW, min_periods=WINDOW).min().iloc[-1]
    last      = closes.iloc[-1]
    near_high = last >= 0.95 * roll_high
    near_low  = last <= 1.05 * roll_low

    rows = []
    for t in closes.columns:
        flag = "NEAR HIGH" if near_high[t] else ("NEAR LOW" if near_low[t] else "—")
        rows.append((t, f"{last[t]:.2f}", f"{roll_high[t]:.2f}", f"{roll_low[t]:.2f}", flag))

    header = f"{'Ticker':<8} {'Price':>9} {'52W High':>10} {'52W Low':>9}  Status"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(f"{row[0]:<8} {row[1]:>9} {row[2]:>10} {row[3]:>9}  {row[4]}")
    print(f"\nDiffusion Index (latest): {di.iloc[-1]:.1f}")


def fetch_etf(ticker: str) -> pd.Series:
    df = yf.Ticker(ticker).history(period="10y", interval="1d", auto_adjust=True)
    if df.empty:
        return pd.Series(dtype=float)
    pct = df["Close"].pct_change(periods=WINDOW) * 100
    return pct.rename(ticker)


def build_chart(di: pd.Series, tickers: list[str], etf_series: pd.Series | None = None) -> go.Figure:
    fig = go.Figure()

    # Background bands
    fig.add_hrect(y0=75, y1=100, fillcolor="rgba(0,180,80,0.10)", line_width=0)
    fig.add_hrect(y0=0,  y1=25,  fillcolor="rgba(220,50,50,0.10)",  line_width=0)

    # Reference lines
    for y, dash in [(50, "dash"), (75, "dot"), (25, "dot")]:
        fig.add_hline(y=y, line=dict(color="#bbb", dash=dash, width=1))

    # DI line (10-day MA)
    di_smooth = di.rolling(5, min_periods=1).mean()
    fig.add_trace(go.Scatter(
        x=di_smooth.index, y=di_smooth.values,
        mode="lines",
        line=dict(color="#0057A8", width=1.8),
        name="Diffusion Index",
        yaxis="y1",
        hovertemplate="%{x|%Y-%m-%d}: %{y:.1f}<extra></extra>",
    ))

    # ETF overlay on secondary axis
    if etf_series is not None and not etf_series.empty:
        aligned = etf_series.reindex(di.index, method="ffill").dropna()
        fig.add_trace(go.Scatter(
            x=aligned.index, y=aligned.values,
            mode="lines",
            line=dict(color="#E07B00", width=1.4),
            name=str(etf_series.name),
            yaxis="y2",
            hovertemplate="%{x|%Y-%m-%d}: %{y:.1f}%<extra></extra>",
        ))

    ticker_str = " / ".join(tickers[:6]) + ("…" if len(tickers) > 6 else "")
    etf_label = f" + {etf_series.name}" if etf_series is not None and not etf_series.empty else ""
    fig.update_layout(
        title=dict(text=f"Breadth Diffusion Index — {ticker_str}{etf_label}  ·  10y daily", font=dict(size=15, color="#222")),
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        yaxis=dict(title="Diffusion Index (0–100)", range=[0, 100], ticksuffix="", gridcolor="#e8e8e8", linecolor="#ccc"),
        yaxis2=dict(title=f"{etf_series.name} 52W % Chg" if etf_series is not None and not etf_series.empty else "",
                    overlaying="y", side="right", showgrid=False, ticksuffix="%", linecolor="#ccc") if etf_series is not None and not etf_series.empty else {},
        xaxis=dict(rangeslider_visible=False, gridcolor="#e8e8e8", linecolor="#ccc"),
        hovermode="x unified",
        margin=dict(l=60, r=70, t=70, b=40),
        height=460,
        legend=dict(orientation="h", y=1.05, x=0),
    )
    return fig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--out", default=None)
    parser.add_argument("--etf", default=None, help="ETF ticker to overlay on secondary axis")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers]
    closes = fetch_closes(tickers)
    if closes.empty:
        sys.exit("No data fetched.")

    di = compute_di(closes)
    snapshot(closes, di)

    etf_series = fetch_etf(args.etf.upper()) if args.etf else None
    fig = build_chart(di, list(closes.columns), etf_series=etf_series)
    tag = "_".join(closes.columns[:5])
    out = args.out or f"/Users/macproajb/claude_projects/yfinance_client/{tag}_diffusion_{date.today()}.html"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(out)
    print(f"\n{out}")


if __name__ == "__main__":
    main()
