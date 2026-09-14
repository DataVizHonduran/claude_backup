#!/usr/bin/env python3
"""
BOJ Watcher — Standalone Script
Mirrors fed_watcher_standalone.py / ecb_watcher_standalone.py for the BOJ Policy Board.

Data sources (zero paid APIs):
  - boj.or.jp/en — speeches, MPM statements, minutes, Outlook Report (requests + BS4)
  - Google News RSS — financial media coverage (feedparser)

LLM layer:
  - HuggingFace Inference API (google/gemma-4-31B-it)

Usage:
    HF_TOKEN=hf_xxx python3 scripts/boj_watcher_standalone.py
    HF_TOKEN=hf_xxx python3 scripts/boj_watcher_standalone.py --days 14
    HF_TOKEN=hf_xxx python3 scripts/boj_watcher_standalone.py --dry-run
    HF_TOKEN=hf_xxx python3 scripts/boj_watcher_standalone.py --fetch-articles

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/boj-watcher/boj-watcher-YYYY-MM-DD.html
    reports/boj-watcher/boj-watcher-YYYY-MM-DD.md
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
        "Mozilla/5.0 (compatible; BOJWatcher/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Encoding": "gzip, deflate",
}

RATE_LIMIT_SLEEP = 0.3   # seconds between BOJ page fetches

BOJ_BASE = "https://www.boj.or.jp"

BOJ_PAGES = {
    "speeches":  f"{BOJ_BASE}/en/about/press/index.htm",       # speeches/remarks list
    "mpm":       f"{BOJ_BASE}/en/mopo/mpmdeci/index.htm",       # MPM policy statements
    "minutes":   f"{BOJ_BASE}/en/mopo/mpmsche_minu/index.htm",  # MPM minutes
    "outlook":   f"{BOJ_BASE}/en/mopo/outlook/index.htm",       # Outlook Report (quarterly)
}

NEWS_QUERIES = [
    '"Bank of Japan" OR "BOJ" interest rates inflation 2026',
    '"Kazuo Ueda" speech 2026',
    'BOJ "Policy Board" decision statement 2026',
    '"Hajime Takata" OR "Naoki Tamura" BOJ 2026',
    '"Kazuyuki Masu" OR "Toichiro Asada" BOJ 2026',
    '"Shinichi Uchida" OR "Ryozo Himino" BOJ 2026',
    'Japan CPI wages "Bank of Japan" 2026',
]

# ---------------------------------------------------------------------------
# Policy Board hawk/dove baselines — verified April 2026
# All 9 members vote at every MPM (unlike FOMC rotation)
# Expired: Toyoaki Nakamura (Jun 2025), Asahi Noguchi (Mar 2026)
# Incoming: Ayano Sato replaces Junko Nakagawa (term ends Jun 29, 2026)
# ---------------------------------------------------------------------------
BASELINES = {
    # --- Governor & Deputy Governors ---
    "Kazuo Ueda":       "Neutral/Cautionary — managing 'Middle East shock' risks; hiked Jul 2024 & Jan 2025; kept April hike on table after Mar hold",
    "Shinichi Uchida":  "Dovish/Pragmatic — architect of the 'Accommodative Hike'; emphasizes market stability",
    "Ryozo Himino":     "Neutral — focus on financial stability and market function",
    # --- External Members ---
    "Hajime Takata":    "Hawkish — serial dissenter; proposed hike to 1% at Jan and Mar 2026 MPMs (8-1 against); vigilant on wage-price spiral",
    "Naoki Tamura":     "Hawkish — wants neutral rate reached faster; consistent hawk alongside Takata",
    "Kazuyuki Masu":    "Neutral/Hawkish — replaced Nakamura (Apr 2026); Feb speech: 'further rate hikes needed to complete normalization'; Japan has shifted into inflation",
    "Toichiro Asada":   "Dovish/Reflationist — replaced Noguchi (Apr 1, 2026); occupies the dovish/reflationist seat",
    "Junko Nakagawa":   "Neutral/Lame Duck — term ending Jun 29, 2026; Ayano Sato incoming as replacement",
    "Junko Koeda":      "Neutral/Data-Dependent — focus on real interest rates; consensus-follower",
}

# Roles for the voting member table
ROLES = {
    "Kazuo Ueda":       "Governor",
    "Shinichi Uchida":  "Deputy Governor",
    "Ryozo Himino":     "Deputy Governor",
    "Hajime Takata":    "External Member",
    "Naoki Tamura":     "External Member",
    "Kazuyuki Masu":    "External Member",
    "Toichiro Asada":   "External Member",
    "Junko Nakagawa":   "External Member",
    "Junko Koeda":      "External Member",
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


def _parse_rss_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _parse_boj_date(text: str) -> datetime | None:
    """
    Parse BOJ date strings: 'April 10, 2026', '2026/4/10', '2026-04-10', etc.
    Returns UTC datetime or None.
    """
    text = text.strip()
    patterns = [
        ("%B %d, %Y", r"\w+ \d{1,2}, \d{4}"),
        ("%Y/%m/%d",  r"\d{4}/\d{1,2}/\d{1,2}"),
        ("%Y-%m-%d",  r"\d{4}-\d{2}-\d{2}"),
    ]
    for fmt, pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return datetime.strptime(m.group(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Layer 1: boj.or.jp scraping
# ---------------------------------------------------------------------------

def _extract_speaker(title: str) -> str:
    """
    BOJ speech titles follow patterns like:
      'Speech by Governor Ueda at ...'
      'Remarks by Deputy Governor Uchida ...'
      'Statement by Mr. Tamura ...'
    Extract the known Policy Board member name if present.
    """
    known_names = list(BASELINES.keys())
    # Check last name match first (most reliable)
    for full_name in known_names:
        last = full_name.split()[-1]
        if last in title:
            return full_name
    return ""


def scrape_boj_speeches(days: int = 30) -> list[dict]:
    """
    Scrape the BOJ speeches/remarks page for recent publications.
    BOJ lists speeches as <a> tags under date-grouped sections.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print("Fetching BOJ speeches page ...", file=sys.stderr)
    soup = _soup(BOJ_PAGES["speeches"])
    if not soup:
        return []

    items = []
    # BOJ pages list entries as rows with date + link
    # Look for table rows or list items with date + link patterns
    for tag in soup.find_all(["tr", "li", "dt", "div"]):
        text = tag.get_text(separator=" ", strip=True)
        # Extract date
        pub_date = _parse_boj_date(text)
        if pub_date and pub_date < cutoff:
            continue

        for link in tag.find_all("a", href=True):
            href  = link.get("href", "")
            label = link.get_text(strip=True)
            if not label or len(label) < 10:
                continue
            # Only speeches/remarks/statements
            lower = label.lower()
            if not any(k in lower for k in ["speech", "remark", "statement", "address", "lecture", "interview"]):
                continue
            full_url = href if href.startswith("http") else BOJ_BASE + href
            speaker  = _extract_speaker(label)

            items.append({
                "source":  "BOJ Speech/Remarks",
                "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title":   label,
                "speaker": speaker,
                "url":     full_url,
                "text":    "",
            })

    # Deduplicate by URL
    seen: set[str] = set()
    deduped = []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            deduped.append(it)

    print(f"  Found {len(deduped)} BOJ speeches in last {days} days.", file=sys.stderr)
    return deduped


