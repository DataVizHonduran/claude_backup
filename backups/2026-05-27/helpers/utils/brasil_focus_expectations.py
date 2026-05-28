#!/usr/bin/env python3
"""
BCB Focus Market Expectations — Latest Snapshot with 1w/4w Comparisons
-----------------------------------------------------------------------
Fetches the most recent 60 days of BCB Focus survey data for all 12 macro
indicators and produces two output files in the same directory:

  brasil_focus_summary.csv       — one row per (indicator, ref_year) with
                                    latest value + 1w and 4w comparisons
  brasil_focus_full_structure.json — full 60-day time series per indicator
                                     and reference year
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

BCB_ENDPOINT = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas"
    "/versao/v1/odata/ExpectativasMercadoAnuais"
)

# slug: (display_label, api_indicator_name, unit, indicador_detalhe_filter)
INDICATORS = {
    'ipca':               ('IPCA',                          'IPCA',                           '% a.a.',  None),
    'pib':                ('PIB Total',                     'PIB Total',                      '% a.a.',  None),
    'cambio':             ('Câmbio',                        'Câmbio',                         'BRL/USD', None),
    'selic':              ('Selic',                         'Selic',                          '% a.a.',  None),
    'igpm':               ('IGP-M',                         'IGP-M',                          '% a.a.',  None),
    'resultado_primario': ('Resultado Primário',             'Resultado primário',              '% PIB',   None),
    'resultado_nominal':  ('Resultado Nominal',              'Resultado nominal',               '% PIB',   None),
    'divida_liquida':     ('Dívida Líquida Setor Público',   'Dívida líquida do setor público', '% PIB',   None),
    'conta_corrente':     ('Conta Corrente',                 'Conta corrente',                  'US$ bi',  None),
    'balanca_comercial':  ('Balança Comercial (Saldo)',      'Balança comercial',               'US$ bi',  'Saldo'),
    'ipca_adm':           ('IPCA Administrados',             'IPCA Administrados',              '% a.a.',  None),
    'ide':                ('Invest. Direto no País',         'Investimento direto no país',     'US$ bi',  None),
}

TARGET_REF_YEARS = [2025, 2026, 2027, 2028]
FETCH_DAYS = 60  # look-back window for API fetch

HERE = Path(__file__).parent


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (compatible; BCB-Focus-Expectations/1.0)',
        'Accept': 'application/json',
    })
    return s


def _api_fetch(api_name: str, start_date: str, session: requests.Session,
               detalhe: str = None) -> list:
    records = []
    skip = 0
    top = 10000
    while True:
        parts = [
            f"Data ge '{start_date}'",
            f"Indicador eq '{api_name}'",
            "baseCalculo eq 0",
        ]
        if detalhe:
            parts.append(f"IndicadorDetalhe eq '{detalhe}'")
        date_filter = ' and '.join(parts)
        url = (
            f"{BCB_ENDPOINT}"
            f"?$top={top}&$skip={skip}"
            f"&$filter={requests.utils.quote(date_filter)}"
            f"&$select=Data,DataReferencia,Mediana"
            f"&$orderby=Data asc&$format=json"
        )
        try:
            r = session.get(url, timeout=90)
            r.raise_for_status()
            data = r.json().get('value', [])
        except Exception as e:
            print(f'    API error at skip={skip}: {e}')
            break
        records.extend(data)
        if len(data) < top:
            break
        skip += top
        time.sleep(0.4)
    return records


def _records_to_df(records: list) -> pd.DataFrame:
    rows = []
    for rec in records:
        try:
            rows.append({
                'date':     str(rec['Data'])[:10],
                'ref_year': int(str(rec['DataReferencia'])[:4]),
                'median':   float(rec['Mediana']),
            })
        except (KeyError, ValueError, TypeError):
            continue
    if not rows:
        return pd.DataFrame(columns=['date', 'ref_year', 'median'])
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=['date', 'ref_year'], keep='last')
    df = df.sort_values(['ref_year', 'date']).reset_index(drop=True)
    return df


def _closest_before(df_yr: pd.DataFrame, cutoff_date: str):
    """Return (value, date_str) for the latest survey date <= cutoff_date."""
    sub = df_yr[df_yr['date'] <= cutoff_date]
    if sub.empty:
        return None, None
    row = sub.iloc[-1]
    return float(row['median']), str(row['date'])


def main():
    today = datetime.now().date()
    start_date = (today - timedelta(days=FETCH_DAYS)).strftime('%Y-%m-%d')
    cutoff_1w  = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    cutoff_4w  = (today - timedelta(days=28)).strftime('%Y-%m-%d')
    today_str  = today.strftime('%Y-%m-%d')

    session = _make_session()
    summary_rows = []
    full_structure = {}

    for slug, (label, api_name, unit, detalhe) in INDICATORS.items():
        print(f'Fetching {label}...')
        records = _api_fetch(api_name, start_date, session, detalhe=detalhe)
        df = _records_to_df(records)
        print(f'  {len(records)} records fetched')

        full_structure[slug] = {
            'label': label,
            'unit': unit,
            'ref_years': {},
        }

        for yr in TARGET_REF_YEARS:
            df_yr = df[df['ref_year'] == yr].sort_values('date')
            if df_yr.empty:
                continue

            val_latest, date_latest = _closest_before(df_yr, today_str)
            val_1w, date_1w         = _closest_before(df_yr, cutoff_1w)
            val_4w, date_4w         = _closest_before(df_yr, cutoff_4w)

            if val_latest is None:
                continue

            summary_rows.append({
                'indicator':   slug,
                'label':       label,
                'unit':        unit,
                'ref_year':    yr,
                'latest':      val_latest,
                'date_latest': date_latest,
                'val_1w_ago':  val_1w,
                'date_1w_ago': date_1w,
                'val_4w_ago':  val_4w,
                'date_4w_ago': date_4w,
            })

            full_structure[slug]['ref_years'][yr] = [
                {'date': str(row['date']), 'median': float(row['median'])}
                for _, row in df_yr.iterrows()
            ]

    summary_csv = HERE / 'brasil_focus_summary.csv'
    full_json   = HERE / 'brasil_focus_full_structure.json'

    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)
    with open(full_json, 'w', encoding='utf-8') as f:
        json.dump(full_structure, f, ensure_ascii=False, indent=2)

    print(f'\nWrote {len(summary_rows)} rows → {summary_csv}')
    print(f'Wrote full structure → {full_json}')


if __name__ == '__main__':
    main()
