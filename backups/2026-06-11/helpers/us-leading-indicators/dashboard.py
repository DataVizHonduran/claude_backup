import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pandas_datareader import data
from datetime import datetime, date, timedelta

def get_fred(dataseries, years=5):
    '''Get data from Fred database. Return df.'''
    end_date = date.today()
    start_date = end_date - timedelta(days=365*years)
    df = data.DataReader(dataseries, 'fred', start_date, end_date)
    return df

def plot_diffusion_index_to_fig(fig, row, col, diffusion_index, recession_data, x0, x1, y0, y1, title):
    """Add a diffusion index plot to a subplot"""
    fig.add_trace(go.Scatter(
        x=diffusion_index.index,
        y=diffusion_index.values,
        mode='lines',
        name=title,
        line=dict(color='blue'),
        showlegend=False
    ), row=row, col=col)
    
    fig.add_trace(go.Scatter(
        x=diffusion_index.index,
        y=[diffusion_index.quantile(.2)] * len(diffusion_index),
        mode='lines',
        name='20% quantile',
        line=dict(dash='dash', color='gray'),
        showlegend=False
    ), row=row, col=col)
    
    # Add recession shading
    for date_val, value in recession_data["USREC"].items():
        if value == 1:
            fig.add_shape(
                type="rect",
                x0=date_val,
                x1=date_val + pd.offsets.MonthEnd(0),
                y0=y0,
                y1=y1,
                fillcolor="lightgray",
                opacity=0.7,
                line_width=0,
                layer="below",
                row=row, col=col
            )
    
    fig.update_xaxes(range=[x0, x1], row=row, col=col)
    fig.update_yaxes(range=[y0, y1], row=row, col=col)

