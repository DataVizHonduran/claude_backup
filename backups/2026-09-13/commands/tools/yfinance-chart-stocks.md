---
description: Chart stock price history for one or more tickers via yfinance — interactive Plotly HTML
---

Fetch price history and render an interactive line chart for the ticker(s) the user specifies.

# Script
`/Users/macproajb/claude_projects/yfinance_client/yfinance_chart_stocks.py`

# Steps

1. Extract ticker(s), period, interval, and mode from the user's message. Defaults: `--period 1y --interval 1d`.
2. Run:
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yfinance_chart_stocks.py <TICKER> [TICKER2 ...] [--period <P>] [--interval <I>] [--drawdown] [--correlation] [--window N]
```
3. The script prints the output HTML path. Run `open <path>` to launch it in the browser.
4. Report the path and note period/interval used. No lengthy summary needed.

# Parameters
| Flag | Default | Options |
|------|---------|---------|
| `--period` | `1y` | `1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max` |
| `--interval` | `1d` | `1m 2m 5m 15m 30m 60m 90m 1h 1d 5d 1wk 1mo 3mo` |
| `--drawdown` | off | Plot % drawdown from rolling high instead of price |
| `--correlation` | off | Plot rolling Pearson r between exactly 2 tickers |
| `--window` | `200` | Rolling window size for `--correlation` |
| `--out` | auto | Custom output HTML path |

# Chart features
- Single ticker: price line + volume subplot, dark theme
- Multiple tickers: overlaid price lines, shared x-axis, no volume
- `--correlation`: Pearson r line, dark theme, y-axis [-0.3, 1.1], requires exactly 2 tickers
- Title format: `TICKER1 / TICKER2 · period (interval bars)`
- Colors cycle through: blue, orange, green, red, purple, gold, teal
