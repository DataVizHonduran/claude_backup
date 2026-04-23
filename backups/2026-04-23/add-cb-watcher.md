# Add Central Bank Watcher

Add a new central bank watcher script to boquin.github.io, following the established pattern of fed/ecb/boj/rba_watcher_standalone.py.

## Arguments
$ARGUMENTS — the central bank name/abbreviation (e.g. "BOE", "SNB", "Banxico")

## Workflow

### 1. Research phase (read-only)
Before writing any code:
- Look up the central bank's official website URL and identify pages for: speeches, meeting minutes/accounts, rate decisions, and quarterly reports/MPR
- Confirm the current policy committee structure: name, number of voting members, meeting frequency, whether individual votes are published
- Identify the current governor + deputy governor + 3-5 key external members, their known hawk/dove leans, and current policy rate
- Check `boquin.github.io/scripts/rba_watcher_standalone.py` as the canonical template

### 2. Script: `scripts/<cb>_watcher_standalone.py`
Mirror `rba_watcher_standalone.py` exactly, adapting:

| Element | Adapt to new CB |
|---------|----------------|
| `CB_BASE` / `CB_PAGES` | Correct URLs for speeches, minutes, decisions, quarterly report |
| `NEWS_QUERIES` | 6-7 queries: CB name, governor name, committee name, key macro themes |
| `BASELINES` dict | All voting members with role + hawk/dove lean + current context |
| `ROLES` dict | Title for each member |
| `scrape_<cb>_speeches()` | Adapt selectors to CB website HTML structure |
| `scrape_board_documents()` | Adapt selectors + source labels |
| `build_context_prompt()` | Thematic sections relevant to that CB's mandate and market focus |
| LLM system prompt | "senior [country] monetary policy analyst" |
| HTML accent color | Pick a color tied to the country/flag |
| HTML_TEMPLATE title/emoji | Country flag emoji + CB name |
| INDEX_TEMPLATE | CB-specific description |
| Output path | `reports/<cb-slug>-watcher/` |
| `regenerate_index()` | Match `<cb>-watcher-*.html` glob |
| `save_output()` | Correct filename prefix |

**CB-specific prompt context to inject** (always include):
- Current policy rate
- Primary inflation gauge (CPI, core PCE, trimmed mean, HICP, etc.)
- Meeting frequency
- Whether individual votes are published
- Any unique features (forward guidance style, QE/QT, FX intervention mandate)

### 3. Dry-run verification
```bash
cd boquin.github.io
python3 scripts/<cb>_watcher_standalone.py --dry-run
```
Confirm: no import errors, all pages return HTTP 200, scrape summary shows > 0 items in at least 2 categories (speeches + news at minimum).

Fix any 404s by checking the CB website for the correct URL path before proceeding.

### 4. index.html card
Insert after the last existing watcher card in the `#section-central-banks` section:
```html
<article class="dashboard-card">
    <div class="card-header">
        <h3>[FLAG_EMOJI] [CB Name] Watcher</h3>
        <p>All [N] [Committee Name] members tracked every 3 days — hawk/dove spectrum, [key theme 1], [key theme 2], powered by Gemma 4.</p>
    </div>
    <div class="card-actions">
        <a href="reports/<cb-slug>-watcher/index.html" class="btn btn-primary">View Reports</a>
    </div>
</article>
```

### 5. GitHub Actions workflow
Copy `.github/workflows/update-boj-watcher.yml` to `.github/workflows/update-<cb>-watcher.yml`, replacing:
- `name:` → `Update [CB] Watcher`
- job name → `update-<cb>-watcher`
- `python scripts/boj_watcher_standalone.py` → `python scripts/<cb>_watcher_standalone.py`
- `--output-dir reports/boj-watcher/` → `--output-dir reports/<cb>-watcher/`
- `git add reports/boj-watcher/` → `git add reports/<cb>-watcher/`
- commit message prefix `BOJ Watcher` → `[CB] Watcher`

Cron schedule: `'0 9 */3 * *'` (every 3 days at 09:00 UTC) — keep consistent with other watchers.

### 6. Commit and push
```bash
git add scripts/<cb>_watcher_standalone.py index.html .github/workflows/update-<cb>-watcher.yml
git commit -m "Add [CB] Watcher script, landing card, and Actions workflow"
git pull --rebase
git push
```

## Quick reference — CB-specific notes

| CB | Website | Vote publication | Key inflation gauge | Meetings/yr |
|----|---------|-----------------|---------------------|-------------|
| BOE | bankofengland.co.uk | Individual votes in minutes (MPC) | CPI (2% target) | 8 |
| SNB | snb.ch | Collective only | CPI (0-2% target) | 4 |
| Norges Bank | norges-bank.no | Collective + rate path | CPI-ATE | 8 |
| Riksbank | riksbank.se | Individual votes | CPIF | 6 |
| Banxico | banxico.org.mx | Individual votes in minutes | Core CPI | 8 |
| BCB | bcb.gov.br | Individual votes (COPOM) | IPCA | 8 |
| RBNZ | rbnz.govt.nz | Collective | CPI (1-3%) | 7 |
| PBoC | pbc.gov.cn | Collective/opaque | CPI + PPI | Ad hoc |
