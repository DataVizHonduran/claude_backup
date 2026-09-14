# 143 West 27th Street Cap Rate

Run the cap-rate research pipeline for 143 West 27th Street, Apt 5 (Chelsea co-op) — or another unit if $ARGUMENTS gives one.

## What this does

Runs `~/claude_projects/condo_monitor/unit_cap_rate.py`, which re-fetches everything live each time (no cached/stale numbers):

1. Resolves the building on CityRealty.
2. Renders the unit's page (Playwright) to pull last-sale price/date, sqft, beds/baths.
3. Pulls the building's NYC DOF income/expense figures (Open Data SODA API — co-op or condo dataset).
4. Pulls live rental comps (condo + co-op + actual rental buildings) across nearby neighborhoods, 2BR, for a market-rent $/sqft.
5. Pulls live closed-sale comps (same neighborhood, bedroom count, building type, last 90 days) for a current $/sqft price estimate — not just one asking price on the building.
6. Prints two rent scenarios (raw comp median, and a no-doorman/no-amenity haircut for older buildings) × two price bases (closed comps, last actual sale), each with gross rent, NOI, and cap rate.

## Workflow

1. Run:
```bash
cd ~/claude_projects/condo_monitor && python3 unit_cap_rate.py
```
   If `$ARGUMENTS` specifies a different address/unit, pass through the matching flags instead, e.g.:
```bash
python3 unit_cap_rate.py --address "$ARGUMENTS" --unit "<unit>" --hood "<neighborhood>" --building-type coop
```
   (`--building-type` is `coop` or `condo`; `--hood` must be a CityRealty neighborhood name, e.g. "Chelsea", "Upper West Side".)

2. Read the script's output back to the user — don't just say "done, see terminal." Summarize:
   - The unit facts found (beds/baths/sqft/last sale)
   - The price range (both bases)
   - The cap rate range across both rent scenarios
   - The caveats block at the end (off-market guesstimate + co-op sublet restriction, if applicable)

3. If the script errors on "Building not found" or "Could not parse sqft/sale history," the CityRealty page structure may have shifted — read `~/claude_projects/condo_monitor/unit_cap_rate.py` and adjust the regexes/selectors rather than guessing at new numbers by hand.

## Notes

- This is a guesstimate tool, not an appraisal — always state the numbers as a range, never a single confident figure.
- If the target is a co-op, always surface the subletting-needs-board-approval caveat — it's printed by the script but easy to bury in a wall of numbers.
- Don't confuse this with the weekly `condo_monitor.py` job (UWS/UES new-build listings under a price cap) — this command is for one-off lookups on a specific unit, run on demand.
