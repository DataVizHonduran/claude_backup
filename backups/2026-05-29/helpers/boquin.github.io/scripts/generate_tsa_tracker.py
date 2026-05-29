"""
TSA Checkpoint Throughput Tracker
Scrapes TSA year pages via Playwright (bypasses Akamai).
Data is embedded as an HTML table — no Excel needed.
Chart: 2026 YTD blue line | 2021-2025 min/max grey band | 2025 dotted reference
"""

import json
import pathlib
import re
import sys
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "reports" / "tsa-tracker"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
CACHE_FILE = OUTPUT_DIR / "historical.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.tsa.gov/travel/passenger-volumes"
HIST_YEARS = [2021, 2022, 2023, 2024, 2025]
CURR_YEAR = 2026

FR24_URL = "https://www.flightradar24.com/data/statistics"
FR24_HIST_YEARS = [2022, 2023, 2024, 2025]

MONTH_TICKS = {
    1: "Jan 1", 32: "Feb 1", 60: "Mar 1", 91: "Apr 1",
    121: "May 1", 152: "Jun 1", 182: "Jul 1", 213: "Aug 1",
    244: "Sep 1", 274: "Oct 1", 305: "Nov 1", 335: "Dec 1",
}


def scrape_year(page, year: int) -> list[dict]:
    url = BASE_URL if year == CURR_YEAR else f"{BASE_URL}/{year}"
    print(f"  Fetching {year} from {url}...")
    page.goto(url, wait_until="networkidle", timeout=60000)
    rows = page.locator("table tr").all()
    records = []
    for row in rows[1:]:  # skip header row
        cells = row.locator("td").all()
        if len(cells) < 2:
            continue
        date_str = cells[0].inner_text().strip()
        num_str = cells[1].inner_text().strip().replace(",", "").replace(" ", "")
        try:
            dt = pd.to_datetime(date_str)
            travelers = int(num_str)
            if travelers <= 0:
                continue
            records.append({
                "date": dt.strftime("%Y-%m-%d"),
                "day_of_year": dt.timetuple().tm_yday,
                "year": year,
                "travelers": travelers,
            })
        except (ValueError, TypeError):
            continue
    print(f"    -> {len(records)} records")
    return records


def load_all_data() -> pd.DataFrame:
    records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Always fetch current year
        curr_records = scrape_year(page, CURR_YEAR)

        # Fetch historical years — use cache if available
        if CACHE_FILE.exists():
            print("Loading historical data from cache...")
            hist_records = json.loads(CACHE_FILE.read_text())
        else:
            print("No cache — fetching historical years...")
            hist_records = []
            for y in HIST_YEARS:
                hist_records.extend(scrape_year(page, y))
            CACHE_FILE.write_text(json.dumps(hist_records))
            print(f"Cached {len(hist_records)} historical records")

        browser.close()
        records = hist_records + curr_records

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["year", "day_of_year"]).reset_index(drop=True)
    return df


def build_chart(df: pd.DataFrame) -> go.Figure:
    hist = (
        df[df["year"].isin(HIST_YEARS)]
        .groupby("day_of_year")["travelers"]
        .agg(low="min", high="max")
        .reset_index()
        .sort_values("day_of_year")
    )
    yr2025 = df[df["year"] == 2025].sort_values("day_of_year")
    curr = df[df["year"] == CURR_YEAR].sort_values("day_of_year")

    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_data = curr["date"].max().strftime("%b %-d, %Y") if not curr.empty else "N/A"

    fig = go.Figure()

    # Grey band — 2021–2025 min/max
    fig.add_trace(go.Scatter(
        x=hist["day_of_year"],
        y=hist["high"],
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=hist["day_of_year"],
        y=hist["low"],
        mode="lines",
        line=dict(width=0),
        fill="tonexty",
        fillcolor="rgba(160,160,160,0.25)",
        name="2021–2025 Range",
        hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2021–2025 Range</extra>",
    ))

    # 2025 dotted reference line
    if not yr2025.empty:
        fig.add_trace(go.Scatter(
            x=yr2025["day_of_year"],
            y=yr2025["travelers"],
            mode="lines",
            line=dict(color="rgba(110,110,110,0.55)", width=1.2, dash="dot"),
            name="2025",
            hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2025</extra>",
        ))

    # 2026 YTD line
    if not curr.empty:
        fig.add_trace(go.Scatter(
            x=curr["day_of_year"],
            y=curr["travelers"],
            mode="lines",
            line=dict(color="#2563EB", width=2.5),
            name="2026 YTD",
            hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2026</extra>",
        ))

    fig.update_layout(
        title=dict(
            text="TSA Checkpoint Throughput",
            font=dict(size=22, color="#111"),
            x=0.5,
        ),
        annotations=[dict(
            text=f"2026 YTD (blue) vs. 2021–2025 min/max range (grey) | Latest: {last_data} | Updated: {last_updated}",
            xref="paper", yref="paper",
            x=0.5, y=1.055,
            showarrow=False,
            font=dict(size=12, color="#555"),
            xanchor="center",
        )],
        xaxis=dict(
            title="",
            tickvals=list(MONTH_TICKS.keys()),
            ticktext=list(MONTH_TICKS.values()),
            range=[1, 366],
            showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            title="Daily Travelers",
            tickformat=",",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
        ),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.06,
            xanchor="right",
            x=1,
            font=dict(size=12),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(t=110, b=50, l=90, r=20),
        height=560,
    )
    return fig


