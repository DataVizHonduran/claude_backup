---
description: Technical analysis dashboard — Bollinger Bands, RSI, Slow Stochastics, MACD, SMA/EMA overlays for any stock or currency pair
---

Plot a multi-panel technical analysis chart for the ticker or currency pair the user specifies.

# Script
`/Users/macproajb/claude_projects/technical_analyst.py`

# Steps

1. Extract the ticker from the user's message. Uppercase it. For currencies use yfinance format (e.g. EURUSD=X, GBPUSD=X). Extract any optional overrides (period, interval, bb, bb-std, rsi, macd-fast, macd-slow, macd-signal, stoch-k, stoch-d).
2. Run:
```bash
python3 /Users/macproajb/claude_projects/technical_analyst.py <TICKER> [--period <P>] [--interval <I>] [--bb <N>] [--bb-std <F>] [--rsi <N>] [--macd-fast <N>] [--macd-slow <N>] [--macd-signal <N>] [--stoch-k <N>] [--stoch-d <N>]
```
3. The script prints an indicator snapshot table and the output HTML path. Run `open <path>` to launch it in the browser.
4. Report the indicator readings from stdout (RSI, MACD, Stoch %K/%D, BB %B). No lengthy summary.

# Parameters
| Flag | Default | Description |
|------|---------|-------------|
| `--period` | `1y` | yfinance period: `1d 5d 1mo 3mo 6mo 1y 2y 5y` |
| `--interval` | `1d` | yfinance interval: `1m 5m 15m 1h 1d 1wk 1mo` |
| `--bb` | `20` | Bollinger Band window |
| `--bb-std` | `2.0` | BB standard deviation multiplier |
| `--rsi` | `14` | RSI lookback window |
| `--macd-fast` | `12` | MACD fast EMA window |
| `--macd-slow` | `26` | MACD slow EMA window |
| `--macd-signal` | `9` | MACD signal EMA window |
| `--stoch-k` | `14` | Slow Stochastic %K window |
| `--stoch-d` | `3` | Stochastic %D smoothing window |

# Chart panels
- **Panel 1 (Price)** — Candlestick + Bollinger Bands (shaded) + SMA 20/50/200 + EMA 9/21
- **Panel 2 (MACD)** — Histogram (green/red) + MACD line (blue) + Signal line (orange)
- **Panel 3 (RSI)** — RSI line with 70/50/30 reference lines
- **Panel 4 (Stoch)** — %K (blue) and %D (red dashed) with 80/20 reference lines

# Ticker formats
- Stocks: `SPY`, `AAPL`, `TSLA`
- FX pairs: `EURUSD=X`, `GBPUSD=X`, `USDJPY=X`
- Crypto: `BTC-USD`, `ETH-USD`
- Indices: `^GSPC`, `^VIX`, `^NDX`
