---
description: US bank credit quality dashboard — net charge-off rates, delinquencies, and loans past due from FDIC call reports + FRED aggregates for the 8 major US banks
---

Pull credit quality metrics (NCO rate, NPL rate, 30/90-day past-due) for major US banks from FDIC call reports and render a 3-panel Plotly HTML dashboard.

## Arguments
`$ARGUMENTS` — optional space-separated tickers (default: all 8 banks)
Valid: `JPM BAC WFC C COF USB PNC TFC`

## Steps

1. Parse tickers from `$ARGUMENTS`. If none provided, use the 8-bank default.
2. Run:
```bash
python3 /Users/macproajb/claude_projects/bank_credit/extractor.py $ARGUMENTS
```
3. Capture stdout (JSON summary). Stderr shows progress — ignore it in your response.
4. Open the HTML file printed to stderr (`Saved → ...`):
```bash
open /Users/macproajb/claude_projects/bank_credit_quality_$(date +%Y%m%d).html
```
5. From the JSON summary, write a brief analysis (~4-6 sentences):
   - Which bank shows highest NCO rate and whether it's rising or falling QoQ
   - Any notable outliers in PD30/PD90 or NPL ratios vs peers
   - Whether stress is broad-based or concentrated (credit card lenders like COF vs mortgage-heavy banks)
   - Relate individual-bank levels to FRED aggregate trends if divergence is notable

## Data sources
- **FDIC BankFind Suite** — quarterly call report data, no API key required
  - `NTLNLSR` — annualized net charge-off rate (%)
  - `NCLNLSR` — noncurrent loan ratio / NPL rate (%)
  - `P3ASSET` / `P9ASSET` — 30-89d and 90+d past-due loans ($K) → converted to % of net loans
- **FRED** — industry aggregate delinquency and charge-off rates (DRCLACBS, DRCCLACBS, DRBLACBS, QBPLNTLNNTCGOFFR, CORCCACBS, CORCACBS)

## Output
- HTML dashboard saved to `/Users/macproajb/claude_projects/bank_credit_quality_{YYYYMMDD}.html`
  - Panel A: Latest-quarter table (all banks × 4 metrics, red/green stress coloring)
  - Panel B: 8-quarter NCO rate trend lines per bank
  - Panel C: 10-year FRED industry aggregate (delinquency + charge-off rates)
- JSON summary to stdout (used for text analysis above)

## Notes
- NTLNLSR is already annualized (YTD charge-offs / avg loans × 12/months × 100). Compare directly across quarters.
- P3ASSET and P9ASSET are end-of-period dollar amounts; the script divides by LNLSNET to produce PD30_PCT and PD90_PCT.
- Capital One (COF) typically has the highest NCO and delinquency rates among peers due to its credit-card-heavy portfolio — expected, not a red flag in isolation.
