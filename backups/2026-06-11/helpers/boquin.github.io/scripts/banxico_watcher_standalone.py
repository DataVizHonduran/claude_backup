#!/usr/bin/env python3
"""
Banxico Watcher — Standalone Script
Mirrors rba_watcher_standalone.py for Banco de México's Junta de Gobierno.

Data sources (zero paid APIs):
  - banxico.org.mx — speeches, meeting minutes, rate decisions, quarterly reports (requests + BS4)
  - Google News RSS — financial media coverage (feedparser)

LLM layer:
  - HuggingFace Inference API (google/gemma-4-31B-it)

Usage:
    HF_TOKEN=hf_xxx python3 scripts/banxico_watcher_standalone.py
    HF_TOKEN=hf_xxx python3 scripts/banxico_watcher_standalone.py --days 14
    HF_TOKEN=hf_xxx python3 scripts/banxico_watcher_standalone.py --dry-run
    HF_TOKEN=hf_xxx python3 scripts/banxico_watcher_standalone.py --fetch-articles

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/banxico-watcher/banxico-watcher-YYYY-MM-DD.html
    reports/banxico-watcher/banxico-watcher-YYYY-MM-DD.md
"""

import os
import sys
import re
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin
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
        "Mozilla/5.0 (compatible; BanxicoWatcher/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Encoding": "gzip, deflate",
}

RATE_LIMIT_SLEEP = 0.3   # seconds between Banxico page fetches

BANXICO_BASE = "https://www.banxico.org.mx"

BANXICO_PAGES = {
    "speeches":  f"{BANXICO_BASE}/publications-and-press/speeches/speeches-of-the-board-of-gove.html",
    "minutes":   f"{BANXICO_BASE}/publicaciones-y-prensa/minutas-de-las-decisiones-de-politica-monetaria/minutas-politica-monetaria-ta.html",
    "decisions": f"{BANXICO_BASE}/publications-and-press/announcements-of-monetary-policy-decisions/monetary-policy-announcements.html",
    "quarterly": f"{BANXICO_BASE}/publicaciones-y-prensa/informes-trimestrales/informes-trimestrales-precios.html",
}

NEWS_QUERIES = [
    '"Banxico" OR "Banco de México" interest rates inflation 2026',
    '"Victoria Rodríguez" Banxico rates 2026',
    '"Jonathan Heath" Banxico inflation 2026',
    'Banxico "tasa de referencia" decision statement 2026',
    '"core CPI" Mexico Banxico 2026',
    'Mexico peso MXN "Banxico" monetary policy 2026',
    '"Junta de Gobierno" Banxico minutes hawk dove 2026',
]

# ---------------------------------------------------------------------------
# Junta de Gobierno hawk/dove baselines (5 members, equal vote weight)
# Banxico DOES publish individual votes in minutes released ~2 weeks after decision.
# March 26 2026 decision: 3-2 cut to 6.75% (Rodríguez, Cuadra, Mejía FOR; Heath, Borja AGAINST)
# ---------------------------------------------------------------------------
BASELINES = {
    "Victoria Rodríguez Ceja":    "Dovish — Governor since Jan 2022; has guided easing cycle from 11.25% peak; voted for March 2026 cut to 6.75%; emphasizes convergence to 3% target while supporting growth",
    "José Gabriel Cuadra García": "Dovish — Subgobernador since Feb 2025; 26+ years at Banxico economic research; voted for March 2026 cut; technical economist aligned with easing consensus",
    "Omar Mejía Castelazo":       "Dovish — Subgobernador; consistent easing supporter throughout 2025-2026 cycle; term through 2030; voted for March 2026 cut",
    "Jonathan Heath Constable":   "Hawkish — Subgobernador; most hawkish on the board; voted AGAINST March 2026 cut; argues inflation will not converge to 3% by mid-2026; concerned about Banxico credibility; term ends 12/31/2026",
    "Galia Borja Gómez":          "Hawkish (recent shift) — Subgobernadora; voted in favor of 2025 decisions but shifted hawkish in 2026; voted AGAINST March 2026 cut citing persistent inflation; term through 2028",
}

