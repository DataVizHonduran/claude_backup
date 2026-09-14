#!/usr/bin/env python3
"""
Riksbank Watcher — Standalone Script
Mirrors rba_watcher_standalone.py for the Sveriges Riksbank Executive Board.

Data sources (zero paid APIs):
  - riksbank.se — speeches, minutes, decisions, MPR (requests + BS4)
  - Google News RSS — financial media coverage (feedparser)

LLM layer:
  - HuggingFace Inference API (google/gemma-4-31B-it)

Usage:
    HF_TOKEN=hf_xxx python3 scripts/riksbank_watcher_standalone.py
    HF_TOKEN=hf_xxx python3 scripts/riksbank_watcher_standalone.py --days 14
    HF_TOKEN=hf_xxx python3 scripts/riksbank_watcher_standalone.py --dry-run
    HF_TOKEN=hf_xxx python3 scripts/riksbank_watcher_standalone.py --fetch-articles

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/riksbank-watcher/riksbank-watcher-YYYY-MM-DD.html
    reports/riksbank-watcher/riksbank-watcher-YYYY-MM-DD.md
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
        "Mozilla/5.0 (compatible; RiksbankWatcher/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Encoding": "gzip, deflate",
}

RATE_LIMIT_SLEEP = 0.3   # seconds between Riksbank page fetches

RIKSBANK_BASE = "https://www.riksbank.se"

RIKSBANK_PAGES = {
    "speeches":  f"{RIKSBANK_BASE}/en-gb/press-and-published/speeches-and-presentations/",
    "minutes":   f"{RIKSBANK_BASE}/en-gb/monetary-policy/monetary-policy-report/minutes-of-the-executive-boards-monetary-policy-meetings/",
    "decisions": f"{RIKSBANK_BASE}/en-gb/monetary-policy/monetary-policy-report/monetary-policy-decision-documents/",
    "mpr":       f"{RIKSBANK_BASE}/en-gb/monetary-policy/monetary-policy-report/monetary-policy-reports-and-updates/",
}

NEWS_QUERIES = [
    '"Riksbank" OR "Sveriges Riksbank" interest rates inflation 2026',
    '"Erik Thedéen" OR "Erik Thedeen" speech rates 2026',
    '"Per Jansson" Riksbank 2026',
    'Riksbank "policy rate" decision CPIF 2026',
    '"CPIF" Sweden Riksbank inflation 2026',
    'Sweden "Riksbank" SEK housing rates 2026',
    '"Aino Bunge" OR "Anna Seim" OR "Göran Hjelm" Riksbank 2026',
]

# ---------------------------------------------------------------------------
# Executive Board — 5 members under Act 2022:1568
# Individual votes ARE published in Riksbank meeting minutes.
# 6 meetings per year; policy rate ~2.25% as of mid-2026.
# ---------------------------------------------------------------------------
BASELINES = {
    # --- Governor & First Deputy Governor ---
    "Erik Thedéen":  "Neutral/Data-Dependent — Governor since Jan 2023; navigated hiking cycle to 4.0% peak and subsequent cuts; emphasizes CPIF returning sustainably to 2% target; pragmatic on forward guidance",
    "Aino Bunge":    "Neutral — First Deputy Governor; took role after Anna Breman's departure to BOE; limited independent public record on rates; supports board consensus",
    # --- Deputy Governors ---
    "Per Jansson":   "Hawkish — Deputy Governor; deeply analytical, research-focused on inflation modeling and expectations; historically skeptical of premature easing; closely watches CPIF and wage data",
    "Anna Seim":     "Neutral/Dovish — Deputy Governor; macroeconomist; research focus on real economy transmission and household balance sheets; attentive to housing market stress",
    "Göran Hjelm":   "Neutral — Deputy Governor since March 2, 2026; ex-Fiscal Policy Council (ESV) and National Institute of Economic Research (NIER); labor-market and fiscal sustainability focus; limited Riksbank public record",
}

ROLES = {
    "Erik Thedéen":  "Governor",
    "Aino Bunge":    "First Deputy Governor",
    "Per Jansson":   "Deputy Governor",
    "Anna Seim":     "Deputy Governor",
    "Göran Hjelm":   "Deputy Governor",
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


def _parse_riksbank_date(text: str) -> datetime | None:
    """Parse Riksbank date strings: '21 April 2026', 'April 2026', '2026-04-21', etc."""
    text = text.strip()
    patterns = [
        ("%d %B %Y",  r"\d{1,2} \w+ \d{4}"),
        ("%B %Y",     r"\w+ \d{4}"),
        ("%Y-%m-%d",  r"\d{4}-\d{2}-\d{2}"),
        ("%d/%m/%Y",  r"\d{1,2}/\d{1,2}/\d{4}"),
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
# Layer 1: riksbank.se scraping
# ---------------------------------------------------------------------------

def _extract_speaker(title: str) -> str:
    """Match known board member names from a speech title or byline."""
    known_names = list(BASELINES.keys())
    for full_name in known_names:
        last = full_name.split()[-1]
        # Handle accent variants (Thedéen / Thedeen)
        if last in title or last.replace("é", "e") in title:
            return full_name
    return ""


def scrape_riksbank_speeches(days: int = 30) -> list[dict]:
    """
    Scrape riksbank.se/en-gb/press-and-published/speeches/ for recent publications.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print("Fetching Riksbank speeches page ...", file=sys.stderr)
    soup = _soup(RIKSBANK_PAGES["speeches"])
    if not soup:
        return []

    items = []
    seen: set[str] = set()

    for tag in soup.find_all(["li", "tr", "div", "article"]):
        text = tag.get_text(separator=" ", strip=True)
        pub_date = _parse_riksbank_date(text)
        if pub_date and pub_date < cutoff:
            continue

        for link in tag.find_all("a", href=True):
            href  = link.get("href", "")
            label = link.get_text(strip=True)
            if not label or len(label) < 10:
                continue
            href_lower  = href.lower()
            label_lower = label.lower()
            if not any(k in href_lower or k in label_lower
                       for k in ["speech", "speeches-and-presentations", "address", "remarks", "statement", "opening", "presentation"]):
                continue
            full_url = href if href.startswith("http") else RIKSBANK_BASE + href
            if full_url in seen:
                continue
            seen.add(full_url)

            speaker = _extract_speaker(text) or _extract_speaker(label)

            items.append({
                "source":  "Riksbank Speech",
                "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title":   label,
                "speaker": speaker,
                "url":     full_url,
                "text":    "",
            })

    print(f"  Found {len(items)} Riksbank speeches in last {days} days.", file=sys.stderr)
    return items


