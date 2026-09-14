"""Render data/valuations.json into the boquin.xyz equity-valuation dashboard page."""
import json, html, time

DATA_DIR = "/Users/macproajb/claude_projects/equity_valuation/data"
VAL_PATH = f"{DATA_DIR}/valuations.json"
OUT_PATH = "/Users/macproajb/claude_projects/boquin.github.io/reports/equity-valuation/index.html"

def esc(s):
    return html.escape(s, quote=True) if isinstance(s, str) else s

def main():
    val = json.load(open(VAL_PATH))
    rows = sorted(val.values(), key=lambda r: r["ticker"])
    sectors = sorted(set(r["sector"] for r in rows))
    counts = {"buy": 0, "hold": 0, "sell": 0}
    for r in rows:
        counts[r["rating"]] += 1
    generated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    rows_js = json.dumps([
        {
            "t": r["ticker"], "n": r["name"], "s": r["sector"], "si": r["sub_industry"],
            "r": r["rating"], "p": r["price"], "pt": r["pt"], "u": r["upside"],
            "e": r["explainer"], "v": r["variant"], "peers": r.get("peers", []),
            "upd": r.get("updated_at", ""),
        } for r in rows
    ])

    sector_options = "\n".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in sectors)

    html_out = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>S&amp;P 500 Equity Valuation Dashboard — boquin.xyz</title>
<style>
  :root {{
    --bg: #f7f7f8; --surface: #ffffff; --border: #e2e2e6; --ink: #1a1a1e;
    --ink-secondary: #55555c; --ink-muted: #8a8a92; --accent: #2563eb;
    --good: #16a34a; --good-bg: #dcfce7; --warn: #b45309; --warn-bg: #fef3c7;
    --bad: #dc2626; --bad-bg: #fee2e2; --row-hover: #f2f4f8; --input-bg: #ffffff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #121214; --surface: #1a1a1d; --border: #2e2e32; --ink: #ececee;
      --ink-secondary: #b4b4ba; --ink-muted: #83838a; --accent: #60a5fa;
      --good: #4ade80; --good-bg: #14532d; --warn: #fbbf24; --warn-bg: #4a3606;
      --bad: #f87171; --bad-bg: #4c1414; --row-hover: #202024; --input-bg: #1f1f23;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #121214; --surface: #1a1a1d; --border: #2e2e32; --ink: #ececee;
    --ink-secondary: #b4b4ba; --ink-muted: #83838a; --accent: #60a5fa;
    --good: #4ade80; --good-bg: #14532d; --warn: #fbbf24; --warn-bg: #4a3606;
    --bad: #f87171; --bad-bg: #4c1414; --row-hover: #202024; --input-bg: #1f1f23;
  }}
  :root[data-theme="light"] {{
    --bg: #f7f7f8; --surface: #ffffff; --border: #e2e2e6; --ink: #1a1a1e;
    --ink-secondary: #55555c; --ink-muted: #8a8a92; --accent: #2563eb;
    --good: #16a34a; --good-bg: #dcfce7; --warn: #b45309; --warn-bg: #fef3c7;
    --bad: #dc2626; --bad-bg: #fee2e2; --row-hover: #f2f4f8; --input-bg: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    margin: 0; padding: 28px 20px 60px;
  }}
  .wrap {{ max-width: 1280px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; letter-spacing: -0.01em; }}
  .subtitle {{ color: var(--ink-secondary); font-size: 0.9rem; margin: 0 0 18px; line-height: 1.5; max-width: 900px; }}
  .meta-row {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 18px; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 9px 15px; min-width: 90px; }}
  .stat .n {{ font-size: 1.25rem; font-weight: 600; }}
  .stat .l {{ font-size: 0.7rem; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.04em; }}

  .controls {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; align-items: center; }}
  .controls input, .controls select {{
    background: var(--input-bg); color: var(--ink); border: 1px solid var(--border);
    border-radius: 8px; padding: 7px 10px; font-size: 0.85rem;
  }}
  .controls input[type="text"] {{ min-width: 200px; }}
  .result-count {{ font-size: 0.78rem; color: var(--ink-muted); margin-left: auto; }}

  .table-scroll {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); max-height: 78vh; overflow-y: auto; }}
  table {{ border-collapse: collapse; width: 100%; min-width: 980px; font-size: 0.84rem; }}
  thead th {{
    text-align: left; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--ink-muted); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--border);
    position: sticky; top: 0; background: var(--surface); cursor: pointer; white-space: nowrap; z-index: 1;
  }}
  thead th:hover {{ color: var(--ink); }}
  tbody td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover {{ background: var(--row-hover); }}
  .ticker {{ font-weight: 700; }}
  .company {{ color: var(--ink-secondary); font-size: 0.76rem; }}
  .sector {{ color: var(--ink-muted); font-size: 0.72rem; }}
  .num {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .explainer {{ color: var(--ink-secondary); line-height: 1.5; max-width: 380px; font-size: 0.8rem; }}
  .badge {{ display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.02em; white-space: nowrap; }}
  .badge.buy {{ color: var(--good); background: var(--good-bg); }}
  .badge.hold {{ color: var(--warn); background: var(--warn-bg); }}
  .badge.sell {{ color: var(--bad); background: var(--bad-bg); }}
  .upside {{ font-weight: 600; }}
  .upside.pos {{ color: var(--good); }}
  .upside.neg {{ color: var(--bad); }}
  .footnote {{ margin-top: 18px; font-size: 0.76rem; color: var(--ink-muted); line-height: 1.6; max-width: 950px; }}
  .footnote code {{ background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; font-size: 0.9em; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>S&amp;P 500 Equity Valuation Dashboard</h1>
  <p class="subtitle">Every S&amp;P 500 constituent run through a mechanical Senior Equity Research Analyst screen — 10-year fade DCF (normalized capex, true debt-weighted WACC) blended 50/50 with sub-industry peer comps. Auto-generated, not analyst-reviewed. Last full refresh: {generated}.</p>

  <div class="meta-row">
    <div class="stat"><div class="n">{len(rows)}</div><div class="l">Covered</div></div>
    <div class="stat"><div class="n">{counts['buy']}</div><div class="l">Buy</div></div>
    <div class="stat"><div class="n">{counts['hold']}</div><div class="l">Hold</div></div>
    <div class="stat"><div class="n">{counts['sell']}</div><div class="l">Sell</div></div>
    <div class="stat"><div class="n">{503-len(rows)}</div><div class="l">Skipped*</div></div>
  </div>

  <div class="controls">
    <input type="text" id="search" placeholder="Search ticker or company…">
    <select id="sectorFilter"><option value="">All sectors</option>{sector_options}</select>
    <select id="ratingFilter">
      <option value="">All ratings</option>
      <option value="buy">Buy</option>
      <option value="hold">Hold</option>
      <option value="sell">Sell</option>
    </select>
    <span class="result-count" id="resultCount"></span>
  </div>

  <div class="table-scroll">
    <table id="tbl">
      <thead>
        <tr>
          <th data-key="t">Ticker</th>
          <th data-key="s">Sector</th>
          <th data-key="r">Rating</th>
          <th data-key="p" class="num">Price</th>
          <th data-key="pt" class="num">12M PT</th>
          <th data-key="u" class="num">Upside</th>
          <th>Explainer</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

  <p class="footnote">
    <strong>Methodology:</strong> FCF built bottom-up from EBITDA × (1-tax) − normalized capex (3yr-average capex/revenue), true WACC = (E/V)×Ke + (D/V)×Kd×(1-tax) using actual market cap/debt weights, 10-year explicit/fade window (growth glides to 2.5% terminal over years 6–10). Stage-1 growth is the mechanical 3yr revenue CAGR, floored at 2.5%, with an automatic override to EBITDA-CAGR-based growth when revenue and EBITDA have moved in opposite directions. Financials, Real Estate, and Utilities use a net-income FCFE variant (discounted at cost of equity) instead of the EBITDA/capex build, per standard convention for regulated/dividend-discount-style sectors. Peer comps use forward P/E and EV/EBITDA averaged within each GICS sub-industry (falling back to sector-level if the sub-industry has &lt;2 peers with data), with the peer/own multiple ratio clamped to [0.4x, 2.5x] to prevent a single distorted multiple from dominating. Extreme outputs are winsorized at +150%/−90% upside. <strong>*Skipped</strong> tickers had insufficient or economically unusable data (e.g. negative trailing earnings across the board) for either variant.
    <br><br>
    100-word-style explainers are template-generated from the computed numbers, not analyst-written prose — treat this as a mechanical screen for triage, not investment research. Financials sourced via yfinance; peer multiples via yfinance <code>.info</code> (SEC EDGAR <code>compare_companies</code> not used). Full methodology and the 10-name hand-reviewed pilot: see <code>equity_research/</code> reports. Not investment advice.
  </p>
</div>

<script>
const rows = {rows_js};
const tbody = document.querySelector('#tbl tbody');
const money = v => '$' + Number(v).toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}});

