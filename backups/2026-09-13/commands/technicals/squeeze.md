---
description: Squeeze Momentum indicator — LazyBear BB/KC squeeze detection with 4-color momentum histogram for any stock or currency pair
---

Plot the Squeeze Momentum indicator for the ticker or currency pair the user specifies.

# Script
`/Users/macproajb/claude_projects/squeeze_momentum.py`

# Steps

1. Extract the ticker from the user's message. Uppercase it. For currencies use yfinance format (e.g. EURUSD=X, GBPUSD=X). Extract any optional overrides (period, interval, bb, bb-mult, kc-mult, mom).
2. Run:
```bash
python3 /Users/macproajb/claude_projects/squeeze_momentum.py <TICKER> [--period <P>] [--interval <I>] [--bb <N>] [--bb-mult <F>] [--kc-mult <F>] [--mom <N>]
```
3. The script prints the output HTML path. Run `open <path>` to launch it in the browser.
4. Report the squeeze ON bar count and file path. No lengthy summary.

# Parameters
| Flag | Default | Description |
|------|---------|-------------|
| `--period` | `1y` | yfinance period: `1d 5d 1mo 3mo 6mo 1y 2y 5y` |
| `--interval` | `1d` | yfinance interval: `1m 5m 15m 1h 1d 1wk 1mo` |
| `--bb` | `20` | Bollinger Band / Keltner Channel period |
| `--bb-mult` | `2.0` | BB standard deviation multiplier |
| `--kc-mult` | `1.5` | Keltner Channel ATR multiplier |
| `--mom` | `20` | Linear regression lookback for momentum |

# Chart legend
- **Lime green bars** — momentum positive and rising
- **Dark green bars** — momentum positive but falling
- **Red bars** — momentum negative and falling
- **Maroon bars** — momentum negative but rising (potential reversal)
- **Orange-red dots** on zero line — squeeze ON (BB inside KC, market coiling)
- **Silver dots** on zero line — squeeze OFF (BB expanded, energy released)
