#!/usr/bin/env python3
"""
bank_credit/extractor.py
Fetches FDIC call-report credit quality data + FRED aggregate series,
renders a 3-panel Plotly HTML dashboard, and prints a JSON summary to stdout.

Usage:  python3 extractor.py [TICKER ...]
        python3 extractor.py JPM BAC WFC
        (default: all 8 banks)
"""
import sys, json, os, datetime
import requests
import pandas as pd
import plotly.graph_objects as go
sys.path.insert(0, "/Users/macproajb/claude_projects")
from fred_client import FredClient

# ── Bank registry ──────────────────────────────────────────────────────────────
BANKS = {
    "JPM": (628,   "JPMorgan Chase"),
    "BAC": (3510,  "Bank of America"),
    "WFC": (3511,  "Wells Fargo"),
    "C":   (7213,  "Citibank"),
    "COF": (4297,  "Capital One"),
    "USB": (6548,  "U.S. Bank"),
    "PNC": (6384,  "PNC Bank"),
    "TFC": (9846,  "Truist Bank"),
}
DEFAULTS = ["JPM", "BAC", "WFC", "C", "COF", "USB", "PNC", "TFC"]

FDIC_FIELDS = "REPDTE,NTLNLSR,NCLNLSR,P3ASSET,P9ASSET,NAASSET,LNLSNET"
FDIC_BASE   = "https://banks.data.fdic.gov/api"

FRED_SERIES = {
    "DRCLACBS":          ("Consumer Delinq.", "delinquency"),
    "DRCCLACBS":         ("Credit Card Delinq.", "delinquency"),
    "DRBLACBS":          ("Business Delinq.", "delinquency"),
    "QBPLNTLNNTCGOFFR":  ("Total NCO Rate", "chargeoff"),
    "CORCCACBS":         ("CC NCO Rate", "chargeoff"),
    "CORCACBS":          ("Consumer NCO Rate", "chargeoff"),
}

OUT_DIR  = "/Users/macproajb/claude_projects"
DARK_BG  = "#f4f6f9"
DARK_PAPER = "#ffffff"
GRID_CLR  = "#d0d4db"
TEXT_CLR  = "#1a1d27"

PALETTE = ["#1a6bb5","#2e8b3e","#c47a00","#b53030","#7b3fa0","#0e8a72","#c0580a","#b5006e"]


