---
description: RBA RDP 2015-12 style AUD real exchange rate cointegration model — regresses ln(Real TWI) on ln(Terms of Trade) and the G3 real interest rate differential, reports current misalignment
---

You are a quantitative macro analyst. Run the AUD real exchange rate
cointegration model and report whether the AUD is over- or under-valued
relative to its terms-of-trade and rate-differential fundamentals.

# Module Location
- Model: `/Users/macproajb/claude_projects/aus_client/rba_cointegration.py`
- Import:
  ```python
  import sys
  sys.path.insert(0, '/Users/macproajb/claude_projects')
  from aus_client.rba_cointegration import fetch_raw_data, compute_model
  ```

# Model Summary
- **Dependent variable**: ln(Real TWI) — RBA Table F15, series `FRERTWI`.
- **Independent 1**: ln(Terms of Trade) — ABS ANA_AGG, *Total* ToT (`TTR`,
  index, seasonally adjusted). Used as a proxy for the goods-only ToT
  deflator referenced in RDP 2015-12 (no clean goods-only series is
  available via the public ABS Data API) — always flag this substitution
  in the output.
- **Independent 2**: G3 Real Interest Rate Differential (RIRD) =
  `Real_AU - (0.45*Real_US + 0.35*Real_EZ + 0.20*Real_JP)`, where each
  `Real_X = nominal policy rate - core CPI YoY`.
- **Coefficients**: `beta_1=0.60` (ToT) and `beta_2=2.00` (RIRD, applied to
  RIRD in decimal-percentage form, i.e. 1% = 0.01) are RDP 2015-12's published
  elasticities, used as-is for fidelity to the original model. `alpha` is
  recalibrated each run as the sample mean of
  `ln_RTWI - beta_1*ln_ToT - beta_2*RIRD_decimal` (so mean misalignment = 0),
  since our series use different index bases/vintages than RDP 2015-12's.
  `res.attrs["rdp_alpha_published"]` holds RDP's original constant (2.10) for
  reference; `res.attrs["ols_alpha/beta_1/beta_2"]` hold a full OLS refit on
  the same data for comparison.
- **Error correction**: `Implied_Next_Quarter_Adjustment = -0.15 * Misalignment`
  (ln terms), per RDP 2015-12's adjustment speed.

# Execution Steps

## Step 1: Fetch and Compute
```python
df = fetch_raw_data()
res = compute_model(df)
last = res.iloc[-1]
quarter = res.index[-1]
```
`fetch_raw_data()` aligns RBA, ABS, FRED, Eurostat, and OECD series onto a
shared quarterly index and drops any quarter with missing inputs — the
last row is the most recent quarter where every input is published (data
lags mean this is often 1-2 quarters behind the calendar).

## Step 1b: Chart
```python
from aus_client.rba_cointegration import plot_cointegration
from datetime import date

fig = plot_cointegration(res)
fname = f"/Users/macproajb/claude_projects/aus_client/RBA_TWI_COINTEGRATION_{date.today()}.html"
fig.write_html(fname)
```
Open with `open <fname>`.

Two-panel, white background, shared x-axis with a range selector for
1/2/3/5/10/15/20-year and full-history horizons:
- **Top**: Real TWI actual vs. cointegration equilibrium, with a shaded
  ±1 SD band (of misalignment) around the equilibrium line.
- **Bottom**: Misalignment (% deviation of actual from equilibrium).

## Step 2: Output Format

Present three sections for `quarter`:

### 1. Data Audit Table
Print the raw values for: `RTWI, ToT, AU_Cash, AU_CPI, US_Cash, US_CPI,
EZ_Cash, EZ_CPI, JP_Cash, JP_CPI`.

### 2. Math Matrix
Print: `Real_AU, Real_US, Real_EZ, Real_JP, Real_G3, RIRD, RIRD_decimal,
ln_RTWI, ln_ToT`, plus `alpha` (recalibrated intercept), `beta_1`, `beta_2`
(RDP elasticities), `rdp_alpha_published`, and the `ols_alpha/beta_1/beta_2`
comparison (all from `res.attrs`).

### 3. Residual Callout
Compute and state:
- `pct_deviation = (RTWI / RTWI_Equilibrium - 1) * 100`
- Whether the AUD Real TWI is **overvalued** (positive deviation) or
  **undervalued** (negative deviation) relative to its model-implied
  equilibrium, with the magnitude in %.
- `Implied_Next_Quarter_Adjustment` (ln terms) and what direction it
  implies for the next quarter's TWI.

Always note in the output that ToT uses the Total (not goods-only) Terms
of Trade index as a documented proxy.
