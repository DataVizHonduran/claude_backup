---
description: Global macro factor dashboard — indexed performance, correlation heatmap, scorecard, and relative strength for 26 factor/region ETFs
---

Generate a 4-panel HTML dashboard for the factor(s) the user specifies.

# Script
`/Users/macproajb/claude_projects/factor_map/factor_map.py`

# Steps

1. Parse from the user's message:
   - `FACTORS` — comma-separated factor names (default: `"US Momentum,US Value,EU Banks,Brazil Proxy"`)
   - `REBASE` — rebase date (default: 1 year ago)
   - `REL_A` — relative strength numerator (default: `"US Momentum"`)
   - `REL_B` — relative strength denominator (default: `"US Value"`)
2. Run:
```bash
python3 /Users/macproajb/claude_projects/factor_map/factor_map.py \
  --factors "FACTORS" \
  --rebase REBASE \
  --rel-a "REL_A" \
  --rel-b "REL_B"
```
3. The script prints the output HTML path. Run `open <path>`.
4. Report: factors charted, rebase date, rel-strength pair, file path. 2 lines max.

# Factor names (valid --factors / --rel-a / --rel-b values)
US Momentum, EU Momentum, JP Momentum, EM Momentum,
US Value, EU Value, JP Value, EM Value,
US Quality, EU Quality, JP Quality, EM Quality,
US Low Vol, EU Low Vol, JP Low Vol, EM Low Vol,
US Small Cap, EU Small Cap, JP Small Cap, EM Small Cap,
EU Banks, EU Resources, Brazil Proxy, JP Governance, JP Hedged Export, S&P 500

# Dashboard panels
| Panel | Content |
|-------|---------|
| 1 | Indexed performance — all selected factors rebased to 100 at REBASE date |
| 2 | Rolling 12M correlation heatmap (RdBu_r) |
| 3 | Factor scorecard — 1M / 3M / 12M / 3Y returns, green/red cell shading |
| 4 | Relative strength REL_A / REL_B — normalized ratio, filled area, gold line |

# Parameters
| Flag | Default | Notes |
|------|---------|-------|
| `--factors` | `"US Momentum,US Value,EU Banks,Brazil Proxy"` | Comma-separated, quote the whole string |
| `--rebase` | 1 year ago | `YYYY-MM-DD` |
| `--rel-a` | `"US Momentum"` | Numerator factor |
| `--rel-b` | `"US Value"` | Denominator factor |
| `--out` | auto | Custom output HTML path |
