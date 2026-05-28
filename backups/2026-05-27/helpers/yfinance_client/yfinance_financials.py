#!/usr/bin/env python3
"""Pull curated financials for any ticker via yfinance."""

import sys
import yfinance as yf

INCOME_BILLIONS = [
    'Total Revenue', 'Gross Profit',
    'Research And Development',
    'Selling General And Administration',
    'Operating Income', 'EBITDA',
    'Interest Expense', 'Tax Provision',
    'Net Income', 'Normalized Income', 'Normalized EBITDA',
]
INCOME_DOLLARS = ['Diluted EPS', 'Basic EPS']
INCOME_LINES = INCOME_BILLIONS + INCOME_DOLLARS

BALANCE_BILLIONS = [
    'Cash And Cash Equivalents', 'Other Short Term Investments',
    'Current Assets', 'Current Liabilities',
    'Total Assets', 'Net PPE',
    'Goodwill And Other Intangible Assets',
    'Total Debt', 'Net Debt',
    'Total Equity Gross Minority Interest',
    'Retained Earnings',
]
BALANCE_SHARES = ['Ordinary Shares Number']
BALANCE_LINES = BALANCE_BILLIONS + BALANCE_SHARES

CASHFLOW_LINES = [
    'Operating Cash Flow',
    'Free Cash Flow', 'Stock Based Compensation',
    'Depreciation And Amortization',
    'Change In Working Capital',
    'Net Income From Continuing Operations', 'Deferred Tax', 'Capital Expenditure',
    'Investing Cash Flow', 'Financing Cash Flow', 'Repurchase Of Capital Stock',
    'Changes In Cash', 'End Cash Position',
]


def print_table(df, label, billions_rows, dollars_rows=None, shares_rows=None, max_cols=None):
    all_lines = billions_rows + (dollars_rows or []) + (shares_rows or [])
    rows = [l for l in all_lines if l in df.index]
    if not rows:
        print(f'\n=== {label} — no data ===')
        return
    out = df.loc[rows].copy()
    out = out[sorted(out.columns)]
    if max_cols:
        out = out.iloc[:, -max_cols:]
    out.loc[[l for l in billions_rows if l in out.index]] = (
        out.loc[[l for l in billions_rows if l in out.index]] / 1e9
    ).round(2)
    if dollars_rows:
        out.loc[[l for l in dollars_rows if l in out.index]] = (
            out.loc[[l for l in dollars_rows if l in out.index]]
        ).round(2)
    if shares_rows:
        out.loc[[l for l in shares_rows if l in out.index]] = (
            out.loc[[l for l in shares_rows if l in out.index]] / 1e9
        ).round(3)
    note = '(USD billions; EPS in dollars; shares in billions)'
    print(f'\n=== {label} ===')
    print(note)
    print(out.to_string())


def _safe_pct(num, den):
    try:
        import math
        n, d = float(num), float(den)
        if math.isnan(n) or math.isnan(d) or d == 0:
            return '—'
        return f'{n / d * 100:.1f}%'
    except Exception:
        return '—'


def _safe_mult(num, den, guard_nonpos=False):
    try:
        import math
        n, d = float(num), float(den)
        if math.isnan(n) or math.isnan(d) or d == 0:
            return '—'
        if guard_nonpos and d <= 0:
            return '—'
        return f'{n / d:.1f}x'
    except Exception:
        return '—'


def _safe_growth(series, idx):
    try:
        import math
        cur, prev = float(series.iloc[idx]), float(series.iloc[idx - 1])
        if math.isnan(cur) or math.isnan(prev) or prev == 0:
            return '—'
        return f'{(cur / prev - 1) * 100:.1f}%'
    except Exception:
        return '—'


