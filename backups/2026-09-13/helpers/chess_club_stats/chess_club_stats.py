"""
Impact Coaching Network chess-club roster stats: fetch, regression, scatter chart.

Data source: each school's public stats page (impactcoachingnetwork.org/<slug>)
embeds an iframe pointing at
    https://icnadmin2.com/icnroster/ck_data_<SCHOOL>.html
which is a bare HTML table, no API/auth needed. This module fetches that table,
parses it, fits a linear regression between any two numeric columns with
single-pass outlier trimming, and renders a self-contained interactive
scatter+regression-band HTML chart (dataviz-skill styled, light/dark aware).

CLI:
    python3 chess_club_stats.py --school PS11 --x ck_rating --y uscf_rating \
        --min-x 900 --z-thresh 1.5 --out /tmp/chart.html

Columns available (order matches the source table):
    name, grade, ck_rating, puzzles_correct, puzzles_attempted, plw,
    uscf_rating, level, les7, wor7, prob_ytd, l_ytd, w_ytd, plw_ytd

Note: uscf_rating == 0 means "no USCF rating on file" for that player, not an
actual rating of zero — fit_linreg/remove_outliers callers should pre-filter
those out when uscf_rating is one of the two fields (see main()).
"""
import argparse
import json
import math
import re
import urllib.request

DATA_URL_TMPL = "https://icnadmin2.com/icnroster/ck_data_{school}.html"

COLUMNS = [
    "name", "grade", "ck_rating", "puzzles_correct", "puzzles_attempted",
    "plw", "uscf_rating", "level", "les7", "wor7", "prob_ytd", "l_ytd",
    "w_ytd", "plw_ytd",
]
NUMERIC_COLUMNS = set(COLUMNS) - {"name", "grade", "level"}

LABELS = {
    "ck_rating": "Chess Kid Rating",
    "uscf_rating": "USCF Rating",
    "puzzles_correct": "Puzzles Correct",
    "puzzles_attempted": "Puzzles Attempted",
    "plw": "PLW",
    "les7": "Lessons (7d)",
    "wor7": "Worksheets (7d)",
    "prob_ytd": "Problems YTD",
    "l_ytd": "Losses YTD",
    "w_ytd": "Wins YTD",
    "plw_ytd": "PLW YTD",
}


def fetch_html(school: str) -> str:
    url = DATA_URL_TMPL.format(school=school.upper())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_roster(html: str) -> list[dict]:
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    out = []
    for r in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if len(cells) < len(COLUMNS):
            continue
        rec = {}
        for col, cell in zip(COLUMNS, cells):
            v = cell.strip()
            if col in NUMERIC_COLUMNS:
                try:
                    v = int(v)
                except ValueError:
                    try:
                        v = float(v)
                    except ValueError:
                        v = None
            rec[col] = v
        out.append(rec)
    return out


def fit_linreg(pts: list[dict], xkey: str, ykey: str) -> dict:
    n = len(pts)
    xs = [p[xkey] for p in pts]
    ys = [p[ykey] for p in pts]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    Sxx = sum((x - mean_x) ** 2 for x in xs)
    Sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    Syy = sum((y - mean_y) ** 2 for y in ys)
    slope = Sxy / Sxx
    intercept = mean_y - slope * mean_x
    resid = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    dof = n - 2
    se = math.sqrt(sum(r ** 2 for r in resid) / dof)
    r = Sxy / math.sqrt(Sxx * Syy)
    return dict(n=n, slope=slope, intercept=intercept, r=r, r2=r * r,
                se=se, mean_x=mean_x, Sxx=Sxx, resid=resid)


def remove_outliers(pts: list[dict], xkey: str, ykey: str, z_thresh: float = 1.5):
    """Single-pass trim: standardized residuals from the full-sample fit,
    not iterative — iterative re-fitting shrinks se each round and spirals
    into removing far too many points."""
    f0 = fit_linreg(pts, xkey, ykey)
    std_resid = [res / f0["se"] for res in f0["resid"]]
    clean = [p for p, z in zip(pts, std_resid) if abs(z) <= z_thresh]
    outliers = [p for p, z in zip(pts, std_resid) if abs(z) > z_thresh]
    fit = fit_linreg(clean, xkey, ykey) if len(clean) >= 3 else f0
    return clean, outliers, fit


