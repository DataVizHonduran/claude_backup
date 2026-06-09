"""
SPF Forecast Evolution Dashboard — Multi-Variable
--------------------------------------------------
Downloads Philadelphia Fed Survey of Professional Forecasters mean
forecast files for 8 macro variables and renders a single interactive
HTML dashboard with dropdowns to switch variable, start year, and
y-axis percentile clipping.

Column conventions
  Growth files (RGDP, NGDP, PGDP):
    DXXX2 … DXXX6  →  target year = YEAR + (horizon − 2)
  Level/rate files (CPI, PCE, UNEMP, TBILL, TBOND):
    XXXA … XXXD    →  target year = YEAR + offset (A=0, B=1, C=2, D=3)
    CPI/PCE only have A/B/C (3 horizons)

No API key required.
Output: reports/spf-gdp-vintages/index.html
"""

import io
import re
import json
import colorsys
import numpy as np
import requests
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "survey-of-professional-forecasters/data-files/files/"
)

VARIABLES: dict[str, tuple] = {
    "RGDP":  ("Real GDP Growth",      "Mean_RGDP_Growth.xlsx", {"DRGDP2":0,"DRGDP3":1,"DRGDP4":2,"DRGDP5":3,"DRGDP6":4}, "% (YoY)",     True),
    "NGDP":  ("Nominal GDP Growth",   "Mean_NGDP_Growth.xlsx", {"DNGDP2":0,"DNGDP3":1,"DNGDP4":2,"DNGDP5":3,"DNGDP6":4}, "% (YoY)",     True),
    "PGDP":  ("GDP Price Deflator",   "Mean_PGDP_Growth.xlsx", {"DPGDP2":0,"DPGDP3":1,"DPGDP4":2,"DPGDP5":3,"DPGDP6":4}, "% (YoY)",     False),
    "CPI":   ("CPI Inflation",        "Mean_CPI_Level.xlsx",   {"CPIA":0,"CPIB":1,"CPIC":2},                               "Ann. avg. %", False),
    "PCE":   ("PCE Inflation",        "Mean_PCE_Level.xlsx",   {"PCEA":0,"PCEB":1,"PCEC":2},                               "Ann. avg. %", False),
    "UNEMP": ("Unemployment Rate",    "Mean_UNEMP_Level.xlsx", {"UNEMPA":0,"UNEMPB":1,"UNEMPC":2,"UNEMPD":3},              "Ann. avg. %", False),
    "TBILL": ("3-Month T-Bill Rate",  "Mean_TBILL_Level.xlsx", {"TBILLA":0,"TBILLB":1,"TBILLC":2,"TBILLD":3},              "Ann. avg. %", False),
    "TBOND": ("10-Year T-Bond Yield", "Mean_TBOND_Level.xlsx", {"TBONDA":0,"TBONDB":1,"TBONDC":2,"TBONDD":3},              "Ann. avg. %", False),
}

# Every 2 years for distant history, every year for recent vintages
TARGET_YEARS = list(range(1990, datetime.now().year + 4))

# Start-year dropdown: (option value, display label)
START_YEAR_OPTIONS = [
    ("1990", "1990 — full history"),
    ("2000", "2000 — last 25 yrs"),
    ("2006", "2006 — last 20 yrs"),
    ("2010", "2010 — last 15 yrs"),
    ("2015", "2015 — last 10 yrs"),
    ("2018", "2018 — last 7 yrs"),
    ("2020", "2020 — last 5 yrs"),
]
DEFAULT_START_YEAR = "2006"

# Y-axis clipping dropdown: (option key, label, (lo_pct, hi_pct))
Y_CLIP_OPTIONS = [
    ("all",  "All data",     (0,    100)),
    ("p99",  "99% of data",  (0.5,  99.5)),
    ("p95",  "95% of data",  (2.5,  97.5)),
    ("p90",  "90% of data",  (5,    95)),
    ("p80",  "80% of data",  (10,   90)),
]
DEFAULT_Y_CLIP = "p90"

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "spf-gdp-vintages"
OUTPUT_FILE = OUTPUT_DIR / "index.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Color gradient: old vintages muted blue-grey → recent vivid red
# ---------------------------------------------------------------------------
def build_palette(years: list[int]) -> dict[int, str]:
    n = len(years)
    colors = {}
    for i, yr in enumerate(years):
        t = i / max(n - 1, 1)
        h = 0.62 * (1 - t)
        s = 0.30 + 0.65 * t
        v = 0.62 + 0.30 * t
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        colors[yr] = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    return colors

