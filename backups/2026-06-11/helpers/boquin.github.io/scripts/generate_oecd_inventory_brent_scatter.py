"""
generate_oecd_inventory_brent_scatter.py — OECD Crude Inventories vs Brent Price
Replicates the FT/Capital Economics scatter "Continued oil inventory drawdowns
would pressure prices higher" using EIA STEO data only:
  - x: OECD commercial crude oil + other liquids inventories (mn barrels)
  - y: Monthly average Brent crude oil price ($/bbl)
Highlights 2022 and the most recent months ("Since Iran conflict") against
the full since-2010 scatter.

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_oecd_inventory_brent_scatter.py
Output: reports/oecd-inventory-brent/index.html
"""

import os
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import date

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE = "https://api.eia.gov/v2/steo/data/"
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT    = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR   = os.path.join(REPO_ROOT, "reports", "oecd-inventory-brent")
OUTPUT_PATH  = os.path.join(OUTPUT_DIR, "index.html")

INVENTORY_SERIES = "PASC_OECD_T3"   # OECD commercial crude + other liquids inventory, mn bbl
BRENT_SERIES     = "BREPUUS"        # Brent crude oil spot price, $/bbl

START_YEAR = 2010

# Months highlighted as "Since Iran conflict" (red) — the 2026 price-spike window
IRAN_START = pd.Timestamp("2026-02-01")

COLORS = {
    "Other since 2010":   "#cfc7bb",
    "2022":               "#1f77b4",
    "Since Iran conflict": "#a8325e",
}
ORDER = ["Other since 2010", "2022", "Since Iran conflict"]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def get_api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        print("WARNING: EIA_API_KEY not set. Using DEMO_KEY (heavily rate-limited).")
        return "DEMO_KEY"
    return key


def fetch_steo_series(api_key: str, series_id: str) -> pd.Series:
    resp = requests.get(EIA_API_BASE, params={
        "api_key": api_key,
        "frequency": "monthly",
        "data[0]": "value",
        "facets[seriesId][]": series_id,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }, timeout=30)
    resp.raise_for_status()
    rows = resp.json()["response"]["data"]
    s = pd.Series(
        {pd.to_datetime(r["period"]): float(r["value"]) for r in rows if r.get("value") not in (None, "")}
    ).sort_index()
    s = s[~s.index.duplicated()]
    return s


def categorize(d: pd.Timestamp) -> str:
    if d >= IRAN_START:
        return "Since Iran conflict"
    if d.year == 2022:
        return "2022"
    return "Other since 2010"


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def build_figure(df: pd.DataFrame) -> tuple[go.Figure, str]:
    fig = go.Figure()
    for cat in ORDER:
        sub = df[df["cat"] == cat]
        fig.add_trace(go.Scatter(
            x=sub["inventory"], y=sub["brent"],
            mode="markers",
            name=cat,
            marker=dict(size=10, color=COLORS[cat], line=dict(width=0)),
            hovertemplate="%{text}<br>Inventory: %{x:,.0f} mn bbl<br>Brent: $%{y:.1f}<extra></extra>",
            text=[d.strftime("%b %Y") for d in sub.index],
        ))

    # OLS fit: brent ~ inventory
    slope, intercept = np.polyfit(df["inventory"], df["brent"], 1)
    fitted = slope * df["inventory"] + intercept
    ss_res = ((df["brent"] - fitted) ** 2).sum()
    ss_tot = ((df["brent"] - df["brent"].mean()) ** 2).sum()
    r_squared = 1 - ss_res / ss_tot

    x_line = np.array([df["inventory"].min(), df["inventory"].max()])
    y_line = slope * x_line + intercept
    fig.add_trace(go.Scatter(
        x=x_line, y=y_line,
        mode="lines",
        name=f"OLS fit: y = {intercept:,.1f} + ({slope:.4f})·x, R² = {r_squared:.2f}",
        line=dict(color="#444444", width=2, dash="dash"),
        hoverinfo="skip",
    ))

    # Rule of thumb + sanity check vs. the highlighted drawdown episode
    per_100mn = -100 * slope
    iran_pts = df[df["cat"] == "Since Iran conflict"]
    start, end = iran_pts.iloc[0], iran_pts.iloc[-1]
    inv_draw = start["inventory"] - end["inventory"]
    actual_move = end["brent"] - start["brent"]
    implied_move = (inv_draw / 100) * per_100mn
    footnote = (
        f"<b>Rule of thumb:</b> every 100 mn barrel draw in OECD commercial crude inventories &asymp; "
        f"+${per_100mn:.1f}/bbl on Brent (and symmetrically, a 100 mn barrel build &asymp; -${per_100mn:.1f}/bbl).<br>"
        f"<b>Sanity check:</b> inventories fell from {start['inventory']:,.0f} mn bbl "
        f"({start.name.strftime('%b %Y')}) to {end['inventory']:,.0f} mn bbl ({end.name.strftime('%b %Y')}) "
        f"&mdash; a {inv_draw:,.0f} mn barrel draw &mdash; which the regression would put at roughly "
        f"+${implied_move:.0f}/bbl, while Brent actually moved from ${start['brent']:.0f} to ${end['brent']:.0f}, "
        f"a ${actual_move:.0f}/bbl jump. The actual move ran hotter than the historical relationship alone "
        f"would predict &mdash; consistent with a geopolitical risk premium layered on top of the inventory effect."
    )

    for d, row in iran_pts.iterrows():
        fig.add_annotation(
            x=row["inventory"], y=row["brent"],
            text=d.strftime("%b %Y"), showarrow=False,
            font=dict(size=11, color=COLORS["Since Iran conflict"]),
            xanchor="left", xshift=10, yshift=6,
        )

    fig.update_layout(
        title="Continued oil inventory drawdowns would pressure prices higher"
              "<br><sup>Monthly average Brent crude vs. OECD commercial crude oil "
              f"inventories, since {START_YEAR}</sup>",
        xaxis_title="OECD commercial crude oil inventories (mn barrels)",
        yaxis_title="Monthly average Brent crude oil price ($ per barrel)",
        template="plotly_white",
        legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="right", x=0.99,
                    bgcolor="rgba(250,246,241,0.7)"),
        width=1000, height=750,
        plot_bgcolor="#faf6f1", paper_bgcolor="#faf6f1",
        margin=dict(t=80),
    )
    return fig, footnote


