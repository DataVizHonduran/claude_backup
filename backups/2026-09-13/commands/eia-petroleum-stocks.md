---
description: Weekly EIA Petroleum Stocks by PAD District — chart + AI commentary, local run of the boquin.xyz pipeline
---

Local invocation of the GitHub Actions pipeline that builds https://boquin.xyz/reports/petroleum-stocks/ — generates the 3x2 PADD panel charts (crude/gasoline/distillate) and injects Gemma commentary, then commits+pushes.

Repo: `/Users/macproajb/boquin.github.io` (remote `git@github.com:DataVizHonduran/boquin.github.io.git`)

## Arguments
`$ARGUMENTS` — optional `nopush` to skip the git commit/push (chart-only, local preview)

## Env required
- `EIA_API_KEY` — https://www.eia.gov/opendata/register.php (falls back to rate-limited DEMO_KEY if unset)
- No `HF_TOKEN` needed — commentary step below is written directly, not via the Gemma script.

## Steps

1. Sync repo:
```bash
cd /Users/macproajb/boquin.github.io && git pull --rebase --autostash
```
2. Generate charts + CSVs + index.html:
```bash
python3 scripts/generate_petroleum_stocks_weekly.py
```
   - Exits early (code 0, no output) if EIA hasn't published this week's data yet (>14 days stale check).
3. **Commentary — do this yourself, do not run `petroleum_stocks_commentary.py`:**
   - Read `reports/petroleum-stocks/data/{crude,gasoline,distillate}_seasonal.csv` and `_raw.csv`.
   - For each product: latest-date NUS total, WoW change (build/draw) from the last two raw rows, seasonal `pct_of_range`, and the 5 PADD breakdowns (flag PADD 3 / R30 for crude as most-watched).
   - Write Markdown commentary covering: crude positioning, gasoline positioning, distillate positioning, cross-product divergences, price implications (bullish/bearish/neutral WTI + refined products), one watchlist item for next Wednesday. Include a summary table `| Product | MMBbl | WoW | Seasonal % | Signal |`. Under 600 words.
   - Save it to `reports/petroleum-stocks/commentary-YYYY-MM-DD.md`.
   - Convert to HTML and inject into `reports/petroleum-stocks/index.html` between `<!-- petro-commentary-start -->` / `<!-- petro-commentary-end -->` markers, reusing the block styling from `build_commentary_block()` in `scripts/petroleum_stocks_commentary.py` (same divs/table CSS) — just swap the "Generated ... · google/gemma-4-31B-it" byline for "Generated {UTC timestamp} · Claude". Replace any existing markers/content if present, else insert before `</body>`.
4. Unless `$ARGUMENTS` contains `nopush`, commit and push:
```bash
git add reports/petroleum-stocks/
git diff --staged --quiet || (git commit -m "Update Petroleum Stocks Weekly Chart - $(date +'%Y-%m-%d') 🤖" && git pull --rebase --autostash && git push)
```
5. Open the result:
```bash
open reports/petroleum-stocks/index.html
```

## Output
- `reports/petroleum-stocks/{Crude,Gasoline,Distillate}_Stocks_Weekly_YYYY_MM_DD.png`
- `reports/petroleum-stocks/data/{crude,gasoline,distillate}_{raw,seasonal}.csv`
- `reports/petroleum-stocks/index.html` (tabbed viewer, live at boquin.xyz/reports/petroleum-stocks/)
- `reports/petroleum-stocks/commentary-YYYY-MM-DD.md` (if commentary ran)

## Notes
- Crude uses PADD-level ex-SPR series (`SAX`) with fallback to `SAE`; gasoline/distillate have no SPR component.
- PADD 3 (Gulf Coast) is the most-watched crude region — commentary flags it explicitly.
- This duplicates the two scheduled workflows (`update-petroleum-stocks-weekly.yml` Wed 17:00 UTC, `petroleum-stocks-commentary.yml` Wed 17:30 UTC) — running this manually the same week just re-commits with identical data (no-op commit, safe).
