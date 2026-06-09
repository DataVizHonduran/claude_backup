"""
Macro Aviation Pulse — Static HTML Generator
=============================================
Two-tab dashboard:
  Tab 1 — EM Regions:       Brazil, Mexico, South Korea, China
  Tab 2 — Middle East Hubs: UAE, Qatar, Saudi Arabia, Turkey, Kuwait/Bahrain

Fetches live aircraft counts from OpenSky Network REST API, persists a
7-day history in history.json, computes Congestion Index per region,
and writes a standalone Plotly HTML report.

Required env vars (registered OpenSky account — ~4,000 req/day):
    OPENSKY_USERNAME
    OPENSKY_PASSWORD

Anonymous access (~100 req/day) works but will hit limits quickly at
9 regions × hourly polling.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import requests

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent.parent
OUTPUT_DIR   = ROOT / "reports" / "macro-aviation-pulse"
OUTPUT_FILE  = OUTPUT_DIR / "index.html"
HISTORY_FILE = OUTPUT_DIR / "history.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Region definitions ───────────────────────────────────────────────────────

REGIONS_EM: dict[str, dict] = {
    "Brazil": {
        "lamin": -34.0, "lomin": -74.0, "lamax":  5.0, "lomax": -34.0,
        "color": "#00b4d8", "flag": "🇧🇷",
    },
    "Mexico": {
        "lamin":  14.0, "lomin": -118.0, "lamax": 33.0, "lomax": -86.0,
        "color": "#f4a261", "flag": "🇲🇽",
    },
    "South Korea": {
        "lamin":  33.0, "lomin": 124.0, "lamax": 38.5, "lomax": 130.0,
        "color": "#e76f51", "flag": "🇰🇷",
    },
    "China": {
        "lamin":  18.0, "lomin":  73.0, "lamax": 53.0, "lomax": 135.0,
        "color": "#2a9d8f", "flag": "🇨🇳",
    },
}

REGIONS_ME: dict[str, dict] = {
    "UAE": {
        "lamin": 22.5, "lomin": 51.5, "lamax": 26.5, "lomax": 56.5,
        "color": "#c9a227", "flag": "🇦🇪",
    },
    "Qatar": {
        "lamin": 24.4, "lomin": 50.0, "lamax": 26.3, "lomax": 52.0,
        "color": "#a78bfa", "flag": "🇶🇦",
    },
    "Saudi Arabia": {
        "lamin": 19.5, "lomin": 37.0, "lamax": 25.5, "lomax": 48.0,
        "color": "#34d399", "flag": "🇸🇦",
    },
    "Turkey": {
        "lamin": 39.5, "lomin": 26.0, "lamax": 42.5, "lomax": 31.5,
        "color": "#f87171", "flag": "🇹🇷",
    },
    "Kuwait / Bahrain": {
        "lamin": 25.5, "lomin": 47.0, "lamax": 30.5, "lomax": 51.5,
        "color": "#fb923c", "flag": "🇰🇼",
    },
}

ALL_REGIONS: dict[str, dict] = {**REGIONS_EM, **REGIONS_ME}

ALERT_CI_THRESHOLD  = 0.80
MAX_OBSERVATIONS = 240
OPENSKY_URL         = "https://opensky-network.org/api/states/all"
REQUEST_TIMEOUT_S   = 20

ICAO24_IDX   = 0
CALLSIGN_IDX = 1
LON_IDX      = 5
LAT_IDX      = 6


# ── OpenSky API ───────────────────────────────────────────────────────────────

def _auth() -> tuple[str, str] | None:
    user = os.environ.get("OPENSKY_USERNAME")
    pw   = os.environ.get("OPENSKY_PASSWORD")
    if user and pw:
        return (user, pw)
    print("  [warn] OPENSKY credentials not set — using anonymous access", file=sys.stderr)
    return None


def get_count_and_positions(region_name: str) -> tuple[int, list[dict]]:
    bbox = ALL_REGIONS[region_name]
    params = {
        "lamin": bbox["lamin"], "lomin": bbox["lomin"],
        "lamax": bbox["lamax"], "lomax": bbox["lomax"],
    }
    try:
        resp = requests.get(
            OPENSKY_URL, params=params, auth=_auth(), timeout=REQUEST_TIMEOUT_S
        )
        if resp.status_code == 429:
            print(f"  [warn] Rate limited on {region_name} (HTTP 429)", file=sys.stderr)
            return 0, []
        if resp.status_code == 401:
            print(f"  [error] Auth failed (HTTP 401) — check credentials", file=sys.stderr)
            return 0, []
        resp.raise_for_status()
        states = resp.json().get("states") or []
    except requests.Timeout:
        print(f"  [warn] Timeout fetching {region_name}", file=sys.stderr)
        return 0, []
    except Exception as exc:
        print(f"  [warn] Error fetching {region_name}: {exc}", file=sys.stderr)
        return 0, []

    seen_icao: set[str] = set()
    positions: list[dict] = []
    for s in states:
        try:
            icao = s[ICAO24_IDX] or ""
            seen_icao.add(icao)
            lat, lon = s[LAT_IDX], s[LON_IDX]
            if lat is not None and lon is not None:
                positions.append({
                    "lat":      float(lat),
                    "lon":      float(lon),
                    "callsign": (s[CALLSIGN_IDX] or icao).strip(),
                })
        except (IndexError, TypeError):
            continue

    return len(seen_icao), positions


# ── History ───────────────────────────────────────────────────────────────────

def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def append_and_save_history(history: list[dict], new_row: dict) -> list[dict]:
    history.append(new_row)
    history = history[-MAX_OBSERVATIONS:]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))
    return history


# ── Congestion Index ──────────────────────────────────────────────────────────

def compute_ci(region: str, current_count: int, history: list[dict]) -> float:
    counts = [r["counts"][region] for r in history if region in r.get("counts", {})]
    if not counts:
        return 1.0
    mean = sum(counts) / len(counts)
    return round(current_count / mean, 4) if mean > 0 else 1.0


# ── Figure builders ───────────────────────────────────────────────────────────

_DARK = dict(paper_bgcolor="#0d1117", plot_bgcolor="#161b22", font_color="#e6edf3")
_GRID = dict(gridcolor="#21262d", zerolinecolor="#30363d")


def build_map_figure(
    all_positions: dict[str, list[dict]],
    regions: dict[str, dict],
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
) -> go.Figure:
    fig = go.Figure()
    total = sum(len(v) for v in all_positions.values())

    for region, positions in all_positions.items():
        if not positions:
            continue
        cfg = regions[region]
        fig.add_trace(go.Scattergeo(
            lat=[p["lat"] for p in positions],
            lon=[p["lon"] for p in positions],
            mode="markers",
            marker=dict(size=4, color=cfg["color"], opacity=0.75),
            name=f"{cfg['flag']} {region}",
            text=[f"{p['callsign']}<br>{region}" for p in positions],
            hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        geo=dict(
            showland=True,       landcolor="#1c2128",
            showocean=True,      oceancolor="#0d1117",
            showcountries=True,  countrycolor="#30363d",
            showcoastlines=True, coastlinecolor="#30363d",
            showframe=False,     bgcolor="#0d1117",
            projection_type="natural earth",
            lataxis_range=list(lat_range),
            lonaxis_range=list(lon_range),
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=400,
        legend=dict(bgcolor="rgba(22,27,34,0.85)", bordercolor="#30363d",
                    borderwidth=1, font=dict(size=11)),
        annotations=[dict(
            text=f"{total:,} aircraft tracked",
            x=0.01, y=0.98, xref="paper", yref="paper",
            showarrow=False, font=dict(size=11, color="#8b949e"),
            bgcolor="rgba(22,27,34,0.7)", align="left",
        )],
        **_DARK,
    )
    return fig


def build_timeseries_figure(
    history: list[dict],
    regions: dict[str, dict],
) -> go.Figure:
    fig = go.Figure()

    for region, cfg in regions.items():
        rows = sorted(
            [(r["ts"], r["counts"].get(region, 0)) for r in history if "counts" in r],
            key=lambda x: x[0],
        )
        x = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts, _ in rows]
        y = [cnt for _, cnt in rows]
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines+markers",
            name=f"{cfg['flag']} {region}",
            line=dict(color=cfg["color"], width=2),
            marker=dict(size=4),
            hovertemplate=f"<b>{region}</b><br>%{{x|%b %d %H:%M UTC}}<br>%{{y:,}} aircraft<extra></extra>",
        ))

    fig.update_layout(
        xaxis=dict(title="UTC", showgrid=True, tickformat="%b %d %H:%M", **_GRID),
        yaxis=dict(title="Aircraft Count", showgrid=True, **_GRID),
        hovermode="x unified",
        height=300,
        margin=dict(l=60, r=20, t=20, b=60),
        legend=dict(bgcolor="rgba(22,27,34,0.85)", bordercolor="#30363d", borderwidth=1),
        **_DARK,
    )
    if not history:
        fig.add_annotation(
            text="Accumulating history — check back after a few runs",
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False, font=dict(size=13, color="#8b949e"),
        )
    return fig


def build_ci_bar_figure(
    ci_values: dict[str, float],
    regions: dict[str, dict],
) -> go.Figure:
    region_list = list(ci_values.keys())
    values  = [ci_values[r] for r in region_list]
    colors  = ["#f85149" if v < ALERT_CI_THRESHOLD else "#e3b341" if v < 0.95 else "#2ea043"
               for v in values]
    labels  = [f"{regions[r]['flag']} {r}" for r in region_list]

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker_color=colors,
        text=[f"{v:.2f}" for v in values],
        textposition="outside",
        hovertemplate="%{y}: CI %{x:.3f}<extra></extra>",
    ))
    fig.add_vline(x=ALERT_CI_THRESHOLD,
                  line=dict(color="#f85149", width=1.5, dash="dash"),
                  annotation_text=f"Alert ({ALERT_CI_THRESHOLD:.0%})",
                  annotation_font=dict(color="#f85149", size=10),
                  annotation_position="top right")
    fig.add_vline(x=1.0, line=dict(color="#484f58", width=1, dash="dot"))

    x_max = max(values) * 1.25 + 0.1 if values else 1.5
    fig.update_layout(
        xaxis=dict(title="CI (1.0 = 7-day baseline)", range=[0, x_max], **_GRID),
        yaxis=dict(showgrid=False),
        height=40 + len(region_list) * 36,
        margin=dict(l=130, r=60, t=10, b=40),
        **_DARK,
    )
    return fig


# ── HTML helpers ──────────────────────────────────────────────────────────────

def build_kpi_html(
    counts: dict[str, int],
    ci_values: dict[str, float],
    alerts: list[str],
    regions: dict[str, dict],
) -> str:
    cards = []
    for region, count in counts.items():
        ci  = ci_values[region]
        cfg = regions[region]
        if ci < ALERT_CI_THRESHOLD:
            ci_color, ci_label = "#f85149", "ALERT"
        elif ci < 0.95:
            ci_color, ci_label = "#e3b341", "below avg"
        else:
            ci_color, ci_label = "#2ea043", "nominal"
        cards.append(f"""
        <div class="kpi-card" style="border-left:3px solid {cfg['color']};">
          <div class="kpi-region">{cfg['flag']} {region}</div>
          <div class="kpi-count">{count:,}</div>
          <div class="kpi-label">aircraft</div>
          <div class="kpi-ci" style="color:{ci_color};">CI {ci:.2f} · {ci_label}</div>
        </div>""")

    if alerts:
        items = "".join(
            f'<li>{regions[r]["flag"]} <strong>{r}</strong> — traffic &gt;20% below 7-day baseline</li>'
            for r in alerts
        )
        alert_html = f'<div class="alert-box"><div class="alert-title">⚠ Congestion Alert</div><ul>{items}</ul></div>'
    else:
        alert_html = '<div class="alert-ok">✓ All regions within normal range</div>'

    return f'<div class="kpi-strip">{"".join(cards)}</div>{alert_html}'


def build_tab_html(
    tab_id: str,
    counts: dict[str, int],
    ci_values: dict[str, float],
    alerts: list[str],
    all_positions: dict[str, list[dict]],
    history: list[dict],
    regions: dict[str, dict],
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
) -> str:
    map_fig  = build_map_figure(all_positions, regions, lat_range, lon_range)
    ts_fig   = build_timeseries_figure(history, regions)
    ci_fig   = build_ci_bar_figure(ci_values, regions)
    kpi_html = build_kpi_html(counts, ci_values, alerts, regions)

    map_div = map_fig.to_html(full_html=False, include_plotlyjs=False, div_id=f"map-{tab_id}")
    ts_div  = ts_fig.to_html(full_html=False, include_plotlyjs=False, div_id=f"ts-{tab_id}")
    ci_div  = ci_fig.to_html(full_html=False, include_plotlyjs=False, div_id=f"ci-{tab_id}")

    return f"""
    <div id="tab-{tab_id}" class="tab-panel">
      {kpi_html}
      <div class="row" style="margin-top:20px;">
        <div class="col-main panel">
          <div class="section-title">Live Aircraft Positions</div>
          {map_div}
        </div>
        <div class="col-side panel">
          <div class="section-title">Congestion Index (CI = current ÷ 7-day mean)</div>
          {ci_div}
          <div style="font-size:.7rem;color:#484f58;margin-top:10px;line-height:1.6;">
            CI &gt; 0.95 = nominal &nbsp;·&nbsp; 0.80–0.95 = below avg &nbsp;·&nbsp; &lt; 0.80 = alert
          </div>
        </div>
      </div>
      <div class="panel" style="margin-top:20px;">
        <div class="section-title">7-Day Traffic Trend</div>
        {ts_div}
      </div>
    </div>"""


# ── CSS + JS ──────────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e6edf3; font-family: 'Courier New', monospace; }
.header { background: #161b22; border-bottom: 1px solid #30363d; padding: 20px 32px; display: flex; align-items: center; gap: 14px; }
.header h1 { font-size: 1.4rem; font-weight: 600; letter-spacing: .04em; }
.header .sub { font-size: .8rem; color: #8b949e; margin-top: 3px; }
.pulse { width: 10px; height: 10px; border-radius: 50%; background: #2ea043; animation: pulse 2s infinite; flex-shrink: 0; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(46,160,67,.6)} 70%{box-shadow:0 0 0 8px rgba(46,160,67,0)} 100%{box-shadow:0 0 0 0 rgba(46,160,67,0)} }
.tabs { display: flex; gap: 4px; padding: 16px 32px 0; background: #161b22; border-bottom: 1px solid #30363d; }
.tab-btn { background: none; border: none; border-bottom: 3px solid transparent; color: #8b949e; font-family: inherit; font-size: .85rem; padding: 8px 20px 10px; cursor: pointer; transition: color .15s, border-color .15s; }
.tab-btn:hover { color: #e6edf3; }
.tab-btn.active { color: #e6edf3; border-bottom-color: #58a6ff; }
.content { padding: 24px 32px; max-width: 1400px; margin: 0 auto; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.section-title { font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; color: #8b949e; padding-bottom: 8px; border-bottom: 1px solid #21262d; margin-bottom: 12px; }
.kpi-strip { display: flex; gap: 16px; flex-wrap: wrap; }
.kpi-card { flex: 1; min-width: 150px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px 18px; }
.kpi-region { font-size: .7rem; text-transform: uppercase; letter-spacing: .07em; color: #8b949e; margin-bottom: 6px; }
.kpi-count { font-size: 1.9rem; font-weight: 700; line-height: 1; margin-bottom: 3px; }
.kpi-label { font-size: .7rem; color: #8b949e; margin-bottom: 8px; }
.kpi-ci { font-size: .8rem; font-weight: 600; }
.alert-box { background: #1f1215; border: 1px solid #f85149; border-radius: 6px; padding: 12px 18px; margin-top: 14px; }
.alert-title { color: #f85149; font-weight: 700; font-size: .85rem; margin-bottom: 6px; }
.alert-box ul { list-style: none; display: flex; flex-direction: column; gap: 4px; }
.alert-box li { font-size: .82rem; }
.alert-ok { background: #0f1f13; border: 1px solid #2ea043; border-radius: 6px; padding: 10px 18px; color: #2ea043; font-size: .82rem; font-weight: 600; margin-top: 14px; }
.row { display: flex; gap: 20px; }
.col-main { flex: 2; min-width: 0; }
.col-side { flex: 1; min-width: 260px; }
.panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
.footer { font-size: .7rem; color: #484f58; text-align: right; padding: 16px 0 8px; }
"""

