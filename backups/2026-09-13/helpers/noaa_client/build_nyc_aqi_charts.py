import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date

CSV = '/Users/macproajb/claude_projects/noaa_client/AQI_NYC_composite_daily.csv'
OUT_DIR = '/Users/macproajb/boquin.github.io/reports/nyc-aqi'

import os
os.makedirs(OUT_DIR, exist_ok=True)

df = pd.read_csv(CSV, parse_dates=['date'])
df['year'] = df['date'].dt.year

# ── Chart 1: Daily AQI line chart ──────────────────────────────────────────
df_sorted = df.sort_values('date').reset_index(drop=True)
df_sorted['rolling30'] = df_sorted['aqi'].rolling(30, center=True).mean()

x_num = (df_sorted['date'] - df_sorted['date'].min()).dt.days.astype(float)
z = np.polyfit(x_num, df_sorted['aqi'], 1)
p = np.poly1d(z)

def aqi_color(v):
    if v <= 50:  return '#00e400'
    if v <= 100: return '#ffff00'
    if v <= 150: return '#ff7e00'
    if v <= 200: return '#ff0000'
    return '#8f3f97'

colors = [aqi_color(v) for v in df_sorted['aqi']]

fig1 = go.Figure()
for lo, hi, color, label in [
    (0,   50,  '#00e400', 'Good'),
    (50,  100, '#ffff00', 'Moderate'),
    (100, 150, '#ff7e00', 'Unhealthy for Sensitive Groups'),
    (150, 200, '#ff0000', 'Unhealthy'),
    (200, 300, '#8f3f97', 'Very Unhealthy'),
]:
    fig1.add_hrect(y0=lo, y1=hi, fillcolor=color, opacity=0.06, line_width=0,
                   annotation_text=label, annotation_position='right',
                   annotation_font_size=10, annotation_font_color='#777')

fig1.add_trace(go.Scatter(
    x=df_sorted['date'], y=df_sorted['aqi'],
    mode='markers', marker=dict(size=3, color=colors, opacity=0.45),
    name='Daily AQI',
    hovertemplate='<b>%{x|%b %d, %Y}</b><br>AQI: %{y:.0f}<extra></extra>',
))
fig1.add_trace(go.Scatter(
    x=df_sorted['date'], y=df_sorted['rolling30'],
    mode='lines', line=dict(color='#2c5f8a', width=2),
    name='30-day avg',
    hovertemplate='30-day avg: %{y:.1f}<extra></extra>',
))
fig1.add_trace(go.Scatter(
    x=df_sorted['date'], y=p(x_num),
    mode='lines', line=dict(color='#e74c3c', width=1.5, dash='dash'),
    name=f'Trend ({z[0]*365:+.2f} AQI/yr)', hoverinfo='skip',
))

milestones = [
    ("1970-01-01", "Clean Energy Act<br>passes"),
    ("1977-01-01", "Clean Energy Act<br>amendments"),
    ("1990-01-01", "Catalytic converter<br>requirements"),
    ("2007-01-01", "Diesel standards<br>tightened"),
    ("2020-03-01", "COVID"),
]
for xval, label in milestones:
    fig1.add_vline(x=xval, line=dict(color='#555', width=1.2, dash='dot'))
    fig1.add_annotation(
        x=xval, y=1, yref='paper', yanchor='top',
        text=label, showarrow=False,
        font=dict(size=10, color='#444'),
        bgcolor='rgba(255,255,255,0.75)',
        borderpad=3, xanchor='left', ax=0, ay=0,
    )

fig1.update_layout(
    title=dict(
        text='<b>NYC Metro Daily Air Quality Index (AQI) — 55 Years (1970–2026)</b><br>'
             '<sup>Composite AQI (max of Ozone, NO₂, CO, SO₂; PM2.5 from 1999) · EPA Air Quality System</sup>',
        x=0.5, xanchor='center', font_size=17,
    ),
    xaxis=dict(title='Date', showgrid=True, gridcolor='#eee', rangeslider=dict(visible=True)),
    yaxis=dict(title='Air Quality Index (AQI)', showgrid=True, gridcolor='#eee'),
    plot_bgcolor='white', paper_bgcolor='white',
    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    margin=dict(l=60, r=160, t=100, b=80),
    hovermode='x unified', width=1200, height=600,
)