def scrape_fr24() -> pd.DataFrame:
    print("Fetching FlightRadar24 statistics...")
    html = requests.get(
        FR24_URL,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        timeout=30,
    ).text
    m = re.search(r"var charts = ({.*?});</script>", html, re.DOTALL)
    raw = json.loads(m.group(1))
    rows = []
    for chart_key in ("general", "commercial"):
        for s in raw[chart_key]["series"]:
            if "7-day" in s["name"]:
                continue
            year = int(s["name"].split()[0])
            for ts, val in s["data"]:
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                rows.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "day_of_year": dt.timetuple().tm_yday,
                    "year": year,
                    "flights": val,
                    "type": chart_key,
                })
    df = pd.DataFrame(rows)
    print(f"  -> {len(df)} FR24 records | years: {sorted(df['year'].unique())}")
    return df


def build_fr24_chart(df: pd.DataFrame, flight_type: str, title: str) -> go.Figure:
    sub = df[df["type"] == flight_type].copy()
    hist = (
        sub[sub["year"].isin(FR24_HIST_YEARS)]
        .groupby("day_of_year")["flights"]
        .agg(low="min", high="max")
        .reset_index()
        .sort_values("day_of_year")
    )
    yr2025 = sub[sub["year"] == 2025].sort_values("day_of_year")
    curr = sub[sub["year"] == CURR_YEAR].sort_values("day_of_year")

    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_data = curr["date"].max() if not curr.empty else "N/A"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist["day_of_year"], y=hist["high"],
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=hist["day_of_year"], y=hist["low"],
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(160,160,160,0.25)", name="2022–2025 Range",
        hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2022–2025 Range</extra>",
    ))
    if not yr2025.empty:
        fig.add_trace(go.Scatter(
            x=yr2025["day_of_year"], y=yr2025["flights"],
            mode="lines", line=dict(color="rgba(110,110,110,0.55)", width=1.2, dash="dot"),
            name="2025",
            hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2025</extra>",
        ))
    if not curr.empty:
        fig.add_trace(go.Scatter(
            x=curr["day_of_year"], y=curr["flights"],
            mode="lines", line=dict(color="#2563EB", width=2.5),
            name="2026 YTD",
            hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2026</extra>",
        ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=22, color="#111"), x=0.5),
        annotations=[dict(
            text=f"2026 YTD (blue) vs. 2022–2025 min/max range (grey) | Latest: {last_data} | Updated: {last_updated}",
            xref="paper", yref="paper", x=0.5, y=1.055, showarrow=False,
            font=dict(size=12, color="#555"), xanchor="center",
        )],
        xaxis=dict(
            tickvals=list(MONTH_TICKS.keys()), ticktext=list(MONTH_TICKS.values()),
            range=[1, 366], showgrid=True, gridcolor="rgba(200,200,200,0.4)",
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            title="Daily Flights", tickformat=",",
            showgrid=True, gridcolor="rgba(200,200,200,0.4)",
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.06, xanchor="right", x=1, font=dict(size=12)),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=110, b=50, l=90, r=20), height=520,
    )
    return fig


def main():
    print("Loading TSA data...")
    df = load_all_data()
    print(f"Total records: {len(df)} | Years: {sorted(df['year'].unique())}")

    print("Building TSA chart...")
    fig_tsa = build_chart(df)

    fr24_df = scrape_fr24()
    print("Building FR24 charts...")
    fig_general = build_fr24_chart(fr24_df, "general", "Total Daily Flights (Flightradar24)")
    fig_commercial = build_fr24_chart(fr24_df, "commercial", "Commercial Daily Flights (Flightradar24)")

    cfg = {"displayModeBar": True, "responsive": True}
    div_tsa = fig_tsa.to_html(include_plotlyjs=False, full_html=False, config=cfg)
    div_general = fig_general.to_html(include_plotlyjs=False, full_html=False, config=cfg)
    div_commercial = fig_commercial.to_html(include_plotlyjs=False, full_html=False, config=cfg)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TSA &amp; Flight Tracker</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f8f9fa; margin: 0; padding: 0; }}
    .tab-bar {{ display: flex; gap: 8px; margin-bottom: 16px; padding: 16px 16px 0; }}
    .tab-btn {{
      padding: 8px 22px; border: none; border-radius: 6px; cursor: pointer;
      background: #e2e8f0; font-size: 14px; font-weight: 600; color: #4a5568;
    }}
    .tab-btn.active {{ background: #2563EB; color: #fff; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    #tsa {{ padding: 0 16px; }}
    #fr24 .plotly-graph-div {{ width: 100% !important; }}
    .fr24-footnote {{ font-size: 12px; color: #6b7280; padding: 4px 16px 12px; }}
  </style>
</head>
<body>
  <div class="tab-bar">
    <button class="tab-btn active" onclick="showTab('tsa', this)">TSA Throughput</button>
    <button class="tab-btn" onclick="showTab('fr24', this)">FlightRadar24</button>
  </div>
  <div id="tsa" class="tab-panel active">{div_tsa}</div>
  <div id="fr24" class="tab-panel">
    {div_general}
    <p class="fr24-footnote"><strong>Total flights:</strong> Commercial flights above + rest of business jet flights + private flights + gliders + most helicopter flights + most ambulance flights + government flights + some military flights + drones</p>
    {div_commercial}
    <p class="fr24-footnote"><strong>Commercial flights:</strong> Commercial passenger flights + cargo flights + charter flights + some business jet flights</p>
  </div>
  <script>
    function showTab(id, btn) {{
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.getElementById(id).classList.add('active');
      btn.classList.add('active');
    }}
  </script>
</body>
</html>"""

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Written: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