function render(data) {{
  tbody.innerHTML = data.map(r => `
    <tr>
      <td><div class="ticker">${{r.t}}</div><div class="company">${{r.n}}</div><div class="sector">${{r.si}}</div></td>
      <td class="sector">${{r.s}}</td>
      <td><span class="badge ${{r.r}}">${{r.r.toUpperCase()}}</span></td>
      <td class="num">${{money(r.p)}}</td>
      <td class="num">${{money(r.pt)}}</td>
      <td class="num upside ${{r.u >= 0 ? 'pos' : 'neg'}}">${{r.u >= 0 ? '+' : ''}}${{r.u.toFixed(1)}}%</td>
      <td class="explainer">${{r.e}}</td>
    </tr>
  `).join('');
  document.getElementById('resultCount').textContent = data.length + ' of ' + rows.length + ' shown';
}}

let sortKey = null, sortDir = 1;
function applyFilters() {{
  const q = document.getElementById('search').value.trim().toLowerCase();
  const sector = document.getElementById('sectorFilter').value;
  const rating = document.getElementById('ratingFilter').value;
  let data = rows.filter(r =>
    (!q || r.t.toLowerCase().includes(q) || r.n.toLowerCase().includes(q)) &&
    (!sector || r.s === sector) &&
    (!rating || r.r === rating)
  );
  if (sortKey) {{
    data = [...data].sort((a, b) => {{
      let av = a[sortKey], bv = b[sortKey];
      if (typeof av === 'string') {{ av = av.toLowerCase(); bv = bv.toLowerCase(); }}
      return av > bv ? sortDir : av < bv ? -sortDir : 0;
    }});
  }}
  render(data);
}}

document.getElementById('search').addEventListener('input', applyFilters);
document.getElementById('sectorFilter').addEventListener('change', applyFilters);
document.getElementById('ratingFilter').addEventListener('change', applyFilters);
document.querySelectorAll('thead th[data-key]').forEach(th => {{
  th.addEventListener('click', () => {{
    const key = th.dataset.key;
    sortDir = (sortKey === key) ? -sortDir : 1;
    sortKey = key;
    applyFilters();
  }});
}});
applyFilters();
</script>
</body>
</html>
"""
    import os
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write(html_out)
    print(f"Wrote {OUT_PATH} ({len(rows)} rows)")

if __name__ == "__main__":
    main()