PALETTE = build_palette(TARGET_YEARS)

def line_width(yr: int) -> float:
    return 2.5 if yr >= 2020 else (1.8 if yr >= 2015 else 1.2)

def marker_size(yr: int) -> int:
    return 6 if yr >= 2020 else (4 if yr >= 2015 else 3)


# ---------------------------------------------------------------------------
# Quarter label → ISO date string (so Plotly uses a real date axis)
# "2006-Q1" → "2006-01-01"
# ---------------------------------------------------------------------------
QUARTER_MONTHS = {"1": "01", "2": "04", "3": "07", "4": "10"}

def qlabel_to_date(label: str) -> str:
    year, q = label.split("-Q")
    return f"{year}-{QUARTER_MONTHS[q]}-01"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_variable(var_key: str, filename: str, col_map: dict[str, int]) -> dict[int, pd.Series]:
    url = BASE_URL + filename
    print(f"  Fetching {var_key} … {filename}")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    if "html" in r.headers.get("content-type", ""):
        raise RuntimeError(f"{var_key}: got HTML — URL may have moved: {url}")

    df = pd.ExcelFile(io.BytesIO(r.content)).parse(0)
    vintages: dict[int, list[tuple[str, float]]] = {yr: [] for yr in TARGET_YEARS}

    for _, row in df.iterrows():
        survey_yr = int(row["YEAR"])
        survey_q  = int(row["QUARTER"])
        date_str  = qlabel_to_date(f"{survey_yr}-Q{survey_q}")

        for col, offset in col_map.items():
            if col not in row.index:
                continue
            val = row[col]
            if pd.isna(val):
                continue
            target_yr = survey_yr + offset
            if target_yr in vintages:
                vintages[target_yr].append((date_str, float(val)))

    result = {}
    for yr in TARGET_YEARS:
        pts = sorted(vintages[yr])
        if not pts:
            continue
        s = pd.Series([v for _, v in pts], index=[k for k, _ in pts], name=str(yr))
        result[yr] = s
    return result


def fetch_all() -> dict[str, dict[int, pd.Series]]:
    all_vintages = {}
    for key, (label, fname, col_map, *_) in VARIABLES.items():
        try:
            all_vintages[key] = fetch_variable(key, fname, col_map)
        except Exception as e:
            print(f"  WARNING: skipping {key}: {e}")
            all_vintages[key] = {}
    return all_vintages


# ---------------------------------------------------------------------------
# Percentile bounds per variable (for y-axis clipping dropdown)
# ---------------------------------------------------------------------------
def compute_y_bounds(all_vintages: dict) -> dict[str, dict[str, list[float]]]:
    """
    Returns {var_key: {clip_key: [lo, hi]}} where lo/hi are the percentile
    bounds across ALL data points for that variable.
    """
    bounds = {}
    for var_key, vintages in all_vintages.items():
        all_vals = []
        for s in vintages.values():
            all_vals.extend(s.dropna().tolist())
        if not all_vals:
            bounds[var_key] = {}
            continue
        var_bounds = {}
        for key, _label, (lo_pct, hi_pct) in Y_CLIP_OPTIONS:
            lo = float(np.percentile(all_vals, lo_pct))
            hi = float(np.percentile(all_vals, hi_pct))
            # Add a small 5% padding so lines don't kiss the edge
            pad = (hi - lo) * 0.05
            var_bounds[key] = [round(lo - pad, 2), round(hi + pad, 2)]
        bounds[var_key] = var_bounds
    return bounds


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------
def compute_insights(all_vintages: dict) -> dict[str, list[str]]:
    insights = {}
    for var_key, vintages in all_vintages.items():
        lines = []
        for yr in sorted(vintages.keys(), reverse=True)[:4]:
            s = vintages[yr]
            if len(s) < 3:
                continue
            diff = s.diff()
            worst_q = diff.idxmin()
            worst_val = diff[worst_q]
            if pd.notna(worst_val) and worst_val < 0:
                # Convert date back to quarter label for display
                date_parts = worst_q.split("-")
                q_num = {v: k for k, v in QUARTER_MONTHS.items()}[date_parts[1]]
                q_label = f"{date_parts[0]}-Q{q_num}"
                lines.append(
                    f"<b>{yr}</b>: largest downward revision in <b>{q_label}</b> "
                    f"({worst_val:+.2f} pp)"
                )
        insights[var_key] = lines
    return insights