# ── FDIC fetch ─────────────────────────────────────────────────────────────────
def fetch_bank(cert: int, n: int = 40) -> list[dict]:
    url = (
        f"{FDIC_BASE}/financials"
        f"?filters=CERT%3A{cert}"
        f"&fields={FDIC_FIELDS}"
        f"&limit={n}"
        f"&sort_by=REPDTE&sort_order=DESC"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    rows = []
    for item in r.json()["data"]:
        d = item["data"]
        lnls = d.get("LNLSNET") or 1  # guard /0
        d["PD30_PCT"] = round(d["P3ASSET"] / lnls * 100, 2) if d.get("P3ASSET") else None
        d["PD90_PCT"] = round(d["P9ASSET"] / lnls * 100, 2) if d.get("P9ASSET") else None
        d["NTLNLSR"]  = round(d["NTLNLSR"], 2) if d.get("NTLNLSR") is not None else None
        d["NCLNLSR"]  = round(d["NCLNLSR"], 2) if d.get("NCLNLSR") is not None else None
        # parse date → "Q1 2025" label
        dt = d["REPDTE"]   # "20251231"
        yr, mo = int(dt[:4]), int(dt[4:6])
        qnum = (mo - 1) // 3 + 1
        d["qlabel"] = f"Q{qnum} {yr}"
        rows.append(d)
    return rows


# ── FRED fetch ─────────────────────────────────────────────────────────────────
def fetch_fred() -> dict:
    client = FredClient()
    out = {}
    for sid, (label, group) in FRED_SERIES.items():
        try:
            df = client.get_series(sid, freq="QS", observation_start="2015-01-01")
            df = df.dropna()
            out[sid] = {
                "label": label,
                "group": group,
                "dates":  df.index.strftime("%Y-%m-%d").tolist(),
                "values": [round(v, 2) for v in df[sid].tolist()],
            }
        except Exception as e:
            print(f"  FRED {sid}: {e}", file=sys.stderr)
    return out


# ── Plotly helpers ─────────────────────────────────────────────────────────────
def _dark_layout(**kw) -> dict:
    base = dict(
        paper_bgcolor=DARK_PAPER,
        plot_bgcolor=DARK_BG,
        font=dict(color=TEXT_CLR, family="Inter, Arial, sans-serif", size=12),
        xaxis=dict(gridcolor=GRID_CLR, linecolor=GRID_CLR),
        yaxis=dict(gridcolor=GRID_CLR, linecolor=GRID_CLR),
        margin=dict(l=60, r=30, t=60, b=50),
    )
    base.update(kw)
    return base


def _cell_color(val, lo, hi) -> str:
    """Red if near high (stress), green if near low (healthy), grey for mid."""
    if val is None:
        return "#f4f6f9"
    span = hi - lo
    if span == 0:
        return "#f4f6f9"
    t = (val - lo) / span
    if t > 0.66:
        return "#fde0e0"
    if t < 0.33:
        return "#d6f0de"
    return "#f4f6f9"


# ── Panel A — comparison table ─────────────────────────────────────────────────
def _fmt_delta(val, prev) -> str:
    if val is None:
        return "–"
    if prev is None:
        return f"{val:.2f}"
    delta = val - prev
    sign = "+" if delta >= 0 else ""
    return f"{val:.2f} ({sign}{delta:.2f})"


def make_table_fig(bank_data: dict) -> go.Figure:
    METRIC_KEYS = [
        ("NCO Rate%",  "NTLNLSR"),
        ("NPL Rate%",  "NCLNLSR"),
        ("PD30 Rate%", "PD30_PCT"),
        ("PD90 Rate%", "PD90_PCT"),
    ]
    cols = {"Bank": [], "Quarter": []}
    raw  = {}   # raw numeric values for cell coloring
    for col, _ in METRIC_KEYS:
        cols[col] = []
        raw[col]  = []

    for ticker, info in bank_data.items():
        qs = info.get("quarters", [])
        if not qs:
            continue
        latest = qs[0]
        prev   = qs[1] if len(qs) > 1 else None
        cols["Bank"].append(info["name"])
        cols["Quarter"].append(latest.get("qlabel", "–"))
        for col, key in METRIC_KEYS:
            v = latest.get(key)
            p = prev.get(key) if prev else None
            cols[col].append(_fmt_delta(v, p))
            raw[col].append(v)

    metric_col_names = [c for c, _ in METRIC_KEYS]
    cell_fills = []
    for key in ["Bank", "Quarter"] + metric_col_names:
        if key in raw:
            vals  = raw[key]
            valid = [v for v in vals if v is not None]
            lo, hi = (min(valid), max(valid)) if valid else (0, 1)
            cell_fills.append([_cell_color(v, lo, hi) for v in vals])
        else:
            cell_fills.append(["#ffffff"] * len(cols["Bank"]))

    fig = go.Figure(go.Table(
        columnwidth=[160, 90, 140, 140, 140, 140],
        header=dict(
            values=["<b>Bank</b>", "<b>Quarter</b>", "<b>NCO Rate %</b>",
                    "<b>NPL Rate %</b>", "<b>PD 30-89d %</b>", "<b>PD 90+ d %</b>"],
            fill_color="#1a6bb5",
            font=dict(color="white", size=13),
            align="center",
            height=36,
        ),
        cells=dict(
            values=[cols[k] for k in ["Bank", "Quarter"] + metric_col_names],
            fill_color=cell_fills,
            font=dict(color=TEXT_CLR, size=12),
            align=["left", "center", "center", "center", "center", "center"],
            height=32,
        ),
    ))
    fig.update_layout(
        title=dict(text="Latest-Quarter Credit Quality Snapshot (QoQ Δ in parentheses)", font=dict(size=15), x=0.01),
        paper_bgcolor=DARK_PAPER,
        font=dict(color=TEXT_CLR),
        margin=dict(l=10, r=10, t=50, b=10),
        height=max(300, 50 + 36 * len(cols["Bank"])),
    )
    return fig


# ── Panel B — NCO rate trend ───────────────────────────────────────────────────
def make_nco_trend_fig(bank_data: dict) -> go.Figure:
    fig = go.Figure()
    for i, (ticker, info) in enumerate(bank_data.items()):
        qs = info.get("quarters", [])
        if not qs:
            continue
        qs_sorted = sorted(qs, key=lambda x: x["REPDTE"])
        x = [q["qlabel"] for q in qs_sorted]
        y = [q.get("NTLNLSR") for q in qs_sorted]
        if all(v is None for v in y):
            continue
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines+markers",
            name=info["name"],
            line=dict(color=PALETTE[i % len(PALETTE)], width=2),
            marker=dict(size=6),
            hovertemplate=f"<b>{info['name']}</b><br>%{{x}}<br>NCO Rate: %{{y:.2f}}%<extra></extra>",
        ))
    fig.update_layout(
        **_dark_layout(
            title=dict(text="Annualized Net Charge-Off Rate by Bank (10 Years)", font=dict(size=15), x=0.01),
            yaxis=dict(title="NCO Rate (%, annualized)", ticksuffix="%", gridcolor=GRID_CLR),
            xaxis=dict(title="Quarter"),
            legend=dict(bgcolor="#ffffff", bordercolor=GRID_CLR, borderwidth=1),
            hovermode="x unified",
            height=400,
        )
    )
    return fig


