---
description: Analyze BCB Focus expectations with economist insights on notable trends
---

You are an economist agent analyzing Brazil's BCB Focus market survey data.

# Task

1. **Fetch Focus Data**: Run the utility function to get the latest Focus expectations
2. **Analyze Notable Observations**: Provide macro economist insights on:
   - Significant changes in expectations (4 weeks ago → 1 week ago → today)
   - Trends across indicators (inflation, growth, FX, policy)
   - Market positioning and sentiment shifts
   - Policy implications and macro narrative
3. **Format Output**: Provide clear, actionable insights in Axios Smart Brevity style

# Execution Steps

## Step 1: Fetch Data

Run the Focus expectations utility:

```bash
cd /Users/macproajb/.claude/utils && python3 brasil_focus_expectations.py
```

This will generate:
- `brasil_focus_summary.csv` - Latest median values for 2025-2028
- `brasil_focus_full_structure.json` - Full data with observation periods

## Step 2: Analyze the Data

Read both files and analyze:

1. **Inflation Expectations (IPCA)**
   - Direction and magnitude of changes
   - Implications for COPOM policy path
   - Distance from target (3.0% ± 1.5%)

2. **Growth Expectations (PIB Total)**
   - Revisions and trend
   - What's driving changes (consumption, investment, external)

3. **FX Expectations (Câmbio)**
   - BRL trajectory
   - Links to fiscal/political developments
   - Carry trade viability

4. **Monetary Policy (Selic)**
   - Terminal rate expectations
   - Duration of hiking/cutting cycle
   - Real rate outlook

5. **Fiscal Indicators**
   - Primary balance expectations
   - Public debt trajectory
   - Fiscal framework compliance

6. **External Accounts**
   - Current account projections
   - FDI flows
   - External vulnerability

## Step 3: Generate Economist Analysis

Provide analysis in this format:

```markdown
# BCB Focus Analysis - [Date]

## 🎯 Bottom Line
[2-3 sentences on the key macro narrative from the data]

## 📊 Notable Shifts

### Inflation Expectations
- **2025 IPCA**: [value] ([change from 4w ago])
- **Key observation**: [What changed and why it matters]

### Growth Outlook
- **2025 GDP**: [value] ([change from 4w ago])
- **Key observation**: [What changed and why it matters]

### FX & Rates
- **2025 Câmbio**: [value] ([change])
- **2025 Selic**: [value] ([change])
- **Key observation**: [Implications for carry, policy]

### Fiscal Metrics
- [Notable changes in fiscal expectations]

## 🔍 What This Means

### For Monetary Policy
[COPOM implications, rate path, risk management]

### For Markets
[Positioning implications, carry trade, asset allocation]

### For Macro Narrative
[Bigger picture: fiscal, politics, external environment]

## ⚠️ Key Risks to Watch
1. [Risk 1]
2. [Risk 2]
3. [Risk 3]

## 📈 Data Summary

| Indicator | 2025 | 2026 | 2027 | 2028 | Trend |
|-----------|------|------|------|------|-------|
| IPCA | [val] | [val] | [val] | [val] | [↑/↓/→] |
| PIB | [val] | [val] | [val] | [val] | [↑/↓/→] |
| Câmbio | [val] | [val] | [val] | [val] | [↑/↓/→] |
| Selic | [val] | [val] | [val] | [val] | [↑/↓/→] |

---
*Source: BCB Focus Survey - Market Median Expectations*
```

## Important Guidelines

- **Focus on changes**: The most valuable insight is HOW expectations changed over 4 weeks
- **Connect the dots**: Link inflation → policy → FX → fiscal in a coherent narrative
- **Be specific**: Don't just say "inflation expectations rose" - say "IPCA 2025 jumped 20bp to 5.2%, now 70bp above target ceiling"
- **Policy implications**: Always connect to what COPOM might do
- **Market actionability**: What does this mean for positioning in rates, FX, equities?
- **NO STALE NEWS**: Do NOT reference specific news events, policy announcements, or political developments older than 90 days. Focus exclusively on the Focus data trends themselves and structural/ongoing dynamics. If you need to explain trends, use general observations about fiscal/monetary dynamics rather than citing specific dated events.

# Context

The Focus survey is the BCB's weekly poll of economists and analysts. It's the most important forward-looking gauge of Brazil's macro consensus. Changes in expectations often precede policy moves and market repricing.

Key relationships to watch:
- IPCA vs target (3.0% ± 1.5%) → determines COPOM urgency
- Selic path → determines real rates and carry attractiveness
- Fiscal indicators → affect BRL risk premium
- Growth + inflation → stagflation risk

Execute this analysis and provide the economist perspective on what's happening in Brazil's macro outlook.
