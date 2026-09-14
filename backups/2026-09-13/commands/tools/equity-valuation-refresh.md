---
description: Refresh the S&P 500 Equity Valuation Dashboard on boquin.xyz — all 500, a stale-N sample, or specific tickers you name
---

Refresh valuations for the tickers in `$ARGUMENTS` and republish the dashboard at
`boquin.xyz/reports/equity-valuation/`.

## Arguments (`$ARGUMENTS`)
- **Empty** → refresh the 20 stalest names (oldest `updated_at`, or never-computed first).
- **A number**, e.g. `50` → refresh that many stalest names.
- **`all`** → refresh every S&P 500 constituent (full rebuild — takes a while, confirm with the user before running unattended).
- **Explicit tickers**, e.g. `AAPL MSFT GOOGL` or `AAPL, MSFT` → refresh exactly those (comma/space separated, uppercase).

## Project location
`/Users/macproajb/claude_projects/equity_valuation/` — has `fetch_fundamentals.py`,
`compute_valuations.py`, `generate_html.py`, `select_tickers.py`, and `data/` (cached
fundamentals + computed valuations, keyed by ticker).

## Steps

1. **Resolve the ticker list.**
   - If `$ARGUMENTS` is empty or a bare number: `cd /Users/macproajb/claude_projects/equity_valuation && python3 select_tickers.py <N or 20>` — capture stdout as `TICKERS`.
   - If `$ARGUMENTS` is `all`: `python3 select_tickers.py all`.
   - Otherwise: treat `$ARGUMENTS` itself as the ticker list (uppercase, comma/space normalized to space-separated).

2. **Re-fetch fundamentals** for just those tickers (force refresh, ignores cache):
   ```bash
   cd /Users/macproajb/claude_projects/equity_valuation
   python3 fetch_fundamentals.py --force $TICKERS
   ```

3. **Recompute valuations** for just those tickers (uses the full cached universe for peer comps, so peer averages stay current even though only these tickers' own numbers update):
   ```bash
   python3 compute_valuations.py $TICKERS
   ```
   Watch stdout for `skipped` count — if a previously-covered ticker drops out, it now has insufficient/negative trailing data; that's expected behavior, not a bug (see `compute_valuations.py` notes/comments for why).

4. **Regenerate the dashboard page** (always full regenerate — it's cheap, and keeps every row consistent):
   ```bash
   python3 generate_html.py
   ```

5. **Publish to boquin.xyz:**
   ```bash
   cd /Users/macproajb/claude_projects/boquin.github.io
   git pull
   git add reports/equity-valuation/index.html
   git commit -m "Refresh equity valuation dashboard: <N> tickers 🤖"
   git pull --rebase
   git push
   ```

6. **Report back**: which tickers were refreshed, their new rating/PT/upside, and whether any dropped out of coverage (insufficient data) or newly appeared.

## Notes
- `all` re-fetches 503 tickers — run the fetch step with the parallel fetcher (already threaded, ~16 workers) and expect several minutes; consider `run_in_background`.
- This is a mechanical screen (auto-generated explainers, no analyst review) — say so if the user asks about report quality, don't oversell precision.
- If you need to change methodology (WACC formula, growth caps, sector variant rules), edit `compute_valuations.py` directly — it's a normal Python file, not templated. Re-run `compute_valuations.py` with no arguments afterward to recompute everyone under the new logic, not just the refreshed subset.
