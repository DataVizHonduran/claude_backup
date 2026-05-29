"""
Strait of Hormuz Daily Ship Transit Tracker
Source: IMF PortWatch (ArcGIS Feature Service, chokepoint6)
No auth required — public API
"""

import requests
import pandas as pd
import plotly.graph_objects as go
import os
from datetime import datetime, date
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
ARCGIS_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest"
    "/services/Daily_Chokepoints_Data/FeatureServer/0/query"
)
PORTID = "chokepoint6"
CURRENT_YEAR = 2026
# Historical band: dynamically detect complete years (≥300 days) excluding current year
# PortWatch chokepoint6 has gaps — auto-detection ensures correct band regardless of API coverage
OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "hormuz-tracker"
OUTPUT_FILE = OUTPUT_DIR / "index.html"


# ── Fetch ────────────────────────────────────────────────────────────────────
def fetch_all_data() -> pd.DataFrame:
    """Paginate through ArcGIS Feature Service (max 2000 rows per call)."""
    records = []
    offset = 0
    page_size = 2000

    while True:
        params = {
            "where": f"portid = '{PORTID}'",
            "outFields": "date,n_total",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "orderByFields": "date ASC",
        }
        resp = requests.get(ARCGIS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            break

        for feat in features:
            attrs = feat["attributes"]
            records.append({
                "epoch_ms": attrs["date"],
                "n_total": attrs["n_total"],
            })

        if not data.get("exceededTransferLimit", False):
            break
        offset += page_size
        print(f"  fetched {offset} rows so far…")

    print(f"Total records fetched: {len(records)}")
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["epoch_ms"], utc=True, errors="coerce").dt.normalize().dt.tz_localize(None)
    df["year"] = df["date"].dt.year
    df["doy"] = df["date"].dt.dayofyear
    df = df.dropna(subset=["n_total"]).sort_values("date").reset_index(drop=True)
    return df


# ── Compute bands ────────────────────────────────────────────────────────────
def get_hist_years(df: pd.DataFrame) -> list:
    """Return complete years (>=300 days of data) that are not the current year."""
    counts = df.groupby("year")["doy"].count()
    return sorted([y for y, n in counts.items() if n >= 300 and y != CURRENT_YEAR])


def compute_hist_band(df: pd.DataFrame) -> pd.DataFrame:
    hist_years = get_hist_years(df)
    print(f"Historical band years: {hist_years}")
    hist = df[df["year"].isin(hist_years)].copy()
    band = (
        hist.groupby("doy")["n_total"]
        .agg(hist_min="min", hist_max="max", hist_median="median")
        .reset_index()
    )
    return band


def get_current_year(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["year"] == CURRENT_YEAR][["date", "doy", "n_total"]].copy()


# ── Build figure ─────────────────────────────────────────────────────────────
def build_figure(band: pd.DataFrame, curr: pd.DataFrame, hist_years: list | None = None) -> go.Figure:
    hist_label = f"{min(hist_years)}–{max(hist_years)}" if hist_years else "Historical"

    # Use 2026 as reference year for x-axis dates
    ref_year = CURRENT_YEAR
    band["ref_date"] = pd.to_datetime(
        band["doy"].apply(lambda d: f"{ref_year}-{d:03d}"), format="%Y-%j"
    )

    last_date = curr["date"].max()
    last_val = curr.loc[curr["date"] == last_date, "n_total"].values[0]
    last_doy = last_date.timetuple().tm_yday

    fig = go.Figure()

    # Grey band: min/max envelope
    fig.add_trace(go.Scatter(
        x=band["ref_date"],
        y=band["hist_max"],
        mode="lines",
        line=dict(width=0),
        name=f"{hist_label} Max",
        showlegend=False,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=band["ref_date"],
        y=band["hist_min"],
        mode="lines",
        fill="tonexty",
        fillcolor="rgba(180,180,180,0.35)",
        line=dict(width=0),
        name=f"{hist_label} Min/Max Range",
        hovertemplate="DOY %{x|%b %d}<br>Range: %{y:.0f}–" +
                       "%{customdata:.0f} vessels<extra>Hist. range</extra>",
        customdata=band["hist_max"],
    ))

    # Dashed median
    fig.add_trace(go.Scatter(
        x=band["ref_date"],
        y=band["hist_median"],
        mode="lines",
        line=dict(color="rgba(120,120,120,0.7)", width=1.5, dash="dash"),
        name=f"{hist_label} Median",
        hovertemplate="DOY %{x|%b %d}<br>Median: %{y:.0f} vessels<extra>Hist. median</extra>",
    ))

    # 2026 line
    fig.add_trace(go.Scatter(
        x=curr["date"],
        y=curr["n_total"],
        mode="lines",
        line=dict(color="#1f77b4", width=2.5),
        name=f"{CURRENT_YEAR} YTD",
        hovertemplate="%{x|%b %d, %Y}<br><b>%{y:.0f} vessels</b><extra>2026</extra>",
    ))

    # Annotation: last data point
    fig.add_annotation(
        x=last_date,
        y=last_val,
        text=f"  {int(last_val)} ({last_date.strftime('%b %d')})",
        showarrow=False,
        xanchor="left",
        font=dict(size=11, color="#1f77b4"),
    )

    updated = datetime.utcnow().strftime("%Y-%m-%d")
    fig.update_layout(
        title=dict(
            text=(
                f"Strait of Hormuz — Daily Ship Transits ({CURRENT_YEAR} vs. {hist_label} Range)<br>"
                f"<sup>Source: IMF PortWatch (chokepoint6) &nbsp;|&nbsp; Updated: {updated} UTC</sup>"
            ),
            font=dict(size=16),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title="",
            tickformat="%b",
            dtick="M1",
            range=[
                f"{CURRENT_YEAR}-01-01",
                f"{CURRENT_YEAR}-12-31",
            ],
            gridcolor="rgba(200,200,200,0.4)",
        ),
        yaxis=dict(
            title="Number of vessels",
            gridcolor="rgba(200,200,200,0.4)",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=60, r=40, t=100, b=60),
        height=520,
    )
    return fig


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching Hormuz transit data from IMF PortWatch…")
    df = fetch_all_data()
    print(f"Date range: {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"Years present: {sorted(df['year'].unique().tolist())}")

    hist_years = get_hist_years(df)
    band = compute_hist_band(df)
    curr = get_current_year(df)
    print(f"{CURRENT_YEAR} records: {len(curr)} days (through {curr['date'].max().date()})")

    fig = build_figure(band, curr, hist_years=hist_years)
    fig.write_html(
        OUTPUT_FILE,
        full_html=True,
        include_plotlyjs="cdn",
        config={"displayModeBar": False},
    )
    print(f"Saved → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
