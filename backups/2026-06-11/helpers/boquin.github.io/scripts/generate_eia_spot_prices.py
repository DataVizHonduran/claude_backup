"""
generate_eia_spot_prices.py — EIA Petroleum Spot Prices Table
Fetches daily spot prices for key petroleum products via EIA Open Data API v2
and generates a static HTML table with % changes across 6 time horizons.
Clicking a row renders a 2-year Plotly price chart.

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_eia_spot_prices.py
Output: reports/eia-spot-prices/index.html
"""

import json
import os
import sys
import requests
from datetime import datetime, date, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE    = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
NATGAS_API_BASE = "https://api.eia.gov/v2/natural-gas/pri/fut/data/"
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT    = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR   = os.path.join(REPO_ROOT, "reports", "eia-spot-prices")
OUTPUT_PATH  = os.path.join(OUTPUT_DIR, "index.html")

# (display_label, unit, series_id)
# Series IDs confirmed from EIA API discovery on 2026-04-30.
PRODUCTS = [
    ("WTI Crude Oil (Cushing, OK)",         "$/bbl", "RWTC"),
    ("Brent Crude Oil (Europe)",             "$/bbl", "RBRTE"),
    ("NY Harbor No. 2 Heating Oil",         "$/gal", "EER_EPD2F_PF4_Y35NY_DPG"),
    ("Gulf Coast Kerosene-Type Jet Fuel",   "$/gal", "EER_EPJK_PF4_RGC_DPG"),
    ("NY Harbor Conventional Gasoline Regular", "$/gal", "EER_EPMRU_PF4_Y35NY_DPG"),
    ("US Gulf Coast Conventional Gasoline Regular", "$/gal", "EER_EPMRU_PF4_RGC_DPG"),
    ("LA RBOB Regular Gasoline",            "$/gal", "EER_EPMRR_PF4_Y05LA_DPG"),
    ("NY Harbor ULS No. 2 Diesel",          "$/gal", "EER_EPD2DXL0_PF4_Y35NY_DPG"),
    ("Gulf Coast ULS No. 2 Diesel",         "$/gal", "EER_EPD2DXL0_PF4_RGC_DPG"),
    ("LA ULS CARB Diesel",                  "$/gal", "EER_EPD2DC_PF4_Y05LA_DPG"),
    ("Propane (Mont Belvieu, TX)",           "$/gal", "EER_EPLLPA_PF4_Y44MB_DPG"),
]

# (display_label, unit, series_id) — fetched from NATGAS_API_BASE
NATGAS_PRODUCTS = [
    ("Henry Hub Natural Gas Spot Price", "$/MMBtu", "RNGWHHD"),
]

PERIODS = [
    ("1D",   1),
    ("1W",   7),
    ("1M",   30),
    ("3M",   91),
    ("12M",  365),
    ("5Y",   1825),
]

# ---------------------------------------------------------------------------
# EIA API fetch
# ---------------------------------------------------------------------------

