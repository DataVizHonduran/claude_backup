---
description: Identify and publish the most interesting upcoming FIFA World Cup matchups — fixtures where group standings force two highly ranked teams into a decisive game against each other
---

You are a sports editor. Pull scheduled (not-yet-played) World Cup group-stage fixtures, cross-reference current group standings, score each matchup by how strong both teams are AND how much is on the line, then publish a ranked digest to boquin.xyz.

# Module Location
Client: `/Users/macproajb/claude_projects/espn_soccer_client/` — import `ESPNSoccerClient, rank_matchups_by_interest`. Mirror copy lives at `boquin.github.io/scripts/wc2026/espn_soccer_client/`; if you ever touch `client.py`, copy the change to both paths (`diff -q` to confirm they match).

No API key needed — same ESPN hidden site API as `tools:soccer-per90-scatter`.

# What "interesting" means here
A fixture scores high when:
1. **Both** teams are well-ranked (FIFA_RANKING dict in `client.py`) — weighted so a top team paired with a mediocre one doesn't outscore two genuinely strong teams (the weaker side's rank is weighted 2x, since that's the bottleneck).
2. **Stakes are live** — neither team is already eliminated, and the points gap is small enough that the result decides who controls the group (level on points = max stakes; widening gap lowers it). The user's reference case: Uruguay vs Spain, where both arrive with results on the board and the winner controls Group H.

`rank_matchups_by_interest(fixtures, standings_by_group, top_n=10)` does this scoring — returns each fixture annotated with `rank1`, `rank2`, `score`, and a human-readable `stakes` string.

## Step 1: Fetch
```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from espn_soccer_client import ESPNSoccerClient, rank_matchups_by_interest

client = ESPNSoccerClient(league="fifa.world")
fixtures = client.scheduled_fixtures("20260621-20260630")  # default: today through +9 days
standings = client.standings()
top = rank_matchups_by_interest(fixtures, standings, top_n=8)
```
Adjust the date window if the user asks for a specific range; default to today through +9 days (covers the next matchday or two).

## Step 2: Sanity-check
Eyeball the top few — both team names should be sides a casual fan would recognize, and `stakes` should read as a real reason to watch (not "stakes unknown", which means standings lookup missed — group name mismatch between scoreboard's `altGameNote` and standings' group name is the likely cause; print `standings.keys()` vs `fx['group']` to debug).

## Step 3: Write the digest
`rank_matchups_by_interest` sorts by score to pick the top N — re-sort that result by `date` ascending before rendering, so the published table reads chronologically (earliest kickoff first), not by interest score.

Plain HTML, no chart — a table. Match the site's report style (see `boquin.github.io/scripts/wc2026/build_wc2026_charts.py` for the shared `FOOTNOTE_CSS`/`MOBILE_RESIZE_JS` blocks — reuse `FOOTNOTE_CSS` for layout consistency, skip the Plotly resize JS since there's no chart here).

Table columns: Date (local-friendly format) · Group · Matchup · FIFA Ranks · Why it matters (the `stakes` string). One sentence of color per matchup is fine but don't editorialize beyond what the standings support.

Save to `/Users/macproajb/claude_projects/boquin.github.io/reports/fifa-wc-2026/matchups.html`.

## Step 4: Wire into the existing dashboard
- `reports/fifa-wc-2026/index.html` has a card grid — add one more `.card` block there pointing to `matchups.html`, matching the existing card markup exactly.
- Root `index.html` also gets a dedicated `<article class="dashboard-card">` under `section-rafa`, right after the "⚽ FIFA WC 2026 Stats" card, linking straight to `reports/fifa-wc-2026/matchups.html` (one click from the homepage, not buried two levels deep). Only add this once — on re-runs, just leave the existing card alone.

## Step 5: Publish
```bash
REPO=/Users/macproajb/claude_projects/boquin.github.io
git -C $REPO pull
# (write matchups.html, edit reports/fifa-wc-2026/index.html)
git -C $REPO add reports/fifa-wc-2026/matchups.html reports/fifa-wc-2026/index.html
git -C $REPO commit -m "Add upcoming WC matchups digest"
git -C $REPO pull --rebase && git -C $REPO push
```
Confirm: published at `https://boquin.xyz/reports/fifa-wc-2026/matchups.html`.

# Notes
- `FIFA_RANKING` and group-elimination `note` text only cover the 2026 World Cup as configured — re-extend the dict in `client.py` for other tournaments.
- Standings endpoint group names (`"Group H"`) must match `scoreboard`'s `altGameNote` suffix — both come from ESPN's own naming, no transformation needed, but verify if a future tournament uses a different naming scheme.
- Re-run this after each matchday closes — points/stakes shift as games complete, so a digest from a few days ago can go stale fast.
