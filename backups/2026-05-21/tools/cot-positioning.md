---
description: Generate CFTC COT positioning snapshot grouped by asset class — current/1W/4W/52W-high/52W-low as % of OI, with commentary on extremes and aggressive shifts
---

Generate a CFTC COT positioning report and open it in the browser.

# Script location
`/Users/macproajb/claude_projects/scripts/cot_positioning_report.py`

# Execution

## Step 1: Run from the project root

```bash
cd /Users/macproajb/claude_projects && python3 scripts/cot_positioning_report.py
```

Default: fetches last 2 years of data across all 4 sectors (Currencies, Rates, Equities, Commodities).

To restrict sectors or change the lookback, call `run()` directly:

```python
import sys; sys.path.insert(0, '/Users/macproajb/claude_projects/scripts')
from cot_positioning_report import run

# Examples:
run(sectors=["Currencies", "Equities"])             # subset of sectors
run(sectors=["Commodities"], lookback_years=3)      # longer 52W baseline
```

## Step 2: Open the report

```bash
open /Users/macproajb/claude_projects/reports/cot-positioning/index.html
```

## Step 3: Report to the user

Print:
- As-of date
- Number of markets covered
- Number of commentary notes
- Path to the HTML file

# What the report contains

**Table (per sector):** Markets × Categories with columns:
`Current (%)` | `1W Ago (%)` | `WoW Δ (pp)` | `4W Ago (%)` | `4W Δ (pp)` | `52W High (%)` | `52W Low (%)`

- Green = net long, Red = net short
- Highlighted cells = position in top/bottom 5% of 52W range

**Commentary section** flags:
- **52W Long/Short Extreme** — current in top or bottom 5% of the 52W positioning range
- **Aggressive 1W shift** — WoW move ≥ 5pp of OI
- **Sustained 4W repositioning** — 4W move ≥ 15pp of OI (not already flagged for WoW)

# Output locations
- **HTML report**: `/Users/macproajb/claude_projects/reports/cot-positioning/index.html`

# Trader classification
| Category    | TFF (Currencies/Rates/Equities) | Disaggregated (Commodities) |
|-------------|--------------------------------|-----------------------------|
| Commercial  | Dealers                        | Prod/Merch + Swap Dealers   |
| Speculator  | Asset Managers + Leveraged Funds | Managed Money              |
| Other       | Other Reportables              | Other Reportables           |
