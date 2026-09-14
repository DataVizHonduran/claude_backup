"""
US Leading Economic Indicators Dashboard
Adapted from DataVizHonduran/us-leading-indicators for boquin.github.io.

Uses fredapi (not pandas_datareader) — set FRED_API_KEY env var.

Generates an 8-panel dashboard of cyclical leading indicators with
NBER recession shading. Output: reports/leading-indicators/index.html
"""

import os
import time
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from fredapi import Fred

OUTPUT_PATH  = "reports/leading-indicators/index.html"
START_DATE   = "1956-01-01"
FRED_API_KEY = os.environ.get('FRED_API_KEY')
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set.")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
fred = Fred(api_key=FRED_API_KEY)


def get_fred(series_id, years=10, retries=3, delay=10):
    start = date.today() - relativedelta(years=years)
    for attempt in range(retries):
        try:
            return fred.get_series(series_id, observation_start=start).dropna()
        except Exception as e:
            if attempt < retries - 1:
                print(f"  ⚠️  {series_id}: {e} — retry {attempt + 1}/{retries - 1}")
                time.sleep(delay)
            else:
                raise


def get_fred_multi(series_ids, years=10, retries=3, delay=10):
    start = date.today() - relativedelta(years=years)
    frames = {}
    for sid in series_ids:
        for attempt in range(retries):
            try:
                frames[sid] = fred.get_series(sid, observation_start=start).dropna()
                break
            except Exception as e:
                if attempt < retries - 1:
                    print(f"  ⚠️  {sid}: {e} — retry {attempt + 1}/{retries - 1}")
                    time.sleep(delay)
                else:
                    print(f"  ⚠️  {sid}: {e} — giving up after {retries} attempts")
    return pd.DataFrame(frames)


def add_recession_shading(fig, recession, row, col, y0, y1):
    """Overlay NBER recession bars on a subplot."""
    in_rec = False
    rec_start = None
    for dt, val in recession.items():
        if val == 1 and not in_rec:
            in_rec = True
            rec_start = dt
        elif val == 0 and in_rec:
            in_rec = False
            fig.add_shape(
                type="rect",
                x0=rec_start, x1=dt,
                y0=y0, y1=y1,
                fillcolor="lightgray", opacity=0.5,
                line_width=0, layer="below",
                row=row, col=col
            )
    # Close any open recession at end of data
    if in_rec:
        fig.add_shape(
            type="rect",
            x0=rec_start, x1=recession.index[-1],
            y0=y0, y1=y1,
            fillcolor="lightgray", opacity=0.5,
            line_width=0, layer="below",
            row=row, col=col
        )


def plot_series(fig, row, col, series, recession, y0, y1,
                color='#1f77b4', quantile_line=0.2, y_label=''):
    """Plot a series with optional 20th-pct dashed line and recession shading."""
    series = series.dropna()

    fig.add_trace(go.Scatter(
        x=series.index, y=series.values,
        mode='lines', showlegend=False,
        line=dict(color=color, width=1.8),
    ), row=row, col=col)

    if quantile_line is not None:
        q = series.quantile(quantile_line)
        fig.add_trace(go.Scatter(
            x=series.index, y=[q] * len(series),
            mode='lines', showlegend=False,
            name=f'{int(quantile_line*100)}th pct',
            line=dict(dash='dash', color='gray', width=1),
        ), row=row, col=col)

    add_recession_shading(fig, recession, row, col, y0, y1)
    fig.update_yaxes(range=[y0, y1], title_text=y_label,
                     title_font=dict(size=11), row=row, col=col)
    fig.update_xaxes(title_text='Date', title_font=dict(size=11), row=row, col=col)