def create_dashboard():
    """Generate all indicators and combine into one dashboard"""
    
    # Get recession data (used by all charts)
    recession_data = get_fred("USREC", 100).dropna()
    x1 = pd.Timestamp("2040-12-31")
    
    # Create subplots - 4 rows x 2 columns = 8 charts
    fig = make_subplots(
        rows=4, cols=2,
        subplot_titles=[
            "Payrolls Diffusion Index (3mma)",
            "EPOP from 24-month high",
            "Continuing Claims (inverted)",
            "New Orders from 24-month highs",
            "Building Permits as % of 24-Month High",
            "Mfg Orders to Inventories from 24-Month High",
            "Diffusion Index of PCE Spending Categories (yoy growth)",
            "Cyclical Hiring (6mma Job Creation, '000)"
        ],
        vertical_spacing=0.1,
        horizontal_spacing=0.1
    )
    
    # ===== CHART 1: Payrolls Diffusion Index =====
    print("Processing Chart 1: Payrolls Diffusion Index...")
    industry_series = {
        "Total Nonfarm": "PAYEMS",
        "Total Private": "USPRIV",
        "Goods-Producing": "USGOOD",
        "Service-Providing": "SRVPRD",
        "Mining and Logging": "USMINE",
        "Construction": "USCONS",
        "Manufacturing": "MANEMP",
        "Durable Goods": "DMANEMP",
        "Nondurable Goods": "NDMANEMP",
        "Trade, Transportation, and Utilities": "USTPU",
        "Wholesale Trade": "USWTRADE",
        "Retail Trade": "USTRADE",
        "Transportation and Warehousing": "CES4348400001",
        "Utilities": "CES4422000001",
        "Information": "USINFO",
        "Financial Activities": "USFIRE",
        "Professional and Business Services": "USPBS",
        "Education and Health Services": "USEHS",
        "Leisure and Hospitality": "USLAH",
        "Other Services": "USSERV",
        "Government": "USGOVT"
    }
    data_df = get_fred(list(industry_series.values()), 100)
    monthly_diff = data_df.diff()
    rising = monthly_diff.gt(0).astype(int)
    diffusion_index = rising.sum(axis=1) / rising.shape[1] * 100
    diffusion_index = diffusion_index.rolling(3).mean()
    x0 = diffusion_index.index.min()
    plot_diffusion_index_to_fig(fig, 1, 1, diffusion_index, recession_data, x0, x1, 0, 100,
                                "Payrolls Diffusion Index (3mma)")
    
    # ===== CHART 2: EPOP from 24-month high =====
    print("Processing Chart 2: EPOP...")
    diffusion_index = get_fred("EMRATIO", 100)["EMRATIO"].dropna()
    n_months = 24
    diffusion_index = (diffusion_index - diffusion_index.rolling(n_months).max())
    x0 = diffusion_index.index.min()
    plot_diffusion_index_to_fig(fig, 1, 2, diffusion_index, recession_data, x0, x1, -4, 0,
                                f"EPOP from {n_months}-month high")
    
    # ===== CHART 3: Continuing Claims =====
    print("Processing Chart 3: Continuing Claims...")
    continuing_claims = get_fred("CCSA", 100)["CCSA"]
    cc_min = continuing_claims.rolling(156).min()
    continuing_claims = 100 - (100 * (continuing_claims / cc_min - 1))
    x0 = continuing_claims.index.min()
    plot_diffusion_index_to_fig(fig, 2, 1, continuing_claims, recession_data, x0, x1, 0, 100,
                                "% Above 3-year Lows in Continuing Claims (inverted)")
    
    # ===== CHART 4: New Orders =====
    print("Processing Chart 4: New Orders...")
    new_order = get_fred("NEWORDER", 50)["NEWORDER"]
    n_month = 24
    new_order = new_order / new_order.rolling(n_month).max()
    x0 = new_order.index.min()
    plot_diffusion_index_to_fig(fig, 2, 2, new_order, recession_data, x0, x1, 0.65, 1,
                                f"New Orders from {n_month} highs")
    
    # ===== CHART 5: Building Permits =====
    print("Processing Chart 5: Building Permits...")
    permits = get_fred("PERMIT", 50)["PERMIT"]
    n_month = 24
    permits = (permits / permits.rolling(n_month).max())
    x0 = permits.index.min()
    plot_diffusion_index_to_fig(fig, 3, 1, permits, recession_data, x0, x1, 0.4, 1,
                                f"Building Permits as % of {n_month}-Month High")
    
    # ===== CHART 6: Mfg Orders to Inventories =====
    print("Processing Chart 6: Mfg Orders to Inventories...")
    item = ["AMTMNO", "AMTMTI"]
    n_month = 24
    mfg_data = get_fred(item, 50)
    ratio = mfg_data["AMTMNO"] / mfg_data["AMTMTI"]
    ratio2 = ratio / ratio.rolling(n_month).max()
    x0 = mfg_data.index.min()
    plot_diffusion_index_to_fig(fig, 3, 2, ratio2, recession_data, x0, x1, 0.7, 1,
                                f"Mfg Orders to Inventories from {n_month}-Month High")
    
    # ===== CHART 7: PCE Spending Diffusion =====
    print("Processing Chart 7: PCE Spending Diffusion...")
    try:
        df = pd.read_csv("pce_spend.csv", skiprows=4, header=None)
        start_year = 1959
        end_year = 2025
        years = list(range(start_year, end_year + 1))
        months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
        date_cols = []
        for year in years:
            for month in months:
                date_cols.append(f"{year}-{month}")
        num_date_cols = min(len(date_cols), df.shape[1] - 2)
        column_names = ['Line', 'Description'] + date_cols[:num_date_cols]
        df = df.iloc[:, :len(column_names)]
        df.columns = column_names
        df = df.dropna(subset=['Description'])
        df['Description'] = df['Description'].astype(str).str.strip()
        df = df[df['Description'] != '']
        numeric_cols = df.columns[2:]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df_melted = df.melt(id_vars=['Line', 'Description'], 
                            var_name='Date', 
                            value_name='Value')
        df_melted[['Year', 'Month']] = df_melted['Date'].str.split('-', expand=True)
        df_melted['Year'] = pd.to_numeric(df_melted['Year'])
        month_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                     'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
        df_melted['Month_Num'] = df_melted['Month'].map(month_map)
        df_melted['Date_Parsed'] = pd.to_datetime(df_melted[['Year', 'Month_Num']].assign(day=1).rename(columns={'Month_Num': 'month', 'Year': 'year'}))
        df_clean = df_melted[['Line', 'Description', 'Date_Parsed', 'Value']].copy()
        df_clean = df_clean.dropna(subset=['Value'])
        df_clean = df_clean.sort_values(['Line', 'Date_Parsed']).reset_index(drop=True)
        df_final = df_clean.pivot(index="Date_Parsed", columns="Description", values="Value")
        df_yoy_growth = df_final.pct_change(periods=12)
        diffusion_index = (df_yoy_growth > 0).sum(axis=1) / df_yoy_growth.count(axis=1) * 100
        diffusion_index = diffusion_index.rolling(3).mean()
        plot_diffusion_index_to_fig(fig, 4, 1, diffusion_index, recession_data, 
                                    diffusion_index.index.min(), x1, 0, 100,
                                    "Diffusion Index of PCE Spending Categories (yoy growth)")
    except Exception as e:
        print(f"Could not process PCE data: {e}")
        print("Make sure pce_spend.csv is in the same directory")

    # ===== CHART 8: Cyclical Hiring =====
    print("Processing Chart 8: Cyclical Hiring...")
    cyclical_series = {
        "Construction": "USCONS",
        "Manufacturing": "MANEMP",
        "Retail Trade": "USTRADE",
        "Wholesale Trade": "USWTRADE",
        "Leisure and Hospitality": "USLAH",
    }
    cyclical_df = get_fred(list(cyclical_series.values()), 100).dropna()
    cyclical_hiring = cyclical_df.sum(axis=1).diff().rolling(6).mean()
    x0 = cyclical_hiring.index.min()
    y0, y1 = -500, 500

    fig.add_trace(go.Scatter(
        x=cyclical_hiring.index,
        y=cyclical_hiring.values,
        mode='lines',
        name='Cyclical Hiring (6mma)',
        line=dict(color='blue'),
        showlegend=False
    ), row=4, col=2)

    fig.add_trace(go.Scatter(
        x=cyclical_hiring.index,
        y=[0] * len(cyclical_hiring),
        mode='lines',
        name='Zero line',
        line=dict(dash='dash', color='gray'),
        showlegend=False
    ), row=4, col=2)

    for date_val, value in recession_data["USREC"].items():
        if value == 1:
            fig.add_shape(
                type="rect",
                x0=date_val,
                x1=date_val + pd.offsets.MonthEnd(0),
                y0=y0,
                y1=y1,
                fillcolor="lightgray",
                opacity=0.7,
                line_width=0,
                layer="below",
                row=4, col=2
            )

    fig.update_xaxes(range=[x0, x1], row=4, col=2)
    fig.update_yaxes(range=[y0, y1], row=4, col=2)

    # Update layout
    fig.update_layout(
        title={
            'text': 'US Leading Economic Indicators Dashboard',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 24}
        },
        height=1600,
        showlegend=False,
        template='plotly_white',
        margin=dict(t=100, l=50, r=50, b=50)
    )
    
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    
    # Add last update timestamp
    update_time = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    fig.add_annotation(
        text=f'Last Updated: {update_time}',
        xref='paper', yref='paper',
        x=0.5, y=-0.02,
        showarrow=False,
        font=dict(size=12, color='gray')
    )
    
    return fig

def main():
    print("Creating US Leading Indicators Dashboard...")
    fig = create_dashboard()
    
    # Save to HTML
    html_file = 'index.html'
    fig.write_html(
        html_file,
        config={'displayModeBar': True, 'displaylogo': False}
    )
    print(f"\nDashboard saved to {html_file}")

if __name__ == "__main__":
    main()