# ── Panel C — FRED aggregate ───────────────────────────────────────────────────
def make_fred_fig(fred_data: dict) -> go.Figure:
    delinq_clrs = ["#4a90d9","#5ba85c","#e8a838"]
    nco_clrs    = ["#d95b5b","#9b59b6"]
    d_i, n_i    = 0, 0

    fig = go.Figure()
    for sid, info in fred_data.items():
        if "error" in info or not info.get("dates"):
            continue
        color = delinq_clrs[d_i % 3] if info["group"] == "delinquency" else nco_clrs[n_i % 2]
        dash   = "solid" if info["group"] == "delinquency" else "dash"
        if info["group"] == "delinquency":
            d_i += 1
        else:
            n_i += 1
        fig.add_trace(go.Scatter(
            x=info["dates"], y=info["values"],
            mode="lines",
            name=info["label"],
            line=dict(color=color, width=2, dash=dash),
            hovertemplate=f"<b>{info['label']}</b><br>%{{x}}<br>%{{y:.2f}}%<extra></extra>",
        ))
    fig.update_layout(
        **_dark_layout(
            title=dict(text="Industry Aggregate: Delinquency & Charge-Off Rates (FRED, 10Y)", font=dict(size=15), x=0.01),
            yaxis=dict(title="Rate (%)", ticksuffix="%", gridcolor=GRID_CLR),
            xaxis=dict(title="Quarter"),
            legend=dict(bgcolor="#ffffff", bordercolor=GRID_CLR, borderwidth=1),
            hovermode="x unified",
            height=400,
        )
    )
    return fig


