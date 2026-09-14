# Manufacturing Spend & AI Capex Dashboard

Fetch and chart key FRED indicators for the datacenter-era manufacturing renaissance. Four chart variations:

1. **Four-panel overview** — Mfg Construction, Electrical Equipment IP, Mfg Structures Investment, Power Construction (indexed Jan 2020 = 100)
2. **Build vs. Deploy (indexed)** — Side-by-side: Census vs BEA | BEA vs BEA, Jan 2020 = 100, 1993–present
3. **Build vs. Deploy (3m annualized)** — Same side-by-side structure, momentum view
4. **Raw dollar context** — Annualized run rates with GDP benchmarks

All charts saved to `/Users/macproajb/claude_projects/fred_client/`.

---

## Module setup

```python
import sys, os, requests, pandas as pd
sys.path.insert(0, '/Users/macproajb/claude_projects')
from dotenv import load_dotenv
load_dotenv('/Users/macproajb/claude_projects/fred_client/.env')
from fred_client import FredPlotter
from plotly.subplots import make_subplots
import plotly.graph_objects as go
from datetime import date

api_key = os.environ.get("FRED_API_KEY")

def fetch(series_id, start="1993-01-01", freq="m"):
    r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={
        "series_id": series_id, "observation_start": start,
        "api_key": api_key, "file_type": "json",
        "frequency": freq, "aggregation_method": "avg"
    })
    r.raise_for_status()
    obs = r.json()["observations"]
    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df.columns = [series_id]
    df.index = df.index.normalize()
    return df.dropna()
```

> **Note:** Use plain `requests` — `requests_cache` breaks on Python 3.13. Never use `FredClient.get_series()` directly.

---

## Series reference

| Series ID | Source | Description | Freq | Units |
|---|---|---|---|---|
| `PRMFGCONS` | Census | Private Mfg Construction Spending | Monthly | SAAR, $M |
| `IPG335S` | Fed | Electrical Equipment & Appliance IP | Monthly | SA, Index |
| `C307RC1Q027SBEA` | BEA | Private Fixed Investment: Nonresidential Structures: Manufacturing | Quarterly | SAAR, $B |
| `PRPWRCONS` | Census | Private Power Construction Spending | Monthly | SAAR, $M |
| `B935RC1Q027SBEA` | BEA | Private Fixed Investment: Nonresidential Equipment: Computers & Peripherals | Quarterly | SAAR, $B |

All three go back to 1993-01-01.

---

## Chart 1 — Four-panel overview (indexed Jan 2020 = 100)

```python
mfg     = fetch("PRMFGCONS")
elec    = fetch("IPG335S")
mfg_inv = fetch("C307RC1Q027SBEA", freq="q").resample("MS").interpolate("linear")
pwr     = fetch("PRPWRCONS")

df = pd.concat([mfg, elec, mfg_inv, pwr], axis=1)
df.columns = [
    "Mfg Construction Spending",
    "Electrical Equipment IP",
    "Mfg Structures Investment",
    "Power Construction Spending",
]
base = df.loc[pd.Timestamp("2020-01-01")]
df_norm = (df / base) * 100

plotter = FredPlotter(
    df_norm,
    title="Datacenter-Era Manufacturing Renaissance — Four Indicators<br><sup>Indexed to Jan 2020 = 100 | Mfg Construction, Electrical Equipment IP, Mfg Structures Investment, Power Construction</sup>",
    height=560
)
fig = plotter.line(value_fmt="%{y:.1f}", y_label="Index (Jan 2020 = 100)")
fig.update_layout(
    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02,
                font=dict(size=13), bgcolor="rgba(255,255,255,0.85)", bordercolor="#CCCCCC", borderwidth=1),
    margin=dict(l=60, r=200, t=80, b=60),
)
fig.write_html(f"/Users/macproajb/claude_projects/fred_client/DATACENTER_MFG_RENAISSANCE_{date.today()}.html")
```

**Key reads (mid-2026):**
- Mfg Structures Investment ~246 — CHIPS/IRA capex still elevated
- Mfg Construction Spending ~219 — rolling off 2024-25 peak as fab projects complete
- Power Construction ~129 — grid buildout running hot, still catching up
- Electrical Equipment IP ~98 — flat; transformer/switchgear supply chain is the bottleneck

---

## Chart 2 & 3 — Build vs. Deploy side-by-side (shared scaffold)

Both panels per chart:
- **Left:** Census `PRMFGCONS` vs BEA `B935RC1Q027SBEA`
- **Right:** BEA `C307RC1Q027SBEA` vs BEA `B935RC1Q027SBEA` (apples-to-apples, same methodology)

NBER recessions shaded. Zero line added on 3m annualized version.