def print_ratios(inc_df, bal_df, cf_df, label, max_cols=None, quarterly=False):
    import pandas as pd

    # Sort columns ascending (oldest left) then slice
    inc = inc_df[sorted(inc_df.columns)]
    bal = bal_df[sorted(bal_df.columns)]
    cf  = cf_df[sorted(cf_df.columns)]

    if max_cols:
        inc = inc.iloc[:, -max_cols:]
        cf  = cf.iloc[:, -max_cols:]
        bal = bal.iloc[:, -max_cols:]

    cols = inc.columns.tolist()
    bal = bal.reindex(columns=cols)  # align balance dates to income dates

    def get(df, name):
        return df.loc[name] if name in df.index else pd.Series([None] * len(cols), index=cols)

    rev    = get(inc, 'Total Revenue')
    gp     = get(inc, 'Gross Profit')
    oi     = get(inc, 'Operating Income')
    ebitda = get(inc, 'EBITDA')
    nebitda= get(inc, 'Normalized EBITDA')
    ni     = get(inc, 'Net Income')
    sga    = get(inc, 'Selling General And Administration')
    rnd    = get(inc, 'Research And Development')
    fcf    = get(cf,  'Free Cash Flow')
    ocf    = get(cf,  'Operating Cash Flow')
    nd     = get(bal, 'Net Debt')
    eq     = get(bal, 'Total Equity Gross Minority Interest')

    rows = {}
    # Profitability
    rows['Gross Margin']        = [_safe_pct(gp[c],      rev[c])              for c in cols]
    rows['Operating Margin']    = [_safe_pct(oi[c],      rev[c])              for c in cols]
    rows['EBITDA Margin']       = [_safe_pct(ebitda[c],  rev[c])              for c in cols]
    rows['Norm. EBITDA Margin'] = [_safe_pct(nebitda[c], rev[c])              for c in cols]
    rows['Net Margin']          = [_safe_pct(ni[c],       rev[c])             for c in cols]
    rows['FCF Margin']          = [_safe_pct(fcf[c],      rev[c])             for c in cols]
    # Efficiency
    rows['R&D % Revenue']       = [_safe_pct(rnd[c],      rev[c])             for c in cols]
    rows['SG&A % Revenue']      = [_safe_pct(sga[c],      rev[c])             for c in cols]
    rows['FCF Conversion']      = [_safe_mult(fcf[c], nebitda[c], guard_nonpos=True) for c in cols]
    rows['OCF Conversion']      = [_safe_mult(ocf[c], nebitda[c], guard_nonpos=True) for c in cols]
    # Returns
    rows['ROE']                 = [_safe_pct(ni[c], eq[c])                    for c in cols]
    # Leverage
    rows['Net Debt / Norm. EBITDA'] = [_safe_mult(nd[c], nebitda[c]) for c in cols]
    # Growth
    growth_label = 'QoQ Growth' if quarterly else 'YoY Growth'
    rev_g    = ['—'] + [_safe_growth(rev,    i) for i in range(1, len(cols))]
    nebitda_g= ['—'] + [_safe_growth(nebitda,i) for i in range(1, len(cols))]
    fcf_g    = ['—'] + [_safe_growth(fcf,    i) for i in range(1, len(cols))]
    rows[f'Revenue {growth_label}']       = rev_g
    rows[f'Norm. EBITDA {growth_label}']  = nebitda_g
    rows[f'FCF {growth_label}']           = fcf_g

    out = pd.DataFrame(rows, index=cols).T
    print(f'\n=== {label} RATIOS ===')
    print(out.to_string())


COUNCIL_Q_LINES = [
    'Total Revenue', 'Gross Profit', 'Operating Income', 'Net Income',
]
COUNCIL_CF_LINES = ['Free Cash Flow', 'Operating Cash Flow']
COUNCIL_BAL_LINES = [
    'Cash And Cash Equivalents', 'Other Short Term Investments',
    'Total Debt', 'Goodwill And Other Intangible Assets',
    'Total Equity Gross Minority Interest', 'Ordinary Shares Number',
]


