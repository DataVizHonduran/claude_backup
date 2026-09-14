#!/usr/bin/env python3
"""
Newsletter Fetch — runs locally every Sunday night via launchd.
Fetches RSS from all subscriptions, saves substack_posts.json, commits and pushes.
GitHub Actions reads this JSON on Monday as its data source.

Usage:
    python3 scripts/newsletter_fetch.py
"""

import re
import time
import json
import sys
import requests
import feedparser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import subprocess

OUTPUT_DIR = Path("reports/newsletters")
POSTS_JSON = OUTPUT_DIR / "substack_posts.json"

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
        try:
            r = requests.get(base + feed_path, headers=FETCH_HEADERS, timeout=15, allow_redirects=True)
            if r.status_code != 200:
                continue
            feed = feedparser.parse(r.content)
            if feed.bozo and not feed.entries:
                continue
            posts = []
            for entry in feed.entries[:5]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "") or entry.get("subtitle", ""))[:200].strip()
                posts.append({"title": title, "url": entry.get("link", ""), "date": _parse_date(entry), "description": summary})
            if posts:
                return posts
        except Exception:
            continue
    return []


def fetch_all() -> dict:
    seen, unique = set(), []
    for u in URLS:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    results = {}
    ok = fail = 0
    for url in unique:
        posts = fetch_posts(url)
        domain = urlparse(url).netloc
        results[domain] = posts
        if posts:
            ok += 1
            print(f"  OK   {domain}: {len(posts)} posts")
        else:
            fail += 1
            print(f"  FAIL {domain}")
        time.sleep(0.3)
    print(f"\n{ok} OK / {fail} failed")
    return results


def git_push(repo: Path, today: str) -> None:
    def run(cmd):
        result = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  git error: {result.stderr.strip()}", file=sys.stderr)
        return result.returncode == 0

    run(["git", "pull", "--rebase"])
    run(["git", "add", str(POSTS_JSON)])
    status = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=repo)
    if status.returncode == 0:
        print("  No changes to commit.")
        return
    run(["git", "commit", "-m", f"Newsletter fetch — {today} (local)"])
    run(["git", "pull", "--rebase"])
    if run(["git", "push"]):
        print("  Pushed to GitHub.")
    else:
        print("  Push failed — check SSH keys.", file=sys.stderr)


if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    repo = Path(__file__).resolve().parent.parent

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching newsletters ({today}) ...")
    results = fetch_all()

    POSTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved {POSTS_JSON}")

    print("Committing and pushing ...")
    git_push(repo, today)
    print("Done.")