```python
NBER_RECESSIONS = [
    ("2001-03-01", "2001-11-01"),
    ("2007-12-01", "2009-06-01"),
    ("2020-02-01", "2020-04-01"),
]
COLORS = {"build": "#0057A8", "deploy": "#C8102E"}

mfg_const  = fetch("PRMFGCONS")
computers  = fetch("B935RC1Q027SBEA", freq="q").resample("MS").interpolate("linear")
mfg_struct = fetch("C307RC1Q027SBEA", freq="q").resample("MS").interpolate("linear")

def add_recession_shading(fig, col):
    for start, end in NBER_RECESSIONS:
        fig.add_vrect(x0=start, x1=end, fillcolor="#CCCCCC", opacity=0.25,
                      layer="below", line_width=0, row=1, col=col)

LAYOUT_BASE = dict(
    font=dict(family="Helvetica Neue, Arial, sans-serif", size=12, color="#333333"),
    paper_bgcolor="white", plot_bgcolor="white",
    height=520, hovermode="x unified",
    legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02,
                font=dict(size=12), bgcolor="rgba(255,255,255,0.85)", bordercolor="#CCCCCC", borderwidth=1),
    margin=dict(l=60, r=220, t=100, b=60),
)

AXIS_STYLE = dict(showgrid=False, showline=True, linecolor="#CCCCCC", tickfont=dict(size=11))
YAXIS_STYLE = dict(showgrid=True, gridcolor="#E5E5E5", zeroline=False, tickfont=dict(size=11))
```

### Chart 2 — Indexed (Jan 2020 = 100), 1993–present

```python
base = pd.Timestamp("2020-01-01")
def norm(s): return (s / s.loc[base]) * 100

p1_build  = norm(mfg_const.iloc[:,0] / 1000)   # $M → $B for display parity
p1_deploy = norm(computers.iloc[:,0])
p2_build  = norm(mfg_struct.iloc[:,0])
p2_deploy = norm(computers.iloc[:,0])

fig = make_subplots(rows=1, cols=2,
    subplot_titles=["Original: Census vs BEA", "Apples-to-Apples: BEA vs BEA"],
    horizontal_spacing=0.08)

fig.add_trace(go.Scatter(x=p1_build.index, y=p1_build, name="Mfg Construction (Census)",
    line=dict(color=COLORS["build"], width=2),
    hovertemplate="<b>Mfg Construction</b>: %{y:.1f}<extra></extra>"), row=1, col=1)
fig.add_trace(go.Scatter(x=p1_deploy.index, y=p1_deploy, name="Computers & Peripherals (BEA)",
    showlegend=False, line=dict(color=COLORS["deploy"], width=2),
    hovertemplate="<b>Computers & Peripherals</b>: %{y:.1f}<extra></extra>"), row=1, col=1)
fig.add_trace(go.Scatter(x=p2_build.index, y=p2_build, name="Mfg Structures Investment (BEA)",
    line=dict(color=COLORS["build"], width=2, dash="dot"),
    hovertemplate="<b>Mfg Structures (BEA)</b>: %{y:.1f}<extra></extra>"), row=1, col=2)
fig.add_trace(go.Scatter(x=p2_deploy.index, y=p2_deploy, name="Computers & Peripherals (BEA)",
    line=dict(color=COLORS["deploy"], width=2),
    hovertemplate="<b>Computers & Peripherals</b>: %{y:.1f}<extra></extra>"), row=1, col=2)

add_recession_shading(fig, 1); add_recession_shading(fig, 2)
fig.update_layout(**LAYOUT_BASE, title=dict(font=dict(size=15), text=(
    "Build vs. Deploy: AI Capex Split (1993–present)<br>"
    "<sup>Indexed Jan 2020 = 100 | Left: Census mfg construction vs BEA computers | Right: BEA structures vs BEA computers</sup>"
)))
for col in [1, 2]:
    fig.update_xaxes(**AXIS_STYLE, row=1, col=col)
    fig.update_yaxes(**YAXIS_STYLE, title_text="Index (Jan 2020 = 100)" if col == 1 else "", row=1, col=col)

fig.write_html(f"/Users/macproajb/claude_projects/fred_client/AI_BUILD_VS_DEPLOY_SIDEBYSIDE_{date.today()}.html")
```

### Chart 3 — 3-Month Annualized Growth Rate, 1993–present

