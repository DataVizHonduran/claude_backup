"""
Inflation Pressures Heat Map — replicates SF Fed / Daly (Hoover 2026) slide.
Pulls 11 indicators from FRED, NY Fed, KC Fed, Cleveland Fed, SF Fed, yfinance.
Outputs: reports/inflation-pressures/index.html
"""
import io
import os
import re
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf
from fredapi import Fred

warnings.filterwarnings("ignore")

# ── config ──────────────────────────────────────────────────────────────────
FRED_API_KEY    = os.environ.get("FRED_API_KEY")
START_HIST      = "2016-01-01"   # fetch from here (covers 2017 display)
BASELINE_START  = "2018-01-01"   # z-score normalization window start
BASELINE_END    = "2024-12-31"   # z-score normalization window end
START_DISPLAY   = "2017-01-01"   # earliest selectable date in the UI
END_DISPLAY     = "2026-04-30"   # latest date shown
DEFAULT_START_YEAR = 2025        # default view on page load

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reports", "inflation-pressures", "index.html",
)

# ── helpers ──────────────────────────────────────────────────────────────────
def fetch_xlsx(url: str, **kwargs) -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return pd.read_excel(io.BytesIO(r.content), **kwargs)


def to_monthly(s: pd.Series) -> pd.Series:
    """Resample to month-start frequency, forward-fill up to 1 period."""
    return s.resample("MS").last().ffill(limit=1)


def zscore(s: pd.Series) -> pd.Series:
    """Z-score relative to BASELINE_START–BASELINE_END window."""
    base = s[(s.index >= BASELINE_START) & (s.index <= BASELINE_END)]
    mu, sigma = base.mean(), base.std()
    if sigma == 0 or np.isnan(sigma):
        return pd.Series(np.nan, index=s.index)
    return (s - mu) / sigma


# ── data fetchers ────────────────────────────────────────────────────────────
def get_fred_series(fred: Fred, series_id: str, name: str) -> pd.Series:
    raw = fred.get_series(series_id, observation_start=START_HIST)
    s = pd.Series(raw, name=name)
    s.index = pd.to_datetime(s.index)
    return to_monthly(s)


def get_import_prices(fred: Fred) -> pd.Series:
    """BLS Import Price Index (All Commodities) — FRED IR."""
    return get_fred_series(fred, "IR", "import_prices")


def get_crude_oil(fred: Fred) -> pd.Series:
    """WTI crude oil monthly average — proxy for 3-6m futures."""
    return get_fred_series(fred, "MCOILWTICO", "crude_oil")


def get_aluminum(fred: Fred) -> pd.Series:
    """Global price of aluminum (USD/metric ton) — FRED PALUMUSDM."""
    return get_fred_series(fred, "PALUMUSDM", "aluminum")


def get_vac_unemp_ratio(fred: Fred) -> pd.Series:
    """Vacancy-to-unemployment ratio: JTSJOL / UNRATE."""
    jol  = get_fred_series(fred, "JTSJOL", "jolts")   # thousands
    unemp = get_fred_series(fred, "UNEMPLOY", "unemployed")  # thousands
    ratio = (jol / unemp).rename("vac_unemp")
    return to_monthly(ratio)


def get_gscpi() -> pd.Series:
    """NY Fed Global Supply Chain Pressure Index (OLE2 .xls despite .xlsx extension)."""
    url = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), sheet_name="GSCPI Monthly Data",
                       engine="xlrd", header=None)
    # Row 0 = header, rows 1-4 = blank/metadata, row 5+ = data
    data = df.iloc[5:].reset_index(drop=True)
    data.columns = ["date", "gscpi"] + [f"_c{i}" for i in range(len(data.columns) - 2)]
    data["date"] = pd.to_datetime(data["date"], dayfirst=True)
    s = pd.Series(pd.to_numeric(data["gscpi"], errors="coerce").values,
                  index=data["date"], name="gscpi")
    s = s.dropna()
    s.index = s.index.to_period("M").to_timestamp()
    return to_monthly(s)


