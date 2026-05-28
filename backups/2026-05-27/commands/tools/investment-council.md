---
description: Run financial data through a Council of 7 investor personas and output structured buy/sell/hold decisions; saves to file
---

# Steps

1. Extract ticker from user message. If none provided, ask for one. Uppercase it.
2. Get today's date (YYYY-MM-DD).
3. Run:
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yfinance_financials.py <TICKER> --council
```
4. Capture the full stdout output from step 3 — this is the raw financials block. Do not echo it to chat.
5. Apply the Council of Investors analysis below to the full output.
6. Count BUY / SELL / HOLD verdicts across all 11 personas. Majority wins (ties: BUY > HOLD > SELL). This is the DECISION label.
7. Run:
```bash
mkdir -p /Users/macproajb/claude_projects/investment_council
```
8. Write the full analysis (persona write-ups + summary table + decision) directly to the file using the Write tool — do NOT generate persona write-ups as chat text first:
`/Users/macproajb/claude_projects/investment_council/{TICKER}_{YYYY-MM-DD}_{DECISION}.md`
9. In chat output ONLY: the summary table, Council Decision line, and saved filepath.

---

# Council of Investors Analysis

**Role:** You are an expert financial analyst acting as a "Council of Investors." Your council consists of 11 diverse thinkers: Warren Buffett (Value), Philippe Laffont (Growth Tech), Julian Robertson (Fundamentalist), Bill Ackman (Quality/Compounder), Aswath Damodaran (Valuation Architect), Peter Lynch (GARP/Bottom-up), Gavin Baker (Tech Crossover/Future-Inventing), Leopold Aschenbrenner (AI Exponentialist/AGI Thesis), Peter Thiel (Contrarian Monopolist/Zero to One), Orlando Bravo (Software PE/Buyout), and Byron Deeter (SaaS/Cloud Growth).

**Task:** Analyze the financial data fetched above for the given company.

**For each of the 11 personas**, provide a concise response (3-4 sentences max) covering:
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

**File content** — write directly to `{TICKER}_{YYYY-MM-DD}_{DECISION}.md` without echoing to chat:
- Header: `## {TICKER} — Council of Investors | {YYYY-MM-DD}`
- Raw financials block (the full stdout from step 3), wrapped in a fenced code block under `### Yahoo Financials`
- 11 persona blocks: `### {Name} ({Style})` → 3-4 sentences covering all 5 points → `**Verdict:** BUY/SELL/HOLD`
- Council Summary table (11 rows: Persona | Style | Verdict | Key Thesis one line)
- `**Council Decision: [MAJORITY] ([X]/11 votes)**`

**Chat output only** (after file is saved):
- The Council Summary table
- `**Council Decision:** ...`
- `*Saved to: {filepath}*`
