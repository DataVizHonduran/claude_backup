#!/usr/bin/env python3
"""
Brasil SGS Pull — fetch BCB time series and render Plotly HTML charts.

Usage:
  python3 brasil_sgs_pull.py --series ipca --transform mom_to_yoy --years 15
  python3 brasil_sgs_pull.py --series custom --codes '{"433":"IPCA","4448":"Non-tradable"}' --transform yoy
  python3 brasil_sgs_pull.py --list
"""

import argparse
import json
import os
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sgs

OUTPUT_DIR = "/Users/macproajb/claude_projects/reports/brasil-sgs"

# ── Known series groups ────────────────────────────────────────────────────────
SERIES_GROUPS = {
    "gdp_demand": {
        "22109": "Overall GDP index at market prices",
        "22110": "Private household consumption index",
        "22111": "Government consumption index",
        "22113": "Gross fixed capital formation index",
    },
    "gdp_supply": {
        "22105": "Agricultural production index",
        "22106": "Industrial production index",
        "22107": "Services sector production index",
        "22108": "Value added at basic prices",
    },
    "ind_prod": {
        "21859": "General (2022=100)",
        "21862": "Manufacturing industry",
        "21863": "Capital goods",
        "21864": "Intermediate goods",
        "21865": "Consumer goods",
        "21866": "Durable goods",
    },
    "ipca": {
        "433": "IPCA",
        "4447": "Tradable Goods",
        "4448": "Non-tradable Goods",
        "4449": "Administered Prices",
    },
    "core_ipca": {
        "11427": "EX0 (excl. food-at-home & administered)",
        "16121": "EX1",
        "16122": "Trimmed mean",
        "11426": "Smoothed trimmed mean",
        "28751": "Excl. food & energy",
        "4466": "Smoothed trimmed mean (alt)",
    },
    "ipca_goods": {
        "10841": "Nondurable goods",
        "10842": "Semidurable goods",
        "10843": "Durable goods",
        "10844": "Services",
    },
    "igp": {
        "189": "IGP-M",
        "7450": "IPA-M",
        "7453": "IPC-M",
        "7456": "INCC-M",
    },
    "ic_br_brl": {
        "27574": "IC-Br General (BRL)",
        "27575": "IC-Br Agriculture (BRL)",
        "27576": "IC-Br Metals (BRL)",
        "27577": "IC-Br Energy (BRL)",
    },
    "ic_br_usd": {
        "29039": "IC-Br Energy (USD)",
        "29040": "IC-Br Metals (USD)",
        "29041": "IC-Br Agriculture (USD)",
        "29042": "IC-Br General (USD)",
    },
    "jobs": {
        "28763": "New CAGED Total",
        "28764": "Agriculture",
        "28766": "Manufacturing",
        "28770": "Construction",
        "28772": "Services",
    },
    "pnad": {
        "24370": "Working age population",
        "24378": "Labor force",
        "24379": "Employed",
        "24380": "Unemployed",
    },
    "earnings": {
        "24381": "Real effective avg earnings",
        "24382": "Real habitually avg earnings",
        "1619": "Minimum wage",
    },
    "cars": {
        "1373": "Vehicles production (total)",
        "1374": "Passenger Cars",
        "1380": "Vehicle Exports",
        "1378": "Vehicle Sales",
        "1381": "Motorcycle sales",
    },
    "retail_sa": {
        "28473": "Total - SA",
        "28475": "Supermarkets - SA",
        "28478": "Furniture & goods - SA",
        "28479": "Vehicles - SA",
        "28485": "Broad trade - SA",
    },
    "bop": {
        "22707": "Goods",
        "22719": "Services",
        "22800": "Primary income",
        "22838": "Secondary income",
    },
    "credit": {
        "20539": "Total Credit",
        "20540": "To Nonfinancial Corporations",
        "20541": "To Households",
        "20593": "Earmarked",
        "20542": "Non-earmarked",
    },
    "credit_gdp": {
        "21302": "Foreign financial institutions",
        "21299": "Private banks",
        "21301": "National private banks",
        "21300": "Public banks",
    },
    "govt_debt": {
        "28196": "Total lending to govt",
        "28197": "Loans",
        "28198": "Debt",
        "28199": "External Debt",
    },
    "monetary": {
        "27810": "M2",
        "27813": "M3",
        "27815": "M4",
        "27840": "Base Money",
    },
    "confidence": {
        "4393": "Consumer Confidence Index",
        "4394": "Current Expectations",
        "4395": "Future Expectations",
    },
    "bndes": {
        "7415": "BNDES disbursements",
        "7416": "Manufacturing",
        "1417": "Commerce",
        "7418": "Agricultural",
    },
}

