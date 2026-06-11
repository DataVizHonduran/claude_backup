---
description: Fetch FDIC BankFind data (institution search, financials, failures, industry summary) and generate financial charts using FDICClient + FDICPlotter
---

You are a banking data analyst. Fetch data from the FDIC BankFind Suite API and produce professional financial charts. No API key required.

# Module Location
- Client + Plotter: `/Users/macproajb/claude_projects/fdic_client/`
- Import: `from fdic_client import FDICClient, FDICPlotter`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Task type**: institution search, financial time-series, failure data, or industry-wide summary
- **Bank identifier**: name string (for search) or FDIC cert number (for financials)
- **Fields**: which financial metrics (see reference table below)
- **Date range**: default last 10 years
- **Chart type**: `line`, `dual_axis`, `bar`, or `failures_timeline`

If the user gives a bank name but not a cert, search first then use the cert.

## Step 2: Setup

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from fdic_client import FDICClient, FDICPlotter

client = FDICClient()
```

## Step 3: Fetch the Data

### Find a bank's FDIC cert number
```python
df = client.search_institutions(name="Silicon Valley Bank", active=False)
print(df[["CERT", "INSTNAME", "CITY", "STNAME", "ASSET"]])
```

### Quarterly financials for one bank
```python
df = client.get_financials(
    cert=628,  # JPMorgan Chase
    fields="REPDTE,ASSET,DEP,NETINC,ROA,ROE,TIER1",
    start_date="2015-01-01",
)
```

### Same field across multiple banks (cross-bank comparison)
```python
df = client.get_multi_financials(
    certs=[628, 3510, 3511],  # JPM, BAC, WFC
    field="ROA",
    start_date="2015-01-01",
)
```

### Bank failure data
```python
df = client.get_failures(start_year=2008, end_year=2012)  # GFC failures
df = client.get_failures(state="TX")                       # Texas only
```

### Industry-wide aggregate statistics (annual national totals)
```python
df = client.get_industry_summary(
    fields="REPDTE,ASSET,DEP,NETINC,LNLS,NTLNLS,NCLNLS,EQ",
    start_year=2010,
)
# Note: summary is annual $-amounts, not ratios. Compute NCO rate: df["NTLNLS"] / df["LNLS"] * 100
```

## Step 4: Chart the Data

**Single series / multiple series, same scale:**
```python
plotter = FDICPlotter(df[["ROA"]], title="JPMorgan ROA (%)")
fig = plotter.line(value_fmt="%{y:.2f}%", y_label="Return on Assets (%)")
fig.show()
```

**Two metrics on different scales:**
```python
plotter = FDICPlotter(df, title="JPMorgan: Total Assets vs. ROA")
fig = plotter.dual_axis(
    left_col="ASSET", right_col="ROA",
    left_fmt="%{y:,.0f}", right_fmt="%{y:.2f}%",
    left_label="Total Assets ($000s)", right_label="ROA (%)"
)
fig.show()
```

**Cross-bank bar comparison (latest snapshot):**
```python
latest = df.tail(1)  # or select a specific quarter
plotter = FDICPlotter(latest.T, title="ROA Comparison — Latest Quarter")
fig = plotter.bar(value_fmt="%{y:.2f}%", y_label="ROA (%)")
fig.show()
```

**Bank failures timeline:**
```python
failures = client.get_failures(start_year=2000)
plotter = FDICPlotter(failures, title="US Bank Failures by Year")
fig = plotter.failures_timeline()
fig.show()
```

## Step 5: Save and Open
Save to `/Users/macproajb/claude_projects/fdic_client/` using this naming convention:
- Single bank: `CERT_FIELD_DATE.html` → `628_ROA_2026-05-13.html`
- Multi-bank: `MULTI_FIELD_DATE.html` → `MULTI_ROA_2026-05-13.html`
- Failures: `FAILURES_STATE_DATE.html` → `FAILURES_ALL_2026-05-13.html`
- Industry: `INDUSTRY_FIELD_DATE.html` → `INDUSTRY_NCO_2026-05-13.html`

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/fdic_client/CERT_FIELD_{date.today()}.html"
fig.write_html(fname)
```

