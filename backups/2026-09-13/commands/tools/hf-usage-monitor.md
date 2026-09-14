---
description: Monitor HuggingFace Inference credit usage/risk across all cron-scheduled automations sharing HF_TOKEN
---

# HuggingFace Usage Monitor

There is no public HuggingFace API for reading credit balance — the billing page
(`huggingface.co/settings/billing`) and Inference Providers usage page
(`huggingface.co/settings/inference-providers`) are the only source of the actual
dollar figure, and only the user can check those (they require a logged-in browser
session). This skill can't fetch that number. Instead it does the two things that
*are* checkable automatically:

1. Static estimate — how many HF Inference calls/week the current cron schedules
   commit you to, across every repo that shares `secrets.HF_TOKEN`.
2. Dynamic check — scan recent GitHub Actions runs for `402 Payment Required` /
   `429` errors, i.e. actual evidence credits ran out or got rate-limited.

## Arguments
`$ARGUMENTS` — optional space-separated list of repo `owner/name` to scan.
Default: `DataVizHonduran/boquin.github.io DataVizHonduran/earnings-recaps`
(the two repos known to use `secrets.HF_TOKEN` as of 2026-09). If the user names
other repos, use those instead/in addition.

---

## Step 1 — Find every HF-calling scheduled workflow, per repo

For each repo, work from a local clone if one exists under
`/Users/macproajb/claude_projects/<repo-name>/` (prefer that — faster, no rate
limit); otherwise `gh repo clone` into the scratchpad.

```bash
cd <repo>
grep -rlE "HF_TOKEN|InferenceClient|huggingface_hub" --include="*.yml" --include="*.yaml" .github/workflows 2>/dev/null
```

For each matching workflow file, pull out:
- The cron schedule (`grep -A1 "schedule:" <file> | grep "cron:"`). No cron line =
  `workflow_dispatch`-only — exclude from the weekly estimate, note separately.
- The script(s) it runs (`run:` lines calling `python scripts/*.py`).

## Step 2 — Estimate calls/run per script

For each script referenced, check how many HF calls one run actually makes —
don't assume 1:

```bash
grep -c "call_gemma(\|chat.completions.create(\|InferenceClient(" scripts/<script>.py
```

A flat count is a **ceiling**, not the truth — the same call site inside a
`for article in batch:` / `for pair in pairs:` loop fires once per item, not once
per script run. Check for a loop wrapping the call site, and for an explicit cap
(`--limit`, `args.limit`, a hardcoded slice like `[:10]`) the workflow's `run:`
step passes in. If the loop bound depends on runtime data (e.g. "however many
articles scraped today"), report it as a **range estimate**, flagged uncertain —
do not silently collapse it to a single number.

Also check whether the job can legitimately return **zero** calls on most runs —
a backfill-style script that processes "unprocessed items since last run" (grep
for `existing`, `unprocessed`, `already processed`, `Nothing to do`) will do
real work once, then no-op forever after, regardless of cron frequency. Confirm
by checking whether recent commits to its output directory are still landing:

```bash
git log --oneline -5 -- <output-dir-from-script>/
```

If the last commit is old relative to the cron cadence, the job is currently a
no-op — count it as ~0/wk, not cron-frequency × calls-per-run, and say so
explicitly in the report so the estimate doesn't look inflated.

## Step 3 — Roll up calls/week per repo and total

`calls/week = (cron occurrences/week) × (calls/run, or the range from Step 2)`.

Cron occurrences/week: daily=7, weekdays=5, `every 6h` (`0 */6 * * *`)=28, a single
weekday=1, monthly ≈ 0.23. Sum across all workflows in a repo, then across repos.

Present as a table: workflow | cadence | calls/run | calls/wk, sorted descending
by calls/wk, with a **Total** row. Flag the top 2-3 consumers by name.

## Step 4 — Check recent runs for exhaustion/rate-limit evidence

For each HF-calling workflow found in Step 1:

```bash
gh run list --repo <owner/name> --workflow <file> --limit 5 --json databaseId,status,conclusion,createdAt
```

For any run with `conclusion == "failure"`:

```bash
gh run view {databaseId} --repo <owner/name> --log-failed 2>&1 \
  | grep -iE "402 Payment Required|429|rate limit|depleted your monthly|Too Many Requests"
```

Collect every hit with its workflow name and run date — this is direct evidence
of credit exhaustion or rate limiting, independent of the Step 3 estimate.

## Step 5 — Output

```
## HuggingFace Usage Monitor — {date}

Repos scanned: {list}

### Estimated load
| Workflow | Cadence | Calls/run | Calls/wk |
|---|---|---|---|
...
**Total: ~{N}/wk**

Top consumers: {name} ({N}/wk, {%} of total), ...

### No-ops (backfill-complete, currently ~0 calls despite cron)
- {workflow} — last real output {date}, cron says {cadence}

### Exhaustion/rate-limit evidence (last 5 runs per workflow)
{table of workflow | run date | matched error} — or "None found in recent runs."

### Can't check from here
Actual credit balance: huggingface.co/settings/billing
Per-model/provider usage breakdown: huggingface.co/settings/inference-providers
```

---

## Implementation notes

- Run inline (bash + grep + `gh`) — do NOT spawn a subagent, this is a handful of
  greps and `gh` calls, not an exploration task.
- If the local clone is behind, `git pull` first so Step 2's `git log` check on
  output directories is accurate — a stale clone will misreport a job as a no-op.
- Don't guess at a script's internal call count from its name — grep it. A script
  that looks like a simple daily commentary job can hide a per-item loop.
- If the user asks to *fix* something this surfaces (cut a cadence, cap a loop),
  that's a follow-up edit — this skill only reports, it doesn't change cron
  schedules or code on its own.
