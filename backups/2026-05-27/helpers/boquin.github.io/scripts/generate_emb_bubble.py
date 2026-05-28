"""
iShares EM Bond ETF Holdings — Duration vs Yield Bubble Chart
Supports: EMB, CEMB, LEMB, EMHY, LQD, HYG
Output: reports/emb-bubble/index.html

Run: python3 scripts/generate_emb_bubble.py
"""

import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ── ETF registry ──────────────────────────────────────────────────────────────
ETFS = {
    "EMB": {
        "label": "EMB",
        "name": "iShares J.P. Morgan USD Emerging Markets Bond ETF",
        "url": (
            "https://www.ishares.com/us/products/239572/"
            "ishares-jp-morgan-usd-emerging-markets-bond-etf/"
            "1467271812596.ajax?fileType=csv&fileName=EMB_holdings&dataType=fund"
        ),
        "referer": "https://www.ishares.com/us/products/239572/",
        "group_by": "country",   # group pills by Location column
    },
    "CEMB": {
        "label": "CEMB",
        "name": "iShares J.P. Morgan EM Corporate Bond ETF",
        "url": (
            "https://www.ishares.com/us/products/239525/"
            "ishares-emerging-markets-corporate-bond-etf/"
            "1467271812596.ajax?fileType=csv&fileName=CEMB_holdings&dataType=fund"
        ),
        "referer": "https://www.ishares.com/us/products/239525/",
        "group_by": "issuer",    # group pills by Name (company) column
    },
    "LEMB": {
        "label": "LEMB",
        "name": "iShares J.P. Morgan EM Local Currency Bond ETF",
        "url": (
            "https://www.ishares.com/us/products/239528/"
            "ishares-emerging-markets-local-currency-bond-etf/"
            "1467271812596.ajax?fileType=csv&fileName=LEMB_holdings&dataType=fund"
        ),
        "referer": "https://www.ishares.com/us/products/239528/",
        "group_by": "country",
    },
    "EMHY": {
        "label": "EMHY",
        "name": "iShares J.P. Morgan EM High Yield Bond ETF",
        "url": (
            "https://www.ishares.com/us/products/239527/"
            "ishares-emerging-markets-high-yield-bond-etf/"
            "1467271812596.ajax?fileType=csv&fileName=EMHY_holdings&dataType=fund"
        ),
        "referer": "https://www.ishares.com/us/products/239527/",
        "group_by": "issuer",
    },
    "LQD": {
        "label": "LQD",
        "name": "iShares iBoxx $ Investment Grade Corporate Bond ETF",
        "url": (
            "https://www.ishares.com/us/products/239566/"
            "ishares-iboxx-investment-grade-corporate-bond-etf/"
            "1467271812596.ajax?fileType=csv&fileName=LQD_holdings&dataType=fund"
        ),
        "referer": "https://www.ishares.com/us/products/239566/",
        "group_by": "issuer",
    },
    "HYG": {
        "label": "HYG",
        "name": "iShares iBoxx $ High Yield Corporate Bond ETF",
        "url": (
            "https://www.ishares.com/us/products/239565/"
            "ishares-iboxx-high-yield-corporate-bond-etf/"
            "1467271812596.ajax?fileType=csv&fileName=HYG_holdings&dataType=fund"
        ),
        "referer": "https://www.ishares.com/us/products/239565/",
        "group_by": "issuer",
    },
}

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/octet-stream,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "emb-bubble"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
CACHE_DIR = Path.home() / ".cache" / "emb-holdings"

# Duration column candidates (in priority order)
DURATION_COLS = ["Effective Duration", "Modified Duration", "Duration"]
# Yield column candidates
YIELD_COLS = ["Yield to Maturity (%)", "YTM (%)", "Yield to Maturity", "YTM", "Yield (%)"]
# Country/location column candidates (for non-EM funds like LQD/HYG, use Sector)
COUNTRY_COLS = ["Location", "Country", "Country of Risk", "Sector"]


