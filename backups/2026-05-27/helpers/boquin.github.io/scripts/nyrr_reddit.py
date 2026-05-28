#!/usr/bin/env python3
"""
NYRR Reddit Scanner
Polls r/NYRR and r/running for posts mentioning race registration.
Stores results in data/nyrr_reddit_state.json.
Injects a "Community Buzz" card into reports/nyrr/index.html.

Usage:
    python scripts/nyrr_reddit.py
    python scripts/nyrr_reddit.py --dry-run
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT  = Path(__file__).parent.parent
STATE_FILE = REPO_ROOT / "data" / "nyrr_reddit_state.json"
INDEX_HTML = REPO_ROOT / "reports" / "nyrr" / "index.html"

MARKER_START = "<!-- nyrr-reddit-start -->"
MARKER_END   = "<!-- nyrr-reddit-end -->"
PLACEHOLDER  = "<!-- nyrr-reddit-here -->"

HEADERS = {"User-Agent": "nyrr-watcher/1.0 (boquin.xyz; contact jeannealbertoreading@gmail.com)"}

# (subreddit, search_query) pairs — r/NYRR is defunct; r/running is the main hub
SEARCHES = [
    ("running",     "NYRR registration"),
    ("running",     "NYRR 9+1"),
    ("running",     "nyrr opens"),
    ("nycmarathon", "NYRR registration"),
]


# ---------------------------------------------------------------------------

def search_reddit(subreddit: str, query: str, limit: int = 25) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {"q": query, "sort": "new", "t": "all", "limit": limit, "restrict_sr": 1}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("data", {}).get("children", [])
    except Exception as exc:
        print(f"[nyrr_reddit] WARN: r/{subreddit} search failed: {exc}", file=sys.stderr)
        return []


def fetch_posts() -> list[dict]:
    seen_ids: set[str] = set()
    posts: list[dict] = []

    for sub, query in SEARCHES:
        raw = search_reddit(sub, query)
        time.sleep(1)
        for child in raw:
            d = child.get("data", {})
            pid = d.get("id", "")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            posts.append({
                "id":        pid,
                "subreddit": d.get("subreddit", sub),
                "title":     d.get("title", ""),
                "url":       "https://reddit.com" + d.get("permalink", ""),
                "score":     d.get("score", 0),
                "created":   datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc).strftime("%Y-%m-%d"),
                "num_comments": d.get("num_comments", 0),
            })

    posts.sort(key=lambda p: p["created"], reverse=True)
    return posts


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"posts": [], "last_fetched": None}


def merge_posts(existing: list[dict], fresh: list[dict]) -> list[dict]:
    by_id = {p["id"]: p for p in existing}
    for p in fresh:
        by_id[p["id"]] = p   # update score/comments if already seen
    merged = sorted(by_id.values(), key=lambda p: p["created"], reverse=True)
    return merged[:200]      # keep rolling 200-post history


def predict_next_drop(posts: list[dict]) -> str:
    """Group historical posts by month to detect announcement clusters."""
    month_counts: dict[str, int] = defaultdict(int)
    for p in posts:
        try:
            dt = datetime.strptime(p["created"], "%Y-%m-%d")
            month_counts[dt.strftime("%B")] += 1
        except ValueError:
            pass
    if not month_counts:
        return ""
    top = sorted(month_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    months_str = ", ".join(m for m, _ in top)
    return f"Based on community activity, registration buzz historically peaks in: <strong>{months_str}</strong>."


def build_block(posts: list[dict], now_str: str) -> str:
    prediction = predict_next_drop(posts)
    prediction_html = f'<p class="reddit-prediction">{prediction}</p>' if prediction else ""

    rows = ""
    for p in posts[:15]:
        badge = f'<span class="reddit-sub">r/{p["subreddit"]}</span>'
        rows += f"""
        <div class="reddit-entry">
            {badge}
            <a class="reddit-title" href="{p['url']}" target="_blank" rel="noopener">{p['title'][:120]}</a>
            <span class="reddit-meta">{p['created']} &middot; {p['score']} pts &middot; {p['num_comments']} comments</span>
        </div>"""

    if not rows:
        rows = '<p class="muted" style="color:#94a3b8;font-size:.88rem;">No matching posts found yet.</p>'

    return f"""{MARKER_START}
<div style="max-width:860px;margin:0 auto;padding:0 1rem 1.25rem;">
  <div style="background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:1.5rem;">
    <div style="border-left:4px solid #f7931e;padding-left:1rem;margin-bottom:1rem;">
      <h2 style="color:#1e293b;margin:0 0 .2rem;font-size:1rem;text-transform:uppercase;letter-spacing:.07em;">Community Buzz</h2>
      <p style="color:#94a3b8;font-size:.78rem;margin:0;">Reddit · r/NYRR &amp; r/running · updated {now_str} UTC</p>
    </div>
    <style>
      .reddit-prediction{{background:#fff0e6;border-radius:8px;padding:.6rem 1rem;font-size:.85rem;color:#64748b;margin-bottom:1rem;}}
      .reddit-entry{{padding:.55rem 0;border-bottom:1px solid #f1f5f9;display:flex;flex-wrap:wrap;gap:.35rem;align-items:baseline;}}
      .reddit-entry:last-child{{border-bottom:none;}}
      .reddit-sub{{font-size:.72rem;font-weight:700;background:#fff0e6;color:#ff6b35;border-radius:5px;padding:.1rem .4rem;white-space:nowrap;}}
      .reddit-title{{font-size:.88rem;color:#1e293b;text-decoration:none;flex:1;min-width:180px;}}
      .reddit-title:hover{{text-decoration:underline;color:#ff6b35;}}
      .reddit-meta{{font-size:.75rem;color:#94a3b8;width:100%;}}
    </style>
    {prediction_html}
    {rows}
  </div>
</div>
{MARKER_END}"""


def inject(index_html: Path, block: str) -> None:
    html = index_html.read_text(encoding="utf-8")
    html = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        "",
        html,
        flags=re.DOTALL,
    )
    if PLACEHOLDER in html:
        html = html.replace(PLACEHOLDER, block + "\n\n        " + PLACEHOLDER, 1)
    else:
        last_body = html.rfind("</body>")
        html = html[:last_body] + block + "\n</body>" + html[last_body + len("</body>"):]
    index_html.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M")

    print("[nyrr_reddit] fetching Reddit posts…")
    fresh = fetch_posts()
    print(f"[nyrr_reddit] {len(fresh)} relevant posts found")

    state = load_state()
    state["posts"] = merge_posts(state.get("posts", []), fresh)
    state["last_fetched"] = now.isoformat()

    block = build_block(state["posts"], now_str)

    if args.dry_run:
        print("[nyrr_reddit] dry-run — no files written")
        print(f"  Sample titles: {[p['title'][:60] for p in state['posts'][:3]]}")
        return

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    inject(INDEX_HTML, block)
    print(f"[nyrr_reddit] injected → {INDEX_HTML}")


if __name__ == "__main__":
    main()
