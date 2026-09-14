---
description: Research analyst that determines a company's key operating KPIs (from its own earnings disclosures) and tracks them quarter over quarter — posts to boquin.xyz/reports/kpi-tracker/
---

Track key operating KPIs for the ticker in `$ARGUMENTS`, across quarters, and publish the trend dashboard.

## Arguments
`$ARGUMENTS` — a ticker, e.g. `DUOL`. Optionally add `backfill` to force a full history rebuild even if `kpis.json` already exists (e.g. `DUOL backfill`).

## Steps

### 1. Parse ticker
Extract TICKER (uppercase) from `$ARGUMENTS`. If missing, ask before proceeding.
`REPO=/Users/macproajb/claude_projects/boquin.github.io`
`JSON=$REPO/reports/kpi-tracker/$TICKER/kpis.json`

### 2. Check state
```bash
git -C $REPO pull
test -f "$JSON" && echo EXISTS || echo NEW
```
- `NEW` (or `backfill` passed) → go to **3a** (seed from scratch, up to 8 quarters of history).
- `EXISTS` → go to **3b** (fetch only quarters newer than the last recorded `period`).

### 3a. First run — fetch history + pick the KPIs
Pull item-2.02 ("Results of Operations") 8-Ks — these are earnings releases — and every exhibit in each:

```python
import requests, re, sys, time

HEADERS = {"User-Agent": "ResearchBot jeannealbertoreading@gmail.com"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
BASE_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

def get_cik(ticker):
    r = requests.get(TICKERS_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    for entry in r.json().values():
        if entry["ticker"] == ticker.upper():
            return str(entry["cik_str"]).zfill(10), entry["title"]
    raise ValueError(f"Ticker {ticker} not found in EDGAR")

def get_earnings_8ks(cik_padded, max_n):
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    recent = r.json()["filings"]["recent"]
    result = []
    for form, date, acc, primary, items in zip(
        recent["form"], recent["filingDate"], recent["accessionNumber"],
        recent["primaryDocument"], recent["items"]
    ):
        if form == "8-K" and "2.02" in items:
            result.append({"date": date, "accession": acc, "primary": primary})
        if len(result) == max_n:
            break
    return result

def get_exhibit_urls(cik_raw, accession, primary_doc):
    acc_clean = accession.replace("-", "")
    base = f"{BASE_ARCHIVE}/{cik_raw}/{acc_clean}"
    r = requests.get(f"{base}/{primary_doc}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    hrefs = re.findall(r'(?<![:\w])href=["\']([^"\'#?]+)["\']', r.text, re.IGNORECASE)
    urls, seen = [], set()
    for h in hrefs:
        name = h.split("/")[-1].lower()
        if not name or name == primary_doc.lower() or not name.endswith((".htm", ".html")):
            continue
        if any(x in name for x in ("r1.htm", "r2.htm")) or re.match(r"^r\d+\.htm$", name):
            continue
        url = f"{base}/{name}"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls

def fetch_text(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = re.sub(r"<[^>]+>", "\n", r.text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&#[0-9]+;", " ", text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)

ticker = sys.argv[1]
max_n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
cik_padded, company = get_cik(ticker)
cik_raw = str(int(cik_padded))
print(f"COMPANY:{company}")
for filing in get_earnings_8ks(cik_padded, max_n):
    time.sleep(0.15)
    try:
        urls = get_exhibit_urls(cik_raw, filing["accession"], filing["primary"])
    except Exception:
        continue
    for url in urls:
        try:
            time.sleep(0.1)
            text = fetch_text(url)
        except Exception:
            continue
        if len(text) < 500:
            continue
        print(f"FILING_DATE:{filing['date']} URL:{url}")
        print("---TEXT_START---")
        print(text)
        print("---TEXT_END---")
```

Run: `python3 -c "<script>" TICKER 8`

From the returned filings (oldest to newest), for each quarter:
- Read the financial-results exhibit (press release and/or shareholder letter — whichever carries the numbers table; skip pure legal boilerplate exhibits).
- **Pick 4-6 KPIs this company itself discloses/emphasizes** as operating metrics — e.g. a "Key Operating Metrics" table, subscriber/user counts, segment revenue mix, same-store sales, units shipped, bookings, take rate — whatever is native to that business. Prefer metrics management repeats every quarter (so history is comparable) over one-off callouts. Always include the core financials (revenue, and a margin metric) alongside 2-4 operating-specific ones.
- Extract the value for each locked KPI, for each quarter found.

Write `$JSON`:
```json
{
  "ticker": "TICKER",
  "company": "Company Name",
  "kpis": [{"key": "snake_case_key", "label": "Human Label", "unit": "M | $M | % | x | etc"}],
  "kpi_rationale": "1-3 sentences: why these, sourced from what management itself emphasizes.",
  "history": [
    {"period": "Q# YYYY", "report_date": "YYYY-MM-DD", "values": {"key": number_or_null, ...}, "source": "SEC EDGAR 8-K <url>"}
  ]
}
```
`history` sorted oldest → newest. Use `null` for a KPI not disclosed that quarter — never invent a number.

### 3b. Later runs — append only new quarters
Run the same script with `max_n=2` (covers a freshly-reported quarter plus overlap). Compare `FILING_DATE`s against the last `report_date` already in `$JSON` — skip anything not newer.

For each new quarter, extract values for the **already-locked** `kpis` list only (don't relitigate the KPI choice — that's what keeps the trend apples-to-apples). If the filing no longer discloses a previously-tracked KPI, use `null` and note it in that quarter's `source` field (e.g. `"... (DAU not disclosed this release)"`). If it discloses a clearly important new metric not in the locked list, mention it to the user — don't add it unilaterally.

Append the new entrie(s) to `history`, keep oldest → newest order, save `$JSON`.

### 4. Render the dashboard
```bash
cd $REPO && python3 scripts/generate_kpi_tracker.py $TICKER
```

### 5. First ticker ever tracked only
Confirm `index.html` already has the "📊 KPI Tracker" card under `section-equities` linking to `reports/kpi-tracker/index.html` (added once when this skill was created — should already be there). If missing, add it following the site's `dashboard-card` template in `SITE_STRUCTURE.md`.

### 6. Publish
```bash
cd $REPO
git add reports/kpi-tracker/$TICKER/kpis.json reports/kpi-tracker/$TICKER/index.html reports/kpi-tracker/index.html
git commit -m "Update $TICKER KPI tracker ($(date +%Y-%m-%d))"
git pull --rebase && git push
```

Confirm: published at `https://boquin.xyz/reports/kpi-tracker/$TICKER/index.html`. Report the latest quarter's values and QoQ/YoY moves for each tracked KPI.