def _parse_frbsf_dates(col: pd.Series) -> pd.DatetimeIndex:
    """Parse SF Fed date format '2021m3' → datetime."""
    import re
    def _parse(s):
        m = re.match(r"(\d{4})m(\d+)", str(s))
        if m:
            return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1)
        return pd.NaT
    return pd.DatetimeIndex([_parse(v) for v in col])


def _fetch_frbsf_pce_csv(url: str, col: str) -> pd.Series:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    dates = _parse_frbsf_dates(df.iloc[:, 0])
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").values, index=dates)
    return to_monthly(s.dropna())


def get_sf_fed_supply_pce() -> pd.Series:
    """
    SF Fed headline supply-driven PCE — proxy for SF Fed inflation shock
    momentum index (wp2026-10 has no public data series yet).
    """
    url = "https://www.frbsf.org/wp-content/uploads/supply-demand-pce-headline-monthly-chart-1.csv"
    return _fetch_frbsf_pce_csv(url, "Supply-driven Inflation").rename("sf_ism_proxy")


def get_core_goods_pce_share() -> pd.Series:
    """
    Proxy for 'core goods as share of total PCE inflation'.
    Uses SF Fed core PCE supply-driven contribution (tariff/supply shocks
    drive core goods prices).
    """
    url = "https://www.frbsf.org/wp-content/uploads/supply-demand-pce-core-monthly-chart-2.csv"
    return _fetch_frbsf_pce_csv(url, "Supply-driven Inflation").rename("core_goods_pce")


def get_hpw_tightness(fred: Fred) -> pd.Series:
    """
    Proxy for NY Fed HPW Labor Market Tightness Index.
    HPW = f(quits rate, V/effective searchers). JOLTS quits rate is the
    dominant input and is publicly available. No direct XLSX download exists
    for the HPW series itself.
    """
    return get_fred_series(fred, "JTSQUR", "hpw_tightness")


def get_kc_lmci(fred: Fred) -> pd.Series:
    """Kansas City Fed LMCI Level of Activity Index — FRED FRBKCLMCILA."""
    return get_fred_series(fred, "FRBKCLMCILA", "kc_lmci")


def get_nyfed_3yr_expectations() -> pd.Series:
    """NY Fed SCE 3-year consumer inflation expectations (median)."""
    url = "https://www.newyorkfed.org/medialibrary/interactives/sce/sce/downloads/data/frbny-sce-data.xlsx"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    # header=None; row 3 = column labels, row 4+ = data (YYYYMM dates)
    df = pd.read_excel(io.BytesIO(r.content), sheet_name="Inflation expectations", header=None)
    headers = df.iloc[3].tolist()
    data = df.iloc[4:].reset_index(drop=True)
    data.columns = headers
    date_col = data.columns[0]
    # Col 2 = "Median three-year ahead expected inflation rate"
    val_col = data.columns[2]
    dates = pd.to_datetime(data[date_col].astype(str).str.strip(), format="%Y%m", errors="coerce")
    s = pd.Series(pd.to_numeric(data[val_col], errors="coerce").values,
                  index=dates, name="nyfed_3yr").dropna()
    return to_monthly(s)


def get_cleveland_1yr_biz() -> pd.Series:
    """Cleveland Fed SoFIE 1-year business inflation expectations (mean %)."""
    url = "https://www.clevelandfed.org/-/media/files/webcharts/survey_of_firms/sofie_statistics.xlsx"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    # header=None; row 4 = column labels, row 5+ = data (YYYY.Q dates)
    df = pd.read_excel(io.BytesIO(r.content), sheet_name=0, header=None)
    data = df.iloc[5:].reset_index(drop=True)
    data.columns = ["date", "mean_pct", "std"]
    def _parse_yyyyq(s):
        try:
            yr, q = str(s).split(".")
            month = (int(q) - 1) * 3 + 1
            return pd.Timestamp(int(yr), month, 1)
        except Exception:
            return pd.NaT
    dates = pd.DatetimeIndex([_parse_yyyyq(v) for v in data["date"]])
    s = pd.Series(pd.to_numeric(data["mean_pct"], errors="coerce").values,
                  index=dates, name="cleveland_1yr").dropna()
    return to_monthly(s)


