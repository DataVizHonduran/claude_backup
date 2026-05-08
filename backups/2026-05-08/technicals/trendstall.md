---
description: TrendStall indicator — ADX momentum exhaustion signals with paintbars and triangles for any stock or currency pair
---

Plot the TrendStall indicator for the ticker or currency pair the user specifies.

# Script
`/Users/macproajb/claude_projects/trendstall.py`

# Steps

1. Extract the ticker from the user's message. Uppercase it. For currencies use yfinance format (e.g. EURUSD=X, GBPUSD=X, JPY=X). Extract any optional overrides (period, interval, adx, roc, ma, threshold).
2. Run:
```bash
python3 /Users/macproajb/claude_projects/trendstall.py <TICKER> [--period <P>] [--interval <I>] [--adx <N>] [--roc <N>] [--ma <N>] [--threshold <F>]
```
3. The script prints the output HTML path. Run `open <path>` to launch it in the browser.
4. Report the stall signal count and file path. No lengthy summary.

# Parameters
| Flag | Default | Description |
|------|---------|-------------|
| `--period` | `1y` | yfinance period: `1d 5d 1mo 3mo 6mo 1y 2y 5y` |
| `--interval` | `1d` | yfinance interval: `1m 5m 15m 1h 1d 1wk 1mo` |
| `--adx` | `14` | Wilder's ADX smoothing period |
| `--roc` | `10` | ADX Rate of Change lookback |
| `--ma` | `5` | Moving average period applied to ADX ROC |
| `--threshold` | `0.5` | ROC level that confirms trend in place |

# Ticker formats
- Stocks: `SPY`, `AAPL`, `TSLA`
- FX pairs: `EURUSD=X`, `GBPUSD=X`, `USDJPY=X`
- Crypto: `BTC-USD`, `ETH-USD`
- Futures/indices: `^GSPC`, `^VIX`

# Chart legend
- **Sandy orange bars** — pre-stall: ADX ROC above threshold, trend confirmed, stall imminent
- **Purple bars** — post-stall: ADX ROC below its MA, stall continuation
- **Red triangle ▼ above bar** — stall in an uptrend (+DI > −DI)
- **Green triangle ▲ below bar** — stall in a downtrend (−DI > +DI)
- **Bottom histogram** — ADX ROC with MA overlay and threshold dashed line
