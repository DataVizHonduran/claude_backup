import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def compute_mas(close: pd.Series, periods: list[int], ma_type: str = "sma") -> pd.DataFrame:
    ma_df = pd.DataFrame(index=close.index)
    for p in periods:
        if ma_type == "ema":
            ma_df[f"MA{p}"] = close.ewm(span=p, adjust=False).mean()
        else:
            ma_df[f"MA{p}"] = close.rolling(p).mean()
    return ma_df


def compute_momentum_score(ma_df: pd.DataFrame) -> pd.Series:
    """Spearman rank correlation between MA period order and MA value order, sign-flipped.

    +1 = perfect bullish stack (MA10 highest ... MA200 lowest)
    -1 = perfect bearish stack (MA10 lowest ... MA200 highest)
    """
    n = ma_df.shape[1]
    value_rank = ma_df.rank(axis=1)
    period_rank = pd.Series(np.arange(1, n + 1), index=ma_df.columns)
    d2 = (value_rank - period_rank) ** 2
    rho = 1 - 6 * d2.sum(axis=1) / (n * (n**2 - 1))
    return -rho


def log_periods(start: int, stop: int, n: int) -> list[int]:
    """Geometrically-spaced MA periods from start to stop (n values)."""
    ratio = (stop / start) ** (1 / (n - 1))
    periods = sorted({round(start * ratio**i) for i in range(n)})
    periods[0], periods[-1] = start, stop
    return periods


def classify(score: float, threshold: float) -> str:
    if score >= threshold:
        return "Strong Bullish"
    elif score >= 0.5:
        return "Bullish"
    elif score <= -threshold:
        return "Strong Bearish"
    elif score <= -0.5:
        return "Bearish"
    else:
        return "Neutral"


BACKTEST_DIRECTION = {
    "Strong Bullish": 1, "Bullish": 1, "Neutral": 0, "Bearish": -1, "Strong Bearish": -1,
}


def backtest_table_html(close: pd.Series, periods: list[int], threshold: float,
                         smooth: int, stride: int = 10,
                         horizons: range = range(5, 61, 5)) -> str:
    """HTML table: hit rate / avg / median forward return by signal bucket and horizon."""
    ma_df = compute_mas(close, periods, "sma")
    score = compute_momentum_score(ma_df)
    if smooth > 1:
        score = score.ewm(span=smooth, adjust=False).mean()
    cat = score.apply(lambda s: classify(s, threshold)).iloc[::stride]
    fwd = {h: close.shift(-h) / close - 1 for h in horizons}

    header = "".join(f"<th>{h}d</th>" for h in horizons)
    body_rows = []
    for c in ["Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish"]:
        mask = cat == c
        if mask.sum() == 0:
            continue
        d = BACKTEST_DIRECTION[c]
        cells = []
        for h in horizons:
            r = fwd[h].reindex(cat.index)[mask].dropna()
            if len(r) == 0:
                cells.append("<td>—</td>")
                continue
            hit = ((r > 0) if d >= 0 else (r < 0)).mean() * 100
            cells.append(f"<td>{hit:.0f}% / {r.mean()*100:+.2f}% / {r.median()*100:+.2f}%</td>")
        body_rows.append(f"<tr><td><b>{c}</b></td>{''.join(cells)}</tr>")

    return f"""<table class="backtest-table">
<thead><tr><th>Signal</th>{header}</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>"""


def event_study_html(close: pd.Series, periods: list[int], smooth: int = 5, min_gap: int = 60,
                      horizons: tuple = (20, 40, 60, 90, 120, 180, 240, 300, 360)) -> str:
    """HTML table: forward returns from the day the score first crosses a threshold."""
    ma_df = compute_mas(close, periods, "sma")
    score = compute_momentum_score(ma_df)
    if smooth > 1:
        score = score.ewm(span=smooth, adjust=False).mean()
    prev = score.shift(1)
    fwd = {h: close.shift(-h) / close - 1 for h in horizons}

    def find_events(cond):
        dates = score.index[cond.fillna(False)]
        kept, last = [], None
        for d in dates:
            if last is None or (d - last).days >= min_gap:
                kept.append(d)
                last = d
        return kept

    event_defs = [
        ("Cross &rarr; Bullish (+0.50)", (prev < 0.5) & (score >= 0.5), 1),
        ("Cross &rarr; Strong Bullish (+0.85)", (prev < 0.85) & (score >= 0.85), 1),
        ("Cross &rarr; Bearish (-0.50)", (prev > -0.5) & (score <= -0.5), -1),
        ("Cross &rarr; Strong Bearish (-0.85)", (prev > -0.85) & (score <= -0.85), -1),
    ]

    header = "".join(f"<th>{h}d</th>" for h in horizons)
    body_rows = []
    for label, cond, direction in event_defs:
        events = find_events(cond)
        cells = []
        for h in horizons:
            r = fwd[h].reindex(events).dropna()
            if len(r) == 0:
                cells.append("<td>—</td>")
                continue
            hit = ((r > 0) if direction == 1 else (r < 0)).mean() * 100
            cells.append(f"<td>{hit:.0f}% / {r.mean()*100:+.2f}% / {r.median()*100:+.2f}%</td>")
        body_rows.append(f"<tr><td><b>{label}</b> (n={len(events)})</td>{''.join(cells)}</tr>")

    return f"""<table class="backtest-table">
<thead><tr><th>Event</th>{header}</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>"""