TRANSFORMS = ["none", "yoy", "mom_to_yoy", "3mma_yoy", "qoq", "12m_sum", "3mma", "12m_diff"]


def pull_data(data_dict, transform="none", years=10):
    today = datetime.today()
    start = today - relativedelta(years=years)

    codes = [int(c) for c in data_dict.keys()]
    rename = {int(c): v for c, v in data_dict.items()}

    df = sgs.dataframe(codes, start=start.strftime("%d/%m/%Y"), end=today.strftime("%d/%m/%Y"))
    df = df.rename(columns=rename)

    if transform == "yoy":
        df = df.pct_change(12) * 100
    elif transform == "mom_to_yoy":
        df = (1 + df.clip(lower=-0.999).fillna(0) / 100).cumprod() * 100
        df = df.pct_change(12) * 100
    elif transform == "3mma_yoy":
        df = df.rolling(3).mean().pct_change(12) * 100
    elif transform == "qoq":
        df = df.pct_change(4) * 100
    elif transform == "12m_sum":
        df = df.rolling(12).sum() / 1000
    elif transform == "3mma":
        df = df.rolling(3).mean()
    elif transform == "12m_diff":
        df = df.diff(12)

    return df


def create_chart(df, label, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    safe = label.replace(" ", "_").replace("/", "-")

    fig = px.line(df, title=label)
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        template="plotly_white",
        legend=dict(x=1.02),
    )

    html_path = os.path.join(output_dir, f"{safe}.html")
    fig.write_html(html_path)
    print(f"Saved: {html_path}")
    return html_path


def main():
    parser = argparse.ArgumentParser(description="Brazil SGS data pull and chart")
    parser.add_argument("--series", default="ipca", help="Series group name or 'custom'")
    parser.add_argument("--codes", default=None, help="JSON dict of {code: label} for custom series")
    parser.add_argument("--transform", default="none", choices=TRANSFORMS)
    parser.add_argument("--years", type=int, default=15)
    parser.add_argument("--label", default=None, help="Chart title (defaults to series name)")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--list", action="store_true", help="List available series groups and exit")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable series groups:")
        for name, d in SERIES_GROUPS.items():
            series_list = ", ".join(list(d.values())[:3])
            print(f"  {name:20s}  {series_list}...")
        print("\nTransforms:", ", ".join(TRANSFORMS))
        return

    if args.series == "custom":
        if not args.codes:
            print("--codes required for custom series. Pass JSON: '{\"433\":\"IPCA\",\"4448\":\"NT\"}'")
            sys.exit(1)
        data_dict = json.loads(args.codes)
    elif args.series in SERIES_GROUPS:
        data_dict = SERIES_GROUPS[args.series]
    else:
        print(f"Unknown series '{args.series}'. Use --list to see options.")
        sys.exit(1)

    label = args.label or f"{args.series} ({args.transform}, {args.years}y)"

    print(f"Fetching {args.series} | transform={args.transform} | years={args.years}")
    df = pull_data(data_dict, transform=args.transform, years=args.years)
    print(df.tail(3).to_string())

    html_path = create_chart(df, label=label, output_dir=args.output_dir)
    print(f"\nOpen: open \"{html_path}\"")


if __name__ == "__main__":
    main()
