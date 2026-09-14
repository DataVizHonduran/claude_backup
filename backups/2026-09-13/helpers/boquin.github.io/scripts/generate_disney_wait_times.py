"""
generate_disney_wait_times.py — Disneyland Paris Live Wait Times
Fetches live queue times for curated marquee rides across Disneyland Park
and Disney Adventure World Paris via the free queue-times.com API and
generates a static HTML page.

Data: https://queue-times.com (Real Time API, free tier — attribution required)
Run: python scripts/generate_disney_wait_times.py
Output: reports/disney-wait-times/index.html
"""

import os
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR  = os.path.join(REPO_ROOT, "reports", "disney-wait-times")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "index.html")

API_BASE = "https://queue-times.com/parks/{park_id}/queue_times.json"

# (park_id, park_label, {ride_id: display_name})
PARKS = [
    (4, "Disneyland Park", {
        8:  "Star Wars Hyperspace Mountain",
        25: "Big Thunder Mountain",
        3:  "Pirates of the Caribbean",
        26: "Phantom Manor",
        22: "Peter Pan's Flight",
        19: "“it's a small world”",
        9:  "Star Tours: The Adventures Continue",
        2:  "Indiana Jones et le Temple du Péril",
        5:  "Buzz Lightyear Laser Blast",
    }),
    (28, "Disney Adventure World Paris", {
        32:    "Crush's Coaster",
        37:    "Ratatouille: L'Aventure Totalement Toquée de Rémy",
        40:    "The Twilight Zone Tower of Terror",
        34:    "RC Racer",
        15413: "Frozen Ever After",
        10848: "Avengers Assemble: Flight Force",
    }),
]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_park_rides(park_id: int) -> dict[int, dict]:
    """Return {ride_id: {name, is_open, wait_time, last_updated}} for one park."""
    url = API_BASE.format(park_id=park_id)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    rides = {}
    for land in payload.get("lands", []):
        for ride in land.get("rides", []):
            rides[ride["id"]] = ride
    for ride in payload.get("rides", []):
        rides[ride["id"]] = ride
    return rides


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def build_park_section(park_label: str, rows: list[dict]) -> str:
    rows_sorted = sorted(rows, key=lambda r: (-r["is_open"], -(r["wait_time"] or -1)))

    body_rows = []
    for row in rows_sorted:
        if row["is_open"]:
            status_html = '<span class="dot open"></span>Open'
            wait_html   = f'<td class="wait">{row["wait_time"]} min</td>'
        else:
            status_html = '<span class="dot closed"></span>Closed'
            wait_html   = '<td class="wait na">—</td>'
        body_rows.append(
            f'<tr><td class="ride-name">{row["name"]}</td>'
            f'<td class="status">{status_html}</td>{wait_html}</tr>'
        )

    return f"""
  <div class="table-card">
    <div class="park-header">{park_label}</div>
    <table>
      <thead>
        <tr><th>Ride</th><th>Status</th><th>Wait</th></tr>
      </thead>
      <tbody>
        {"".join(body_rows)}
      </tbody>
    </table>
  </div>"""


def build_html(sections_html: str, generated_at: str, missing: list[str]) -> str:
    missing_note = ""
    if missing:
        missing_note = f'<div class="missing-note">Not currently reporting: {", ".join(missing)}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="600">
<title>Disneyland Paris Wait Times</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:       #f4f7fb;
    --surface:  #ffffff;
    --navy:     #2a3f5f;
    --navy-hd:  #1a2e45;
    --blue-md:  #3d5a8a;
    --text:     #2a3f5f;
    --muted:    #7b8faa;
    --border:   #d1dce9;
    --green:    #1a7f3c;
    --red:      #c0392b;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }}

  .dashboard-header {{
    background: linear-gradient(135deg, var(--navy-hd) 0%, var(--blue-md) 100%);
    padding: 28px 32px 24px;
    border-bottom: 1px solid #b8c8db;
    color: #ffffff;
  }}
  .dashboard-header h1 {{
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 6px;
  }}
  .header-meta {{ font-size: 12px; color: rgba(255,255,255,0.7); }}
  .back-link {{
    display: inline-block;
    margin-bottom: 14px;
    color: rgba(255,255,255,0.75);
    text-decoration: none;
    font-size: 12px;
    letter-spacing: 0.02em;
  }}
  .back-link:hover {{ color: #fff; }}

  .main-content {{
    max-width: 900px;
    margin: 28px auto;
    padding: 0 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }}

  .table-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }}
  .park-header {{
    background: var(--navy);
    color: #fff;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.03em;
    padding: 12px 16px;
  }}

  table {{ width: 100%; border-collapse: collapse; }}

  thead th {{
    background: #eef2f8;
    color: var(--muted);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 10px 16px;
    text-align: left;
  }}
  thead th:last-child, thead th:nth-child(2) {{ text-align: right; }}

  tbody tr {{ border-bottom: 1px solid var(--border); }}
  tbody tr:last-child {{ border-bottom: none; }}

  td {{ padding: 12px 16px; }}
  td.ride-name {{ font-weight: 500; color: var(--navy); }}
  td.status {{ white-space: nowrap; text-align: right; color: var(--muted); font-size: 13px; }}
  td.wait {{ text-align: right; font-weight: 700; font-size: 15px; color: var(--navy); font-variant-numeric: tabular-nums; }}
  td.wait.na {{ color: var(--muted); font-weight: 400; }}

  .dot {{
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
  }}
  .dot.open {{ background: var(--green); }}
  .dot.closed {{ background: var(--red); }}

  .missing-note {{
    font-size: 11px;
    color: var(--muted);
    text-align: center;
  }}

  .footer {{
    text-align: center;
    margin: 8px 0 40px;
    font-size: 11px;
    color: var(--muted);
  }}
  .footer a {{ color: var(--muted); }}

  @media (max-width: 768px) {{
    .main-content {{ padding: 0 12px; margin: 16px auto; }}
    td, th {{ padding: 9px 10px; font-size: 12px; }}
  }}
</style>
</head>
<body>

<div class="dashboard-header">
  <a class="back-link" href="../../index.html">← boquin.xyz</a>
  <h1>\U0001f3a2 Disneyland Paris Wait Times</h1>
  <div class="header-meta">Live queue times · refreshes every 10 min · Updated: {generated_at}</div>
</div>

<div class="main-content">
{sections_html}
  {missing_note}
  <div class="footer">
    Powered by <a href="https://queue-times.com" target="_blank">Queue-Times.com</a>
  </div>
</div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections = []
    missing = []
    for park_id, park_label, ride_ids in PARKS:
        print(f"Fetching: {park_label} (park {park_id})...")
        live_rides = fetch_park_rides(park_id)

        rows = []
        for ride_id, display_name in ride_ids.items():
            live = live_rides.get(ride_id)
            if live is None:
                print(f"  WARNING: ride id {ride_id} ({display_name}) not found in API response")
                missing.append(display_name)
                continue
            rows.append({
                "name":      display_name,
                "is_open":   bool(live.get("is_open")),
                "wait_time": live.get("wait_time"),
            })

        print(f"  {len(rows)}/{len(ride_ids)} rides reporting")
        sections.append(build_park_section(park_label, rows))

    html = build_html("\n".join(sections), generated_at, missing)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