# ── heat map rendering ────────────────────────────────────────────────────────
COLORSCALE = [
    [0.0,  "#8B1A1A"],   # dark red — strongly inflationary
    [0.25, "#D97B7B"],   # light red
    [0.50, "#F5F0E8"],   # cream — neutral
    [0.75, "#9DC98D"],   # light green
    [1.0,  "#2D6E2D"],   # dark green — disinflationary
]

ROWS = [
    # (display_label, category_label, series_key)
    ("Core goods as share of total PCE inflation", "Tariff\nshock", "core_goods_pce"),
    ("Import prices index",                        "Tariff\nshock", "import_prices"),
    ("Crude oil futures prices (3–6 months ahead)","Oil\nshock",   "crude_oil"),
    ("NY Fed's global supply chain pressure index","Oil\nshock",   "gscpi"),
    ("SF Fed's inflation shock momentum index*",   "Both\nshocks", "sf_ism_proxy"),
    ("Global commodities prices (e.g., aluminum)", "Both\nshocks", "aluminum"),
    ("Vacancy-to-unemployment ratio",              "",             "vac_unemp"),
    ("NY Fed's labor market tightness index",      "",             "hpw_tightness"),
    ("Kansas City Fed's labor market conditions",  "",             "kc_lmci"),
    ("NY Fed's 3-year inflation expectations (consumers)", "",     "nyfed_3yr"),
    ("Cleveland Fed's 1-year expectations (businesses)",   "",     "cleveland_1yr"),
]


def zscore_to_color(z: float) -> float:
    """Map z-score → [0,1] for colorscale (clamped to ±2.5σ)."""
    # High z = inflationary = dark red = 0; low z = green = 1
    clamped = max(-2.5, min(2.5, z))
    return 0.5 - clamped / 5.0  # 0 when z=2.5, 1 when z=-2.5


def interp_color(v: float) -> str:
    """Map [0,1] value → hex color via COLORSCALE."""
    v = max(0.0, min(1.0, v))
    for k in range(len(COLORSCALE) - 1):
        lo, c1 = COLORSCALE[k]
        hi, c2 = COLORSCALE[k + 1]
        if lo <= v <= hi:
            t = (v - lo) / (hi - lo)
            r1, g1, b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
            r2, g2, b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
            return "#{:02x}{:02x}{:02x}".format(
                int(r1 + t*(r2-r1)), int(g1 + t*(g2-g1)), int(b1 + t*(b2-b1))
            )
    return COLORSCALE[-1][1]


def build_json_data(data: dict) -> list:
    """
    Build JSON-serialisable list of row objects covering the full display range.
    Each row: {label, cat, months: ["YYYY-MM",...], colors: ["#hex",...], zscores: [float|null,...]}
    """
    import json
    months = pd.date_range(START_DISPLAY, END_DISPLAY, freq="MS")
    month_strs = [m.strftime("%Y-%m") for m in months]

    rows_out = []
    for label, cat, key in ROWS:
        colors  = ["#f5f0e8"] * len(months)   # neutral default
        zscores = [None]       * len(months)

        if key in data:
            s  = data[key]
            zs = zscore(s)
            for j, m in enumerate(months):
                diffs = abs(s.index - m)
                idx   = diffs.argmin()
                if diffs[idx].days > 45:
                    continue
                z_val = zs.iloc[idx]
                if np.isnan(z_val):
                    continue
                z_f = round(float(z_val), 2)
                zscores[j] = z_f
                colors[j]  = interp_color(zscore_to_color(z_f))

        rows_out.append({"label": label, "cat": cat,
                         "colors": colors, "zscores": zscores})

    return month_strs, rows_out


