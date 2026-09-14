"""
Monetary Policy Rules Tracker (Fed MPR Box 4 style)
====================================================
Fetches FRED data, computes historical rule paths, and generates a self-contained
interactive HTML page with both a historical chart and a live calculator.

FRED series (quarterly):
  FEDFUNDS  – Effective federal funds rate
  PCEPILFE  – Core PCE price index → 4-quarter YoY %
  UNRATE    – Unemployment rate
  NROU      – CBO NAIRU

Formulas (using Okun's Law form with unemployment gap):
  Taylor (1993):       R = r* + π + 0.5·(π − π*) − 1.0·(U − U*)
  Adjusted Taylor:      R = max(R_T93 − Z, ELB), Z_t = max(0, Z_{t-1} + (ELB − R_T93_{t-1}))
  Balanced Approach:   R = r* + π + 0.5·(π − π*) − 2.0·(U − U*)
  First-Difference:    R = FFR_{t-1} + 0.5·(π − π*) − (U_t − U_{t-4})
"""

import json
import os
import time
from datetime import date

import pandas as pd
from fredapi import Fred

_FRED_KEY_DEFAULT = "a68d4b16dd1984d0c8455381a79a8b6e"
FRED_API_KEY = os.environ.get("FRED_API_KEY", _FRED_KEY_DEFAULT)

START_DATE = "1990-01-01"
PI_STAR = 2.0   # inflation target
R_STAR  = 0.5   # neutral real rate
ELB     = 0.125 # effective lower bound (midpoint of 0-0.25% range)

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "reports", "taylor-rule", "index.html"
)


def fetch(fred: Fred, series_id: str) -> pd.Series:
    print(f"  Fetching {series_id}...")
    time.sleep(0.5)
    s = fred.get_series(series_id, observation_start=START_DATE)
    s.index = pd.to_datetime(s.index)
    return s.dropna()


def build_dataset(fred: Fred) -> pd.DataFrame:
    ffr   = fetch(fred, "FEDFUNDS").resample("QE").mean().rename("FEDFUNDS")
    pce   = fetch(fred, "PCEPILFE").resample("QE").last()
    urate = fetch(fred, "UNRATE").resample("QE").mean().rename("UNRATE")
    nrou  = fetch(fred, "NROU").resample("QE").last().rename("NROU")

    pce_yoy = pce.pct_change(4).mul(100).rename("CorePCE_YoY")

    df = pd.concat([ffr, pce_yoy, urate, nrou], axis=1).dropna()

    pi   = df["CorePCE_YoY"]
    ugap = df["UNRATE"] - df["NROU"]   # positive = slack

    df["Taylor"]   = R_STAR + pi + 0.5 * (pi - PI_STAR) - 1.0 * ugap
    df["Balanced"] = R_STAR + pi + 0.5 * (pi - PI_STAR) - 2.0 * ugap

    # Adjusted Taylor (1993) — Reifschneider-Williams ELB makeup recursion.
    taylor = df["Taylor"].to_numpy()
    z = 0.0
    adjusted = []
    for i, t93 in enumerate(taylor):
        if i > 0:
            z = max(0.0, z + (ELB - taylor[i - 1]))
        adjusted.append(max(t93 - z, ELB))
    df["Adjusted"] = adjusted

    # First-difference rule — uses actual lagged FFR, not a lagged rule value.
    df["FirstDiff"] = (
        df["FEDFUNDS"].shift(1) + 0.5 * (pi - PI_STAR) - (df["UNRATE"] - df["UNRATE"].shift(4))
    )

    return df.dropna()


