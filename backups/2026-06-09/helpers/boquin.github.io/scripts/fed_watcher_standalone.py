#!/usr/bin/env python3
"""
Fed Watcher — Standalone Script
Replicates the /us-fed-watcher Claude skill as a pure-Python script.

Data sources (zero paid APIs):
  - federalreserve.gov  — speeches, testimony, FOMC calendars, Beige Book (requests + BS4)
  - Google News RSS     — financial media coverage (feedparser)
  - Regional Fed RSS    — supplemental district publications (feedparser)

LLM layer:
  - HuggingFace Inference API (google/gemma-4-31B-it)

Usage:
    HF_TOKEN=hf_xxx python3 fed_watcher_standalone.py
    HF_TOKEN=hf_xxx python3 fed_watcher_standalone.py --days 14
    HF_TOKEN=hf_xxx python3 fed_watcher_standalone.py --dry-run

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    ~/.claude/cache/us/fed-watcher/us_fed_watch_YYYY-MM-DD.md
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
        "Mozilla/5.0 (compatible; FedWatcher/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Encoding": "gzip, deflate",
}

RATE_LIMIT_SLEEP = 0.2   # seconds between Fed page fetches

FED_BASE = "https://www.federalreserve.gov"

FED_PAGES = {
    "speeches_rss": f"{FED_BASE}/feeds/speeches_and_testimony.xml",  # covers speeches + testimony
    "fomc":         f"{FED_BASE}/monetarypolicy/fomccalendars.htm",
    "beige_book":   f"{FED_BASE}/monetarypolicy/beige-book-default.htm",
}

NEWS_QUERIES = [
    '"Federal Reserve" OR "FOMC" interest rates inflation 2026',
    '"Jerome Powell" speech 2026',
    '"Fed governor" OR "Fed president" interview 2026 rates',
    '"FOMC minutes" OR "FOMC statement" 2026',
    '"Michelle Bowman" OR "Christopher Waller" OR "Adriana Kugler" Fed 2026',
    '"Neel Kashkari" OR "Lorie Logan" OR "Beth Hammack" Fed 2026',
]

REGIONAL_RSS = [
    {"district": "NY",  "url": "https://libertystreeteconomics.newyorkfed.org/feed/"},
    {"district": "ATL", "url": "https://www.atlantafed.org/rss/macroblog"},
    {"district": "SF",  "url": "https://www.frbsf.org/research-and-insights/publications/economic-letter/feed/"},
    {"district": "RIC", "url": "https://www.richmondfed.org/research/economic_brief/rss.xml"},
]

# Hawk/dove baseline — copied from us-fed-watcher.md
BASELINES = {
    "Jerome Powell":       "Neutral — consensus-builder; aligns with committee median",
    "Philip Jefferson":    "Neutral/Dovish — emphasizes labor market risks",
    "Michael Barr":        "Neutral/Hawkish — emphasizes inflation persistence",
    "Michelle Bowman":     "Neutral/Hawkish — dissented for smaller cuts in 2024",
    "Christopher Waller":  "Neutral/Dovish — reads tariff inflation as transitory",
    "Lisa Cook":           "Neutral/Dovish — emphasizes labor market risks",
    "Adriana Kugler":      "Neutral/Dovish",
    "Stephen Miran":       "Dovish — serial dissenter; advocates 100bp+ in cuts",
    "John Williams":       "Neutral — data-dependent; aligns closely with Chair",
    "Neel Kashkari":       "Neutral/Hawkish — concerned about premature easing",
    "Lorie Logan":         "Neutral/Hawkish — focus on balance sheet normalization",
    "Beth Hammack":        "Neutral — data-dependent; limited public record",
    "Anna Paulson":        "Neutral — data-dependent; limited public record",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> requests.Response | None:
    """GET with retry on 5xx / timeout, rate-limited."""
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


# ---------------------------------------------------------------------------
# Layer 1: federalreserve.gov scraping
# ---------------------------------------------------------------------------

def scrape_fed_speeches(days: int = 30) -> list[dict]:
    """
    Fetch official Fed speeches and testimony via the combined RSS feed.
    URL: https://www.federalreserve.gov/feeds/speeches_and_testimony.xml
    Returns entries published within the last `days` days.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print("Fetching Fed speeches/testimony RSS ...", file=sys.stderr)
    feed = feedparser.parse(FED_PAGES["speeches_rss"])

    items = []
    for entry in feed.entries:
        pub_date = _parse_rss_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        title = getattr(entry, "title", "")
        # Feed title format: "LastName, Speech Title" — split on first comma
        speaker = ""
        if "," in title:
            speaker_part, _ = title.split(",", 1)
            speaker = speaker_part.strip()

        href = getattr(entry, "link", "")
        full_url = href if href.startswith("http") else FED_BASE + href

        items.append({
            "source": "Fed Speeches/Testimony",
            "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title": title,
            "speaker": speaker,
            "url": full_url,
            "text": "",
        })

    print(f"  Found {len(items)} speeches/testimony in last {days} days.", file=sys.stderr)
    return items


