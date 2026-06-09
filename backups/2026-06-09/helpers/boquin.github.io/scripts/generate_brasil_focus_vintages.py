#!/usr/bin/env python3
"""
Brasil FOCUS Forecast Vintage Evolution Dashboard
-------------------------------------------------
Downloads BCB FOCUS survey expectations from the Olinda OData API and
renders a single interactive HTML dashboard for all 12 macro indicators.

Output: reports/brasil-focus-vintages/index.html
"""

import colorsys
import json
import time
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings('ignore')

BCB_ENDPOINT = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas"
    "/versao/v1/odata/ExpectativasMercadoAnuais"
)

# slug: (display_label, api_indicator_name, unit, show_zero_line, indicador_detalhe_filter)
# baseCalculo=0 (all respondents) is always applied.
# indicador_detalhe_filter: None = no sub-filter; 'Saldo' = net trade balance only.
INDICATORS = {
    'ipca':               ('IPCA',                          'IPCA',                           '% a.a.',  False, None),
    'pib':                ('PIB Total',                     'PIB Total',                      '% a.a.',  True,  None),
    'cambio':             ('Câmbio',                        'Câmbio',                         'BRL/USD', False, None),
    'selic':              ('Selic',                         'Selic',                          '% a.a.',  False, None),
    'igpm':               ('IGP-M',                         'IGP-M',                          '% a.a.',  False, None),
    'resultado_primario': ('Resultado Primário',             'Resultado primário',              '% PIB',   True,  None),
    'resultado_nominal':  ('Resultado Nominal',              'Resultado nominal',               '% PIB',   True,  None),
    'divida_liquida':     ('Dívida Líquida Setor Público',   'Dívida líquida do setor público', '% PIB',   False, None),
    'conta_corrente':     ('Conta Corrente',                 'Conta corrente',                  'US$ bi',  True,  None),
    'balanca_comercial':  ('Balança Comercial (Saldo)',      'Balança comercial',               'US$ bi',  False, 'Saldo'),
    'ipca_adm':           ('IPCA Administrados',             'IPCA Administrados',              '% a.a.',  False, None),
    'ide':                ('Invest. Direto no País',         'Investimento direto no país',     'US$ bi',  False, None),
}

TARGET_YEARS = list(range(2001, datetime.now().year + 3))

START_YEAR_OPTIONS = [
    ('2001', '2001 — full history'),
    ('2005', '2005 — last ~20 yrs'),
    ('2010', '2010 — last ~15 yrs'),
    ('2015', '2015 — last ~10 yrs'),
    ('2018', '2018 — last 7 yrs'),
    ('2020', '2020 — last 5 yrs'),
]
DEFAULT_START_YEAR = '2010'

Y_CLIP_OPTIONS = [
    ('all',  'All data',    (0,    100)),
    ('p99',  '99% of data', (0.5,  99.5)),
    ('p95',  '95% of data', (2.5,  97.5)),
    ('p90',  '90% of data', (5,    95)),
    ('p80',  '80% of data', (10,   90)),
]
DEFAULT_Y_CLIP = 'p95'

DEFAULT_INDICATOR = 'ipca'

OUTPUT_DIR  = Path(__file__).parent.parent / 'reports' / 'brasil-focus-vintages'
DATA_DIR    = OUTPUT_DIR / 'data'   # cached CSVs, one per indicator
OUTPUT_FILE = OUTPUT_DIR / 'index.html'

END_YEAR = datetime.now().year + 3

INCREMENTAL_DAYS = 365  # overlap window for incremental fetch


# ---------------------------------------------------------------------------
# Color gradient: old vintages muted blue-grey → recent vivid red
# ---------------------------------------------------------------------------
def _build_palette(years: list) -> dict:
    n = len(years)
    colors = {}
    for i, yr in enumerate(years):
        t = i / max(n - 1, 1)
        h = 0.62 * (1 - t)
        s = 0.30 + 0.65 * t
        v = 0.62 + 0.30 * t
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        colors[yr] = f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
    return colors


PALETTE = _build_palette(TARGET_YEARS)


def _line_width(yr: int) -> float:
    return 2.5 if yr >= 2020 else (1.8 if yr >= 2015 else 1.2)


def _marker_size(yr: int) -> int:
    return 5 if yr >= 2020 else (3 if yr >= 2015 else 2)


# ---------------------------------------------------------------------------
# Data fetching + CSV cache (incremental)
# ---------------------------------------------------------------------------
def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (compatible; BCB-Focus-Vintages/1.0)',
        'Accept': 'application/json',
    })
    return s


