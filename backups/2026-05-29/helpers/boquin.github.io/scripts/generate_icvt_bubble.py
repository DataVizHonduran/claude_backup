"""
iShares Convertible Bond ETF (ICVT) Holdings — Yield to Worst vs Modified Duration Bubble Chart
Output: reports/icvt-bubble/index.html

Run: python3 scripts/generate_icvt_bubble.py
"""

import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ── ETF config ────────────────────────────────────────────────────────────────
ETF_URL = (
    "https://www.ishares.com/us/products/272819/"
    "ishares-convertible-bond-etf/"
    "1467271812596.ajax?fileType=csv&fileName=ICVT_holdings&dataType=fund"
)
ETF_REFERER = "https://www.ishares.com/us/products/272819/"
ETF_NAME = "iShares Convertible Bond ETF"
ETF_TICKER = "ICVT"

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "icvt-bubble"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
CACHE_DIR = Path.home() / ".claude" / "cache" / "icvt"

# Column search order — first match wins
DURATION_COLS = ["Mod. Duration", "Modified Duration", "Effective Duration", "Duration"]
YIELD_COLS = ["Yield to Worst (%)", "YTW (%)", "Yield to Maturity (%)", "YTM (%)"]

# 8-color palette (Wong 2011) — assigned in sector order by total weight
SECTOR_PALETTE = [
    "#0072B2",  # blue         — Technology
    "#E69F00",  # orange       — Consumer Cyclical
    "#009E73",  # green        — Capital Goods
    "#CC79A7",  # pink         — Health Care
    "#56B4E9",  # sky blue     — Communication
    "#D55E00",  # vermilion    — Energy
    "#6B4226",  # brown        — Financial
    "#999999",  # gray         — REITs / Other
]


# ── Fetch CSV ─────────────────────────────────────────────────────────────────
def fetch_csv() -> tuple[str, bool]:
    """Return (csv_text, is_fresh). Falls back to cache if fetch fails."""
    cache_file = CACHE_DIR / "icvt_holdings.csv"
    headers = {**BASE_HEADERS, "Referer": ETF_REFERER}
    try:
        print("  Fetching ICVT…")
        resp = requests.get(ETF_URL, headers=headers, timeout=45)
        resp.raise_for_status()
        text = resp.text
        if len(text) < 500 or "Name" not in text:
            raise ValueError(f"Response too short or missing data ({len(text)} chars)")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
        print(f"    {len(text):,} chars OK")
        return text, True
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        if cache_file.exists():
            print("    Falling back to cache", file=sys.stderr)
            return cache_file.read_text(encoding="utf-8"), False
        print("    No cache — cannot continue", file=sys.stderr)
        return "", False


