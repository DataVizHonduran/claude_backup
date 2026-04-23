---
description: Fetch and analyze 2026 Brazilian presidential election polls from Wikipedia/pollsters with trend analysis
---

# Brazil 2026 Presidential Election Polls Monitor

Fetch and analyze the latest Brazilian presidential election polling data for the 2026 election.

## Instructions

1. **Primary Source:** Try WebFetch for Wikipedia first: https://en.wikipedia.org/wiki/Opinion_polling_for_the_2026_Brazilian_presidential_election

2. **Fallback Strategy (if Wikipedia blocked):** Use WebSearch with targeted queries for ALL major Brazilian pollsters:
   - **Quaest/Genial:** "Quaest Brazil 2026 poll [current month/year]"
   - **AtlasIntel:** "AtlasIntel Brazil 2026 presidential election poll [current month/year]"
   - **Paraná Pesquisas:** "Paraná Pesquisas" Brazil 2026 Lula Tarcísio Michelle [current month/year]"
   - **Datafolha:** "Datafolha Brazil 2026 election poll [current month/year]"
   - **Ipespe:** "Ipespe Brazil 2026 presidential poll [current month/year]"
   - **Other pollsters:** Search for "Ipec" "MDA" "Instituto IDEIA" if needed
   - **Portuguese queries:** "pesquisa eleitoral" Brazil 2026 presidencial [current month/year]"
   - Include actual current date in searches for recency
   - Run searches in PARALLEL for efficiency

3. **Data to Extract:**
   - Poll fieldwork dates (specific date ranges)
   - Pollster names (Quaest, Datafolha, AtlasIntel, etc.)
   - Sample sizes and methodologies (online, in-person, phone)
   - Margin of error
   - All candidate names and exact percentages
   - Both first round AND second round scenarios
   - Note any candidates who are legally ineligible

4. **Trend Analysis:**
   - Compare polls over time (calculate percentage point changes)
   - Use directional indicators: ↑ ↓ for increases/decreases
   - Identify tightening or widening races
   - Note statistical ties (within margin of error)

5. **Context to Include:**
   - Public sentiment (support for/against candidates running)
   - Recent political announcements (candidacy declarations)
   - Legal barriers (ineligibility rulings)
   - Emerging opposition candidates

## Output Format

### Header
```
2026 Brazilian Presidential Election - Poll Summary
Report Generated: [current date]
Data Sources: [list pollsters and note if Wikipedia unavailable]
```

### Recent Polls Table (Last 60 days)
Markdown table format:
```
| Date | Pollster | Sample | Lula (PT) | Tarcísio (REP) | Bolsonaro (PL)* | Methodology |
```

### First Round Scenarios
Most recent poll showing all candidates with percentages

### Second Round Projections
Multiple head-to-head matchups:
- Lula vs. Candidate A: X% | Y% (± change from previous)
- Lula vs. Candidate B: X% | Y% (± change from previous)

### Key Trends
Bullet points with:
- **Trend Name:** Description with directional changes and context
- Include percentage point changes in parentheses

### Notable Context
- Eligibility issues
- Candidacy announcements
- Public sentiment paradoxes
- Emerging candidates

---

**Important:** Use actual data, calculate real trends, format tables properly, and include all available matchup scenarios.

## Output File

After completing the analysis:

1. Save the complete report to: `~/.claude/cache/brasil/election-polls/brasil_election_polls_YYYY-MM-DD.md`

2. Update the metadata file at `~/.claude/cache/brasil/metadata.json`:
   - Set `election-polls.last_run` to today's date (YYYY-MM-DD format)
   - Set `election-polls.output_path` to the full path of the saved file

   Use this Python snippet to update metadata:
   ```python
   import json, os
   from datetime import date

   metadata_path = os.path.expanduser('~/.claude/cache/brasil/metadata.json')
   with open(metadata_path, 'r') as f:
       metadata = json.load(f)

   today = date.today().strftime('%Y-%m-%d')
   output_file = f"~/.claude/cache/brasil/election-polls/brasil_election_polls_{today}.md"

   metadata['election-polls']['last_run'] = today
   metadata['election-polls']['output_path'] = output_file

   with open(metadata_path, 'w') as f:
       json.dump(metadata, f, indent=2)
   ```