def _parse_fomc_meeting_date(year: int, month_str: str, day_range: str) -> datetime | None:
    """
    Convert FOMC calendar month + day range to a datetime.
    month_str: 'January', 'March/April', etc.
    day_range: '27-28', '18-19', '6-7*', etc.
    Returns the last day of the meeting (i.e., decision date).
    """
    # Use first month if it's a cross-month meeting (e.g. 'March/April')
    month_name = month_str.split("/")[0].strip()
    # Extract last day number from range (decision day)
    day_match = re.findall(r"\d+", day_range)
    if not day_match:
        return None
    day = int(day_match[-1])
    try:
        return datetime.strptime(f"{month_name} {day} {year}", "%B %d %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def scrape_fomc_documents(days: int = 30) -> list[dict]:
    """
    Scrape FOMC calendars page for recent statements, minutes, SEP, and press conferences.
    Structure: div.row.fomc-meeting rows under year-section h5 headers.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    today_year = datetime.now(timezone.utc).year
    print("Fetching FOMC calendars page ...", file=sys.stderr)
    soup = _soup(FED_PAGES["fomc"])
    if not soup:
        return []

    items = []

    # Page structure: div.panel.panel-default, each containing:
    #   div.panel-heading > h4 > a  (year label, e.g. "2026 FOMC Meetings")
    #   div.row.fomc-meeting        (one per meeting)
    for panel in soup.select("div.panel.panel-default"):
        heading_el = panel.select_one("div.panel-heading h4 a, div.panel-heading h4")
        if not heading_el:
            continue
        m = re.search(r"(\d{4})", heading_el.get_text())
        if not m:
            continue
        panel_year = int(m.group(1))

        for row in panel.select("div.row"):
            cls = " ".join(row.get("class", []))
            if "fomc-meeting" not in cls:
                continue

            month_el = row.select_one("div.fomc-meeting__month")
            date_el  = row.select_one("div.fomc-meeting__date")
            if not month_el or not date_el:
                continue

            month_str = month_el.get_text(strip=True)
            day_str   = date_el.get_text(strip=True)
            meeting_date = _parse_fomc_meeting_date(panel_year, month_str, day_str)

            # Only include recent meetings
            if meeting_date and meeting_date < cutoff:
                continue

            date_label = (
                meeting_date.strftime("%Y-%m-%d") if meeting_date
                else f"{month_str} {day_str} {panel_year}"
            )

            for link in row.select("a[href]"):
                href   = link.get("href", "")
                label  = link.get_text(strip=True)
                if not label or label in ("PDF", "HTML"):
                    parent_text = link.parent.get_text(separator=" ", strip=True)
                    label = parent_text[:80]
                href_lower = href.lower()
                if not any(k in href_lower for k in ["monetary", "fomcpress", "minutes", "sep", "projection"]):
                    continue
                full_url = href if href.startswith("http") else FED_BASE + href
                items.append({
                    "source": "FOMC Document",
                    "date": date_label,
                    "title": label,
                    "speaker": "FOMC",
                    "url": full_url,
                    "text": "",
                })

    # Beige Book — grab the 2 most recent links
    print("Fetching Beige Book page ...", file=sys.stderr)
    soup2 = _soup(FED_PAGES["beige_book"])
    if soup2:
        for link in soup2.select("a[href*='beige'], a[href*='Beige']")[:2]:
            href = link.get("href", "")
            full_url = href if href.startswith("http") else FED_BASE + href
            items.append({
                "source": "Beige Book",
                "date": "",
                "title": link.get_text(strip=True),
                "speaker": "FOMC",
                "url": full_url,
                "text": "",
            })

    print(f"  Found {len(items)} FOMC documents.", file=sys.stderr)
    return items


def fetch_article_text(url: str, max_chars: int = 3000) -> str:
    """Best-effort extraction of article body text from a URL."""
    if not url or "pdf" in url.lower():
        return ""
    resp = _get(url, timeout=30)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    # Remove nav/footer/scripts
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    # Try article body selectors first
    body = (
        soup.select_one("article, .speech-content, .content-body, main, #content")
        or soup.body
    )
    if not body:
        return ""
    text = re.sub(r"\s{3,}", "\n\n", body.get_text(separator=" ", strip=True))
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Layer 2: Google News RSS
# ---------------------------------------------------------------------------

def _parse_rss_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def search_google_news(query: str, max_results: int = 10) -> list[dict]:
    """Search Google News RSS — free, no API key."""
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_results]:
        pub_date = _parse_rss_date(entry)
        items.append({
            "source": "Google News RSS",
            "query": query,
            "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title": getattr(entry, "title", ""),
            "url": getattr(entry, "link", ""),
            "summary": _strip_html(getattr(entry, "summary", "")),
        })
    return items


def search_news(queries: list[str], days: int = 30) -> list[dict]:
    """Run all queries and deduplicate by URL."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen_urls: set[str] = set()
    results = []

    for q in queries:
        print(f"  News search: {q[:60]} ...", file=sys.stderr)
        for item in search_google_news(q):
            if item["url"] in seen_urls:
                continue
            # Filter by date if parseable
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


def fetch_regional_rss(days: int = 30) -> list[dict]:
    """Fetch regional Fed RSS feeds for supplemental context."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items = []
    for source in REGIONAL_RSS:
        print(f"  Regional RSS ({source['district']}): {source['url']}", file=sys.stderr)
        feed = feedparser.parse(source["url"])
        for entry in feed.entries:
            pub_date = _parse_rss_date(entry)
            if pub_date and pub_date < cutoff:
                continue
            items.append({
                "source": f"Regional Fed — {source['district']}",
                "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title": getattr(entry, "title", ""),
                "url": getattr(entry, "link", ""),
                "summary": _strip_html(getattr(entry, "summary", ""))[:500],
            })
        time.sleep(0.3)
    print(f"  Regional RSS items: {len(items)}", file=sys.stderr)
    return items


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_context_prompt(
    speeches: list[dict],
    fomc_docs: list[dict],
    news: list[dict],
    regional: list[dict],
    days: int,
    today: str,
) -> str:
    """Assemble all gathered data into a context block for Gemma."""

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

    prompt = f"""You are a US monetary policy analyst producing a Fed Watcher report.
Today: {today}
Coverage period: last {days} days

## Known Hawk/Dove Baselines (use as prior, only override with direct evidence)
{baselines_md}

---

## DATA GATHERED

### 1. Fed Official Speeches & Testimony ({len(speeches)} items)
{_fmt_items(speeches)}

### 2. FOMC Documents ({len(fomc_docs)} items)
{_fmt_items(fomc_docs)}

### 3. Financial News ({len(news)} items)
{_fmt_items(news, include_text=False)}

### 4. Regional Fed Research ({len(regional)} items)
{_fmt_items(regional, include_text=False)}

---

## REQUIRED OUTPUT

Produce the full Fed Watcher report in this exact structure:

### Executive Summary (≤150 words)
Brief overview of the most significant statements and FOMC updates from the past {days} days.

### FOMC Member Pronouncements

| Date | Official | Role | Venue/Context | Key Statement | Policy Signal | Evolution vs Previous |
|------|----------|------|---------------|---------------|---------------|-----------------------|

### Federal Reserve Official Communications

| Date | Document Type | Title | Key Takeaways | Policy Implications |
|------|---------------|-------|---------------|---------------------|

### Thematic Analysis

**1. Inflation Assessment**
**2. Labor Market Views**
**3. Growth Outlook**
**4. Financial Conditions**
**5. Balance Sheet Policy (QT)**
**6. Forward Guidance Evolution**

### Hawk-Dove Spectrum Analysis

```
HAWKISH (favor higher rates / extended pause)
├─ [Names and recent positioning]

NEUTRAL/DATA-DEPENDENT
├─ [Names and recent positioning]

DOVISH (favor rate cuts)
└─ [Names and recent positioning]
```

**Key Shifts Identified:**

### Voting Member Focus

| Official | Voting Status | Current Stance | Key Quote |
|----------|---------------|----------------|-----------|

### Dissent Watch
(any dissents or verbal signals of dissent)

---

Rules:
- Only cite verifiable information from the data above.
- If an official has no statements in the data, note "No public comments found".
- Policy Signal classification: Hawkish / Dovish / Neutral / Mixed
- 90-DAY RECENCY RULE: Only reference specific prior statements when they appear in the data above; otherwise use "Consistent with historical [lean] baseline".
"""
    return prompt


# ---------------------------------------------------------------------------
# LLM call (mirrors fed_district_ai_processor.py)
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


HTML_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 1000px; margin: 0 auto; padding: 20px;
    line-height: 1.6; background: #f5f5f5; color: #333;
}
.container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
h1 { color: #1565c0; border-bottom: 3px solid #1565c0; padding-bottom: 10px; }
h2 { color: #1565c0; border-bottom: 2px solid #e3f2fd; padding-bottom: 6px; margin-top: 36px; }
h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
h4 { color: #555; margin-top: 20px; }
.meta { color: #777; font-size: 0.85em; margin: 6px 0 20px; }
.back-link { display: inline-block; margin-bottom: 20px; color: #1565c0; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }
th { background: #1565c0; color: white; padding: 10px 12px; text-align: left; }
td { border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }
pre code { background: none; padding: 0; }
blockquote {
    border-left: 4px solid #1565c0; margin: 16px 0; padding: 8px 16px;
    background: #e3f2fd; border-radius: 0 4px 4px 0; color: #333;
}
strong { color: #111; }
ul, ol { padding-left: 1.5em; }
li { margin: 4px 0; }
hr { border: none; border-top: 2px solid #eee; margin: 32px 0; }
a { color: #1565c0; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>US Fed Watcher — {date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">← Fed Watcher Archive</a>
    <h1>🦅 US Fed Watcher — {date}</h1>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Coverage: last {days} days &nbsp;|&nbsp;
        Sources: federalreserve.gov · Google News RSS · Regional Fed RSS &nbsp;|&nbsp;
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
    <title>US Fed Watcher — Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #1565c0; border-bottom: 3px solid #1565c0; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #1565c0; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #1565c0; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>🦅 US Fed Watcher</h1>
    <p class="description">
        FOMC member speeches, testimonies, and policy communications — tracked every 3 days
        using <strong>federalreserve.gov</strong>, Google News RSS, and regional Fed feeds,
        analyzed by Gemma 4.
    </p>
    <ul class="report-list">
        {items}
    </ul>
</div>
</body>
</html>"""


def _markdown_to_html(md_text: str) -> str:
    """Convert markdown to HTML with table support."""
    return md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )


