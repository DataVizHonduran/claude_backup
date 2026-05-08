---
description: Pull curated income statement, balance sheet, and cash flow for any ticker via yfinance
---

Fetch financials for the ticker the user specifies (or asks about).

# Script
`/Users/macproajb/claude_projects/yfinance_client/yfinance_financials.py`

# Steps

1. Extract the ticker from the user's message. If none provided, ask for one.
2. Run:
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yfinance_financials.py <TICKER>
```
3. Display the output. Briefly highlight any notable figures (e.g. FCF trend, revenue growth, margin expansion) in 2-3 sentences max.

# Output covers (USD billions unless noted)
**Income:** Total Revenue, Gross Profit, R&D, SG&A, Operating Income, EBITDA, Interest Expense, Tax Provision, Net Income, Normalized Income, Normalized EBITDA, Diluted EPS, Basic EPS
**Balance:** Cash & Equivalents, Short-Term Investments, Current Assets, Current Liabilities, Total Assets, Net PPE, Goodwill & Intangibles, Total Debt, Net Debt, Total Equity, Retained Earnings, Shares Outstanding
**Cash Flow:** Operating Cash Flow, Free Cash Flow, SBC, D&A, Working Capital Change, CapEx, Investing CF, Financing CF, Buybacks, End Cash

Both annual (4 years) and quarterly (5 quarters) for all three statements.
**Ratios (Annual & Quarterly):** Gross/Operating/EBITDA/Norm.EBITDA/Net/FCF Margins, R&D%, SG&A%, FCF & OCF Conversion, ROE, Net Debt/Norm.EBITDA, Revenue/EBITDA/FCF Growth (YoY annual, QoQ quarterly)