def render(data: dict) -> str:
    import json as _json

    now_str = datetime.now().strftime("%Y-%m-%d")
    month_strs, rows_json = build_json_data(data)

    # Category rowspan map (fixed — doesn't change with date range)
    cat_rowspans = {}
    prev_cat = None
    for i, (_, cat, _) in enumerate(ROWS):
        if cat and cat != prev_cat:
            span = sum(1 for r in ROWS[i:] if r[1] == cat)
            cat_rowspans[i] = (cat, span)
            prev_cat = cat
        elif not cat:
            prev_cat = None

    # Serialise to JS
    js_months    = _json.dumps(month_strs)
    js_rows      = _json.dumps(rows_json)
    js_cat_spans = _json.dumps({str(k): list(v) for k, v in cat_rowspans.items()})
    js_default   = DEFAULT_START_YEAR

    # Build year options for the selector
    years = sorted({int(m[:4]) for m in month_strs})
    year_options = "\n".join(
        f'<option value="{y}"{" selected" if y == DEFAULT_START_YEAR else ""}>{y}</option>'
        for y in years
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inflation Pressures Heat Map | boquin.xyz</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ text-align: center; color: #0a3161; font-size: 1.6rem; margin-bottom: 4px; }}
  .subtitle {{ text-align: center; color: #1a6b9a; font-size: 1.1rem; margin-bottom: 12px; }}
  .controls {{ text-align: center; margin-bottom: 14px; }}
  .controls label {{ font-size: 0.85rem; color: #444; margin-right: 6px; }}
  .controls select {{ font-size: 0.85rem; padding: 3px 8px; border: 1px solid #aaa;
                      border-radius: 4px; background: #fff; cursor: pointer; }}
  .source-note {{ font-size: 0.72rem; color: #666; text-align: center; margin-bottom: 14px; line-height: 1.5; }}
  .tbl-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; background: #fff; border: 1px solid #ccc; }}
  .ind-label {{ font-size: 0.78rem; padding: 5px 8px; text-align: left; white-space: nowrap;
                min-width: 260px; border-bottom: 1px solid #e0e0e0; }}
  .cat-label {{ font-size: 0.8rem; font-weight: bold; padding: 5px 8px; text-align: center;
                border-left: 2px solid #0a3161; border-bottom: 1px solid #e0e0e0;
                vertical-align: middle; white-space: pre-line; min-width: 62px; }}
  .yr-header {{ background: #0a3161; color: white; text-align: center;
                font-size: 0.85rem; padding: 6px 4px; }}
  .mo-header {{ background: #1a6b9a; color: white; text-align: center;
                font-size: 0.72rem; padding: 4px 2px; min-width: 36px; }}
  .cell {{ width: 36px; height: 26px; border: 1px solid rgba(255,255,255,0.4); cursor: default; }}
  .legend {{ display: flex; align-items: center; justify-content: center;
             gap: 8px; margin-top: 12px; font-size: 0.75rem; color: #444; flex-wrap: wrap; }}
  .leg-box {{ width: 18px; height: 18px; border-radius: 2px; flex-shrink: 0; }}
  .updated {{ text-align: right; font-size: 0.7rem; color: #999; margin-top: 6px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Inflation Pressures Heat Map</h1>
  <div class="subtitle">SF Fed — Daly, Hoover Institution (May 8 2026)</div>

  <div class="controls">
    <label for="startYear">Show from:</label>
    <select id="startYear" onchange="renderTable(+this.value)">
{year_options}
    </select>
  </div>

  <div class="source-note">
    Colors = z-score vs {BASELINE_START[:4]}–{BASELINE_END[:4]} baseline.
    Dark red = strongly inflationary &nbsp;|&nbsp; Dark green = disinflationary.<br>
    *SF Fed ISM proxied with SF Fed supply-driven PCE (wp2026-10 pending public release).
    &nbsp;†NY Fed tightness proxied with JOLTS quits rate (HPW has no direct download).
  </div>

  <div class="tbl-wrap"><table id="heatmap"></table></div>

  <div class="legend">
    <div class="leg-box" style="background:#8B1A1A"></div> Strongly inflationary &nbsp;
    <div class="leg-box" style="background:#D97B7B"></div> Moderately inflationary &nbsp;
    <div class="leg-box" style="background:#F5F0E8"></div> Neutral &nbsp;
    <div class="leg-box" style="background:#9DC98D"></div> Moderately disinflationary &nbsp;
    <div class="leg-box" style="background:#2D6E2D"></div> Strongly disinflationary
  </div>
  <div class="updated">Updated: {now_str} | Sources: FRED, NY Fed, KC Fed, Cleveland Fed, SF Fed</div>
</div>

<script>
const MONTHS   = {js_months};
const ROWS     = {js_rows};
const CAT_SPAN = {js_cat_spans};  // {{rowIndex: [catLabel, span]}}

function renderTable(startYear) {{
  // Filter column indices
  const cols = MONTHS
    .map((m, i) => ({{m, i}}))
    .filter(({{m}}) => +m.slice(0,4) >= startYear);

  // Build year groups for header
  const yearGroups = {{}};
  cols.forEach(({{m, i}}) => {{
    const y = m.slice(0,4);
    if (!yearGroups[y]) yearGroups[y] = [];
    yearGroups[y].push(i);
  }});

  let html = '<thead>';

  // Row 1: "Indicator" + year spans
  html += '<tr>';
  html += '<th class="ind-label" style="background:#0a3161;color:white">Indicator</th>';
  Object.keys(yearGroups).sort().forEach(y => {{
    html += `<th class="yr-header" colspan="${{yearGroups[y].length}}">${{y}}</th>`;
  }});
  html += '</tr>';

  // Row 2: blank + month labels
  html += '<tr>';
  html += '<th class="ind-label" style="background:#1a6b9a"></th>';
  cols.forEach(({{m}}) => {{
    const mo = new Date(m + '-02').toLocaleString('en', {{month: 'short'}});
    html += `<th class="mo-header">${{mo}}</th>`;
  }});
  html += '</tr></thead><tbody>';

  // Data rows
  ROWS.forEach((row, ri) => {{
    html += '<tr>';
    html += `<td class="ind-label">${{row.label}}</td>`;
    if (CAT_SPAN[ri]) {{
      const [cat, span] = CAT_SPAN[ri];
      html += `<td class="cat-label" rowspan="${{span}}">${{cat}}</td>`;
    }}
    cols.forEach(({{i}}) => {{
      const color = row.colors[i];
      const z     = row.zscores[i];
      const tip   = z !== null ? 'z=' + z.toFixed(2) : 'n/a';
      html += `<td class="cell" style="background:${{color}}" title="${{tip}}"></td>`;
    }});
    html += '</tr>';
  }});

  html += '</tbody>';
  document.getElementById('heatmap').innerHTML = html;
}}

renderTable({js_default});
</script>
</body>
</html>"""
    return html


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY not set")
    fred = Fred(api_key=FRED_API_KEY)

    print("Fetching FRED series...")
    data = {}
    data["import_prices"] = get_import_prices(fred)
    data["crude_oil"]     = get_crude_oil(fred)
    data["aluminum"]      = get_aluminum(fred)
    data["vac_unemp"]     = get_vac_unemp_ratio(fred)

    print("Fetching NY Fed GSCPI...")
    data["gscpi"] = get_gscpi()

    print("Fetching SF Fed supply-driven PCE (ISM proxy)...")
    data["sf_ism_proxy"] = get_sf_fed_supply_pce()

    print("Fetching SF Fed core goods PCE...")
    data["core_goods_pce"] = get_core_goods_pce_share()

    print("Fetching NY Fed HPW tightness index (proxy: JOLTS quits rate)...")
    data["hpw_tightness"] = get_hpw_tightness(fred)

    print("Fetching KC Fed LMCI...")
    data["kc_lmci"] = get_kc_lmci(fred)

    print("Fetching NY Fed SCE 3-year expectations...")
    data["nyfed_3yr"] = get_nyfed_3yr_expectations()

    print("Fetching Cleveland Fed SoFIE 1-year expectations...")
    data["cleveland_1yr"] = get_cleveland_1yr_biz()

    print("Rendering heat map...")
    html = render(data)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