def scrape_mpm_documents(days: int = 30) -> list[dict]:
    """
    Scrape MPM policy statements and minutes pages.
    Returns recent links from both pages combined.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items  = []

    for source_key, source_label in [("mpm", "MPM Statement"), ("minutes", "MPM Minutes")]:
        url = BOJ_PAGES[source_key]
        print(f"Fetching BOJ {source_label} page ...", file=sys.stderr)
        soup = _soup(url)
        if not soup:
            continue

        seen_hrefs: set[str] = set()
        for link in soup.find_all("a", href=True):
            href  = link.get("href", "")
            label = link.get_text(strip=True)
            if not label or len(label) < 8 or href in seen_hrefs:
                continue
            # Filter to relevant document links
            href_lower = href.lower()
            if not any(k in href_lower for k in ["mpmdeci", "mpmsche", "minu", "new", "2025", "2026"]):
                continue
            seen_hrefs.add(href)

            # Try to extract date from label or href
            pub_date = _parse_boj_date(label) or _parse_boj_date(href)
            if pub_date and pub_date < cutoff:
                continue

            full_url = href if href.startswith("http") else BOJ_BASE + href
            items.append({
                "source":  source_label,
                "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title":   label,
                "speaker": "Policy Board",
                "url":     full_url,
                "text":    "",
            })
            if len(items) >= 12:
                break

        time.sleep(0.3)

    # Outlook Report (quarterly — grab top 2 links)
    print("Fetching BOJ Outlook Report page ...", file=sys.stderr)
    soup2 = _soup(BOJ_PAGES["outlook"])
    if soup2:
        for link in soup2.find_all("a", href=True)[:30]:
            href  = link.get("href", "")
            label = link.get_text(strip=True)
            if not label or len(label) < 8:
                continue
            if "outlook" not in href.lower() and "prexp" not in href.lower():
                continue
            full_url = href if href.startswith("http") else BOJ_BASE + href
            items.append({
                "source":  "Outlook Report",
                "date":    "",
                "title":   label,
                "speaker": "Policy Board",
                "url":     full_url,
                "text":    "",
            })
            if sum(1 for i in items if i["source"] == "Outlook Report") >= 2:
                break

    print(f"  Found {len(items)} MPM/Outlook documents.", file=sys.stderr)
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
    mpm_docs: list[dict],
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

    baselines_md = "\n".join(f"- {k} ({ROLES.get(k, 'Member')}): {v}" for k, v in BASELINES.items())

    prompt = f"""You are a Japan monetary policy analyst producing a BOJ Watcher report.
