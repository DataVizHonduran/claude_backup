---
description: Download BCB FOCUS survey vintages and render interactive HTML dashboard for all 12 macro indicators
---

Run the FOCUS vintage evolution dashboard generator and open the result.

# Execution

## Step 1: Run the script

```bash
python3 /Users/macproajb/claude_projects/scripts/brasil_focus_vintages.py
```

First run fetches full history from 2001 for all 12 indicators (~2–5 min, ~1.2M rows across indicators).
Subsequent runs are incremental (last 365 days overlap window, ~30 sec).

## Step 2: Open the dashboard

```bash
open /Users/macproajb/claude_projects/reports/brasil-focus-vintages/index.html
```

## Step 3: Report

Report the output path and print the row counts / ref-year spans from the script's stdout.

# Output locations

- **HTML dashboard**: `/Users/macproajb/claude_projects/reports/brasil-focus-vintages/index.html`
- **CSV cache**: `/Users/macproajb/claude_projects/reports/brasil-focus-vintages/data/<slug>.csv`

# Indicators covered (12)

IPCA, PIB Total, Câmbio, Selic, IGP-M, Resultado Primário, Resultado Nominal,
Dívida Líquida Setor Público, Conta Corrente, Balança Comercial (Saldo),
IPCA Administrados, Investimento Direto no País

# Dashboard controls

- **Indicator** — switch between all 12 macro series
- **Start year** — 2001 / 2005 / 2010 / 2015 / 2018 / 2020
- **Y-axis** — all data or percentile clipping (p99 / p95 / p90 / p80)
- **Display** — All vintages / Average across horizons / Current-year forecast

Colors graduate blue-grey (oldest vintages) → vivid red (most recent).
Click legend entries to toggle individual reference years on/off.
