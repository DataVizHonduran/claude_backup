# Scrape layoffs.fyi → CSV

Scrape the layoffs.fyi Airtable tracker and save to CSV in the current working directory.

## Step 1 — Ask the user before doing anything

**Before running any code**, ask:

> "Scrape **all records** (full history, ~4 361 rows, ~3 min) or just the **last 30 days** (fast, ~1 min)?
> - If last 30 days: I'll append new rows to an existing CSV if one is found in this folder, or create a new one."

Wait for the answer, then proceed accordingly.

---

## What this does

layoffs.fyi embeds a **public Airtable** (`app1PaujS9zxVGUZ4`, view `shroKsHx3SdYYOzeh`).  
The table is in **reverse-chronological order** and uses **virtual scrolling** — only ~27 rows are in the DOM at once.  
We use **Playwright + Chromium** to scroll through `.antiscroll-inner` and collect cells via `[data-columnid]` + `[data-rowid]`.

---

## Column map (Airtable field IDs → human names)

| Field ID | Column name |
|---|---|
| fld9AHA9YDoNhrVFQ | Company |
| fldeoYEol1GhizODE | Location HQ |
| fldH1FcSF7DAaS1EB | # Laid Off |
| fldaRiRVH3vaD9DRC | Date |
| fldZRD6CwpFopYqqv | % |
| fldZxgn3xoVqoHWuj | Industry |
| fldpt9Gt8PewUC1Sh | Source |
| fldoYp88YU5yEaK2P | Stage |
| fldiT8WOrVKce4LDj | $ Raised (mm) |
| fldATTnRRO0iX7jr0 | Country |
| fldwGtACkf7IYtRZ6 | Date Added |

---

## Script