Today: {today}
Coverage period: last {days} days

## Known Hawk/Dove Baselines (use as prior, only override with direct evidence)
{baselines_md}

---

## DATA GATHERED

### 1. BOJ Official Speeches & Remarks ({len(speeches)} items)
{_fmt_items(speeches)}

### 2. MPM Statements, Minutes & Outlook Reports ({len(mpm_docs)} items)
{_fmt_items(mpm_docs)}

### 3. Financial News ({len(news)} items)
{_fmt_items(news, include_text=False)}

---

## REQUIRED OUTPUT

Produce the full BOJ Watcher report in this exact structure:

### Executive Summary (≤150 words)
Brief overview of the most significant statements and MPM updates from the past {days} days.

### Policy Board Member Pronouncements

| Date | Official | Role | Venue/Context | Key Statement | Policy Signal | Evolution vs Baseline |
|------|----------|------|---------------|---------------|---------------|-----------------------|

### MPM Official Communications

| Date | Document Type | Title | Key Takeaways | Policy Implications |
|------|---------------|-------|---------------|---------------------|

### Thematic Analysis

**1. Inflation Assessment (CPI, Core, Wages)**
**2. Growth Outlook**
**3. Yen / FX Considerations**
**4. Financial Conditions & JGB Market**
**5. Balance Sheet (JGB purchase taper)**
**6. Forward Guidance Evolution**

### Hawk-Dove Spectrum Analysis

```
HAWKISH (favor faster normalization / rate hikes)
├─ [Names and recent positioning]

NEUTRAL/DATA-DEPENDENT
├─ [Names and recent positioning]

DOVISH (favor maintaining accommodation / slower hikes)
└─ [Names and recent positioning]
```

**Key Shifts Identified:**

### All 9 Voting Members Focus

| Official | Role | Current Stance | Key Quote |
|----------|------|----------------|-----------|

### Dissent Watch
(any dissents or verbal signals of dissent — note BOJ publishes individual member votes in minutes)

---

