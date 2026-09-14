---
description: Pull ESPN's hidden soccer API (no key) for player or team stats in a tournament/league, compute per-90 or per-match rates, and chart as an interactive scatter
---

You are a sports data analyst. Pull player or team stats from ESPN's free hidden API for a soccer league/tournament, aggregate across all completed matches, compute per-90 (player) or per-match (team) rates, and chart as an interactive Plotly scatter.

# Module Location
- Client + Plotter: `/Users/macproajb/claude_projects/espn_soccer_client/`
- Import: `from espn_soccer_client import ESPNSoccerClient, aggregate_player_stats, aggregate_team_stats, SoccerPer90Plotter, SoccerTeamPlotter`

No API key needed. This hits `site.api.espn.com` / `site.web.api.espn.com` directly — fbref.com and similar sites return 403 and are not viable; this is the workaround.

Team boxscore stats (`summary['boxscore']['teams']`) carry no `value` key, only a string `displayValue` — `aggregate_team_stats` handles the cast; don't reuse the player-stat `_stat()` helper for team fields, it will silently return 0 for all of them.

# Supported Combos
Five charts are the supported, kept set. Default to one of these unless the user asks for a different stat pair.

**Player-level (per-90, `SoccerPer90Plotter`):**
- Goals/90 vs Shots/90 — `goals_vs_shots_scatter(min_goals=1)`

**Team-level (per-match average, `SoccerTeamPlotter`):**
- Possession% vs Shots/match — `possession_vs_shots_scatter()`
- Shot Conversion% vs Shots/match — `shot_conversion_vs_shots_scatter()`
- Long Ball% vs Pass% — `longball_vs_pass_scatter()`
- Accurate Crosses vs Total Crosses/match — `crosses_accuracy_scatter()`

Team charts label outliers only (combined z-distance > 1.4 on both axes) to avoid clutter at 32-48 teams; pass `label_outliers_only=False` to `team_scatter()` to label everyone instead. Marker size = matches played, color = confederation.

## Step 1: Clarify the Request
Identify from the user's message:
- **League/tournament slug**: e.g. `fifa.world` (World Cup), `eng.1` (Premier League), `esp.1` (La Liga), `uefa.champions`. Default to `fifa.world` if context is a current World Cup.
- **Date range**: `YYYYMMDD-YYYYMMDD` covering the matches to include. Default to tournament start through today.
- **Which of the five supported combos** (or a custom pair via `per90_scatter`/`team_scatter` — anything in ESPN's per-match boxscore stat list: player side has `totalGoals`, `totalShots`, `shotsOnTarget`, `goalAssists`, `foulsCommitted`, `foulsSuffered`, `yellowCards`, `redCards`, `offsides`; team side adds `possessionPct`, `passPct`, `shotPct`, `longballPct`, `totalTackles`, `effectiveTackles`, `interceptions`, `totalCrosses`, `accurateCrosses`, `wonCorners`, `totalClearance`. Team side has no `shotsFaced` data — that field is always 0 in this feed, don't chart it).
- **Minimum goals filter** (player charts only): default 1 (only show scorers).

If ambiguous, ask before proceeding.

## Step 2: Fetch Completed Matches

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from espn_soccer_client import ESPNSoccerClient, aggregate_player_stats, aggregate_team_stats, SoccerPer90Plotter, SoccerTeamPlotter

client = ESPNSoccerClient(league="fifa.world")
event_ids = client.completed_match_ids("20260611-20260620")
```

## Step 3: Aggregate Stats

**Player route** — walks every roster entry in every completed match, sums the requested stats, and derives minutes played per player from `starter`/`subbedIn`/`subbedOut` flags plus substitution-event clock times (normalized to a 90-min match — added/stoppage time folds into the same minute bucket ESPN uses).

```python
players = aggregate_player_stats(
    client, event_ids,
    stat_names=("totalGoals", "totalShots", "shotsOnTarget"),
)
```

**Known data quirk**: occasionally a player shows minutes=0 with goals>0 (substitution name-matching gap, or an own-goal credit). Filter these out before charting (`SoccerPer90Plotter(players, min_minutes=1)` handles it) and flag the player by name in your summary.

**Team route** — walks every team's boxscore across the given matches, sums each requested stat, then divides by matches played for a fair per-match rate (percentage fields like `possessionPct` average cleanly; count fields like `totalShots` become a per-match rate so teams with different match counts compare fairly).

```python
teams = aggregate_team_stats(client, event_ids)  # default stat_names covers the 4 kept team combos
```

## Step 4: Chart

Player:
```python
plotter = SoccerPer90Plotter(players, min_minutes=1)
fig = plotter.goals_vs_shots_scatter(min_goals=1, title="<Tournament> — Goals/90 vs Shots/90")
```
For a different player stat pair: `plotter.per90_scatter(x_stat="foulsCommitted", y_stat="totalGoals", title="...")`. Marker size = minutes played, color = confederation, hover shows team/confederation/goals/shots/minutes.

Team:
```python
tp = SoccerTeamPlotter(teams)
fig = tp.possession_vs_shots_scatter(title="<Tournament> — Possession% vs Shots/match")
# or: tp.shot_conversion_vs_shots_scatter() / tp.longball_vs_pass_scatter() / tp.crosses_accuracy_scatter()
```
For a different team stat pair: `tp.team_scatter(x_stat="interceptions", y_stat="totalTackles", title="...")`. Marker size = matches played, color = confederation, labels = outliers only by default.

## Step 5: Save and Open
Naming convention: `<tournament>_<stat1>_<stat2>_scatter_<date>.html`

```python
from datetime import date
fname = f"/Users/macproajb/claude_projects/wc_{date.today()}_possession_shots_scatter.html"
fig.write_html(fname)
```

Then open with: `open <fname>`

# Notes
- ESPN league slugs follow the pattern used in URLs like `espn.com/soccer/league/_/league/<slug>`.
- Per-90 numbers are noisy early in a tournament (small minute samples) — call this out in any table/chart summary, especially for any player under ~30 minutes.
- Rate-limit politely: this is ESPN's public site API, not a documented/ToS-covered endpoint — don't hammer it in tight loops.