def regenerate_index(out_dir: Path) -> None:
    """Rebuild index.html from all report HTML files in out_dir."""
    reports = sorted(out_dir.glob("fed-watcher-*.html"), reverse=True)
    items = []
    for i, path in enumerate(reports):
        date_str = path.stem.replace("fed-watcher-", "")
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">Fed Watcher — {date_str}{badge}</a>'
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

    # Markdown file
    md_header = (
        f"# US Fed Watcher — {today}\n\n"
        f"**Generated:** {generated_at} UTC  \n"
        f"**Coverage:** {days} days ending {today}  \n"
        f"**Model:** {MODEL_ID}\n\n"
        "---\n\n"
    )
    md_path = out_dir / f"fed-watcher-{today}.md"
    md_path.write_text(md_header + report, encoding="utf-8")

    # HTML file
    body_html = _markdown_to_html(report)
    html_content = HTML_TEMPLATE.format(
        date=today,
        generated_at=generated_at,
        days=days,
        model=MODEL_ID,
        css=HTML_CSS,
        body=body_html,
    )
    html_path = out_dir / f"fed-watcher-{today}.html"
    html_path.write_text(html_content, encoding="utf-8")

    # Rebuild archive index
    regenerate_index(out_dir)
    regenerate_cb_monitor(out_dir.parent.parent)

    print(f"\nMarkdown : {md_path}", file=sys.stderr)
    print(f"HTML     : {html_path}", file=sys.stderr)
    print(f"Index    : {out_dir / 'index.html'}", file=sys.stderr)

    # Update local metadata.json (skip in CI / no home .claude dir)
    meta_path = Path.home() / ".claude" / "cache" / "us" / "metadata.json"
    if meta_path.parent.exists():
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                pass
        meta.setdefault("fed-watcher", {})
        meta["fed-watcher"]["last_run"] = today
        meta["fed-watcher"]["output_path"] = str(html_path)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return html_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fed Watcher — standalone scrape + LLM analysis")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to write output files (default: ~/.claude/cache/us/fed-watcher/)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip LLM call and file write")
    parser.add_argument("--fetch-articles", action="store_true",
                        help="Fetch full article text for speeches (slower, uses more tokens)")
    args = parser.parse_args()

    default_out_dir = Path.home() / ".claude" / "cache" / "us" / "fed-watcher"
    out_dir = Path(args.output_dir) if args.output_dir else default_out_dir

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Fed Watcher — {today} (lookback {args.days}d) ===", file=sys.stderr)

    # --- Scrape ---
    speeches  = scrape_fed_speeches(days=args.days)
    fomc_docs = scrape_fomc_documents(days=args.days)
    news      = search_news(NEWS_QUERIES, days=args.days)
    regional  = fetch_regional_rss(days=args.days)

    # Optionally fetch article bodies for speeches
    if args.fetch_articles and not args.dry_run:
        print(f"Fetching article text for {len(speeches)} speeches ...", file=sys.stderr)
        for item in speeches[:10]:  # cap at 10 to stay within token budget
            item["text"] = fetch_article_text(item["url"])

    total = len(speeches) + len(fomc_docs) + len(news) + len(regional)
    print(f"\n--- Scrape summary ---", file=sys.stderr)
    print(f"  Speeches/Testimony: {len(speeches)}", file=sys.stderr)
    print(f"  FOMC docs:          {len(fomc_docs)}", file=sys.stderr)
    print(f"  News items:         {len(news)}", file=sys.stderr)
    print(f"  Regional RSS:       {len(regional)}", file=sys.stderr)
    print(f"  TOTAL:              {total}", file=sys.stderr)

    if args.dry_run:
        print("\n--dry-run: skipping LLM call and file write.", file=sys.stderr)
        return

    # --- Build prompt ---
    context_prompt = build_context_prompt(
        speeches, fomc_docs, news, regional,
        days=args.days, today=today,
    )

    # Rough token estimate (4 chars ≈ 1 token)
    est_tokens = len(context_prompt) // 4
    print(f"\nContext prompt: ~{est_tokens:,} tokens", file=sys.stderr)
    if est_tokens > 90_000:
        print("  WARNING: prompt may exceed model context — truncating news/regional.", file=sys.stderr)
        news = news[:20]
        regional = regional[:15]
        context_prompt = build_context_prompt(
            speeches, fomc_docs, news, regional,
            days=args.days, today=today,
        )

    # --- LLM ---
    print("\n--- Calling Gemma 4 ---", file=sys.stderr)
    messages = [{"role": "user", "content": context_prompt}]
    report = call_gemma(messages, hf_token=hf_token, max_tokens=5000)

    # --- Save ---
    out_path = save_output(report, today, out_dir=out_dir, days=args.days)
    print(f"\nDone. Output: {out_path}")


if __name__ == "__main__":
    main()
