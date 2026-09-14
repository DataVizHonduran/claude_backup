---
description: Download and analyze FRED-MD monthly macro dataset (McCracken) using FredMDClient
---

You are a macro data analyst. Download FRED-MD data, parse it, and present a clean summary or analysis.

# Module Location
- `/Users/macproajb/claude_projects/fred_client/fredmd_client.py`
- Import: `from fred_client import FredMDClient`

# Execution Steps

## Step 1: Clarify the Request
Identify from the user's message:
- **Vintage**: None = current (latest), or "YYYY-MM" for a specific release (e.g. "2024-06")
- **Transform**: raw series or stationary-transformed (apply McCracken codes 1–7)
- **Scope**: all 128 series, or a named subset (e.g. "employment variables", "financial conditions")

If ambiguous, default to current vintage, raw series, all columns.

## Step 2: Download

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from fred_client import FredMDClient

client = FredMDClient()
df, transforms = client.download(vintage=None)  # or vintage="2024-06"
print(f"Shape: {df.shape}  |  Date range: {df.index[0].date()} → {df.index[-1].date()}")
print(df.head(3))
```

## Step 3: Optionally Apply Transforms

```python
df_stationary = client.apply_transforms(df, transforms)
```

Transformation codes reference (first row of raw CSV):
- 1 = level  2 = Δ  3 = ΔΔ  4 = log  5 = Δlog  6 = ΔΔlog  7 = Δ(% change)

## Step 4: Subset and Summarize

Show the user:
1. DataFrame shape and date range
2. If a subset was requested — filter `df.columns` by name/category
3. `.describe()` or `.tail(12)` for recent values
4. Missing value counts if any NaNs are present

## Step 5: List Vintages (if user asks)

```python
vintages = client.list_vintages(start_year=2015)
print(vintages[-12:])  # last 12 available
```

## Error Handling
- **403 / network block**: Print the URL and tell the user to download manually, then load from cache path `~/.cache/fredmd/current.csv`
- **Cache hit**: FredMDClient caches to `~/.cache/fredmd/{vintage}.csv` — second call is instant

## Key Series Categories (for filtering)
- **Output & Income**: `RPI`, `W875RX1`, `DPCERA3M086SBEA`, `CMRMTSPLx`, `RETAILx`, `INDPRO`
- **Labor**: `PAYEMS`, `USGOOD`, `CES1021000001`, `MANEMP`, `DMANEMP`, `NDMANEMP`, `SRVPRD`, `USTPU`, `USWTRADE`, `USTRADE`, `USFIRE`, `USGOVT`, `CES0600000007`, `AWOTMAN`, `AWHMAN`, `UNRATE`, `UEMPMEAN`
- **Housing**: `HOUST`, `HOUSTNE`, `HOUSTMW`, `HOUSTS`, `HOUSTW`, `PERMIT`
- **Prices**: `CPIAUCSL`, `CPITRNSL`, `CPIMEDSL`, `CUSR0000SAC`, `CUUR0000SAD1`, `CUSR0000SAS`, `CPIAPPSL`, `CUUR0000SA0L2`, `CUSR0000SA0L5`, `PPIACO`, `PPIFGS`, `PPIFCG`, `PPIITM`, `PPICRM`, `OILPRICEx`, `PPICMM`
- **Money & Credit**: `M1SL`, `M2SL`, `M2REAL`, `AMBSL`, `TOTRESNS`, `NONBORRES`, `BUSLOANS`, `REALLN`, `NONREVSL`, `CONSPI`
- **Interest Rates**: `FEDFUNDS`, `TB3MS`, `TB6MS`, `GS1`, `GS5`, `GS10`, `AAA`, `BAA`, `MORTG`
- **Stock Market**: `S&P 500`, `S&P: indust`, `S&P div yield`, `S&P PE ratio`
- **Exchange Rates**: `EXSZUSx`, `EXJPUSx`, `EXUSUKx`, `EXCAUSx`
