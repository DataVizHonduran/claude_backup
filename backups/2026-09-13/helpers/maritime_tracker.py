"""
Hormuz / Persian Gulf maritime threat tracker
Sources:
  1. Combined Maritime Forces RSS  — combinedmaritimeforces.com/feed/
  2. NGA MSI Broadcast Warnings    — msi.nga.mil (NAVAREA IX = Arabian Sea/Persian Gulf)

UKMTO and MARAD MSCI are Cloudflare/Akamai-blocked to headless requests.
MARAD workaround: subscribe via GovDelivery email list and parse incoming mail.
"""

import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email import utils as eutils
from html import unescape
from typing import Optional
from xml.etree import ElementTree as ET

import requests

# ── geo filter ────────────────────────────────────────────────────────────────

GEO_KEYWORDS = [
    "hormuz", "strait of hormuz",
    "persian gulf", "arabian gulf", "arabian sea",
    "gulf of oman",
    "iran", "uae", "united arab emirates",
    "bahrain", "qatar", "oman",
    "musandam", "bandar abbas", "qeshm",
    "5th fleet", "fifth fleet", "navcent",
    "red sea",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CMF_FEED    = "https://combinedmaritimeforces.com/feed/"
NGA_API     = "https://msi.nga.mil/api/publications/broadcast-warn?output=json"

# NAVAREA regions covering the Gulf / Arabian Sea / Indian Ocean
# IX = Arabian Sea (India coordinator), X = Northern Indian Ocean, XI = NW Pacific
NAVAREA_GULF = {"IX", "X", "IX "}


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class Advisory:
    source:     str         # "CMF" | "NGA"
    title:      str
    date:       Optional[str]
    url:        Optional[str]
    summary:    Optional[str]
    fetched_at: str = ""

    def __post_init__(self):
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()

    def is_hormuz_relevant(self) -> bool:
        blob = " ".join(filter(None, [self.title, self.summary])).lower()
        return any(kw in blob for kw in GEO_KEYWORDS)

    def date_iso(self) -> str:
        if not self.date:
            return ""
        try:
            dt = eutils.parsedate_to_datetime(self.date)
            return dt.isoformat()
        except Exception:
            return self.date


# ── CMF RSS ───────────────────────────────────────────────────────────────────

def fetch_cmf(session: requests.Session) -> list[Advisory]:
    advisories = []
    try:
        r = session.get(CMF_FEED, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[CMF] fetch error: {e}", file=sys.stderr)
        return advisories

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        print(f"[CMF] XML parse error: {e}", file=sys.stderr)
        return advisories

    channel = root.find("channel")
    if channel is None:
        return advisories

    NS = {
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc":      "http://purl.org/dc/elements/1.1/",
    }

    for item in channel.findall("item"):
        title_el   = item.find("title")
        link_el    = item.find("link")
        date_el    = item.find("pubDate")
        desc_el    = item.find("description")
        content_el = item.find("content:encoded", NS)

        title   = unescape(title_el.text.strip())  if title_el is not None and title_el.text  else ""
        href    = link_el.text.strip()              if link_el  is not None and link_el.text   else None
        date    = date_el.text.strip()              if date_el  is not None and date_el.text   else None
        raw     = content_el.text or (desc_el.text if desc_el else "")
        # strip HTML tags for summary
        summary = re.sub(r"<[^>]+>", " ", unescape(raw or "")).strip()[:500]

        adv = Advisory(source="CMF", title=title, date=date, url=href, summary=summary)
        advisories.append(adv)

    return advisories


# ── NGA MSI broadcast warnings ───────────────────────────────────────────────

def fetch_nga(session: requests.Session) -> list[Advisory]:
    advisories = []
    try:
        r = session.get(NGA_API, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[NGA] fetch error: {e}", file=sys.stderr)
        return advisories

    items = data.get("broadcast-warn", [])

    for item in items:
        authority = item.get("authority", "")
        text      = item.get("text", "")
        area      = item.get("navArea", "")
        year      = item.get("msgYear", "")
        num       = item.get("msgNumber", "")
        date_raw  = item.get("issueDate", "")
        status    = item.get("status", "")

        # Skip cancelled warnings
        if status == "C" and item.get("cancelDate"):
            continue

        # Build a clean title from first line of text
        first_line = text.split("\n")[0].strip()[:120]
        title = f"NAVAREA {area} {num}/{year}: {first_line}" if num else first_line

        adv = Advisory(
            source="NGA",
            title=title,
            date=date_raw,
            url=None,
            summary=text[:600],
        )
        advisories.append(adv)

    return advisories


# ── orchestrator ─────────────────────────────────────────────────────────────

def fetch_all(
    hormuz_only: bool = True,
    sources: list[str] | None = None,
) -> list[Advisory]:
    if sources is None:
        sources = ["cmf", "nga"]

    session = requests.Session()
    combined: list[Advisory] = []

    if "cmf" in sources:
        combined += fetch_cmf(session)
    if "nga" in sources:
        combined += fetch_nga(session)

    if hormuz_only:
        combined = [a for a in combined if a.is_hormuz_relevant()]

    combined.sort(key=lambda a: a.date_iso(), reverse=True)
    return combined


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(
        description="Hormuz maritime threat tracker — CMF + NGA MSI"
    )
    p.add_argument("--all",     action="store_true", help="Include non-Hormuz items")
    p.add_argument("--sources", default="cmf,nga",   help="Comma-separated: cmf,nga")
    p.add_argument("--json",    action="store_true", help="JSON output")
    p.add_argument("--limit",   type=int, default=20, help="Max items to show (0=all)")
    args = p.parse_args()

    sources = [s.strip().lower() for s in args.sources.split(",")]
    advisories = fetch_all(hormuz_only=not args.all, sources=sources)

    if args.limit:
        advisories = advisories[:args.limit]

    if args.json:
        print(json.dumps([asdict(a) for a in advisories], indent=2))
        return

    if not advisories:
        print("No relevant advisories found.")
        return

    for a in advisories:
        print(f"\n[{a.source}] {a.date or 'n/d'}")
        print(f"  {a.title}")
        if a.url:
            print(f"  {a.url}")
        if a.summary:
            snippet = a.summary[:220].replace("\n", " ").strip()
            print(f"  {snippet}")


# ── MARAD note ────────────────────────────────────────────────────────────────
# MARAD MSCI is behind Akamai (403 to headless requests).
# Programmatic option: subscribe to their GovDelivery email list at
#   https://public.govdelivery.com/accounts/USDOTMARAD/subscriber/new
# then parse incoming MSCI emails with imaplib/email. Filter subject
# lines matching "MSCI.*Gulf|MSCI.*Hormuz|MSCI.*Middle East".
#
# UKMTO is behind Cloudflare JS challenge. No headless workaround without
# Playwright/Selenium. Alternative: register at ukmto.org for broadcast alerts.

if __name__ == "__main__":
    main()
