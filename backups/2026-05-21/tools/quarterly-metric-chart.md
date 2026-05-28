---
description: Bar chart of any fundamental metric (revenue, gross profit, net income, FCF, EBITDA, etc.) for N quarters — fetches from stockanalysis.com, renders Plotly HTML
---

Chart a single financial metric across N quarters for a given ticker.

# Key rules (token efficiency)
- **Never run yfinance_financials.py** — it dumps all statements and caps at 5Q.
- **Go straight to WebFetch** on stockanalysis.com. No yfinance, no EDGAR.
- **One ToolSearch call max** — `select:WebFetch` only if schema not yet loaded.
- **Use correct Plotly title syntax**: `title=dict(text=..., font=dict(...))` — never `titlefont`.

# Steps

1. **Parse from user message:**
   - `TICKER` — required
   - `METRIC` — e.g. "revenue", "gross profit", "net income", "EBITDA", "free cash flow", "operating income", "EPS"
   - `N` — number of quarters (default 20)

2. **Determine the right stockanalysis.com URL** based on metric:

| Metric keywords | URL |
|---|---|
| revenue, gross profit, operating income, net income, EBITDA, EPS, R&D, SG&A | `https://stockanalysis.com/stocks/{ticker}/financials/?p=quarterly` |
| free cash flow, operating cash flow, capex, buybacks | `https://stockanalysis.com/stocks/{ticker}/financials/cash-flow-statement/?p=quarterly` |
| total assets, total debt, cash, equity, net debt | `https://stockanalysis.com/stocks/{ticker}/financials/balance-sheet/?p=quarterly` |

   Use lowercase ticker in the URL.

3. **WebFetch** the URL. Prompt: `"Extract the {METRIC} row from the quarterly table. Return all available quarters and values as: Quarter | Value. Include units (millions/billions)."` Take the most recent N quarters.

4. **Build Plotly bar chart inline** (no external script). Dark theme. Color bars by year. Label each bar with the value. Save to `/Users/macproajb/claude_projects/{TICKER}_quarterly_{metric_slug}.html`. Run `open <path>`.

5. **2-sentence takeaway** max: trend direction + any notable inflection.

# Plotly template

```python
import plotly.graph_objects as go

# quarters: list of strings like ["Q1 2022", ...]
# values:   list of numbers (in millions or billions, consistent)
# unit_label: "USD millions" or "USD billions" etc.

year_palette = {
    "2020":"#4a90d9","2021":"#4a90d9","2022":"#5ba85c",
    "2023":"#e8a838","2024":"#d95b5b","2025":"#9b59b6","2026":"#1abc9c",
}
bar_colors = [year_palette.get(q.split()[-1], "#888") for q in quarters]

fig = go.Figure()
fig.add_trace(go.Bar(
    x=quarters, y=values,
    marker_color=bar_colors,
    marker_line_color="rgba(0,0,0,0.15)", marker_line_width=0.8,
    text=[f"${v:.1f}B" for v in values],   # adjust format to unit
    textposition="outside",
    textfont=dict(size=9, color="#e0e0e0"),
    hovertemplate="<b>%{x}</b><br>{METRIC}: $%{y:,.1f}<extra></extra>",
))
fig.update_layout(
    title=dict(
        text=f"{TICKER} — Quarterly {METRIC} ({quarters[0]} – {quarters[-1]})",
        font=dict(size=18, color="#f0f0f0", family="Arial"),
        x=0.5, xanchor="center", y=0.97,
    ),
    xaxis=dict(tickfont=dict(size=9, color="#aaa"), tickangle=-45,
               gridcolor="rgba(255,255,255,0.04)"),
    yaxis=dict(
        title=dict(text=f"{METRIC} ({unit_label})", font=dict(size=11, color="#aaa")),
        tickfont=dict(size=10, color="#aaa"),
        gridcolor="rgba(255,255,255,0.07)", rangemode="tozero",
    ),
    plot_bgcolor="#1a1a2e", paper_bgcolor="#0f0f1a",
    font=dict(color="#e0e0e0"), bargap=0.25,
    margin=dict(t=70, b=110, l=80, r=30), height=540, width=1050,
)
out = f"/Users/macproajb/claude_projects/{TICKER}_quarterly_{metric_slug}.html"
fig.write_html(out)
print("Saved:", out)
```