def create_dashboard():
    print("Fetching NBER recession data...")
    recession = get_fred("USREC", years=100)

    fig = make_subplots(
        rows=6, cols=2,
        subplot_titles=[
            "Payrolls Diffusion Index (3mma)",
            "Employment-to-Population from 24-Month High (All 16+ vs 25–54)",
            "Continuing Claims — % Above 3-Year Low (Inverted)",
            "New Orders from 24-Month High",
            "Building Permits as % of 24-Month High",
            "Mfg Orders-to-Inventories from 24-Month High",
            "Consumer & Activity Diffusion Index (YoY, 3mma)",
            "Payrolls: Cumulative 3M MA − 36M MA Gap (Since 1955)",
            "Capex Shipments: Nondefense ex Aircraft, NSA (YoY %)",
            "Full-Time vs Part-Time Employment Spread (3M/12M Rolling Sum)",
            "Construction + Manufacturing Jobs: % Below 24-Month Peak",
            "Residential Fixed Investment vs Prior 12Q Max",
        ],
        vertical_spacing=0.08,
        horizontal_spacing=0.08,
    )

    # ── Chart 1: Payrolls Diffusion Index ────────────────────────────────────
    print("Chart 1: Payrolls Diffusion Index...")
    payroll_ids = [
        "PAYEMS", "USPRIV", "USGOOD", "SRVPRD", "USMINE", "USCONS",
        "MANEMP", "DMANEMP", "NDMANEMP", "USTPU", "USWTRADE", "USTRADE",
        "CES4348400001", "CES4422000001", "USINFO", "USFIRE",
        "USPBS", "USEHS", "USLAH", "USSERV", "USGOVT",
    ]
    df1 = get_fred_multi(payroll_ids, years=100)
    rising = df1.diff().gt(0).astype(int)
    diffusion1 = (rising.sum(axis=1) / rising.shape[1] * 100).rolling(3).mean().dropna()
    plot_series(fig, 1, 1, diffusion1, recession, 0, 100, y_label='% of Industries Rising')
    bls_diff = get_fred("SMS00000000000000021", years=100).rolling(3).mean().dropna()
    fig.add_trace(go.Scatter(
        x=bls_diff.index, y=bls_diff.values,
        mode='lines', showlegend=True,
        name='BLS Official (3M MA)',
        line=dict(color='#e67e22', width=1.6),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=diffusion1.index, y=diffusion1.values,
        mode='lines', showlegend=True,
        name='21-Series Custom (3M MA)',
        line=dict(color='#1f77b4', width=1.8),
    ), row=1, col=1)

    # ── Chart 2: EPOP from 24-month high ─────────────────────────────────────
    print("Chart 2: Employment-to-Population Ratio...")
    epop = get_fred("EMRATIO", years=100)
    epop_rel = (epop - epop.rolling(24).max()).dropna()
    epop25 = get_fred("LNS12300060", years=100)
    epop25_rel = (epop25 - epop25.rolling(24).max()).dropna()
    plot_series(fig, 1, 2, epop_rel, recession, -4, 0, y_label='pp vs 24M High')
    # Overlay prime-age (25-54) EPOP as a second line
    fig.add_trace(go.Scatter(
        x=epop25_rel.index, y=epop25_rel.values,
        mode='lines', showlegend=True,
        name='25–54',
        line=dict(color='#e67e22', width=1.6),
    ), row=1, col=2)
    # Legend entry for the blue All 16+ line (plot_series draws it with showlegend=False)
    fig.add_trace(go.Scatter(
        x=epop_rel.index, y=epop_rel.values,
        mode='lines', showlegend=True,
        name='All 16+',
        line=dict(color='#1f77b4', width=1.8),
    ), row=1, col=2)

    # ── Chart 3: Continuing Claims (inverted) ─────────────────────────────────
    print("Chart 3: Continuing Claims...")
    cc = get_fred("CCSA", years=100)
    cc_rel = (100 - 100 * (cc / cc.rolling(156).min() - 1)).dropna()
    plot_series(fig, 2, 1, cc_rel, recession, 0, 100, y_label='% Above 3Y Low (Inverted)')

    # ── Chart 4: New Orders from 24-month high ────────────────────────────────
    print("Chart 4: New Orders...")
    no = get_fred("NEWORDER", years=75)
    no_rel = (no / no.rolling(24).max()).dropna()
    plot_series(fig, 2, 2, no_rel, recession, 0.65, 1.02, y_label='Ratio vs 24M High')

    # ── Chart 5: Building Permits ─────────────────────────────────────────────
    print("Chart 5: Building Permits...")
    permits = get_fred("PERMIT", years=75)
    permits_rel = (permits / permits.rolling(24).max()).dropna()
    plot_series(fig, 3, 1, permits_rel, recession, 0.4, 1.02, y_label='Ratio vs 24M High')

    # ── Chart 6: Mfg Orders-to-Inventories ───────────────────────────────────
    print("Chart 6: Mfg Orders-to-Inventories...")
    mfg = get_fred_multi(["AMTMNO", "AMTMTI"], years=75)
    ratio = mfg["AMTMNO"] / mfg["AMTMTI"]
    ratio_rel = (ratio / ratio.rolling(24).max()).dropna()
    plot_series(fig, 3, 2, ratio_rel, recession, 0.7, 1.02, y_label='Ratio vs 24M High')

    # ── Chart 7: Consumer & Activity Diffusion Index ─────────────────────────
    # YoY % change > 0 across 8 consumer/activity series = broad spending health
    print("Chart 7: Consumer & Activity Diffusion Index...")
    consumer_ids = {
        "RSAFS":    "Retail Sales",
        "PCEC96":   "Real PCE",
        "DSPIC96":  "Real Disposable Income",
        "UMCSENT":  "UMich Sentiment",
        "AHETPI":   "Avg Hourly Earnings",
        "HOUST":    "Housing Starts",
        "INDPRO":   "Industrial Production",
        "CPILFESL": "Core CPI",
    }
    con_df  = get_fred_multi(list(consumer_ids.keys()), years=75)
    con_yoy = con_df.pct_change(12) * 100
    diffusion7 = ((con_yoy > 0).sum(axis=1) / con_yoy.count(axis=1) * 100
                  ).rolling(3).mean().dropna()
    plot_series(fig, 4, 1, diffusion7, recession, 0, 100, y_label='% of Series with Positive YoY')

    # ── Chart 8: Payrolls Cumulative 3M MA − 36M MA Gap ──────────────────────
    print("Chart 8: Payrolls Cumulative Gap (3M MA − 36M MA)...")
    payems = get_fred("PAYEMS", years=75)
    mom8   = payems.diff()
    ma3_8  = mom8.rolling(3).mean()
    ma36_8 = mom8.rolling(36).mean()
    cumgap8 = (ma3_8 - ma36_8).dropna().cumsum()
    cumgap8 = cumgap8[START_DATE:]

    # COVID crop (Feb 2020–Feb 2022) for y-axis range
    covid_mask8 = (
        (cumgap8.index >= pd.Timestamp('2020-02-01')) &
        (cumgap8.index <= pd.Timestamp('2022-02-01'))
    )
    non_covid8 = cumgap8[~covid_mask8]
    y0_8 = non_covid8.min() - 500
    y1_8 = non_covid8.max() + 500

    fig.add_trace(go.Scatter(
        x=cumgap8.index, y=cumgap8.clip(lower=0).values,
        fill='tozeroy', fillcolor='rgba(31,119,180,0.25)',
        line=dict(width=0), showlegend=False, hoverinfo='skip',
    ), row=4, col=2)
    fig.add_trace(go.Scatter(
        x=cumgap8.index, y=cumgap8.clip(upper=0).values,
        fill='tozeroy', fillcolor='rgba(214,39,40,0.20)',
        line=dict(width=0), showlegend=False, hoverinfo='skip',
    ), row=4, col=2)
    fig.add_trace(go.Scatter(
        x=cumgap8.index, y=cumgap8.values,
        mode='lines', showlegend=False,
        line=dict(color='#1f77b4', width=1.8),
        hovertemplate='%{x|%b %Y}<br><b>Cumulative gap: %{y:+,.0f}k</b><extra></extra>',
    ), row=4, col=2)
    fig.add_hline(y=0, line_color='black', line_width=1, row=4, col=2)
    add_recession_shading(fig, recession, 4, 2, y0_8, y1_8)
    fig.update_yaxes(range=[y0_8, y1_8], title_text='Cumulative Gap (Thousands)',
                     title_font=dict(size=11), row=4, col=2)
    fig.update_xaxes(title_text='Date', title_font=dict(size=11), row=4, col=2)

    # ── Chart 9: Capex Shipments — Nondefense ex Aircraft (YoY %) ────────────
    print("Chart 9: Capex Shipments (NonDef ex-Aircraft, NSA YoY%)...")
    capex_raw = get_fred("UNXAVS", years=100)
    capex_yoy = (capex_raw.pct_change(12) * 100).dropna()
    plot_series(fig, 5, 1, capex_yoy, recession, -25, 22,
                color='#1f77b4', quantile_line=None,
                y_label='YoY % Change')
    fig.add_hline(y=0, line_color='black', line_width=1, row=5, col=1)

    # ── Chart 10: Full-Time vs Part-Time Employment Spread ───────────────────
    print("Chart 10: Full-Time vs Part-Time Employment Spread...")
    ft = get_fred("LNS12500000", years=100)
    pt = get_fred("LNS12600000", years=100)
    ft_chg = ft.diff()
    pt_chg = pt.diff()
    spread_3m  = ft_chg.rolling(3).sum()  - pt_chg.rolling(3).sum()
    spread_12m = ft_chg.rolling(12).sum() - pt_chg.rolling(12).sum()
    spread_3m  = spread_3m.dropna()
    spread_12m = spread_12m.dropna()
    # COVID crop for y-axis range (use 3M series which is noisier)
    covid_mask10 = (
        (spread_3m.index >= pd.Timestamp('2020-02-01')) &
        (spread_3m.index <= pd.Timestamp('2022-02-01'))
    )
    non_covid10 = spread_3m[~covid_mask10]
    y0_10 = non_covid10.min() * 1.20
    y1_10 = non_covid10.max() * 1.20
    colors10 = ['rgba(34,139,34,0.65)' if v >= 0 else 'rgba(200,30,30,0.65)'
                for v in spread_3m.values]
    fig.add_trace(go.Bar(
        x=spread_3m.index, y=spread_3m.values,
        marker_color=colors10, showlegend=False,
        hovertemplate='%{x|%b %Y}<br><b>3M spread: %{y:+,.0f}k</b><extra></extra>',
    ), row=5, col=2)
    fig.add_trace(go.Scatter(
        x=spread_12m.index, y=spread_12m.values,
        mode='lines', showlegend=False,
        line=dict(color='#1f77b4', width=1.8),
        hovertemplate='%{x|%b %Y}<br><b>12M spread: %{y:+,.0f}k</b><extra></extra>',
    ), row=5, col=2)
    fig.add_hline(y=0, line_color='black', line_width=1, row=5, col=2)
    add_recession_shading(fig, recession, 5, 2, y0_10, y1_10)
    fig.update_yaxes(range=[y0_10, y1_10], title_text='Thousands (FT \u2212 PT)',
                     title_font=dict(size=11), row=5, col=2)
    fig.update_xaxes(title_text='Date', title_font=dict(size=11), row=5, col=2)

    # ── Chart 11: Construction + Manufacturing Jobs % from 24-Month Peak ────────
    print("Chart 11: Construction + Manufacturing Jobs % from 24-Month Peak...")
    cons = get_fred("USCONS", years=100)
    mfg  = get_fred("MANEMP", years=100)
    combined11 = (cons + mfg).dropna()
    peak_24m11 = combined11.rolling(24).max()
    pct_from_peak11 = ((combined11 / peak_24m11) - 1) * 100
    pct_from_peak11 = pct_from_peak11.dropna()

    # Drawdown fill below zero
    fig.add_trace(go.Scatter(
        x=pct_from_peak11.index,
        y=pct_from_peak11.clip(upper=0).values,
        fill='tozeroy', fillcolor='rgba(214,39,40,0.20)',
        line=dict(width=0), showlegend=False, hoverinfo='skip',
    ), row=6, col=1)
    # Main line
    fig.add_trace(go.Scatter(
        x=pct_from_peak11.index, y=pct_from_peak11.values,
        mode='lines', showlegend=False,
        line=dict(color='#1f77b4', width=1.8),
        hovertemplate='%{x|%b %Y}: %{y:.2f}%<extra></extra>',
    ), row=6, col=1)
    fig.add_hline(y=0, line_color='black', line_width=1, row=6, col=1)
    add_recession_shading(fig, recession, 6, 1, -26, 1)
    fig.update_yaxes(range=[-26, 1], title_text='% Below 24M Peak',
                     title_font=dict(size=11), row=6, col=1)
    fig.update_xaxes(title_text='Date', title_font=dict(size=11), row=6, col=1)

    # ── Chart 12: Real Gross Domestic Income (YoY %) ─────────────────────────
    print("Chart 12: Residential Fixed Investment vs Prior 12Q Max...")
    rfi_raw = get_fred("A011RE1Q156NBEA", years=100)
    prior_12q_max = rfi_raw.rolling(12).max().shift(1)
    rfi_rel = (rfi_raw - prior_12q_max).dropna()
    plot_series(fig, 6, 2, rfi_rel, recession,
                rfi_rel.min() * 1.1, rfi_rel.max() * 1.1,
                color='#1f77b4', quantile_line=None,
                y_label='Actual − Prior 12Q Max (Bil. $)')

    # ── Layout ────────────────────────────────────────────────────────────────
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    fig.update_layout(
        title=dict(
            text="US Leading Economic Indicators",
            x=0.5, xanchor='center',
            font=dict(size=22, color='#1a1a2e')
        ),
        height=2520,
        showlegend=True,
        legend=dict(x=0.55, y=0.805, xanchor='left', bgcolor='rgba(255,255,255,0.7)',
                    bordercolor='lightgray', borderwidth=1, font=dict(size=11)),
        template='plotly_white',
        margin=dict(t=100, l=55, r=40, b=60),
    )
    # Resize all subplot titles (must run before add_annotation for footer)
    fig.update_annotations(font_size=13, font_color='#1a1a2e')
    # Add footer last so it isn't affected by the bulk update above
    fig.add_annotation(
        text=(f'Last Updated: {update_time} | '
              'Source: FRED (St. Louis Fed) | Gray shading = NBER recessions'),
        xref='paper', yref='paper',
        x=0.5, y=-0.02,
        showarrow=False,
        font=dict(size=11, color='gray'),
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#eeeeee',
                     range=[START_DATE, datetime.today().strftime('%Y-%m-%d')])
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#eeeeee')

    return fig


def main():
    print("=" * 60)
    print("US Leading Indicators Dashboard")
    print("=" * 60)
    fig = create_dashboard()
    fig.write_html(
        OUTPUT_PATH,
        config={'displayModeBar': True, 'displaylogo': False},
    )
    print(f"\n✅ Dashboard saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

