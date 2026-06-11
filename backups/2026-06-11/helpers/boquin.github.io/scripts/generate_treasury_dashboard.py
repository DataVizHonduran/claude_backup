"""
Daily US Treasury Yield Curve Analysis for GitHub Actions
Uses FRED API via fredapi for reliable data access
"""

import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from fredapi import Fred

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
API_KEY = os.environ.get('FRED_API_KEY')
if not API_KEY:
    raise ValueError("FRED_API_KEY environment variable is not set")

fred = Fred(api_key=API_KEY)

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'reports', 'treasury-dashboard', 'index.html'
)


def get_treasury_data(years=2):
    """
    Fetches Treasury yields using the fredapi wrapper.
    """
    series_map = {
        '2Y': 'DGS2',
        '5Y': 'DGS5',
        '10Y': 'DGS10',
        '30Y': 'DGS30'
    }

    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * years)

    data_frames = []

    for name, s_id in series_map.items():
        s = fred.get_series(s_id, observation_start=start_date)
        df_s = s.to_frame(name=name)
        data_frames.append(df_s)

    if not data_frames:
        return pd.DataFrame()

    df = pd.concat(data_frames, axis=1)
    df.ffill(inplace=True)
    return df.dropna()


def plot_curve(df, n_days=90):
    """
    Generates a 4-pane interactive visualization of the yield environment.
    """
    stats = pd.DataFrame({
        'Current': df.iloc[-1],
        'Min': df.tail(n_days).min(),
        'Max': df.tail(n_days).max()
    })

    maturities = ['2Y', '5Y', '10Y', '30Y']
    current_yields = [stats['Current'][m] for m in maturities]

    fig = make_subplots(
        rows=2, cols=2,
        vertical_spacing=0.15,
        horizontal_spacing=0.1,
        subplot_titles=(
            'Current Yield Curve',
            'Historical Yields (1Y)',
            'Spreads: 2s10s & 5s30s',
            f'Current vs {n_days}D Range'
        )
    )

    # 1. Current Yield Curve
    fig.add_trace(go.Scatter(
        x=maturities, y=current_yields,
        mode='lines+markers+text',
        text=[f'{y:.2f}%' for y in current_yields],
        textposition='top center',
        line=dict(width=4, color='#1f77b4'),
        name='Current'
    ), row=1, col=1)

    # 2. Historical Yields (Last 252 trading days)
    for m in maturities:
        fig.add_trace(go.Scatter(
            x=df.tail(252).index,
            y=df[m].tail(252),
            name=m,
            opacity=0.8
        ), row=1, col=2)

    # 3. Yield Spreads (Term Premium Proxy)
    s2s10s = (df['10Y'] - df['2Y']).tail(252)
    s5s30s = (df['30Y'] - df['5Y']).tail(252)

    fig.add_trace(go.Scatter(x=s2s10s.index, y=s2s10s, name='2s10s', line=dict(color='#d62728')), row=2, col=1)
    fig.add_trace(go.Scatter(x=s5s30s.index, y=s5s30s, name='5s30s', line=dict(color='#2ca02c')), row=2, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="black", row=2, col=1)

    # 4. Current vs Range
    for col, color in zip(['Min', 'Current', 'Max'], ['#aec7e8', '#1f77b4', '#ff7f0e']):
        fig.add_trace(go.Scatter(
            x=maturities,
            y=stats[col],
            mode='lines+markers',
            name=col,
            line=dict(color=color, dash='dot' if col != 'Current' else 'solid')
        ), row=2, col=2)

    fig.update_layout(
        height=900,
        template='plotly_white',
        title_text="U.S. Treasury Yield Analysis",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    fig.update_yaxes(ticksuffix="%")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    fig.write_html(OUTPUT_PATH)
    print(f"✅ Dashboard saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        data = get_treasury_data()
        if not data.empty:
            plot_curve(data)
        else:
            print("No data retrieved. Check your API key.")
    except Exception as e:
        print(f"An error occurred: {e}")
        raise
