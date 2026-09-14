---
description: Rolling Hurst exponent (R/S analysis) — trending vs mean-reverting regime detection for any stock, index, or currency pair
---

Plot the rolling Hurst exponent for the ticker the user specifies.

# Script
`/Users/macproajb/claude_projects/hurst_trendiness.py`

# Steps

1. Extract the ticker from the user's message. Uppercase it. Use yfinance format for FX (e.g. `EURUSD=X`, `JPY=X`) and crypto (`BTC-USD`). Extract any optional overrides (`--period`, `--interval`, `--window`, `--min-lag`, `--max-lag`, `--log-returns`).
2. Run:
```bash
python3 /Users/macproajb/claude_projects/hurst_trendiness.py <TICKER> [--period <P>] [--interval <I>] [--window <N>] [--min-lag <N>] [--max-lag <N>] [--log-returns]
```
3. The script prints the output HTML path. Run `open <path>` to launch it in the browser.
4. Report the last Hurst value, the regime (TRENDING / MEAN-REVERTING / RANDOM WALK), and the file path. No lengthy summary.

# Parameters
| Flag | Default | Description |
|------|---------|-------------|
| `--period` | `5y` | yfinance period: `1y 2y 5y 10y max` |
| `--interval` | `1wk` | yfinance interval: `1d 1wk 1mo` |
| `--window` | `40` | Rolling R/S window in bars |
| `--min-lag` | `2` | Min block size for R/S segments |
| `--max-lag` | `20` | Max block size for R/S segments |
| `--log-returns` | off | Transform price → log returns before computing H |

# Interpretation
- **H > 0.5 (green)** — persistent / trending: prior moves predict future direction
- **H ≈ 0.5 (gray)** — random walk: no memory, unpredictable
- **H < 0.5 (red)** — anti-persistent / mean-reverting: moves tend to reverse