ROLES = {
    "Victoria Rodríguez Ceja":    "Gobernadora (Governor)",
    "José Gabriel Cuadra García": "Subgobernador",
    "Omar Mejía Castelazo":       "Subgobernador",
    "Jonathan Heath Constable":   "Subgobernador",
    "Galia Borja Gómez":          "Subgobernadora",
}

# Spanish month name mapping for date parsing
ES_MONTHS = {
    "enero": "January", "febrero": "February", "marzo": "March",
    "abril": "April", "mayo": "May", "junio": "June",
    "julio": "July", "agosto": "August", "septiembre": "September",
    "octubre": "October", "noviembre": "November", "diciembre": "December",
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


def _parse_date(text: str) -> datetime | None:
    """
    Parse date strings from Banxico pages.
    Handles English and Spanish month names, plus MM/DD/YY and DD/MM/YY short formats.
    For ambiguous N/N/YY dates (both N ≤ 12), tries both formats and picks the non-future one.
    """
    text = text.strip()
    text_norm = text.lower()
    for es, en in ES_MONTHS.items():
        text_norm = text_norm.replace(es, en)
    text_norm = re.sub(r"\bde\b", " ", text_norm).strip()
    text_norm = re.sub(r"\s{2,}", " ", text_norm)

    now = datetime.now(timezone.utc)

    # Named-month patterns (unambiguous)
    for fmt, pat in [
        ("%d %B %Y", r"\d{1,2} \w+ \d{4}"),
        ("%B %Y",    r"\w+ \d{4}"),
        ("%Y-%m-%d", r"\d{4}-\d{2}-\d{2}"),
        ("%d/%m/%Y", r"\d{1,2}/\d{1,2}/\d{4}"),
    ]:
        m = re.search(pat, text_norm, re.IGNORECASE)
        if m:
            try:
                return datetime.strptime(m.group().strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    # Short 2-digit year: try MM/DD/YY and DD/MM/YY, pick the non-future result
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2})\b", text_norm)
    if m:
        a, b, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        candidates = []
        for fmt, mo, dy in [("%m/%d/%y", a, b), ("%d/%m/%y", b, a)]:
            if 1 <= mo <= 12 and 1 <= dy <= 31:
                try:
                    d = datetime.strptime(m.group(), fmt).replace(tzinfo=timezone.utc)
                    candidates.append(d)
                except ValueError:
                    pass
        # Prefer the candidate that isn't in the future; if both or neither, take first
        past = [d for d in candidates if d <= now]
        if past:
            return max(past)   # most recent non-future date
        if candidates:
            return candidates[0]

    return None


# ---------------------------------------------------------------------------
# Layer 1: banxico.org.mx scraping
# ---------------------------------------------------------------------------

def _extract_speaker(title: str) -> str:
    """Match known Junta de Gobierno member names from title or byline.
    Checks every individual name token so 'Victoria Rodríguez' matches
    'Victoria Rodríguez Ceja' even when the apellido materno is absent.
    """
    for full_name in BASELINES:
        for token in full_name.split():
            if len(token) > 3 and token in title:
                return full_name
    return ""


