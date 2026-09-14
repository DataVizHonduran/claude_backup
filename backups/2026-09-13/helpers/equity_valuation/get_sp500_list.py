"""Fetch current S&P 500 constituents (ticker, name, GICS sector/sub-industry) from Wikipedia."""
import json
import pandas as pd
import urllib.request

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read()
    tables = pd.read_html(html)
    df = tables[0]
    df = df.rename(columns={
        "Symbol": "ticker",
        "Security": "name",
        "GICS Sector": "sector",
        "GICS Sub-Industry": "sub_industry",
    })[["ticker", "name", "sector", "sub_industry"]]
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)  # BRK.B -> BRK-B for yfinance
    return df

if __name__ == "__main__":
    df = fetch()
    print(f"Fetched {len(df)} constituents")
    df.to_json("/Users/macproajb/claude_projects/equity_valuation/data/sp500_constituents.json", orient="records", indent=2)
    print(df["sector"].value_counts())
