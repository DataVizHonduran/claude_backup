#!/usr/bin/env python3
"""
ECB Watcher — Standalone Script
Mirrors fed_watcher_standalone.py for the ECB Governing Council.

Data sources (zero paid APIs):
  - ecb.europa.eu — speeches/interviews RSS, GC accounts, press conferences (requests + BS4)
  - Google News RSS — financial media coverage (feedparser)
  - NCB supplemental feeds — Bundesbank, ECB Blog (feedparser)

LLM layer:
  - HuggingFace Inference API (google/gemma-4-31B-it)

Usage:
    HF_TOKEN=hf_xxx python3 scripts/ecb_watcher_standalone.py
    HF_TOKEN=hf_xxx python3 scripts/ecb_watcher_standalone.py --days 14
    HF_TOKEN=hf_xxx python3 scripts/ecb_watcher_standalone.py --dry-run

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/ecb-watcher/ecb-watcher-YYYY-MM-DD.html
    reports/ecb-watcher/ecb-watcher-YYYY-MM-DD.md
"""

import os
import sys
import re
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from pathlib import Path

import requests
import feedparser
import markdown as md_lib
from bs4 import BeautifulSoup
from huggingface_hub import InferenceClient
from cb_monitor_utils import regenerate_cb_monitor

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID = "google/gemma-4-31B-it"

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ECBWatcher/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Encoding": "gzip, deflate",
}

RATE_LIMIT_SLEEP = 0.3   # seconds between ECB page fetches

ECB_BASE = "https://www.ecb.europa.eu"

ECB_PAGES = {
    "press_rss":    f"{ECB_BASE}/rss/press.html",       # speeches, interviews, press releases
    "blog_rss":     f"{ECB_BASE}/rss/blog.html",        # ECB Blog
    "accounts":     f"{ECB_BASE}/press/accounts/html/index.en.html",  # GC accounts (≈ FOMC minutes)
    "press_conf":   f"{ECB_BASE}/press/press_conference/html/index.en.html",
}

NEWS_QUERIES = [
    '"ECB" OR "European Central Bank" interest rates inflation 2026',
    '"Christine Lagarde" speech 2026',
    '"Isabel Schnabel" OR "Philip Lane" ECB 2026 rates',
    '"ECB Governing Council" decision statement 2026',
    '"Joachim Nagel" OR "François Villeroy" OR "Klaas Knot" ECB 2026',
    '"Fabio Panetta" OR "Mario Centeno" OR "Robert Holzmann" ECB 2026',
]

NCB_SUPPLEMENTAL = [
    {"name": "Bundesbank",  "url": "https://www.bundesbank.de/service/rss/en/633292/feed.rss"},
    {"name": "ECB Blog",    "url": f"{ECB_BASE}/rss/blog.html"},
]