def scrape_board_documents(days: int = 30) -> list[dict]:
    """
    Scrape minutes, decisions, and MPR pages for recent links.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items  = []

    source_map = [
        ("decisions", "Policy Decision"),
        ("minutes",   "Meeting Minutes"),
    ]

    for page_key, source_label in source_map:
        url = RIKSBANK_PAGES[page_key]
        print(f"Fetching Riksbank {source_label} page ...", file=sys.stderr)
        soup = _soup(url)
        if not soup:
            continue

        seen_hrefs: set[str] = set()
        for link in soup.find_all("a", href=True):
            href  = link.get("href", "")
            label = link.get_text(strip=True)
            if not label or len(label) < 8 or href in seen_hrefs:
                continue
            href_lower = href.lower()
            if not any(k in href_lower for k in ["minutes", "decision", "monetary-policy-report", "speeches", "2025", "2026"]):
                continue
            seen_hrefs.add(href)

            pub_date = _parse_riksbank_date(label) or _parse_riksbank_date(href)
            if pub_date and pub_date < cutoff:
                continue

            full_url = href if href.startswith("http") else RIKSBANK_BASE + href
            items.append({
                "source":  source_label,
                "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title":   label,
                "speaker": "Executive Board",
                "url":     full_url,
                "text":    "",
            })
            if len(items) >= 16:
                break

        time.sleep(0.3)

    # Monetary Policy Report (quarterly) — grab top 2
    print("Fetching Riksbank MPR page ...", file=sys.stderr)
    soup_mpr = _soup(RIKSBANK_PAGES["mpr"])
    if soup_mpr:
        mpr_count = 0
        for link in soup_mpr.find_all("a", href=True)[:40]:
            href  = link.get("href", "")
            label = link.get_text(strip=True)
            if not label or len(label) < 8:
                continue
            if "monetary-policy-report" not in href.lower() and "monetary-policy" not in href.lower():
                continue
            full_url = href if href.startswith("http") else RIKSBANK_BASE + href
            items.append({
                "source":  "Monetary Policy Report",
                "date":    "",
                "title":   label,
                "speaker": "Executive Board",
                "url":     full_url,
                "text":    "",
            })
            mpr_count += 1
            if mpr_count >= 2:
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

    prompt = f"""You are a senior Swedish monetary policy analyst producing a Riksbank Watcher report.
Today: {today}
Coverage period: last {days} days

## Known Hawk/Dove Baselines (use as prior, only override with direct evidence)
{baselines_md}

---

## DATA GATHERED

### 1. Riksbank Official Speeches & Addresses ({len(speeches)} items)
{_fmt_items(speeches)}

### 2. Policy Decisions, Minutes & Monetary Policy Reports ({len(board_docs)} items)
{_fmt_items(board_docs)}

### 3. Financial News ({len(news)} items)
{_fmt_items(news, include_text=False)}

---

## REQUIRED OUTPUT

Produce the full Riksbank Watcher report in this exact structure:

### Executive Summary (≤150 words)
Brief overview of the most significant statements and board communications from the past {days} days.

### Executive Board Member Pronouncements

| Date | Official | Role | Venue/Context | Key Statement | Policy Signal | Evolution vs Baseline |
|------|----------|------|---------------|---------------|---------------|-----------------------|

### Board Official Communications

| Date | Document Type | Title | Key Takeaways | Policy Implications |
|------|---------------|-------|---------------|---------------------|

### Thematic Analysis

