import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

CSV = '/Users/macproajb/claude_projects/noaa_client/AQI_NYC_composite_daily.csv'
OUT = '/Users/macproajb/claude_projects/noaa_client/AQI_NYC_bubble_static.png'

df = pd.read_csv(CSV, parse_dates=['date'])
df['year'] = df['date'].dt.year

def zone(v):
    if v <= 50:  return 'Good (0–50)'
    if v <= 100: return 'Moderate (51–100)'
    if v <= 150: return 'Unhealthy for\nSensitive Groups\n(101–150)'
    if v <= 200: return 'Unhealthy (151–200)'
    if v <= 300: return 'Very Unhealthy\n(201–300)'
    return 'Hazardous (301+)'

zone_order = [
    'Good (0–50)',
    'Moderate (51–100)',
    'Unhealthy for\nSensitive Groups\n(101–150)',
    'Unhealthy (151–200)',
    'Very Unhealthy\n(201–300)',
    'Hazardous (301+)',
]
zone_colors = {
    'Good (0–50)':                                '#00e400',
    'Moderate (51–100)':                          '#ffcc00',
    'Unhealthy for\nSensitive Groups\n(101–150)': '#ff7e00',
    'Unhealthy (151–200)':                        '#ff0000',
    'Very Unhealthy\n(201–300)':                  '#8f3f97',
    'Hazardous (301+)':                           '#7e0023',
}

df['zone'] = df['aqi'].apply(zone)
bubble = df.groupby(['year', 'zone']).size().reset_index(name='days')
years = sorted(df['year'].unique())
max_days = bubble['days'].max()
scale = 2200 / max_days  # max bubble area

fig, ax = plt.subplots(figsize=(18, 7))
fig.patch.set_facecolor('white')
ax.set_facecolor('white')

for z in zone_order:
    zdata = bubble[bubble['zone'] == z]
    y_pos = zone_order.index(z)
    for _, row in zdata.iterrows():
        ax.scatter(row['year'], y_pos, s=row['days'] * scale,
                   color=zone_colors[z], alpha=0.82,
                   edgecolors='white', linewidths=0.8, zorder=3)

milestones = [
    (1970, "Clean Energy\nAct passes"),
    (1977, "Clean Energy Act\namendments"),
    (1990, "Catalytic converter\nrequirements"),
    (2007, "Diesel standards\ntightened"),
    (2020, "COVID"),
]
for xval, label in milestones:
    ax.axvline(xval, color='#bbb', linewidth=1, linestyle='--', zorder=1)
    ax.text(xval + 0.3, -1.0, label, fontsize=8, color='#666',
            va='top', ha='left', linespacing=1.4)

ax.set_xlim(years[0] - 1.5, years[-1] + 1.5)
ax.set_ylim(-1.8, len(zone_order) - 0.3)
ax.set_yticks(range(len(zone_order)))
ax.set_yticklabels(zone_order, fontsize=10, linespacing=1.3)
ax.set_xticks([y for y in years if y % 5 == 0])
ax.tick_params(axis='x', labelsize=10)
ax.grid(axis='x', color='#eee', linewidth=0.6, zorder=0)
ax.grid(axis='y', color='#f5f5f5', linewidth=0.6, zorder=0)
ax.spines[['top', 'right', 'left']].set_visible(False)
ax.spines['bottom'].set_color('#ccc')

ax.set_title(
    'NYC Metro — Days per Air Quality Index (AQI) Zone per Year (1970–2026)',
    fontsize=16, fontweight='bold', pad=16,
)
ax.text(0.5, 1.01,
        'Bubble size = days in that zone · EPA Air Quality System',
        transform=ax.transAxes, ha='center', fontsize=10, color='#666')

plt.tight_layout(rect=[0, 0.05, 1, 1])
fig.savefig(OUT, dpi=180, bbox_inches='tight', facecolor='white')
plt.close()
print(f"Saved: {OUT}")