def write_page(fig: go.Figure, footnote: str, latest_label: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    chart_html = fig.to_html(include_plotlyjs="cdn", full_html=False)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OECD Crude Inventories vs. Brent Price | boquin.xyz</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         margin:0;padding:1.5rem;background:#faf6f1;color:#222;
         display:flex;flex-direction:column;align-items:center}}
    header{{max-width:1000px;width:100%;margin-bottom:1rem}}
    header h1{{font-size:1.3rem;font-weight:bold;margin:0}}
    header p{{color:#555;font-size:.85rem;margin-top:.4rem}}
    .chart-wrapper{{width:100%;max-width:1040px;background:#fff;
                   border:1px solid #ddd;border-radius:4px;padding:1rem}}
    .footnote{{width:100%;max-width:1040px;font-size:.8rem;color:#555;
              line-height:1.5;margin-top:.75rem;padding:0 .25rem}}
    footer{{margin-top:1.5rem;font-size:.8rem;color:#888;text-align:center}}
    footer a{{color:#2196F3;text-decoration:none}}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F6E2;&#xFE0F; OECD Commercial Crude Inventories vs. Brent Price</h1>
    <p>Monthly since {START_YEAR} &mdash; latest point: {latest_label}</p>
  </header>
  <div class="chart-wrapper">
    {chart_html}
  </div>
  <p class="footnote">{footnote}</p>
  <footer>
    Source: <a href="https://www.eia.gov/outlooks/steo/" target="_blank">EIA Short-Term Energy Outlook</a>
    (series {INVENTORY_SERIES}, {BRENT_SERIES})
    &nbsp;&bull;&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_oecd_inventory_brent_scatter.py" target="_blank">Source Code</a>
    &nbsp;&bull;&nbsp;
    <a href="https://boquin.xyz" target="_blank">boquin.xyz</a>
  </footer>
</body>
</html>"""
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {OUTPUT_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    api_key = get_api_key()

    print("Fetching EIA STEO series...")
    inventory = fetch_steo_series(api_key, INVENTORY_SERIES)
    brent     = fetch_steo_series(api_key, BRENT_SERIES)

    df = pd.concat([inventory.rename("inventory"), brent.rename("brent")], axis=1, join="inner")
    df = df[df.index >= f"{START_YEAR}-01-01"]
    last_complete_month = (pd.Timestamp.today().to_period("M") - 1).to_timestamp()
    df = df[df.index <= last_complete_month]
    df["cat"] = df.index.map(categorize)
    print(f"  {len(df)} months, {df.index.min().date()} - {df.index.max().date()}")

    fig, footnote = build_figure(df)
    latest = df.index.max()
    latest_label = f"{latest.strftime('%b %Y')} (inventory {df['inventory'].iloc[-1]:,.0f} mn bbl, Brent ${df['brent'].iloc[-1]:.1f})"
    write_page(fig, footnote, latest_label)


if __name__ == "__main__":
    main()
