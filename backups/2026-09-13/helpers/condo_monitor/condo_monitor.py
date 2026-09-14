#!/usr/bin/env python3
"""
Manhattan Condo Monitor — UWS/UES, 2BR, new-build/recent-conversion condos, <=$1.7M
Hits CityRealty's search JSON API directly (session + CSRF cookie, no browser needed).
StreetEasy/Zillow are ruled out: both sit behind an active PerimeterX "press & hold"
bot challenge that blocked headless Playwright outright.

Usage:
    python3 condo_monitor.py           # fetch listings, store, publish
    python3 condo_monitor.py --dry-run # fetch + print, no DB/publish
    python3 condo_monitor.py --status  # print current matches from DB
"""

import argparse
import copy
import json
import sqlite3
import subprocess
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
PRICE_MAX      = 1_700_000
BEDROOM_SPECS  = [(1, 11), (2, 12)]   # (bedroom count, "N Bedrooms" filter option value)
BUILDING_TYPE  = "condo"
NEW_BUILD_CUTOFF_YEAR = datetime.now().year - 20  # new dev or converted within ~20yrs
REGIONS        = ["Upper West Side", "Upper East Side"]
ROWS_PER_PAGE  = 52

SITE_REPO   = Path("/Users/macproajb/claude_projects/boquin.github.io")
DB_PATH     = SITE_REPO / "data" / "condo_listings.db"
REPORT_DIR  = SITE_REPO / "reports" / "manhattan-condo-monitor"
TEMPLATE_FILE = Path(__file__).parent / "data" / "city_search_template.json"
RENTAL_TEMPLATE_FILE = Path(__file__).parent / "data" / "city_rental_template.json"
LOG = "[CONDO]"

# Cap-rate guesstimate assumptions (see boquin.xyz report footnote):
# NOI = (region median rent $/sqft/yr * sqft) - actual common charges - actual
# property tax - 5% vacancy - 8% mgmt fee. Tax blank on feed -> $1.50/sqft/mo fallback.
VACANCY_RATE     = 0.05
MGMT_FEE_RATE    = 0.08
TAX_FALLBACK_PSF_MO = 1.50

BASE = "https://www.cityrealty.com"
SEARCH_PAGE_URL = f"{BASE}/nyc/apartments-for-sale/search-new"
RENTAL_SEARCH_PAGE_URL = f"{BASE}/nyc/apartments-for-rent/search-new"
API_URL = (
    f"{BASE}/rpc/search/get-sale-listings"
    "?f%5B%5D=priceRangeSale&f%5B%5D=location&f%5B%5D=bedroomFullMulti"
    "&f%5B%5D=saleBuildingTypeMulti&f%5B%5D=doorman&f%5B%5D=amenities"
    "&f%5B%5D=inContract&f%5B%5D=dateListed&f%5B%5D=priceChange"
    "&f%5B%5D=searchTermListings&f%5B%5D=subHoods&f%5B%5D=newDevelopmentsOnly"
    "&s%5B%5D=salePrice&s%5B%5D=dateListed&s%5B%5D=ppsqft&s%5B%5D=registration"
    "&show_vow=1&type=json&uniqueid=condo_monitor"
)
RENTAL_API_URL = (
    f"{BASE}/rpc/search/get-rental-listings"
    "?f%5B%5D=priceRangeRent&f%5B%5D=location&f%5B%5D=bedroomFullMulti"
    "&f%5B%5D=rentalBuildingTypeMulti&f%5B%5D=doorman&f%5B%5D=amenities"
    "&f%5B%5D=dateListed&f%5B%5D=priceChange&f%5B%5D=searchTermListings&f%5B%5D=subHoods"
    "&s%5B%5D=rentPrice&s%5B%5D=dateListed&s%5B%5D=ppsqft&s%5B%5D=registration"
    "&show_vow=1&type=json&uniqueid=condo_monitor_rent"
)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


# ─── SESSION / API ──────────────────────────────────────────────────────────