# ---------------------------------------------------------------------------
# Governing Council hawk/dove baselines
# All 25 members vote at every meeting (unlike FOMC rotation)
# ---------------------------------------------------------------------------
BASELINES = {
    # --- Executive Board (6 members, permanent) ---
    "Christine Lagarde":           "Neutral — consensus-builder; rarely signals personal rate preference",
    "Luis de Guindos":             "Neutral — cautious on financial stability; follows committee median",
    "Philip Lane":                 "Neutral/Dovish — Chief Economist; data-dependent; emphasizes underlying inflation",
    "Isabel Schnabel":             "Neutral/Hawkish — most hawkish on Executive Board; persistent on 2% target",
    "Frank Elderson":              "Neutral/Dovish — climate focus; aligns with Lagarde consensus",
    "Piero Cipollone":             "Neutral/Dovish — payments/digital euro focus; limited rate hawkishness",
    # --- NCB Governors (19 members) ---
    "Joachim Nagel":               "Hawkish — Bundesbank president; strong 2% commitment; slow to ease",
    "François Villeroy de Galhau": "Neutral/Dovish — Banque de France; supports gradual easing as inflation falls",
    "Fabio Panetta":               "Dovish — Banca d'Italia; emphasizes growth risks; favors faster easing",
    "José Luis Escrivá":           "Neutral — Banco de España (since 2024); limited public record on rates",
    "Klaas Knot":                  "Neutral/Hawkish — DNB Netherlands; cautious on premature easing",
    "Pierre Wunsch":               "Neutral/Hawkish — NBB Belgium; vigilant on wage-driven inflation",
    "Robert Holzmann":             "Hawkish — OeNB Austria; serial hawk; last to support cuts",
    "Mário Centeno":               "Dovish — Banco de Portugal; consistently favors faster rate cuts",
    "Olli Rehn":                   "Neutral/Dovish — Suomen Pankki Finland; data-dependent; supports gradual cuts",
    "Gabriel Makhlouf":            "Neutral — Central Bank Ireland; measured; follows ECB consensus",
    "Yannis Stournaras":           "Dovish — Bank of Greece; advocates faster easing; growth risk emphasis",
    "Peter Kažimír":               "Neutral/Hawkish — NBS Slovakia; cautious; slow to ease",
    "Madis Müller":                "Hawkish — Eesti Pank Estonia; persistent inflation concern",
    "Mārtiņš Kazāks":             "Hawkish — Latvijas Banka; vigilant on second-round effects",
    "Gediminas Šimkus":            "Neutral/Hawkish — LB Lithuania; data-dependent but cautious",
    "Boštjan Vasle":               "Neutral — Banka Slovenije; limited divergence from consensus",
    "Edward Scicluna":             "Neutral/Dovish — Central Bank Malta; aligns with dovish camp",
    "Boris Vujčić":                "Neutral — HNB Croatia; balanced; consensus-follower",
    "Gaston Reinesch":             "Neutral/Dovish — BCL Luxembourg; low-profile; consensus-follower",
    "Constantinos Herodotou":      "Neutral/Dovish — CBC Cyprus; growth-focused; aligned with doves",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> requests.Response | None:
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=BASE_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                time.sleep(RATE_LIMIT_SLEEP)
                return resp
            if resp.status_code in (429, 503):
                wait = 30 * (attempt + 1)
                print(f"  Rate limited ({resp.status_code}) — waiting {wait}s ...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  HTTP {resp.status_code} for {url}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Fetch error ({url}): {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    return None


def _soup(url: str) -> BeautifulSoup | None:
    resp = _get(url)
    if resp is None:
        return None
    return BeautifulSoup(resp.text, "html.parser")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_rss_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# Layer 1: ecb.europa.eu scraping
# ---------------------------------------------------------------------------

def scrape_ecb_speeches(days: int = 30) -> list[dict]:
    """
    Fetch ECB speeches and interviews via the press RSS feed.
    Title format: "Speaker Name: Speech Title" — split on first colon.
    Filters to speech/interview entries by checking for known speaker names.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    known_speakers = set(BASELINES.keys())

    print("Fetching ECB press RSS ...", file=sys.stderr)
    feed = feedparser.parse(ECB_PAGES["press_rss"])

    items = []
    for entry in feed.entries:
        pub_date = _parse_rss_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        title = getattr(entry, "title", "").strip()
        link  = getattr(entry, "link",  "").strip()
        if not title or not link:
            continue

        # ECB title format: "FirstName LastName: Speech Title"
        speaker = ""
        speech_title = title
        if ":" in title:
            candidate, rest = title.split(":", 1)
            candidate = candidate.strip()
            # Accept if matches a known GC member (full or last name)
            for known in known_speakers:
                if known in candidate or candidate in known:
                    speaker = known
                    speech_title = rest.strip()
                    break
            if not speaker:
                # Still treat as speech if candidate looks like a name (≤4 words, no numbers)
                words = candidate.split()
                if 1 <= len(words) <= 4 and not any(c.isdigit() for c in candidate):
                    speaker = candidate
                    speech_title = rest.strip()

        full_url = link if link.startswith("http") else ECB_BASE + link

        items.append({
            "source":   "ECB Speech/Interview",
            "date":     pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title":    speech_title or title,
            "speaker":  speaker,
            "url":      full_url,
            "text":     "",
        })

    print(f"  Found {len(items)} ECB press items in last {days} days.", file=sys.stderr)
    return items


def scrape_gc_accounts(days: int = 30) -> list[dict]:
    """
    Scrape ECB Governing Council accounts page (equivalent of FOMC minutes).
    Returns the 2 most recent account documents.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print("Fetching GC accounts page ...", file=sys.stderr)
    soup = _soup(ECB_PAGES["accounts"])
    if not soup:
        return []

    items = []
    for link in soup.select("a[href]")[:40]:
        href  = link.get("href", "")
        label = link.get_text(strip=True)
        if not label or len(label) < 5:
            continue
        if not any(k in href.lower() for k in ["account", "monetary", "minutes"]):
            continue
        full_url = href if href.startswith("http") else ECB_BASE + href

        # Try to extract date from label or URL
        pub_date = ""
        m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4})", label)
        if m:
            pub_date = m.group(1)

        items.append({
            "source":   "GC Accounts (Minutes)",
            "date":     pub_date,
            "title":    label,
            "speaker":  "Governing Council",
            "url":      full_url,
            "text":     "",
        })
        if len(items) >= 3:
            break

    print(f"  Found {len(items)} GC account documents.", file=sys.stderr)
    return items


