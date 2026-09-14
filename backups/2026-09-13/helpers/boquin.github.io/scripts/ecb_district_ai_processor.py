"""
ECB & Eurozone Central Bank Monitor — AI Processor.

Two operating modes:

1. --input mode (used by /ecb-monitor skill):
   Reads raw article data pre-fetched by Claude, enriches with Gemma 4,
   writes HTML + MD reports.

2. --scrape mode (used by GitHub Actions daily cron):
   Fetches articles directly (RSS via feedparser for ECB and Bundesbank,
   Playwright for JS-rendered NCB sites),
   then enriches and writes reports.

Usage:
    # Skill mode
    HF_TOKEN=xxx python3 scripts/ecb_district_ai_processor.py \\
        --input /tmp/ecb_raw_articles.json \\
        --output-dir reports/ecb-monitor/ \\
        --cache ~/.claude/cache/ecb-district-monitor.json \\
        --date 2026-04-12

    # GitHub Actions mode
    HF_TOKEN=xxx python3 scripts/ecb_district_ai_processor.py \\
        --scrape \\
        --days 3 \\
        --output-dir reports/ecb-monitor/ \\
        --cache reports/ecb-monitor/cache.json \\
        --date 2026-04-12

Required environment variables:
    HF_TOKEN  — HuggingFace API token

GitHub Actions secrets required:
    HF_TOKEN
"""

import os
import sys
import json
import time
import argparse
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from huggingface_hub import InferenceClient
from cb_monitor_utils import regenerate_cb_monitor

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID   = "google/gemma-4-31B-it"
BATCH_SIZE = 8   # articles per Gemma4 tagging call

TAG_VOCAB = [
    "monetary policy", "inflation", "interest rates", "labor markets",
    "employment", "wages", "financial stability", "banking", "credit",
    "housing", "real estate", "GDP growth", "recession", "consumer spending",
    "fiscal policy", "sovereign debt", "trade", "exchange rates",
    "eurozone", "banking union", "digital euro", "climate & transition",
    "green finance", "payments", "TARGET2", "demographics",
    "productivity", "supply chains", "geopolitics",
]

INSTITUTION_ORDER = ["ECB", "DBB", "BDF", "BDI", "BDE", "DNB", "CBI"]

INSTITUTION_META = {
    "ECB": {"name": "European Central Bank",         "type": "Working Papers, Research Bulletin & Blog"},
    "DBB": {"name": "Deutsche Bundesbank",            "type": "Discussion Papers"},
    "BDF": {"name": "Banque de France",               "type": "Working Papers"},
    "BDI": {"name": "Banca d'Italia",                 "type": "Occasional Papers (QEF)"},
    "BDE": {"name": "Banco de España",                "type": "Working Papers"},
    "DNB": {"name": "De Nederlandsche Bank",          "type": "Working Papers"},
    "CBI": {"name": "Central Bank of Ireland",        "type": "Research Technical Papers"},
}

# ---------------------------------------------------------------------------
# Scrape config  (used only in --scrape mode)
# ---------------------------------------------------------------------------

SCRAPE_SOURCES = [
    # ECB — three RSS feeds
    {"institution": "ECB", "type": "rss",
     "url": "https://www.ecb.europa.eu/rss/wppub.html"},
    {"institution": "ECB", "type": "rss",
     "url": "https://www.ecb.europa.eu/rss/rbu.html"},
    {"institution": "ECB", "type": "rss",
     "url": "https://www.ecb.europa.eu/rss/blog.html"},
    # Bundesbank — Discussion Papers RSS
    {"institution": "DBB", "type": "rss",
     "url": "https://www.bundesbank.de/service/rss/en/633292/feed.rss"},
    # Banque de France — Working Papers (playwright, JS-rendered)
    {"institution": "BDF", "type": "playwright",
     "url": "https://www.banque-france.fr/en/publications-and-research/our-main-publications/working-papers"},
    # Banca d'Italia — QEF (playwright)
    {"institution": "BDI", "type": "playwright",
     "url": "https://www.bancaditalia.it/pubblicazioni/qef/"},
    # Banco de España — Working Papers (playwright)
    {"institution": "BDE", "type": "playwright",
     "url": "https://www.bde.es/wbe/en/publicaciones/estudios-e-informes/documentos-trabajo/"},
    # DNB — Working Papers (playwright)
    {"institution": "DNB", "type": "playwright",
     "url": "https://www.dnb.nl/en/research/dnb-working-papers/"},
    # CBI — Research Technical Papers (static HTML)
    {"institution": "CBI", "type": "html",
     "url": "https://www.centralbank.ie/publication/research-publications/research-technical-papers"},
]

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ECBMonitor/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    )
}

