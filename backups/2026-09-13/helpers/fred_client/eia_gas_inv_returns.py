"""
EIA Gasoline Inventories vs Subsequent 3M & 6M Returns
Data:
  - Inventories: EIA API v2, EPM0 (Total Motor Gasoline), NUS, weekly → monthly
  - Prices:      yfinance RB=F (RBOB Gasoline Futures, $/gal)
"""
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date

TODAY = date.today()

# ── 1. EIA Gasoline Inventories (EPM0 = Total Motor Gasoline, NUS, weekly) ──
print("Fetching EIA gasoline stocks...")
params = {
    "frequency": "weekly",
    "data[0]": "value",
    "facets[product][]": "EPM0",
    "facets[duoarea][]": "NUS",
    "sort[0][column]": "period",
    "sort[0][direction]": "asc",
    "length": 5000,
    "api_key": "DEMO_KEY",
}
r = requests.get("https://api.eia.gov/v2/petroleum/stoc/wstk/data/", params=params, timeout=30)
r.raise_for_status()
raw = r.json()["response"]["data"]
inv_raw = pd.DataFrame(raw)
inv_raw["date"] = pd.to_datetime(inv_raw["period"])
inv_raw["value"] = pd.to_numeric(inv_raw["value"], errors="coerce")
inv_raw = inv_raw.set_index("date")[["value"]].dropna()
inv_raw.columns = ["GasStocks_KB"]

# Resample weekly → monthly (last observation of month)
inv = inv_raw.resample("MS").mean()
print(f"  {len(inv)} monthly obs  |  {inv.index[0].date()} – {inv.index[-1].date()}")
print(f"  Latest: {inv.iloc[-1,0]:,.0f} thousand barrels")

# ── 2. RBOB Gasoline Futures Prices (RB=F) ──
print("Fetching RBOB gasoline prices (yfinance)...")
raw_rbob = yf.download("RB=F", start="2005-01-01", auto_adjust=True, progress=False)["Close"]
if hasattr(raw_rbob, "squeeze"):
    raw_rbob = raw_rbob.squeeze()
rbob = raw_rbob.resample("MS").last()
rbob.name = "RBOB_Close"
print(f"  {len(rbob)} monthly obs  |  {rbob.index[0].date()} – {rbob.index[-1].date()}")
print(f"  Latest: ${rbob.iloc[-1]:.3f}/gal")

# ── 3. Forward Returns ──
fwd_3m = (rbob.shift(-3) / rbob - 1) * 100
fwd_6m = (rbob.shift(-6) / rbob - 1) * 100

# ── 4. Merge ──
df = pd.concat([inv, fwd_3m.rename("Fwd_3M_Pct"), fwd_6m.rename("Fwd_6M_Pct")], axis=1).dropna()
print(f"\nMerged dataset: {len(df)} rows  |  {df.index[0].date()} – {df.index[-1].date()}")

# Correlation summary
corr3 = df["GasStocks_KB"].corr(df["Fwd_3M_Pct"])
corr6 = df["GasStocks_KB"].corr(df["Fwd_6M_Pct"])
print(f"Correlation  Inv vs 3M Fwd: {corr3:.3f}")
print(f"Correlation  Inv vs 6M Fwd: {corr6:.3f}")

# Quantile buckets
q_labels = [f"D{i}" for i in range(1, 11)]
q_labels[0] = "D1 (Low)"
q_labels[-1] = "D10 (High)"
df["inv_q"] = pd.qcut(df["GasStocks_KB"], 10, labels=q_labels)
print("\nMedian forward returns by inventory decile:")
print(df.groupby("inv_q", observed=True)[["Fwd_3M_Pct","Fwd_6M_Pct"]].median().round(1))

# ── 5. Chart A: Time series — Inventories + 3M Fwd Return ──
fig1 = make_subplots(specs=[[{"secondary_y": True}]])

fig1.add_trace(go.Scatter(
    x=df.index, y=df["GasStocks_KB"],
    name="Gas Stocks (KB)", line=dict(color="#0057A8", width=2),
    hovertemplate="%{x|%b %Y}<br>%{y:,.0f} KB<extra>Stocks</extra>"
), secondary_y=False)

colors_3m = ["rgba(0,135,90,0.55)" if v >= 0 else "rgba(200,16,46,0.55)" for v in df["Fwd_3M_Pct"]]
fig1.add_trace(go.Bar(
    x=df.index, y=df["Fwd_3M_Pct"],
    name="Subsequent 3M Return", marker_color=colors_3m,
    hovertemplate="%{x|%b %Y}<br>%{y:.1f}%<extra>3M Fwd</extra>"
), secondary_y=True)

fig1.update_layout(
    title="EIA Motor Gasoline Stocks vs Subsequent 3-Month RBOB Return",
    height=520, template="plotly_white",
    legend=dict(orientation="h", y=1.08), hovermode="x unified",
    font=dict(family="Arial")
)
fig1.update_yaxes(title_text="Gasoline Stocks (Thousand Barrels)", secondary_y=False, tickformat=",")
fig1.update_yaxes(title_text="3M Forward Return (%)", secondary_y=True, ticksuffix="%",
                  zeroline=True, zerolinecolor="gray", zerolinewidth=1)

fname1 = f"/Users/macproajb/claude_projects/fred_client/EIA_GAS_INV_3M_FWD_{TODAY}.html"
fig1.write_html(fname1)
print(f"\nSaved: {fname1}")

# ── 6. Chart B: Time series — Inventories + 6M Fwd Return ──
fig2 = make_subplots(specs=[[{"secondary_y": True}]])

fig2.add_trace(go.Scatter(
    x=df.index, y=df["GasStocks_KB"],
    name="Gas Stocks (KB)", line=dict(color="#0057A8", width=2),
    hovertemplate="%{x|%b %Y}<br>%{y:,.0f} KB<extra>Stocks</extra>"
), secondary_y=False)