```python
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import time, csv, os, glob

COL_MAP = {
    "fld9AHA9YDoNhrVFQ": "Company",
    "fldeoYEol1GhizODE": "Location HQ",
    "fldH1FcSF7DAaS1EB": "# Laid Off",
    "fldaRiRVH3vaD9DRC": "Date",
    "fldZRD6CwpFopYqqv": "%",
    "fldZxgn3xoVqoHWuj": "Industry",
    "fldpt9Gt8PewUC1Sh": "Source",
    "fldoYp88YU5yEaK2P": "Stage",
    "fldiT8WOrVKce4LDj": "$ Raised (mm)",
    "fldATTnRRO0iX7jr0": "Country",
    "fldwGtACkf7IYtRZ6": "Date Added",
}

EMBED_URL = (
    "https://airtable.com/embed/app1PaujS9zxVGUZ4/"
    "shroKsHx3SdYYOzeh?backgroundColor=green&viewControls=on"
)
FIELDNAMES = list(COL_MAP.values())


def extract_rows(page):
    return page.evaluate("""(colMap) => {
        const cells = document.querySelectorAll('[data-columnid]');
        const rows = {};
        cells.forEach(cell => {
            const colId = cell.getAttribute('data-columnid');
            if (!colMap[colId]) return;
            const rowEl = cell.closest('[data-rowid]');
            if (!rowEl) return;
            const rowId = rowEl.getAttribute('data-rowid');
            if (!rows[rowId]) rows[rowId] = {};
            const text = cell.innerText.trim();
            if (text) rows[rowId][colId] = text;
        });
        return Object.entries(rows).map(([rid, data]) => ({_rowId: rid, ...data}));
    }""", colMap)


def clean_row(row):
    clean = {COL_MAP[k]: v for k, v in row.items() if k in COL_MAP}
    if "Location HQ" in clean:
        clean["Location HQ"] = clean["Location HQ"].replace("\nNon-U.S.", "").strip()
    return clean


def parse_date(date_str):
    """Parse M/D/YYYY date strings from Airtable."""
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y")
    except Exception:
        return None


def scrape_all_rows(page):
    """Scroll through the full virtual list and return all rows."""
    scroll_info = page.evaluate("""() => {
        const el = document.querySelector('.antiscroll-inner');
        return el ? {scrollHeight: el.scrollHeight, clientHeight: el.clientHeight} : null;
    }""")
    total_height = scroll_info["scrollHeight"]
    print(f"Scroll container height: {total_height}px")

    all_rows = {}
    scroll_pos = 0
    scroll_step = 480
    last_report = 0
    step = 0

    print(f"Scrolling in steps of {scroll_step}px…")
    while scroll_pos <= total_height + scroll_step:
        page.evaluate(f"""() => {{
            const el = document.querySelector('.antiscroll-inner');
            if (el) el.scrollTop = {scroll_pos};
        }}""")
        time.sleep(0.35)

        for r in extract_rows(page):
            rid = r.pop("_rowId")
            if rid not in all_rows:
                all_rows[rid] = {}
            all_rows[rid].update({k: v for k, v in r.items() if v})

        count = len(all_rows)
        if count - last_report >= 200:
            pct = min(100, int(scroll_pos / total_height * 100))
            print(f"  step {step:4d} | {pct:3d}% | {count:5d} rows")
            last_report = count

        scroll_pos += scroll_step
        step += 1

    return all_rows


def scrape_last_30_days(page):
    """
    Scroll from the top (most recent) and stop as soon as every row in a
    batch is older than 30 days. Table is reverse-chronological so we stop early.
    """
    cutoff = datetime.now() - timedelta(days=30)
    print(f"Collecting rows with Date >= {cutoff.strftime('%m/%d/%Y')}")

    all_rows = {}
    scroll_pos = 0
    scroll_step = 480
    step = 0
    stop = False

    while not stop:
        page.evaluate(f"""() => {{
            const el = document.querySelector('.antiscroll-inner');
            if (el) el.scrollTop = {scroll_pos};
        }}""")
        time.sleep(0.35)

        batch = extract_rows(page)
        any_new = False
        all_old = True

        for r in batch:
            rid = r.pop("_rowId")
            date_val = r.get("fldaRiRVH3vaD9DRC", "")
            dt = parse_date(date_val)
            if dt and dt >= cutoff:
                all_old = False
                if rid not in all_rows:
                    all_rows[rid] = {}
                    any_new = True
                all_rows[rid].update({k: v for k, v in r.items() if v})
            # rows without a date are included conservatively
            elif not dt:
                if rid not in all_rows:
                    all_rows[rid] = {}
                    any_new = True
                all_rows[rid].update({k: v for k, v in r.items() if v})

        if all_old and not any_new:
            print(f"  Reached rows older than 30 days — stopping.")
            stop = True
        else:
            count = len(all_rows)
            print(f"  step {step:4d} | {count:4d} rows within 30 days")

        scroll_pos += scroll_step
        step += 1

    return all_rows


def find_existing_csv(cwd):
    """Return the most recently modified layoffs_fyi_*.csv in cwd, or None."""
    pattern = os.path.join(cwd, "layoffs_fyi_*.csv")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return matches[0] if matches else None


def load_existing_csv(path):
    """Load existing CSV rows keyed by (Company, Date, # Laid Off) for dedup."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def run(mode, cwd):
    today_str = datetime.now().strftime("%m%d%Y")
    out_path = os.path.join(cwd, f"layoffs_fyi_{today_str}.csv")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})

        print("Loading Airtable embed…")
        page.goto(EMBED_URL, wait_until="domcontentloaded", timeout=40000)
        time.sleep(12)

        if mode == "all":
            raw = scrape_all_rows(page)
        else:
            raw = scrape_last_30_days(page)

        browser.close()

    new_rows = [clean_row(v) for v in raw.values()]
    print(f"\nScraped {len(new_rows)} new rows.")

    if mode == "30d":
        existing_csv = find_existing_csv(cwd)
        if existing_csv:
            print(f"Found existing file: {existing_csv}")
            existing_rows = load_existing_csv(existing_csv)

            # Deduplicate: key = (Company, Date, Source) — most stable combo
            def row_key(r):
                return (r.get("Company", ""), r.get("Date", ""), r.get("Source", ""))

            existing_keys = {row_key(r) for r in existing_rows}
            truly_new = [r for r in new_rows if row_key(r) not in existing_keys]
            print(f"  {len(truly_new)} rows not already in existing file.")

            # Write updated file (existing + new on top, preserving reverse-chron order)
            combined = truly_new + existing_rows
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(combined)
            print(f"Appended {len(truly_new)} new rows → {out_path}  ({len(combined)} total)")
        else:
            print("No existing CSV found — writing fresh file.")
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(new_rows)
            print(f"Saved {len(new_rows)} rows → {out_path}")
    else:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(new_rows)
        print(f"Saved {len(new_rows)} rows → {out_path}")
```

---

## Usage instructions for the agent

1. **Ask the user** (Step 1 above) before touching any files or running code.
2. Set `mode = "all"` or `mode = "30d"` based on the answer.
3. Set `cwd` to the current working directory.
4. Call `run(mode, cwd)`.
5. Report: rows scraped, rows appended (if 30d mode), and the output file path.

---

## Key implementation notes

- **Wait 12 seconds** after `domcontentloaded` — Airtable's JS needs time to render the first batch.
- **Scroll `.antiscroll-inner`**, NOT `.gridView` — `.antiscroll-inner` is the true virtual-scroll container (height ≈ 139 617 px for ~4 361 rows).
- **Step size 480 px** stays safely inside the ~765 px visible window so no rows are skipped.
- **`[data-rowid]`** is the dedup key during scrolling; `(Company, Date, Source)` is the dedup key when merging with an existing CSV.
- **30-day mode stops early** once all rows in a scroll batch are older than the cutoff — the table is reverse-chronological so this is safe.
- **`Non-U.S.` tag** appears as a second line in Location HQ for non-US companies — strip it.
- Field IDs are stable (Airtable internal IDs don't change if column names are renamed).