def print_council_snapshot(tk, ticker):
    """Slim quarterly snapshot: revenue/income/FCF + key balance sheet items."""
    import pandas as pd

    t = ticker.upper()

    # Quarterly income
    print_table(
        tk.quarterly_financials, f'{t} QUARTERLY SNAPSHOT — INCOME',
        [l for l in COUNCIL_Q_LINES if l not in ('Diluted EPS',)],
        dollars_rows=['Diluted EPS'],
        max_cols=4,
    )

    # Quarterly FCF
    print_table(tk.quarterly_cashflow, f'{t} QUARTERLY SNAPSHOT — CASH FLOW',
                COUNCIL_CF_LINES, max_cols=4)

    # Most recent balance sheet (single column)
    bs = tk.quarterly_balance_sheet
    bs = bs[sorted(bs.columns)]
    latest_col = bs.columns[-1]
    bs_latest = bs[[latest_col]]
    rows = [l for l in COUNCIL_BAL_LINES if l in bs_latest.index]
    if rows:
        out = bs_latest.loc[rows].copy()
        bil_rows = [l for l in rows if l != 'Ordinary Shares Number']
        out.loc[bil_rows] = (out.loc[bil_rows] / 1e9).round(2)
        out.loc[['Ordinary Shares Number']] = (out.loc[['Ordinary Shares Number']] / 1e9).round(3)
        print(f'\n=== {t} BALANCE SHEET — LATEST ({latest_col.date()}) ===')
        print('(USD billions; shares in billions)')
        print(out.to_string())


def run(ticker: str, council: bool = False):
    tk = yf.Ticker(ticker.upper())

    if council:
        print_council_snapshot(tk, ticker)
        print_ratios(tk.financials, tk.balance_sheet, tk.cashflow,
                     f'{ticker.upper()} RATIOS — ANNUAL', max_cols=4)
        return

    # Income statement
    print_table(tk.financials,           f'{ticker.upper()} INCOME — ANNUAL',    INCOME_BILLIONS, INCOME_DOLLARS)
    print_table(tk.quarterly_financials, f'{ticker.upper()} INCOME — QUARTERLY', INCOME_BILLIONS, INCOME_DOLLARS, max_cols=5)

    # Balance sheet
    print_table(tk.balance_sheet,           f'{ticker.upper()} BALANCE SHEET — ANNUAL',    BALANCE_BILLIONS, shares_rows=BALANCE_SHARES)
    print_table(tk.quarterly_balance_sheet, f'{ticker.upper()} BALANCE SHEET — QUARTERLY', BALANCE_BILLIONS, shares_rows=BALANCE_SHARES, max_cols=5)

    # Cash flow
    print_table(tk.cashflow,           f'{ticker.upper()} CASH FLOW — ANNUAL',    CASHFLOW_LINES)
    print_table(tk.quarterly_cashflow, f'{ticker.upper()} CASH FLOW — QUARTERLY', CASHFLOW_LINES, max_cols=5)

    # Ratios
    print_ratios(tk.financials,           tk.balance_sheet,           tk.cashflow,           f'{ticker.upper()} RATIOS — ANNUAL')
    print_ratios(tk.quarterly_financials, tk.quarterly_balance_sheet, tk.quarterly_cashflow, f'{ticker.upper()} RATIOS — QUARTERLY', max_cols=5, quarterly=True)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python yfinance_financials.py <TICKER> [--council]')
        sys.exit(1)

    import io
    import os
    from datetime import date

    ticker_arg = sys.argv[1]
    council_mode = '--council' in sys.argv

    buf = io.StringIO()
    _orig_stdout = sys.stdout
    sys.stdout = buf
    run(ticker_arg, council=council_mode)
    sys.stdout = _orig_stdout
    output = buf.getvalue()
    print(output, end='')

    suffix = '_council' if council_mode else ''
    filename = f"{ticker_arg.upper()}_{date.today().strftime('%Y-%m-%d')}{suffix}.txt"
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(out_path, 'w') as f:
        f.write(output)
    print(f'\nSaved → {out_path}')
