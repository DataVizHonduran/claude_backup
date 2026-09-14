import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from PIL import Image
import io

CSV = '/Users/macproajb/claude_projects/noaa_client/AQI_NYC_composite_daily.csv'
OUT = '/Users/macproajb/claude_projects/noaa_client/AQI_NYC_bubble_animated.gif'

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
    'Good (0–50)':                           '#00e400',
    'Moderate (51–100)':                     '#ffcc00',
    'Unhealthy for\nSensitive Groups\n(101–150)': '#ff7e00',
    'Unhealthy (151–200)':                   '#ff0000',
    'Very Unhealthy\n(201–300)':             '#8f3f97',
    'Hazardous (301+)':                      '#7e0023',
}

df['zone'] = df['aqi'].apply(zone)
bubble = df.groupby(['year', 'zone']).size().reset_index(name='days')
years = sorted(df['year'].unique())

max_days = bubble['days'].max()
# scale: max bubble ~1800 pts^2 area → radius = sqrt(area/pi)
scale = 1800 / max_days

milestones = [
    (1970, "Clean Energy\nAct passes"),
    (1977, "Clean Energy\nAct amendments"),
    (1990, "Catalytic converter\nrequirements"),
    (2007, "Diesel standards\ntightened"),
    (2020, "COVID"),
]

frames = []
for i, yr in enumerate(years):
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    sub = bubble[bubble['year'] <= yr]

    for z in zone_order:
        zdata = sub[sub['zone'] == z]
        if zdata.empty:
            continue
        y_pos = zone_order.index(z)
        for _, row in zdata.iterrows():
            size = row['days'] * scale
            ax.scatter(row['year'], y_pos, s=size,
                       color=zone_colors[z], alpha=0.82,
                       edgecolors='white', linewidths=0.6, zorder=3)

    # milestone lines
    for xval, label in milestones:
        if xval <= yr:
            ax.axvline(xval, color='#aaa', linewidth=0.8, linestyle='--', zorder=1)

    ax.set_xlim(years[0] - 1, years[-1] + 1)
    ax.set_ylim(-0.7, len(zone_order) - 0.3)
    ax.set_yticks(range(len(zone_order)))
    ax.set_yticklabels(zone_order, fontsize=8)
    ax.set_xticks([y for y in years if y % 5 == 0])
    ax.tick_params(axis='x', labelsize=9)
    ax.grid(axis='x', color='#eee', linewidth=0.5, zorder=0)
    ax.spines[['top', 'right']].set_visible(False)

    ax.set_title(
        'NYC Metro — Days per Air Quality Index (AQI) Zone per Year (1970–2026)\n'
        'Bubble size = days in that zone · EPA Air Quality System',
        fontsize=11, pad=10,
    )

    # current year watermark
    ax.text(0.98, 0.04, str(yr), transform=ax.transAxes,
            fontsize=40, color='#e8e8e8', ha='right', va='bottom', fontweight='bold')

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    frames.append(Image.open(buf).copy())
    buf.close()

    if i % 10 == 0:
        print(f"  frame {i+1}/{len(years)} ({yr})", flush=True)

# hold last frame for 1 second (10 extra copies at 100ms)
frames += [frames[-1]] * 10

print("Saving GIF...", flush=True)
frames[0].save(
    OUT,
    save_all=True,
    append_images=frames[1:],
    duration=100,       # 0.1s per frame
    loop=0,             # loop forever
    optimize=False,
)
print(f"Saved: {OUT}")
print(f"Size: {__import__('os').path.getsize(OUT) / 1024 / 1024:.1f} MB")