def _api_fetch(api_name: str, start_date: str, session: requests.Session, detalhe: str = None) -> list:
    """Fetch paginated records for one indicator from BCB Olinda, starting at start_date.

    Always filters baseCalculo=0 (all respondents).
    detalhe: optional IndicadorDetalhe value (e.g. 'Saldo' for Balança Comercial).
    """
    records = []
    skip = 0
    top  = 10000
    while True:
        parts = [
            f"Data ge '{start_date}'",
            f"Indicador eq '{api_name}'",
            "baseCalculo eq 0",
        ]
        if detalhe:
            parts.append(f"IndicadorDetalhe eq '{detalhe}'")
        date_filter = ' and '.join(parts)
        url = (
            f"{BCB_ENDPOINT}"
            f"?$top={top}&$skip={skip}"
            f"&$filter={requests.utils.quote(date_filter)}"
            f"&$select=Data,DataReferencia,Mediana"
            f"&$orderby=Data asc&$format=json"
        )
        try:
            r = session.get(url, timeout=90)
            r.raise_for_status()
            data = r.json().get('value', [])
        except Exception as e:
            print(f'    API error at skip={skip}: {e}')
            break
        records.extend(data)
        if len(data) < top:
            break
        skip += top
        time.sleep(0.4)
    return records


