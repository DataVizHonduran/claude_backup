import pandas as pd
import plotly.graph_objects as go

CSV = '/Users/macproajb/claude_projects/noaa_client/AQI_NYC_composite_daily.csv'
OUT = '/Users/macproajb/boquin.github.io/reports/nyc-aqi/animated.html'

df = pd.read_csv(CSV, parse_dates=['date'])
df['year'] = df['date'].dt.year

def zone(v):
    if v <= 50:  return 'Good (0–50)'
    if v <= 100: return 'Moderate (51–100)'
    if v <= 150: return 'Unhealthy for Sensitive Groups (101–150)'
    if v <= 200: return 'Unhealthy (151–200)'
    if v <= 300: return 'Very Unhealthy (201–300)'
    return 'Hazardous (301+)'

zone_order = [
    'Good (0–50)',
    'Moderate (51–100)',
    'Unhealthy for Sensitive Groups (101–150)',
    'Unhealthy (151–200)',
    'Very Unhealthy (201–300)',
    'Hazardous (301+)',
]
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
sizeref = 2 * bubble['days'].max() / (60 ** 2)

years = sorted(df['year'].unique())

def traces_up_to(yr):
    sub_all = bubble[bubble['year'] <= yr]
    traces = []
    for z in zone_order:
        sub = sub_all[sub_all['zone'] == z]
        # anchor point (invisible) keeps the zone on the y-axis from frame 1
        x_vals = [years[0] - 2] + sub['year'].tolist()
        y_vals = [z] + [z] * len(sub)
        size_vals = [0] + sub['days'].tolist()
        custom_vals = [None] + sub['days'].tolist()
        traces.append(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode='markers',
            marker=dict(
                size=size_vals,
                sizemode='area',
                sizeref=sizeref,
                sizemin=0,
                color=zone_colors[z],
                opacity=0.8,
                line=dict(color='white', width=0.5),
            ),
            name=z,
            customdata=custom_vals,
            hovertemplate='<b>%{x}</b><br>' + z + ': %{customdata} days<extra></extra>',
            showlegend=False,
        ))
    return traces

frames = [
    go.Frame(data=traces_up_to(yr), name=str(yr))
    for yr in years
]

milestone_vlines = [
    (1970, "Clean Energy Act<br>passes"),
    (1977, "Clean Energy Act<br>amendments"),
    (1990, "Catalytic converter<br>requirements"),
    (2007, "Diesel standards<br>tightened"),
    (2020, "COVID"),
]

fig = go.Figure(data=traces_up_to(years[0]), frames=frames)

for xval, label in milestone_vlines:
    fig.add_vline(x=xval, line=dict(color='#aaa', width=1, dash='dot'))
    fig.add_annotation(
        x=xval, y=-0.08, yref='paper', yanchor='top',
        text=label, showarrow=False,
        font=dict(size=9, color='#555'),
        bgcolor='rgba(255,255,255,0.75)',
        borderpad=2, xanchor='center',
    )

fig.update_layout(
    title=dict(
        text='<b>NYC Metro — Days per Air Quality Index (AQI) Zone per Year (1970–2026)</b><br>'
             '<sup>Bubble size = number of days in that zone · EPA Air Quality System</sup>',
        x=0.5, xanchor='center', font_size=17,
    ),
    xaxis=dict(title='', range=[years[0] - 1, years[-1] + 1], dtick=5, showgrid=True, gridcolor='#eee'),
    yaxis=dict(title='', categoryorder='array', categoryarray=zone_order, showgrid=True, gridcolor='#eee'),
    plot_bgcolor='white', paper_bgcolor='white',
    showlegend=False,
    margin=dict(l=240, r=40, t=100, b=100),
    width=1100, height=480,
    updatemenus=[dict(
        type='buttons', showactive=False,
        y=1.1, x=0.5, xanchor='center',
        buttons=[
            dict(label='▶ Play', method='animate',
                 args=[None, dict(frame=dict(duration=100, redraw=True),
                                  fromcurrent=True, transition=dict(duration=0))]),
            dict(label='⏸ Pause', method='animate',
                 args=[[None], dict(frame=dict(duration=0, redraw=False),
                                    mode='immediate', transition=dict(duration=0))]),
        ],
    )],
)

fig.write_html(OUT, include_plotlyjs='cdn')

# Inject loop JS — restart animation when last frame ends
last_year = str(years[-1])
loop_js = f"""
<script>
(function() {{
  var el = document.getElementsByClassName('plotly-graph-div')[0];
  el.on('plotly_animatingframe', function(e) {{
    if (e.name === '{last_year}') {{
      setTimeout(function() {{
        Plotly.animate(el, null, {{
          frame: {{duration: 100, redraw: true}},
          transition: {{duration: 0}},
          fromcurrent: false,
          mode: 'immediate'
        }});
      }}, 1000);
    }}
  }});
}})();
</script>
"""
with open(OUT, 'r') as f:
    html = f.read()
with open(OUT, 'w') as f:
    f.write(html.replace('</body>', loop_js + '</body>'))

print(f"Saved: {OUT} — {len(years)} frames × 0.1s = {len(years)*0.1:.1f}s")
