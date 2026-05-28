---
description: Fetch OTM options chain (5 calls + 5 puts per expiry, round strikes 20-30% from spot) across current-year quarterly exps + Jan of next 2 years — outputs HTML file
---

Fetch an options chain for the ticker the user specifies.

# Script
`/Users/macproajb/claude_projects/options_chain/options_chain.py`

# Steps

1. Extract the ticker from the user's message. If none provided, ask for one.
2. Run:
```bash
python3 /Users/macproajb/claude_projects/options_chain/options_chain.py <TICKER>
```
3. Open the generated HTML file:
```bash
open options_chain_<TICKER>.html
```
4. Report: spot price, 52wk range, expiries covered, and any expiries that returned 0 rows (sparse OI is normal for far-dated).

# Output covers
- **Expiries:** Current-year Jun/Sep/Dec + next-year Jan + two-years-out Jan (matched to nearest available)
- **Strikes:** 5 OTM calls (20-30% above spot) + 5 OTM puts (20-30% below spot), round numbers
- **Columns:** Expiry, Type, Strike, Last, Bid, Ask, Open Interest
- **Header:** Spot, 52wk High, 52wk Low
