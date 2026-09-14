#!/usr/bin/env python3
"""
Weekly generator: Manhattan temperature radial chart → boquin.xyz
  - Fetches ERA5 daily data from open-meteo (no API key)
  - Pre-computes 9 percentile band combos (lo: 10/20/30, hi: 70/80/90)
  - Outputs self-contained HTML with JS toggle buttons
  - Run: python3 scripts/generate_manhattan_temp.py
"""
import json
import requests
import pandas as pd
import numpy as np
from datetime import date
from pathlib import Path

LAT, LON   = 40.7829, -73.9654          # Central Park
START      = "2006-01-01"
REPORT_DIR = Path(__file__).parent.parent / "reports" / "manhattan-temp"
OUT        = REPORT_DIR / "index.html"
PCTS       = [10, 20, 30, 40, 50, 60, 70, 80, 90]


# ── data ─────────────────────────────────────────────────────────────────────

def fetch():
    end = date.today().isoformat()
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": LAT, "longitude": LON,
            "start_date": START, "end_date": end,
            "daily": "temperature_2m_mean",
            "timezone": "America/New_York",
            "temperature_unit": "fahrenheit",
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    return pd.DataFrame({"date": pd.to_datetime(d["time"]), "tmean": d["temperature_2m_mean"]})


def smooth_circular(arr):
    padded = np.concatenate([arr[-3:], arr, arr[:3]])
    return pd.Series(padded).rolling(7, center=True, min_periods=1).mean().values[3:-3]


def build_payload(df):
    df = df.copy()
    df["doy"]  = df["date"].dt.dayofyear
    df["year"] = df["date"].dt.year
    df = df[df["doy"] <= 365]

    cur_year = date.today().year
    hist     = df[df["year"] < cur_year]
    grp      = hist.groupby("doy")["tmean"]

    angles = [(d - 1) / 365 * 360 for d in range(1, 366)]

    # raw (unsmoothed) percentile curves
    pct = {}
    for p in PCTS:
        pct[f"p{p}"] = grp.quantile(p / 100).reindex(range(1, 366)).values.astype(float).tolist()

    # 9 pre-computed band polygons
    bands = {}
    for lo in [10, 20, 30]:
        for hi in [70, 80, 90]:
            outer_t = angles + [360.0]
            outer_r = pct[f"p{hi}"] + [pct[f"p{hi}"][0]]
            inner_t = list(reversed(angles))
            inner_r = list(reversed(pct[f"p{lo}"]))
            bands[f"{lo}_{hi}"] = {"theta": outer_t + inner_t, "r": outer_r + inner_r}

    # median closed loop
    med_theta = angles + [360.0]
    med_r     = pct["p50"] + [pct["p50"][0]]

    # current-year YTD (raw daily)
    yr = df[df["year"] == cur_year].sort_values("doy").copy()
    cur_theta = [(d - 1) / 365 * 360 for d in yr["doy"].tolist()]
    cur_r     = yr["tmean"].round(2).tolist()

    months    = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    month_doy = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    month_ang = [(d - 1) / 365 * 360 for d in month_doy]

    return {
        "bands":     bands,
        "med_theta": med_theta,
        "med_r":     [round(v, 2) for v in med_r],
        "cur_theta": cur_theta,
        "cur_r":     cur_r,
        "month_ang": month_ang,
        "months":    months,
        "cur_year":  cur_year,
        "updated":   date.today().isoformat(),
    }


# ── HTML template ─────────────────────────────────────────────────────────────