def scrape_press_conference(days: int = 30) -> list[dict]:
    """Grab the 2 most recent press conference pages."""
    print("Fetching press conference page ...", file=sys.stderr)
    soup = _soup(ECB_PAGES["press_conf"])
    if not soup:
        return []

    items = []
    seen = set()
    for link in soup.select("a[href]"):
        href  = link.get("href", "")
        label = link.get_text(strip=True)
        if not label or href in seen or len(label) < 10:
            continue
        if not any(k in href.lower() for k in ["press_conference", "monetary-policy-statement"]):
            continue
        seen.add(href)
        full_url = href if href.startswith("http") else ECB_BASE + href
        items.append({
            "source":   "Press Conference",
            "date":     "",
            "title":    label,
            "speaker":  "Christine Lagarde",
            "url":      full_url,
            "text":     "",
        })
        if len(items) >= 3:
            break

    print(f"  Found {len(items)} press conference links.", file=sys.stderr)
    return items


def fetch_article_text(url: str, max_chars: int = 3000) -> str:
    """Best-effort extraction of article body text from a URL."""
    if not url or "pdf" in url.lower():
        return ""
    resp = _get(url, timeout=30)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = (
        soup.select_one("article, .speech-content, .content-body, main, #main-wrapper, #content")
        or soup.body
    )
    if not body:
        return ""
    text = re.sub(r"\s{3,}", "\n\n", body.get_text(separator=" ", strip=True))
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Layer 2: Google News RSS
# ---------------------------------------------------------------------------

def search_google_news(query: str, max_results: int = 10) -> list[dict]:
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_results]:
        pub_date = _parse_rss_date(entry)
        items.append({
            "source":  "Google News RSS",
            "query":   query,
            "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title":   getattr(entry, "title", ""),
            "url":     getattr(entry, "link", ""),
            "summary": _strip_html(getattr(entry, "summary", "")),
        })
    return items


