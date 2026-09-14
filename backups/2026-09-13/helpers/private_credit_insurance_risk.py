#!/usr/bin/env python3
"""
private_credit_insurance_risk.py
Private Credit – Life Insurance Systemic Risk Monitor

Tracks four risk transmission channels:
  1. ALM Mismatch / Liquidity Illusion  (HY/IG spreads)
  2. Mark-to-Myth Valuation Opacity     (BDC basket + quarterly table)
  3. Bermuda Triangle Regulatory Arb    (PE vs reinsurer equity)
  4. Bank Interconnectedness Loop       (C&I loans + G-SIB equity)

Usage: python3 private_credit_insurance_risk.py [--out PATH]

Data sources:
  FRED: BAMLH0A0HYM2, BAMLC0A0CM, BUSLOANS, USREC
  yfinance: BDC basket, PE managers, insurers, Bermuda reinsurers, G-SIBs
  Hard-coded (update quarterly): Proskauer + Lincoln International data
"""
import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf
from dotenv import load_dotenv
from plotly.subplots import make_subplots

load_dotenv(dotenv_path="/Users/macproajb/claude_projects/fred_client/.env")

TODAY      = date.today().isoformat()
OUT_DEFAULT = f"/Users/macproajb/claude_projects/private_credit_insurance_risk_{TODAY}.html"

PALETTE = {
    "blue":   "#0057A8",
    "orange": "#E8630A",
    "green":  "#00875A",
    "red":    "#C8102E",
    "purple": "#7B2D8B",
    "teal":   "#00A8A8",
    "amber":  "#C0A000",
    "grey":   "#6B7280",
    "navy":   "#1a3a5c",
}
BG    = "#f7f9fc"
PAPER = "#ffffff"
GRID  = "#dde1ea"
TEXT  = "#1a1d27"

# Equity baskets
BDC_TICKERS  = ["ARCC", "OBDC", "FSK", "BXSL", "PSEC"]    # public BDCs = live PC proxy
PE_TICKERS   = ["APO", "ARES", "KKR", "OWL"]               # PE-insurer asset managers
INS_TICKERS  = ["PRU", "LNC", "MET", "EQH"]                # traditional cedant insurers
BDA_TICKERS  = ["RNR", "EG", "ACGL"]                       # Bermuda reinsurers (EG = Everest Group)
GSIB_TICKERS = ["JPM", "BAC", "C", "GS", "MS"]             # G-SIBs

# ── Quarterly hard-coded distress data ─────────────────────────────────────────
# Sources: Proskauer Private Credit Default Index; Lincoln International PMI
# UPDATE EACH QUARTER with new Proskauer + Lincoln releases
PC_DEFAULT_RATE = 2.73   # Proskauer Q1-2026
BAD_PIK_PCT     = 6.4    # Lincoln International 2025 year-end

DISTRESS_TABLE = {
    "Distress Metric": [
        "Headline Default Rate (Proskauer Index)",
        "Loans Utilizing PIK Interest (Lincoln)",
        '"Bad PIK" Shadow Default Rate (Lincoln)',
        "LTV of Bad-PIK Borrowers at Stress (Lincoln)",
        "Direct Lender Foreclosures (Annual)",
    ],
    "2021 Baseline": ["< 1.50%", "7.0%", "2.5%", "39.4% (inception LTV)", "~$4.5B/yr"],
    "2024 Midpoint": ["~1.80%", "9.0%", "4.5%", "~55.0%", "~$9.0B"],
    "Q1-2026 (Latest)": ["2.73%", "11.0%", "6.4%", "76.1%", "$24.1B (2025 FY)"],
    "Insurer Implication": [
        "Incremental recognized impairments + RBC capital charges",
        "Cash-flow starvation; recognition of defaults delayed",
        "Shadow defaults avoiding downgrade via PIK capitalization",
        "Severe recovery erosion on liquidation; LTV > 70% = near-total loss",
        "Equity control seizures → punitive NAIC equity RBC charges",
    ],
}


# ── Data helpers ───────────────────────────────────────────────────────────────

_FRED_BASE = "https://api.stlouisfed.org/fred"
_FRED_KEY  = os.environ.get("FRED_API_KEY", "")