Rules:
- Only cite verifiable information from the data above.
- If an official has no statements in the data, note "No public comments found".
- Policy Signal classification: Hawkish / Dovish / Neutral / Mixed
- 90-DAY RECENCY RULE: Only reference specific prior statements when they appear in the data above; otherwise use "Consistent with historical [lean] baseline".
- All 9 Policy Board members vote at every MPM — note voting records when available in minutes.
- Key BOJ-specific context: BOJ began rate normalization in 2024 after 17 years of NIRP/YCC; current policy rate 0.75% (held Mar 2026, 8-1 with Takata dissenting for 1%); JGB purchase tapering ongoing.
- Board rotation note: Toyoaki Nakamura (term ended Jun 2025) and Asahi Noguchi (term ended Mar 31, 2026) have departed. Toichiro Asada joined Apr 1, 2026 (dovish/reflationist). Junko Nakagawa's term ends Jun 29, 2026 — Ayano Sato is the incoming replacement.
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
            is_rate_limit = any(x in str(e) for x in ("429", "503", "504", "Too Many Requests", "Service Temporarily Unavailable", "Gateway Time-out"))
            if is_rate_limit and attempt < 4:
                wait = 30 * (attempt + 1)
                print(f"\n  HF transient error — waiting {wait}s (attempt {attempt+1}/5) ...", file=sys.stderr)
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
h1 { color: #bf0000; border-bottom: 3px solid #bf0000; padding-bottom: 10px; }
h2 { color: #bf0000; border-bottom: 2px solid #fce4e4; padding-bottom: 6px; margin-top: 36px; }
h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
h4 { color: #555; margin-top: 20px; }
.meta { color: #777; font-size: 0.85em; margin: 6px 0 20px; }
.back-link { display: inline-block; margin-bottom: 20px; color: #bf0000; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }
th { background: #bf0000; color: white; padding: 10px 12px; text-align: left; }
td { border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }
pre code { background: none; padding: 0; }
blockquote {
    border-left: 4px solid #bf0000; margin: 16px 0; padding: 8px 16px;
    background: #fce4e4; border-radius: 0 4px 4px 0; color: #333;
}
strong { color: #111; }
ul, ol { padding-left: 1.5em; }
li { margin: 4px 0; }
hr { border: none; border-top: 2px solid #eee; margin: 32px 0; }
a { color: #bf0000; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BOJ Watcher — {date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">&#8592; BOJ Watcher Archive</a>
    <h1>&#127471;&#127477; BOJ Watcher &#8212; {date}</h1>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Coverage: last {days} days &nbsp;|&nbsp;
        Sources: boj.or.jp &middot; Google News RSS &nbsp;|&nbsp;
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
    <title>BOJ Watcher &#8212; Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #bf0000; border-bottom: 3px solid #bf0000; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #bf0000; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #bf0000; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
        .back-link {{ display: inline-block; margin-bottom: 20px; color: #bf0000; text-decoration: none; }}
        .back-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
<div class="container">
    <a href="../../index.html" class="back-link">&#8592; Back to Portfolio</a>
    <h1>&#127471;&#127477; BOJ Watcher</h1>
    <p class="description">
        Bank of Japan Policy Board speeches, statements, and policy communications &#8212; tracked every 3 days
        using <strong>boj.or.jp</strong> and Google News RSS,
        analyzed by Gemma 4. All 9 Policy Board members covered.
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
    reports = sorted(out_dir.glob("boj-watcher-*.html"), reverse=True)
    items = []
    for i, path in enumerate(reports):
        date_str = path.stem.replace("boj-watcher-", "")
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">BOJ Watcher &#8212; {date_str}{badge}</a>'
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
        f"# BOJ Watcher — {today}\n\n"
        f"**Generated:** {generated_at} UTC  \n"
        f"**Coverage:** {days} days ending {today}  \n"
        f"**Model:** {MODEL_ID}\n\n"
        "---\n\n"
    )
    md_path = out_dir / f"boj-watcher-{today}.md"
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
    html_path = out_dir / f"boj-watcher-{today}.html"
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
    parser = argparse.ArgumentParser(description="BOJ Watcher — standalone scrape + LLM analysis")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to write output files (default: reports/boj-watcher/)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip LLM call and file write")
    parser.add_argument("--fetch-articles", action="store_true",
                        help="Fetch full article text for speeches (slower, uses more tokens)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports/boj-watcher")

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== BOJ Watcher — {today} (lookback {args.days}d) ===", file=sys.stderr)

    # --- Scrape ---
    speeches = scrape_boj_speeches(days=args.days)
    mpm_docs = scrape_mpm_documents(days=args.days)
    news     = search_news(NEWS_QUERIES, days=args.days)

    if args.fetch_articles and not args.dry_run:
        print(f"Fetching article text for up to 10 speeches ...", file=sys.stderr)
        for item in speeches[:10]:
            item["text"] = fetch_article_text(item["url"])

    total = len(speeches) + len(mpm_docs) + len(news)
    print(f"\n--- Scrape summary ---", file=sys.stderr)
    print(f"  Speeches/Remarks: {len(speeches)}", file=sys.stderr)
    print(f"  MPM docs:         {len(mpm_docs)}", file=sys.stderr)
    print(f"  News items:       {len(news)}", file=sys.stderr)
    print(f"  TOTAL:            {total}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] Skipping LLM call.", file=sys.stderr)
        return

    if total == 0:
        print("No data gathered — aborting.", file=sys.stderr)
        sys.exit(1)

    # --- Build prompt ---
    context = build_context_prompt(speeches, mpm_docs, news, args.days, today)

    # Rough token estimate
    est_tokens = len(context) // 4
    print(f"\nContext prompt: ~{est_tokens:,} tokens", file=sys.stderr)
    if est_tokens > 90_000:
        print("  WARNING: prompt may exceed model context — truncating news.", file=sys.stderr)
        news = news[:20]
        context = build_context_prompt(speeches, mpm_docs, news, args.days, today)

    # --- LLM ---
    print("\n--- Calling Gemma 4 ---", file=sys.stderr)
    messages = [
        {"role": "system", "content": "You are a senior Japan monetary policy analyst at a top investment bank."},
        {"role": "user",   "content": context},
    ]
    report = call_gemma(messages, hf_token, max_tokens=4096)

    # --- Save ---
    save_output(report, today, out_dir, args.days)
    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
