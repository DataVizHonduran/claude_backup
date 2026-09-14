#!/usr/bin/env python3
"""
FIFA World Cup 2026 Ticket Price Monitor
Scrapes StubHub event pages for WC games at MetLife Stadium (NJ) and
Lincoln Financial Field (PA). Publishes price drops to boquin.xyz.

Prices are extracted from JSON-LD embedded in each event page
(field: offers.lowPrice). Reliable; no selector guesswork.

Usage:
    python3 wc2026_ticket_monitor.py           # fetch all events, store, publish
    python3 wc2026_ticket_monitor.py --dry-run # fetch + print, no DB/publish
    python3 wc2026_ticket_monitor.py --status  # print last 24h prices from DB
    python3 wc2026_ticket_monitor.py --refresh # re-discover events from city pages
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
DROP_THRESHOLD       = 0.20   # alert on >=20% drop from 24h rolling high
ALERT_COOLDOWN_HOURS = 6      # suppress repeat alerts within 6h for same event
PAGE_TIMEOUT_MS      = 60_000
PAGE_SETTLE_MS       = 2_000

SITE_REPO   = Path("/Users/macproajb/claude_projects/boquin.github.io")
DB_PATH     = SITE_REPO / "data" / "wc2026_tickets.db"
REPORT_DIR  = SITE_REPO / "reports" / "wc2026-tickets"
EVENTS_FILE = Path(__file__).parent / "data" / "wc2026_events.json"
LOG         = "[WC2026]"

# City-page URLs used for event discovery (--refresh)
CITY_PAGES = [
    ("https://www.stubhub.com/world-cup-tickets/grouping/45410/east-rutherford-city/19",
     "MetLife Stadium, East Rutherford, NJ"),
    ("https://www.stubhub.com/world-cup-tickets/grouping/45410/philadelphia-city/5418",
     "Lincoln Financial Field, Philadelphia, PA"),
]

# Seed event list — all known WC games at MetLife + Lincoln Financial.
# The monitor bootstraps from this; --refresh re-discovers via city pages.
SEED_EVENTS = [
    # MetLife Stadium, East Rutherford NJ
    {"url": "https://www.stubhub.com/world-cup-east-rutherford-tickets-6-13-2026/event/153021803/",
     "name": "Brazil vs Morocco (Group C, Match 7)",
     "venue": "MetLife Stadium, East Rutherford NJ", "date": "2026-06-13"},
    {"url": "https://www.stubhub.com/world-cup-east-rutherford-tickets-6-16-2026/event/153022598/",
     "name": "France vs Senegal (Group I, Match 17)",
     "venue": "MetLife Stadium, East Rutherford NJ", "date": "2026-06-16"},
    {"url": "https://www.stubhub.com/world-cup-east-rutherford-tickets-6-22-2026/event/153023354/",
     "name": "Norway vs Senegal (Group I, Match 41)",
     "venue": "MetLife Stadium, East Rutherford NJ", "date": "2026-06-22"},
    {"url": "https://www.stubhub.com/world-cup-east-rutherford-tickets-6-25-2026/event/153023689/",
     "name": "Ecuador vs Germany (Group E, Match 56)",
     "venue": "MetLife Stadium, East Rutherford NJ", "date": "2026-06-25"},
    {"url": "https://www.stubhub.com/world-cup-east-rutherford-tickets-6-27-2026/event/153023828/",
     "name": "Panama vs England (Group L, Match 67)",
     "venue": "MetLife Stadium, East Rutherford NJ", "date": "2026-06-27"},
    {"url": "https://www.stubhub.com/world-cup-east-rutherford-tickets-6-30-2026/event/153023840/",
     "name": "TBD vs TBD (Round of 32, Match 77)",
     "venue": "MetLife Stadium, East Rutherford NJ", "date": "2026-06-30"},
    {"url": "https://www.stubhub.com/world-cup-east-rutherford-tickets-7-19-2026/event/153020449/",
     "name": "World Cup Final (Match 104)",
     "venue": "MetLife Stadium, East Rutherford NJ", "date": "2026-07-19"},
    # Lincoln Financial Field, Philadelphia PA
    {"url": "https://www.stubhub.com/world-cup-philadelphia-tickets-6-14-2026/event/153022356/",
     "name": "Côte d'Ivoire vs Ecuador (Group E, Match 9)",
     "venue": "Lincoln Financial Field, Philadelphia PA", "date": "2026-06-14"},
    {"url": "https://www.stubhub.com/world-cup-philadelphia-tickets-6-19-2026/event/153022742/",
     "name": "Brazil vs Haiti (Group C, Match 29)",
     "venue": "Lincoln Financial Field, Philadelphia PA", "date": "2026-06-19"},
    {"url": "https://www.stubhub.com/world-cup-philadelphia-tickets-6-22-2026/event/153023094/",
     "name": "France vs Iraq (Group I, Match 42)",
     "venue": "Lincoln Financial Field, Philadelphia PA", "date": "2026-06-22"},
    {"url": "https://www.stubhub.com/world-cup-philadelphia-tickets-6-25-2026/event/153023579/",
     "name": "Curaçao vs Côte d'Ivoire (Group E, Match 55)",
     "venue": "Lincoln Financial Field, Philadelphia PA", "date": "2026-06-25"},
    {"url": "https://www.stubhub.com/world-cup-philadelphia-tickets-6-27-2026/event/153023766/",
     "name": "Croatia vs Ghana (Group L, Match 68)",
     "venue": "Lincoln Financial Field, Philadelphia PA", "date": "2026-06-27"},
    {"url": "https://www.stubhub.com/world-cup-philadelphia-tickets-7-4-2026/event/153023863/",
     "name": "TBD vs TBD (Round of 16, Match 89)",
     "venue": "Lincoln Financial Field, Philadelphia PA", "date": "2026-07-04"},
]
# ---------------------------------------------------------------------------


def load_events() -> list[dict]:
    if EVENTS_FILE.exists():
        return json.loads(EVENTS_FILE.read_text())
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps(SEED_EVENTS, indent=2, ensure_ascii=False))
    return SEED_EVENTS


def discover_events(page) -> list[dict]:
    """Scrape StubHub city pages for event URLs. Merges with existing list."""
    found: dict[str, dict] = {e["url"]: e for e in load_events()}

    for city_url, default_venue in CITY_PAGES:
        print(f"{LOG} Discovering events at {default_venue}...")
        try:
            page.goto(city_url, wait_until="networkidle", timeout=45_000)
        except PWTimeout:
            print(f"{LOG}   Timeout on city page — skipping.")
            continue

        links = page.query_selector_all("a[href*='/event/']")
        for a in links:
            href = (a.get_attribute("href") or "").split("?")[0]
            m = re.search(r"/event/(\d+)/", href)
            if not m:
                continue
            full = href if href.startswith("http") else f"https://www.stubhub.com{href}"
            if full in found:
                continue
            # Filter: only MetLife or Lincoln Financial events
            txt = a.inner_text().lower()
            if "east rutherford" in txt or "metlife" in txt:
                venue = "MetLife Stadium, East Rutherford NJ"
            elif "philadelphia" in txt or "lincoln financial" in txt:
                venue = "Lincoln Financial Field, Philadelphia PA"
            else:
                continue
            title_m = re.search(r"((?:\w[\w\s'éÉ&]+?)\s+vs\.?\s+\S+)", a.inner_text())
            name = title_m.group(0).strip() if title_m else f"WC2026 Event {m.group(1)}"
            date_m = re.search(r"-(\d+-\d+-\d+)-\d+", href.replace("tickets-", ""))
            date = ""
            if date_m:
                parts = date_m.group(1).split("-")
                date = f"2026-{parts[0].zfill(2)}-{parts[1].zfill(2)}" if len(parts) == 2 else ""
            found[full] = {"url": full, "name": name, "venue": venue, "date": date}
            print(f"{LOG}   + Discovered: {name}")

    events = list(found.values())
    EVENTS_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False))
    print(f"{LOG} Event list: {len(events)} total.")
    return events


def _make_browser_context(pw):
    return pw.chromium.launch(headless=True).new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )


# ─── DB ────────────────────────────────────────────────────────────────────

def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id          INTEGER PRIMARY KEY,
            event_url   TEXT NOT NULL,
            event_name  TEXT NOT NULL,
            venue       TEXT NOT NULL,
            game_date   TEXT,
            min_price   REAL,
            captured_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_url_ts
            ON price_snapshots(event_url, captured_at);
        CREATE TABLE IF NOT EXISTS alerts_sent (
            id           INTEGER PRIMARY KEY,
            event_url    TEXT NOT NULL,
            drop_pct     REAL,
            triggered_at TEXT NOT NULL
        );
    """)
    conn.commit()
    return conn