TAGGING_SYSTEM_PROMPT = (
    "You are a European Central Bank research analyst. For each article in the list provided, "
    "return a JSON array where each element corresponds to one article (in the same order) "
    "and has exactly two keys:\n"
    '- "summary": 2-3 sentences in a concise, analytical tone describing what the paper argues or finds.\n'
    f'- "tags": an array of 5 to 8 lowercase topic tags chosen ONLY from this controlled vocabulary: {json.dumps(TAG_VOCAB)}.\n\n'
    "Return ONLY the JSON array. No prose, no markdown fences, no explanation."
)

INSIGHTS_SYSTEM_PROMPT = (
    "You are a senior economist at a top investment bank covering the Eurozone. You have just "
    "reviewed all ECB and Eurozone national central bank research published recently and must "
    "brief your investment team."
)


# ---------------------------------------------------------------------------
# HuggingFace
# ---------------------------------------------------------------------------

def call_gemma(messages: list, hf_token: str, max_tokens: int = 2048,
               retries: int = 5) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(retries):
        try:
            stream = client.chat.completions.create(
                messages=messages,
                temperature=0.3,
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
            is_rate_limit = "429" in str(e) or "Too Many Requests" in str(e)
            if is_rate_limit and attempt < retries - 1:
                wait = 60 * (attempt + 1)
                print(f"\n  HF rate limit (429), waiting {wait}s before retry "
                      f"(attempt {attempt+1}/{retries}) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def _strip_html(html_text: str) -> str:
    """Remove HTML tags and return plain text."""
    return re.sub(r"<[^>]+>", "", html_text or "").strip()


def _parse_feed_date(entry) -> datetime | None:
    """Extract publication date from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def scrape_rss(institution: str, url: str, cutoff: datetime) -> list[dict]:
    """Fetch and parse an RSS/Atom feed. Returns list of article dicts."""
    try:
        import feedparser
    except ImportError:
        print(f"  [skip {institution}] feedparser not installed.", file=sys.stderr)
        return []

    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        print(f"  [warn {institution}] RSS fetch failed ({url}): {exc}", file=sys.stderr)
        return []

    articles = []
    for entry in feed.entries:
        pub_dt = _parse_feed_date(entry)
        if pub_dt and pub_dt < cutoff:
            continue

        title = getattr(entry, "title", "").strip()
        link  = getattr(entry, "link",  "").strip()
        if not title or not link:
            continue

        authors = []
        if hasattr(entry, "authors"):
            authors = [a.get("name", "") for a in entry.authors if a.get("name")]
        elif hasattr(entry, "author") and entry.author:
            authors = [entry.author]

        snippet = ""
        if hasattr(entry, "summary") and entry.summary:
            snippet = _strip_html(entry.summary)[:600]
        elif hasattr(entry, "content") and entry.content:
            snippet = _strip_html(entry.content[0].get("value", ""))[:600]

        articles.append({
            "institution":     institution,
            "title":           title,
            "url":             link,
            "publicationDate": pub_dt.strftime("%Y-%m-%d") if pub_dt else "",
            "authors":         authors,
            "scrapedSnippet":  snippet,
        })

    print(f"  [RSS {institution}] {len(articles)} articles from {url}")
    return articles


def scrape_html_cbi(cutoff: datetime) -> list[dict]:
    """Scrape Central Bank of Ireland Research Technical Papers (static HTML)."""
    try:
        import requests as req
        from bs4 import BeautifulSoup
    except ImportError:
        print("  [skip CBI] requests/beautifulsoup4 not installed.", file=sys.stderr)
        return []

    url = "https://www.centralbank.ie/publication/research-publications/research-technical-papers"
    try:
        resp = req.get(url, headers=SCRAPE_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [warn CBI] HTML fetch failed: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    # CBI uses a list-style layout; try common patterns
    cards = (soup.select(".search-result__item") or
             soup.select("article") or
             soup.select(".publication-item") or
             soup.select("li.item") or [])

    for card in cards:
        title_el = card.select_one("h2 a, h3 a, h4 a, a.title, a[href]")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href  = title_el.get("href", "")
        if not href or len(title) < 10:
            continue
        if href.startswith("/"):
            href = "https://www.centralbank.ie" + href

        pub_date = ""
        time_el = card.select_one("time")
        if time_el:
            pub_date = time_el.get("datetime", time_el.get_text(strip=True))
        else:
            text = card.get_text(" ", strip=True)
            m = re.search(r"\b(\d{4}-\d{2}-\d{2}|\w+ \d{1,2},?\s*\d{4})\b", text)
            if m:
                pub_date = m.group(1)

        if pub_date:
            try:
                dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except ValueError:
                pass

        snippet_el = card.select_one("p, .summary, .description")
        snippet = snippet_el.get_text(strip=True)[:500] if snippet_el else ""

        articles.append({
            "institution":     "CBI",
            "title":           title,
            "url":             href,
            "publicationDate": pub_date,
            "authors":         [],
            "scrapedSnippet":  snippet,
        })

    print(f"  [HTML CBI] {len(articles)} articles from {url}")
    return articles


def scrape_playwright(institution: str, url: str, cutoff: datetime) -> list[dict]:
    """Scrape a JS-rendered page using Playwright (Chromium headless)."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print(f"  [skip {institution}] playwright not installed. "
              "Run: pip install playwright && playwright install chromium", file=sys.stderr)
        return []

    # Institution-specific base URLs for resolving relative hrefs
    base_urls = {
        "BDF": "https://www.banque-france.fr",
        "BDI": "https://www.bancaditalia.it",
        "BDE": "https://www.bde.es",
        "DNB": "https://www.dnb.nl",
    }
    base_url = base_urls.get(institution, "")

    articles = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=SCRAPE_HEADERS["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=60_000)

            selectors_to_try = [
                "article a[href]",
                "[class*='result'] a[href]",
                "[class*='paper'] a[href]",
                "[class*='publication'] a[href]",
                "[class*='research'] a[href]",
                "[class*='working'] a[href]",
                "li a[href]",
            ]

            seen_hrefs = set()
            for sel in selectors_to_try:
                try:
                    els = page.query_selector_all(sel)
                except Exception:
                    continue
                for el in els:
                    href = el.get_attribute("href") or ""
                    if not href or href in seen_hrefs or href.startswith("#"):
                        continue
                    if not href.startswith("http"):
                        from urllib.parse import urljoin
                        href = urljoin(base_url or url, href)
                    seen_hrefs.add(href)

                    title = (el.inner_text() or "").strip()
                    if len(title) < 10:
                        continue

                    pub_date = ""
                    try:
                        parent = el.evaluate_handle(
                            "el => el.closest('article, li, [class*=\"result\"], "
                            "[class*=\"paper\"], [class*=\"card\"], [class*=\"publication\"]')"
                        ).as_element()
                        if parent:
                            container_text = parent.inner_text()
                            m = re.search(
                                r"\b(\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|"
                                r"Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4})\b",
                                container_text,
                            )
                            if m:
                                pub_date = m.group(1)
                    except Exception:
                        pass

                    if pub_date:
                        try:
                            dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            if dt < cutoff:
                                continue
                        except ValueError:
                            pass

                    articles.append({
                        "institution":     institution,
                        "title":           title,
                        "url":             href,
                        "publicationDate": pub_date,
                        "authors":         [],
                        "scrapedSnippet":  "",
                    })

                if articles:
                    break

            browser.close()
    except PWTimeout:
        print(f"  [warn {institution}] Playwright timeout on {url}", file=sys.stderr)
    except Exception as exc:
        print(f"  [warn {institution}] Playwright error on {url}: {exc}", file=sys.stderr)

    print(f"  [PW {institution}] {len(articles)} articles from {url}")
    return articles


def scrape_all_institutions(days: int) -> list[dict]:
    """Scrape all institution sources and return a flat list of raw articles."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_articles: list[dict] = []
    seen_urls: set[str] = set()

    for source in SCRAPE_SOURCES:
        institution = source["institution"]
        src_type    = source["type"]
        src_url     = source["url"]

        if src_type == "rss":
            batch = scrape_rss(institution, src_url, cutoff)
        elif src_type == "html" and institution == "CBI":
            batch = scrape_html_cbi(cutoff)
        elif src_type == "playwright":
            batch = scrape_playwright(institution, src_url, cutoff)
        else:
            print(f"  [skip] Unknown source type '{src_type}' for {institution}", file=sys.stderr)
            batch = []

        for article in batch:
            if article["url"] not in seen_urls:
                seen_urls.add(article["url"])
                all_articles.append(article)

    print(f"\n[scrape] Total articles fetched: {len(all_articles)}")
    return all_articles


# ---------------------------------------------------------------------------
# AI enrichment
# ---------------------------------------------------------------------------

def enrich_articles(articles: list, hf_token: str) -> None:
    """Add aiSummary and tags to each article in-place via Gemma4."""
    total = len(articles)
    for batch_start in range(0, total, BATCH_SIZE):
        batch = articles[batch_start: batch_start + BATCH_SIZE]
        print(f"\n[Gemma4] Enriching articles {batch_start+1}–"
              f"{min(batch_start+BATCH_SIZE, total)} of {total} ...")

        items_text = json.dumps(
            [{"index": i+1, "title": a["title"],
              "snippet": a.get("scrapedSnippet", "")[:400]}
             for i, a in enumerate(batch)],
            ensure_ascii=False, indent=2,
        )
        messages = [
            {"role": "system", "content": TAGGING_SYSTEM_PROMPT},
            {"role": "user",   "content":
             f"Here are {len(batch)} articles. Return the JSON array:\n\n{items_text}"},
        ]

        raw = call_gemma(messages, hf_token, max_tokens=1500)
        raw_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)

        try:
            results = json.loads(raw_clean)
            if not isinstance(results, list):
                raise ValueError("Expected a JSON array")
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  JSON parse failed ({exc}); retrying ...", file=sys.stderr)
            messages[-1]["content"] += (
                "\n\nIMPORTANT: Your previous response could not be parsed. "
                "Return ONLY a raw JSON array, no markdown, no explanation."
            )
            raw2 = call_gemma(messages, hf_token, max_tokens=1500)
            raw2_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw2.strip(), flags=re.MULTILINE)
            try:
                results = json.loads(raw2_clean)
            except (json.JSONDecodeError, ValueError):
                print("  Fallback: empty summaries/tags for this batch.", file=sys.stderr)
                results = [{"summary": "", "tags": []} for _ in batch]

        while len(results) < len(batch):
            results.append({"summary": "", "tags": []})

        for article, result in zip(batch, results):
            article["aiSummary"] = result.get("summary", "")
            article["tags"]      = result.get("tags", [])[:8]


def generate_top_insights(articles: list, hf_token: str, run_date: str) -> str:
    """Generate the daily Top Insights narrative from all articles."""
    print("\n[Gemma4] Generating Top Insights digest ...")
    article_list = "\n".join(
        f"{i+1}. [{a['institution']}] {a['title']} — {a.get('scrapedSnippet', '')[:200]}"
        for i, a in enumerate(articles)
    )
    messages = [
        {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
        {"role": "user",   "content": (
            f"Today is {run_date}. Below are all ECB and Eurozone national central bank "
            f"publications from the recent monitoring window:\n\n{article_list}\n\n"
            "Select the 4–6 most analytically significant publications. For each, write "
            "2–3 sentences explaining the key insight and why it matters for the Eurozone "
            "macro/policy outlook. Format as a numbered list. End with a 2-sentence overall "
            "synthesis labeled **Synthesis:**."
        )},
    ]
    return call_gemma(messages, hf_token, max_tokens=1500)


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = cache_path.with_suffix(".backup.json")
            cache_path.rename(backup)
            print(f"  Cache corrupted — backed up to {backup}, starting fresh.", file=sys.stderr)
    return {"metadata": {"version": "2.0", "lastRun": None, "totalItems": 0}, "items": {}}


def make_hash(url: str, title: str) -> str:
    return hashlib.sha256((url + title).encode()).hexdigest()


def save_cache(cache: dict, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def insights_to_html(text: str) -> str:
    lines = text.strip().split("\n")
    parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\.\s+(.*)", line)
        if m:
            content = _inline_md(m.group(2))
            parts.append(
                f'<p class="insight-item">'
                f'<span class="insight-num">{m.group(1)}.</span> {content}</p>'
            )
        else:
            parts.append(f"<p>{_inline_md(line)}</p>")
    return "\n".join(parts)


def _inline_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",    r"<em>\1</em>",          text)
    return text


def tags_html(tags: list) -> str:
    if not tags:
        return ""
    chips = "".join(f'<span class="tag">{t}</span>' for t in tags)
    return f'<div class="tags">{chips}</div>'


def render_publication_card(article: dict) -> str:
    title      = article.get("title", "Untitled")
    url        = article.get("url", "#")
    authors    = article.get("authors", [])
    pub_date   = article.get("publicationDate", "")
    ai_summary = article.get("aiSummary", "")
    snippet    = article.get("scrapedSnippet", "")
    tags       = article.get("tags", [])
    is_new     = article.get("_isNew", True)
    badge      = ('<span class="badge-new">🆕 New</span>' if is_new
                  else '<span class="badge-cached">cached</span>')

    authors_html = (f'<div class="authors">Authors: {", ".join(authors)}</div>'
                    if authors else "")

    snippet_html = ""
    if snippet:
        snippet_safe = snippet.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        snippet_html = (
            '<details class="source-excerpt"><summary>Source excerpt</summary>'
            f'<p>{snippet_safe}</p></details>'
        )

    summary_html = f"<p>{_inline_md(ai_summary)}</p>" if ai_summary else ""

    return f"""
        <div class="publication">
            <div class="publication-title">
                <a href="{url}" target="_blank" rel="noopener">{title} →</a>
                {badge}
            </div>
            {authors_html}
            <div class="meta">Published: {pub_date}</div>
            {summary_html}
            {tags_html(tags)}
            {snippet_html}
        </div>"""


def generate_html_report(articles_by_institution: dict, top_insights_html: str,
                         run_date: str, days: int, cache_stats: dict) -> str:
    institutions_html = ""
    for code in INSTITUTION_ORDER:
        arts = articles_by_institution.get(code, [])
        if not arts:
            continue
        meta      = INSTITUTION_META.get(code, {"name": code, "type": "Publications"})
        new_count = sum(1 for a in arts if a.get("_isNew", True))
        cards     = "".join(render_publication_card(a) for a in arts)
        institutions_html += f"""
        <h2>{meta['name']}</h2>
        <p class="meta"><strong>Content Type:</strong> {meta['type']} &nbsp;|&nbsp;
        <strong>New Items:</strong> {new_count} of {len(arts)}</p>
        {cards}"""

    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ECB & Eurozone Monitor — {run_date}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1000px; margin: 0 auto; padding: 20px;
            line-height: 1.6; background: #f5f5f5;
        }}
        .container {{
            background: white; padding: 40px;
            border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{ color: #003189; border-bottom: 3px solid #003189; padding-bottom: 10px; }}
        h2 {{ color: #333; border-bottom: 2px solid #ddd; padding-bottom: 8px; margin-top: 35px; }}
        .meta {{ color: #666; font-size: 0.9em; margin: 8px 0; }}
        .back-link {{
            display: inline-block; margin-bottom: 20px;
            color: #003189; text-decoration: none;
        }}
        .back-link:hover {{ text-decoration: underline; }}
        /* Top Insights */
        .insights-panel {{
            background: #e8f0fe; border-left: 5px solid #003189;
            border-radius: 6px; padding: 24px 28px; margin: 24px 0 32px;
        }}
        .insights-panel h2 {{
            border: none; color: #003189; margin-top: 0;
            padding-bottom: 0; font-size: 1.2em;
        }}
        .insight-item {{ margin: 10px 0; }}
        .insight-num {{ font-weight: bold; color: #003189; margin-right: 4px; }}
        .insights-footer {{ font-size: 0.8em; color: #999; margin-top: 14px; }}
        /* Cards */
        .publication {{
            background: #f8f9fa; padding: 15px 18px; margin: 15px 0;
            border-left: 4px solid #003189; border-radius: 4px;
        }}
        .publication-title {{
            font-size: 1.05em; font-weight: bold; margin-bottom: 6px;
            display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
        }}
        .publication-title a {{ color: #003189; text-decoration: none; }}
        .publication-title a:hover {{ text-decoration: underline; }}
        .authors {{ color: #666; font-size: 0.88em; margin: 4px 0; }}
        .badge-new {{
            font-size: 0.72em; background: #e8f5e9; color: #2e7d32;
            padding: 2px 7px; border-radius: 10px; font-weight: normal;
        }}
        .badge-cached {{
            font-size: 0.72em; background: #f5f5f5; color: #9e9e9e;
            padding: 2px 7px; border-radius: 10px; font-weight: normal;
        }}
        /* Tags */
        .tags {{ margin: 10px 0 6px; display: flex; flex-wrap: wrap; gap: 5px; }}
        .tag {{
            background: #e8f0fe; color: #003189; font-size: 0.75em;
            padding: 3px 10px; border-radius: 12px; white-space: nowrap;
        }}
        /* Source excerpt */
        details.source-excerpt {{ margin-top: 8px; font-size: 0.88em; }}
        details.source-excerpt summary {{ cursor: pointer; color: #888; }}
        details.source-excerpt p {{ margin: 6px 0 0; color: #555; font-style: italic; }}
        /* Cache summary */
        .cache-summary {{
            background: #f1f8e9; border-left: 4px solid #558b2f;
            padding: 14px 18px; border-radius: 4px; margin: 20px 0; font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <a href="index.html" class="back-link">← Back to ECB Monitor Archive</a>
    <div class="container">
        <h1>🇪🇺 ECB &amp; Eurozone Central Bank Monitor</h1>
        <div class="meta">
            <strong>Report Date:</strong> {run_date}<br>
            <strong>Coverage Period:</strong> Past {days} days<br>
            <strong>Institutions Monitored:</strong> ECB, DBB, BDF, BDI, BDE, DNB, CBI<br>
            <strong>Generated:</strong> {now_ts}
        </div>

        <div class="insights-panel">
            <h2>🔦 Today's Most Interesting Insights</h2>
            {top_insights_html}
            <div class="insights-footer">Generated by Gemma 4 · {now_ts}</div>
        </div>

        {institutions_html}

        <div class="cache-summary">
            <strong>Cache Update Summary</strong><br>
            Items added: {cache_stats.get('added', 0)} &nbsp;|&nbsp;
            Already cached: {cache_stats.get('cached', 0)} &nbsp;|&nbsp;
            Total cache size: {cache_stats.get('total', 0)} items
        </div>
    </div>
</body>
</html>"""


def generate_md_report(articles_by_institution: dict, top_insights_text: str,
                       run_date: str, days: int, cache_stats: dict) -> str:
    lines = [
        f"# 🇪🇺 ECB & Eurozone Central Bank Monitor — {run_date}",
        "",
        f"**Coverage Period:** Past {days} days | **Institutions:** ECB, DBB, BDF, BDI, BDE, DNB, CBI",
        "",
        "---",
        "",
        "## 🔦 Today's Most Interesting Insights",
        "",
        top_insights_text.strip(),
        "",
        "---",
    ]
    for code in INSTITUTION_ORDER:
        arts = articles_by_institution.get(code, [])
        if not arts:
            continue
        meta      = INSTITUTION_META.get(code, {"name": code, "type": "Publications"})
        new_count = sum(1 for a in arts if a.get("_isNew", True))
        lines += [
            "",
            f"## {meta['name']}",
            f"**Content Type:** {meta['type']} | **New:** {new_count} of {len(arts)}",
        ]
        for a in arts:
            badge = "🆕" if a.get("_isNew", True) else "(cached)"
            lines += [
                "",
                f"### {badge} [{a.get('title', 'Untitled')}]({a.get('url', '#')})",
                f"**Published:** {a.get('publicationDate', '')} | "
                f"**Authors:** {', '.join(a.get('authors', []))}",
                "",
                a.get("aiSummary", ""),
                "",
                f"**Tags:** {' · '.join(a.get('tags', []))}",
            ]
    lines += [
        "",
        "---",
        "",
        "## Cache Update Summary",
        f"- Items added: {cache_stats.get('added', 0)}",
        f"- Already cached: {cache_stats.get('cached', 0)}",
        f"- Total cache size: {cache_stats.get('total', 0)} items",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Monthly MTD helpers
# ---------------------------------------------------------------------------

def load_mtd_articles(cache_path: Path, year_month: str) -> list[dict]:
    """Return all cached articles whose publicationDate falls in year_month (YYYY-MM)."""
    cache = load_cache(cache_path)
    articles = []
    for item in cache.get("items", {}).values():
        if item.get("publicationDate", "").startswith(year_month):
            articles.append({
                "institution":     item.get("institutionCode", ""),
                "title":           item.get("title", ""),
                "url":             item.get("url", ""),
                "publicationDate": item.get("publicationDate", ""),
                "authors":         item.get("authors", []),
                "scrapedSnippet":  item.get("scrapedSnippet", ""),
                "aiSummary":       item.get("aiSummary", ""),
                "tags":            item.get("tags", []),
                "_isNew":          False,
                "_hash":           "",
            })
    articles.sort(key=lambda a: a["publicationDate"], reverse=True)
    return articles


def run_monthly_pipeline(run_date: str, cache_path: Path,
                         output_dir: Path, hf_token: str) -> None:
    """Build the month-to-date rolling report from the cache."""
    year_month  = run_date[:7]
    month_label = datetime.strptime(year_month, "%Y-%m").strftime("%B %Y")

    all_articles = load_mtd_articles(cache_path, year_month)
    if not all_articles:
        print(f"[ecb-monitor] No cached articles for {year_month} — skipping MTD report.")
        return

    print(f"\n[ecb-monitor] MTD report: {len(all_articles)} articles for {month_label}")

    top_insights_text = generate_top_insights(all_articles, hf_token, run_date)
    top_insights_html = insights_to_html(top_insights_text)

    articles_by_institution: dict = {}
    for article in all_articles:
        code = article.get("institution", "UNKNOWN")
        articles_by_institution.setdefault(code, []).append(article)

    cache_stats = {"added": 0, "cached": len(all_articles), "total": len(all_articles)}
    html = generate_html_report(
        articles_by_institution, top_insights_html,
        run_date=f"{month_label} (Month to Date)",
        days=0,
        cache_stats=cache_stats,
    )
    html = html.replace(
        "<strong>Coverage Period:</strong> Past 0 days",
        f"<strong>Coverage Period:</strong> Month to date: {month_label} "
        f"({len(all_articles)} articles across 7 institutions)",
    )

    md = generate_md_report(
        articles_by_institution, top_insights_text,
        run_date=f"{month_label} (Month to Date)",
        days=0,
        cache_stats=cache_stats,
    )
    md = md.replace(
        "**Coverage Period:** Past 0 days",
        f"**Coverage Period:** Month to date: {month_label} ({len(all_articles)} articles)",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"ecb-monitor-{year_month}.html"
    md_path   = output_dir / f"ecb-monitor-{year_month}.md"

    html_path.write_text(html, encoding="utf-8")
    md_path.write_text(md,   encoding="utf-8")

    print(f"[ecb-monitor] MTD reports written:")
    print(f"  HTML → {html_path}")
    print(f"  MD   → {md_path}")
    regenerate_cb_monitor(output_dir.parent.parent)


# ---------------------------------------------------------------------------
# Core pipeline (shared between --input and --scrape modes)
# ---------------------------------------------------------------------------

def run_pipeline(all_articles: list, days: int, run_date: str,
                 cache_path: Path, output_dir: Path, hf_token: str) -> None:
    """Enrich articles, update cache, write reports."""
    cache = load_cache(cache_path)
    items = cache.setdefault("items", {})

    needs_enrichment = []
    for article in all_articles:
        h = make_hash(article.get("url", ""), article.get("title", ""))
        article["_hash"] = h
        if h in items:
            article["_isNew"]    = False
            cached               = items[h]
            article["aiSummary"] = cached.get("aiSummary", "")
            article["tags"]      = cached.get("tags", [])
            if not article["tags"] or not article["aiSummary"]:
                needs_enrichment.append(article)
        else:
            article["_isNew"] = True
            needs_enrichment.append(article)

    added_count  = sum(1 for a in all_articles if a["_isNew"])
    cached_count = len(all_articles) - added_count
    print(f"  New: {added_count} | Cached: {cached_count} | "
          f"Need enrichment: {len(needs_enrichment)}")

    if needs_enrichment:
        enrich_articles(needs_enrichment, hf_token)
    else:
        print("  All articles already enriched — skipping tagging calls.")

    top_insights_text = generate_top_insights(all_articles, hf_token, run_date)
    top_insights_html = insights_to_html(top_insights_text)

    now_ts = datetime.now(timezone.utc).isoformat()
    for article in all_articles:
        h = article["_hash"]
        if h not in items or not items[h].get("tags"):
            items[h] = {
                "url":             article.get("url", ""),
                "title":           article.get("title", ""),
                "institution":     INSTITUTION_META.get(article.get("institution", ""), {}).get(
                                       "name", article.get("institution", "")),
                "institutionCode": article.get("institution", ""),
                "contentType":     INSTITUTION_META.get(article.get("institution", ""), {}).get(
                                       "type", "research"),
                "publicationDate": article.get("publicationDate", ""),
                "authors":         article.get("authors", []),
                "firstSeen":       items.get(h, {}).get("firstSeen", now_ts),
                "lastChecked":     now_ts,
                "scrapedSnippet":  article.get("scrapedSnippet", ""),
                "aiSummary":       article.get("aiSummary", ""),
                "tags":            article.get("tags", []),
                "tagsGeneratedAt": now_ts,
            }
        else:
            items[h]["lastChecked"] = now_ts

    cache["metadata"]["lastRun"]    = now_ts
    cache["metadata"]["totalItems"] = len(items)
    cache["metadata"]["version"]    = "2.0"
    save_cache(cache, cache_path)
    print(f"\n[ecb-monitor] Cache saved: {len(items)} total items → {cache_path}")

    articles_by_institution: dict = {}
    for article in all_articles:
        code = article.get("institution", "UNKNOWN")
        articles_by_institution.setdefault(code, []).append(article)

    cache_stats = {"added": added_count, "cached": cached_count, "total": len(items)}

    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"ecb-monitor-{run_date}.html"
    md_path   = output_dir / f"ecb-monitor-{run_date}.md"

    html_path.write_text(
        generate_html_report(articles_by_institution, top_insights_html,
                             run_date, days, cache_stats),
        encoding="utf-8",
    )
    md_path.write_text(
        generate_md_report(articles_by_institution, top_insights_text,
                           run_date, days, cache_stats),
        encoding="utf-8",
    )

    print(f"[ecb-monitor] Reports written:")
    print(f"  HTML → {html_path}")
    print(f"  MD   → {md_path}")
    regenerate_cb_monitor(output_dir.parent.parent)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ECB & Eurozone Monitor — AI Processor")

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--input",   help="Path to pre-fetched raw articles JSON (skill mode)")
    mode_group.add_argument("--scrape",  action="store_true",
                            help="Fetch articles directly from ECB/NCB sources (GH Actions mode)")
    mode_group.add_argument("--monthly", action="store_true",
                            help="Build month-to-date rolling report from cache (no scraping)")

    parser.add_argument("--output-dir", required=True, help="Directory for HTML/MD reports")
    parser.add_argument("--cache",      required=True, help="Path to cache JSON file")
    parser.add_argument("--date",       required=True, help="Report date YYYY-MM-DD")
    parser.add_argument("--days",       type=int, default=3,
                        help="Look-back window in days (default: 3 for --scrape, 30 for --input)")
    args = parser.parse_args()

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    output_dir = Path(args.output_dir).expanduser()
    cache_path = Path(args.cache).expanduser()
    run_date   = args.date

    if args.monthly:
        run_monthly_pipeline(run_date, cache_path, output_dir, hf_token)
    elif args.scrape:
        days         = args.days
        all_articles = scrape_all_institutions(days)
        print(f"\n[ecb-monitor] {len(all_articles)} articles scraped (last {days} days)")
        run_pipeline(all_articles, days, run_date, cache_path, output_dir, hf_token)
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        raw          = json.loads(input_path.read_text(encoding="utf-8"))
        all_articles = raw.get("articles", [])
        days         = args.days if args.days != 3 else raw.get("days", 30)
        print(f"\n[ecb-monitor] {len(all_articles)} articles loaded from {input_path}")
        run_pipeline(all_articles, days, run_date, cache_path, output_dir, hf_token)


if __name__ == "__main__":
    main()
