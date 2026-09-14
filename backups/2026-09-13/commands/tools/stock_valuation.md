---
description: Senior equity research analyst — full DCF + peer comps + 12-month price target for any ticker
---

Conduct a comprehensive equity research analysis for the ticker the user specifies.

# Steps

1. Extract ticker from user message. If none provided, ask for one. Uppercase it.
2. Get today's date (YYYY-MM-DD).
3. Run:
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yfinance_financials.py <TICKER>
```
4. From the yfinance output, identify the company's sector and sub-industry. Select 3–4 peer tickers in the same sub-industry using your own knowledge (e.g., for MSFT: GOOGL, ORCL, CRM, SAP).
5. Call the `mcp__edgar-tools__compare_companies` tool with the target ticker + peer tickers to retrieve peer forward P/E, EV/EBITDA, and EV/Revenue multiples.
6. Apply the Full Analysis Prompt below to all collected data.
7. Run:
```bash
mkdir -p /Users/macproajb/claude_projects/equity_research
```
8. Save the full report to:
`/Users/macproajb/claude_projects/equity_research/{TICKER}_{YYYY-MM-DD}_PT{price_target}.md`
(Replace `{price_target}` with the rounded integer dollar value of the 12-month PT.)
9. Display the report in chat and confirm the file path.

---

# Full Analysis Prompt

**Role:** Senior Equity Research Analyst, Goldman Sachs Equity Research. Audience: institutional portfolio managers who demand rigorous, data-anchored conclusions.

**Inputs available:**
- yfinance financials (income statement, balance sheet, cash flow — 4 annual + 5 quarterly periods; ratio suite)
- EDGAR compare_companies output (peer multiples)

**Produce the following sections in strict order:**

---

## [TICKER] — Equity Research | [YYYY-MM-DD]
**Rating:** BUY / HOLD / SELL  
**12-Month Price Target: $XX**  
**Current Price: $XX | Upside/(Downside): XX%**

---

### 1. Investment Thesis
Three sentences. State the rating and the core structural argument. Third sentence: **Variant Perception** — the specific mispricing or misread the market has on this name. Be concrete: name the metric or dynamic the consensus is wrong about.

---

### 2. Key Value Drivers
Identify exactly 3 drivers. For each: name the driver, cite the supporting data point from yfinance (e.g., "Revenue CAGR of X% over 3 years"), and state the forward implication. Drivers must cover: (a) top-line durability, (b) margin/operating leverage trajectory, (c) capital allocation or FCF compounding.

---

### 3a. Intrinsic Valuation — 2-Stage DCF

**Assumptions (state all explicitly):**
- Base FCF: most recent annual FCF from yfinance ($Xbn)
- Stage 1 growth (years 1–5): derived from 3-yr revenue CAGR + margin trend from yfinance data
- Stage 2 / Terminal growth: 2.5%
- Beta (β): from yfinance data
- WACC: Risk-free rate 4.3% + β × 5.5% (ERP) + 0.5% company spread = X.X%
- Net debt (from balance sheet), shares outstanding (from yfinance)

**DCF Table:**

| Year | FCF ($bn) | Discount Factor | PV ($bn) |
|------|-----------|-----------------|----------|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| Terminal Value | | | |
| **Enterprise Value** | | | |
| Less: Net Debt | | | |
| **Equity Value** | | | |
| Shares Outstanding | | | |
| **DCF Implied Price** | | | **$XX** |

---

### 3b. Relative Valuation — Peer Comps

**Source: EDGAR compare_companies**

| Metric | [TICKER] | [Peer 1] | [Peer 2] | [Peer 3] | Peer Avg | [TICKER] vs. Avg |
|--------|----------|----------|----------|----------|----------|------------------|
| Fwd P/E | | | | | | |
| EV/EBITDA | | | | | | |
| EV/Revenue | | | | | | |

**5-yr historical average:** Approximated as current trailing multiple × 0.85 (conservative mean-reversion assumption). *Flag: estimated, not sourced from historical data series.*

**Comps-implied price:** Apply peer-average forward P/E and EV/EBITDA to [TICKER]'s consensus forward estimates. Average the two → **Comps-implied price: $XX**

---

### 4. Price Target Derivation

| Method | Implied Price | Weight |
|--------|--------------|--------|
| DCF | $XX | 50% |
| Peer Comps | $XX | 50% |
| **Blended PT** | **$XX** | |

**12-Month Price Target: $XX**  
**vs. Current Price: $XX → Upside/(Downside): XX%**

---

### 5. Bear Case — Risk Factors

Three specific catalysts that would invalidate the thesis. For each: name the risk, quantify the potential earnings/FCF impact using data from the financials, and state what price level the stock would trade at in that scenario.

---

**Data disclosure:** Financials sourced via yfinance (most recent 10-K/10-Q data available). Peer multiples sourced via SEC EDGAR. 5-yr historical multiple averages approximated; not sourced from historical data series. This is not investment advice.

---

# Style Rules
- Tone: clinical, institutional. No superlatives, no emotional adjectives.
- Every number must come from yfinance output or compare_companies output. Do not fabricate figures.
- If a required data point is absent, state it explicitly and omit that sub-calculation.
- DCF arithmetic must be internally consistent — verify the math before writing.