def scrape_banxico_speeches(days: int = 30) -> list[dict]:
    """
    Scrape the Banxico speeches listing page for recent publications.
    Page uses a <table> with <tr> rows: date | title+speaker | "Full text" PDF link.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print("Fetching Banxico speeches page ...", file=sys.stderr)
    soup = _soup(BANXICO_PAGES["speeches"])
    if not soup:
        return []

    items = []
    seen: set[str] = set()

    for row in soup.find_all("tr"):
        # Each row: date cell | title cell | "Full text" PDF link cell
        row_text = row.get_text(separator="|", strip=True)
        pub_date = _parse_date(row_text)
        if pub_date and pub_date < cutoff:
            continue

        # Grab the PDF link (href contains /speeches/ and .pdf)
        pdf_link = None
        for a in row.find_all("a", href=True):
            href = a.get("href", "")
            if "speeches" in href.lower() and ".pdf" in href.lower():
                pdf_link = href if href.startswith("http") else BANXICO_BASE + href
                break
        if not pdf_link or pdf_link in seen:
            continue
        seen.add(pdf_link)

        # Title is the bulk of the row text (strip the date and "Full text")
        title = re.sub(r"^\d{1,2}/\d{1,2}/\d{2,4}\s*\|?\s*", "", row_text)
        title = re.sub(r"\s*\|?\s*Full text\s*$", "", title, flags=re.IGNORECASE).strip()

        speaker = _extract_speaker(row_text)

        items.append({
            "source":  "Banxico Speech",
            "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title":   title[:200],
            "speaker": speaker,
            "url":     pdf_link,
            "text":    "",
        })

    print(f"  Found {len(items)} Banxico speeches in last {days} days.", file=sys.stderr)
    return items


def scrape_board_documents(days: int = 30) -> list[dict]:
    """
    Scrape minutes, decisions, and quarterly report pages for recent links.
    Both pages use <tr> rows: date | title | "Full text"/"Minuta" PDF link.
    Minutes use DD/MM/YY; decisions use MM/DD/YY — _parse_date handles both.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items  = []

    source_map = [
        ("decisions", "Rate Decision"),
        ("minutes",   "Meeting Minutes"),
    ]

    for page_key, source_label in source_map:
        url = BANXICO_PAGES[page_key]
        print(f"Fetching Banxico {source_label} page ...", file=sys.stderr)
        soup = _soup(url)
        if not soup:
            continue

        seen_hrefs: set[str] = set()
        for row in soup.find_all("tr"):
            row_text = row.get_text(separator="|", strip=True)
            if not row_text:
                continue

            # Find the document PDF link in this row
            pdf_link = None
            for a in row.find_all("a", href=True):
                href = a.get("href", "")
                if any(k in href.lower() for k in
                       ["minuta", "minutes", "decision", "announcement",
                        "politica-monetaria", "monetary-policy"]):
                    if href not in seen_hrefs:
                        pdf_link = href if href.startswith("http") else BANXICO_BASE + href
                        seen_hrefs.add(href)
                        break
            if not pdf_link:
                continue

            pub_date = _parse_date(row_text)
            if pub_date and pub_date < cutoff:
                continue

            # Extract title: strip leading date and trailing link text
            title = re.sub(r"^\d{1,2}/\d{1,2}/\d{2,4}\s*\|?\s*", "", row_text)
            title = re.sub(r"\s*\|\s*(Full text|Minuta|Texto completo)\s*.*$", "",
                           title, flags=re.IGNORECASE).strip()
            if not title or len(title) < 10:
                continue

            items.append({
                "source":  source_label,
                "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title":   title[:250],
                "speaker": "Junta de Gobierno",
                "url":     pdf_link,
                "text":    "",
            })

        time.sleep(0.3)

    # Quarterly Inflation Report — grab top 2
    print("Fetching Banxico Quarterly Report page ...", file=sys.stderr)
    soup_q = _soup(BANXICO_PAGES["quarterly"])
    if soup_q:
        q_count = 0
        for row in soup_q.find_all("tr"):
            row_text = row.get_text(separator="|", strip=True)
            pdf_link = None
            for a in row.find_all("a", href=True):
                href = a.get("href", "")
                if any(k in href.lower() for k in
                       ["informe", "trimestral", "quarterly", "inflation-report"]):
                    pdf_link = href if href.startswith("http") else BANXICO_BASE + href
                    break
            if not pdf_link:
                continue
            pub_date = _parse_date(row_text)
            title = re.sub(r"^\d{1,2}/\d{1,2}/\d{2,4}\s*\|?\s*", "", row_text)
            title = re.sub(r"\s*\|?\s*(Full text|Texto completo|Ver)\s*.*$", "",
                           title, flags=re.IGNORECASE).strip()
            items.append({
                "source":  "Quarterly Inflation Report",
                "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title":   title[:250] if title else row_text[:100],
                "speaker": "Junta de Gobierno",
                "url":     pdf_link,
                "text":    "",
            })
            q_count += 1
            if q_count >= 2:
                break

    print(f"  Found {len(items)} board documents.", file=sys.stderr)
    return items