def fetch_fred(series_id: str, start: str, freq: str = "D") -> pd.Series:
    """Fetch FRED series with plain requests (bypasses requests_cache)."""
    params = {
        "series_id": series_id,
        "observation_start": start,
        "api_key": _FRED_KEY,
        "file_type": "json",
    }
    resp = requests.get(f"{_FRED_BASE}/series/observations", params=params, timeout=30)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    df = pd.DataFrame(obs).set_index("date")[["value"]]
    df.index = pd.to_datetime(df.index, errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna().resample(freq).last()
    return df["value"].rename(series_id)


def fetch_equity(tickers: list, period: str = "2y") -> dict:
    out = {}
    for t in tickers:
        try:
            df = yf.Ticker(t).history(period=period, interval="1d", auto_adjust=True)
            if not df.empty:
                s = df["Close"].copy()
                s.index = s.index.tz_localize(None)
                out[t] = s.dropna()
        except Exception as e:
            print(f"  Warning: could not fetch {t}: {e}")
    return out


def normalize_to_100(series_dict: dict) -> dict:
    out = {}
    for t, s in series_dict.items():
        s = s.dropna()
        if not s.empty:
            out[t] = s / s.iloc[0] * 100
    return out


def pct_of_52w_high(s: pd.Series) -> float:
    s = s.dropna()
    if s.empty:
        return float("nan")
    cutoff = s.index[-1] - pd.Timedelta(weeks=52)
    window = s.loc[s.index >= cutoff]
    if window.empty:
        return float("nan")
    return float(s.iloc[-1] / window.max() * 100)


def current_drawdown_pct(s: pd.Series) -> float:
    """Current % drawdown from series peak (negative number)."""
    s = s.dropna()
    if s.empty:
        return float("nan")
    return float((s.iloc[-1] - s.max()) / s.max() * 100)


def yoy_latest(s: pd.Series) -> float:
    s = s.dropna().sort_index()
    if len(s) < 2:
        return float("nan")
    latest = s.iloc[-1]
    target = s.index[-1] - pd.DateOffset(weeks=52)
    try:
        prior = s.asof(target)
    except Exception:
        prior = s.iloc[0]
    if pd.isna(prior) or prior == 0:
        return float("nan")
    return float((latest - prior) / abs(prior) * 100)


def traffic_light(val: float, warn: float, danger: float, higher_is_bad: bool = True) -> str:
    if pd.isna(val):
        return PALETTE["grey"]
    v = val if higher_is_bad else -val
    w = warn if higher_is_bad else -warn
    d = danger if higher_is_bad else -danger
    if v >= d:
        return PALETTE["red"]
    if v >= w:
        return PALETTE["amber"]
    return PALETTE["green"]


def add_recession_bands(fig, usrec: pd.Series, row: int):
    """Shade NBER recession periods in a subplot using x-data / y-domain coords."""
    in_rec, start = False, None
    for dt, val in usrec.items():
        if val == 1 and not in_rec:
            in_rec, start = True, dt
        elif val == 0 and in_rec:
            in_rec = False
            fig.add_shape(type="rect", yref="y domain",
                          x0=str(start.date()), x1=str(dt.date()), y0=0, y1=1,
                          fillcolor="rgba(150,150,150,0.18)", line_width=0, row=row, col=1)
    if in_rec and start is not None:
        fig.add_shape(type="rect", yref="y domain",
                      x0=str(start.date()), x1=str(usrec.index[-1].date()), y0=0, y1=1,
                      fillcolor="rgba(150,150,150,0.18)", line_width=0, row=row, col=1)


def add_hline_sub(fig, y_val: float, row: int, color: str, dash: str = "dot",
                  width: float = 1.2, label: str = "", label_x: float = 0.99):
    """Horizontal reference line scoped to a specific subplot row."""
    # xref="x domain" → 0-1 spans the subplot's x width; yref omitted → auto from row/col
    fig.add_shape(type="line", xref="x domain", x0=0, x1=1,
                  y0=y_val, y1=y_val,
                  line=dict(color=color, dash=dash, width=width), row=row, col=1)
    if label:
        # yref="y domain" means 0-1 relative to subplot height; use y as fraction
        # Instead, annotate in data coords with auto-resolved axis from row/col
        fig.add_annotation(x=1, y=y_val, text=label, showarrow=False,
                           xref="x domain", xanchor="right", yanchor="bottom",
                           font=dict(size=9, color=color), row=row, col=1)


# ── Main build ─────────────────────────────────────────────────────────────────

def build(out_path: str):
    start_5y = (date.today() - timedelta(days=365 * 5)).isoformat()
    start_3y = (date.today() - timedelta(days=365 * 3)).isoformat()

    print("Fetching FRED data …")
    hy    = fetch_fred("BAMLH0A0HYM2", start_5y, freq="D")
    ig    = fetch_fred("BAMLC0A0CM",   start_5y, freq="D")
    bl    = fetch_fred("BUSLOANS",     start_3y, freq="W")
    usrec = fetch_fred("USREC",        start_5y, freq="MS")

    print("Fetching equity data …")
    bdc_raw  = fetch_equity(BDC_TICKERS,  "2y")
    pe_raw   = fetch_equity(PE_TICKERS,   "2y")
    ins_raw  = fetch_equity(INS_TICKERS,  "2y")
    bda_raw  = fetch_equity(BDA_TICKERS,  "2y")
    gsib_raw = fetch_equity(GSIB_TICKERS, "3y")

    # ── KPI values ──
    hy_latest  = float(hy.iloc[-1])  if not hy.empty  else float("nan")
    bdc_52w    = float(np.nanmedian([pct_of_52w_high(s) for s in bdc_raw.values()]))
    pe_dd      = float(np.nanmean([abs(current_drawdown_pct(s)) for s in pe_raw.values()]))
    ci_yoy     = yoy_latest(bl)

    # ── KPI colors ──
    col_hy  = traffic_light(hy_latest,  400, 600)
    col_pcd = traffic_light(PC_DEFAULT_RATE, 2.0, 3.5)
    col_pik = traffic_light(BAD_PIK_PCT,     3.0, 6.0)
    col_bdc = traffic_light(bdc_52w,    90,  80, higher_is_bad=False)
    col_pe  = traffic_light(pe_dd,      10,  20)
    col_ci  = traffic_light(ci_yoy,     5,   0, higher_is_bad=False)

    # ── Subplot layout ─────────────────────────────────────────────────────────
    specs = [
        [{"type": "indicator"}] * 6,                                          # Row 1: KPI tiles
        [{"type": "xy", "colspan": 6}] + [None] * 5,                         # Row 2: HY/IG spreads
        [{"type": "xy", "colspan": 6}] + [None] * 5,                         # Row 3: BDC basket
        [{"type": "table", "colspan": 6}] + [None] * 5,                      # Row 4: Mark-to-Myth table
        [{"type": "xy", "colspan": 6}] + [None] * 5,                         # Row 5: PE vs Insurer
        [{"type": "xy", "colspan": 6}] + [None] * 5,                         # Row 6: Bermuda
        [{"type": "xy", "colspan": 6}] + [None] * 5,                         # Row 7: Bank
    ]

    fig = make_subplots(
        rows=7, cols=6,
        specs=specs,
        row_heights=[0.09, 0.14, 0.14, 0.13, 0.15, 0.15, 0.15],
        vertical_spacing=0.04,
        subplot_titles=(
            "", "", "", "", "", "",
            "① Credit Stress — US High Yield & Investment Grade OAS (basis points, 5-year)",
            "② BDC Basket — Live Private Credit NAV Proxy (normalized, base = 100 at 2-year start)",
            '③ "Mark-to-Myth" Distress Tracker (update quarterly from Proskauer + Lincoln International)',
            "④ PE Asset Manager vs. Traditional Life Insurer Equity (normalized, base = 100)",
            "⑤ Bermuda Triangle — Offshore Reinsurer vs. PE-Insurer Parent Equity",
            "⑥ Bank Interconnectedness — C&I Loan Index vs. G-SIB Equity Index (normalized, base = 100)",
        ),
    )

    # ── Row 1: KPI indicator tiles ─────────────────────────────────────────────
    kpis = [
        (hy_latest,        "US HY OAS (bps)",           ".0f", col_hy,  "bps"),
        (PC_DEFAULT_RATE,  "PC Default Rate %",          ".2f", col_pcd, "%"),
        (BAD_PIK_PCT,      '"Bad PIK" Shadow Default %', ".1f", col_pik, "%"),
        (bdc_52w,          "BDC Median vs 52w High",     ".1f", col_bdc, "%"),
        (pe_dd,            "PE-Insurer Drawdown",        ".1f", col_pe,  "%"),
        (ci_yoy,           "C&I Loan Growth YoY",        ".1f", col_ci,  "%"),
    ]
    for col_i, (val, title, fmt, color, unit) in enumerate(kpis, start=1):
        fig.add_trace(go.Indicator(
            mode="number",
            value=val,
            number={"valueformat": fmt, "suffix": f" {unit}",
                    "font": {"size": 30, "color": color}},
            title={"text": f"<b>{title}</b>", "font": {"size": 10.5, "color": TEXT}},
        ), row=1, col=col_i)

    # ── Row 2: HY + IG spreads with recession bands ────────────────────────────
    add_recession_bands(fig, usrec, row=2)
    fig.add_trace(go.Scatter(x=hy.index, y=hy.values, name="US HY OAS",
                             line=dict(color=PALETTE["red"], width=1.8)), row=2, col=1)
    fig.add_trace(go.Scatter(x=ig.index, y=ig.values, name="US IG OAS",
                             line=dict(color=PALETTE["blue"], width=1.8)), row=2, col=1)
    add_hline_sub(fig, 400, row=2, color=PALETTE["amber"], label="HY stress (400 bps)")
    add_hline_sub(fig, 600, row=2, color=PALETTE["red"],   label="HY crisis (600 bps)")
    fig.update_yaxes(title_text="OAS (bps)", row=2, col=1)

    # ── Row 3: BDC normalized basket ──────────────────────────────────────────
    bdc_norm = normalize_to_100(bdc_raw)
    bdc_palette = [PALETTE["blue"], PALETTE["orange"], PALETTE["green"],
                   PALETTE["red"], PALETTE["purple"]]
    for i, (t, s) in enumerate(bdc_norm.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=t,
                                 line=dict(color=bdc_palette[i % 5], width=1.5),
                                 opacity=0.75), row=3, col=1)
    if bdc_norm:
        bdc_df  = pd.DataFrame(bdc_norm).dropna(how="all")
        bdc_avg = bdc_df.mean(axis=1)
        fig.add_trace(go.Scatter(x=bdc_avg.index, y=bdc_avg.values, name="BDC Average",
                                 line=dict(color=TEXT, width=2.5, dash="dash")), row=3, col=1)
    add_hline_sub(fig, 90,  row=3, color=PALETTE["amber"], label="Stress zone (< 90)")
    add_hline_sub(fig, 100, row=3, color=GRID, dash="solid", width=0.8)
    fig.update_yaxes(title_text="Index (base=100)", row=3, col=1)

    # ── Row 4: Mark-to-Myth distress table ────────────────────────────────────
    col_keys = list(DISTRESS_TABLE.keys())
    fig.add_trace(go.Table(
        header=dict(
            values=[f"<b>{k}</b>" for k in col_keys],
            fill_color=PALETTE["navy"],
            font=dict(color="white", size=11),
            align="left",
            height=32,
        ),
        cells=dict(
            values=[DISTRESS_TABLE[k] for k in col_keys],
            fill_color=[
                ["#eef2f8"] * len(DISTRESS_TABLE["Distress Metric"]),
                ["#f5f7fb"] * len(DISTRESS_TABLE["2021 Baseline"]),
                ["#fffaed"] * len(DISTRESS_TABLE["2024 Midpoint"]),
                ["#fff0f0"] * len(DISTRESS_TABLE["Q1-2026 (Latest)"]),
                ["#f5f7fb"] * len(DISTRESS_TABLE["Insurer Implication"]),
            ],
            font=dict(color=TEXT, size=10.5),
            align="left",
            height=27,
        ),
    ), row=4, col=1)

    # ── Row 5: PE managers vs. traditional insurers ───────────────────────────
    pe_norm  = normalize_to_100(pe_raw)
    ins_norm = normalize_to_100(ins_raw)
    pe_colors  = [PALETTE["blue"], PALETTE["teal"], PALETTE["purple"], PALETTE["navy"]]
    ins_colors = [PALETTE["orange"], PALETTE["red"], "#8B2500", PALETTE["amber"]]

    for i, (t, s) in enumerate(pe_norm.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=f"PE: {t}",
                                 line=dict(color=pe_colors[i % 4], width=2.0)), row=5, col=1)
    for i, (t, s) in enumerate(ins_norm.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=f"Ins: {t}",
                                 line=dict(color=ins_colors[i % 4], width=1.8, dash="dot")), row=5, col=1)
    add_hline_sub(fig, 100, row=5, color=GRID, dash="solid", width=0.8)
    fig.update_yaxes(title_text="Index (base=100)", row=5, col=1)

    # ── Row 6: Bermuda reinsurers vs. APO (PE-insurer parent) ─────────────────
    bda_norm = normalize_to_100(bda_raw)
    bda_colors = [PALETTE["blue"], PALETTE["green"], PALETTE["teal"]]

    for i, (t, s) in enumerate(bda_norm.items()):
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=f"Reins: {t}",
                                 line=dict(color=bda_colors[i % 3], width=2.0)), row=6, col=1)
    if "APO" in pe_raw:
        apo = normalize_to_100({"APO": pe_raw["APO"]})["APO"]
        fig.add_trace(go.Scatter(x=apo.index, y=apo.values, name="PE-Ins: APO",
                                 line=dict(color=PALETTE["red"], width=2.2, dash="dot")), row=6, col=1)
    add_hline_sub(fig, 100, row=6, color=GRID, dash="solid", width=0.8)
    fig.update_yaxes(title_text="Index (base=100)", row=6, col=1)

    # ── Row 7: C&I loans + G-SIB equity (both normalized) ────────────────────
    bl_norm = (bl / bl.dropna().iloc[0] * 100).dropna()

    gsib_norm = normalize_to_100(gsib_raw)
    if gsib_norm:
        gsib_df    = pd.DataFrame(gsib_norm).dropna(how="all")
        gsib_index = gsib_df.mean(axis=1)
    else:
        gsib_index = pd.Series(dtype=float)

    fig.add_trace(go.Scatter(x=bl_norm.index, y=bl_norm.values,
                             name="C&I Loans (level, base=100)",
                             line=dict(color=PALETTE["blue"], width=2.0)), row=7, col=1)
    if not gsib_index.empty:
        fig.add_trace(go.Scatter(x=gsib_index.index, y=gsib_index.values,
                                 name="G-SIB Equity Index (avg, base=100)",
                                 line=dict(color=PALETTE["orange"], width=2.0, dash="dot")), row=7, col=1)
    add_hline_sub(fig, 100, row=7, color=GRID, dash="solid", width=0.8)
    fig.update_yaxes(title_text="Index (base=100)", row=7, col=1)

    # ── Global layout ──────────────────────────────────────────────────────────
    footnote = (
        "Sources: FRED (St. Louis Fed) — BAMLH0A0HYM2, BAMLC0A0CM, BUSLOANS, USREC &nbsp;|&nbsp; "
        "yfinance — BDC basket (ARCC/OBDC/FSK/BXSL/PSEC), PE managers (APO/ARES/KKR/OWL), "
        "Insurers (PRU/LNC/MET/EQH), Bermuda reinsurers (RNR/EG/ACGL), G-SIBs (JPM/BAC/C/GS/MS) &nbsp;|&nbsp; "
        "Hard-coded (quarterly): Proskauer Private Credit Default Index, Lincoln International PMI"
    )

    fig.update_layout(
        title=dict(
            text=(
                "<b>Private Credit – Life Insurance Systemic Risk Monitor</b><br>"
                f"<span style='font-size:12px;color:{PALETTE['grey']}'>"
                "Four risk channels: ALM Mismatch · Mark-to-Myth · Bermuda Triangle · Bank Interconnectedness"
                f" &nbsp;·&nbsp; Updated {TODAY}</span>"
            ),
            font=dict(size=20, color=TEXT),
            x=0.012, xanchor="left", y=0.99,
        ),
        paper_bgcolor=PAPER,
        plot_bgcolor=BG,
        font=dict(family="Inter, Arial, sans-serif", color=TEXT, size=11),
        legend=dict(
            orientation="h", yanchor="top", y=-0.022, xanchor="left", x=0,
            bgcolor="rgba(255,255,255,0.9)", bordercolor=GRID, borderwidth=1,
            font=dict(size=10),
        ),
        height=2200,
        margin=dict(l=60, r=60, t=110, b=120),
        annotations=[
            # panel subtitle annotations are handled by subplot_titles
            # add footnote
            dict(
                text=footnote,
                xref="paper", yref="paper", x=0, y=-0.055,
                xanchor="left", yanchor="top",
                font=dict(size=9, color=PALETTE["grey"]),
                showarrow=False,
            ),
        ],
    )

    # Style all xy axes
    for row_i in range(2, 8):
        fig.update_xaxes(showgrid=True, gridcolor=GRID, gridwidth=0.5,
                         zeroline=False, showline=True, linecolor=GRID, row=row_i, col=1)
        fig.update_yaxes(showgrid=True, gridcolor=GRID, gridwidth=0.5,
                         zeroline=False, showline=True, linecolor=GRID, row=row_i, col=1)

    fig.write_html(out_path, include_plotlyjs="cdn")
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Private Credit – Life Insurance Risk Monitor")
    parser.add_argument("--out", default=OUT_DEFAULT, help="Output HTML path")
    args = parser.parse_args()
    build(args.out)
