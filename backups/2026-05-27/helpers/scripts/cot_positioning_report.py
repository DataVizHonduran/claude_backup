"""
CFTC COT Positioning Snapshot
Produces an HTML report grouped by asset class with:
  Current | 1W Ago | 4W Ago | 52W High | 52W Low  (all as % of OI)
And a commentary section flagging extremes / aggressive positioning shifts.
"""

import sys
import warnings
import datetime
import pandas as pd
from pathlib import Path

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))
warnings.filterwarnings("ignore")

from cot_analysis import main as fetch_cot


# ── Thresholds for commentary ─────────────────────────────────────────────────
# Extreme: current is in top/bottom 5% of the 52W range AND range > 10pp AND |current| > 3%
EXTREME_RANK_CUTOFF = 0.05   # top/bottom 5% of 52W range
EXTREME_MIN_RANGE   = 10.0   # 52W range must be > this (pp) to be considered meaningful
EXTREME_MIN_ABS     = 3.0    # |current position| must exceed this (pp)
WOW_THRESHOLD_PP    = 5.0    # 1-week move (pct pts of OI) considered aggressive
MONTH_THRESHOLD_PP  = 15.0   # 4-week move threshold (only fires if WoW not already flagged)


def build_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """
    From a tidy COT DataFrame, compute the 5-column positioning snapshot:
    Current, 1W Ago, 4W Ago, 52W High, 52W Low — all as Position_Pct_OI.
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])

    latest = df["Date"].max()
    target_1w  = latest - pd.Timedelta(weeks=1)
    target_4w  = latest - pd.Timedelta(weeks=4)
    cutoff_52w = latest - pd.Timedelta(weeks=52)

    def nearest_date(target: pd.Timestamp, available: pd.Series) -> pd.Timestamp:
        return available.iloc[(available - target).abs().argsort()[:1]].values[0]

    group_cols = ["Sector", "Market", "Category"]
    rows = []

    for key, grp in df.groupby(group_cols):
        sector, market, category = key
        grp = grp.sort_values("Date")
        dates = grp["Date"]
        pcts  = grp.set_index("Date")["Position_Pct_OI"]

        current_val = float(pcts.loc[latest]) if latest in pcts.index else float("nan")

        d_1w = nearest_date(target_1w, dates)
        val_1w = float(pcts.loc[d_1w]) if d_1w in pcts.index else float("nan")

        d_4w = nearest_date(target_4w, dates)
        val_4w = float(pcts.loc[d_4w]) if d_4w in pcts.index else float("nan")

        hist = pcts[pcts.index >= cutoff_52w]
        hi_52 = float(hist.max()) if not hist.empty else float("nan")
        lo_52 = float(hist.min()) if not hist.empty else float("nan")

        rows.append({
            "Sector":   sector,
            "Market":   market,
            "Category": category,
            "Current":  current_val,
            "1W Ago":   val_1w,
            "4W Ago":   val_4w,
            "52W High": hi_52,
            "52W Low":  lo_52,
            "WoW Δ":    current_val - val_1w,
            "4W Δ":     current_val - val_4w,
            "As_of":    latest,
        })

    snap = pd.DataFrame(rows)
    snap.sort_values(["Sector", "Market", "Category"], inplace=True)
    snap.reset_index(drop=True, inplace=True)
    return snap


def generate_commentary(snap: pd.DataFrame) -> list[str]:
    """
    Flag notable positioning conditions:
    - 52W extreme: current in top/bottom 5% of 52W range (range > EXTREME_MIN_RANGE, |cur| > EXTREME_MIN_ABS)
    - Aggressive WoW: |WoW Δ| >= WOW_THRESHOLD_PP and |current| > EXTREME_MIN_ABS
    - Aggressive 4W: |4W Δ| >= MONTH_THRESHOLD_PP (only when WoW not already flagged)
    Returns sorted list of HTML commentary strings.
    """
    snap = snap.copy()
    snap["_range"]    = snap["52W High"] - snap["52W Low"]
    snap["_pct_rank"] = (snap["Current"] - snap["52W Low"]) / snap["_range"].replace(0, float("nan"))

    notes = []
    wow_flagged = set()

    for _, row in snap.iterrows():
        cur   = row["Current"]
        hi    = row["52W High"]
        lo    = row["52W Low"]
        wow   = row["WoW Δ"]
        m4    = row["4W Δ"]
        rank  = row["_pct_rank"]
        rng   = row["_range"]
        label = f"{row['Market']} — {row['Category']}"

        # 52W extreme
        if (not pd.isna(rank) and not pd.isna(rng)
                and rng > EXTREME_MIN_RANGE and abs(cur) > EXTREME_MIN_ABS):
            if rank >= (1 - EXTREME_RANK_CUTOFF):
                notes.append(
                    f"<b>{label}</b>: 52W <span class='bull'>LONG EXTREME</span> — "
                    f"current {cur:+.1f}% (52W range {lo:+.1f}% → {hi:+.1f}%)"
                )
            elif rank <= EXTREME_RANK_CUTOFF:
                notes.append(
                    f"<b>{label}</b>: 52W <span class='bear'>SHORT EXTREME</span> — "
                    f"current {cur:+.1f}% (52W range {lo:+.1f}% → {hi:+.1f}%)"
                )

        # Aggressive WoW
        if not pd.isna(wow) and abs(wow) >= WOW_THRESHOLD_PP and abs(cur) > EXTREME_MIN_ABS:
            direction = "bought" if wow > 0 else "sold"
            notes.append(
                f"<b>{label}</b>: aggressive 1W shift "
                f"<span class='{'bull' if wow > 0 else 'bear'}'>{wow:+.1f}pp</span> — "
                f"net {direction} aggressively (now {cur:+.1f}%)"
            )
            wow_flagged.add(label)

        # Sustained 4W (only if WoW not already flagged)
        if (label not in wow_flagged and not pd.isna(m4)
                and abs(m4) >= MONTH_THRESHOLD_PP and abs(cur) > EXTREME_MIN_ABS):
            direction = "accumulated longs" if m4 > 0 else "built shorts"
            notes.append(
                f"<b>{label}</b>: sustained 4W repositioning "
                f"<span class='{'bull' if m4 > 0 else 'bear'}'>{m4:+.1f}pp</span> — "
                f"steadily {direction} (now {cur:+.1f}%)"
            )

    notes.sort()
    return notes if notes else ["No notable extremes or aggressive shifts detected this week."]


def _fmt(val: float, highlight: bool = False, bear: bool = False) -> str:
    if pd.isna(val):
        return "<td>—</td>"
    cls = ""
    if highlight:
        cls = " class='bear'" if bear else " class='bull'"
    color_class = "neg" if val < 0 else "pos"
    return f"<td{cls}><span class='{color_class}'>{val:+.1f}%</span></td>"


def render_html(snap: pd.DataFrame, commentary: list[str], as_of: str) -> str:
    css = """
    <style>
      body { font-family: 'Segoe UI', Arial, sans-serif; background: #0f1117; color: #e0e0e0;
             margin: 0; padding: 20px; }
      h1   { color: #ffffff; font-size: 1.4rem; border-bottom: 1px solid #333; padding-bottom: 8px; }
      h2   { color: #aac4e8; font-size: 1.05rem; margin: 24px 0 6px; text-transform: uppercase;
             letter-spacing: .08em; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 24px; font-size: .85rem; }
      th   { background: #1a1d27; color: #8899aa; text-align: right; padding: 6px 10px;
             border-bottom: 1px solid #2a2d3a; font-weight: 500; }
      th:first-child, th:nth-child(2) { text-align: left; }
      td   { padding: 5px 10px; text-align: right; border-bottom: 1px solid #1e2130; }
      td:first-child { text-align: left; color: #c8d6e5; font-weight: 500; }
      td:nth-child(2) { text-align: left; color: #8899aa; font-size: .8rem; }
      tr:hover td { background: #1c2030; }
      .pos { color: #4caf82; }
      .neg { color: #e05c5c; }
      .bull { color: #4caf82; font-weight: 600; }
      .bear { color: #e05c5c; font-weight: 600; }
      .commentary { background: #1a1d27; border-left: 3px solid #3a5f8a; padding: 12px 16px;
                    border-radius: 4px; margin-bottom: 24px; }
      .commentary p { margin: 5px 0; font-size: .88rem; line-height: 1.6; }
      .meta { color: #556; font-size: .78rem; margin-bottom: 20px; }
      .delta-pos { color: #4caf82; }
      .delta-neg { color: #e05c5c; }
    </style>
    """

    commentary_html = "<div class='commentary'>" + \
        "".join(f"<p>• {n}</p>" for n in commentary) + \
        "</div>"

    sector_blocks = []
    for sector, sdf in snap.groupby("Sector", sort=True):
        rows_html = ""
        for market, mdf in sdf.groupby("Market"):
            for i, (_, row) in enumerate(mdf.iterrows()):
                mkt_cell  = f"<td rowspan='{len(mdf)}'>{market}</td>" if i == 0 else ""
                cat       = row["Category"]
                cur, w1, w4 = row["Current"], row["1W Ago"], row["4W Ago"]
                hi, lo    = row["52W High"], row["52W Low"]
                wow, m4   = row["WoW Δ"], row["4W Δ"]

                rng     = hi - lo if not (pd.isna(hi) or pd.isna(lo)) else 0
                rank    = (cur - lo) / rng if rng > EXTREME_MIN_RANGE else float("nan")
                near_hi = not pd.isna(rank) and rank >= (1 - EXTREME_RANK_CUTOFF) and abs(cur) > EXTREME_MIN_ABS
                near_lo = not pd.isna(rank) and rank <= EXTREME_RANK_CUTOFF and abs(cur) > EXTREME_MIN_ABS

                def delta_cell(val):
                    if pd.isna(val):
                        return "<td>—</td>"
                    cls = "delta-pos" if val > 0 else "delta-neg"
                    return f"<td><span class='{cls}'>{val:+.1f}pp</span></td>"

                rows_html += (
                    f"<tr>{mkt_cell}"
                    f"<td>{cat}</td>"
                    + _fmt(cur, highlight=near_hi or near_lo, bear=near_lo)
                    + _fmt(w1)
                    + delta_cell(wow)
                    + _fmt(w4)
                    + delta_cell(m4)
                    + _fmt(hi)
                    + _fmt(lo)
                    + "</tr>"
                )

        sector_blocks.append(f"""
        <h2>{sector}</h2>
        <table>
          <thead>
            <tr>
              <th>Market</th><th>Category</th>
              <th>Current</th><th>1W Ago</th><th>WoW Δ</th>
              <th>4W Ago</th><th>4W Δ</th>
              <th>52W High</th><th>52W Low</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>COT Positioning Snapshot</title>{css}</head>
<body>
  <h1>CFTC COT Positioning Snapshot</h1>
  <div class='meta'>As of {as_of} &nbsp;|&nbsp; Position % of Open Interest &nbsp;|&nbsp;
    <span class='bull'>Green</span> = net long &nbsp;
    <span class='bear'>Red</span> = net short &nbsp;|&nbsp;
    Highlighted cells = near 52W extreme
  </div>
  <h2>Commentary</h2>
  {commentary_html}
  {''.join(sector_blocks)}
</body>
</html>"""


def run(sectors=None, lookback_years=2, output_dir=None):
    today = datetime.date.today()
    start_year = today.year - lookback_years
    end_year   = today.year

    print(f"Fetching COT data {start_year}–{end_year}…", flush=True)
    df = fetch_cot(sectors=sectors, start_year=start_year, end_year=end_year)

    print("Building snapshot…", flush=True)
    snap = build_snapshot(df)

    as_of = snap["As_of"].max().strftime("%Y-%m-%d")
    commentary = generate_commentary(snap)

    html = render_html(snap, commentary, as_of)

    out_dir = Path(output_dir) if output_dir else Path(__file__).parents[1] / "reports" / "cot-positioning"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"\n✓ Report saved → {out_path}")
    print(f"  As-of date : {as_of}")
    print(f"  Markets    : {snap['Market'].nunique()}")
    print(f"  Commentary : {len(commentary)} note(s)")
    return str(out_path)


if __name__ == "__main__":
    run()