# ── Chart 2: 100+ days per year stacked bar ────────────────────────────────
def cat(v):
    if v >= 201: return 'Very Unhealthy (201+)'
    if v >= 151: return 'Unhealthy (151–200)'
    return 'Unhealthy for Sensitive Groups (100–150)'

bad = df[df['aqi'] >= 100].copy()
bad['category'] = bad['aqi'].apply(cat)
stacked = bad.groupby(['year', 'category']).size().unstack(fill_value=0).reset_index()

cats = ['Unhealthy for Sensitive Groups (100–150)', 'Unhealthy (151–200)', 'Very Unhealthy (201+)']
cat_colors = {'Unhealthy for Sensitive Groups (100–150)': '#ff7e00', 'Unhealthy (151–200)': '#ff0000', 'Very Unhealthy (201+)': '#8f3f97'}

fig2 = go.Figure()
for cat_name in cats:
    if cat_name not in stacked.columns:
        continue
    fig2.add_trace(go.Bar(
        x=stacked['year'], y=stacked[cat_name],
        name=cat_name, marker_color=cat_colors[cat_name],
        hovertemplate=f'<b>%{{x}}</b><br>{cat_name}: %{{y}} days<extra></extra>',
    ))

for xval, label in [("1970", "Clean Energy Act<br>passes"), ("1977", "Clean Energy Act<br>amendments"), ("1990", "Catalytic converter<br>requirements"), ("2007", "Diesel standards<br>tightened"), ("2020", "COVID")]:
    fig2.add_vline(x=int(xval), line=dict(color='#555', width=1.2, dash='dot'))
    fig2.add_annotation(
        x=int(xval), y=1, yref='paper', yanchor='top',
        text=label, showarrow=False,
        font=dict(size=10, color='#444'),
        bgcolor='rgba(255,255,255,0.75)',
        borderpad=3, xanchor='left',
    )

fig2.update_layout(
    barmode='stack',
    title=dict(
        text='<b>NYC Metro — Days per Year with Air Quality Index (AQI) ≥ 100 (1970–2026)</b><br>'
             '<sup>Composite AQI (Ozone, NO₂, CO, SO₂; PM2.5 from 1999) · EPA Air Quality System</sup>',
        x=0.5, xanchor='center', font_size=17,
    ),
    xaxis=dict(title='Year', dtick=5, showgrid=False),
    yaxis=dict(title='Days with Air Quality Index (AQI) ≥ 100', showgrid=True, gridcolor='#eee'),
    plot_bgcolor='white', paper_bgcolor='white',
    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    margin=dict(l=60, r=40, t=100, b=60),
    width=1100, height=520,
)

# ── Chart 3: Bubble chart — days per AQI zone per year ────────────────────
def zone(v):
    if v <= 50:  return 'Good (0–50)'
    if v <= 100: return 'Moderate (51–100)'
    if v <= 150: return 'Unhealthy for Sensitive Groups (101–150)'
    if v <= 200: return 'Unhealthy (151–200)'
    if v <= 300: return 'Very Unhealthy (201–300)'
    return 'Hazardous (301+)'

zone_order  = ['Good (0–50)', 'Moderate (51–100)', 'Unhealthy for Sensitive Groups (101–150)',
               'Unhealthy (151–200)', 'Very Unhealthy (201–300)', 'Hazardous (301+)']
zone_colors = {
    'Good (0–50)':                              '#00e400',
    'Moderate (51–100)':                        '#ffcc00',
    'Unhealthy for Sensitive Groups (101–150)': '#ff7e00',
    'Unhealthy (151–200)':                      '#ff0000',
    'Very Unhealthy (201–300)':                 '#8f3f97',
    'Hazardous (301+)':                         '#7e0023',
}