TAB_JS = """
function showTab(id) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  document.getElementById('btn-' + id).classList.add('active');
}
"""


# ── Full HTML render ──────────────────────────────────────────────────────────

def render_html(
    em_counts:    dict[str, int],
    em_ci:        dict[str, float],
    em_alerts:    list[str],
    em_positions: dict[str, list[dict]],
    me_counts:    dict[str, int],
    me_ci:        dict[str, float],
    me_alerts:    list[str],
    me_positions: dict[str, list[dict]],
    history:      list[dict],
    generated_at: str,
) -> str:
    em_tab = build_tab_html(
        "em", em_counts, em_ci, em_alerts, em_positions, history,
        REGIONS_EM, lat_range=(-40, 60), lon_range=(-130, 145),
    )
    me_tab = build_tab_html(
        "me", me_counts, me_ci, me_alerts, me_positions, history,
        REGIONS_ME, lat_range=(15, 48), lon_range=(22, 65),
    )

    total_em = sum(em_counts.values())
    total_me = sum(me_counts.values())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Macro Aviation Pulse</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>{CSS}</style>
</head>
<body>

<div class="header">
  <div class="pulse"></div>
  <div>
    <h1>✈ Macro Aviation Pulse</h1>
    <div class="sub">Real-time air traffic density · economic activity proxy · {generated_at} UTC</div>
  </div>
