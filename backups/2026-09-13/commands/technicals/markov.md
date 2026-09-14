---
description: Markov chain regime analysis — discretize returns into states, build a transition probability matrix, stationary distribution, and next-period forecast for any stock or currency pair
---

Run a Markov chain regime analysis for the ticker the user specifies.

# Script
`/Users/macproajb/claude_projects/markov_chain.py`

# Steps

1. Extract the ticker from the user's message. Uppercase it. For currencies use yfinance format (e.g. `MXN=X` for USDMXN, `EURUSD=X`, `GBPUSD=X`). Default ticker is `MXN=X` (USDMXN). Extract any optional overrides (period, interval, states).
2. Run:
```bash
python3 /Users/macproajb/claude_projects/markov_chain.py <TICKER> [--period <P>] [--interval <I>] [--mode trend|quantile] [--ma-window <N>] [--band <F>] [--states <N>]
```
3. The script prints the transition matrix, stationary distribution, current state, next-period forecast, state-change frequency, and the output HTML path. Run `open <path>` to launch it in the browser.
4. Report: current state, next-period forecast probabilities, state changes/year, and the file path. No lengthy summary.

# Parameters
| Flag | Default | Description |
|------|---------|-------------|
| `--period` | `10y` | yfinance period: `1d 5d 1mo 3mo 6mo 1y 2y 5y 10y max` |
| `--interval` | `1d` | yfinance interval: `1m 5m 15m 1h 1d 1wk 1mo` |
| `--mode` | `trend` | State definition. `trend` = price vs. moving average with hysteresis (few regime changes/year, 3 states: Downtrend/Neutral/Uptrend). `quantile` = daily return quantiles (many changes/year, noisy) |
| `--ma-window` | `200` | [trend mode] moving average window |
| `--band` | `0.035` | [trend mode] hysteresis band as fraction of MA (e.g. `0.035` = 3.5%). Larger band = fewer, slower regime changes |
| `--states` | `5` | [quantile mode] number of equal-frequency return states (3, 4, or 5 get named labels; other N get Q1..QN) |
| `--out` | `markov_<TICKER>.html` | Output HTML path |

# Chart contents
- Price line with markers colored by regime/return-state (red = down, green = up)
- Transition probability matrix heatmap (row = current state, col = next state)
- Bar chart: long-run stationary distribution vs. next-period forecast from the current state

# Tuning state-change frequency (trend mode)
The script prints "state changes / year". For USDMXN at the default `--ma-window 200 --band 0.035`, this is ~5/year. Increase `--band` for fewer/slower changes, decrease for more/faster.