# ── Fetch CSV ─────────────────────────────────────────────────────────────────
def fetch_csv(ticker: str, etf: dict) -> tuple[str, bool]:
    """Return (csv_text, is_fresh). Falls back to cache if fetch fails."""
    cache_file = CACHE_DIR / f"{ticker.lower()}_holdings.csv"
    headers = {**BASE_HEADERS, "Referer": etf["referer"]}
    try:
        print(f"  Fetching {ticker}…")
        resp = requests.get(etf["url"], headers=headers, timeout=45)
        resp.raise_for_status()
        text = resp.text
        if text.lstrip().startswith(("<!DOCTYPE", "<html", "<!doctype")):
            raise ValueError(f"iShares returned HTML instead of CSV (bot detection) — {len(text):,} chars")
        if len(text) < 500 or "Name" not in text:
            raise ValueError(f"Response too short or missing data ({len(text)} chars)")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
        print(f"    {len(text):,} chars OK")
        return text, True
    except Exception as e:
        print(f"    FAILED: {e}", file=sys.stderr)
        if cache_file.exists():
            print(f"    Falling back to cache for {ticker}", file=sys.stderr)
            return cache_file.read_text(encoding="utf-8"), False
        print(f"    No cache for {ticker} — skipping", file=sys.stderr)
        return "", False


