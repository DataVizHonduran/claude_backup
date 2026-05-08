---
description: Rolling breadth diffusion index — % of tickers near 52w high vs low, 10y history via yfinance. Range 0 (all near lows) to 100 (all near highs).
---

Compute a rolling diffusion index for the ticker list the user supplies.

# Script
`/Users/macproajb/claude_projects/yfinance_client/yahoo_diffusion.py`

# Steps

1. Extract the list of tickers from the user's message. Must be at least 2.
   - If user passes a single ETF ticker, ALWAYS fetch its full constituent list dynamically — never hardcode a partial list. Use this Python snippet to get constituents:
     - **S&P 500 (VOO, SPY, IVV)**: scrape Wikipedia `List_of_S%26P_500_companies`, column `Symbol`, replace `.` with `-`.
     - **Other ETFs**: use `pip show etf-data` or `yfinance` ETF info, or scrape the ETF provider's holdings page.
     - Pass all fetched tickers to the script and add `--etf <ETF>` to overlay the ETF price.
   - Example for VOO/SPY/IVV:
     ```python
     import urllib.request, pandas as pd, io
     req = urllib.request.Request('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'})
     html = urllib.request.urlopen(req).read()
     tickers = pd.read_html(io.BytesIO(html))[0]['Symbol'].str.replace('.', '-', regex=False).tolist()
     ```
2. Run:
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yahoo_diffusion.py TICKER1 TICKER2 [...] [--etf ETF] [--out PATH]
```
3. The script prints a per-ticker snapshot table and the current DI value, then the HTML path. Run `open <path>`.
4. Report: current DI reading, which tickers are near highs/lows, and the output path. Keep it brief.

# Formula
- near_high: close ≥ 0.95 × 252-day rolling max
- near_low:  close ≤ 1.05 × 252-day rolling min
- DI = ((near_high_count − near_low_count) / N + 1) / 2 × 100
- 100 = all tickers near 52w highs, 0 = all near 52w lows, 50 = neutral

# Chart features
- 10y daily time series, white background
- Green band > 75, red band < 25, dashed guides at 25/50/75
- Hover shows exact DI per date
- `--etf ETF`: overlays ETF price on secondary right-hand axis (orange line)
