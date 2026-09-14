"""
Overlay chart — notable components, current 24m vs analog 24m windows.
Rates/FX shown as levels (unit-stable across eras); index/dollar series shown as YoY % change
(raw index/dollar levels aren't comparable across 1966/1977/1988/2026 due to rebasing & nominal growth).
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).parent))
from regime_classifier import load_fredmd

# var -> ("level" | "yoy", display label)
MODE = {
    "EXSZUSx":  ("level", "CHF/USD (level)"),
    "GS10":     ("level", "10yr Treasury Yield (%)"),
    "CPIAPPSL": ("yoy",   "CPI Apparel (YoY %)"),
    "CPIMEDSL": ("yoy",   "CPI Medical Care (YoY %)"),
    "REALLN":   ("yoy",   "Real Estate Loans (YoY %)"),
    "NONBORRES":("yoy",   "Nonborrowed Reserves (YoY %)"),
}
NOTABLE = list(MODE.keys())

REF_DATE = pd.Timestamp("2026-02-01")
ANALOG_ENDS = {
    "1977-10 (76-77 cluster)": pd.Timestamp("1977-10-01"),
    "1966-05": pd.Timestamp("1966-05-01"),
    "1988-07": pd.Timestamp("1988-07-01"),
}


def window(s: pd.Series, end: pd.Timestamp, months: int = 24) -> pd.Series:
    idx = s.index[s.index.get_indexer([end], method="nearest")[0]]
    pos = s.index.get_loc(idx)
    start_pos = max(0, pos - months + 1)
    return s.iloc[start_pos:pos + 1]


def main():
    print("Loading FRED-MD...")
    df, transforms = load_fredmd()

    series = {}
    for var, (mode, _) in MODE.items():
        if var not in df.columns:
            continue
        series[var] = df[var] if mode == "level" else df[var].pct_change(12) * 100

    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=[MODE[v][1] for v in NOTABLE],
        specs=[[{"secondary_y": True}, {"secondary_y": True}],
               [{"secondary_y": True}, {"secondary_y": True}],
               [{"secondary_y": True}, {"secondary_y": True}]],
        vertical_spacing=0.10, horizontal_spacing=0.09,
    )

    colors = ["royalblue", "seagreen", "firebrick"]

    for i, var in enumerate(NOTABLE):
        r, c = i // 2 + 1, i % 2 + 1
        mode, _ = MODE[var]
        if var not in series:
            continue
        s = series[var]

        cur = window(s, REF_DATE)
        x_rel = list(range(-len(cur) + 1, 1))
        fig.add_trace(go.Scatter(
            x=x_rel, y=cur.values, mode="lines",
            line=dict(color="black", width=2.5),
            name="Current (24m to 2026-02)", legendgroup="current",
            showlegend=(i == 0),
            hovertemplate="m%{x}<br>%{y:.2f}<extra></extra>",
        ), row=r, col=c, secondary_y=False)

        use_secondary = (mode == "level")
        for j, (label, end) in enumerate(ANALOG_ENDS.items()):
            w = window(s, end)
            x_rel_a = list(range(-len(w) + 1, 1))
            fig.add_trace(go.Scatter(
                x=x_rel_a, y=w.values, mode="lines",
                line=dict(color=colors[j], width=1.5, dash="dash"),
                name=label, legendgroup=label,
                showlegend=(i == 0),
                hovertemplate="m%{x}<br>%{y:.2f}<extra></extra>",
            ), row=r, col=c, secondary_y=use_secondary)

        if use_secondary:
            fig.update_yaxes(title_text="Current", row=r, col=c, secondary_y=False,
                              showgrid=True, color="black")
            fig.update_yaxes(title_text="Analogs", row=r, col=c, secondary_y=True,
                              showgrid=False, color="gray")
        else:
            fig.update_yaxes(title_text="%", row=r, col=c, secondary_y=False, showgrid=True)

    fig.update_layout(
        title=dict(
            text="Notable Components — Current 24m vs Analog 24m Windows<br>"
                 "<sub>Rates/FX = level (left axis, dashed analogs on right axis, different scale) · "
                 "Index/dollar series = YoY % change (single shared axis)</sub>",
            font_size=15,
        ),
        template="plotly_white",
        height=900,
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
    )

    out = Path(__file__).parent / "regime_notable_overlay_mixed_2026-02.html"
    fig.write_html(str(out))
    print(f"Chart: {out}")


if __name__ == "__main__":
    main()