```python
def annualize_3m(s):
    return ((s / s.shift(3)) ** 4 - 1) * 100

clip = (-100, 300)
p1_build  = annualize_3m(mfg_const.iloc[:,0]).clip(*clip)
p1_deploy = annualize_3m(computers.iloc[:,0]).clip(*clip)
p2_build  = annualize_3m(mfg_struct.iloc[:,0]).clip(*clip)
p2_deploy = annualize_3m(computers.iloc[:,0]).clip(*clip)

fig = make_subplots(rows=1, cols=2,
    subplot_titles=["Original: Census vs BEA", "Apples-to-Apples: BEA vs BEA"],
    horizontal_spacing=0.08)

fig.add_trace(go.Scatter(x=p1_build.index, y=p1_build, name="Mfg Construction (Census)",
    line=dict(color=COLORS["build"], width=1.5),
    hovertemplate="<b>Mfg Construction</b>: %{y:.1f}%<extra></extra>"), row=1, col=1)
fig.add_trace(go.Scatter(x=p1_deploy.index, y=p1_deploy, name="Computers & Peripherals (BEA)",
    showlegend=False, line=dict(color=COLORS["deploy"], width=1.5),
    hovertemplate="<b>Computers & Peripherals</b>: %{y:.1f}%<extra></extra>"), row=1, col=1)
fig.add_trace(go.Scatter(x=p2_build.index, y=p2_build, name="Mfg Structures Investment (BEA)",
    line=dict(color=COLORS["build"], width=1.5, dash="dot"),
    hovertemplate="<b>Mfg Structures (BEA)</b>: %{y:.1f}%<extra></extra>"), row=1, col=2)
fig.add_trace(go.Scatter(x=p2_deploy.index, y=p2_deploy, name="Computers & Peripherals (BEA)",
    line=dict(color=COLORS["deploy"], width=1.5),
    hovertemplate="<b>Computers & Peripherals</b>: %{y:.1f}%<extra></extra>"), row=1, col=2)

add_recession_shading(fig, 1); add_recession_shading(fig, 2)
for col in [1, 2]:
    fig.add_hline(y=0, line_width=1, line_color="#999999", line_dash="dot", row=1, col=col)

fig.update_layout(**LAYOUT_BASE, title=dict(font=dict(size=15), text=(
    "Build vs. Deploy: 3-Month Annualized Growth Rate (1993–present)<br>"
    "<sup>Left: Census mfg construction vs BEA computers | Right: BEA structures vs BEA computers | Clipped ±300%</sup>"
)))
for col in [1, 2]:
    fig.update_xaxes(**AXIS_STYLE, row=1, col=col)
    fig.update_yaxes(**YAXIS_STYLE, title_text="3m Annualized Growth (%)" if col == 1 else "", row=1, col=col)

fig.write_html(f"/Users/macproajb/claude_projects/fred_client/AI_BUILD_VS_DEPLOY_3MANN_{date.today()}.html")
```

**Key reads (mid-2026):**
- Computers & Peripherals: +94% annualized — still running at near-peak acceleration
- Mfg Construction: -15% annualized
- Mfg Structures (BEA): -25% annualized
- Momentum divergence is sharper than the level chart; construction contracting hard while compute deployment accelerates

---

## Step 4 — Raw dollar context

```python
mfg_raw  = fetch("PRMFGCONS", start="2019-01-01")
comp_raw = fetch("B935RC1Q027SBEA", start="2019-01-01", freq="q")

print("=== Mfg Construction Spending (PRMFGCONS) — $M SAAR ===")
for d in ["2020-01-01","2022-01-01","2023-01-01","2024-01-01","2025-01-01"]:
    ts = pd.Timestamp(d)
    if ts in mfg_raw.index:
        print(f"  {d[:7]}: ${mfg_raw.loc[ts].values[0]/1000:.1f}B/yr")
print(f"  Latest: ${mfg_raw.dropna().iloc[-1].values[0]/1000:.1f}B/yr")

print("\n=== Computers & Peripherals Investment (B935RC1Q027SBEA) — $B SAAR ===")
for d in ["2020-01-01","2022-01-01","2023-01-01","2024-01-01","2025-01-01"]:
    ts = pd.Timestamp(d)
    if ts in comp_raw.index:
        print(f"  {d[:7]}: ${comp_raw.loc[ts].values[0]:.0f}B/yr")
print(f"  Latest: ${comp_raw.dropna().iloc[-1].values[0]:.0f}B/yr")

print(f"\n  US GDP ~$29T | Computers at $384B = {384/29000*100:.1f}% of GDP")
```

---

## Open all charts

```bash
open /Users/macproajb/claude_projects/fred_client/DATACENTER_MFG_RENAISSANCE_<date>.html
open /Users/macproajb/claude_projects/fred_client/AI_BUILD_VS_DEPLOY_SIDEBYSIDE_<date>.html
open /Users/macproajb/claude_projects/fred_client/AI_BUILD_VS_DEPLOY_3MANN_<date>.html
```