**1. CPIF Inflation & Price Stability Outlook**
**2. Swedish Housing Market & Household Balance Sheets**
**3. Labor Market (employment, wages, collective agreements)**
**4. SEK / REER & External Competitiveness**
**5. Neutral Rate Estimate & Real Rate Stance**
**6. Forward Guidance & Communication Style**

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

### All 5 Executive Board Members Focus

| Official | Role | Current Stance | Key Quote |
|----------|------|----------------|-----------|

### Dissent Watch
(Note: Riksbank DOES publish individual votes in minutes. Flag any dissent, split votes, or divergent speech language explicitly.)

---

Rules:
- Only cite verifiable information from the data above.
- If an official has no statements in the data, note "No public comments found".
- Policy Signal classification: Hawkish / Dovish / Neutral / Mixed
- 90-DAY RECENCY RULE: Only reference specific prior statements when they appear in the data above; otherwise use "Consistent with historical [lean] baseline".
- Key Riksbank-specific context:
  - Policy rate: 1.75% (cut from 4.0% peak; unchanged as of May 2026)
  - CPIF is the primary inflation gauge (target: 2%, fixed-rate CPI)
  - Riksbank meets 6×/year
  - Individual votes ARE published in meeting minutes
  - Executive Board has 5 members under Act 2022:1568 (reduced from 6)
  - Monetary Policy Report (MPR) published at 4 of the 6 meetings per year
  - Riksbank has FX intervention mandate (SEK management)
  - Swedish housing market sensitivity is a key domestic transmission channel
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
h1 { color: #006AA7; border-bottom: 3px solid #006AA7; padding-bottom: 10px; }
h2 { color: #006AA7; border-bottom: 2px solid #d0e8f5; padding-bottom: 6px; margin-top: 36px; }
h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
h4 { color: #555; margin-top: 20px; }
.meta { color: #777; font-size: 0.85em; margin: 6px 0 20px; }
.back-link { display: inline-block; margin-bottom: 20px; color: #006AA7; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }
th { background: #006AA7; color: white; padding: 10px 12px; text-align: left; }
td { border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }
pre code { background: none; padding: 0; }
blockquote {
    border-left: 4px solid #006AA7; margin: 16px 0; padding: 8px 16px;
    background: #d0e8f5; border-radius: 0 4px 4px 0; color: #333;
}
strong { color: #111; }
ul, ol { padding-left: 1.5em; }
li { margin: 4px 0; }
hr { border: none; border-top: 2px solid #eee; margin: 32px 0; }
a { color: #006AA7; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Riksbank Watcher — {date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">&#8592; Riksbank Watcher Archive</a>
    <h1>&#127480;&#127466; Riksbank Watcher &#8212; {date}</h1>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Coverage: last {days} days &nbsp;|&nbsp;
        Sources: riksbank.se &middot; Google News RSS &nbsp;|&nbsp;
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
    <title>Riksbank Watcher &#8212; Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #006AA7; border-bottom: 3px solid #006AA7; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #006AA7; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #006AA7; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
        .back-link {{ display: inline-block; margin-bottom: 20px; color: #006AA7; text-decoration: none; }}
        .back-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
<div class="container">
    <a href="../../index.html" class="back-link">&#8592; Back to Portfolio</a>
    <h1>&#127480;&#127466; Riksbank Watcher</h1>
    <p class="description">
        Sveriges Riksbank Executive Board speeches, decisions, and minutes &#8212; tracked every 3 days
        using <strong>riksbank.se</strong> and Google News RSS,
        analyzed by Gemma 4. All 5 Executive Board members covered.
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
    reports = sorted(out_dir.glob("riksbank-watcher-*.html"), reverse=True)
    items = []
    for i, path in enumerate(reports):
        date_str = path.stem.replace("riksbank-watcher-", "")
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">Riksbank Watcher &#8212; {date_str}{badge}</a>'
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
        f"# Riksbank Watcher — {today}\n\n"
        f"**Generated:** {generated_at} UTC  \n"
        f"**Coverage:** {days} days ending {today}  \n"
        f"**Model:** {MODEL_ID}\n\n"
        "---\n\n"
    )
    md_path = out_dir / f"riksbank-watcher-{today}.md"
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
    html_path = out_dir / f"riksbank-watcher-{today}.html"
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
    parser = argparse.ArgumentParser(description="Riksbank Watcher — standalone scrape + LLM analysis")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to write output files (default: reports/riksbank-watcher/)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip LLM call and file write")
    parser.add_argument("--fetch-articles", action="store_true",
                        help="Fetch full article text for speeches (slower, uses more tokens)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports/riksbank-watcher")

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Riksbank Watcher — {today} (lookback {args.days}d) ===", file=sys.stderr)

    # --- Scrape ---
    speeches   = scrape_riksbank_speeches(days=args.days)
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
        {"role": "system", "content": "You are a senior Swedish monetary policy analyst at a top investment bank."},
        {"role": "user",   "content": context},
    ]
    report = call_gemma(messages, hf_token, max_tokens=4096)

    # --- Save ---
    save_output(report, today, out_dir, args.days)
    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
