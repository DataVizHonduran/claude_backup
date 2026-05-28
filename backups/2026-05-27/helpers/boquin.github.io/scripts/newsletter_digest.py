#!/usr/bin/env python3
"""
Newsletter Digest — Weekly AI Synthesis
Fetches recent posts from all subscriptions via RSS feeds (/feed),
generates reports/newsletters/index.html, and injects Gemma 4 macro synthesis.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/newsletter_digest.py

Output:
    reports/newsletters/substack_posts.json
    reports/newsletters/index.html
    reports/newsletters/commentary-YYYY-MM-DD.md
"""

import os
import sys
import re
import time
import json
import requests
import feedparser
import markdown as md_lib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID   = "google/gemma-4-31B-it"
OUTPUT_DIR = Path("reports/newsletters")
INDEX_HTML = OUTPUT_DIR / "index.html"
POSTS_JSON = OUTPUT_DIR / "substack_posts.json"

MARKER_START = "<!-- newsletters-commentary-start -->"
MARKER_END   = "<!-- newsletters-commentary-end -->"

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

URLS = [
    "https://junkbondinvestor.substack.com",
    "https://www.semianalysis.com",
    "https://epbresearch.substack.com",
    "https://thechangeconstant.substack.com",
    "https://hfiresearch.substack.com",
    "https://www.notboring.co",
    "https://macrocreditthinking.substack.com",
    "https://macromostly.substack.com",
    "https://rupakghose.substack.com",
    "https://www.newcomer.co",
    "https://globalmacromethod.substack.com",
    "https://thematicmarkets.substack.com",
    "https://thesundaydrive.substack.com",
    "https://www.doomberg.com",
    "https://technically.substack.com",
    "https://openinsights.substack.com",
    "https://www.chinatalk.media",
    "https://capitalmischief.substack.com",
    "https://sovereignvibe.substack.com",
    "https://robinjbrooks.substack.com",
    "https://www.parentdata.org",
    "https://debtserious.substack.com",
    "https://cartadocondado.substack.com",
    "https://thecentralbankswatcher.substack.com",
    "https://10xdisruptivestocks.substack.com",
    "https://yetanothervalueblog.substack.com",
    "https://www.weightythoughts.com",
    "https://chaufa.substack.com",
    "https://quantseeker.substack.com",
    "https://reboundcapital.substack.com",
    "https://stevesaretsky.substack.com",
    "https://macromusings.substack.com",
    "https://airlinerevenueeconomics.substack.com",
    "https://neilsethi.substack.com",
    "https://www.publicnotice.co",
    "https://lbmacro.substack.com",
    "https://quantumnomia.substack.com",
    "https://whirligigbear.substack.com",
    "https://therosenreport.substack.com",
    "https://helenemeisler.substack.com",
    "https://quantenthusiasts.substack.com",
    "https://www.commoditycontext.com",
    "https://energyoutlookadvisors.substack.com",
    "https://chartstorm.substack.com",
    "https://damnang.substack.com",
    "https://macrocharts.substack.com",
    "https://polimetrics.substack.com",
    "https://dualityresearch.substack.com",
    "https://www.capitalwars.com",
    "https://thesignal.substack.com",
    "https://asgoghie.substack.com",
    "https://worksinprogress.substack.com",
    "https://demographyunplugged.substack.com",
    "https://bojwatchtower.substack.com",
    "https://tscs.substack.com",
    "https://michaelwgreen.substack.com",
    "https://latinamericariskreport.substack.com",
]

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _parse_date(entry) -> str:
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            try:
                return datetime(*t[:3]).strftime("%Y-%m-%d")
            except Exception:
                pass
    return ""