def open_session() -> tuple[requests.Session, str]:
    """Bootstrap a session + CSRF token by loading the search page once."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.get(SEARCH_PAGE_URL, timeout=30)
    csrf = urllib.parse.unquote(s.cookies.get("CSRF-Token", ""))
    return s, csrf


def build_payload(region: str, page: int, bedroom_value: int) -> dict:
    template = json.loads(TEMPLATE_FILE.read_text())
    for f in template["filters"]:
        if f["name"] == "hoods":
            for grp in f["options"]:
                for h in grp["hoods"]:
                    h["active"] = 1 if grp["name"] == region else 0
        elif f["name"] == "bedrooms":
            for o in f["options"]:
                o["active"] = (o["value"] == bedroom_value)
        elif f["name"] == "building type":
            for o in f["options"]:
                o["active"] = (o["value"] == BUILDING_TYPE)
    template["pagination"] = {"total": 2500, "rowsPerPage": ROWS_PER_PAGE, "currentPage": str(page)}
    return template


def fetch_region_listings(session: requests.Session, csrf: str, region: str, bedroom_value: int) -> list[dict]:
    headers = {
        "Content-Type": "application/json",
        "Referer": f"{BASE}/nyc/apartments-for-sale/search-results",
        "Origin": BASE,
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": csrf,
    }
    all_items = []
    page = 1
    while True:
        payload = build_payload(region, page, bedroom_value)
        r = session.post(f"{API_URL}&page={page}", headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        all_items.extend(items)
        total = data.get("stats", {}).get("cnt", 0)
        if len(all_items) >= total or not items:
            break
        page += 1
    return all_items


def filter_new_build(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        if it.get("price_raw", 0) > PRICE_MAX:
            continue
        year = it.get("built_converted") or it.get("yearbuilt") or 0
        if year < NEW_BUILD_CUTOFF_YEAR:
            continue
        out.append(it)
    return out


# ─── RENTAL COMPS / CAP RATE ────────────────────────────────────────────────

def fetch_region_median_rent_psf(session: requests.Session, csrf: str, region: str) -> float | None:
    """Median annual $/sqft rent across 2BR+ condo rentals in the region — used as
    the market-rent proxy for cap-rate NOI. Returns None if no comps found."""
    template = json.loads(RENTAL_TEMPLATE_FILE.read_text())
    for f in template["filters"]:
        if f["name"] == "hoods":
            for grp in f["options"]:
                for h in grp["hoods"]:
                    h["active"] = 1 if grp["name"] == region else 0
        elif f["name"] == "building type":
            for o in f["options"]:
                o["active"] = (o["value"] == BUILDING_TYPE)
    template["pagination"] = {"total": 2500, "rowsPerPage": ROWS_PER_PAGE, "currentPage": "1"}

    headers = {
        "Content-Type": "application/json",
        "Referer": f"{BASE}/nyc/apartments-for-rent/search-results",
        "Origin": BASE,
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": csrf,
    }
    r = session.post(f"{RENTAL_API_URL}&page=1", headers=headers, json=template, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    ppsqfts = sorted(it["ppsqft_raw"] for it in items if it.get("ppsqft_raw") and it.get("sqft_raw"))
    if not ppsqfts:
        return None
    return ppsqfts[len(ppsqfts) // 2]


def _parse_money(s) -> float | None:
    if not s:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    return float(s) if s else None


def compute_cap_rate(it: dict, region_median_rent_psf: float | None) -> dict:
    """Attach guesstimated maintenance/tax/gross_rent/noi/cap_rate to a sale item.
    Leaves gross_rent/noi/cap_rate as None if there's no rent comp to work from."""
    sqft = it.get("sqft_raw") or 0
    maint = _parse_money(it.get("monthlyMaintenanceOrCharges")) or 0
    tax = _parse_money(it.get("monthlyTaxes"))
    if tax is None:
        tax = TAX_FALLBACK_PSF_MO * sqft
    it["_maint_monthly"] = maint
    it["_tax_monthly"] = tax

    if not region_median_rent_psf or not sqft or not it.get("price_raw"):
        it["_gross_rent_annual"] = None
        it["_noi_annual"] = None
        it["_cap_rate"] = None
        return it

    gross_rent = region_median_rent_psf * sqft
    annual_carrying = (maint + tax) * 12
    noi = gross_rent - annual_carrying - (VACANCY_RATE * gross_rent) - (MGMT_FEE_RATE * gross_rent)
    it["_gross_rent_annual"] = gross_rent
    it["_noi_annual"] = noi
    it["_cap_rate"] = noi / it["price_raw"]
    return it


# ─── DB ────────────────────────────────────────────────────────────────────