Then open with: `open <fname>`

# Chart Strategy Guidelines
- **Scale**: ASSET, DEP, LNLSNET, NETINC are in **$thousands** — label axes accordingly or divide by 1_000_000 for billions
- **Dual axis**: use when pairing a rate (ROA %, NCO %) with a level (assets, deposits)
- **Failures**: `failures_timeline()` auto-aggregates by year — no prep needed
- **Industry summary**: good for decade-long trend context before drilling into individual banks
- **Color**: US bank series → `#0057A8`, stress/NCO → `#C8102E`, growth/income → `#00875A`

# Field Reference

## `/financials` endpoint — per-bank quarterly data
| Concept | Field | Notes |
|---------|-------|-------|
| Report date | `REPDTE` | YYYYMMDD — auto-parsed to DatetimeIndex |
| Total assets | `ASSET` | $000s |
| Total deposits | `DEP` | $000s |
| Net loans | `LNLSNET` | $000s |
| Net income | `NETINC` | $000s |
| Return on assets | `ROA` | % annualized |
| Return on equity | `ROE` | % annualized |
| Net interest income | `INTINC` | $000s |
| Noninterest income | `NONII` | $000s |
| Noninterest expense | `NONIX` | $000s |
| Tier 1 capital ratio | `TIER1` | % |
| Risk-based capital ratio | `RBCRWAJ` | % |
| Net charge-off rate | `NTLNLSR` | % annualized |
| Noncurrent loan rate | `NCLNLSR` | % |
| 30-89d past due assets | `P3ASSET` | $000s |
| 90d+ past due assets | `P9ASSET` | $000s |
| Real estate loans | `LNRE` | $000s |
| C&I loans | `LNCI` | $000s |
| Consumer loans | `LNCON` | $000s |

## `/failures` endpoint — failure records
| Concept | Field | Notes |
|---------|-------|-------|
| FDIC cert | `CERT` | |
| Institution name | `NAME` | |
| City | `CITY` | |
| State abbreviation | `PSTALP` | use `state=` param to filter |
| Failure date | `FAILDATE` | parsed to datetime |
| Savings type | `SAVR` | DIF = FDIC-insured |
| Resolution type | `RESTYPE` | FAILURE / ASSISTANCE |
| Estimated loss | `COST` | $thousands |

## `/summary` endpoint — annual national industry aggregates
| Concept | Field | Notes |
|---------|-------|-------|
| Total assets | `ASSET` | $000s |
| Total deposits | `DEP` | $000s |
| Net income | `NETINC` | $000s |
| Gross loans | `LNLS` | $000s |
| Net charge-offs | `NTLNLS` | $000s — divide by LNLS×100 for rate |
| Noncurrent loans | `NCLNLS` | $000s |
| Equity | `EQ` | $000s |
| Number of banks | `BANKS` | count |

## `/institutions` endpoint — institution info
| Concept | Field | Notes |
|---------|-------|-------|
| FDIC cert | `CERT` | key identifier |
| Institution name | `INSTNAME` | |
| City | `CITY` | |
| State | `STNAME` | full name |
| Total assets | `ASSET` | latest period, $000s |
| Active flag | `ACTIVE` | 1 = active |
| Charter type | `CHARTER` | N = national, SM = state member, etc. |

# Common FDIC Cert Numbers
| Bank | Cert |
|------|------|
| JPMorgan Chase | 628 |
| Bank of America | 3510 |
| Wells Fargo | 3511 |
| Citibank | 7213 |
| Capital One | 4297 |
| U.S. Bancorp | 6548 |
| PNC Bank | 6384 |
| Truist Bank | 9846 |
| Goldman Sachs Bank | 33124 |
| Morgan Stanley Bank | 34942 |
| Silicon Valley Bank (failed 2023) | 57450 |
| Signature Bank (failed 2023) | 57278 |
| First Republic Bank (failed 2023) | 59017 |

Execute the fetch and chart, then show the figure.