def build_html(payload):
    data_json = json.dumps(payload, separators=(",", ":"))
    cur_year  = payload["cur_year"]
    updated   = payload["updated"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Manhattan Temperature · boquin.xyz</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9f9f9;color:#222}}
header{{text-align:center;padding:22px 0 6px}}
header h1{{font-size:1.25rem;font-weight:700;letter-spacing:-0.01em}}
header p{{font-size:0.80rem;color:#777;margin-top:3px}}
.controls{{display:flex;justify-content:center;gap:48px;padding:12px 0 2px;flex-wrap:wrap}}
.tog{{display:flex;flex-direction:column;align-items:center;gap:6px}}
.tog label{{font-size:0.73rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#555}}
.btn-row{{display:flex;gap:4px}}
.btn-row button{{
  padding:5px 14px;border:1.5px solid #ccc;background:#fff;
  border-radius:5px;cursor:pointer;font-size:0.82rem;color:#444;
  transition:background 0.12s,border-color 0.12s;
}}
.btn-row button.active{{background:#2563eb;border-color:#2563eb;color:#fff;font-weight:600}}
.btn-row button:hover:not(.active){{background:#f0f0f0}}
#chart{{width:100%;max-width:820px;margin:0 auto}}
footer{{text-align:center;font-size:0.70rem;color:#bbb;padding:6px 0 18px}}
</style>
</head>
<body>
<header>
  <h1>Manhattan Daily Average Temperature</h1>
  <p>Central Park · ERA5 reanalysis · °F · updated {updated}</p>
</header>

<div class="controls">
  <div class="tog">
    <label>Lower bound</label>
    <div class="btn-row" id="lo-btns">
      <button data-val="10" onclick="setLo(this)" class="active">10th%</button>
      <button data-val="20" onclick="setLo(this)">20th%</button>
      <button data-val="30" onclick="setLo(this)">30th%</button>
    </div>
  </div>
  <div class="tog">
    <label>Upper bound</label>
    <div class="btn-row" id="hi-btns">
      <button data-val="70" onclick="setHi(this)">70th%</button>
      <button data-val="80" onclick="setHi(this)">80th%</button>
      <button data-val="90" onclick="setHi(this)" class="active">90th%</button>
    </div>
  </div>
</div>

<div id="chart"></div>
<footer>Source: open-meteo ERA5 archive &nbsp;·&nbsp; boquin.xyz</footer>

<script>
const D={data_json};
let lo=10,hi=90;

const layout={{
  height:740,autosize:true,
  paper_bgcolor:'#FFFFFF',
  margin:{{t:10,b:10,l:10,r:10}},
  legend:{{x:0.79,y:0.08,bgcolor:'rgba(255,255,255,0.88)',bordercolor:'#ddd',borderwidth:1,font:{{size:12}}}},
  polar:{{
    bgcolor:'#F7F7F7',
    angularaxis:{{
      direction:'clockwise',rotation:90,
      tickmode:'array',tickvals:D.month_ang,ticktext:D.months,
      tickfont:{{size:13,color:'#333'}},
      showgrid:true,gridcolor:'rgba(180,180,180,0.45)',
    }},
    radialaxis:{{
      range:[0,97],ticksuffix:'°',tickvals:[20,40,60,80],
      tickfont:{{size:10,color:'#666'}},
      showgrid:true,gridcolor:'rgba(180,180,180,0.45)',showline:false,
    }},
  }},
}};

function traces(lo,hi){{
  const b=D.bands[lo+'_'+hi];
  return [
    {{type:'scatterpolar',theta:b.theta,r:b.r,
      fill:'toself',fillcolor:'rgba(150,150,150,0.28)',line:{{width:0}},
      name:lo+'–'+hi+'th pct',hoverinfo:'skip'}},
    {{type:'scatterpolar',theta:D.med_theta,r:D.med_r,
      mode:'lines',line:{{color:'#5BB8D4',width:2.5}},name:'Median (2006–'+(D.cur_year-1)+')'}},
    {{type:'scatterpolar',theta:D.cur_theta,r:D.cur_r,
      mode:'lines',line:{{color:'#D62728',width:2.5}},name:D.cur_year+' (YTD)'}},
  ];
}}

const gd=document.getElementById('chart');
Plotly.newPlot(gd,traces(lo,hi),layout,{{responsive:true,displayModeBar:false}});

function setLo(btn){{
  lo=+btn.dataset.val;
  document.querySelectorAll('#lo-btns button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const b=D.bands[lo+'_'+hi];
  Plotly.restyle(gd,{{theta:[b.theta],r:[b.r],name:[lo+'–'+hi+'th pct']}},[0]);
}}
function setHi(btn){{
  hi=+btn.dataset.val;
  document.querySelectorAll('#hi-btns button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const b=D.bands[lo+'_'+hi];
  Plotly.restyle(gd,{{theta:[b.theta],r:[b.r],name:[lo+'–'+hi+'th pct']}},[0]);
}}
</script>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("Fetching ERA5 data …")
    df = fetch()
    print(f"  {len(df):,} days fetched ({df['date'].min().date()} → {df['date'].max().date()})")

    payload = build_payload(df)
    html    = build_html(payload)
    OUT.write_text(html, encoding="utf-8")
    print(f"Saved → {OUT}")


if __name__ == "__main__":
    main()