def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS listing_snapshots (
            id            INTEGER PRIMARY KEY,
            listing_id    INTEGER NOT NULL,
            address       TEXT NOT NULL,
            neighborhood  TEXT,
            price         REAL,
            beds          TEXT,
            baths         TEXT,
            sqft          REAL,
            built_year    INTEGER,
            url           TEXT,
            captured_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_listing_ts
            ON listing_snapshots(listing_id, captured_at);
        CREATE TABLE IF NOT EXISTS runs (captured_at TEXT PRIMARY KEY);
    """)
    for col, coltype in [("maintenance", "REAL"), ("tax", "REAL"),
                          ("gross_rent", "REAL"), ("noi", "REAL"), ("cap_rate", "REAL"),
                          ("bedroom_count", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE listing_snapshots ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    return conn


def store_snapshot(conn: sqlite3.Connection, it: dict, ts: str, bedroom_count: int):
    conn.execute(
        "INSERT INTO listing_snapshots "
        "(listing_id, address, neighborhood, price, beds, baths, sqft, built_year, url, captured_at, "
        "maintenance, tax, gross_rent, noi, cap_rate, bedroom_count) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (it["listing_id"], it["display_name"], it.get("hood", ""), it["price_raw"],
         it.get("display_bedrooms", ""), it.get("display_bathrooms", ""),
         it.get("sqft_raw"), it.get("built_converted") or it.get("yearbuilt"),
         BASE + it["url_listing"], ts,
         it.get("_maint_monthly"), it.get("_tax_monthly"), it.get("_gross_rent_annual"),
         it.get("_noi_annual"), it.get("_cap_rate"), bedroom_count),
    )


def detect_changes(conn: sqlite3.Connection, ts: str) -> tuple[list[dict], list[dict]]:
    """Compare this run's snapshot (captured_at=ts) against the prior run. Returns (new, price_cuts)."""
    prior_ts_row = conn.execute(
        "SELECT DISTINCT captured_at FROM listing_snapshots WHERE captured_at < ? "
        "ORDER BY captured_at DESC LIMIT 1", (ts,)
    ).fetchone()
    new_listings, price_cuts = [], []

    current = conn.execute(
        "SELECT listing_id, address, price, url FROM listing_snapshots WHERE captured_at = ?", (ts,)
    ).fetchall()

    prior = {}
    if prior_ts_row:
        prior_ts = prior_ts_row[0]
        prior = {row[0]: row for row in conn.execute(
            "SELECT listing_id, address, price, url FROM listing_snapshots WHERE captured_at = ?", (prior_ts,)
        ).fetchall()}
    # No prior snapshot with any matches (first run to find data) -> everything
    # currently on the board counts as new, so the first real digest isn't empty.

    for listing_id, address, price, url in current:
        if listing_id not in prior:
            new_listings.append({"listing_id": listing_id, "address": address, "price": price, "url": url})
        elif price < prior[listing_id][2]:
            price_cuts.append({"listing_id": listing_id, "address": address,
                                "prior_price": prior[listing_id][2], "price": price, "url": url})
    return new_listings, price_cuts


# ─── STATUS ────────────────────────────────────────────────────────────────

def print_status(conn: sqlite3.Connection):
    latest_ts_row = conn.execute("SELECT MAX(captured_at) FROM runs").fetchone()
    if not latest_ts_row or not latest_ts_row[0]:
        print("No data yet.")
        return
    ts = latest_ts_row[0]
    rows = conn.execute(
        "SELECT address, neighborhood, price, beds, sqft, built_year, cap_rate, url, bedroom_count "
        "FROM listing_snapshots WHERE captured_at = ? ORDER BY bedroom_count DESC, cap_rate DESC", (ts,)
    ).fetchall()
    print(f"\n{len(rows)} matches as of {ts}\n")
    for address, hood, price, beds, sqft, year, cap_rate, url, bedroom_count in rows:
        sqft_str = f"{sqft:,.0f} ft2" if sqft else "—"
        cap_str = f"{cap_rate*100:.2f}%" if cap_rate is not None else "—"
        print(f"${price:>10,.0f}  {beds:<12} {sqft_str:<10} built/conv {year}  cap {cap_str:>6}  {address} ({hood})")
        print(f"            {url}")


# ─── SITE PUBLISH ──────────────────────────────────────────────────────────

def _render_table(rows, new_ids: set, cut_ids: set) -> str:
    table_rows = []
    for listing_id, address, hood, price, beds, baths, sqft, year, cap_rate, url in rows:
        badge = ""
        if listing_id in new_ids:
            badge += " 🆕"
        if listing_id in cut_ids:
            badge += " 🔻"
        sqft_str = f"{sqft:,.0f}" if sqft else "—"
        cap_str = f"{cap_rate*100:.2f}%" if cap_rate is not None else "—"
        table_rows.append(
            f"<tr><td><a href=\"{url}\" target=\"_blank\">{address}{badge}</a></td>"
            f"<td>{hood}</td><td>${price:,.0f}</td><td>{beds}</td><td>{baths}</td>"
            f"<td>{sqft_str}</td><td>{year}</td><td>{cap_str}</td></tr>"
        )
    table_body = "\n".join(table_rows) if table_rows else '<tr><td colspan="7">No matches.</td></tr>'
    return f"""<table>
<thead><tr><th>Address</th><th>Neighborhood</th><th>Price</th><th>Beds</th><th>Baths</th><th>Sqft</th><th>Built/Converted</th><th>Cap Rate</th></tr></thead>
<tbody>
{table_body}
</tbody>
</table>"""


def generate_html(conn: sqlite3.Connection, new_listings: list[dict], price_cuts: list[dict]) -> str:
    latest_ts = conn.execute("SELECT MAX(captured_at) FROM runs").fetchone()[0]
    all_rows = conn.execute(
        "SELECT listing_id, address, neighborhood, price, beds, baths, sqft, built_year, cap_rate, url, bedroom_count "
        "FROM listing_snapshots WHERE captured_at = ? ORDER BY cap_rate DESC", (latest_ts,)
    ).fetchall()

    new_ids = {n["listing_id"] for n in new_listings}
    cut_ids = {c["listing_id"] for c in price_cuts}

    sections = []
    for count, label in [(2, "2 Bedroom"), (1, "1 Bedroom")]:
        rows = [r[:-1] for r in all_rows if r[-1] == count]
        sections.append(f"<h2>{label}</h2>\n{_render_table(rows, new_ids, cut_ids)}")
    tables_html = "\n".join(sections)

    alert_html = ""
    if new_listings or price_cuts:
        items = "".join(
            f'<li>🆕 <strong>{n["address"]}</strong> — ${n["price"]:,.0f} '
            f'<a href="{n["url"]}" target="_blank">View ↗</a></li>' for n in new_listings
        ) + "".join(
            f'<li>🔻 <strong>{c["address"]}</strong> — '
            f'${c["prior_price"]:,.0f} → ${c["price"]:,.0f} '
            f'<a href="{c["url"]}" target="_blank">View ↗</a></li>' for c in price_cuts
        )
        alert_html = f'<div class="alert-box"><h2>This Week</h2><ul>{items}</ul></div>'

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manhattan Condo Monitor — boquin.xyz</title>
<link rel="stylesheet" href="../../styles.css">
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  h2 {{ font-size: 1.1rem; margin: 2rem 0 0.5rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th {{ background: #111; color: #fff; padding: 0.5rem 0.75rem; text-align: left; }}
  td {{ padding: 0.45rem 0.75rem; border-bottom: 1px solid #e5e5e5; }}
  tr:hover td {{ background: #f8f8f8; }}
  .alert-box {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 1rem 1.25rem; margin-bottom: 1.5rem; }}
  .alert-box h2 {{ margin: 0 0 0.5rem; font-size: 1rem; }}
  .alert-box ul {{ margin: 0; padding-left: 1.25rem; }}
  a {{ color: #1a0dab; }}
  .back {{ font-size: 0.85rem; margin-bottom: 1rem; display: block; }}
</style>
</head>
<body>
<a class="back" href="../../index.html">← boquin.xyz</a>
<h1>🏢 Manhattan Condo Monitor</h1>
<p class="meta">UWS &amp; UES · 1BR &amp; 2BR condos, new development or converted since {NEW_BUILD_CUTOFF_YEAR} · ≤${PRICE_MAX:,.0f} · Source: CityRealty · Updated: {updated}</p>
{alert_html}
{tables_html}
<p class="meta">Cap rate is a guesstimate, not an appraisal: NOI = (neighborhood median asking-rent $/sqft × unit sqft) − actual common charges − actual property tax (${TAX_FALLBACK_PSF_MO:.2f}/sqft/mo assumed where the feed has no tax figure) − {VACANCY_RATE*100:.0f}% vacancy − {MGMT_FEE_RATE*100:.0f}% management fee, divided by price. Rent comps: live condo rental listings in the same neighborhood.</p>
</body>
</html>"""


def publish_to_site(conn: sqlite3.Connection, new_listings: list[dict], price_cuts: list[dict], dry_run: bool):
    for n in new_listings:
        print(f"{LOG} NEW — {n['address']} ${n['price']:,.0f}")
    for c in price_cuts:
        print(f"{LOG} PRICE CUT — {c['address']} ${c['prior_price']:,.0f} -> ${c['price']:,.0f}")

    html = generate_html(conn, new_listings, price_cuts)

    if dry_run:
        print(f"{LOG} [dry-run] HTML generated ({len(html):,} chars) — not writing to site.")
        return

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"{LOG} Written to {REPORT_DIR / 'index.html'}")

    try:
        subprocess.run(["git", "add", "data/condo_listings.db", "reports/manhattan-condo-monitor/index.html"],
                        cwd=SITE_REPO, check=True, capture_output=True)
        msg = f"condo monitor: update {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        if new_listings or price_cuts:
            msg += f" ({len(new_listings)} new, {len(price_cuts)} price cuts)"
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=SITE_REPO)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", msg], cwd=SITE_REPO, check=True, capture_output=True)
            subprocess.run(["git", "push"], cwd=SITE_REPO, check=True, capture_output=True)
            print(f"{LOG} Pushed to boquin.xyz — reports/manhattan-condo-monitor/index.html")
        else:
            print(f"{LOG} No changes to commit.")
    except subprocess.CalledProcessError as e:
        print(f"{LOG} Git error: {e.stderr.decode()[:300] if e.stderr else e}")


# ─── MAIN ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Manhattan condo monitor (UWS/UES, 2BR, new build, <=$1.7M)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch, print, skip DB writes and publish")
    parser.add_argument("--status", action="store_true", help="Print current matches from DB (no fetch)")
    args = parser.parse_args()

    conn = open_db()

    if args.status:
        print_status(conn)
        return

    session, csrf = open_session()
    if not csrf:
        print(f"{LOG} Could not obtain CSRF token — aborting.")
        return

    all_matches = []  # list of (item, bedroom_count)
    for bedroom_count, bedroom_value in BEDROOM_SPECS:
        for region in REGIONS:
            print(f"{LOG} Fetching {region} ({bedroom_count}BR)...")
            items = fetch_region_listings(session, csrf, region, bedroom_value)
            matches = filter_new_build(items)
            print(f"{LOG}   {len(items)} {bedroom_count}BR condos, {len(matches)} match new-build/price criteria")

            if matches:
                median_rent_psf = fetch_region_median_rent_psf(session, csrf, region)
                print(f"{LOG}   Rent comp: ${median_rent_psf:.0f}/sqft/yr" if median_rent_psf
                      else f"{LOG}   No rent comps found for {region} — cap rate will be blank.")
                for it in matches:
                    compute_cap_rate(it, median_rent_psf)

            all_matches.extend((it, bedroom_count) for it in matches)

    ts = datetime.now(timezone.utc).isoformat()

    if args.dry_run:
        if not all_matches:
            print(f"{LOG} [dry-run] No matching listings found.")
        else:
            print(f"\n{LOG} [dry-run] Matches (not stored):")
            for it, bedroom_count in all_matches:
                cap = it.get("_cap_rate")
                cap_str = f"{cap*100:.2f}%" if cap is not None else "—"
                print(f"  {bedroom_count}BR  ${it['price_raw']:>10,.0f}  cap {cap_str:>6}  {it['display_name']}  ({it.get('hood')})  built/conv {it.get('built_converted') or it.get('yearbuilt')}")
        return

    subprocess.run(["git", "pull", "--rebase"], cwd=SITE_REPO, capture_output=True)

    for it, bedroom_count in all_matches:
        store_snapshot(conn, it, ts, bedroom_count)
    conn.execute("INSERT INTO runs (captured_at) VALUES (?)", (ts,))
    conn.commit()
    print(f"{LOG} Stored {len(all_matches)} snapshots ({ts}).")

    new_listings, price_cuts = detect_changes(conn, ts)
    if not new_listings and not price_cuts:
        print(f"{LOG} No new listings or price cuts vs prior run.")
    publish_to_site(conn, new_listings, price_cuts, dry_run=False)


if __name__ == "__main__":
    main()