def build_band(fit: dict, xkey: str, clean_pts: list[dict], n_points: int = 60, t95: float = 2.00):
    xs = [p[xkey] for p in clean_pts]
    xmin, xmax = min(xs), max(xs)
    pad = (xmax - xmin) * 0.05
    lo, hi = xmin - pad, xmax + pad
    n, slope, intercept = fit["n"], fit["slope"], fit["intercept"]
    se, mean_x, Sxx = fit["se"], fit["mean_x"], fit["Sxx"]
    band = []
    for i in range(n_points + 1):
        x = lo + (hi - lo) * i / n_points
        yhat = slope * x + intercept
        ci = t95 * se * math.sqrt(1 / n + (x - mean_x) ** 2 / Sxx)
        band.append({"x": round(x, 1), "yhat": round(yhat, 1),
                     "lo": round(yhat - ci, 1), "hi": round(yhat + ci, 1)})
    return band


HTML_TEMPLATE = r"""<title>{title}</title>
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --surface-2:      #f4f3f0;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #83817a;
    --grid-line:      #e3e1db;
    --series-1:       #2a78d6;
    --series-1-fill:  #2a78d61a;
    --series-1-line:  #1d5aa8;
    --outlier:        #83817a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1: #1a1a19; --surface-2: #232322; --text-primary: #ffffff;
      --text-secondary: #c3c2b7; --text-muted: #8b897f; --grid-line: #33322f;
      --series-1: #3987e5; --series-1-fill: #3987e526; --series-1-line: #7fb4f0;
      --outlier: #8b897f;
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1: #1a1a19; --surface-2: #232322; --text-primary: #ffffff;
    --text-secondary: #c3c2b7; --text-muted: #8b897f; --grid-line: #33322f;
    --series-1: #3987e5; --series-1-fill: #3987e526; --series-1-line: #7fb4f0;
    --outlier: #8b897f;
  }}
  .viz-root {{ background: var(--surface-1); color: var(--text-primary); padding: 24px; }}
  .viz-header h1 {{ font-size: 1.15rem; margin: 0 0 2px; }}
  .viz-header p {{ font-size: 0.85rem; color: var(--text-secondary); margin: 0 0 4px; }}
  .viz-header .meta {{ font-size: 0.78rem; color: var(--text-muted); margin: 0 0 16px; }}
  .chart-wrap {{ position: relative; width: 100%; overflow-x: auto; }}
  svg {{ display: block; width: 100%; height: auto; }}
  .axis-label {{ fill: var(--text-secondary); font-size: 12px; }}
  .axis-title {{ fill: var(--text-secondary); font-size: 12.5px; font-weight: 600; }}
  .grid-line {{ stroke: var(--grid-line); stroke-width: 1; }}
  .band-fill {{ fill: var(--series-1-fill); }}
  .reg-line {{ stroke: var(--series-1-line); stroke-width: 2; stroke-linecap: round; fill: none; }}
  .pt {{ fill: var(--series-1); fill-opacity: 0.8; stroke: var(--surface-1); stroke-width: 1; cursor: pointer; }}
  .pt:hover {{ fill-opacity: 1; }}
  .pt-outlier {{ fill: none; stroke: var(--outlier); stroke-width: 1.5; stroke-dasharray: 2 1.5; cursor: pointer; opacity: 0.75; }}
  .pt-outlier:hover {{ opacity: 1; }}
  .tooltip {{
    position: absolute; pointer-events: none; background: var(--surface-2);
    border: 1px solid var(--grid-line); border-radius: 6px; padding: 6px 9px;
    font-size: 12px; color: var(--text-primary); box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    opacity: 0; transition: opacity 0.1s; white-space: nowrap; z-index: 10;
  }}
  .tooltip .t-name {{ font-weight: 600; }}
  .tooltip .t-row {{ color: var(--text-secondary); }}
  .legend {{ display: flex; gap: 18px; align-items: center; margin-top: 10px; font-size: 12.5px; color: var(--text-secondary); flex-wrap: wrap; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .swatch-dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--series-1); display: inline-block; }}
  .swatch-dot-outlier {{ width: 9px; height: 9px; border-radius: 50%; background: none; border: 1.5px dashed var(--outlier); display: inline-block; box-sizing: border-box; }}
  .swatch-line {{ width: 16px; height: 2px; background: var(--series-1-line); display: inline-block; }}
  .swatch-band {{ width: 16px; height: 9px; background: var(--series-1-fill); border: 1px solid var(--series-1-line); display: inline-block; }}
  .foot {{ margin-top: 14px; font-size: 0.78rem; color: var(--text-muted); line-height: 1.5; }}
</style>

<div class="viz-root">
  <div class="viz-header">
    <h1>{title}</h1>
    <p>{subtitle}</p>
    <p class="meta">{meta}</p>
  </div>
  <div class="chart-wrap">
    <svg id="chart" viewBox="0 0 860 520" role="img" aria-label="Scatter plot of {xlabel} versus {ylabel} with a regression line and 95% confidence band"></svg>
    <div class="tooltip" id="tooltip"></div>
  </div>
  <div class="legend">
    <div class="legend-item"><span class="swatch-dot"></span> Player (n = {n_clean})</div>
    <div class="legend-item"><span class="swatch-dot-outlier"></span> Outlier, excluded from fit (n = {n_outliers})</div>
    <div class="legend-item"><span class="swatch-line"></span> Regression line</div>
    <div class="legend-item"><span class="swatch-band"></span> 95% confidence band</div>
  </div>
  <div class="foot">{footnote}</div>
</div>

<script>
const DATA = {data_json};
const clean = DATA.clean, outliers = DATA.outliers, band = DATA.band;
const xlabel = {xlabel_json}, ylabel = {ylabel_json};

const svg = document.getElementById('chart');
const tooltip = document.getElementById('tooltip');
const NS = 'http://www.w3.org/2000/svg';
const W = 860, H = 520;
const M = {{ top: 20, right: 24, bottom: 56, left: 60 }};
const plotW = W - M.left - M.right, plotH = H - M.top - M.bottom;

const allPts = clean.concat(outliers);
const allX = allPts.map(p => p.x).concat(band.map(b => b.x));
const allY = allPts.map(p => p.y).concat(band.map(b => b.lo)).concat(band.map(b => b.hi));
const xMin = {xmin_json} !== null ? {xmin_json} : Math.floor(Math.min(...allX, 0) / 100) * 100;
const xMax = Math.ceil(Math.max(...allX) / 100) * 100;
const yMin = 0, yMax = Math.ceil(Math.max(...allY) / 100) * 100;

function sx(x) {{ return M.left + (x - xMin) / (xMax - xMin) * plotW; }}
function sy(y) {{ return M.top + plotH - (y - yMin) / (yMax - yMin) * plotH; }}
function el(tag, attrs) {{ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }}

const xStep = Math.max(50, Math.round((xMax - xMin) / 8 / 50) * 50);
const yStep = Math.max(50, Math.round(yMax / 8 / 50) * 50);
const xTicks = []; for (let v = xMin; v <= xMax; v += xStep) xTicks.push(v);
const yTicks = []; for (let v = 0; v <= yMax; v += yStep) yTicks.push(v);

xTicks.forEach(t => {{
  svg.appendChild(el('line', {{ class: 'grid-line', x1: sx(t), x2: sx(t), y1: M.top, y2: M.top + plotH }}));
  const lbl = el('text', {{ class: 'axis-label', x: sx(t), y: M.top + plotH + 20, 'text-anchor': 'middle' }});
  lbl.textContent = t; svg.appendChild(lbl);
}});
yTicks.forEach(t => {{
  svg.appendChild(el('line', {{ class: 'grid-line', x1: M.left, x2: M.left + plotW, y1: sy(t), y2: sy(t) }}));
  const lbl = el('text', {{ class: 'axis-label', x: M.left - 10, y: sy(t) + 4, 'text-anchor': 'end' }});
  lbl.textContent = t; svg.appendChild(lbl);
}});

const xTitle = el('text', {{ class: 'axis-title', x: M.left + plotW / 2, y: H - 10, 'text-anchor': 'middle' }});
xTitle.textContent = xlabel; svg.appendChild(xTitle);
const yTitle = el('text', {{ class: 'axis-title', x: -(M.top + plotH / 2), y: 18, 'text-anchor': 'middle', transform: 'rotate(-90)' }});
yTitle.textContent = ylabel; svg.appendChild(yTitle);

let bandPath = 'M ' + band.map(b => `${{sx(b.x)}},${{sy(b.hi)}}`).join(' L ');
bandPath += ' L ' + band.slice().reverse().map(b => `${{sx(b.x)}},${{sy(b.lo)}}`).join(' L ') + ' Z';
svg.appendChild(el('path', {{ class: 'band-fill', d: bandPath }}));
svg.appendChild(el('path', {{ class: 'reg-line', d: 'M ' + band.map(b => `${{sx(b.x)}},${{sy(b.yhat)}}`).join(' L ') }}));

function showTip(ev, p, extra) {{
  tooltip.innerHTML = `<div class="t-name">${{p.name}}</div><div class="t-row">${{xlabel}} ${{p.x}} · ${{ylabel}} ${{p.y}}</div>${{extra || ''}}`;
  tooltip.style.opacity = 1;
  const wrapRect = svg.parentElement.getBoundingClientRect();
  tooltip.style.left = (ev.clientX - wrapRect.left + 12) + 'px';
  tooltip.style.top = (ev.clientY - wrapRect.top - 12) + 'px';
}}

clean.forEach(p => {{
  const c = el('circle', {{ class: 'pt', cx: sx(p.x), cy: sy(p.y), r: 5 }});
  c.addEventListener('mousemove', ev => showTip(ev, p));
  c.addEventListener('mouseleave', () => {{ tooltip.style.opacity = 0; }});
  svg.appendChild(c);
}});
outliers.forEach(p => {{
  const c = el('circle', {{ class: 'pt-outlier', cx: sx(p.x), cy: sy(p.y), r: 5.5 }});
  c.addEventListener('mousemove', ev => showTip(ev, p, '<div class="t-row">excluded outlier</div>'));
  c.addEventListener('mouseleave', () => {{ tooltip.style.opacity = 0; }});
  svg.appendChild(c);
}});
</script>
"""


