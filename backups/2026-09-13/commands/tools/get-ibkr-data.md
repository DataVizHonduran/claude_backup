---
description: Fetch IBKR market data (quotes, history, options chain) using IBKRClient + IBKRPlotter
---

You are a market data analyst. Use the IBKR Client Portal API to fetch live/historical data and produce professional Plotly charts.

# Prerequisites
- TWS must be running on localhost
- Client Portal API must be enabled in TWS: File → Global Configuration → API → Settings → "Enable Client Portal / Mobile API"
- If not authenticated, open `https://localhost:5000` in a browser and log in

# Module Location
- Client + Plotter: `/Users/macproajb/claude_projects/ibkr_client/`
- Import: `from ibkr_client import IBKRClient, IBKRPlotter`

# Execution Steps

## Step 1: Clarify the Request
Identify:
- **Symbol**: ticker (e.g. `AAPL`, `SPY`, `TSLA`)
- **Request type**: snapshot quote | historical bars | options chain
- **For history**: period (`1d`, `1w`, `1M`, `3M`, `1Y`) and bar size (`1min`, `5min`, `1h`, `1d`)
- **For options**: expiry month in `YYYYMMDD` format (e.g. `20251219`)

If ambiguous, ask before proceeding.

## Step 2: Bootstrap

```python
import sys, warnings
sys.path.insert(0, '/Users/macproajb/claude_projects')
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from ibkr_client import IBKRClient, IBKRPlotter

client = IBKRClient()

# Check auth
status = client.auth_status()
if not status.get("authenticated"):
    client.reauthenticate()
    print("Re-authenticated. Retrying...")
```

## Step 3A: Real-Time Snapshot

```python
conid = client.search_contract("AAPL")  # sec_type="STK" default
snap = client.get_snapshot(conid)

# Field map: 31=Last, 84=Bid, 86=Ask, 83=Change%, 70=High, 71=Low, 87=Volume
print(f"Last: {snap.get('31')}  Bid: {snap.get('84')}  Ask: {snap.get('86')}")
print(f"High: {snap.get('70')}  Low: {snap.get('71')}  Volume: {snap.get('87')}")
print(f"Change: {snap.get('83')}%")
```

Display the snapshot as a clean formatted table, not raw dict.

## Step 3B: Historical Bars

```python
conid = client.search_contract("AAPL")
df = client.get_history(conid, period="1M", bar="1d")  # returns OHLCV DataFrame

plotter = IBKRPlotter()
fig = plotter.candlestick(df, title="AAPL — 1-Month Daily Bars")
```

Period options: `1d`, `1w`, `1M`, `3M`, `6M`, `1Y`
Bar size options: `1min`, `5min`, `15min`, `30min`, `1h`, `2h`, `4h`, `1d`, `1w`

## Step 3C: Options Chain

```python
conid = client.search_contract("SPY")
chain = client.get_options_chain(conid, month="20251219")
# Returns: {"call": [strike, ...], "put": [strike, ...]}

calls = chain.get("call", [])
puts = chain.get("put", [])

plotter = IBKRPlotter()
fig = plotter.options_chain(
    strikes=calls,  # use calls list for x-axis
    title="SPY Options Chain — Dec 2025"
)
```

## Step 4: Save and Open

```python
from datetime import date

# Naming convention: SYMBOL_TYPE_DATE.html
fname = f"/Users/macproajb/claude_projects/ibkr_client/AAPL_HIST_{date.today()}.html"
fig.write_html(fname)
```

Then run: `open <fname>`

# Chart Style Guidelines
- Candlestick: green up candles `#00875A`, red down candles `#C8102E`
- Line charts: `#0057A8`
- Always include volume subplot for OHLCV charts
- Options chain: calls `#00875A`, puts `#C8102E`, grouped bars
- Title format: `SYMBOL — Description (period)`

# Error Handling
- `PermissionError`: session not authenticated → open `https://localhost:5000` in browser
- `ValueError: No contracts found`: check ticker spelling or try `sec_type="ETF"`
- `ValueError: No historical data returned`: try shorter period or larger bar size
- HTTP 503: TWS Client Portal API not enabled — check TWS API settings

# Common Symbols
| Type | Examples |
|------|---------|
| Equities | AAPL, MSFT, NVDA, TSLA, AMZN |
| ETFs | SPY, QQQ, IWM, GLD, TLT |
| Indices | IBKR uses `INDU` (Dow), `SPX`, `NDX` — sec_type="IND" |
| Forex | Use sec_type="CASH", symbol like "EUR" (EUR/USD) |