# ── Parse CSV ─────────────────────────────────────────────────────────────────
DATE_PATTERNS = [
    (r"(\w{3}\s+\d{1,2},\s*\d{4})", "%b %d, %Y"),
    (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
    (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
    (r"(\d{1,2}-\w{3}-\d{4})", "%d-%b-%Y"),
]


def parse_csv(text: str) -> tuple[pd.DataFrame, str]:
    """Parse iShares CSV, skipping metadata rows. Returns (df, as_of_date)."""
    lines = text.splitlines()

    as_of = ""
    for line in lines[:8]:
        if "as of" in line.lower() or "holdings date" in line.lower():
            clean = line.replace('"', "")
            for pattern, fmt in DATE_PATTERNS:
                m = re.search(pattern, clean)
                if m:
                    try:
                        dt = datetime.strptime(m.group(1).strip(), fmt)
                        as_of = dt.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        pass
            if as_of:
                break

    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip().strip('"')
        if stripped.startswith("Name") or stripped.startswith("Ticker"):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find header row in CSV")

    csv_body = "\n".join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(csv_body), thousands=",", low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    return df, as_of


# ── Clean & extract ───────────────────────────────────────────────────────────
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to fixed income bonds with valid modified duration and YTW."""
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].str.strip() == "Fixed Income"].copy()

    def find_col(candidates, partial_key):
        for c in candidates:
            if c in df.columns:
                return c
        for col in df.columns:
            if partial_key in col.lower():
                return col
        return None

    dur_col = find_col(DURATION_COLS, "duration")
    ytw_col = find_col(YIELD_COLS, "yield")
    mv_col  = find_col(["Market Value", "Notional Value", "Market Value (USD)"], "market")
    wt_col  = find_col(["Weight (%)", "Weight", "Portfolio Weight"], "weight")
    cp_col  = find_col(["Coupon (%)", "Coupon", "Coupon Rate"], "coupon")
    mat_col = find_col(["Maturity", "Maturity Date"], "matur")
    sec_col = find_col(["Sector"], "sector")

    if dur_col is None:
        raise ValueError(f"No duration column found. Available: {list(df.columns)}")
    if ytw_col is None:
        raise ValueError(f"No yield column found. Available: {list(df.columns)}")
    if sec_col is None:
        raise ValueError(f"No sector column found. Available: {list(df.columns)}")

    def to_float(series):
        return pd.to_numeric(
            series.astype(str).str.replace(",", "").str.replace("%", "").str.strip(),
            errors="coerce",
        )

    df["_duration"] = to_float(df[dur_col])
    df["_ytw"]      = to_float(df[ytw_col])
    df["_weight"]   = to_float(df[wt_col]) if wt_col else 0.0
    df["_mv"]       = to_float(df[mv_col]) if mv_col else 0.0
    df["_coupon"]   = to_float(df[cp_col]) if cp_col else None
    df["_maturity"] = df[mat_col].astype(str).str.strip() if mat_col else ""
    df["_name"]     = df["Name"].astype(str).str.strip() if "Name" in df.columns else ""
    df["_sector"]   = df[sec_col].astype(str).str.strip()

    df = df.dropna(subset=["_duration", "_ytw"])
    df = df[df["_duration"] > 0]
    df = df[df["_ytw"] > 0]
    df = df[~df["_sector"].isin(["", "nan", "N/A", "-", "nan"])]
    return df


# ── Build payload ─────────────────────────────────────────────────────────────
def build_payload(df: pd.DataFrame, as_of: str, fetched_at: str, is_fresh: bool) -> dict:
    bonds = []
    for _, row in df.iterrows():
        bonds.append({
            "n": row["_name"],
            "s": row["_sector"],
            "d": round(float(row["_duration"]), 3),
            "y": round(float(row["_ytw"]), 3),
            "w": round(float(row["_weight"]), 3) if pd.notna(row["_weight"]) else 0.0,
            "m": round(float(row["_mv"]), 0),
            "c": round(float(row["_coupon"]), 3) if pd.notna(row["_coupon"]) else None,
            "t": row["_maturity"],
        })

    # Sort sectors by total portfolio weight descending
    wt_by_sector = df.groupby("_sector")["_weight"].sum().sort_values(ascending=False)
    sectors = wt_by_sector.index.tolist()

    return {
        "as_of": as_of,
        "fetched_at": fetched_at,
        "is_fresh": is_fresh,
        "bond_count": len(bonds),
        "sector_count": len(sectors),
        "sectors": sectors,
        "bonds": bonds,
    }


# ── Generate HTML ─────────────────────────────────────────────────────────────
def generate_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    palette_json = json.dumps(SECTOR_PALETTE)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ICVT — Convertible Bond Bubble Chart</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  :root {{
    --forest: #1a3a2f;
    --forest-light: #2d5a47;
    --cream: #faf9f7;
    --charcoal: #1a1a1a;
    --warm-gray: #6b6b6b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; background: var(--cream); color: var(--charcoal); }}

  .page-header {{
    background: linear-gradient(135deg, var(--forest) 0%, var(--forest-light) 100%);
    color: #fff;
    padding: 20px 32px 18px;
  }}
  .page-header h1 {{ font-size: 1.4rem; font-weight: 700; }}
  .page-header p {{ font-size: 0.82rem; opacity: 0.75; margin-top: 4px; }}

  /* Fund strip */
  .fund-strip {{
    background: #fff;
    border-bottom: 1px solid #e4e8ef;
    padding: 8px 32px;
    font-size: 0.78rem;
    color: var(--warm-gray);
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  }}
  .fund-name {{ font-weight: 600; color: var(--charcoal); }}
  .badge {{
    font-size: 0.70rem; padding: 2px 8px; border-radius: 999px; font-weight: 500;
  }}
  .badge-fresh {{ background: rgba(44,160,44,0.12); color: #1a7a1a; }}
  .badge-stale {{ background: rgba(212,168,0,0.15); color: #8a6a00; }}

  .main {{ max-width: 1300px; margin: 0 auto; padding: 16px 24px 40px; }}

  /* Stats */
  .stats-row {{ display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }}
  .stat-card {{
    background: #fff; border: 1px solid #e4e8ef; border-radius: 8px;
    padding: 10px 14px; flex: 1; min-width: 110px;
  }}
  .stat-label {{ font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--warm-gray); }}
  .stat-value {{ font-size: 1.2rem; font-weight: 700; margin-top: 2px; }}
  .stat-sub {{ font-size: 0.68rem; color: var(--warm-gray); margin-top: 1px; }}

  /* Sector selector */
  .selector-panel {{
    background: #fff; border: 1px solid #e4e8ef; border-radius: 10px;
    padding: 14px 18px; margin-bottom: 14px;
  }}
  .selector-panel h3 {{
    font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--warm-gray); margin-bottom: 8px; font-weight: 600;
  }}
  .selector-controls {{
    display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap;
  }}
  .selector-hint {{ font-size: 0.73rem; color: var(--warm-gray); flex: 1; }}
  .btn-link {{
    font-size: 0.73rem; color: var(--forest); background: none; border: none;
    cursor: pointer; padding: 2px 6px; border-radius: 4px; font-weight: 500;
    text-decoration: underline; text-underline-offset: 2px;
  }}
  .btn-link:hover {{ background: rgba(26,58,47,0.08); }}
  .search-wrap {{ position: relative; margin-bottom: 8px; }}
  .search-wrap input {{
    width: 100%; padding: 6px 30px 6px 10px;
    border: 1.5px solid #dde3ec; border-radius: 6px;
    font-size: 0.80rem; outline: none; background: #f8f9fc; color: var(--charcoal);
  }}
  .search-wrap input:focus {{ border-color: #8b9dc3; background: #fff; }}
  .search-clear {{
    position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
    cursor: pointer; color: #aab3c8; font-size: 1rem; line-height: 1;
    display: none; user-select: none;
  }}
  .search-clear.visible {{ display: block; }}
  .no-results {{ font-size: 0.76rem; color: #aab3c8; padding: 4px 2px; }}
  .sector-pills {{
    display: flex; flex-wrap: wrap; gap: 5px; padding: 2px;
  }}
  .pill {{
    cursor: pointer; padding: 3px 11px; border-radius: 999px;
    font-size: 0.76rem; font-weight: 500;
    border: 1.5px solid #dde3ec; background: #f8f9fc; color: var(--charcoal);
    transition: all 0.13s; user-select: none;
  }}
  .pill:hover {{ border-color: #aab3c8; background: #eef1f7; }}
  .pill.active {{ color: #fff; }}
  .pill.disabled {{ opacity: 0.38; cursor: not-allowed; }}

  /* Chart */
  .chart-card {{
    background: #fff; border: 1px solid #e4e8ef; border-radius: 10px;
    padding: 4px; margin-bottom: 14px;
  }}
  #bubble-chart {{ width: 100%; height: 580px; }}

  /* Footer */
  .page-footer {{
    border-top: 1px solid #e4e8ef; margin-top: 4px; padding-top: 12px;
    font-size: 0.70rem; color: var(--warm-gray);
    display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px;
  }}
  .update-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 5px; vertical-align: middle; }}
  .dot-fresh {{ background: #2ca02c; }}
  .dot-stale {{ background: #d4a800; }}

  @media (max-width: 600px) {{
    .page-header {{ padding: 14px 16px; }}
    .fund-strip {{ padding: 7px 16px; }}
    .main {{ padding: 10px 12px 30px; }}
    #bubble-chart {{ height: 400px; }}
  }}
</style>
</head>
<body>

<header class="page-header">
  <h1>&#128200; ICVT — iShares Convertible Bond ETF</h1>
  <p>Yield to Worst vs. Modified Duration &nbsp;&middot;&nbsp; Bubble size = portfolio weight &nbsp;&middot;&nbsp; Color = sector</p>
</header>

<div class="fund-strip">
  <span class="fund-name">iShares Convertible Bond ETF (ICVT)</span>
  <span id="fund-badge" class="badge"></span>
  <span id="fund-holdings-date" style="margin-left:auto"></span>
</div>

<main class="main">
  <div class="stats-row" id="stats-row"></div>

  <div class="selector-panel">
    <h3>Select Sectors to Display</h3>
    <div class="selector-controls">
      <span class="selector-hint">Click sectors to toggle. Max <strong>8</strong> at a time.</span>
      <button class="btn-link" id="btn-select-all">Select All</button>
      <button class="btn-link" id="btn-clear">Clear</button>
    </div>
    <div class="search-wrap">
      <input type="text" id="group-search" placeholder="Search sectors…" autocomplete="off" spellcheck="false">
      <span class="search-clear" id="search-clear" title="Clear">&#x2715;</span>
    </div>
    <div class="sector-pills" id="sector-pills"></div>
  </div>

  <div class="chart-card">
    <div id="bubble-chart"></div>
  </div>

  <div class="page-footer">
    <div id="footer-left"></div>
    <div>Source: <a href="https://www.ishares.com/us/products/272819/" target="_blank" rel="noopener">iShares</a> &nbsp;|&nbsp; Fixed income holdings only &nbsp;|&nbsp; Bubble size = portfolio weight (%)</div>
  </div>
</main>

<script>
const DATA = {data_json};
const PALETTE = {palette_json};
const MAX_SEL = 8;

let selected = [];
let sectorColors = {{}};

// ── Boot ───────────────────────────────────────────────────────────────────
function init() {{
  // Assign colors to sectors (by weight order, already sorted in payload)
  DATA.sectors.forEach((s, i) => {{
    sectorColors[s] = PALETTE[i % PALETTE.length];
  }});

  // Default: select all sectors
  selected = DATA.sectors.slice(0, MAX_SEL);

  // Fund strip metadata
  const badge = document.getElementById('fund-badge');
  if (DATA.is_fresh) {{
    badge.className = 'badge badge-fresh';
    badge.textContent = 'Live';
  }} else {{
    badge.className = 'badge badge-stale';
    badge.textContent = 'Cached';
  }}
  const hd = document.getElementById('fund-holdings-date');
  hd.textContent = DATA.as_of ? `Holdings: ${{DATA.as_of}}` : '';

  // Search input
  const searchEl = document.getElementById('group-search');
  const clearEl  = document.getElementById('search-clear');
  searchEl.addEventListener('input', () => {{
    clearEl.classList.toggle('visible', searchEl.value.length > 0);
    renderPills();
  }});
  clearEl.addEventListener('click', () => {{
    searchEl.value = '';
    clearEl.classList.remove('visible');
    renderPills();
    searchEl.focus();
  }});

  // Select All / Clear buttons
  document.getElementById('btn-select-all').addEventListener('click', () => {{
    selected = DATA.sectors.slice(0, MAX_SEL);
    renderPills();
    renderChart();
    renderStats();
  }});
  document.getElementById('btn-clear').addEventListener('click', () => {{
    selected = [];
    renderPills();
    renderChart();
    renderStats();
  }});

  renderStats();
  renderPills();
  renderChart();
  updateFooter();
}}

// ── Stats ──────────────────────────────────────────────────────────────────
function renderStats() {{
  const visibleBonds = selected.length > 0
    ? DATA.bonds.filter(b => selected.includes(b.s))
    : DATA.bonds;

  const totalW = visibleBonds.reduce((s, b) => s + (b.w || 0), 0);
  const wtAvgDur = wavg(visibleBonds, 'd', 'w');
  const wtAvgYTW = wavg(visibleBonds, 'y', 'w');

  document.getElementById('stats-row').innerHTML = `
    <div class="stat-card"><div class="stat-label">Holdings Shown</div><div class="stat-value">${{visibleBonds.length}}</div><div class="stat-sub">of ${{DATA.bond_count}} bonds</div></div>
    <div class="stat-card"><div class="stat-label">Sectors</div><div class="stat-value">${{DATA.sector_count}}</div><div class="stat-sub">in ETF</div></div>
    <div class="stat-card"><div class="stat-label">Avg Mod Duration</div><div class="stat-value">${{wtAvgDur.toFixed(1)}}y</div><div class="stat-sub">weight-avg</div></div>
    <div class="stat-card"><div class="stat-label">Avg YTW</div><div class="stat-value">${{wtAvgYTW.toFixed(2)}}%</div><div class="stat-sub">weight-avg</div></div>
    <div class="stat-card"><div class="stat-label">Total Weight</div><div class="stat-value">${{totalW.toFixed(1)}}%</div><div class="stat-sub">shown sectors</div></div>
  `;
}}

function wavg(bonds, field, wField) {{
  let sw = 0, swx = 0;
  bonds.forEach(b => {{ const w = b[wField] || 0; sw += w; swx += w * (b[field] || 0); }});
  return sw > 0 ? swx / sw : 0;
}}

// ── Pills ──────────────────────────────────────────────────────────────────
function renderPills() {{
  const container = document.getElementById('sector-pills');
  const query = document.getElementById('group-search').value.trim().toLowerCase();
  container.innerHTML = '';

  const visible = DATA.sectors.filter(s => !query || s.toLowerCase().includes(query));

  if (visible.length === 0) {{
    const msg = document.createElement('span');
    msg.className = 'no-results';
    msg.textContent = 'No matches';
    container.appendChild(msg);
    return;
  }}

  visible.forEach(sector => {{
    const isActive  = selected.includes(sector);
    const isDisabled = !isActive && selected.length >= MAX_SEL;
    const pill = document.createElement('span');
    pill.className = 'pill' + (isActive ? ' active' : '') + (isDisabled ? ' disabled' : '');
    pill.textContent = sector;
    if (isActive) {{
      const col = sectorColors[sector] || '#999';
      pill.style.background = col;
      pill.style.borderColor = col;
    }}
    pill.addEventListener('click', () => onPillClick(sector));
    container.appendChild(pill);
  }});
}}

function onPillClick(sector) {{
  const idx = selected.indexOf(sector);
  if (idx >= 0) {{
    selected.splice(idx, 1);
  }} else {{
    if (selected.length >= MAX_SEL) return;
    selected.push(sector);
  }}
  renderPills();
  renderChart();
  renderStats();
}}

// ── Chart ──────────────────────────────────────────────────────────────────
function renderChart() {{
  if (selected.length === 0) {{
    Plotly.react('bubble-chart', [], getLayout('Select sectors above to display bonds'));
    return;
  }}

  const allBonds = DATA.bonds.filter(b => selected.includes(b.s));
  const maxW = Math.max(...allBonds.map(b => b.w || 0.01), 0.01);

  const traces = selected.map(sector => {{
    const bonds = DATA.bonds.filter(b => b.s === sector);
    if (!bonds.length) return null;
    const col = sectorColors[sector] || '#999';
    return {{
      type: 'scatter',
      mode: 'markers',
      name: sector,
      x: bonds.map(b => b.d),
      y: bonds.map(b => b.y),
      text: bonds.map(b =>
        `<b>${{b.n}}</b><br>`
        + `Sector: ${{b.s}}<br>`
        + `Mod. Duration: ${{b.d.toFixed(2)}}y<br>`
        + `Yield to Worst: ${{b.y.toFixed(2)}}%<br>`
        + `Weight: ${{b.w.toFixed(2)}}%<br>`
        + (b.c != null ? `Coupon: ${{b.c.toFixed(2)}}%<br>` : '')
        + (b.t && b.t !== 'nan' ? `Maturity: ${{b.t}}` : '')
      ),
      hovertemplate: '%{{text}}<extra>' + sector + '</extra>',
      marker: {{
        size: bonds.map(b => Math.max(Math.sqrt((b.w || 0.01) / maxW) * 55, 5)),
        sizemode: 'diameter',
        color: col,
        opacity: 0.72,
        line: {{ color: 'rgba(255,255,255,0.55)', width: 1 }},
      }},
    }};
  }}).filter(Boolean);

  Plotly.react('bubble-chart', traces, getLayout());
}}

function getLayout(annotation) {{
  const layout = {{
    xaxis: {{ title: 'Modified Duration (years)', gridcolor: 'rgba(200,200,200,0.4)', zeroline: false }},
    yaxis: {{ title: 'Yield to Worst (%)', gridcolor: 'rgba(200,200,200,0.4)', zeroline: false }},
    plot_bgcolor: '#fff', paper_bgcolor: '#fff',
    margin: {{ l: 65, r: 30, t: 30, b: 65 }},
    legend: {{ orientation: 'h', yanchor: 'bottom', y: 1.01, xanchor: 'left', x: 0 }},
    hovermode: 'closest',
  }};
  if (annotation) {{
    layout.annotations = [{{ text: annotation, xref: 'paper', yref: 'paper',
      x: 0.5, y: 0.5, showarrow: false, font: {{ size: 15, color: '#bbb' }} }}];
  }}
  return layout;
}}

// ── Footer ─────────────────────────────────────────────────────────────────
function updateFooter() {{
  let ts = DATA.fetched_at || '';
  try {{
    const dt = new Date(ts);
    ts = dt.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  }} catch(e) {{}}
  const dotClass = DATA.is_fresh ? 'dot-fresh' : 'dot-stale';
  const msg = DATA.is_fresh
    ? `Data fetched ${{ts}}`
    : `&#9888; Cached data from ${{ts}} — live fetch failed`;
  document.getElementById('footer-left').innerHTML =
    `<span class="update-dot ${{dotClass}}"></span>${{msg}}`;
}}

document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("Fetching ICVT holdings…")
    csv_text, is_fresh = fetch_csv()
    if not csv_text:
        raise RuntimeError("No ICVT data available")

    df, as_of = parse_csv(csv_text)
    print(f"  Parsed: as-of={as_of or 'unknown'}")
    df = clean_data(df)
    print(f"  Clean: {len(df)} valid bonds, {df['_sector'].nunique()} sectors")

    payload = build_payload(df, as_of, fetched_at, is_fresh)
    html = generate_html(payload)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\nSaved → {OUTPUT_FILE}  ({len(html):,} chars, {payload['bond_count']} bonds, {payload['sector_count']} sectors)")


if __name__ == "__main__":
    main()