def to_json_payload(df: pd.DataFrame) -> str:
    payload = {
        "dates":     [d.strftime("%Y-%m-%d") for d in df.index],
        "fedfunds":  [round(v, 4) for v in df["FEDFUNDS"]],
        "taylor":    [round(v, 4) for v in df["Taylor"]],
        "adjusted":  [round(v, 4) for v in df["Adjusted"]],
        "balanced":  [round(v, 4) for v in df["Balanced"]],
        "firstdiff": [round(v, 4) for v in df["FirstDiff"]],
        "pce":       [round(v, 4) for v in df["CorePCE_YoY"]],
        "unrate":    [round(v, 4) for v in df["UNRATE"]],
        "nrou":      [round(v, 4) for v in df["NROU"]],
        "latest": {
            "fedfunds":  round(df["FEDFUNDS"].iloc[-1], 2),
            "pce":       round(df["CorePCE_YoY"].iloc[-1], 2),
            "unrate":    round(df["UNRATE"].iloc[-1], 2),
            "nrou":      round(df["NROU"].iloc[-1], 2),
            "taylor":    round(df["Taylor"].iloc[-1], 2),
            "adjusted":  round(df["Adjusted"].iloc[-1], 2),
            "balanced":  round(df["Balanced"].iloc[-1], 2),
            "firstdiff": round(df["FirstDiff"].iloc[-1], 2),
            "date":      df.index[-1].strftime("%B %Y"),
        },
    }
    return json.dumps(payload)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monetary Policy Rules Tracker</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
:root {{
  --bg: #f8fafc;
  --surface: #ffffff;
  --surface2: #f1f5f9;
  --border: #e2e8f0;
  --accent: #6366f1;
  --accent2: #4f46e5;
  --amber: #d97706;
  --green: #16a34a;
  --red: #dc2626;
  --text: #0f172a;
  --muted: #64748b;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; }}
header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; }}
header h1 {{ font-size: 1.25rem; font-weight: 700; color: var(--accent2); }}
header .meta {{ color: var(--muted); font-size: 0.8rem; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px 32px; }}
.section-title {{ font-size: 0.7rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; margin-bottom: 12px; }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
.chart-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
.divider {{ border: none; border-top: 1px solid var(--border); margin: 32px 0; }}

/* Calculator inputs */
.input-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 20px; }}
.input-group label {{ display: block; font-size: 0.75rem; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .05em; }}
.input-group input {{
  width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
  color: var(--text); font-size: 1rem; padding: 8px 10px; outline: none;
  transition: border-color .2s;
}}
.input-group input:focus {{ border-color: var(--accent); }}

/* Result cards */
.result-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
.result-card {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }}
.result-card.taylor {{ border-left: 3px solid var(--accent2); }}
.result-card.balanced {{ border-left: 3px solid var(--amber); }}
.result-card .rule-name {{ font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); margin-bottom: 6px; }}
.result-card .rate {{ font-size: 2.4rem; font-weight: 800; margin-bottom: 6px; }}
.result-card.taylor .rate {{ color: var(--accent2); }}
.result-card.balanced .rate {{ color: var(--amber); }}
.result-card .formula {{ font-size: 0.72rem; color: var(--muted); font-family: monospace; line-height: 1.6; }}
.divergence-box {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; display: flex; align-items: center; gap: 20px; margin-bottom: 20px; }}
.divergence-box .label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: .08em; }}
.divergence-box .value {{ font-size: 1.5rem; font-weight: 700; color: var(--text); }}
.legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}

/* Explainer */
.explainer {{ color: var(--muted); font-size: 0.8rem; line-height: 1.7; }}
.explainer b {{ color: var(--text); }}

@media (max-width: 768px) {{
  .input-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .result-row {{ grid-template-columns: 1fr; }}
  .container {{ padding: 16px; }}
  header {{ padding: 12px 16px; }}
}}
</style>
</head>
<body>

<header>
  <div>
    <h1>📐 Monetary Policy Rules Tracker</h1>
    <div style="color:var(--muted);font-size:.75rem;margin-top:2px;">Taylor (1993), Adjusted Taylor, Balanced Approach &amp; First-Difference rules vs. actual fed funds · Fed MPR Box 4 style · Source: FRED</div>
  </div>
  <div class="meta">Updated: {updated}</div>
</header>

