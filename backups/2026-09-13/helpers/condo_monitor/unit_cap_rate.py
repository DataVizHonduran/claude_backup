#!/usr/bin/env python3
"""
Cap-rate guesstimate for a specific NYC condo/co-op unit — CityRealty for
live comps + unit history, NYC DOF Open Data for building income/expense.

Default target: 143 West 27th Street, Apt 5 (Chelsea co-op). Override with
--address / --unit for any other building.

Pipeline (all live, re-fetched every run — nothing hardcoded/stale):
  1. Resolve the building on CityRealty (autocomplete-search-mini).
  2. Scrape the unit's page for last-sale price/date/sqft/beds (Playwright —
     this specific page needs JS render; no static-HTML shortcut found).
  3. Pull the building's DOF income/expense figures (NYC Open Data SODA API —
     tries the co-op dataset, falls back to the condo dataset).
  4. Pull live rental comps (nearby neighborhoods, all building types incl.
     actual rental buildings — condo/co-op sublets alone are too thin/skewed).
  5. Pull live closed-sale comps (same neighborhood, same bedroom count, same
     building type) for a current $/sqft estimate — NOT just the one asking
     price on the building, which is what burned the first pass of this.
  6. NOI = gross rent estimate - opex - tax - vacancy - mgmt fee. Cap rate
     is reported as a range, not a point estimate — the whole point of this
     script is that the range is the honest answer.

Terminal output only — not published anywhere.

Usage:
    python3 unit_cap_rate.py                                   # 143 W 27th St #5
    python3 unit_cap_rate.py --address "..." --unit "5A" --hood "Chelsea" --building-type coop
"""

import argparse
import json
import re
import urllib.parse
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "https://www.cityrealty.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
RENTAL_TEMPLATE_FILE = Path(__file__).parent / "data" / "city_rental_template.json"

VACANCY_RATE      = 0.05
MGMT_FEE_RATE     = 0.08
TAX_FALLBACK_PSF_MO = 1.50
NO_DOORMAN_HAIRCUT = 0.175   # discount vs newer/amenity rental comps, for older no-doorman buildings

DOF_DATASET = {"coop": "myei-c3fa", "condo": "9ck6-2jew"}

BEDROOM_LABEL_TO_ID = {"studio": 10, "1br": 11, "2br": 12, "3br": 13}

DEFAULT_NEARBY_HOODS = {
    "Chelsea": {"Chelsea", "Flatiron/Union Square", "Gramercy Park", "NoMad",
                "Greenwich Village", "West Village"},
}


def open_session() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.get(f"{BASE}/nyc/apartments-for-rent/search-new", timeout=30)
    csrf = urllib.parse.unquote(s.cookies.get("CSRF-Token", ""))
    return s, csrf


def resolve_building(s: requests.Session, address: str) -> dict | None:
    r = s.get(f"{BASE}/rpc/autocomplete-search-mini",
               params={"properties": 1, "rpc": 1, "query": address}, timeout=30)
    r.raise_for_status()
    prop = r.json().get("property", {}) or {}
    listing = (prop.get("list") or [None])[0]
    return listing  # has url_main, type ("Co-op"/"Condo"), address


def fetch_unit_page_text(building_url_main: str, unit: str) -> str:
    """The unit page is an Angular app — needs a real render, static HTML is a shell."""
    url = f"{BASE}{building_url_main}/{urllib.parse.quote(unit)}"
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 1000})
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1500)
        text = page.inner_text("body")
        b.close()
    return text


def parse_unit_history(text: str) -> dict:
    out = {}
    m = re.search(r"Sold for \$([\d,]+)", text)
    if m:
        out["last_sale_price"] = int(m.group(1).replace(",", ""))
    m = re.search(r"Apartment Last Sold on ([A-Za-z]+ \d+, \d+)", text)
    if m:
        out["last_sale_date"] = m.group(1)
    m = re.search(r"Approx ([\d,]+)\s*ft", text)
    if m:
        out["sqft"] = int(m.group(1).replace(",", ""))
    m = re.search(r"(\d+)\s*beds?,\s*(\d+)\s*baths?", text)
    if m:
        out["beds"], out["baths"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"with (\d+) units and built in (\d+)", text)
    if m:
        out["total_units"], out["year_built"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"asking price\s*by\s*[\d,]+", text)
    return out


