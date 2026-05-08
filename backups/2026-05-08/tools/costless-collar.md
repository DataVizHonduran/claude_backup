---
description: Compute costless collars for every liquid maturity for a given stock ticker — buy floor put, sell covering call, net cost ≈ 0
---

Find the costless collar structure for each liquid maturity for the ticker the user specifies.

# Steps

1. Extract the ticker from the user's message. If none provided, ask for one.
2. **Ask the user for the floor price** (the put strike they want protection at). Example: "What floor price do you want for the put? (e.g. $180 for AAPL)". Do not proceed until the user provides this.
3. Run:
```bash
python3 /Users/macproajb/claude_projects/options_chain/costless_collar.py <TICKER> <FLOOR_PRICE>
```
4. Open the generated HTML file:
```bash
open collar_<TICKER>.html
```
5. Report per expiry: put strike, put ask, call strike (cap), call bid, net cost, and flag any "partial" rows where no single call fully covers the put premium.

# What it does
For each liquid maturity (current-year Mar/Jun/Sep/Dec + next Jan + two-years-out Jan):
- **Put leg:** Finds the strike nearest to the user's floor price
- **Call leg:** Walks OTM calls to find the lowest strike whose bid ≥ put ask (zero-net-cost condition)
- **Fallback:** If no call fully covers, shows best partial cover with a "partial" badge
- **Net cost:** put ask − call bid (negative = credit, positive = debit)

# Output columns
| Column | Meaning |
|--------|---------|
| Expiry / DTE | Maturity date and days to expiration |
| Put Strike | Nearest to floor input; % vs spot shown |
| Put Ask | Cost of downside protection |
| Call Strike (Cap) | Upside cap level; % vs spot shown |
| Call Bid | Premium received from selling the call |
| Net Cost | Credit / Even / Debit + partial badge if no full cover |