colors_6m = ["rgba(0,135,90,0.55)" if v >= 0 else "rgba(200,16,46,0.55)" for v in df["Fwd_6M_Pct"]]
fig2.add_trace(go.Bar(
    x=df.index, y=df["Fwd_6M_Pct"],
    name="Subsequent 6M Return", marker_color=colors_6m,
    hovertemplate="%{x|%b %Y}<br>%{y:.1f}%<extra>6M Fwd</extra>"
), secondary_y=True)

fig2.update_layout(
    title="EIA Motor Gasoline Stocks vs Subsequent 6-Month RBOB Return",
    height=520, template="plotly_white",
    legend=dict(orientation="h", y=1.08), hovermode="x unified",
    font=dict(family="Arial")
)
fig2.update_yaxes(title_text="Gasoline Stocks (Thousand Barrels)", secondary_y=False, tickformat=",")
fig2.update_yaxes(title_text="6M Forward Return (%)", secondary_y=True, ticksuffix="%",
                  zeroline=True, zerolinecolor="gray", zerolinewidth=1)

fname2 = f"/Users/macproajb/claude_projects/fred_client/EIA_GAS_INV_6M_FWD_{TODAY}.html"
fig2.write_html(fname2)
print(f"Saved: {fname2}")

# ── 7. Chart C: Scatter — Inventory Level vs Forward Returns ──
fig3 = make_subplots(rows=1, cols=2,
    subplot_titles=[
        f"Stocks vs 3M Fwd Return (r={corr3:.2f})",
        f"Stocks vs 6M Fwd Return (r={corr6:.2f})"
    ])

z3 = np.polyfit(df["GasStocks_KB"], df["Fwd_3M_Pct"], 1)
z6 = np.polyfit(df["GasStocks_KB"], df["Fwd_6M_Pct"], 1)
xr = np.linspace(df["GasStocks_KB"].min(), df["GasStocks_KB"].max(), 100)

fig3.add_trace(go.Scatter(
    x=df["GasStocks_KB"], y=df["Fwd_3M_Pct"],
    mode="markers",
    marker=dict(color="#0057A8", opacity=0.45, size=7),
    text=df.index.strftime("%b %Y"),
    hovertemplate="%{text}<br>%{x:,.0f} KB → %{y:.1f}%<extra>3M</extra>",
    name="3M"), row=1, col=1)
fig3.add_trace(go.Scatter(
    x=xr, y=z3[0]*xr + z3[1],
    mode="lines", line=dict(color="#C8102E", dash="dash", width=1.5),
    name="OLS 3M", showlegend=False), row=1, col=1)

fig3.add_trace(go.Scatter(
    x=df["GasStocks_KB"], y=df["Fwd_6M_Pct"],
    mode="markers",
    marker=dict(color="#00875A", opacity=0.45, size=7),
    text=df.index.strftime("%b %Y"),
    hovertemplate="%{text}<br>%{x:,.0f} KB → %{y:.1f}%<extra>6M</extra>",
    name="6M"), row=1, col=2)
fig3.add_trace(go.Scatter(
    x=xr, y=z6[0]*xr + z6[1],
    mode="lines", line=dict(color="#C8102E", dash="dash", width=1.5),
    name="OLS 6M", showlegend=False), row=1, col=2)

fig3.update_layout(
    title="EIA Motor Gasoline Stocks vs Forward RBOB Returns (Monthly, 2005–present)",
    height=500, template="plotly_white", showlegend=False,
    font=dict(family="Arial")
)
fig3.update_xaxes(title_text="Gasoline Stocks (Thousand Barrels)", tickformat=",")
fig3.update_yaxes(title_text="Forward Return (%)", ticksuffix="%", row=1, col=1)
fig3.update_yaxes(ticksuffix="%", row=1, col=2)

fname3 = f"/Users/macproajb/claude_projects/fred_client/EIA_GAS_SCATTER_{TODAY}.html"
fig3.write_html(fname3)
print(f"Saved: {fname3}")

# ── 8. Chart D: Quartile bar chart ──
qmed = df.groupby("inv_q", observed=True)[["Fwd_3M_Pct","Fwd_6M_Pct"]].median()

fig4 = go.Figure()
fig4.add_trace(go.Bar(
    x=q_labels, y=qmed["Fwd_3M_Pct"],
    name="3M Fwd Return",
    marker_color=["rgba(200,16,46,0.7)" if v < 0 else "rgba(0,135,90,0.7)" for v in qmed["Fwd_3M_Pct"]],
    text=[f"{v:.1f}%" for v in qmed["Fwd_3M_Pct"]],
    textposition="outside",
))
fig4.add_trace(go.Bar(
    x=q_labels, y=qmed["Fwd_6M_Pct"],
    name="6M Fwd Return",
    marker_color=["rgba(200,16,46,0.45)" if v < 0 else "rgba(0,87,168,0.55)" for v in qmed["Fwd_6M_Pct"]],
    text=[f"{v:.1f}%" for v in qmed["Fwd_6M_Pct"]],
    textposition="outside",
))
fig4.update_layout(
    title="Median RBOB Forward Return by Gasoline Inventory Decile",
    height=500, template="plotly_white", barmode="group",
    yaxis_title="Median Return (%)", yaxis_ticksuffix="%",
    legend=dict(orientation="h", y=1.05),
    font=dict(family="Arial")
)
fig4.add_hline(y=0, line_width=1, line_color="gray")

fname4 = f"/Users/macproajb/claude_projects/fred_client/EIA_GAS_DECILE_{TODAY}.html"
fig4.write_html(fname4)
print(f"Saved: {fname4}")
print("\nDone.")
