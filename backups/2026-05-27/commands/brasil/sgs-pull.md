---
description: Fetch BCB SGS time series and render interactive Plotly HTML charts — GDP, inflation, credit, jobs, BOP, commodities, and more
---

Pull Brazilian Central Bank (SGS) data and render an interactive HTML chart.

# Parameters

The user should specify (use defaults if not given):

| Param | Default | Options |
|-------|---------|---------|
| `--series` | `ipca` | See list below |
| `--transform` | `none` | `none`, `yoy`, `mom_to_yoy`, `3mma_yoy`, `qoq`, `12m_sum`, `3mma`, `12m_diff` |
| `--years` | `15` | any integer |
| `--label` | auto | chart title string |
| `--codes` | — | custom JSON dict `{"code":"label"}` (requires `--series custom`) |

**Available series groups:**
`gdp_demand`, `gdp_supply`, `ind_prod`, `ipca`, `core_ipca`, `ipca_goods`, `igp`,
`ic_br_brl`, `ic_br_usd`, `jobs`, `pnad`, `earnings`, `cars`, `retail_sa`,
`bop`, `credit`, `credit_gdp`, `govt_debt`, `monetary`, `confidence`, `bndes`

Run `--list` to print all groups with their series names.

# Execution

## Step 1 (optional) — list available groups

```bash
python3 /Users/macproajb/claude_projects/scripts/brasil_sgs_pull.py --list
```

## Step 2 — pull data and render chart

```bash
python3 /Users/macproajb/claude_projects/scripts/brasil_sgs_pull.py \
  --series $SERIES \
  --transform $TRANSFORM \
  --years $YEARS \
  --label "$LABEL"
```

For custom series:

```bash
python3 /Users/macproajb/claude_projects/scripts/brasil_sgs_pull.py \
  --series custom \
  --codes '{"433":"IPCA","4447":"Tradables","4448":"Non-tradables"}' \
  --transform mom_to_yoy \
  --years 15 \
  --label "IPCA custom"
```

## Step 3 — open the chart

```bash
open "/Users/macproajb/claude_projects/reports/brasil-sgs/$SAFE_LABEL.html"
```

(The script prints the exact `open` command on the last line of stdout.)

# Output

- **HTML charts**: `/Users/macproajb/claude_projects/reports/brasil-sgs/`

# Report to user

- Series group fetched, transform applied, date range
- Tail of the DataFrame (last 3 rows)
- Path to the HTML file
- Offer to pull additional groups or change the transform
