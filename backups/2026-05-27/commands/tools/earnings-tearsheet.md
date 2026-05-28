---
description: Cold sell-side Q earnings tearsheet for any ticker — fetches transcript from SEC EDGAR + consensus data, formats into 4-section recap, posts to boquin.xyz/reports/earnings/
---

Produce an earnings tearsheet for the ticker and quarter specified in `$ARGUMENTS`.

## Arguments
`$ARGUMENTS` — ticker and quarter/year (e.g. `AAPL Q2 2025`, `MSFT Q3 FY2025`)

## Steps

### 1. Parse Arguments
Extract TICKER and QUARTER/YEAR from `$ARGUMENTS`. If either is missing, ask the user before proceeding.

### 2. Fetch Earnings Transcript / Press Release
Run the script below to pull the most recent 8-K exhibit from SEC EDGAR. Save the `filing_date` (YYYY-MM-DD) — it becomes the filename date.

```python
import requests, re, time, os, sys

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

def get_recent_8ks(cik_padded):
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    recent = r.json()["filings"]["recent"]
    result = []
    for form, date, acc, primary in zip(
        recent["form"], recent["filingDate"],
        recent["accessionNumber"], recent["primaryDocument"]
    ):
        if form == "8-K":
            result.append({"date": date, "accession": acc, "primary": primary})
        if len(result) == 15:
            break
    return result

def get_exhibit_urls(cik_raw, accession, primary_doc):
    acc_clean = accession.replace("-", "")
    base = f"{BASE_ARCHIVE}/{cik_raw}/{acc_clean}"
    r = requests.get(f"{base}/{primary_doc}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    hrefs = re.findall(r'(?<![:\w])href=["\']([^"\'#?]+)["\']', r.text, re.IGNORECASE)
    seen = {}
    for h in hrefs:
        name = h.split("/")[-1].lower()
        if not name or name == primary_doc.lower():
            continue
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in ("htm", "html", "txt", "pdf"):
            continue
        score = 10 if "transcript" in name else (5 if re.search(r"ex.?99|exhibit.?99", name) else 1)
        url = f"{base}/{name}"
        if url not in seen or seen[url] < score:
            seen[url] = score
    return sorted([(score, url) for url, score in seen.items()], key=lambda x: -x[0])

def fetch_text(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.text
    if "<html" in text[:300].lower():
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;|&#160;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&#8212;", "—", text)
        text = re.sub(r"&#[0-9]+;", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

TRANSCRIPT_MARKERS = [
    "Operator:", "OPERATOR:", "Question-and-Answer", "Q&A SESSION",
    "QUESTION AND ANSWER", "Good morning,", "Good afternoon,",
    "Thank you for standing by", "Thank you for joining",
    "conference call", "CONFERENCE CALL",
]

def is_transcript(text):
    return sum(1 for m in TRANSCRIPT_MARKERS if m in text) >= 2

def run(ticker):
    cik_padded, company = get_cik(ticker)
    cik_raw = str(int(cik_padded))
    filings = get_recent_8ks(cik_padded)
    for filing in filings:
        time.sleep(0.15)
        try:
            candidates = get_exhibit_urls(cik_raw, filing["accession"], filing["primary"])
        except Exception:
            continue
        if not candidates:
            continue
        for _, url in candidates:
            try:
                time.sleep(0.1)
                text = fetch_text(url)
            except Exception:
                continue
            if len(text) < 300:
                continue
            label = "TRANSCRIPT" if is_transcript(text) else "PRESS_RELEASE"
            print(f"FILING_DATE:{filing['date']}")
            print(f"COMPANY:{company}")
            print(f"TYPE:{label}")
            print(f"CHARS:{len(text)}")
            print("---TEXT_START---")
            print(text)
            return
    print("No earnings exhibit found.")

ticker = sys.argv[1] if len(sys.argv) > 1 else input("Ticker: ").strip()
run(ticker)
```

Run: `python3 -c "<script>" TICKER` or pipe via stdin. Capture full output — you need the filing date and the full text body.

### 3. Get Financials
```bash
python3 /Users/macproajb/claude_projects/yfinance_client/yfinance_financials.py TICKER
```
Use for gross margin, operating margin, revenue, and EPS figures. Cross-reference with the EDGAR text.

### 4. Get Consensus Estimates
Run two WebSearches:
- `"TICKER" "Q[X] [YEAR]" earnings revenue EPS consensus estimate beat miss`
- `"TICKER" "[quarter] [year]" earnings results analyst expectations`

Extract: consensus revenue estimate, consensus EPS estimate, actual beat/miss amounts. Mark `N/A` for anything not found.

### 5. Write the Tearsheet
Synthesize all data into this exact format. Cold, no filler. Bold for emphasis. `N/A` when consensus unavailable.

```
# [TICKER] | Q[X] [YEAR] Recap

### 1. The Numbers
- **Revenue:** [Value] ([YoY %]) | [Beat/Miss] by [Amount]
- **Adj. EPS:** [Value] ([YoY %]) | [Beat/Miss] by [Amount]
- **Margins:** Gross: [X]% | Operating: [Y]% ([expansion/contraction driver])

### 2. Segment Performance
- [Top Segment Name]: [Revenue] ([YoY %]) | [Key Driver]
- [Secondary Segment]: [Revenue] ([YoY %]) | [Key Driver]

### 3. Management Narrative & Guidance
- **The "Why":** [Bullet 1 — primary beat/miss driver]
- **The "Why":** [Bullet 2 — secondary factor]
- **Guidance Update:** [Raised/Lowered/Reiterated] FY outlook for [Metric] to [Range].
- **Capital Allocation:** [Buyback authorization / dividend change / debt paydown — specifics].

### 4. Analyst Focus (Q&A)
- [One sentence on the most contentious Q&A topic.]
```

### 6. Save & Deploy

Use the EDGAR filing date as YYYY-MM-DD for the filename.

```bash
REPO=/Users/macproajb/claude_projects/boquin.github.io
TICKER=<TICKER>
DATE=<FILING_DATE>

git -C $REPO pull
# Write tearsheet content to $REPO/reports/earnings/$TICKER-$DATE.md
python3 $REPO/scripts/generate_earnings_index.py
git -C $REPO add reports/earnings/$TICKER-$DATE.md reports/earnings/index.html
git -C $REPO commit -m "Add $TICKER Q[X] [YEAR] earnings tearsheet"
git -C $REPO pull --rebase && git -C $REPO push
```

Confirm: report published at `https://boquin.xyz/reports/earnings/`.