def fetch_series(series_id: str, api_key: str, start: str, base: str = EIA_API_BASE) -> dict[str, float]:
    """Fetch daily data for one series from `start` to today. Returns {date_str: price}."""
    params = {
        "api_key":              api_key,
        "frequency":            "daily",
        "data[0]":              "value",
        "facets[series][]":     series_id,
        "sort[0][column]":      "period",
        "sort[0][direction]":   "desc",
        "start":                start,
        "length":               2200,
        "offset":               0,
    }
    try:
        resp = requests.get(base, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        print(f"  ERROR fetching {series_id}: {exc}")
        return {}

    rows   = payload.get("response", {}).get("data", [])
    result = {}
    for row in rows:
        period = row.get("period", "")
        val    = row.get("value")
        if period and val is not None:
            try:
                result[period] = float(val)
            except (TypeError, ValueError):
                pass
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pct_change(prices: dict[str, float], lookback_days: int) -> float | None:
    if not prices:
        return None
    dates      = sorted(prices.keys())
    latest     = dates[-1]
    latest_dt  = datetime.strptime(latest, "%Y-%m-%d")
    target_str = (latest_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    past       = [d for d in dates if d <= target_str]
    if not past:
        return None
    px_now  = prices[latest]
    px_then = prices[past[-1]]
    if px_then == 0:
        return None
    return (px_now - px_then) / px_then * 100


def compute_spread(fn, *price_dicts: dict[str, float]) -> dict[str, float]:
    """Compute a derived price series over the date intersection of all input dicts."""
    common = set(price_dicts[0].keys())
    for d in price_dicts[1:]:
        common &= d.keys()
    return {dt: fn(*[pd[dt] for pd in price_dicts]) for dt in common}


def history_2y(prices: dict[str, float]) -> dict:
    """Return {dates: [...], prices: [...]} for the last 730 calendar days."""
    if not prices:
        return {"dates": [], "prices": []}
    dates      = sorted(prices.keys())
    latest_dt  = datetime.strptime(dates[-1], "%Y-%m-%d")
    cutoff     = (latest_dt - timedelta(days=730)).strftime("%Y-%m-%d")
    filtered   = sorted(d for d in dates if d >= cutoff)
    return {"dates": filtered, "prices": [round(prices[d], 4) for d in filtered]}


def fmt_pct(val: float | None) -> tuple[str, str]:
    if val is None:
        return "—", "na"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%", "pos" if val >= 0 else "neg"


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def build_html(rows: list[dict], generated_at: str) -> str:
    period_headers = "".join(f"<th>{p}</th>" for p, _ in PERIODS)

    body_rows = []
    for i, row in enumerate(rows):
        cells = [
            f'<td class="product-name">{row["label"]}</td>',
            f'<td class="spot-price">{row["spot"]}<span class="unit">{row["unit"]}</span></td>',
        ]
        for p, days in PERIODS:
            text, cls = fmt_pct(row["changes"].get(p))
            cells.append(f'<td class="pct {cls}">{text}</td>')
        selected = ' class="selected"' if i == 0 else ""
        body_rows.append(f'<tr{selected} data-label="{row["label"]}">{"".join(cells)}</tr>')

    body_html = "\n            ".join(body_rows)

    # Build JS history object  {label: {dates, prices, unit}}
    history_obj = {}
    for row in rows:
        history_obj[row["label"]] = {**row["history"], "unit": row["unit"]}
    history_json = json.dumps(history_obj)

    first_label = rows[0]["label"] if rows else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EIA Petroleum Spot Prices</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:       #f4f7fb;
    --surface:  #ffffff;
    --navy:     #2a3f5f;
    --navy-hd:  #1a2e45;
    --blue-md:  #3d5a8a;
    --blue-sel: #e8f0fa;
    --text:     #2a3f5f;
    --muted:    #7b8faa;
    --border:   #d1dce9;
    --green:    #1a7f3c;
    --green-bg: #e8f5ee;
    --red:      #c0392b;
    --red-bg:   #fdecea;
    --na:       #9aa8bb;
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
    max-width: 1100px;
    margin: 28px auto;
    padding: 0 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }}

  /* ── Chart card ── */
  .chart-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }}
  .chart-header {{
    padding: 14px 20px 0;
    display: flex;
    align-items: baseline;
    gap: 10px;
  }}
  .chart-title {{
    font-size: 15px;
    font-weight: 600;
    color: var(--navy);
  }}
  .chart-hint {{
    font-size: 11px;
    color: var(--muted);
  }}
  #chart {{ width: 100%; height: 320px; }}

  /* ── Table card ── */
  .table-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }}

  table {{ width: 100%; border-collapse: collapse; }}

  thead th {{
    background: var(--navy);
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 11px 14px;
    text-align: right;
    white-space: nowrap;
    position: sticky;
    top: 0;
    z-index: 1;
  }}
  thead th:first-child {{ text-align: left; }}

  tbody tr {{
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.1s;
  }}
  tbody tr:last-child {{ border-bottom: none; }}
  tbody tr:hover {{ background: #f0f4fa; }}
  tbody tr.selected {{
    background: var(--blue-sel);
    border-left: 3px solid var(--blue-md);
  }}
  tbody tr.selected td.product-name {{ color: var(--blue-md); font-weight: 600; }}

  td {{
    padding: 11px 14px;
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }}
  td.product-name {{
    text-align: left;
    font-weight: 500;
    color: var(--navy);
  }}
  td.spot-price {{ font-weight: 600; color: var(--navy); }}
  .unit {{ font-size: 10px; font-weight: 400; color: var(--muted); margin-left: 3px; }}

  td.pct {{ font-weight: 600; font-size: 13px; border-radius: 4px; }}
  td.pct.pos {{ color: var(--green); background: var(--green-bg); }}
  td.pct.neg {{ color: var(--red);   background: var(--red-bg);   }}
  td.pct.na  {{ color: var(--na);    font-weight: 400;            }}

  .footer {{
    text-align: center;
    margin: 8px 0 40px;
    font-size: 11px;
    color: var(--muted);
  }}
  .footer a {{ color: var(--muted); }}

  @media (max-width: 768px) {{
    .main-content {{ padding: 0 12px; margin: 16px auto; }}
    td, th {{ padding: 9px 8px; font-size: 12px; }}
    td.product-name {{ min-width: 140px; }}
    #chart {{ height: 240px; }}
  }}
</style>
</head>
<body>

<div class="dashboard-header">
  <a class="back-link" href="../../index.html">← boquin.xyz</a>
  <h1>⛽ EIA Petroleum Spot Prices</h1>
  <div class="header-meta">Daily spot prices · Source: EIA Open Data API v2 · Updated: {generated_at}</div>
</div>

<div class="main-content">

  <div class="chart-card">
    <div class="chart-header">
      <span class="chart-title" id="chart-label">{first_label}</span>
      <span class="chart-hint">2-year daily price history</span>
    </div>
    <div id="chart"></div>
  </div>

  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th>Product</th>
          <th>Spot Price</th>
          {period_headers}
        </tr>
      </thead>
      <tbody>
            {body_html}
      </tbody>
    </table>
  </div>

  <div class="footer">
    Data: <a href="https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm" target="_blank">EIA Petroleum &amp; Other Liquids — Spot Prices</a> ·
    % changes from closest available trading day.
  </div>
</div>

<script>
const HISTORY = {history_json};

function showChart(label) {{
  const d = HISTORY[label];
  if (!d || !d.dates.length) return;

  const isBbl = d.unit === '$/bbl' || d.unit === '$/MMBtu';
  const fmt   = isBbl ? '.2f' : '.4f';

  Plotly.react('chart', [{{
    x:    d.dates,
    y:    d.prices,
    type: 'scatter',
    mode: 'lines',
    line: {{ color: '#3d5a8a', width: 2 }},
    fill: 'tozeroy',
    fillcolor: 'rgba(61,90,138,0.07)',
    hovertemplate: '<b>%{{x}}</b><br>' + d.unit.replace('$','') + ' %{{y:' + fmt + '}}<extra></extra>',
  }}], {{
    margin:      {{ t: 20, r: 20, b: 50, l: 70 }},
    paper_bgcolor: '#ffffff',
    plot_bgcolor:  '#f8fafd',
    font:        {{ family: '-apple-system,sans-serif', size: 12, color: '#2a3f5f' }},
    xaxis: {{ type: 'date', gridcolor: '#d1dce9', linecolor: '#d1dce9', tickformat: '%b %Y' }},
    yaxis: {{ title: d.unit, gridcolor: '#d1dce9', linecolor: '#d1dce9',
              tickformat: isBbl ? '.1f' : '.3f' }},
    hovermode: 'x unified',
    showlegend: false,
  }}, {{ responsive: true, displayModeBar: false }});

  document.getElementById('chart-label').textContent = label;

  document.querySelectorAll('tbody tr').forEach(tr => {{
    tr.classList.toggle('selected', tr.dataset.label === label);
  }});
}}

document.querySelectorAll('tbody tr').forEach(tr => {{
  tr.addEventListener('click', () => showChart(tr.dataset.label));
}});

// Load first product on page render
showChart({json.dumps(first_label)});
</script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("EIA_API_KEY", "").strip()
    if not api_key:
        print("ERROR: EIA_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    start_date   = (date.today() - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    raw: dict[str, dict[str, float]] = {}
    rows = []
    for label, unit, series_id in PRODUCTS:
        print(f"Fetching: {label} ({series_id})...")
        prices = fetch_series(series_id, api_key, start_date)
        raw[series_id] = prices

        if not prices:
            spot_str = "N/A"
            changes  = {p: None for p, _ in PERIODS}
            hist     = {"dates": [], "prices": []}
        else:
            dates     = sorted(prices.keys())
            latest_px = prices[dates[-1]]
            spot_str  = f"{latest_px:.2f}" if unit in ("$/bbl", "$/MMBtu") else f"{latest_px:.4f}"
            changes   = {p: pct_change(prices, days) for p, days in PERIODS}
            hist      = history_2y(prices)
            print(f"  Latest ({dates[-1]}): {latest_px}  ({len(hist['dates'])} days of 2Y history)")

        rows.append({
            "label":   label,
            "spot":    spot_str,
            "unit":    unit,
            "changes": changes,
            "history": hist,
        })

    for label, unit, series_id in NATGAS_PRODUCTS:
        print(f"Fetching: {label} ({series_id})...")
        prices = fetch_series(series_id, api_key, start_date, base=NATGAS_API_BASE)

        if not prices:
            spot_str = "N/A"
            changes  = {p: None for p, _ in PERIODS}
            hist     = {"dates": [], "prices": []}
        else:
            dates     = sorted(prices.keys())
            latest_px = prices[dates[-1]]
            spot_str  = f"{latest_px:.2f}"
            changes   = {p: pct_change(prices, days) for p, days in PERIODS}
            hist      = history_2y(prices)
            print(f"  Latest ({dates[-1]}): {latest_px}  ({len(hist['dates'])} days of 2Y history)")

        rows.append({
            "label":   label,
            "spot":    spot_str,
            "unit":    unit,
            "changes": changes,
            "history": hist,
        })

    # Crack spreads (derived — no extra API calls)
    wti  = raw.get("RWTC", {})
    rbob = raw.get("EER_EPMRU_PF4_Y35NY_DPG", {})
    ho   = raw.get("EER_EPD2F_PF4_Y35NY_DPG", {})

    spread_defs = [
        (
            "1:1 Crack Spread (RBOB–WTI)",
            compute_spread(lambda r, w: (r * 42) - w, rbob, wti),
        ),
        (
            "3:2:1 Crack Spread",
            compute_spread(lambda r, h, w: ((2 * r * 42) + (h * 42) - (3 * w)) / 3, rbob, ho, wti),
        ),
    ]

    for label, prices in spread_defs:
        print(f"Computing: {label}...")
        if not prices:
            rows.append({"label": label, "spot": "N/A", "unit": "$/bbl",
                         "changes": {p: None for p, _ in PERIODS}, "history": {"dates": [], "prices": []}})
        else:
            dates     = sorted(prices.keys())
            latest_px = prices[dates[-1]]
            rows.append({
                "label":   label,
                "spot":    f"{latest_px:.2f}",
                "unit":    "$/bbl",
                "changes": {p: pct_change(prices, days) for p, days in PERIODS},
                "history": history_2y(prices),
            })
            print(f"  Latest ({dates[-1]}): {latest_px:.2f}")

    html = build_html(rows, generated_at)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
