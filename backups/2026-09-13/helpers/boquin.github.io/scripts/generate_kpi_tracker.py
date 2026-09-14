#!/usr/bin/env python3
"""
KPI tracker dashboard generator.

Reads reports/kpi-tracker/<TICKER>/kpis.json (locked KPI list + quarterly
history, seeded/appended by hand or by an analyst pass over the latest
earnings release) and renders:
  - reports/kpi-tracker/<TICKER>/index.html  (per-ticker trend dashboard)
  - reports/kpi-tracker/index.html           (master list of tracked tickers)

Usage: python3 scripts/generate_kpi_tracker.py TICKER [TICKER ...]
"""
import json
import sys
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "kpi-tracker"

# dataviz reference palette, categorical slots in fixed order (never cycled)
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]


def fmt(value, unit):
    if value is None:
        return "—"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "$M":
        return f"${value:,.1f}M"
    return f"{value:,.1f}{unit}"


def qoq_yoy(history, key, i):
    """QoQ = vs previous entry. YoY = vs entry 4 quarters back, if present."""
    cur = history[i]["values"].get(key)
    qoq = None
    yoy = None
    if cur is not None and i > 0:
        prev = history[i - 1]["values"].get(key)
        if prev:
            qoq = (cur - prev) / prev * 100
    if cur is not None and i >= 4:
        prevy = history[i - 4]["values"].get(key)
        if prevy:
            yoy = (cur - prevy) / prevy * 100
    return qoq, yoy