def fetch_dof_income(address: str, dataset_key: str) -> dict | None:
    """DOF addresses drop ordinal suffixes ("27 STREET" not "27TH STREET")."""
    dataset_id = DOF_DATASET.get(dataset_key)
    if not dataset_id:
        return None
    normalized = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", address.upper())
    resp = requests.get(
        f"https://data.cityofnewyork.us/resource/{dataset_id}.json",
        params={"$where": f"upper(address)='{normalized}'", "$limit": 1}, timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def fetch_rental_comps(s: requests.Session, csrf: str, hoods: set[str],
                        building_types: set[str] = frozenset({"condo", "coop", "rental"}),
                        bedroom_value: int = 12) -> dict:
    template = json.loads(RENTAL_TEMPLATE_FILE.read_text())
    for f in template["filters"]:
        if f["name"] == "hoods":
            for grp in f["options"]:
                for h in grp["hoods"]:
                    h["active"] = 1 if h["name"] in hoods else 0
        elif f["name"] == "building type":
            for o in f["options"]:
                o["active"] = o["value"] in building_types
        elif f["name"] == "bedrooms":
            for o in f["options"]:
                o["active"] = (o["value"] == bedroom_value)
    template["pagination"] = {"total": 2500, "rowsPerPage": 52, "currentPage": "1"}

    headers = {
        "Content-Type": "application/json",
        "Referer": f"{BASE}/nyc/apartments-for-rent/search-results",
        "Origin": BASE, "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": csrf,
    }
    url = (f"{BASE}/rpc/search/get-rental-listings"
           "?f%5B%5D=priceRangeRent&f%5B%5D=location&f%5B%5D=bedroomFullMulti"
           "&f%5B%5D=rentalBuildingTypeMulti&f%5B%5D=doorman&f%5B%5D=amenities"
           "&f%5B%5D=dateListed&f%5B%5D=priceChange&f%5B%5D=searchTermListings"
           "&f%5B%5D=subHoods&s%5B%5D=rentPrice&s%5B%5D=dateListed&s%5B%5D=ppsqft"
           "&s%5B%5D=registration&show_vow=1&type=json&uniqueid=unit_cap_rate&page=1")
    r = s.post(url, headers=headers, json=template, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    comps = [{"name": it["display_name"], "rent": it["price_raw"], "sqft": it["sqft_raw"],
              "ppsqft": it["ppsqft_raw"], "type": it["building_type"]}
             for it in items if it.get("ppsqft_raw") and it.get("sqft_raw")]
    ppsqfts = sorted(c["ppsqft"] for c in comps)
    n = len(ppsqfts)
    return {"comps": comps, "median_ppsqft": ppsqfts[n // 2] if n else None, "n": n}


def fetch_closed_sale_comps(s: requests.Session, csrf: str, hood_name: str,
                             bedroom_id: str, building_type_label: str,
                             lookback_days: int = 90) -> dict:
    from datetime import datetime, timedelta
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    headers = {
        "X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/nyc/market-data/recent-sales", "Origin": BASE,
    }
    url = (f"{BASE}/rpc/market-insight-recent-sales"
           f"?types%5B%5D=2&types%5B%5D=3&price_format=short"
           f"&start_date={start_date}&currency=USD&rpc_count=1")
    r = s.post(url, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    comps = []
    for _region_id, beds in data.get("list", {}).items():
        for bed_id, sales in beds.items():
            if bed_id != bedroom_id:
                continue
            for sale in sales:
                if sale.get("hood_name") != hood_name:
                    continue
                if building_type_label and sale.get("building_type") != building_type_label:
                    continue
                comps.append({
                    "name": sale["display_name"], "unit": sale.get("unit"),
                    "price": int(sale["sale_price"]), "sqft": sale.get("sqft"),
                    "ppsqft": sale.get("ppsqft"), "date": sale.get("sale_date"),
                })
    ppsqfts = sorted(c["ppsqft"] for c in comps if c.get("ppsqft"))
    n = len(ppsqfts)
    return {"comps": comps, "median_ppsqft": ppsqfts[n // 2] if n else None, "n": n, "lookback_days": lookback_days}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default="143 West 27th Street")
    ap.add_argument("--unit", default="5")
    ap.add_argument("--hood", default="Chelsea", help="CityRealty neighborhood name for comps")
    ap.add_argument("--nearby-hoods", nargs="*", default=None,
                     help="Extra neighborhoods to widen the rental comp pool (default: a curated Downtown set for Chelsea)")
    ap.add_argument("--building-type", choices=["coop", "condo"], default="coop")
    ap.add_argument("--bedrooms", default="2br", choices=list(BEDROOM_LABEL_TO_ID))
    args = ap.parse_args()

    bedroom_id = str(BEDROOM_LABEL_TO_ID[args.bedrooms])
    sale_comp_type_label = {"coop": "Cooperative", "condo": "Condominium"}[args.building_type]
    nearby = set(args.nearby_hoods) if args.nearby_hoods else DEFAULT_NEARBY_HOODS.get(args.hood, {args.hood})

    print(f"[UNIT-CAP-RATE] Resolving {args.address}...")
    s, csrf = open_session()
    building = resolve_building(s, args.address)
    if not building:
        print("[UNIT-CAP-RATE] Building not found on CityRealty — aborting.")
        return
    print(f"[UNIT-CAP-RATE]   {building['name_display']} — {building['type']} — {BASE}{building['url_main']}")

    print(f"[UNIT-CAP-RATE] Fetching unit #{args.unit} history (renders JS, ~10-20s)...")
    text = fetch_unit_page_text(building["url_main"], args.unit)
    unit = parse_unit_history(text)
    if not unit.get("sqft"):
        print("[UNIT-CAP-RATE]   Could not parse sqft/sale history from the unit page — showing raw excerpt:")
        print(text[:600])
        return
    print(f"[UNIT-CAP-RATE]   {unit}")

    print(f"[UNIT-CAP-RATE] Pulling NYC DOF income/expense data ({args.building_type})...")
    dof = fetch_dof_income(args.address, args.building_type)
    if dof:
        print(f"[UNIT-CAP-RATE]   gross_income_per_sqft=${dof['gross_income_per_sqft']}/ft²  "
              f"expense_per_sqft=${dof['expense_per_sqft']}/ft²  (FY vintage varies, dataset last updated periodically)")
    else:
        print("[UNIT-CAP-RATE]   No DOF match found for this address.")

    print(f"[UNIT-CAP-RATE] Pulling rental comps ({', '.join(sorted(nearby))})...")
    rent_comps = fetch_rental_comps(s, csrf, nearby, bedroom_value=int(bedroom_id))
    print(f"[UNIT-CAP-RATE]   n={rent_comps['n']}  median=${rent_comps['median_ppsqft']}/ft²/yr" if rent_comps["median_ppsqft"]
          else "[UNIT-CAP-RATE]   No rental comps found.")

    print(f"[UNIT-CAP-RATE] Pulling closed {args.bedrooms} {sale_comp_type_label} sale comps in {args.hood} (last 90d)...")
    sale_comps = fetch_closed_sale_comps(s, csrf, args.hood, bedroom_id, sale_comp_type_label)
    print(f"[UNIT-CAP-RATE]   n={sale_comps['n']}  median=${sale_comps['median_ppsqft']}/ft²" if sale_comps["median_ppsqft"]
          else "[UNIT-CAP-RATE]   No closed sale comps found — falling back to last-sale price only.")

    # ── Assemble estimate ────────────────────────────────────────────────
    sqft = unit["sqft"]
    price_estimates = []
    if sale_comps["median_ppsqft"]:
        price_estimates.append(("closed sale comps", sale_comps["median_ppsqft"] * sqft))
    if unit.get("last_sale_price") and unit.get("last_sale_date"):
        price_estimates.append((f"last sale ({unit['last_sale_date']}, no appreciation adj.)", unit["last_sale_price"]))
    if not price_estimates:
        print("[UNIT-CAP-RATE] No price basis found at all — can't estimate a cap rate.")
        return

    rent_psf = rent_comps["median_ppsqft"]
    print("\n" + "=" * 78)
    print(f"CAP RATE GUESSTIMATE — {building['name_display']} #{args.unit}")
    print("=" * 78)
    print(f"Unit: {unit.get('beds','?')}BR/{unit.get('baths','?')}BA, ~{sqft:,} ft², "
          f"{building.get('type')}, built {unit.get('year_built','?')}")
    for label, price in price_estimates:
        print(f"Price basis — {label}: ${price:,.0f} (${price/sqft:,.0f}/ft²)")

    if not rent_psf:
        print("\nNo rent comps — cannot compute NOI/cap rate.")
        return

    tax_annual = TAX_FALLBACK_PSF_MO * sqft * 12
    opex_annual = (float(dof["expense_per_sqft"]) * sqft) if dof else 0

    for rent_label, rent_multiplier in [("raw comp median", 1.0), (f"–{NO_DOORMAN_HAIRCUT*100:.0f}% no-doorman haircut", 1 - NO_DOORMAN_HAIRCUT)]:
        gross_rent = rent_psf * sqft * rent_multiplier
        noi = gross_rent - opex_annual - tax_annual - (VACANCY_RATE * gross_rent) - (MGMT_FEE_RATE * gross_rent)
        print(f"\n-- Rent scenario: {rent_label} (${rent_psf * rent_multiplier:,.0f}/ft²/yr) --")
        print(f"   Gross rent: ${gross_rent:,.0f}/yr (${gross_rent/12:,.0f}/mo)")
        print(f"   Est. NOI:   ${noi:,.0f}/yr  (opex ${opex_annual:,.0f} + tax-fallback ${tax_annual:,.0f} "
              f"+ {VACANCY_RATE*100:.0f}% vacancy + {MGMT_FEE_RATE*100:.0f}% mgmt)")
        for label, price in price_estimates:
            print(f"   Cap rate vs {label}: {noi/price*100:.2f}%")

    print("\nCaveats: unit is off-market (no live listing) — every number above is a live-data-driven")
    print("guesstimate, not an appraisal. Maintenance/tax are estimated, not the building's actual budget.")
    if building.get("type", "").lower().startswith("co"):
        print("Co-op: subletting typically needs board approval — confirm the building allows rentals")
        print("at all before any of this matters.")


if __name__ == "__main__":
    main()