# ---------------------------------------------------------------------------
# Trace data for JS
# ---------------------------------------------------------------------------
def build_trace_data(all_vintages: dict) -> list[dict]:
    traces = []
    for var_key, vintages in all_vintages.items():
        _, _, _, unit, _ = VARIABLES[var_key]
        for yr in TARGET_YEARS:
            if yr not in vintages:
                continue
            s = vintages[yr]
            traces.append({
                "var":        var_key,
                "year":       yr,
                "x":          list(s.index),          # ISO date strings
                "y":          [round(v, 4) for v in s.values],
                "color":      PALETTE.get(yr, "#888888"),
                "width":      line_width(yr),
                "markerSize": marker_size(yr),
                "name":       str(yr),
                "unit":       unit,
            })
    return traces


# ---------------------------------------------------------------------------
# Special traces: average and current-year
# ---------------------------------------------------------------------------
def build_special_traces(all_vintages: dict) -> list[dict]:
    specials = []
    for var_key, vintages in all_vintages.items():
        _, _, _, unit, _ = VARIABLES[var_key]

        # Average: mean of all target-year forecasts at each survey date
        date_vals: dict[str, list[float]] = {}
        for yr, s in vintages.items():
            for date, val in zip(s.index, s.values):
                date_vals.setdefault(date, []).append(float(val))
        avg_dates = sorted(date_vals.keys())
        specials.append({
            "var":  var_key,
            "mode": "avg",
            "x":    avg_dates,
            "y":    [round(sum(date_vals[d]) / len(date_vals[d]), 4) for d in avg_dates],
            "unit": unit,
        })

        # Current year: forecast where target_year == survey_year (offset = 0)
        curr_pts = []
        for yr, s in vintages.items():
            for date, val in zip(s.index, s.values):
                if int(date[:4]) == yr:
                    curr_pts.append((date, round(float(val), 4)))
        curr_pts.sort()
        specials.append({
            "var":  var_key,
            "mode": "current",
            "x":    [p[0] for p in curr_pts],
            "y":    [p[1] for p in curr_pts],
            "unit": unit,
        })

    return specials


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPF Forecast Vintages</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'DM Sans', system-ui, sans-serif;
            background: #f5f5f5;
            color: #1a1a1a;
            padding: 24px 16px;
        }}
        .container {{ max-width: 1160px; margin: 0 auto; }}
        .header {{ margin-bottom: 16px; }}
        .page-title {{ font-size: 1.1rem; font-weight: 600; color: #1a3a2f; margin-bottom: 4px; }}
        .subtitle {{ font-size: 0.87rem; color: #555; line-height: 1.5; }}
        .controls {{
            display: flex; align-items: center; gap: 16px;
            margin-bottom: 14px; flex-wrap: wrap;
        }}
        .control-group {{ display: flex; align-items: center; gap: 8px; }}
        .control-group label {{ font-size: 0.85rem; font-weight: 500; color: #333; white-space: nowrap; }}
        .ctrl-select {{
            font-family: inherit; font-size: 0.88rem;
            border: 1px solid #ccc; border-radius: 6px;
            padding: 5px 10px; background: white;
            cursor: pointer; color: #1a1a1a;
        }}
        #varSelect {{ min-width: 200px; }}
        #startYearSelect {{ min-width: 185px; }}
        #yClipSelect {{ min-width: 150px; }}
        #modeSelect {{ min-width: 160px; }}
        .ctrl-select:focus {{ outline: 2px solid #1a3a2f; border-color: transparent; }}
        .chart-card {{
            background: white; border-radius: 10px;
            box-shadow: 0 1px 6px rgba(0,0,0,0.09);
            padding: 16px; margin-bottom: 16px;
        }}
        #spf-chart {{ width: 100%; }}
        .insight-section {{ display: none; }}
        .insight-section.active {{
            display: block;
            background: #f0f7f4;
            border-left: 4px solid #1a3a2f;
            border-radius: 6px;
            padding: 13px 17px;
            margin-bottom: 16px;
        }}
        .insight-section h3 {{
            font-size: 0.91rem; font-weight: 600; color: #1a3a2f; margin-bottom: 7px;
        }}
        .insight-section ul {{ list-style: disc; padding-left: 17px; }}
        .insight-section li {{
            font-size: 0.84rem; color: #333; margin-bottom: 3px; line-height: 1.5;
        }}
        .methodology {{
            background: white; border-radius: 8px;
            padding: 12px 16px; margin-bottom: 16px;
            font-size: 0.80rem; color: #666; line-height: 1.6;
            box-shadow: 0 1px 4px rgba(0,0,0,0.07);
        }}
        .methodology strong {{ color: #1a3a2f; }}
        .source-note {{ font-size: 0.76rem; color: #999; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <p class="page-title">Survey of Professional Forecasters — Forecast Vintage Evolution</p>
        <p class="subtitle">Each line traces how the consensus forecast for a given calendar year
        evolved across successive survey quarters. Older vintages are muted; recent ones are bold.
        Click legend entries to show/hide individual years.</p>
    </div>

    <div class="controls">
        <div class="control-group">
            <label for="varSelect">Variable:</label>
            <select id="varSelect" class="ctrl-select">
{option_tags}
            </select>
        </div>
        <div class="control-group">
            <label for="startYearSelect">Start year:</label>
            <select id="startYearSelect" class="ctrl-select">
{start_year_tags}
            </select>
        </div>
        <div class="control-group">
            <label for="yClipSelect">Y-axis:</label>
            <select id="yClipSelect" class="ctrl-select">
{y_clip_tags}
            </select>
        </div>
        <div class="control-group">
            <label for="modeSelect">Display:</label>
            <select id="modeSelect" class="ctrl-select">
                <option value="vintage" selected>All vintages</option>
                <option value="avg">Average</option>
                <option value="current">Current year</option>
            </select>
        </div>
    </div>

    <div class="chart-card">
        <div id="spf-chart"></div>
    </div>

{insight_sections}

    <div class="methodology">
        <strong>Methodology:</strong>
        Growth variables (RGDP, NGDP, GDP Deflator) use SPF Mean Growth files —
        horizon columns DXXX2–6, where target year = survey year + (horizon − 2).
        Rate/level variables use Mean Level files — annual-average columns A/B/C/D,
        offset +0/+1/+2/+3 from survey year. Target years shown every 2 years for 2000–2017,
        every year for 2018–2026. Colors graduate from steel-blue (old) to red (new).
        Y-axis percentile bounds computed across all observations for the selected variable.
    </div>
    <p class="source-note">Source: Federal Reserve Bank of Philadelphia, Survey of Professional Forecasters.
    Generated: {generated}</p>
</div>

<script>
const TRACES        = {traces_json};
const SPECIAL       = {specials_json};
const VAR_META      = {var_meta_json};
const Y_BOUNDS      = {y_bounds_json};

const DEFAULT_VAR   = 'RGDP';
const DEFAULT_START = '{default_start}';
const DEFAULT_YCLIP = '{default_yclip}';

// ── Build Plotly traces ──────────────────────────────────────────────────────
function makeTrace(t, activeVar) {{
    return {{
        x: t.x,
        y: t.y,
        mode: 'lines+markers',
        type: 'scatter',
        name: String(t.year),
        legendgroup: t.var + '_' + t.year,
        showlegend: (t.var === activeVar),
        line:   {{ color: t.color, width: t.width }},
        marker: {{ size: t.markerSize, color: t.color }},
        visible: (t.var === activeVar),
        hovertemplate:
            '<b>' + VAR_META[t.var].label + ' \u2014 ' + t.year + ' forecast</b><br>' +
            'Survey: %{{x|%Y Q}} — %{{y:.2f}}' + t.unit + '<extra></extra>',
        _var: t.var, _mode: 'vintage',
    }};
}}

function makeSpecialTrace(s) {{
    const isAvg  = s.mode === 'avg';
    const color  = isAvg ? '#c0392b' : '#1a3a2f';
    const label  = isAvg ? 'Average across horizons' : 'Current-year forecast';
    return {{
        x: s.x, y: s.y,
        mode: 'lines+markers',
        type: 'scatter',
        name: label,
        showlegend: false,
        line:   {{ color: color, width: 2.5 }},
        marker: {{ size: 5, color: color }},
        visible: false,
        hovertemplate:
            '<b>' + label + '</b><br>' +
            'Survey: %{{x|%Y Q}} — %{{y:.2f}}' + s.unit + '<extra></extra>',
        _var: s.var, _mode: s.mode,
    }};
}}

const vintageTraces = TRACES.map(t => makeTrace(t, DEFAULT_VAR));
const specialTraces = SPECIAL.map(s => makeSpecialTrace(s));
const allTraces     = [...vintageTraces, ...specialTraces];

// ── Helpers ──────────────────────────────────────────────────────────────────
function xRange(startYear) {{
    return [startYear + '-01-01', '2030-01-01'];
}}

function yRange(varKey, clipKey) {{
    const b = Y_BOUNDS[varKey];
    return (b && b[clipKey]) ? b[clipKey] : null;
}}

function zeroLine() {{
    return {{
        type: 'line', xref: 'paper', x0: 0, x1: 1,
        yref: 'y', y0: 0, y1: 0,
        line: {{ color: 'rgba(100,100,100,0.40)', width: 1.1, dash: 'dash' }},
    }};
}}

// ── Initial layout ───────────────────────────────────────────────────────────
const initYRange = yRange(DEFAULT_VAR, DEFAULT_YCLIP);
const layout = {{
    title: {{
        text: 'The Evolution of Expectations: ' + VAR_META[DEFAULT_VAR].label + ' Vintages',
        x: 0.5, xanchor: 'center',
        font: {{ size: 15, family: 'DM Sans, system-ui, sans-serif' }},
    }},
    xaxis: {{
        title: 'Survey Quarter',
        type: 'date',
        range: xRange(DEFAULT_START),
        tickformat: '%Y',
        dtick: 'M12',
        tickfont: {{ size: 10 }},
        gridcolor: 'rgba(200,200,200,0.4)',
    }},
    yaxis: {{
        title: VAR_META[DEFAULT_VAR].unit,
        range: initYRange,
        gridcolor: 'rgba(200,200,200,0.4)',
        zeroline: false,
        ticksuffix: '%',
    }},
    legend: {{
        title: {{ text: 'Target<br>Year', font: {{ size: 11 }} }},
        orientation: 'v',
        yanchor: 'top', y: 1,
        xanchor: 'left', x: 1.01,
        bgcolor: 'rgba(255,255,255,0.85)',
        bordercolor: 'rgba(200,200,200,0.5)', borderwidth: 1,
        font: {{ size: 10 }},
    }},
    shapes: VAR_META[DEFAULT_VAR].zeroLine ? [zeroLine()] : [],
    plot_bgcolor: 'white', paper_bgcolor: 'white',
    height: 560,
    margin: {{ l: 60, r: 90, t: 55, b: 80 }},
    font: {{ family: 'DM Sans, system-ui, sans-serif' }},
    hovermode: 'x unified',
}};

Plotly.newPlot('spf-chart', allTraces, layout, {{displayModeBar: false, responsive: true}});

// ── State ────────────────────────────────────────────────────────────────────
let currentVar   = DEFAULT_VAR;
let currentStart = DEFAULT_START;
let currentClip  = DEFAULT_YCLIP;
let currentMode  = 'vintage';

function applyAll() {{
    const meta = VAR_META[currentVar];

    const vis    = allTraces.map(t => t._var === currentVar && t._mode === currentMode);
    const showLg = allTraces.map(t => t._var === currentVar && t._mode === 'vintage');

    Plotly.restyle('spf-chart', {{ visible: vis, showlegend: showLg }});

    const yr = yRange(currentVar, currentClip);
    Plotly.relayout('spf-chart', {{
        'title.text':       'The Evolution of Expectations: ' + meta.label + ' Vintages',
        'yaxis.title.text': meta.unit,
        'yaxis.range':      yr,
        'xaxis.range':      xRange(currentStart),
        'shapes':           meta.zeroLine ? [zeroLine()] : [],
    }});

    document.querySelectorAll('.insight-section').forEach(el => el.classList.remove('active'));
    const sec = document.getElementById('insight-' + currentVar);
    if (sec) sec.classList.add('active');
}}

document.getElementById('varSelect').addEventListener('change', function() {{
    currentVar = this.value;
    applyAll();
}});
document.getElementById('startYearSelect').addEventListener('change', function() {{
    currentStart = this.value;
    applyAll();
}});
document.getElementById('yClipSelect').addEventListener('change', function() {{
    currentClip = this.value;
    applyAll();
}});
document.getElementById('modeSelect').addEventListener('change', function() {{
    currentMode = this.value;
    applyAll();
}});
</script>
</body>
</html>
"""


def build_html(all_vintages: dict, insights: dict, traces: list[dict], specials: list[dict], y_bounds: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Variable dropdown
    option_tags = ""
    for key, (label, *_) in VARIABLES.items():
        selected = ' selected' if key == "RGDP" else ""
        option_tags += f'                <option value="{key}"{selected}>{label}</option>\n'

    # Start year dropdown
    start_year_tags = ""
    for val, label in START_YEAR_OPTIONS:
        selected = ' selected' if val == DEFAULT_START_YEAR else ""
        start_year_tags += f'                <option value="{val}"{selected}>{label}</option>\n'

    # Y-clip dropdown
    y_clip_tags = ""
    for key, label, _ in Y_CLIP_OPTIONS:
        selected = ' selected' if key == DEFAULT_Y_CLIP else ""
        y_clip_tags += f'                <option value="{key}"{selected}>{label}</option>\n'

    # Insight sections
    insight_sections_html = ""
    for i, key in enumerate(VARIABLES):
        lines = insights.get(key, [])
        active_cls = " active" if i == 0 else ""
        if lines:
            items = "".join(f"<li>{l}</li>" for l in lines)
            body = f'<h3>Notable Downward Revisions (recent target years)</h3><ul>{items}</ul>'
        else:
            body = '<p style="font-size:.84rem;color:#555">No significant downward revisions found for recent target years.</p>'
        insight_sections_html += (
            f'    <div id="insight-{key}" class="insight-section{active_cls}">\n'
            f'        {body}\n'
            f'    </div>\n'
        )

    var_meta = {
        key: {"label": cfg[0], "unit": cfg[3], "zeroLine": cfg[4]}
        for key, cfg in VARIABLES.items()
    }

    return HTML_TEMPLATE.format(
        option_tags=option_tags.rstrip("\n"),
        start_year_tags=start_year_tags.rstrip("\n"),
        y_clip_tags=y_clip_tags.rstrip("\n"),
        insight_sections=insight_sections_html,
        generated=now,
        traces_json=json.dumps(traces, separators=(",", ":")),
        specials_json=json.dumps(specials, separators=(",", ":")),
        var_meta_json=json.dumps(var_meta, separators=(",", ":")),
        y_bounds_json=json.dumps(y_bounds, separators=(",", ":")),
        default_start=DEFAULT_START_YEAR,
        default_yclip=DEFAULT_Y_CLIP,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching SPF data (all available history)...")
    all_vintages = fetch_all()

    print(f"\nTarget years with data:")
    for var_key, vintages in all_vintages.items():
        yrs = sorted(vintages.keys())
        print(f"  {var_key}: {yrs[0]}–{yrs[-1]}  ({len(yrs)} years)")

    print("\nComputing percentile bounds...")
    y_bounds = compute_y_bounds(all_vintages)
    for var_key, bounds in y_bounds.items():
        b90 = bounds.get("p90", [])
        print(f"  {var_key} 90%: {b90}")

    print("\nComputing insights...")
    insights = compute_insights(all_vintages)

    print("\nBuilding trace data...")
    traces = build_trace_data(all_vintages)
    print(f"  {len(traces)} traces across {len(VARIABLES)} variables")

    print("\nBuilding special traces (avg + current year)...")
    specials = build_special_traces(all_vintages)
    print(f"  {len(specials)} special traces")

    html = build_html(all_vintages, insights, traces, specials, y_bounds)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\nSaved → {OUTPUT_FILE}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
