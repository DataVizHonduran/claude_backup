---
description: Scan boquin.github.io GitHub Actions for failures and propose fixes
---

# Scan boquin.github.io Actions

Fetch recent GitHub Actions runs, identify failures, classify the error type, and propose a concrete fix for each.

## Arguments
`$ARGUMENTS` — lookback window in hours (default: 24). Example: `/scan-actions 48` checks the last 48 hours.

---

## Step 1 — Parse arguments

```python
import sys
hours = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 24
```

If the user passed a number via $ARGUMENTS, use it. Otherwise default to 24.

---

## Step 2 — Fetch runs

Run this bash command:

```bash
gh run list \
  --repo DataVizHonduran/boquin.github.io \
  --limit 50 \
  --status failure \
  --json databaseId,name,workflowName,createdAt
```

Parse the JSON output. Filter runs where:
- `workflowName != "pages-build-deployment"` (skip GitHub infra)
- `createdAt >= now - {hours}h`

Deduplicate by `workflowName` — keep only the most recent run per workflow.

---

## Step 3 — Fetch error log for each failure

For each unique failing run:

```bash
gh run view {databaseId} \
  --repo DataVizHonduran/boquin.github.io \
  --log-failed 2>&1 \
  | sed 's/^[^\t]*\t[^\t]*\t[0-9TZ.:]*\t//' \
  | grep -v '^[[:space:]]*$' \
  | tail -40
```

The `sed` strips the `job\tstep\ttimestamp\t` prefix GitHub Actions prepends to every line. Keep the last 40 lines as the traceback excerpt.

---

## Step 4 — Classify the error

Apply these rules to the log excerpt (first match wins):

| Patterns to match | Class | Label |
|---|---|---|
| `TypeError` + `deprecate_kwarg`, `ImportError`, `ModuleNotFoundError`, `cannot import`, `has no attribute` on a library | dependency break | `DEP_BREAK` |
| `HTTPError 500`, `HTTPError 503`, `ValueError: Internal Server Error`, `ConnectionError`, `TimeoutError`, `ReadTimeout` | transient API failure | `TRANSIENT` |
| `KeyError`, `AttributeError` on a response/dataframe key, `IndexError` in data parsing | upstream data shape changed | `DATA_SHAPE` |
| `Permission denied`, `403`, `git push` failure, `bad credentials`, `token` | auth / secret expired | `AUTH` |
| `SyntaxError` | code bug | `CODE_BUG` |
| anything else | unknown | `UNKNOWN` |

---

## Step 5 — Propose fix per class

Use the specific error + script name from the traceback to make the proposal concrete:

- **DEP_BREAK** → Identify the breaking import and the package. Propose pinning to the last working version (check PyPI changelog) OR replacing with an equivalent that's already installed. Real example: `pandas_datareader` is broken with `pandas 3.x` — replace with direct `yfinance.download()` calls.
- **TRANSIENT** → Likely a one-time API hiccup. Recommend wrapping the failing call in a 3-attempt retry with `time.sleep(10)` backoff. Offer to trigger an immediate re-run: `gh run rerun {databaseId} --repo DataVizHonduran/boquin.github.io`.
- **DATA_SHAPE** → The upstream API changed its response format. Identify the missing key from the `KeyError` and check the data source docs. Propose updating the key name or adding a fallback.
- **AUTH** → Check GitHub repo secrets (Settings → Secrets). Token may have expired. No code change needed — rotate the secret.
- **CODE_BUG** → Show the exact offending line from the traceback and propose an inline fix.
- **UNKNOWN** → Show the full traceback excerpt. No automated proposal — flag for manual review.

---

## Step 6 — Output the report

Print this exact structure:

```
## boquin.github.io Actions Scan — last {hours}h
Scanned: {datetime now UTC}

### ❌ Failures ({N} found)

#### 1. {workflowName}  [{CLASS}]
Run: {databaseId} | {createdAt}
Error: `{one-line error summary}`
Cause: {plain-English explanation}
Fix: {concrete proposal}

#### 2. ...

---
### ✅ Passing workflows: {M} ran successfully in this window
```

If zero failures found:

```
## boquin.github.io Actions Scan — last {hours}h
✅ All clear — {M} workflows ran successfully. No failures found.
```

If zero runs found in the window at all:

```
## boquin.github.io Actions Scan — last {hours}h
No runs found in this window. Either no workflows ran or the lookback window is too short.
```

---

## Implementation notes

- Run the Python logic inline (write and execute a temp script) — do NOT spawn a subagent.
- All `gh` commands assume the user is already authenticated (`gh auth status` passes).
- ANSI escape codes and line prefixes are stripped in bash (Step 3) — no additional processing needed.
- `createdAt` from the GitHub API is ISO 8601 UTC — parse with `datetime.fromisoformat()`.
- For the one-line error summary: find the last line matching `Error:`, `Exception:`, or `##[error]` in the log excerpt.