def search_news(queries: list[str], days: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen_urls: set[str] = set()
    results = []

    for q in queries:
        print(f"  News search: {q[:60]} ...", file=sys.stderr)
        for item in search_google_news(q):
            if item["url"] in seen_urls:
                continue
            if item["date"]:
                try:
                    d = datetime.fromisoformat(item["date"]).replace(tzinfo=timezone.utc)
                    if d < cutoff:
                        continue
                except ValueError:
                    pass
            seen_urls.add(item["url"])
            results.append(item)
        time.sleep(0.5)

    print(f"  Total news items after dedup: {len(results)}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Layer 3: NCB supplemental RSS
# ---------------------------------------------------------------------------

def fetch_ncb_rss(days: int = 30) -> list[dict]:
    """Fetch NCB supplemental RSS feeds for context."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items = []
    for source in NCB_SUPPLEMENTAL:
        print(f"  NCB RSS ({source['name']}): {source['url']}", file=sys.stderr)
        feed = feedparser.parse(source["url"])
        for entry in feed.entries:
            pub_date = _parse_rss_date(entry)
            if pub_date and pub_date < cutoff:
                continue
            items.append({
                "source":  f"NCB — {source['name']}",
                "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title":   getattr(entry, "title", ""),
                "url":     getattr(entry, "link", ""),
                "summary": _strip_html(getattr(entry, "summary", ""))[:500],
            })
        time.sleep(0.3)
    print(f"  NCB RSS items: {len(items)}", file=sys.stderr)
    return items


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_context_prompt(
    speeches: list[dict],
    gc_docs: list[dict],
    news: list[dict],
    ncb: list[dict],
    days: int,
    today: str,
) -> str:
    def _fmt_items(items: list[dict], include_text: bool = True) -> str:
        parts = []
        for it in items:
            chunk = f"[{it.get('date', 'n/a')}] {it.get('title', '')} — {it.get('speaker', it.get('source', ''))}"
            if it.get("url"):
                chunk += f"\nURL: {it['url']}"
            body = it.get("text") or it.get("summary", "")
            if include_text and body:
                chunk += f"\nExcerpt: {body[:800]}"
            parts.append(chunk)
        return "\n\n".join(parts) if parts else "(none found)"

    baselines_md = "\n".join(f"- {k}: {v}" for k, v in BASELINES.items())

    prompt = f"""You are a Eurozone monetary policy analyst producing an ECB Watcher report.
Today: {today}
Coverage period: last {days} days

## Known Hawk/Dove Baselines (use as prior, only override with direct evidence)
{baselines_md}

---

## DATA GATHERED

### 1. ECB Official Speeches & Interviews ({len(speeches)} items)
{_fmt_items(speeches)}

### 2. GC Accounts & Press Conferences ({len(gc_docs)} items)
{_fmt_items(gc_docs)}

### 3. Financial News ({len(news)} items)
{_fmt_items(news, include_text=False)}

### 4. NCB Supplemental Research ({len(ncb)} items)
{_fmt_items(ncb, include_text=False)}

---

## REQUIRED OUTPUT

Produce the full ECB Watcher report in this exact structure:

### Executive Summary (≤150 words)
Brief overview of the most significant statements and GC updates from the past {days} days.

### Governing Council Member Pronouncements

| Date | Official | Role | Venue/Context | Key Statement | Policy Signal | Evolution vs Baseline |
|------|----------|------|---------------|---------------|---------------|-----------------------|

### ECB Official Communications

| Date | Document Type | Title | Key Takeaways | Policy Implications |
|------|---------------|-------|---------------|---------------------|

### Thematic Analysis

**1. Inflation Assessment**
**2. Growth Outlook**
**3. Labor Markets & Wages**
**4. Financial Conditions & Credit**
**5. Balance Sheet (APP/PEPP rundown)**
**6. Forward Guidance Evolution**

### Hawk-Dove Spectrum Analysis

```
HAWKISH (favor slower cuts / extended pause)
├─ [Names and recent positioning]

NEUTRAL/DATA-DEPENDENT
├─ [Names and recent positioning]

DOVISH (favor faster / deeper cuts)
└─ [Names and recent positioning]
```

**Key Shifts Identified:**

### All 25 Voting Members Focus

| Official | Institution | Current Stance | Key Quote |
|----------|-------------|----------------|-----------|

### Dissent Watch
(any dissents or verbal signals of dissent — note ECB rarely publishes formal dissents)

---

Rules:
- Only cite verifiable information from the data above.
- If an official has no statements in the data, note "No public comments found".
- Policy Signal classification: Hawkish / Dovish / Neutral / Mixed
- 90-DAY RECENCY RULE: Only reference specific prior statements when they appear in the data above; otherwise use "Consistent with historical [lean] baseline".
- Unlike the Fed, all 25 ECB Governing Council members vote at every meeting — note this in the voting member table.
"""
    return prompt


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_gemma(messages: list[dict], hf_token: str, max_tokens: int = 4096) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(5):
        try:
            stream = client.chat.completions.create(
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
                stream=True,
            )
            parts = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
                    print(delta, end="", flush=True)
            print()
            return "".join(parts)
        except Exception as e:
            is_rate_limit = any(x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if is_rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n  HF rate limit — waiting {wait}s (attempt {attempt+1}/5) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# HTML / output
# ---------------------------------------------------------------------------

HTML_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 1000px; margin: 0 auto; padding: 20px;
    line-height: 1.6; background: #f5f5f5; color: #333;
}
.container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
h1 { color: #003189; border-bottom: 3px solid #003189; padding-bottom: 10px; }
h2 { color: #003189; border-bottom: 2px solid #e8f0fe; padding-bottom: 6px; margin-top: 36px; }
h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
h4 { color: #555; margin-top: 20px; }
.meta { color: #777; font-size: 0.85em; margin: 6px 0 20px; }
.back-link { display: inline-block; margin-bottom: 20px; color: #003189; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }
th { background: #003189; color: white; padding: 10px 12px; text-align: left; }
td { border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }
pre code { background: none; padding: 0; }
blockquote {
    border-left: 4px solid #003189; margin: 16px 0; padding: 8px 16px;
    background: #e8f0fe; border-radius: 0 4px 4px 0; color: #333;
}
strong { color: #111; }
ul, ol { padding-left: 1.5em; }
li { margin: 4px 0; }
hr { border: none; border-top: 2px solid #eee; margin: 32px 0; }
a { color: #003189; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ECB Watcher — {date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">← ECB Watcher Archive</a>
    <h1>🇪🇺 ECB Watcher — {date}</h1>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Coverage: last {days} days &nbsp;|&nbsp;
        Sources: ecb.europa.eu · Google News RSS · NCB feeds &nbsp;|&nbsp;
        Model: {model}
    </p>
    <hr>
    {body}
</div>
</body>
</html>"""

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ECB Watcher — Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #003189; border-bottom: 3px solid #003189; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #003189; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #003189; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
        .back-link {{ display: inline-block; margin-bottom: 20px; color: #003189; text-decoration: none; }}
        .back-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
<div class="container">
    <a href="../../index.html" class="back-link">← Back to Portfolio</a>
    <h1>🇪🇺 ECB Watcher</h1>
    <p class="description">
        ECB Governing Council speeches, interviews, and policy communications — tracked every 3 days
        using <strong>ecb.europa.eu</strong>, Google News RSS, and NCB feeds,
        analyzed by Gemma 4. All 25 Governing Council members covered.
    </p>
    <ul class="report-list">
        {items}
    </ul>
</div>
</body>
</html>"""


def _markdown_to_html(md_text: str) -> str:
    return md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )


def regenerate_index(out_dir: Path) -> None:
    reports = sorted(out_dir.glob("ecb-watcher-*.html"), reverse=True)
    items = []
    for i, path in enumerate(reports):
        date_str = path.stem.replace("ecb-watcher-", "")
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">ECB Watcher — {date_str}{badge}</a>'
            f'<span class="report-date">{date_str}</span>'
            f'</li>'
        )
    (out_dir / "index.html").write_text(
        INDEX_TEMPLATE.format(items="\n        ".join(items) if items else "<li>No reports yet.</li>"),
        encoding="utf-8",
    )


def save_output(report: str, today: str, out_dir: Path, days: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    md_header = (
        f"# ECB Watcher — {today}\n\n"
        f"**Generated:** {generated_at} UTC  \n"
        f"**Coverage:** {days} days ending {today}  \n"
        f"**Model:** {MODEL_ID}\n\n"
        "---\n\n"
    )
    md_path = out_dir / f"ecb-watcher-{today}.md"
    md_path.write_text(md_header + report, encoding="utf-8")

    body_html = _markdown_to_html(report)
    html_content = HTML_TEMPLATE.format(
        date=today,
        generated_at=generated_at,
        days=days,
        model=MODEL_ID,
        css=HTML_CSS,
        body=body_html,
    )
    html_path = out_dir / f"ecb-watcher-{today}.html"
    html_path.write_text(html_content, encoding="utf-8")

    regenerate_index(out_dir)
    regenerate_cb_monitor(out_dir.parent.parent)

    print(f"\nMarkdown : {md_path}", file=sys.stderr)
    print(f"HTML     : {html_path}", file=sys.stderr)
    print(f"Index    : {out_dir / 'index.html'}", file=sys.stderr)
    return html_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ECB Watcher — standalone scrape + LLM analysis")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to write output files (default: reports/ecb-watcher/)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip LLM call and file write")
    parser.add_argument("--fetch-articles", action="store_true",
                        help="Fetch full article text for speeches (slower, uses more tokens)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports/ecb-watcher")

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== ECB Watcher — {today} (lookback {args.days}d) ===", file=sys.stderr)

    # --- Scrape ---
    speeches = scrape_ecb_speeches(days=args.days)
    gc_docs  = scrape_gc_accounts(days=args.days) + scrape_press_conference(days=args.days)
    news     = search_news(NEWS_QUERIES, days=args.days)
    ncb      = fetch_ncb_rss(days=args.days)

    if args.fetch_articles and not args.dry_run:
        print(f"Fetching article text for up to 10 speeches ...", file=sys.stderr)
        for item in speeches[:10]:
            item["text"] = fetch_article_text(item["url"])

    total = len(speeches) + len(gc_docs) + len(news) + len(ncb)
    print(f"\n--- Scrape summary ---", file=sys.stderr)
    print(f"  Speeches/Interviews: {len(speeches)}", file=sys.stderr)
    print(f"  GC docs:             {len(gc_docs)}", file=sys.stderr)
    print(f"  News items:          {len(news)}", file=sys.stderr)
    print(f"  NCB items:           {len(ncb)}", file=sys.stderr)
    print(f"  TOTAL:               {total}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] Skipping LLM call.", file=sys.stderr)
        return

    if total == 0:
        print("No data gathered — aborting.", file=sys.stderr)
        sys.exit(1)

    # --- LLM ---
    context = build_context_prompt(speeches, gc_docs, news, ncb, args.days, today)
    print(f"\n[Gemma4] Generating ECB Watcher report ({len(context)} chars context) ...", file=sys.stderr)

    messages = [
        {"role": "system", "content": "You are a senior Eurozone monetary policy analyst at a top investment bank."},
        {"role": "user",   "content": context},
    ]
    report = call_gemma(messages, hf_token, max_tokens=4096)

    # --- Save ---
    save_output(report, today, out_dir, args.days)
    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
