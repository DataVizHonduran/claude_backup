---
description: Drawup chart for any FRED commodity series — % above rolling 12-month prior low, 95th-pctl threshold line, plus narrative explainers for each exceedance episode
---

Produce a drawup chart and episode explainers for the FRED series specified in `$ARGUMENTS`.

## Arguments
`$ARGUMENTS` — FRED series ID and optional label (e.g. `APU000074714 "US Gasoline"`, `DCOILWTICO "WTI Crude"`, `PCOPPUSDM "Copper"`).
If only a series ID is given, derive a readable label from the FRED series title.
If no argument is given, ask the user for a series ID before proceeding.

## Steps

### 1. Parse Arguments
Extract `SERIES_ID` and optional `LABEL` from `$ARGUMENTS`.

### 2. Fetch Data and Compute Drawup

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

from fred_client import FredClient
import pandas as pd
import numpy as np

client = FredClient()

# Fetch full history — go back as far as possible
df = client.get_series(SERIES_ID, freq="MS", observation_start="1960-01-01")
prices = df[SERIES_ID].dropna()

# Prior 12-month rolling minimum (shift(1) excludes current month)
rolling_min_12m = prices.shift(1).rolling(window=12, min_periods=6).min()

# Drawup: % above the 12-month prior floor
drawup = (prices - rolling_min_12m) / rolling_min_12m * 100
drawup = drawup.dropna()

p95 = float(np.nanpercentile(drawup, 95))

# Episode detection: consecutive months above p95, gap > 6 months = new episode
above = drawup[drawup >= p95]
episodes = []
ep_dates = []
for dt in above.index:
    if not ep_dates or (dt - ep_dates[-1]).days > 180:
        if ep_dates:
            episodes.append(ep_dates)
        ep_dates = [dt]
    else:
        ep_dates.append(dt)
if ep_dates:
    episodes.append(ep_dates)

# Print episode stats for use in explainers
print(f"p95 threshold: {p95:.2f}%")
for i, ep in enumerate(episodes, 1):
    s, e = ep[0], ep[-1]
    peak_dt = drawup[ep].idxmax()
    peak_val = drawup[peak_dt]
    price_at_peak = prices[peak_dt]
    prior_min = rolling_min_12m[peak_dt]
    print(f"Episode {i}: {s.strftime('%b %Y')} – {e.strftime('%b %Y')}  |  Peak: {peak_dt.strftime('%b %Y')}  drawup={peak_val:.1f}%  price={price_at_peak:.3f}  floor={prior_min:.3f}")
```

### 3. Build Chart

```python
import plotly.graph_objects as go
from datetime import date

# Recession shading
rec = client.get_series("USREC", freq="MS", observation_start="1960-01-01")["USREC"]
rec_idx = rec.index[rec == 1]
bands = []
if len(rec_idx):
    start = prev = rec_idx[0]
    for dt in rec_idx[1:]:
        if (dt - prev).days > 40:
            bands.append((start, prev))
            start = dt
        prev = dt
    bands.append((start, prev))

fig = go.Figure()

for s, e in bands:
    fig.add_vrect(x0=s, x1=e, fillcolor="#d3d3d3", opacity=0.35, layer="below", line_width=0)

fig.add_trace(go.Scatter(
    x=drawup.index, y=drawup.values,
    mode="lines",
    name=f"Drawup vs 12M Prior Min",
    line=dict(color="#0057A8", width=1.6),
    fill="tozeroy", fillcolor="rgba(0,87,168,0.12)",
    hovertemplate="%{x|%b %Y}  %{y:.1f}%<extra></extra>"
))

fig.add_trace(go.Scatter(
    x=[drawup.index[0], drawup.index[-1]], y=[p95, p95],
    mode="lines",
    name=f"95th Pctl ({p95:.1f}%)",
    line=dict(color="#C8102E", dash="dot", width=2),
    hovertemplate=f"95th pctl: {p95:.1f}%<extra></extra>"
))

fig.add_annotation(
    x=drawup.index[-1], y=p95,
    text=f" 95th pctl: {p95:.1f}%",
    showarrow=False, xanchor="right", yanchor="bottom",
    font=dict(color="#C8102E", size=12)
)

fig.update_layout(
    title=dict(
        text=f"{LABEL} — Drawup vs. Prior 12-Month Low",
        font=dict(size=18, family="Arial"),
        x=0.5, xanchor="center"
    ),
    xaxis=dict(title="", showgrid=False, zeroline=False),
    yaxis=dict(title="% Above 12-Month Prior Low", ticksuffix="%", gridcolor="#ebebeb"),
    plot_bgcolor="white", paper_bgcolor="white",
    legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center"),
    hovermode="x unified",
    margin=dict(t=80, b=80, l=70, r=30),
    width=1100, height=560,
    annotations=[dict(
        text=f"Source: FRED ({SERIES_ID}) | Shaded = NBER Recessions",
        xref="paper", yref="paper", x=0.0, y=-0.18,
        showarrow=False, font=dict(size=10, color="#888"), align="left"
    )]
)

fname = f"/Users/macproajb/claude_projects/fred_client/{SERIES_ID}_DRAWUP_12M_P95_{date.today()}.html"
fig.write_html(fname)
print(f"Saved → {fname}")
```

Open with: `open <fname>`

### 4. Write Episode Explainers

Using the episode stats printed in Step 2, write a narrative explainer for **each episode** that crossed the 95th percentile. For each episode include:

- **Header**: `Episode N — Mon YYYY–Mon YYYY | Peak drawup: X% | Price: $Y`
- 2–4 sentences covering: the macro/geopolitical catalyst, why the 12-month floor was low (what depressed prices before the spike), and how/when the episode resolved.
- Close with a **Pattern** note after all episodes summarizing what the episodes have in common (supply shocks vs. demand rebounds vs. refinery constraints, etc.).

Be specific: name the event, the year, the mechanism. Do not hedge or generalize.

### 5. Embed Explainers in the HTML Chart

After writing all episode explainers, inject them into the saved HTML file before `</body>`. Build `explainer_html` as a concatenated HTML string — one `<div>` per episode — then run:

```python
episode_divs = ""
# Build one block per episode, e.g.:
# episode_divs += """
# <div style="margin-bottom:28px">
#   <h3 style="font-size:14px;color:#0057A8;margin-bottom:4px">Episode 1 — Sep 1990–Oct 1990 | Peak drawup: 131.8% | Price: $39.53</h3>
#   <p style="font-size:13px;color:#333;line-height:1.6;margin:0">Narrative text here...</p>
# </div>
# """

pattern_html = """<p style="font-size:13px;color:#555;margin-top:16px;border-top:1px solid #ddd;padding-top:12px">
  <strong>Pattern:</strong> [pattern note]
</p>"""

inject = f"""
<div style="font-family:Arial,sans-serif;max-width:1100px;margin:24px auto;padding:0 30px 40px">
  <h2 style="font-size:15px;color:#333;border-bottom:2px solid #0057A8;padding-bottom:6px;margin-bottom:20px">
    95th-Percentile Episodes — Narrative Explainers
  </h2>
  {episode_divs}
  {pattern_html}
</div>
"""

with open(fname, "r") as f:
    html = f.read()
html = html.replace("</body>", inject + "</body>")
with open(fname, "w") as f:
    f.write(html)
print(f"Explainers embedded → {fname}")
```

Populate `episode_divs` and `pattern_html` with the actual text from Step 4 before running. Each episode `<h3>` matches the header format from Step 4. The pattern note goes in `pattern_html`.
