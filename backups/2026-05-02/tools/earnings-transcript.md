---
description: Fetch the most recent earnings call transcript (or press release fallback) for any ticker from SEC EDGAR 8-K filings — free, no API key
---

Fetch the most recent earnings exhibit from SEC EDGAR for the ticker in `$ARGUMENTS`.

## Arguments
`$ARGUMENTS` — ticker symbol (e.g. AAPL, MSFT, JPM)

## Steps

1. Extract ticker from `$ARGUMENTS`. If missing, ask the user.
2. Run the script below (only requires `requests`).
3. Report: company name, filing date, whether it's a TRANSCRIPT or PRESS_RELEASE, char count, and print the first 3000 characters.
4. Confirm the `.txt` file was saved.

## Script

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
    # avoid xlink:href and other namespace attrs; only match bare href=
    hrefs = re.findall(r'(?<![:\w])href=["\']([^"\'#?]+)["\']', r.text, re.IGNORECASE)
    seen = {}
    for h in hrefs:
        name = h.split("/")[-1].lower()
        # require a real document extension to filter out XBRL taxonomy refs
        if not name or name == primary_doc.lower():
            continue
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in ("htm", "html", "txt", "pdf"):
            continue
        score = 0
        if "transcript" in name: score = 10
        elif re.search(r"ex.?99|exhibit.?99", name): score = 5
        else: score = 1
        url = f"{base}/{name}"
        if url not in seen or seen[url] < score:
            seen[url] = score
    # return (score, url) tuples sorted by descending score
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
    print(f"Resolving {ticker.upper()} → CIK...")
    cik_padded, company = get_cik(ticker)
    cik_raw = str(int(cik_padded))
    print(f"  {company} | CIK {cik_raw}")

    filings = get_recent_8ks(cik_padded)
    print(f"  Scanning {len(filings)} recent 8-K filings...")

    for filing in filings:
        time.sleep(0.15)
        try:
            candidates = get_exhibit_urls(cik_raw, filing["accession"], filing["primary"])
        except Exception as e:
            print(f"  Skip {filing['date']}: {e}")
            continue

        if not candidates:
            continue

        for _, url in candidates:
            try:
                time.sleep(0.1)
                text = fetch_text(url)
            except Exception as e:
                print(f"  Fetch error: {e}")
                continue

            if len(text) < 300:
                continue

            label = "TRANSCRIPT" if is_transcript(text) else "PRESS_RELEASE"
            out = f"{ticker.upper()}_{filing['date']}_{label}.txt"

            print(f"\n{'='*60}")
            print(f"  Company    : {company}")
            print(f"  Filed      : {filing['date']}")
            print(f"  Type       : {label}")
            print(f"  Source     : {url.split('/')[-1]}")
            print(f"  Characters : {len(text):,}")
            print(f"{'='*60}\n")
            print(text[:3000])

            cwd = os.getcwd()
            with open(os.path.join(cwd, out), "w", encoding="utf-8") as f:
                f.write(f"Company: {company}\nFiled: {filing['date']}\nType: {label}\nSource: {url}\n\n")
                f.write(text)
            print(f"\n[Full text saved → {out}]")
            return

    print("No earnings exhibit found in recent 8-K filings.")


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else input("Ticker: ").strip()
    run(ticker)
```

## Notes
- EDGAR rate limit: 10 req/sec. Script sleeps 0.15s per filing + 0.1s per exhibit.
- Flow: submissions JSON → primary 8-K doc → parse exhibit hrefs → score (transcript=10, ex99=5, htm=1) → fetch + classify.
- Transcript detection: ≥2 of TRANSCRIPT_MARKERS present. Most companies only file press releases on EDGAR; actual transcripts are less common.
- Output saved to current working directory as `{TICKER}_{date}_{TYPE}.txt`.