def fetch_article_text(url: str, max_chars: int = 3000) -> str:
    if not url or "pdf" in url.lower():
        return ""
    resp = _get(url, timeout=30)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = (
        soup.select_one("article, .speech-content, .content-body, main, #main, #content")
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
# Prompt builder
# ---------------------------------------------------------------------------

def build_context_prompt(
    speeches: list[dict],
    board_docs: list[dict],
    news: list[dict],
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

    baselines_md = "\n".join(
        f"- {k} ({ROLES.get(k, 'Member')}): {v}" for k, v in BASELINES.items()
    )

    prompt = f"""You are a Mexico monetary policy analyst producing a Banxico Watcher report.
Today: {today}
Coverage period: last {days} days

## Known Hawk/Dove Baselines (use as prior, only override with direct evidence)
{baselines_md}

---

## DATA GATHERED

### 1. Banxico Official Speeches & Addresses ({len(speeches)} items)
{_fmt_items(speeches)}

### 2. Rate Decisions, Meeting Minutes & Quarterly Reports ({len(board_docs)} items)
{_fmt_items(board_docs)}

### 3. Financial News ({len(news)} items)
{_fmt_items(news, include_text=False)}

---

## REQUIRED OUTPUT

Produce the full Banxico Watcher report in this exact structure:

### Executive Summary (≤150 words)
Brief overview of the most significant statements and Junta de Gobierno communications from the past {days} days.

### Board Member Pronouncements

| Date | Official | Role | Venue/Context | Key Statement | Policy Signal | Evolution vs Baseline |
|------|----------|------|---------------|---------------|---------------|-----------------------|

### Official Communications

| Date | Document Type | Title | Key Takeaways | Policy Implications |
|------|---------------|-------|---------------|---------------------|

### Thematic Analysis

**1. Core CPI & Headline Inflation (3% ±1pp target)**
**2. MXN / Real Exchange Rate & FX Intervention Mandate**
**3. Wage Growth & Labor Market (IMSS formal employment)**
**4. Fiscal Deficit & PEMEX (quasi-fiscal risks)**
**5. US Spillovers (Fed policy, tariffs, nearshoring)**
**6. Neutral Rate Estimate & Real Rate Stance**
**7. Forward Guidance Evolution**

### Hawk-Dove Spectrum Analysis

```
HAWKISH (favor slower easing / higher-for-longer)
├─ [Names and recent positioning]

NEUTRAL/DATA-DEPENDENT
├─ [Names and recent positioning]

DOVISH (favor faster easing / lower rates)
└─ [Names and recent positioning]
```

**Key Shifts Identified:**

### All 5 Junta de Gobierno Members Focus

| Official | Role | Current Stance | Key Quote |
|----------|------|----------------|-----------|

### Dissent & Vote Record Watch
(Banxico publishes individual votes in minutes. Flag all split-vote decisions, dissenting rationales, and any shift from recent 3-2 pattern. Note if any member has changed their vote relative to their historical baseline.)

---

Rules:
- Only cite verifiable information from the data above.
- If an official has no statements in the data, note "No public comments found".
- Policy Signal classification: Hawkish / Dovish / Neutral / Mixed
- 90-DAY RECENCY RULE: Only reference specific prior statements when they appear in the data above; otherwise use "Consistent with historical [lean] baseline".
- Key Banxico-specific context:
  - Overnight interbank funding rate: 6.75% (cut from 7.00% on March 26, 2026; 3-2 vote — Rodríguez, Cuadra, Mejía FOR; Heath, Borja AGAINST)
  - Core CPI is the primary inflation gauge; headline target 3% ±1pp
  - Banxico meets 8×/year; minutes released ~2 weeks after decision
  - Individual votes ARE published in minutes (unlike RBA/SNB)
  - Jonathan Heath's term ends 12/31/2026 — potential board composition shift
  - MXN sensitivity to Fed decisions and US tariff developments is a key risk
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
h1 { color: #006847; border-bottom: 3px solid #006847; padding-bottom: 10px; }
h2 { color: #006847; border-bottom: 2px solid #d4edda; padding-bottom: 6px; margin-top: 36px; }
h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
h4 { color: #555; margin-top: 20px; }
.meta { color: #777; font-size: 0.85em; margin: 6px 0 20px; }
.back-link { display: inline-block; margin-bottom: 20px; color: #006847; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }
th { background: #006847; color: white; padding: 10px 12px; text-align: left; }
td { border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }
pre code { background: none; padding: 0; }
blockquote {
    border-left: 4px solid #006847; margin: 16px 0; padding: 8px 16px;
    background: #d4edda; border-radius: 0 4px 4px 0; color: #333;
}
strong { color: #111; }
ul, ol { padding-left: 1.5em; }
li { margin: 4px 0; }
hr { border: none; border-top: 2px solid #eee; margin: 32px 0; }
a { color: #006847; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Banxico Watcher — {date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">&#8592; Banxico Watcher Archive</a>
    <h1>&#127474;&#127485; Banxico Watcher &#8212; {date}</h1>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Coverage: last {days} days &nbsp;|&nbsp;
        Sources: banxico.org.mx &middot; Google News RSS &nbsp;|&nbsp;
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
    <title>Banxico Watcher &#8212; Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #006847; border-bottom: 3px solid #006847; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #006847; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #006847; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
        .back-link {{ display: inline-block; margin-bottom: 20px; color: #006847; text-decoration: none; }}
        .back-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
<div class="container">
    <a href="../../index.html" class="back-link">&#8592; Back to Portfolio</a>
    <h1>&#127474;&#127485; Banxico Watcher</h1>
    <p class="description">
        Banco de M&#233;xico Junta de Gobierno speeches, rate decisions, and meeting minutes &#8212; tracked every 3 days
        using <strong>banxico.org.mx</strong> and Google News RSS,
        analyzed by Gemma 4. All 5 Junta de Gobierno members covered with individual vote dissent watch.
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
    reports = sorted(out_dir.glob("banxico-watcher-*.html"), reverse=True)
    items = []
    for i, path in enumerate(reports):
        date_str = path.stem.replace("banxico-watcher-", "")
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">Banxico Watcher &#8212; {date_str}{badge}</a>'
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
        f"# Banxico Watcher — {today}\n\n"
        f"**Generated:** {generated_at} UTC  \n"
        f"**Coverage:** {days} days ending {today}  \n"
        f"**Model:** {MODEL_ID}\n\n"
        "---\n\n"
    )
    md_path = out_dir / f"banxico-watcher-{today}.md"
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
    html_path = out_dir / f"banxico-watcher-{today}.html"
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
    parser = argparse.ArgumentParser(description="Banxico Watcher — standalone scrape + LLM analysis")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to write output files (default: reports/banxico-watcher/)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip LLM call and file write")
    parser.add_argument("--fetch-articles", action="store_true",
                        help="Fetch full article text for speeches (slower, uses more tokens)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports/banxico-watcher")

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Banxico Watcher — {today} (lookback {args.days}d) ===", file=sys.stderr)

    # --- Scrape ---
    speeches   = scrape_banxico_speeches(days=args.days)
    board_docs = scrape_board_documents(days=args.days)
    news       = search_news(NEWS_QUERIES, days=args.days)

    if args.fetch_articles and not args.dry_run:
        print(f"Fetching article text for up to 10 speeches ...", file=sys.stderr)
        for item in speeches[:10]:
            item["text"] = fetch_article_text(item["url"])

    total = len(speeches) + len(board_docs) + len(news)
    print(f"\n--- Scrape summary ---", file=sys.stderr)
    print(f"  Speeches:    {len(speeches)}", file=sys.stderr)
    print(f"  Board docs:  {len(board_docs)}", file=sys.stderr)
    print(f"  News items:  {len(news)}", file=sys.stderr)
    print(f"  TOTAL:       {total}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] Skipping LLM call.", file=sys.stderr)
        return

    if total == 0:
        print("No data gathered — aborting.", file=sys.stderr)
        sys.exit(1)

    # --- Build prompt ---
    context = build_context_prompt(speeches, board_docs, news, args.days, today)

    est_tokens = len(context) // 4
    print(f"\nContext prompt: ~{est_tokens:,} tokens", file=sys.stderr)
    if est_tokens > 90_000:
        print("  WARNING: prompt may exceed model context — truncating news.", file=sys.stderr)
        news = news[:20]
        context = build_context_prompt(speeches, board_docs, news, args.days, today)

    # --- LLM ---
    print("\n--- Calling Gemma 4 ---", file=sys.stderr)
    messages = [
        {"role": "system", "content": "You are a senior Mexico monetary policy analyst at a top investment bank."},
        {"role": "user",   "content": context},
    ]
    report = call_gemma(messages, hf_token, max_tokens=4096)

    # --- Save ---
    save_output(report, today, out_dir, args.days)
    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