def render_ticker_page(data):
    ticker = data["ticker"]
    company = data["company"]
    kpis = data["kpis"]
    history = data["history"]
    periods = [h["period"] for h in history]

    charts_html = []
    cards_html = []
    for idx, kpi in enumerate(kpis):
        key, label, unit = kpi["key"], kpi["label"], kpi["unit"]
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]
        xs = periods
        ys = [h["values"].get(key) for h in history]

        last_val = ys[-1] if ys else None
        qoq, yoy = qoq_yoy(history, key, len(history) - 1) if history else (None, None)
        chg_bits = []
        if qoq is not None:
            chg_bits.append(f"{qoq:+.1f}% QoQ")
        if yoy is not None:
            chg_bits.append(f"{yoy:+.1f}% YoY")
        chg = " · ".join(chg_bits) if chg_bits else "—"

        cards_html.append(f"""
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value" style="color:{color}">{fmt(last_val, unit)}</div>
      <div class="kpi-change">{chg}</div>
    </div>""")

        div_id = f"chart-{key}"
        charts_html.append(f"""
    <div class="chart-box">
      <div class="chart-title">{label} <span class="chart-unit">({unit})</span></div>
      <div id="{div_id}" class="plot"></div>
    </div>
    <script>
      Plotly.newPlot("{div_id}", [{{
        x: {json.dumps(xs)},
        y: {json.dumps(ys)},
        mode: "lines+markers+text",
        line: {{color: "{color}", width: 2, shape: "spline"}},
        marker: {{color: "{color}", size: 8}},
        text: {json.dumps([fmt(y, unit) for y in ys])},
        textposition: "top center",
        textfont: {{color: "{color}", size: 11}},
        hovertemplate: "%{{x}}<br>%{{y}}<extra></extra>",
        connectgaps: true
      }}], {{
        margin: {{l: 44, r: 16, t: 8, b: 32}},
        height: 220,
        xaxis: {{showgrid: false, tickfont: {{size: 11, color: "#666"}}}},
        yaxis: {{showgrid: true, gridcolor: "#eee", zeroline: false, tickfont: {{size: 11, color: "#666"}}}},
        plot_bgcolor: "white",
        paper_bgcolor: "white",
        showlegend: false
      }}, {{displayModeBar: false, responsive: true}});
    </script>""")

    latest = history[-1] if history else None
    rationale = data.get("kpi_rationale", "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} KPI Tracker</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#f5f7fa; margin:0; padding:0; color:#333; }}
  .header {{ background:#1a1a2e; color:white; padding:28px 32px; }}
  .header h1 {{ margin:0; font-size:1.8em; }}
  .header .sub {{ color:#aaa; font-size:.9em; margin-top:6px; }}
  .container {{ max-width:1000px; margin:0 auto; padding:32px 20px 60px; }}
  .back {{ display:inline-block; margin-bottom:20px; color:#007bff;
          text-decoration:none; font-size:.9em; }}
  .back:hover {{ text-decoration:underline; }}
  .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:14px; margin-bottom:28px; }}
  .kpi-card {{ background:white; border-radius:10px; box-shadow:0 2px 6px rgba(0,0,0,.08); padding:16px; }}
  .kpi-label {{ font-size:.78em; color:#666; margin-bottom:6px; }}
  .kpi-value {{ font-size:1.5em; font-weight:700; }}
  .kpi-change {{ font-size:.8em; color:#888; margin-top:4px; }}
  .chart-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:18px; }}
  .chart-box {{ background:white; border-radius:10px; box-shadow:0 2px 6px rgba(0,0,0,.08); padding:16px; }}
  .chart-title {{ font-size:.9em; font-weight:600; color:#333; margin-bottom:4px; }}
  .chart-unit {{ font-weight:400; color:#888; }}
  .rationale {{ background:white; border-radius:10px; box-shadow:0 2px 6px rgba(0,0,0,.08);
               padding:20px 24px; margin-top:28px; font-size:.88em; color:#555; line-height:1.5; }}
  .rationale h3 {{ margin-top:0; font-size:1em; color:#1a1a2e; }}
  table {{ width:100%; border-collapse:collapse; margin-top:28px; font-size:.85em; background:white;
          border-radius:10px; overflow:hidden; box-shadow:0 2px 6px rgba(0,0,0,.08); }}
  th, td {{ text-align:right; padding:10px 14px; }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ background:#1a1a2e; color:white; font-weight:600; }}
  tr:nth-child(even) {{ background:#fafafa; }}
</style>
</head>
<body>
<div class="header">
  <h1>📊 {ticker} KPI Tracker</h1>
  <div class="sub">{company} — key operating metrics tracked over time, locked from mgmt-disclosed KPIs · latest: {latest["period"] if latest else "n/a"} ({latest["report_date"] if latest else ""})</div>
</div>
<div class="container">
  <a class="back" href="../../index.html">← All Dashboards</a>
  <a class="back" href="../index.html" style="margin-left:16px;">← All Tracked Tickers</a>

  <div class="kpi-grid">
    {''.join(cards_html)}
  </div>

  <div class="chart-grid">
    {''.join(charts_html)}
  </div>

  <div class="rationale">
    <h3>Why these KPIs</h3>
    {rationale}
  </div>

  <table>
    <tr><th>Period</th>{''.join(f'<th>{k["label"]}</th>' for k in kpis)}</tr>
    {''.join('<tr><td>' + h["period"] + '</td>' + ''.join(f'<td>{fmt(h["values"].get(k["key"]), k["unit"])}</td>' for k in kpis) + '</tr>' for h in history)}
  </table>
</div>
</body>
</html>
"""


def render_master_index(tickers_data):
    cards = []
    for d in sorted(tickers_data, key=lambda x: x["ticker"]):
        latest = d["history"][-1] if d["history"] else None
        cards.append(f"""
    <article class="card">
      <div class="card-date">{d["ticker"]}</div>
      <div class="card-desc">{d["company"]} — latest: {latest["period"] if latest else "n/a"}</div>
      <a class="view-link" href="{d["ticker"]}/index.html">View KPI Tracker →</a>
    </article>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KPI Tracker</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#f5f7fa; margin:0; padding:0; color:#333; }}
  .header {{ background:#1a1a2e; color:white; padding:28px 32px; }}
  .header h1 {{ margin:0; font-size:1.8em; }}
  .header .sub {{ color:#aaa; font-size:.9em; margin-top:6px; }}
  .container {{ max-width:900px; margin:0 auto; padding:32px 20px 60px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:18px; }}
  .card {{ background:white; border-radius:10px; box-shadow:0 2px 6px rgba(0,0,0,.08);
          padding:24px; display:flex; flex-direction:column; gap:6px; }}
  .card-date {{ font-size:1.3em; font-weight:700; color:#1a1a2e; }}
  .card-desc {{ font-size:.85em; color:#666; }}
  .view-link {{ margin-top:auto; padding-top:12px; color:#007bff; text-decoration:none;
               font-weight:600; font-size:.9em; border-top:1px solid #f0f0f0; }}
  .view-link:hover {{ text-decoration:underline; }}
  .back {{ display:inline-block; margin-bottom:20px; color:#007bff; text-decoration:none; font-size:.9em; }}
  .back:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
<div class="header">
  <h1>📊 KPI Tracker</h1>
  <div class="sub">Per-company key operating metrics, tracked quarter over quarter</div>
</div>
<div class="container">
  <a class="back" href="../../index.html">← All Dashboards</a>
  <div class="grid">
    {''.join(cards)}
  </div>
</div>
</body>
</html>
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: generate_kpi_tracker.py TICKER [TICKER ...]")
        sys.exit(1)

    requested = [t.upper() for t in sys.argv[1:]]
    for ticker in requested:
        json_path = REPORTS_DIR / ticker / "kpis.json"
        if not json_path.exists():
            print(f"SKIP {ticker}: no {json_path} — seed it first (KPI selection is an analyst judgment call).")
            continue
        data = json.loads(json_path.read_text())
        out = render_ticker_page(data)
        out_path = REPORTS_DIR / ticker / "index.html"
        out_path.write_text(out)
        print(f"wrote {out_path}")

    # regenerate master index from every ticker dir that has a kpis.json
    all_data = []
    for d in sorted(REPORTS_DIR.iterdir()):
        jp = d / "kpis.json"
        if d.is_dir() and jp.exists():
            all_data.append(json.loads(jp.read_text()))
    if all_data:
        (REPORTS_DIR / "index.html").write_text(render_master_index(all_data))
        print(f"wrote {REPORTS_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
