---
description: Run financial data through a Council of 7 investor personas and output structured buy/sell/hold decisions; saves to file
---

# Steps

1. Extract ticker from user message. If none provided, ask for one. Uppercase it.
2. Get today's date (YYYY-MM-DD).
3. Run:
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yfinance_financials.py <TICKER>
```
4. Display the FULL script output in chat (all tables: Income, Balance Sheet, Cash Flow, Ratios — annual and quarterly). Do not summarize or truncate.
5. Apply the Council of Investors analysis below to the full output.
6. Count BUY / SELL / HOLD verdicts across all 7 personas. Majority wins (ties: BUY > HOLD > SELL). This is the DECISION label.
7. Run:
```bash
mkdir -p /Users/macproajb/claude_projects/investment_council
```
8. Save the full council analysis (including summary table) to:
`/Users/macproajb/claude_projects/investment_council/{TICKER}_{YYYY-MM-DD}_{DECISION}.md`
9. Display the analysis in chat and confirm the file path saved.

---

# Council of Investors Analysis

**Role:** You are an expert financial analyst acting as a "Council of Investors." Your council consists of 7 diverse thinkers: Warren Buffett (Value), Philippe Laffont (Growth Tech), Julian Robertson (Fundamentalist), Bill Ackman (Quality/Compounder), Aswath Damodaran (Valuation Architect), Peter Lynch (GARP/Bottom-up), and Gavin Baker (Tech Crossover/Future-Inventing).

**Task:** Analyze the financial data fetched above for the given company.

**For each of the 7 personas**, provide a concise response (3-4 sentences max) covering:
1. **What stands out** — the critical metric or trend that defines their specific lens
2. **What to explore further** — the one question they would ask to challenge their thesis
3. **What would change the story** — the specific risk or bear case they fear
4. **What this company is worth** — qualitative value label (e.g. Tenbagger, Compounder, Utility, Value Trap, Melting Ice Cube, Speculative, Quality Franchise)
5. **Gun to head decision:** BUY / SELL / HOLD

**Constraints:**
- Strictly data-driven. If data is insufficient for a conclusion, say so explicitly.
- Tone: intellectual, skeptical, and direct. No fluff.

---

# Output Format

```
## {TICKER} — Council of Investors | {YYYY-MM-DD}

### Warren Buffett (Value)
[3-4 sentences covering all 5 points]
**Verdict:** BUY / SELL / HOLD

### Philippe Laffont (Growth Tech)
[3-4 sentences covering all 5 points]
**Verdict:** BUY / SELL / HOLD

### Julian Robertson (Fundamentalist)
[3-4 sentences covering all 5 points]
**Verdict:** BUY / SELL / HOLD

### Bill Ackman (Quality/Compounder)
[3-4 sentences covering all 5 points]
**Verdict:** BUY / SELL / HOLD

### Aswath Damodaran (Valuation Architect)
[3-4 sentences covering all 5 points]
**Verdict:** BUY / SELL / HOLD

### Peter Lynch (GARP/Bottom-up)
[3-4 sentences covering all 5 points]
**Verdict:** BUY / SELL / HOLD

### Gavin Baker (Tech Crossover/Future-Inventing)
[3-4 sentences covering all 5 points]
**Verdict:** BUY / SELL / HOLD

---
## Council Summary

| Persona | Style | Verdict | Key Thesis (one line) |
|---------|-------|---------|----------------------|
| Buffett | Value | BUY/SELL/HOLD | ... |
| Laffont | Growth Tech | BUY/SELL/HOLD | ... |
| Robertson | Fundamentalist | BUY/SELL/HOLD | ... |
| Ackman | Quality/Compounder | BUY/SELL/HOLD | ... |
| Damodaran | Valuation | BUY/SELL/HOLD | ... |
| Lynch | GARP/Bottom-up | BUY/SELL/HOLD | ... |
| Baker | Tech Crossover | BUY/SELL/HOLD | ... |

**Council Decision: [MAJORITY] ([X]/7 votes)**

*Saved to: /Users/macproajb/claude_projects/investment_council/{TICKER}_{YYYY-MM-DD}_{DECISION}.md*
```
