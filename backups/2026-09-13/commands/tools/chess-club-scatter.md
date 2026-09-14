---
description: Pull player ratings (Chess Kid Rating, USCF Rating, puzzles, etc.) from an Impact Coaching Network school stats page and chart any two columns as a scatter with a banded linear-regression fit and single-pass outlier trimming
---

Pull a school's chess-club roster stats from Impact Coaching Network and chart
two numeric columns against each other as an interactive scatter with a
regression line, 95% confidence band, and outliers marked/excluded.

# Module Location
`/Users/macproajb/claude_projects/chess_club_stats/chess_club_stats.py`

# Data Source
Each school's public page is `impactcoachingnetwork.org/<slug>` (e.g.
`ps11chessclubandteamstats`). That page just embeds an iframe — the actual
data is a bare HTML table at:
```
https://icnadmin2.com/icnroster/ck_data_<SCHOOL>.html
```
where `<SCHOOL>` is the short code (e.g. `PS11`). To find the code for a new
school, fetch the impactcoachingnetwork.org page's raw HTML (`curl -s -L
<url> -A "Mozilla/5.0"`) and grep for `iframe src` — the code is in the
`ck_data_<CODE>.html` filename.

## Available columns
`name, grade, ck_rating, puzzles_correct, puzzles_attempted, plw, uscf_rating,
level, les7, wor7, prob_ytd, l_ytd, w_ytd, plw_ytd`

`ck_rating` = Chess Kid Rating (online puzzle-derived rating). `uscf_rating` =
official USCF tournament rating; **a value of 0 means the player has no USCF
rating on file**, not an actual rating of zero — the script drops these
automatically when either charted column is `uscf_rating`.

# Step 1: Clarify the Request
From the user's message, identify:
- **School** (slug or code) — ask if not given.
- **Which two columns** to plot (x, y). Default to `ck_rating` vs `uscf_rating`
  if the user just says "ratings."
- **Any minimum-value filter** (e.g. "exclude scores under 900") — maps to
  `--min-x` / `--min-y`.
- **Outlier strictness** — default `--z-thresh 1.5` (single-pass, based on the
  full-sample fit's standardized residuals — NOT iterative re-fitting, which
  spirals into over-trimming as se shrinks each round). Loosen to 2.0 for a
  light trim, tighten to 1.0–1.2 only if the user explicitly wants a very tight
  line and is fine losing more points.

If ambiguous, ask before proceeding — especially which two columns, since the
module supports any pair from the list above.

# Step 2: Run

```bash
python3 /Users/macproajb/claude_projects/chess_club_stats/chess_club_stats.py \
  --school PS11 --x ck_rating --y uscf_rating \
  --min-x 900 --z-thresh 1.5 \
  --out /private/tmp/claude-501/.../scratchpad/chess_scatter.html
```

Prints `n / clean / outliers`, the fitted slope/intercept/r/r², and the output
path.

# Step 3: Verify and Publish
1. Screenshot-check before publishing (headless Chrome renders the same static
   HTML the artifact will serve):
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless \
     --disable-gpu --screenshot=<preview>.png --window-size=1000,700 \
     "file://<out.html>"
   ```
   Read the PNG back and eyeball it — label collisions, sane axis ranges,
   band not absurdly wide/narrow.
2. Publish via the Artifact tool (favicon `♟️`). Republish to the same URL on
   follow-up tweaks (different columns, filters, outlier threshold) rather
   than minting a new one, unless the user is comparing two charts side by
   side.

# Notes
- The chart is self-contained SVG + inline JS (dataviz-skill styled, light/dark
  aware, hover tooltips) — no external chart library, safe for Artifact's CSP.
- `remove_outliers()` does exactly one pass: fit on the full sample, flag
  `|standardized residual| > z_thresh`, refit on the survivors. Re-running it
  on its own output would keep finding new "outliers" indefinitely — don't
  loop it.
- Re-fetches live every run (no caching) — the roster page updates
  continuously through the season, so a re-run after "exclude X" or "change
  the columns" naturally picks up any new practice data too.