df['zone'] = df['aqi'].apply(zone)
bubble = df.groupby(['year', 'zone']).size().reset_index(name='days')

fig3 = go.Figure()
for z in zone_order:
    sub = bubble[bubble['zone'] == z]
    if sub.empty:
        continue
    fig3.add_trace(go.Scatter(
        x=sub['year'],
        y=[z] * len(sub),
        mode='markers',
        marker=dict(
            size=sub['days'],
            sizemode='area',
            sizeref=2 * bubble['days'].max() / (60 ** 2),
            sizemin=3,
            color=zone_colors[z],
            opacity=0.8,
            line=dict(color='white', width=0.5),
        ),
        name=z,
        customdata=sub['days'],
        hovertemplate='<b>%{x}</b><br>' + z + ': %{customdata} days<extra></extra>',
    ))

for xval, label in [("1970", "Clean Energy Act<br>passes"), ("1977", "Clean Energy Act<br>amendments"), ("1990", "Catalytic converter<br>requirements"), ("2007", "Diesel standards<br>tightened"), ("2020", "COVID")]:
    fig3.add_vline(x=int(xval), line=dict(color='#aaa', width=1, dash='dot'))
    fig3.add_annotation(
        x=int(xval), y=-0.08, yref='paper', yanchor='top',
        text=label, showarrow=False,
        font=dict(size=9, color='#555'),
        bgcolor='rgba(255,255,255,0.75)',
        borderpad=2, xanchor='center',
    )

fig3.update_layout(
    title=dict(
        text='<b>NYC Metro — Days per Air Quality Index (AQI) Zone per Year (1970–2026)</b><br>'
             '<sup>Bubble size = number of days in that zone · EPA Air Quality System</sup>',
        x=0.5, xanchor='center', font_size=17,
    ),
    xaxis=dict(title='', dtick=5, showgrid=True, gridcolor='#eee'),
    yaxis=dict(
        title='', categoryorder='array', categoryarray=zone_order,
        showgrid=True, gridcolor='#eee',
    ),
    plot_bgcolor='white', paper_bgcolor='white',
    showlegend=False,
    margin=dict(l=180, r=40, t=100, b=100),
    hovermode='closest',
    width=1100, height=480,
)

# ── Write combined index.html ───────────────────────────────────────────────
daily_html  = fig1.to_html(full_html=False, include_plotlyjs=False)
bar_html    = fig2.to_html(full_html=False, include_plotlyjs=False)
bubble_html = fig3.to_html(full_html=False, include_plotlyjs=False)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NYC Air Quality Index (AQI) — 55-Year History</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f8f9fa; margin: 0; padding: 20px; color: #222; }}
  h1 {{ text-align: center; font-size: 1.6rem; margin-bottom: 4px; }}
  p.sub {{ text-align: center; color: #666; font-size: 0.9rem; margin-top: 0; }}
  .chart {{ background: white; border-radius: 8px; padding: 16px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; }}
  footer {{ text-align: center; color: #aaa; font-size: 0.8rem; margin-top: 32px; }}
</style>
</head>
<body>
<h1>NYC Metro Air Quality Index (AQI) — 55-Year History</h1>
<p class="sub">Source: EPA Air Quality System · Updated {date.today()}</p>
<div class="chart">{daily_html}</div>
<div class="chart">{bubble_html}</div>
<div class="chart">{bar_html}</div>
<footer>Composite AQI = daily max across Ozone, NO₂, CO, SO₂ (all years) and PM2.5 (1999+)</footer>
</body>
</html>"""

with open(f'{OUT_DIR}/index.html', 'w') as f:
    f.write(html)

print(f"Written: {OUT_DIR}/index.html")
print(f"Total rows: {len(df)}, years: {df['year'].min()}–{df['year'].max()}")