def fetch_posts(base_url: str) -> list[dict]:
    base = base_url.rstrip("/")
    for feed_path in ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml"):
        feed_url = base + feed_path
        try:
            r = requests.get(feed_url, headers=FETCH_HEADERS, timeout=15, allow_redirects=True)
            if r.status_code != 200:
                print(f"    {feed_url}: HTTP {r.status_code}", file=sys.stderr)
                continue
            feed = feedparser.parse(r.content)
            if feed.bozo and not feed.entries:
                ct = r.headers.get("content-type", "")
                print(f"    {feed_url}: bozo=True 0-entries ct={ct[:60]}", file=sys.stderr)
                continue
            posts = []
            for entry in feed.entries[:5]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                link = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("subtitle", "")
                summary = re.sub(r"<[^>]+>", "", summary)[:200].strip()
                date = _parse_date(entry)
                posts.append({"title": title, "url": link, "date": date, "description": summary})
            if posts:
                return posts
        except Exception as e:
            print(f"    {feed_url}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
    return []


def load_cache() -> dict:
    if POSTS_JSON.exists():
        try:
            return json.loads(POSTS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def fetch_all() -> dict:
    cached = load_cache()
    seen, unique = set(), []
    for u in URLS:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    results = {}
    for url in unique:
        posts = fetch_posts(url)
        domain = urlparse(url).netloc
        if posts:
            results[domain] = posts
            print(f"  {domain}: {len(posts)} posts")
        elif domain in cached and cached[domain]:
            results[domain] = cached[domain]
            print(f"  {domain}: cached ({len(cached[domain])} posts)")
        else:
            results[domain] = []
            print(f"  {domain}: FAILED")
        time.sleep(0.3)
    return results


# ---------------------------------------------------------------------------
# Gemma
# ---------------------------------------------------------------------------

def build_gemma_input(results: dict) -> str:
    lines = []
    for domain, posts in results.items():
        if not posts:
            continue
        lines.append(f"\n=== {domain} ===")
        for p in posts[:3]:
            desc = p["description"][:120] if p["description"] else ""
            suffix = f" — {desc}" if desc else ""
            lines.append(f"  [{p['date']}] {p['title']}{suffix}")
    return "\n".join(lines)[:8000]


def call_gemma(messages: list, hf_token: str, max_tokens: int = 1800) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(5):
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
            is_rate_limit = any(x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if is_rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n  HF rate limit — waiting {wait}s (attempt {attempt+1}/5) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def generate_synthesis(data: str, hf_token: str, week_of: str) -> str:
    prompt = f"""[ROLE]: Senior macro strategist reviewing a curated set of research newsletters.

[TASK]: Synthesize the key themes from this week's newsletter posts (week of {week_of}).
Produce a structured Markdown commentary covering:
1. Dominant macro themes — what most newsletters are focused on this week
2. Divergences — where analysts disagree (bullish vs bearish, policy views, sector calls)
3. Most actionable signals — specific trades, data releases, or inflection points flagged
4. Under-covered risks — themes mentioned by only 1-2 newsletters that could matter
5. One-line verdict: risk-on, risk-off, or mixed heading into next week

[FORMAT]:
- Markdown with ## headers and bullet points
- Summary table: | Theme | Newsletters flagging it | Consensus view |
- Under 600 words total

[DATA]:
{data}"""

    return call_gemma([{"role": "user", "content": prompt}], hf_token)


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def build_html(results: dict, week_of: str) -> str:
    active = {d: p for d, p in results.items() if p}
    failed = [d for d, p in results.items() if not p]

    cards_html = ""
    for domain, posts in sorted(active.items()):
        post_links = ""
        for p in posts[:3]:
            date_tag = (
                f'<span style="color:#888;font-size:0.8em;margin-right:6px;">{p["date"]}</span>'
                if p["date"] else ""
            )
            post_links += (
                f'<li style="margin:6px 0;">{date_tag}'
                f'<a href="{p["url"]}" target="_blank" style="color:#007bff;text-decoration:none;">{p["title"]}</a>'
                f'</li>\n'
            )
        cards_html += f"""
<div style="background:white;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);padding:20px;margin-bottom:16px;">
  <h3 style="color:#333;margin:0 0 10px;font-size:1em;border-bottom:2px solid #007bff;padding-bottom:6px;">{domain}</h3>
  <ul style="list-style:none;padding:0;margin:0;">{post_links}</ul>
</div>"""

    failed_html = ""
    if failed:
        failed_html = f"""
<div style="background:#fff3cd;border-radius:8px;padding:16px;margin-top:20px;">
  <p style="color:#856404;margin:0;font-size:0.9em;">
    <strong>Paywalled / not retrieved ({len(failed)}):</strong> {", ".join(failed)}
  </p>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Newsletter Digest — Week of {week_of}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f5f5; padding:20px; }}
.container {{ max-width:1400px; margin:0 auto; }}
h1 {{ color:#333; border-bottom:3px solid #007bff; padding-bottom:15px; margin-bottom:20px; }}
h2 {{ color:#333; margin:30px 0 16px; font-size:1.3em; }}
.meta {{ color:#666; font-size:0.85em; margin-bottom:20px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(380px,1fr)); gap:16px; }}
</style>
</head>
<body>
<div class="container">
<h1>Newsletter Digest</h1>
<p class="meta">Week of {week_of} &nbsp;·&nbsp; {len(active)} newsletters &nbsp;·&nbsp; Auto-generated weekly via Gemma 4</p>

{MARKER_START}{MARKER_END}

<h2>Recent Posts by Newsletter</h2>
<div class="grid">
{cards_html}
</div>
{failed_html}
</div>
</body>
</html>"""


def inject_commentary(commentary_md: str, generated_at: str) -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    body_html = md_lib.markdown(commentary_md, extensions=["tables"])

    block = f"""{MARKER_START}
<div style="margin:20px 0 30px;">
  <div style="background:white;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);padding:30px;">
    <div style="border-left:4px solid #007bff;padding-left:16px;margin-bottom:20px;">
      <h2 style="color:#333;margin:0 0 4px;">Weekly Macro Synthesis</h2>
      <p style="color:#666;font-size:0.85em;margin:0;">Generated {generated_at} UTC &nbsp;·&nbsp; google/gemma-4-31B-it</p>
    </div>
    <div class="newsletters-commentary" style="line-height:1.7;color:#444;">
      <style>
        .newsletters-commentary table {{border-collapse:collapse;width:100%;margin:16px 0;}}
        .newsletters-commentary th,.newsletters-commentary td {{border:1px solid #dee2e6;padding:8px 12px;text-align:left;}}
        .newsletters-commentary th {{background:#f8f9fa;font-weight:600;}}
        .newsletters-commentary h2,.newsletters-commentary h3 {{color:#333;margin:20px 0 8px;}}
        .newsletters-commentary ul {{padding-left:20px;}}
        .newsletters-commentary li {{margin:4px 0;}}
      </style>
      {body_html}
    </div>
  </div>
</div>
{MARKER_END}"""

    html = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        block,
        html,
        flags=re.DOTALL,
    )
    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"  Injected commentary into {INDEX_HTML}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    today        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching substacks ...")
    results = fetch_all()

    POSTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    active_count = sum(1 for p in results.values() if p)
    print(f"\nFetched: {active_count}/{len(results)} newsletters returned posts")

    print("\nBuilding HTML page ...")
    html = build_html(results, today)
    INDEX_HTML.write_text(html, encoding="utf-8")

    data = build_gemma_input(results)
    print(f"  Built {len(data)} chars of structured data for Gemma")

    print("\nGenerating synthesis via Gemma 4 ...")
    commentary = generate_synthesis(data, hf_token, today)

    dated_path = OUTPUT_DIR / f"commentary-{today}.md"
    dated_path.write_text(commentary, encoding="utf-8")
    print(f"\nWrote archive: {dated_path}")

    inject_commentary(commentary, generated_at)
    print("Done.")