</div>

<div class="tabs">
  <button id="btn-em" class="tab-btn active" onclick="showTab('em')">
    🌎 EM Regions &nbsp;<span style="color:#484f58;font-size:.75rem;">{total_em:,} aircraft</span>
  </button>
  <button id="btn-me" class="tab-btn" onclick="showTab('me')">
    🕌 Middle East Hubs &nbsp;<span style="color:#484f58;font-size:.75rem;">{total_me:,} aircraft</span>
  </button>
</div>

<div class="content">
  {em_tab}
  {me_tab}

  <div class="footer">
    Data: OpenSky Network REST API &nbsp;·&nbsp;
    Bounding boxes: approximations of national/regional airspaces &nbsp;·&nbsp;
    Updated: {generated_at} UTC &nbsp;·&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_aviation_pulse.py"
       style="color:#58a6ff;">Source</a>
  </div>
</div>

<script>{TAB_JS}</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"Macro Aviation Pulse — {generated_at} UTC")

    history = load_history()
    print(f"  Loaded {len(history)} historical rows")

    counts:    dict[str, int]        = {}
    positions: dict[str, list[dict]] = {}

    for i, region in enumerate(ALL_REGIONS):
        print(f"  Fetching {region}…")
        cnt, pos = get_count_and_positions(region)
        counts[region]    = cnt
        positions[region] = pos
        print(f"    → {cnt} aircraft, {len(pos)} with position fix")
        if i < len(ALL_REGIONS) - 1:
            time.sleep(3)

    new_row = {"ts": int(time.time()), "counts": counts}
    history = append_and_save_history(history, new_row)
    print(f"  History now has {len(history)} rows")

    em_counts    = {r: counts[r]    for r in REGIONS_EM}
    em_positions = {r: positions[r] for r in REGIONS_EM}
    em_ci        = {r: compute_ci(r, counts[r], history) for r in REGIONS_EM}
    em_alerts    = [r for r, ci in em_ci.items() if ci < ALERT_CI_THRESHOLD]

    me_counts    = {r: counts[r]    for r in REGIONS_ME}
    me_positions = {r: positions[r] for r in REGIONS_ME}
    me_ci        = {r: compute_ci(r, counts[r], history) for r in REGIONS_ME}
    me_alerts    = [r for r, ci in me_ci.items() if ci < ALERT_CI_THRESHOLD]

    print("\n  EM Congestion Index:")
    for r, ci in em_ci.items():
        print(f"    {r}: {ci:.3f}" + (" ⚠" if r in em_alerts else ""))
    print("\n  Middle East Congestion Index:")
    for r, ci in me_ci.items():
        print(f"    {r}: {ci:.3f}" + (" ⚠" if r in me_alerts else ""))

    html = render_html(
        em_counts, em_ci, em_alerts, em_positions,
        me_counts, me_ci, me_alerts, me_positions,
        history, generated_at,
    )
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\n  Written → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
