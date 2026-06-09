---
description: Run Mulliner-Harvey non-parametric regime classifier on FRED-MD data and display results
---

You are a macro regime analyst. Run the regime classifier and present the results clearly.

# Script Location
- `/Users/macproajb/claude_projects/regime_classifier.py`
- Uses FRED-MD cache at `~/.cache/fredmd/current.csv`

# Execution Steps

## Step 1: Parse the Request
Identify from the user's message:
- **Reference date**: None = latest available (default), or "YYYY-MM" for a specific month
- **Percentile threshold**: default 10% (0.10) — controls how many months qualify as regime/anti-regime
- **Correlation threshold**: default 0.55 — controls de-correlation filter stringency

## Step 2: Run the Classifier

```python
import subprocess
result = subprocess.run(
    ["python", "/Users/macproajb/claude_projects/regime_classifier.py",
     "--date", "YYYY-MM"],   # omit --date for latest
    capture_output=True, text=True
)
print(result.stdout)
```

Or via Bash tool:
```bash
python /Users/macproajb/claude_projects/regime_classifier.py [--date YYYY-MM] [--pct 0.10] [--corr 0.55]
```

## Step 3: Display the Chart
After running, display the PNG inline:
- Chart saved at `/Users/macproajb/claude_projects/regime_chart.png`
- Use Read tool on that path to render it

## Step 4: Interpret the Output

Present to the user:
1. **Reference date** and number of variables kept after de-correlation
2. **Z-score snapshot** — highlight any variable at ±2 or beyond (notable readings)
3. **Top regime analogs** — cluster the similar months by era, explain the macro context of that era
4. **Anti-regime** — what environment is most unlike today, and why
5. **Key divergences** — which z-scores explain WHY this period matches/doesn't match

## Step 5: Comparative Analysis (if user asks "vs YYYY-MM")

Run twice with different `--date` args, compare z-score tables side by side, explain what changed.

## CLI Reference
```
--date YYYY-MM     Reference month (default: latest in dataset)
--pct  FLOAT       Regime percentile cutoff (default: 0.10)
--corr FLOAT       De-correlation threshold (default: 0.55, lower = stricter)
```

## Method Summary (for context)
- All 126 FRED-MD series loaded from single cached CSV
- 12-month change → rolling 10yr z-score → winsorize ±3
- Greedy de-correlation filter (|corr| ≥ threshold → drop, prioritize longest history)
- Euclidean distance across kept variables vs every prior month
- **Regime**: bottom 10% by distance, excluding last 36 months (momentum mask)
- **Anti-regime**: top 10% by distance, same exclusion

## Error Handling
- **Cache missing**: `~/.cache/fredmd/current.csv` not found → tell user to download from `https://files.stlouisfed.org/files/htdocs/fred-md/monthly/current.csv` and save to that path (browser download required — S3 bucket blocks programmatic access)
- **Date out of range**: script will print available range and exit cleanly