# ── Parse CSV ─────────────────────────────────────────────────────────────────
DATE_PATTERNS = [
    (r"(\w{3}\s+\d{1,2},\s*\d{4})", "%b %d, %Y"),
    (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
    (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
    (r"(\d{1,2}-\w{3}-\d{4})", "%d-%b-%Y"),
]


def parse_csv(text: str) -> tuple[pd.DataFrame, str]:
    """Parse iShares CSV (skipping metadata rows). Returns (df, as_of_date)."""
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
def clean_data(df: pd.DataFrame, group_by: str = "country") -> pd.DataFrame:
    """Filter to fixed income bonds with valid duration & yield.

    group_by:
      "country" — use Location/Country column for pill grouping (sovereign ETFs)
      "issuer"  — use Name column for pill grouping (corporate ETFs)
    """
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
    ytm_col = find_col(YIELD_COLS, "yield")
    mv_col = find_col(["Market Value", "Notional Value", "Market Value (USD)"], "market")
    wt_col = find_col(["Weight (%)", "Weight", "Portfolio Weight"], "weight")
    cp_col = find_col(["Coupon (%)", "Coupon", "Coupon Rate"], "coupon")
    mat_col = find_col(["Maturity", "Maturity Date"], "matur")
    loc_col = find_col(COUNTRY_COLS, "locat")

    if dur_col is None:
        raise ValueError(f"No duration column. Available: {list(df.columns)}")
    if ytm_col is None:
        raise ValueError(f"No yield column. Available: {list(df.columns)}")

    def to_float(series):
        return pd.to_numeric(
            series.astype(str).str.replace(",", "").str.replace("%", "").str.strip(),
            errors="coerce",
        )

    df["_duration"] = to_float(df[dur_col])
    df["_ytm"] = to_float(df[ytm_col])
    df["_market_value"] = to_float(df[mv_col]) if mv_col else 0.0
    df["_weight"] = to_float(df[wt_col]) if wt_col else 0.0
    df["_coupon"] = to_float(df[cp_col]) if cp_col else None
    df["_maturity"] = df[mat_col].astype(str).str.strip() if mat_col else ""
    df["_name"] = df["Name"].astype(str).str.strip() if "Name" in df.columns else ""

    if group_by == "issuer":
        # For corporate ETFs the Name column IS the issuer/company name
        df["_group"] = df["_name"]
    else:
        # For sovereign ETFs use Location column
        df["_group"] = df[loc_col].astype(str).str.strip() if loc_col else "Unknown"

    df = df.dropna(subset=["_duration", "_ytm"])
    df = df[df["_duration"] > 0]
    df = df[df["_ytm"] > 0]
    df = df[~df["_group"].isin(["", "nan", "N/A", "-"])]
    return df


# ── Build payload for one ETF ─────────────────────────────────────────────────
def build_etf_payload(
    ticker: str, df: pd.DataFrame, as_of: str, fetched_at: str, is_fresh: bool,
    group_by: str = "country",
) -> dict:
    bonds = []
    for _, row in df.iterrows():
        bonds.append(
            {
                "n": row["_name"],
                "g": row["_group"],
                "d": round(float(row["_duration"]), 3),
                "y": round(float(row["_ytm"]), 3),
                "m": round(float(row["_market_value"]), 0),
                "w": round(float(row["_weight"]), 3) if row["_weight"] else 0.0,
                "c": round(float(row["_coupon"]), 3) if pd.notna(row["_coupon"]) else None,
                "t": row["_maturity"],
            }
        )

    if group_by == "issuer":
        # All issuers ranked by total market value (user can search/filter via search bar)
        mv_by_group = df.groupby("_group")["_market_value"].sum().sort_values(ascending=False)
        groups = mv_by_group.index.tolist()
        group_label = "Company"
    else:
        groups = sorted(df["_group"].unique().tolist())
        group_label = "Country"

    return {
        "as_of": as_of,
        "fetched_at": fetched_at,
        "is_fresh": is_fresh,
        "bond_count": len(bonds),
        "group_count": len(df["_group"].unique()),
        "group_label": group_label,
        "groups": groups,
        "bonds": bonds,
    }


# ── Generate HTML ─────────────────────────────────────────────────────────────
def generate_html(all_payloads: dict) -> str:
    data_json = json.dumps(all_payloads, ensure_ascii=False, separators=(",", ":"))

    etf_tabs_html = ""
    for ticker in ETFS:
        if ticker not in all_payloads:
            continue
        etf_tabs_html += f'<button class="etf-tab" data-etf="{ticker}">{ticker}</button>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EM Bond ETF Holdings — Duration vs Yield</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  :root {{
    --forest: #1a3a2f;
    --forest-light: #2d5a47;
    --cream: #faf9f7;
    --charcoal: #1a1a1a;
    --warm-gray: #6b6b6b;
    --c1: #0072B2;
    --c2: #E69F00;
    --c3: #009E73;
    --c4: #CC79A7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; background: var(--cream); color: var(--charcoal); }}

  .page-header {{
    background: linear-gradient(135deg, var(--forest) 0%, var(--forest-light) 100%);
    color: #fff;
    padding: 20px 32px 16px;
  }}
  .page-header h1 {{ font-size: 1.4rem; font-weight: 700; }}
  .page-header p {{ font-size: 0.82rem; opacity: 0.75; margin-top: 3px; }}

  /* ETF tab bar */
  .etf-bar {{
    display: flex; gap: 6px; margin-top: 14px; flex-wrap: wrap;
  }}
  .etf-tab {{
    cursor: pointer;
    padding: 6px 16px;
    border-radius: 6px;
    font-size: 0.82rem;
    font-weight: 600;
    border: 1.5px solid rgba(255,255,255,0.3);
    background: rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.75);
    transition: all 0.15s;
    letter-spacing: 0.02em;
  }}
  .etf-tab:hover {{ background: rgba(255,255,255,0.2); color: #fff; }}
  .etf-tab.active {{ background: #fff; color: var(--forest); border-color: #fff; }}
  .etf-tab.unavailable {{ opacity: 0.35; cursor: not-allowed; }}

  /* Fund label strip */
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

  /* Country selector */
  .selector-panel {{
    background: #fff; border: 1px solid #e4e8ef; border-radius: 10px;
    padding: 14px 18px; margin-bottom: 14px;
  }}
  .selector-panel h3 {{
    font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--warm-gray); margin-bottom: 8px; font-weight: 600;
  }}
  .selector-hint {{ font-size: 0.73rem; color: var(--warm-gray); margin-bottom: 8px; }}
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
  .country-pills {{
    display: flex; flex-wrap: wrap; gap: 5px;
    max-height: 180px; overflow-y: auto; padding: 2px;
  }}
  .pill {{
    cursor: pointer; padding: 3px 11px; border-radius: 999px;
    font-size: 0.76rem; font-weight: 500;
    border: 1.5px solid #dde3ec; background: #f8f9fc; color: var(--charcoal);
    transition: all 0.13s; user-select: none;
  }}
  .pill:hover {{ border-color: #aab3c8; background: #eef1f7; }}
  .pill.active-0 {{ background: var(--c1); border-color: var(--c1); color: #fff; }}
  .pill.active-1 {{ background: var(--c2); border-color: var(--c2); color: #fff; }}
  .pill.active-2 {{ background: var(--c3); border-color: var(--c3); color: #fff; }}
  .pill.active-3 {{ background: var(--c4); border-color: var(--c4); color: #fff; }}
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
  <h1>&#128200; EM Bond ETF Holdings — Duration vs Yield</h1>
  <p>Select a fund below, then choose up to 4 countries/sectors to compare on the bubble chart.</p>
  <div class="etf-bar">
    {etf_tabs_html}
  </div>
</header>

<div class="fund-strip">
  <span class="fund-name" id="fund-name">—</span>
  <span id="fund-badge" class="badge"></span>
  <span id="fund-holdings-date" style="margin-left:auto"></span>
</div>

<main class="main">
  <div class="stats-row" id="stats-row"></div>

  <div class="selector-panel">
    <h3 id="selector-heading">Select to Display</h3>
    <p class="selector-hint" id="selector-hint">Choose up to <strong>4</strong>. Bubble size = market value.</p>
    <div class="search-wrap">
      <input type="text" id="group-search" placeholder="Search…" autocomplete="off" spellcheck="false">
      <span class="search-clear" id="search-clear" title="Clear">&#x2715;</span>
    </div>
    <div class="country-pills" id="country-pills"></div>
  </div>

  <div class="chart-card">
    <div id="bubble-chart"></div>
  </div>

  <div class="page-footer">
    <div id="footer-left"></div>
    <div>Source: <a href="https://www.ishares.com/us/" target="_blank" rel="noopener">iShares</a> &nbsp;|&nbsp; Fixed income holdings only &nbsp;|&nbsp; Bubble size = market value</div>
  </div>
</main>

<script>
const ALL_DATA = {data_json};
const ETF_META = {{
  "EMB":  {{ label:"EMB",  name:"iShares J.P. Morgan USD Emerging Markets Bond ETF" }},
  "CEMB": {{ label:"CEMB", name:"iShares J.P. Morgan EM Corporate Bond ETF" }},
  "LEMB": {{ label:"LEMB", name:"iShares J.P. Morgan EM Local Currency Bond ETF" }},
  "EMHY": {{ label:"EMHY", name:"iShares J.P. Morgan EM High Yield Bond ETF" }},
  "LQD":  {{ label:"LQD",  name:"iShares iBoxx $ Investment Grade Corporate Bond ETF" }},
  "HYG":  {{ label:"HYG",  name:"iShares iBoxx $ High Yield Corporate Bond ETF" }},
}};
const COLORS = ['#0072B2', '#E69F00', '#009E73', '#CC79A7'];
const MAX_SEL = 4;

let currentEtf = null;
let selected = [];

// ── Boot ───────────────────────────────────────────────────────────────────
function init() {{
  // Mark unavailable tabs
  document.querySelectorAll('.etf-tab').forEach(btn => {{
    const etf = btn.dataset.etf;
    if (!ALL_DATA[etf] || !ALL_DATA[etf].bonds.length) {{
      btn.classList.add('unavailable');
    }}
    btn.addEventListener('click', () => {{
      if (!btn.classList.contains('unavailable')) switchEtf(etf);
    }});
  }});

  // Search input — filter pills on keystroke
  const searchEl = document.getElementById('group-search');
  const clearEl  = document.getElementById('search-clear');
  searchEl.addEventListener('input', () => {{
    clearEl.classList.toggle('visible', searchEl.value.length > 0);
    if (currentEtf) renderPills(ALL_DATA[currentEtf]);
  }});
  clearEl.addEventListener('click', () => {{
    searchEl.value = '';
    clearEl.classList.remove('visible');
    if (currentEtf) renderPills(ALL_DATA[currentEtf]);
    searchEl.focus();
  }});

  // Activate first available
  const first = Object.keys(ALL_DATA).find(k => ALL_DATA[k] && ALL_DATA[k].bonds.length);
  if (first) switchEtf(first);
}}

function switchEtf(etf) {{
  currentEtf = etf;
  selected = [];
  // Clear search when switching funds
  const searchEl = document.getElementById('group-search');
  searchEl.value = '';
  document.getElementById('search-clear').classList.remove('visible');

  // Update tabs
  document.querySelectorAll('.etf-tab').forEach(b => b.classList.toggle('active', b.dataset.etf === etf));

  // Update fund strip
  const meta = ETF_META[etf] || {{}};
  const payload = ALL_DATA[etf];
  document.getElementById('fund-name').textContent = meta.name || etf;

  const badge = document.getElementById('fund-badge');
  if (payload.is_fresh) {{
    badge.className = 'badge badge-fresh';
    badge.textContent = 'Live';
  }} else {{
    badge.className = 'badge badge-stale';
    badge.textContent = 'Cached';
  }}

  const hd = document.getElementById('fund-holdings-date');
  hd.textContent = payload.as_of ? `Holdings: ${{payload.as_of}}` : '';

  // Update selector heading based on group type
  const groupLabel = payload.group_label || 'Country';
  document.getElementById('selector-heading').textContent = `Select ${{groupLabel === 'Company' ? 'Companies' : 'Countries'}} to Display`;
  document.getElementById('selector-hint').innerHTML =
    `Choose up to <strong>4</strong> ${{groupLabel === 'Company' ? 'companies' : 'countries'}}. Bubble size = market value.`;

  // Pick 4 largest defaults
  const ranked = rankGroups(payload);
  ranked.slice(0, MAX_SEL).forEach(d => {{ if (selected.length < MAX_SEL) selected.push(d.group); }});

  renderStats(payload);
  renderPills(payload);
  renderChart(payload);
  updateFooter(payload);
}}

// ── Stats ──────────────────────────────────────────────────────────────────
function renderStats(payload) {{
  const bonds = payload.bonds;
  const totalMV = bonds.reduce((s, b) => s + (b.m || 0), 0);
  const wtAvgDur = wavg(bonds, 'd', 'm');
  const wtAvgYTM = wavg(bonds, 'y', 'm');
  document.getElementById('stats-row').innerHTML = `
    <div class="stat-card"><div class="stat-label">Holdings</div><div class="stat-value">${{payload.bond_count}}</div><div class="stat-sub">bonds</div></div>
    <div class="stat-card"><div class="stat-label">Groups</div><div class="stat-value">${{payload.group_count}}</div><div class="stat-sub">countries / sectors</div></div>
    <div class="stat-card"><div class="stat-label">Avg Duration</div><div class="stat-value">${{wtAvgDur.toFixed(1)}}y</div><div class="stat-sub">MV-weighted</div></div>
    <div class="stat-card"><div class="stat-label">Avg YTM</div><div class="stat-value">${{wtAvgYTM.toFixed(2)}}%</div><div class="stat-sub">MV-weighted</div></div>
    <div class="stat-card"><div class="stat-label">Total MV</div><div class="stat-value">${{fmtMV(totalMV)}}</div><div class="stat-sub">shown holdings</div></div>
  `;
}}

function wavg(bonds, field, wField) {{
  let sw = 0, swx = 0;
  bonds.forEach(b => {{ const w = b[wField] || 0; sw += w; swx += w * (b[field] || 0); }});
  return sw > 0 ? swx / sw : 0;
}}

function fmtMV(v) {{
  if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(0) + 'M';
  return v.toFixed(0);
}}

// ── Pills ──────────────────────────────────────────────────────────────────
function getSearchQuery() {{
  return document.getElementById('group-search').value.trim().toLowerCase();
}}

function renderPills(payload) {{
  const container = document.getElementById('country-pills');
  const query = getSearchQuery();
  container.innerHTML = '';

  const visible = payload.groups.filter(g =>
    !query || g.toLowerCase().includes(query)
  );

  if (visible.length === 0) {{
    const msg = document.createElement('span');
    msg.className = 'no-results';
    msg.textContent = 'No matches';
    container.appendChild(msg);
    return;
  }}

  visible.forEach(group => {{
    const idx = selected.indexOf(group);
    const isActive = idx >= 0;
    const isDisabled = !isActive && selected.length >= MAX_SEL;
    const pill = document.createElement('span');
    pill.className = 'pill' + (isActive ? ' active-' + idx : '') + (isDisabled ? ' disabled' : '');
    pill.textContent = group;
    pill.addEventListener('click', () => onPillClick(group, payload));
    container.appendChild(pill);
  }});
}}

function onPillClick(group, payload) {{
  const idx = selected.indexOf(group);
  if (idx >= 0) {{
    selected.splice(idx, 1);
  }} else {{
    if (selected.length >= MAX_SEL) return;
    selected.push(group);
  }}
  renderPills(payload);
  renderChart(payload);
}}

function rankGroups(payload) {{
  const mv = {{}};
  payload.bonds.forEach(b => {{ mv[b.g] = (mv[b.g] || 0) + b.m; }});
  return Object.entries(mv).map(([group, total]) => ({{ group, total }})).sort((a, b) => b.total - a.total);
}}

// ── Chart ──────────────────────────────────────────────────────────────────
function renderChart(payload) {{
  if (selected.length === 0) {{
    Plotly.react('bubble-chart', [], getLayout('Select groups above to display bonds'));
    return;
  }}

  const allBonds = payload.bonds.filter(b => selected.includes(b.g));
  const maxMV = Math.max(...allBonds.map(b => b.m || 1), 1);

  const traces = selected.map((group, colorIdx) => {{
    const bonds = payload.bonds.filter(b => b.g === group);
    if (!bonds.length) return null;
    return {{
      type: 'scatter',
      mode: 'markers',
      name: group,
      x: bonds.map(b => b.d),
      y: bonds.map(b => b.y),
      text: bonds.map(b =>
        `<b>${{b.n}}</b><br>`
        + `Duration: ${{b.d.toFixed(1)}}y<br>`
        + `YTM: ${{b.y.toFixed(2)}}%<br>`
        + (b.c != null ? `Coupon: ${{b.c.toFixed(2)}}%<br>` : '')
        + (b.t ? `Maturity: ${{b.t}}<br>` : '')
        + `Market Value: $${{fmtMV(b.m)}}<br>`
        + `Weight: ${{b.w.toFixed(2)}}%`
      ),
      hovertemplate: '%{{text}}<extra>' + group + '</extra>',
      marker: {{
        size: bonds.map(b => Math.max(Math.sqrt((b.m || 1) / maxMV) * 60, 4)),
        sizemode: 'diameter',
        color: COLORS[colorIdx],
        opacity: 0.72,
        line: {{ color: 'rgba(255,255,255,0.55)', width: 1 }},
      }},
    }};
  }}).filter(Boolean);

  Plotly.react('bubble-chart', traces, getLayout());
}}

function getLayout(annotation) {{
  const layout = {{
    xaxis: {{ title: 'Duration (years)', gridcolor: 'rgba(200,200,200,0.4)', zeroline: false }},
    yaxis: {{ title: 'Yield to Maturity (%)', gridcolor: 'rgba(200,200,200,0.4)', zeroline: false }},
    plot_bgcolor: '#fff', paper_bgcolor: '#fff',
    margin: {{ l: 60, r: 30, t: 30, b: 60 }},
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
function updateFooter(payload) {{
  let ts = payload.fetched_at || '';
  try {{
    const dt = new Date(ts);
    ts = dt.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  }} catch(e) {{}}
  const dotClass = payload.is_fresh ? 'dot-fresh' : 'dot-stale';
  const msg = payload.is_fresh
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
    all_payloads = {}

    print("Fetching iShares ETF holdings…")
    for ticker, etf in ETFS.items():
        csv_text, is_fresh = fetch_csv(ticker, etf)
        if not csv_text:
            continue
        try:
            group_by = etf.get("group_by", "country")
            df, as_of = parse_csv(csv_text)
            print(f"    {ticker}: header found, as-of={as_of or 'unknown'}, group_by={group_by}")
            df = clean_data(df, group_by=group_by)
            print(f"    {ticker}: {len(df)} valid bonds")
            all_payloads[ticker] = build_etf_payload(
                ticker, df, as_of, fetched_at, is_fresh, group_by=group_by
            )
        except Exception as e:
            print(f"    {ticker}: parse/clean error — {e}", file=sys.stderr)

    if not all_payloads:
        raise RuntimeError("No ETF data could be loaded")

    html = generate_html(all_payloads)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\nSaved → {OUTPUT_FILE}  ({len(html):,} chars, {len(all_payloads)} ETFs)")


if __name__ == "__main__":
    main()