def render_html(clean, outliers, band, xkey, ykey, *, title, subtitle, meta,
                 xmin=None) -> str:
    xlabel = LABELS.get(xkey, xkey)
    ylabel = LABELS.get(ykey, ykey)
    data = {
        "clean": [{"name": p["name"], "x": p[xkey], "y": p[ykey]} for p in clean],
        "outliers": [{"name": p["name"], "x": p[xkey], "y": p[ykey]} for p in outliers],
        "band": band,
    }
    fit = fit_linreg(clean, xkey, ykey)
    footnote = (
        f"{ylabel} = {fit['slope']:.3f} × {xlabel} "
        f"{'+' if fit['intercept'] >= 0 else '−'} {abs(fit['intercept']):.1f} "
        f"&nbsp;·&nbsp; r = {fit['r']:.2f} (r² = {fit['r2']:.2f}) "
        f"&nbsp;·&nbsp; n = {fit['n']}. "
        f"{len(outliers)} outlier(s) (|standardized residual| &gt; 1.5) excluded from the fit."
    )
    return HTML_TEMPLATE.format(
        title=title, subtitle=subtitle, meta=meta,
        xlabel=xlabel, ylabel=ylabel,
        n_clean=len(clean), n_outliers=len(outliers),
        footnote=footnote,
        data_json=json.dumps(data),
        xlabel_json=json.dumps(xlabel), ylabel_json=json.dumps(ylabel),
        xmin_json=json.dumps(xmin),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--school", required=True, help="School code, e.g. PS11 (matches ck_data_<SCHOOL>.html)")
    ap.add_argument("--x", default="ck_rating", choices=sorted(NUMERIC_COLUMNS))
    ap.add_argument("--y", default="uscf_rating", choices=sorted(NUMERIC_COLUMNS))
    ap.add_argument("--min-x", type=float, default=None, help="Drop rows with x below this value")
    ap.add_argument("--min-y", type=float, default=None, help="Drop rows with y below this value")
    ap.add_argument("--z-thresh", type=float, default=1.5, help="Standardized-residual cutoff for outlier trim")
    ap.add_argument("--out", required=True, help="Output HTML path")
    args = ap.parse_args()

    html = fetch_html(args.school)
    roster = parse_roster(html)
    pts = [p for p in roster if p.get(args.x) is not None and p.get(args.y) is not None]
    # a rating of 0 in this feed means "not on file", not a real value
    pts = [p for p in pts if p[args.x] != 0 and p[args.y] != 0]
    if args.min_x is not None:
        pts = [p for p in pts if p[args.x] >= args.min_x]
    if args.min_y is not None:
        pts = [p for p in pts if p[args.y] >= args.min_y]

    clean, outliers, fit = remove_outliers(pts, args.x, args.y, z_thresh=args.z_thresh)
    band = build_band(fit, args.x, clean)

    xlabel, ylabel = LABELS.get(args.x, args.x), LABELS.get(args.y, args.y)
    subtitle = f"{args.school.upper()} Chess Club & Team — each point is one player"
    if args.min_x:
        subtitle += f", {xlabel} ≥ {args.min_x:g}"
    meta = f"Source: impactcoachingnetwork.org (school code {args.school.upper()})"

    out_html = render_html(
        clean, outliers, band, args.x, args.y,
        title=f"{xlabel} vs. {ylabel}", subtitle=subtitle, meta=meta,
        xmin=args.min_x,
    )
    with open(args.out, "w") as f:
        f.write(out_html)

    print(f"n={len(pts)} clean={len(clean)} outliers={len(outliers)}")
    print(f"slope={fit['slope']:.4f} intercept={fit['intercept']:.2f} r={fit['r']:.3f} r2={fit['r2']:.3f}")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