def store_snapshot(conn: sqlite3.Connection, ev: dict, price: float):
    conn.execute(
        "INSERT INTO price_snapshots "
        "(event_url, event_name, venue, game_date, min_price, captured_at) "
        "VALUES (?,?,?,?,?,?)",
        (ev["url"], ev["name"], ev["venue"], ev.get("date", ""),
         price, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# ─── PRICE FETCH ───────────────────────────────────────────────────────────

def fetch_price(page, ev: dict) -> float | None:
    """Navigate to StubHub event page, return JSON-LD lowPrice."""
    try:
        page.goto(ev["url"], wait_until="load", timeout=PAGE_TIMEOUT_MS)
        page.wait_for_timeout(PAGE_SETTLE_MS)
        scripts = page.query_selector_all("script[type='application/ld+json']")
        for sc in scripts:
            try:
                d = json.loads(sc.inner_text())
                if d.get("@type") == "SportsEvent":
                    offers = d.get("offers", {})
                    price = offers.get("lowPrice")
                    if price:
                        print(f"{LOG}   [json-ld] ${float(price):,.2f}")
                        return float(price)
            except (json.JSONDecodeError, ValueError):
                continue
        # Fallback: find all $X,XXX.XX patterns in body, take the smallest >= $50
        body = page.inner_text("body")
        candidates = [
            float(m.replace(",", ""))
            for m in re.findall(r"\$([\d]{2,5}(?:,\d{3})*(?:\.\d{2})?)", body)
        ]
        candidates = [p for p in candidates if p >= 50]
        if candidates:
            price = min(candidates)
            print(f"{LOG}   [fallback] ${price:,.2f} (from {len(candidates)} candidates)")
            return price
        print(f"{LOG}   No price found in JSON-LD or body.")
    except Exception as e:
        print(f"{LOG}   Error fetching {ev['name']}: {e}")
    return None


# ─── DROP DETECTION ────────────────────────────────────────────────────────

def check_drops(conn: sqlite3.Connection) -> list[dict]:
    cutoff_24h   = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cutoff_cool  = (datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_HOURS)).isoformat()

    rows = conn.execute("""
        SELECT event_url, event_name, venue,
               MAX(min_price) AS high_24h
        FROM price_snapshots
        WHERE captured_at >= ? AND min_price IS NOT NULL
        GROUP BY event_url
    """, (cutoff_24h,)).fetchall()

    alerts = []
    for event_url, event_name, venue, high_24h in rows:
        row = conn.execute("""
            SELECT min_price FROM price_snapshots
            WHERE event_url=? AND min_price IS NOT NULL
            ORDER BY captured_at DESC LIMIT 1
        """, (event_url,)).fetchone()
        if not row or not high_24h:
            continue
        current = row[0]
        drop = (high_24h - current) / high_24h
        if drop < DROP_THRESHOLD:
            continue
        recent = conn.execute("""
            SELECT 1 FROM alerts_sent
            WHERE event_url=? AND triggered_at>=?
        """, (event_url, cutoff_cool)).fetchone()
        if recent:
            continue
        alerts.append({"event_url": event_url, "event_name": event_name,
                        "venue": venue, "high_24h": high_24h,
                        "current_price": current, "drop_pct": drop})
    return alerts


def record_alert(conn: sqlite3.Connection, alert: dict):
    conn.execute(
        "INSERT INTO alerts_sent (event_url, drop_pct, triggered_at) VALUES (?,?,?)",
        (alert["event_url"], alert["drop_pct"],
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# ─── SITE PUBLISH ──────────────────────────────────────────────────────────

def _row_class(drop_pct: float | None) -> str:
    if drop_pct is None:
        return ""
    if drop_pct >= 0.20:
        return ' class="drop-major"'
    if drop_pct >= 0.10:
        return ' class="drop-minor"'
    return ""


def generate_html(conn: sqlite3.Connection, alerts: list[dict]) -> str:
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    # Latest snapshot per event (no time cutoff) + 24h high for drop display
    rows = conn.execute("""
        SELECT p.event_url, p.event_name, p.venue, p.game_date, p.min_price, p.captured_at,
               (SELECT MAX(min_price) FROM price_snapshots p2
                WHERE p2.event_url=p.event_url AND p2.captured_at >= ?) AS high_24h
        FROM price_snapshots p
        WHERE p.id IN (
            SELECT MAX(id) FROM price_snapshots
            WHERE min_price IS NOT NULL
            GROUP BY event_url
        )
        ORDER BY p.game_date, p.event_url
    """, (cutoff_24h,)).fetchall()

    seen = set()
    table_rows = []
    for url, name, venue, gdate, price, ts, high in rows:
        key = (url,)
        if key in seen:
            continue
        seen.add(key)
        drop_pct = (high - price) / high if (high and price and high > price) else None
        drop_str = f"{drop_pct * 100:.1f}%" if drop_pct is not None else "—"
        high_str = f"${high:,.0f}" if high else "—"
        rc = _row_class(drop_pct)
        badge = " 🔔" if any(a["event_url"] == url for a in alerts) else ""
        table_rows.append(
            f'<tr{rc}>'
            f'<td><a href="{url}" target="_blank">{name}{badge}</a></td>'
            f'<td>{venue.split(",")[0]}</td>'
            f'<td>{gdate or "—"}</td>'
            f'<td>${price:,.0f}</td>'
            f'<td>{high_str}</td>'
            f'<td>{drop_str}</td>'
            f'<td>{ts[5:16]} UTC</td>'
            f'</tr>'
        )

    alert_html = ""
    if alerts:
        items = "".join(
            f'<li><strong>{a["event_name"]}</strong> — '
            f'${a["high_24h"]:,.0f} → ${a["current_price"]:,.0f} '
            f'({a["drop_pct"]*100:.1f}% drop) '
            f'<a href="{a["event_url"]}" target="_blank">StubHub ↗</a></li>'
            for a in alerts
        )
        alert_html = f'<div class="alert-box"><h2>🔔 Price Drops Detected</h2><ul>{items}</ul></div>'

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    table_body = "\n".join(table_rows) if table_rows else '<tr><td colspan="7">No data in last 24h.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WC2026 Ticket Prices — boquin.xyz</title>
<link rel="stylesheet" href="../../styles.css">
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th {{ background: #111; color: #fff; padding: 0.5rem 0.75rem; text-align: left; }}
  td {{ padding: 0.45rem 0.75rem; border-bottom: 1px solid #e5e5e5; }}
  tr:hover td {{ background: #f8f8f8; }}
  tr.drop-major td {{ background: #fff0f0; }}
  tr.drop-minor td {{ background: #fffbe6; }}
  .alert-box {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 1rem 1.25rem; margin-bottom: 1.5rem; }}
  .alert-box h2 {{ margin: 0 0 0.5rem; font-size: 1rem; }}
  .alert-box ul {{ margin: 0; padding-left: 1.25rem; }}
  a {{ color: #1a0dab; }}
  .back {{ font-size: 0.85rem; margin-bottom: 1rem; display: block; }}
</style>
</head>
<body>
<a class="back" href="../../index.html">← boquin.xyz</a>
<h1>⚽ WC2026 Ticket Price Monitor</h1>
<p class="meta">StubHub min prices — MetLife (NJ) &amp; Lincoln Financial (PA) · Updated: {updated} · Threshold: ≥20% drop alerts</p>
{alert_html}
<table>
<thead><tr>
  <th>Match</th><th>Venue</th><th>Date</th>
  <th>Now</th><th>24h High</th><th>Drop</th><th>Captured</th>
</tr></thead>
<tbody>
{table_body}
</tbody>
</table>
</body>
</html>"""


def publish_to_site(conn: sqlite3.Connection, alerts: list[dict], dry_run: bool):
    for alert in alerts:
        pct = alert["drop_pct"] * 100
        print(f"{LOG} ALERT — {alert['event_name']}")
        print(f"  ${alert['high_24h']:,.0f} → ${alert['current_price']:,.0f} ({pct:.1f}% drop)")

    html = generate_html(conn, alerts)

    if dry_run:
        print(f"{LOG} [dry-run] HTML generated ({len(html):,} chars) — not writing to site.")
        return

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"{LOG} Written to {REPORT_DIR / 'index.html'}")

    try:
        subprocess.run(["git", "pull", "--rebase"], cwd=SITE_REPO, check=True, capture_output=True)
        subprocess.run(["git", "add",
                        "data/wc2026_tickets.db",
                        "reports/wc2026-tickets/index.html"],
                       cwd=SITE_REPO, check=True, capture_output=True)
        msg = f"wc2026: price update {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        if alerts:
            msg += f" ({len(alerts)} drop alert{'s' if len(alerts) > 1 else ''})"
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=SITE_REPO)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", msg], cwd=SITE_REPO, check=True, capture_output=True)
            subprocess.run(["git", "push"], cwd=SITE_REPO, check=True, capture_output=True)
            print(f"{LOG} Pushed to boquin.xyz — reports/wc2026-tickets/index.html")
        else:
            print(f"{LOG} No changes to commit.")
    except subprocess.CalledProcessError as e:
        print(f"{LOG} Git error: {e.stderr.decode()[:300] if e.stderr else e}")


# ─── STATUS ────────────────────────────────────────────────────────────────

def print_status(conn: sqlite3.Connection):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = conn.execute("""
        SELECT p.event_name, p.venue, p.game_date, p.min_price, p.captured_at,
               (SELECT MAX(min_price) FROM price_snapshots p2
                WHERE p2.event_url=p.event_url AND p2.captured_at >= ?) AS high_24h
        FROM price_snapshots p
        WHERE p.captured_at >= ? AND p.min_price IS NOT NULL
        ORDER BY p.event_url, p.captured_at DESC
    """, (cutoff, cutoff)).fetchall()

    if not rows:
        print("No price data in the last 24 hours.")
        return

    seen = set()
    print(f"\n{'Game':<48} {'Date':<12} {'Now $':>8} {'24hHigh':>8} {'Drop%':>7}  Captured")
    print("-" * 110)
    for name, venue, gdate, price, ts, high in rows:
        key = (name, venue)
        if key in seen:
            continue
        seen.add(key)
        drop_str = f"{(high - price) / high * 100:.1f}%" if high and price else "—"
        short_name = f"{name[:35]} ({venue.split(',')[0]})"
        print(f"{short_name:<48} {(gdate or ''):<12} {(price or 0):>8,.0f} {(high or 0):>8,.0f} {drop_str:>7}  {ts[:19]}")


# ─── MAIN ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FIFA WC 2026 ticket price monitor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch prices, print, skip DB writes and Telegram alerts")
    parser.add_argument("--status", action="store_true",
                        help="Print last 24h price table from DB (no fetch)")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-scrape StubHub city pages to update event list")
    args = parser.parse_args()

    conn = open_db()

    if args.status:
        print_status(conn)
        return

    today = datetime.now(timezone.utc).date()

    with sync_playwright() as pw:
        ctx = _make_browser_context(pw)
        page = ctx.new_page()

        # Event discovery
        if args.refresh or not EVENTS_FILE.exists():
            events = discover_events(page)
        else:
            events = load_events()

        # Filter to future/today events only (no point fetching past games)
        events = [e for e in events
                  if not e.get("date") or e["date"] >= str(today)]
        print(f"{LOG} Monitoring {len(events)} upcoming events.")

        # Fetch prices
        snapshots = []
        for ev in events:
            print(f"{LOG} Fetching: {ev['name']} ...")
            price = fetch_price(page, ev)
            if price is None:
                print(f"{LOG}   No price found — skipping.")
                continue
            print(f"{LOG}   Min price: ${price:,.2f}")
            snapshots.append((ev, price))

        ctx.browser.close()

    if not snapshots:
        print(f"{LOG} No prices retrieved.")
        return

    if not args.dry_run:
        for ev, price in snapshots:
            store_snapshot(conn, ev, price)
        print(f"{LOG} Stored {len(snapshots)} snapshots.")

        drops = check_drops(conn)
        if not drops:
            print(f"{LOG} No significant drops detected.")
        publish_to_site(conn, drops, dry_run=False)
        for alert in drops:
            record_alert(conn, alert)
    else:
        print(f"\n{LOG} [dry-run] Prices fetched (not stored):")
        for ev, price in snapshots:
            print(f"  ${price:>9,.2f}  {ev['name']}  ({ev['venue']})")
        drops = check_drops(conn)
        publish_to_site(conn, drops, dry_run=True)


if __name__ == "__main__":
    main()
