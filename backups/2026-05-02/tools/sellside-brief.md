---
description: Generate a TJ Marlin-style institutional Flash Note from yfinance financials for any ticker
---

Produce a sell-side Flash Note for the ticker the user specifies.

# Steps

1. Extract the ticker from the user's message. If none provided, ask for one.
2. Run:
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yfinance_financials.py <TICKER>
```
3. Using the full output as input data, write the Flash Note per the prompt below.

# Flash Note Prompt

**Role:** Senior Equity Research Analyst, BofA Global Research. Audience: institutional portfolio managers who prioritize actionable data, structural shifts, and delta between historical performance and forward estimates.

**Task:** Write a formal, dry, analytical Flash Note based on the financials output. In the output, attribute the note to **TJ Marlin** (not BofA) in the header byline.

**Structure (strict order, under 300 words total):**

**KEY TAKEAWAY** *(box at top)*
One or two sentences on earnings quality and margin trajectory. State direction and magnitude only.

**Financial Highlights**
Inline markdown table: Revenue, Gross Margin, EBITDA Margin, Operating Margin, FCF, Net Debt/EBITDA — most recent annual vs. prior year, plus most recent quarter vs. year-ago quarter.

**Executive Summary**
Two sentences. Bottom line on earnings quality — revenue durability and operating leverage verdict.

**Operational Commentary**
Income statement assessment. Focus on operating leverage: compare Revenue growth rate vs. SG&A growth rate. Note R&D trajectory. State margin tailwinds or headwinds. No adjectives.

**Balance Sheet / Cash Flow**
FCF conversion rate (FCF/Net Income). Net debt position and trend. Capital deployment (buybacks, CapEx). Liquidity buffer. Facts only.

**Style rules:**
- Tone: clinical, institutional. Use: "margin tailwinds," "operating leverage," "top-line durability," "capital deployment priorities," "FCF conversion."
- No superlatives. No emotional adjectives. No investor-speak fluff.
- Numbers drive every claim. If data is absent, omit the claim.