# ── HTML assembly ──────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>US Bank Credit Quality – {date}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {bg}; color: {txt}; font-family: Inter, Arial, sans-serif; padding: 24px; }}
  h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #555; font-size: 13px; margin-bottom: 24px; }}
  .panel {{ background: {paper}; border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
  .legend-note {{ font-size: 11px; color: #555; margin-top: 8px; }}
</style>
</head>
<body>
<h1>US Bank Credit Quality Dashboard</h1>
<div class="subtitle">FDIC Call Report Data + FRED Aggregates &nbsp;|&nbsp; {date}</div>

<div class="panel">{table_div}</div>
<div class="legend-note" style="margin:-12px 0 16px 8px">
  Cell shading: <span style="background:#d6f0de;padding:1px 6px;border-radius:3px;color:#1a1d27">green = lower stress</span>
  &nbsp;<span style="background:#fde0e0;padding:1px 6px;border-radius:3px;color:#1a1d27">red = higher stress</span>
  &nbsp;relative to peers shown.
</div>

<div class="panel">{nco_div}</div>
<div class="panel">{fred_div}</div>
</body>
</html>"""


def build_html(bank_data: dict, fred_data: dict, date_str: str) -> str:
    table_fig = make_table_fig(bank_data)
    nco_fig   = make_nco_trend_fig(bank_data)
    fred_fig  = make_fred_fig(fred_data)

    cfg = dict(responsive=True, displayModeBar=False)
    table_div = table_fig.to_html(full_html=False, include_plotlyjs=False, config=cfg)
    nco_div   = nco_fig.to_html(full_html=False, include_plotlyjs=False, config=cfg)
    fred_div  = fred_fig.to_html(full_html=False, include_plotlyjs=False, config=cfg)

    return HTML_TEMPLATE.format(
        date=date_str, bg=DARK_BG, paper=DARK_PAPER, txt=TEXT_CLR,
        table_div=table_div, nco_div=nco_div, fred_div=fred_div,
    )


# ── Summary JSON ───────────────────────────────────────────────────────────────
def build_summary(bank_data: dict) -> dict:
    rows = []
    for ticker, info in bank_data.items():
        qs = info.get("quarters", [])
        if len(qs) < 2:
            continue
        lat, prev = qs[0], qs[1]
        rows.append({
            "ticker": ticker,
            "name":   info["name"],
            "quarter": lat.get("qlabel"),
            "nco_rate": lat.get("NTLNLSR"),
            "npl_rate": lat.get("NCLNLSR"),
            "pd30_pct": lat.get("PD30_PCT"),
            "pd90_pct": lat.get("PD90_PCT"),
            "nco_qoq_delta": round(lat.get("NTLNLSR",0) - prev.get("NTLNLSR",0), 2)
                             if lat.get("NTLNLSR") is not None and prev.get("NTLNLSR") is not None else None,
        })
    return {"banks": rows}


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    tickers = [t.upper() for t in sys.argv[1:]] if sys.argv[1:] else DEFAULTS
    bad = [t for t in tickers if t not in BANKS]
    if bad:
        print(f"ERROR: Unknown tickers {bad}. Valid: {sorted(BANKS)}", file=sys.stderr)
        sys.exit(1)

    bank_data = {}
    for t in tickers:
        cert, name = BANKS[t]
        print(f"  Fetching FDIC: {name} (cert {cert})...", file=sys.stderr)
        try:
            rows = fetch_bank(cert)
            bank_data[t] = {"name": name, "quarters": rows}
            print(f"    → {len(rows)} quarters", file=sys.stderr)
        except Exception as e:
            print(f"    ERROR: {e}", file=sys.stderr)
            bank_data[t] = {"name": name, "quarters": [], "error": str(e)}

    print("  Fetching FRED aggregate series...", file=sys.stderr)
    fred_data = fetch_fred()

    date_str = datetime.date.today().strftime("%Y-%m-%d")
    out_path = os.path.join(OUT_DIR, f"bank_credit_quality_{date_str.replace('-','')}.html")

    print("  Building HTML dashboard...", file=sys.stderr)
    html = build_html(bank_data, fred_data, date_str)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved → {out_path}", file=sys.stderr)

    summary = build_summary(bank_data)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