def _records_to_df(records: list) -> pd.DataFrame:
    rows = []
    for rec in records:
        try:
            rows.append({
                'date':     str(rec['Data'])[:10],
                'ref_year': int(str(rec['DataReferencia'])[:4]),
                'median':   float(rec['Mediana']),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['date', 'ref_year', 'median'])


def _load_or_fetch(slug: str, api_name: str, session: requests.Session, detalhe: str = None) -> pd.DataFrame:
    """
    Load cached CSV and append the last INCREMENTAL_DAYS of API data.
    On first run (no CSV), fetches full history from 2001-01-01.
    """
    csv_path = DATA_DIR / f'{slug}.csv'
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if csv_path.exists():
        df_cached = pd.read_csv(csv_path, dtype={'date': str, 'ref_year': int, 'median': float})
    else:
        df_cached = pd.DataFrame(columns=['date', 'ref_year', 'median'])

    if len(df_cached) == 0:
        start_date = '2001-01-01'
        print(f'    No cache. Full fetch from {start_date}...')
    else:
        start_date = (datetime.now() - timedelta(days=INCREMENTAL_DAYS)).strftime('%Y-%m-%d')
        print(f'    Cached {len(df_cached):,} rows. Fetching from {start_date}...')

    records = _api_fetch(api_name, start_date, session, detalhe=detalhe)
    df_new  = _records_to_df(records)
    print(f'    API returned {len(records):,} new records.')

    if not df_new.empty:
        df_all = pd.concat([df_cached, df_new], ignore_index=True)
        df_all = (
            df_all
            .drop_duplicates(subset=['date', 'ref_year'], keep='last')
            .sort_values(['ref_year', 'date'])
            .reset_index(drop=True)
        )
    else:
        df_all = df_cached

    df_all.to_csv(csv_path, index=False)
    return df_all


MAX_HORIZON_YEARS = 3  # only show surveys within this many years of the ref year

def _df_to_vintages(df: pd.DataFrame) -> dict:
    """Convert flat DataFrame to {ref_year: pd.Series(index=date_str, values=median)}.
    Only keeps survey dates within MAX_HORIZON_YEARS of the reference year.
    """
    target_set = set(TARGET_YEARS)
    vintages: dict = {}
    for yr, grp in df.groupby('ref_year'):
        if yr not in target_set:
            continue
        grp = grp.sort_values('date')
        grp = grp[grp['date'].str[:4].astype(int) >= yr - MAX_HORIZON_YEARS]
        if grp.empty:
            continue
        vintages[yr] = pd.Series(
            grp['median'].values,
            index=grp['date'].values,
            name=str(yr),
        )
    return vintages


def fetch_all() -> dict:
    session = _make_session()
    all_vintages = {}
    for slug, (label, api_name, unit, zero_line, detalhe) in INDICATORS.items():
        print(f'  {label}...')
        df = _load_or_fetch(slug, api_name, session, detalhe=detalhe)
        all_vintages[slug] = _df_to_vintages(df)
        ref_yrs = sorted(all_vintages[slug].keys())
        span = f'{ref_yrs[0]}–{ref_yrs[-1]}' if ref_yrs else 'none'
        print(f'    {len(df):,} total rows → {len(ref_yrs)} ref years ({span})')
    return all_vintages


# ---------------------------------------------------------------------------
# Y-axis bounds (percentile clipping)
# ---------------------------------------------------------------------------
def compute_y_bounds(all_vintages: dict) -> dict:
    bounds = {}
    for slug, vintages in all_vintages.items():
        all_vals = []
        for s in vintages.values():
            all_vals.extend(s.dropna().tolist())
        if not all_vals:
            bounds[slug] = {}
            continue
        var_bounds = {}
        for key, _lbl, (lo_pct, hi_pct) in Y_CLIP_OPTIONS:
            lo = float(np.percentile(all_vals, lo_pct))
            hi = float(np.percentile(all_vals, hi_pct))
            pad = (hi - lo) * 0.05
            var_bounds[key] = [round(lo - pad, 3), round(hi + pad, 3)]
        bounds[slug] = var_bounds
    return bounds


# ---------------------------------------------------------------------------
# Insights: largest downward revision for 4 most recent ref years
# ---------------------------------------------------------------------------
def compute_insights(all_vintages: dict) -> dict:
    insights = {}
    for slug, vintages in all_vintages.items():
        lines = []
        for yr in sorted(vintages.keys(), reverse=True)[:4]:
            s = vintages[yr]
            if len(s) < 3:
                continue
            diff = s.diff()
            worst_idx = diff.idxmin()
            worst_val = diff[worst_idx]
            if pd.notna(worst_val) and worst_val < 0:
                lines.append(
                    f'<b>{yr}</b>: largest downward revision on <b>{worst_idx}</b> '
                    f'({worst_val:+.3f})'
                )
        insights[slug] = lines
    return insights


# ---------------------------------------------------------------------------
# Trace data
# ---------------------------------------------------------------------------
def build_trace_data(all_vintages: dict) -> list:
    traces = []
    for slug, vintages in all_vintages.items():
        _, _, unit, *_ = INDICATORS[slug]
        for yr in TARGET_YEARS:
            if yr not in vintages:
                continue
            s = vintages[yr]
            traces.append({
                'var':   slug,
                'year':  yr,
                'x':     list(s.index),
                'y':     [round(v, 4) for v in s.values],
                'color': PALETTE.get(yr, '#888888'),
                'width': _line_width(yr),
                'name':  str(yr),
                'unit':  unit,
            })
    return traces


def build_special_traces(all_vintages: dict) -> list:
    specials = []
    for slug, vintages in all_vintages.items():
        _, _, unit, *_ = INDICATORS[slug]

        # Average across all ref years at each survey date
        date_vals: dict = defaultdict(list)
        for yr, s in vintages.items():
            for date, val in zip(s.index, s.values):
                date_vals[date].append(float(val))
        avg_dates = sorted(date_vals.keys())
        specials.append({
            'var':  slug,
            'mode': 'avg',
            'x':    avg_dates,
            'y':    [round(sum(date_vals[d]) / len(date_vals[d]), 4) for d in avg_dates],
            'unit': unit,
        })

        # Current-year: survey date falls in the same calendar year as ref year
        curr_pts = []
        for yr, s in vintages.items():
            for date, val in zip(s.index, s.values):
                if date[:4] == str(yr):
                    curr_pts.append((date, round(float(val), 4)))
        curr_pts.sort()
        specials.append({
            'var':  slug,
            'mode': 'current',
            'x':    [p[0] for p in curr_pts],
            'y':    [p[1] for p in curr_pts],
            'unit': unit,
        })

    return specials


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Brasil FOCUS Forecast Vintages</title>
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
        .page-title {{ font-size: 1.1rem; font-weight: 600; color: #1a4a28; margin-bottom: 4px; }}
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
        #varSelect {{ min-width: 210px; }}
        #startYearSelect {{ min-width: 185px; }}
        #yClipSelect {{ min-width: 150px; }}
        #modeSelect {{ min-width: 165px; }}
        .ctrl-select:focus {{ outline: 2px solid #1a4a28; border-color: transparent; }}
        .chart-card {{
            background: white; border-radius: 10px;
            box-shadow: 0 1px 6px rgba(0,0,0,0.09);
            padding: 16px; margin-bottom: 16px;
        }}
        #focus-chart {{ width: 100%; }}
        .insight-section {{ display: none; }}
        .insight-section.active {{
            display: block;
            background: #f0f7f2;
            border-left: 4px solid #1a4a28;
            border-radius: 6px;
            padding: 13px 17px;
            margin-bottom: 16px;
        }}
        .insight-section h3 {{
            font-size: 0.91rem; font-weight: 600; color: #1a4a28; margin-bottom: 7px;
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
        .methodology strong {{ color: #1a4a28; }}
        .source-note {{ font-size: 0.76rem; color: #999; }}
        .source-note a {{ color: #999; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <p class="page-title">&#x1F1E7;&#x1F1F7; BCB FOCUS Survey — Forecast Vintage Evolution</p>
        <p class="subtitle">Each line traces how the market consensus (median) for a given reference year evolved across successive survey weeks. Older vintages muted; recent ones bold. Click legend entries to toggle individual years.</p>
    </div>

    <div class="controls">
        <div class="control-group">
            <label for="varSelect">Indicator:</label>
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
                <option value="current">Current-year</option>
            </select>
        </div>
    </div>

    <div class="chart-card">
        <div id="focus-chart"></div>
    </div>

{insight_sections}

    <div class="methodology">
        <strong>Methodology:</strong>
        Data from the BCB FOCUS survey (Pesquisa de Expectativas de Mercado) via the
        Olinda OData API (<em>ExpectativasMercadoAnuais</em>). Each line is the median
        forecast for a specific reference year across all available survey dates.
        Colors graduate from steel-blue (oldest vintages) to red (most recent).
        Survey runs weekly on Fridays since 2001. Y-axis percentile bounds computed
        across all observations for the selected indicator.
    </div>
    <p class="source-note">
        Source: Banco Central do Brasil, FOCUS &mdash; Pesquisa de Expectativas de Mercado.
        Generated: {generated} &nbsp;|&nbsp;
        <a href="https://boquin.xyz">boquin.xyz</a>
    </p>
</div>

<script>
const TRACES   = {traces_json};
const SPECIAL  = {specials_json};
const VAR_META = {var_meta_json};
const Y_BOUNDS = {y_bounds_json};

const DEFAULT_VAR   = '{default_var}';
const DEFAULT_START = '{default_start}';
const DEFAULT_YCLIP = '{default_yclip}';

function makeTrace(t, activeVar) {{
    return {{
        x: t.x,
        y: t.y,
        mode: 'lines',
        type: 'scatter',
        name: String(t.year),
        legendgroup: t.var + '_' + t.year,
        showlegend: (t.var === activeVar),
        line: {{ color: t.color, width: t.width }},
        visible: (t.var === activeVar),
        hovertemplate:
            '<b>' + VAR_META[t.var].label + ' \u2014 ' + t.year + ' forecast</b><br>' +
            'Survey: %{{x|%Y-%m-%d}} \u2014 %{{y:.3f}} ' + t.unit + '<extra></extra>',
        _var: t.var,
        _mode: 'vintage',
    }};
}}

function makeSpecialTrace(s) {{
    const isAvg = s.mode === 'avg';
    const color = isAvg ? '#c0392b' : '#1a4a28';
    const label = isAvg ? 'Average across horizons' : 'Current-year forecast';
    return {{
        x: s.x,
        y: s.y,
        mode: 'lines',
        type: 'scatter',
        name: label,
        showlegend: false,
        line: {{ color: color, width: 2.5 }},
        visible: false,
        hovertemplate:
            '<b>' + label + '</b><br>' +
            'Survey: %{{x|%Y-%m-%d}} \u2014 %{{y:.3f}} ' + s.unit + '<extra></extra>',
        _var: s.var,
        _mode: s.mode,
    }};
}}

const vintageTraces = TRACES.map(t => makeTrace(t, DEFAULT_VAR));
const specialTraces = SPECIAL.map(s => makeSpecialTrace(s));
const allTraces     = [...vintageTraces, ...specialTraces];

function xRange(startYear) {{
    return [startYear + '-01-01', '{end_year}-12-31'];
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

const initYR = yRange(DEFAULT_VAR, DEFAULT_YCLIP);
const layout = {{
    title: {{
        text: 'Evolution of Expectations: ' + VAR_META[DEFAULT_VAR].label + ' Vintages',
        x: 0.5, xanchor: 'center',
        font: {{ size: 15, family: 'DM Sans, system-ui, sans-serif' }},
    }},
    xaxis: {{
        title: 'Survey Date',
        type: 'date',
        range: xRange(DEFAULT_START),
        tickformat: '%Y',
        dtick: 'M12',
        tickfont: {{ size: 10 }},
        gridcolor: 'rgba(200,200,200,0.4)',
    }},
    yaxis: {{
        title: VAR_META[DEFAULT_VAR].unit,
        range: initYR,
        gridcolor: 'rgba(200,200,200,0.4)',
        zeroline: false,
    }},
    legend: {{
        title: {{ text: 'Ref<br>Year', font: {{ size: 11 }} }},
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

Plotly.newPlot('focus-chart', allTraces, layout, {{displayModeBar: false, responsive: true}});

let currentVar   = DEFAULT_VAR;
let currentStart = DEFAULT_START;
let currentClip  = DEFAULT_YCLIP;
let currentMode  = 'vintage';

function applyAll() {{
    const meta   = VAR_META[currentVar];
    const vis    = allTraces.map(t => t._var === currentVar && t._mode === currentMode);
    const showLg = allTraces.map(t => t._var === currentVar && t._mode === 'vintage');
    Plotly.restyle('focus-chart', {{ visible: vis, showlegend: showLg }});
    const yr = yRange(currentVar, currentClip);
    Plotly.relayout('focus-chart', {{
        'title.text':       'Evolution of Expectations: ' + meta.label + ' Vintages',
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


def build_html(all_vintages: dict, insights: dict, traces: list, specials: list, y_bounds: dict) -> str:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # Indicator dropdown
    option_tags = ''
    for slug, (label, *_) in INDICATORS.items():
        sel = ' selected' if slug == DEFAULT_INDICATOR else ''
        option_tags += f'                <option value="{slug}"{sel}>{label}</option>\n'

    # Start-year dropdown
    start_year_tags = ''
    for val, label in START_YEAR_OPTIONS:
        sel = ' selected' if val == DEFAULT_START_YEAR else ''
        start_year_tags += f'                <option value="{val}"{sel}>{label}</option>\n'

    # Y-clip dropdown
    y_clip_tags = ''
    for key, label, _ in Y_CLIP_OPTIONS:
        sel = ' selected' if key == DEFAULT_Y_CLIP else ''
        y_clip_tags += f'                <option value="{key}"{sel}>{label}</option>\n'

    # Insight sections
    insight_html = ''
    for i, slug in enumerate(INDICATORS):
        lines = insights.get(slug, [])
        active = ' active' if i == 0 else ''
        if lines:
            items = ''.join(f'<li>{l}</li>' for l in lines)
            body = f'<h3>Notable Downward Revisions (recent ref years)</h3><ul>{items}</ul>'
        else:
            body = '<p style="font-size:.84rem;color:#555">No significant downward revisions in recent reference years.</p>'
        insight_html += (
            f'    <div id="insight-{slug}" class="insight-section{active}">\n'
            f'        {body}\n'
            f'    </div>\n'
        )

    var_meta = {
        slug: {'label': cfg[0], 'unit': cfg[2], 'zeroLine': cfg[3]}
        for slug, cfg in INDICATORS.items()
    }


    return HTML_TEMPLATE.format(
        option_tags=option_tags.rstrip('\n'),
        start_year_tags=start_year_tags.rstrip('\n'),
        y_clip_tags=y_clip_tags.rstrip('\n'),
        insight_sections=insight_html,
        generated=now,
        traces_json=json.dumps(traces, separators=(',', ':')),
        specials_json=json.dumps(specials, separators=(',', ':')),
        var_meta_json=json.dumps(var_meta, separators=(',', ':')),
        y_bounds_json=json.dumps(y_bounds, separators=(',', ':')),
        default_var=DEFAULT_INDICATOR,
        default_start=DEFAULT_START_YEAR,
        default_yclip=DEFAULT_Y_CLIP,
        end_year=END_YEAR,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print('Loading/updating BCB FOCUS data (12 indicators)...')
    all_vintages = fetch_all()

    print('\nComputing percentile bounds...')
    y_bounds = compute_y_bounds(all_vintages)

    print('Computing insights...')
    insights = compute_insights(all_vintages)

    print('Building trace data...')
    traces   = build_trace_data(all_vintages)
    specials = build_special_traces(all_vintages)
    print(f'  {len(traces)} vintage traces, {len(specials)} special traces')

    print('Rendering HTML...')
    html = build_html(all_vintages, insights, traces, specials, y_bounds)
    OUTPUT_FILE.write_text(html, encoding='utf-8')
    print(f'\nSaved → {OUTPUT_FILE}  ({len(html):,} bytes)')


if __name__ == '__main__':
    main()