<div class="container">

  <!-- Historical chart -->
  <p class="section-title">Historical: Actual FFR vs. Policy Rules (1990–present, quarterly)</p>
  <div class="chart-box">
    <div id="hist-chart" style="height:420px;"></div>
    <div style="display:flex;gap:24px;margin-top:10px;font-size:0.75rem;color:var(--muted);flex-wrap:wrap;">
      <span><span class="legend-dot" style="background:#374151;"></span>Actual FFR</span>
      <span><span class="legend-dot" style="background:#4f46e5;"></span>Taylor Rule (1993)</span>
      <span><span class="legend-dot" style="background:#16a34a;"></span>Adjusted Taylor (1993)</span>
      <span><span class="legend-dot" style="background:#d97706;"></span>Balanced Approach Rule</span>
      <span><span class="legend-dot" style="background:#dc2626;"></span>First-Difference Rule</span>
    </div>
  </div>

  <hr class="divider">

  <!-- Calculator -->
  <p class="section-title">Live Calculator — adjust inputs to reprice both rules</p>
  <div class="card">
    <div class="input-grid">
      <div class="input-group">
        <label>r* — Neutral Real Rate (%)</label>
        <input type="number" id="inp-rstar" value="0.5" step="0.1" min="-2" max="5" oninput="recalc()">
      </div>
      <div class="input-group">
        <label>π — Current Inflation (%)</label>
        <input type="number" id="inp-pi" step="0.1" min="-5" max="20" oninput="recalc()">
      </div>
      <div class="input-group">
        <label>π* — Inflation Target (%)</label>
        <input type="number" id="inp-pistar" value="2.0" step="0.1" min="0" max="5" oninput="recalc()">
      </div>
      <div class="input-group">
        <label>U — Unemployment Rate (%)</label>
        <input type="number" id="inp-u" step="0.1" min="0" max="20" oninput="recalc()">
      </div>
      <div class="input-group">
        <label>U* — NAIRU (%)</label>
        <input type="number" id="inp-ustar" step="0.1" min="0" max="15" oninput="recalc()">
      </div>
    </div>
  </div>

  <div class="result-row">
    <div class="result-card taylor">
      <div class="rule-name">Taylor Rule (1993)</div>
      <div class="rate" id="res-taylor">—</div>
      <div class="formula" id="fml-taylor"></div>
    </div>
    <div class="result-card balanced">
      <div class="rule-name">Balanced Approach Rule</div>
      <div class="rate" id="res-balanced">—</div>
      <div class="formula" id="fml-balanced"></div>
    </div>
  </div>

  <div class="divergence-box">
    <div>
      <div class="label">Divergence (Balanced − Taylor)</div>
      <div class="value" id="res-divergence">—</div>
    </div>
    <div style="color:var(--muted);font-size:0.75rem;max-width:500px;">
      When U &gt; U*, the Balanced Approach prescribes a lower rate than Taylor. Divergence = 0 when unemployment is exactly at NAIRU.
    </div>
  </div>

  <div class="divergence-box">
    <div>
      <div class="label">Current Adjusted Taylor (1993)</div>
      <div class="value">{adjusted_latest}%</div>
    </div>
    <div>
      <div class="label">Current First-Difference Rule</div>
      <div class="value">{firstdiff_latest}%</div>
    </div>
    <div style="color:var(--muted);font-size:0.75rem;max-width:420px;">
      Both are path-dependent (accumulated ELB shortfall / lagged actual FFR), so they're shown as latest computed values rather than live-editable — see historical chart above.
    </div>
  </div>

  <!-- Sensitivity chart -->
  <p class="section-title">Sensitivity — Prescribed rate vs. unemployment (other inputs held fixed)</p>
  <div class="chart-box">
    <div id="sens-chart" style="height:360px;"></div>
  </div>

  <hr class="divider">

  <!-- Explainer -->
  <div class="explainer">
    <p style="margin-bottom:8px;"><b>Taylor Rule (1993):</b> R = r* + π + 0.5·(π − π*) − 1.0·(U − U*)</p>
    <p style="margin-bottom:8px;"><b>Adjusted Taylor (1993):</b> R = max(R_T93 − Z, ELB), where Z is the cumulative sum of past Taylor-rule shortfalls below the ELB (Reifschneider-Williams "lower-for-longer" makeup).</p>
    <p style="margin-bottom:8px;"><b>Balanced Approach Rule:</b> R = r* + π + 0.5·(π − π*) − 2.0·(U − U*)</p>
    <p style="margin-bottom:8px;"><b>First-Difference Rule:</b> R = FFR_(t−1) + 0.5·(π − π*) − (U_t − U_(t−4))</p>
    <p style="margin-bottom:8px;">The first three rules are written using the unemployment gap (via Okun's Law), where a 1% rise in unemployment ≈ 2% drop in output. The Balanced Approach doubles the unemployment coefficient from −1.0 to −2.0, prescribing 200 bps of cuts per 1% of excess unemployment vs. 100 bps under Taylor. The Adjusted Taylor rule accounts for periods when the Taylor rule prescribes a rate below the effective lower bound (ELB) by holding the prescribed rate lower for longer once liftoff occurs, to make up for the shortfall in accommodation. The First-Difference rule instead anchors off the prior quarter's actual fed funds rate and reacts to the year-over-year change in unemployment, making it inertial and less sensitive to real-time estimates of r* or U*.</p>
    <p style="color:var(--muted);font-size:0.72rem;">Sources: FRED — FEDFUNDS, PCEPILFE (Core PCE 4-quarter YoY), UNRATE, NROU (CBO NAIRU), quarterly. r* held constant at 0.5%, ELB at 0.125% (standard Fed Research assumptions).</p>
  </div>

</div>

<script>
const DATA = {data_json};

// ── Historical chart ──────────────────────────────────────────────────────────
(function() {{
  const layout = {{
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    margin: {{ t: 10, r: 10, b: 40, l: 45 }},
    xaxis: {{ gridcolor: '#e2e8f0', color: '#64748b', tickfont: {{ size: 11 }} }},
    yaxis: {{ gridcolor: '#e2e8f0', color: '#64748b', tickfont: {{ size: 11 }}, title: {{ text: 'Rate (%)', font: {{ color: '#64748b', size: 11 }} }} }},
    legend: {{ x: 0.01, y: 0.99, bgcolor: 'transparent', font: {{ color: '#64748b', size: 11 }} }},
    hovermode: 'x unified',
    hoverlabel: {{ bgcolor: '#ffffff', bordercolor: '#e2e8f0', font: {{ color: '#0f172a' }} }},
  }};
  const traces = [
    {{ x: DATA.dates, y: DATA.fedfunds,  name: 'Actual FFR', line: {{ color: '#374151', width: 1.5 }}, hovertemplate: '%{{y:.2f}}%' }},
    {{ x: DATA.dates, y: DATA.taylor,    name: 'Taylor (1993)', line: {{ color: '#4f46e5', width: 1.5, dash: 'dot' }}, hovertemplate: '%{{y:.2f}}%' }},
    {{ x: DATA.dates, y: DATA.adjusted,  name: 'Adjusted Taylor (1993)', line: {{ color: '#16a34a', width: 1.5, dash: 'dashdot' }}, hovertemplate: '%{{y:.2f}}%' }},
    {{ x: DATA.dates, y: DATA.balanced,  name: 'Balanced Approach', line: {{ color: '#d97706', width: 1.5, dash: 'dash' }}, hovertemplate: '%{{y:.2f}}%' }},
    {{ x: DATA.dates, y: DATA.firstdiff, name: 'First-Difference', line: {{ color: '#dc2626', width: 1.5, dash: 'longdash' }}, hovertemplate: '%{{y:.2f}}%' }},
  ];
  Plotly.newPlot('hist-chart', traces, layout, {{responsive: true, displayModeBar: false}});
}})();

// ── Calculator ────────────────────────────────────────────────────────────────
const L = DATA.latest;
document.getElementById('inp-pi').value    = L.pce;
document.getElementById('inp-u').value     = L.unrate;
document.getElementById('inp-ustar').value = L.nrou;

function recalc() {{
  const rstar  = parseFloat(document.getElementById('inp-rstar').value)  || 0;
  const pi     = parseFloat(document.getElementById('inp-pi').value)     || 0;
  const pistar = parseFloat(document.getElementById('inp-pistar').value) || 0;
  const u      = parseFloat(document.getElementById('inp-u').value)      || 0;
  const ustar  = parseFloat(document.getElementById('inp-ustar').value)  || 0;

  const infGap  = pi - pistar;
  const unempGap = u - ustar;

  const taylor   = rstar + pi + 0.5 * infGap - 1.0 * unempGap;
  const balanced = rstar + pi + 0.5 * infGap - 2.0 * unempGap;
  const diverg   = balanced - taylor;

  document.getElementById('res-taylor').textContent   = taylor.toFixed(2) + '%';
  document.getElementById('res-balanced').textContent = balanced.toFixed(2) + '%';
  document.getElementById('res-divergence').textContent = (diverg >= 0 ? '+' : '') + diverg.toFixed(2) + '%';

  const fmtN = v => (v >= 0 ? '+' : '') + v.toFixed(2);
  document.getElementById('fml-taylor').innerHTML =
    `R = ${{rstar.toFixed(2)}} + ${{pi.toFixed(2)}} + 0.5·(${{pi.toFixed(2)}} − ${{pistar.toFixed(2)}}) − 1.0·(${{u.toFixed(2)}} − ${{ustar.toFixed(2)}})<br>` +
    `&nbsp;&nbsp;= ${{rstar.toFixed(2)}} + ${{pi.toFixed(2)}} ${{fmtN(0.5*infGap)}} ${{fmtN(-unempGap)}} = ${{taylor.toFixed(2)}}%`;

  document.getElementById('fml-balanced').innerHTML =
    `R = ${{rstar.toFixed(2)}} + ${{pi.toFixed(2)}} + 0.5·(${{pi.toFixed(2)}} − ${{pistar.toFixed(2)}}) − 2.0·(${{u.toFixed(2)}} − ${{ustar.toFixed(2)}})<br>` +
    `&nbsp;&nbsp;= ${{rstar.toFixed(2)}} + ${{pi.toFixed(2)}} ${{fmtN(0.5*infGap)}} ${{fmtN(-2*unempGap)}} = ${{balanced.toFixed(2)}}%`;

  // Sensitivity sweep
  const uArr = [], tArr = [], bArr = [];
  for (let uu = 1.0; uu <= 12.0; uu += 0.1) {{
    const ug = uu - ustar;
    uArr.push(parseFloat(uu.toFixed(1)));
    tArr.push(parseFloat((rstar + pi + 0.5 * infGap - 1.0 * ug).toFixed(4)));
    bArr.push(parseFloat((rstar + pi + 0.5 * infGap - 2.0 * ug).toFixed(4)));
  }}

  const sensLayout = {{
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    margin: {{ t: 10, r: 10, b: 45, l: 50 }},
    xaxis: {{ gridcolor: '#e2e8f0', color: '#64748b', title: {{ text: 'Unemployment Rate (%)', font: {{ color: '#64748b', size: 11 }} }}, tickfont: {{ size: 11 }} }},
    yaxis: {{ gridcolor: '#e2e8f0', color: '#64748b', title: {{ text: 'Prescribed Rate (%)', font: {{ color: '#64748b', size: 11 }} }}, tickfont: {{ size: 11 }} }},
    legend: {{ x: 0.01, y: 0.99, bgcolor: 'transparent', font: {{ color: '#64748b', size: 11 }} }},
    hovermode: 'x unified',
    hoverlabel: {{ bgcolor: '#ffffff', bordercolor: '#e2e8f0', font: {{ color: '#0f172a' }} }},
    shapes: [{{ type: 'line', x0: ustar, x1: ustar, y0: 0, y1: 1, yref: 'paper',
               line: {{ color: '#94a3b8', width: 1, dash: 'dot' }} }}],
    annotations: [{{ x: ustar, y: 1, yref: 'paper', text: 'U*', showarrow: false,
                     font: {{ color: '#64748b', size: 10 }}, xanchor: 'left', xshift: 4 }}],
  }};
  const sensTraces = [
    {{ x: uArr, y: tArr, name: 'Taylor (1993)', line: {{ color: '#4f46e5', width: 2 }}, hovertemplate: '%{{y:.2f}}%' }},
    {{ x: uArr, y: bArr, name: 'Balanced Approach', line: {{ color: '#d97706', width: 2 }}, hovertemplate: '%{{y:.2f}}%' }},
  ];
  Plotly.react('sens-chart', sensTraces, sensLayout, {{responsive: true, displayModeBar: false}});
}}

recalc();
</script>
</body>
</html>"""


def main():
    fred = Fred(api_key=FRED_API_KEY)
    print("Fetching FRED data...")
    df = build_dataset(fred)
    print(f"  Dataset: {df.index[0].date()} → {df.index[-1].date()} ({len(df)} months)")

    data_json = to_json_payload(df)
    updated = date.today().strftime("%B %d, %Y")

    html = HTML_TEMPLATE.format(
        data_json=data_json,
        updated=updated,
        adjusted_latest=round(df["Adjusted"].iloc[-1], 2),
        firstdiff_latest=round(df["FirstDiff"].iloc[-1], 2),
    )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Written → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