def gradient_colors(n: int, start_rgb=(70, 130, 180), end_rgb=(220, 80, 60)) -> list[str]:
    """Cool (short MA) -> warm (long MA) ribbon colors."""
    colors = []
    for i in range(n):
        t = i / (n - 1)
        rgb = tuple(int(start_rgb[j] + (end_rgb[j] - start_rgb[j]) * t) for j in range(3))
        colors.append(f"rgb({rgb[0]},{rgb[1]},{rgb[2]})")
    return colors


def plot_ribbon(close: pd.Series, ma_df: pd.DataFrame, momentum_score: pd.Series,
                ticker: str, threshold: float, variant_label: str = "") -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.04,
    )

    fig.add_trace(go.Scatter(
        x=close.index, y=close.values,
        line=dict(color="#111111", width=1.5),
        name=ticker,
    ), row=1, col=1)

    colors = gradient_colors(ma_df.shape[1])
    for col, color in zip(ma_df.columns, colors):
        fig.add_trace(go.Scatter(
            x=ma_df.index, y=ma_df[col],
            line=dict(color=color, width=1),
            opacity=0.8,
            name=col,
        ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=momentum_score.index, y=momentum_score.values,
        line=dict(color="#000000", width=3),
        name="Momentum Score",
        showlegend=False,
    ), row=2, col=1)

    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=2, col=1)
    fig.add_hline(y=threshold, line_dash="dash", line_color="#00FF00", row=2, col=1)
    fig.add_hline(y=-threshold, line_dash="dash", line_color="#FF0000", row=2, col=1)

    last_date = close.index[-1]
    first_date = close.index[0]
    price_panel = pd.concat([close.rename("Price"), ma_df], axis=1)
    range_buttons = []
    for label, yrs in [("1y", 1), ("2y", 2), ("3y", 3), ("5y", 5), ("10y", 10), ("15y", 15), ("20y", 20)]:
        start = max(last_date - pd.DateOffset(years=yrs), first_date)
        window = price_panel.loc[price_panel.index >= start]
        y_min, y_max = window.min().min(), window.max().max()
        pad = (y_max - y_min) * 0.05
        range_buttons.append(dict(
            label=label,
            method="relayout",
            args=[{
                "xaxis.range": [start, last_date],
                "xaxis2.range": [start, last_date],
                "yaxis.range": [y_min - pad, y_max + pad],
                "yaxis.autorange": False,
            }],
        ))

    last_score = momentum_score.iloc[-1]
    title_main = f"<b>{ticker} — MA Ribbon Momentum</b>"
    if variant_label:
        title_main += f" <span style='font-size:12px;color:#999'>({variant_label})</span>"
    fig.update_layout(
        title=(
            f"{title_main}<br>"
            f"<span style='font-size:13px;color:#555'>"
            f"Score: <b>{last_score:.2f}</b> ({classify(last_score, threshold)})</span>"
        ),
        template="plotly_white",
        height=820,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=9)),
        margin=dict(t=150),
        updatemenus=[dict(
            type="buttons",
            direction="right",
            x=0.0, y=1.18,
            xanchor="left", yanchor="top",
            buttons=range_buttons,
            bgcolor="#f0f0f0",
            bordercolor="#cccccc",
            font=dict(size=11),
            showactive=True,
        )],
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Momentum Score", range=[-1.05, 1.05], row=2, col=1)
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def build_html(tabs: list[dict], ticker: str, last_date: str, backtest_html: str = "", event_html: str = "") -> str:
    """tabs: list of {"id", "label", "fig"} dicts. First tab renders active."""
    buttons, contents = [], []
    for i, tab in enumerate(tabs):
        active = " active" if i == 0 else ""
        buttons.append(
            f'<button class="tab-btn{active}" onclick="showTab(\'{tab["id"]}\', this)">{tab["label"]}</button>'
        )
        chart_html = tab["fig"].to_html(
            include_plotlyjs=("cdn" if i == 0 else False),
            full_html=False, div_id=f"chart-{tab['id']}",
            config={"displayModeBar": True, "scrollZoom": True},
        )
        contents.append(f'<div id="tab-{tab["id"]}" class="tab-content{active}">{chart_html}</div>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>USD MA Ribbon Momentum | boquin.xyz</title>
<style>
  body {{ margin: 0; font-family: Inter, sans-serif; background: #fff; color: #111; }}
  .header {{ padding: 18px 24px 0; border-bottom: 1px solid #eee; }}
  .header a {{ text-decoration: none; color: #0066cc; font-size: 13px; }}
  .meta {{ padding: 6px 24px 12px; font-size: 12px; color: #888; }}
  .tabs {{ display: flex; gap: 8px; padding: 0 24px 8px; }}
  .tab-btn {{ padding: 8px 16px; border: 1px solid #ccc; background: #f0f0f0; color: #333;
              cursor: pointer; border-radius: 4px; font-size: 13px; font-family: inherit; }}
  .tab-btn.active {{ background: #0066cc; color: #fff; border-color: #0066cc; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  .chart-wrap {{ padding: 0 16px 24px; }}
  .footnote {{ padding: 0 24px 24px; font-size: 11px; color: #888; line-height: 1.6; }}
  .footnote b {{ color: #333; }}
  .backtest-table {{ border-collapse: collapse; margin: 8px 0; font-size: 10px; }}
  .backtest-table th, .backtest-table td {{ border: 1px solid #ddd; padding: 4px 6px; text-align: center; white-space: nowrap; }}
  .backtest-table th {{ background: #f5f5f5; color: #555; }}
  .backtest-table td:first-child, .backtest-table th:first-child {{ text-align: left; }}
</style>
</head>
<body>
<div class="header"><a href="/">← boquin.xyz</a></div>
<div class="meta">Last updated: {last_date} &nbsp;·&nbsp; Data: Yahoo Finance ({ticker})</div>
<div class="tabs">{''.join(buttons)}</div>
<div class="chart-wrap">{''.join(contents)}</div>
<div class="footnote">
  <b>Momentum Score</b> = Spearman rank correlation between MA period order and MA value order, sign-flipped, smoothed with a 5-day EMA.
  +1 = perfect bullish stack (shortest MA highest ... longest MA lowest). -1 = perfect bearish stack (reverse).
  <br><br>
  <b>How to trade this:</b>
  Score &gt; 0.85 or &lt; -0.85 = strong trend — bias long USD pairs in the stack's direction (long DXY/UUP, or short EURUSD/AUDUSD/gold on bullish reads, and the reverse on bearish reads).
  |Score| &lt; 0.5 = ribbon tangled, no trend — avoid trend-following USD trades, range/mean-reversion regime instead.
  Use the score as a <b>filter</b>, not a standalone trigger: only take breakout/pullback entries that agree with its sign — it's built from lagging MAs.
  A cross through 0 flags an early regime shift; crossing ±0.5 flags the trend strengthening or weakening, useful for scaling in/out.
  <b>Divergence</b> — price makes a new high/low while the score rolls over — signals fading momentum: tighten stops, watch for reversal.
  Ribbon shape (top panel): wide and ordered = trend has room to run; compressed/crossing = consolidation, often resolves into a breakout in the direction the score confirms.
  <br><br>
  <b>Fancier Steps tab</b> — uses geometrically (log) spaced MA periods instead of linear 10-day steps. Adjacent linear MAs (e.g. MA110 vs MA120) move almost in lockstep,
  adding redundancy and noise to the rank ordering. Log spacing makes each MA represent a genuinely distinct timeframe, giving a less choppy, more information-dense score
  at the cost of a sparser-looking ribbon.
  <br><br>
  <b>Backtest (Linear ribbon, 2004–present, sampled every 10 days):</b> forward-return stats by signal bucket. Cell = Hit Rate / Avg Return / Median Return,
  where "hit" = price moved in the direction the bucket favors (up for Bullish/Strong Bullish, down for Bearish/Strong Bearish).
  Edge is strongest in the 5–35d range and decays toward breakeven by 40–60d.
  {backtest_html}
  <br>
  <b>Event study — regime-shift entries:</b> instead of averaging every day in a bucket, this looks only at the day the score first
  crosses a threshold (debounced 60+ trading days apart), then tracks forward returns. Cell = Hit Rate / Avg Return / Median Return.
  Bullish crossings show real follow-through for 1–4 months before fading; bearish/strong-bearish crossings are weaker and often contrarian
  (extreme bearish reads tend to mark lows, not accelerate declines).
  {event_html}
</div>
<script>
function showTab(id, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
  var gd = document.getElementById('chart-' + id);
  if (gd && window.Plotly) {{ Plotly.Plots.resize(gd); }}
}}
</script>
</body>
</html>"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Moving-average ribbon momentum indicator")
    parser.add_argument("ticker", nargs="?", default="DX-Y.NYB",
                         help="yfinance ticker (default: DX-Y.NYB, the broad USD index)")
    parser.add_argument("--period", default=None, help="yfinance period (overridden by --start if set)")
    parser.add_argument("--start", default="2004-01-01", help="start date YYYY-MM-DD (default: 2004-01-01)")
    parser.add_argument("--interval", default="1d", help="yfinance interval (default: 1d)")
    parser.add_argument("--step", type=int, default=10, help="MA period step (default: 10)")
    parser.add_argument("--max-period", type=int, default=200, help="longest MA period (default: 200)")
    parser.add_argument("--ma-type", choices=["sma", "ema"], default="sma", help="moving average type")
    parser.add_argument("--threshold", type=float, default=0.85, help="strong-momentum score threshold")
    parser.add_argument("--fancy-count", type=int, default=8, help="number of MAs in the log-spaced 'Fancier Steps' tab")
    parser.add_argument("--smooth", type=int, default=5, help="EMA smoothing span applied to the momentum score (default: 5, 1=off)")
    parser.add_argument("--out", default=None, help="output HTML path")
    args = parser.parse_args()

    TICKER = args.ticker.upper()

    if args.period:
        print(f"Fetching {TICKER} ({args.period} / {args.interval})...")
        raw = yf.download(TICKER, period=args.period, interval=args.interval,
                           auto_adjust=True, progress=False)
    else:
        print(f"Fetching {TICKER} (from {args.start} / {args.interval})...")
        raw = yf.download(TICKER, start=args.start, interval=args.interval,
                           auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close = raw["Close"].dropna()
    print(f"  {close.index[0].date()} -> {close.index[-1].date()}  ({len(close)} rows)")

    variants = [
        ("linear", f"10–{args.max_period} (step {args.step})",
         list(range(args.step, args.max_period + args.step, args.step)), "Linear steps"),
        ("fancy", "Fancier Steps",
         log_periods(args.step, args.max_period, args.fancy_count), "Fancier Steps — log-spaced"),
    ]

    tabs = []
    for tab_id, tab_label, periods, variant_label in variants:
        ma_df = compute_mas(close, periods, args.ma_type)
        momentum_score = compute_momentum_score(ma_df)
        if args.smooth > 1:
            momentum_score = momentum_score.ewm(span=args.smooth, adjust=False).mean()

        last_score = momentum_score.iloc[-1]
        last_label = classify(last_score, args.threshold)
        last_mas = ma_df.iloc[-1].values
        stack_count = int(np.sum(last_mas[:-1] > last_mas[1:]))
        print(f"[{tab_label}] periods={periods}")
        print(f"[{tab_label}] Momentum score: {last_score:.2f} ({last_label}) | "
              f"Stack: {stack_count}/{len(periods) - 1} adjacent MAs descending")

        fig = plot_ribbon(close, ma_df, momentum_score, TICKER, args.threshold, variant_label)
        tabs.append({"id": tab_id, "label": tab_label, "fig": fig})

    linear_periods = list(range(args.step, args.max_period + args.step, args.step))
    backtest_html = backtest_table_html(close, linear_periods, args.threshold, args.smooth)
    event_html = event_study_html(close, linear_periods, args.smooth)

    html = build_html(tabs, TICKER, close.index[-1].strftime("%B %d, %Y"), backtest_html, event_html)
    out = args.out or f"/Users/macproajb/claude_projects/momentum_ribbon_{TICKER}.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Chart saved -> {out}")
