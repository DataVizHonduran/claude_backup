"""Fetch yfinance fundamentals for a list of tickers, checkpointing to disk after each.

Usage:
  python3 fetch_fundamentals.py                 # fetch all S&P 500 constituents not yet cached
  python3 fetch_fundamentals.py --force          # re-fetch everyone
  python3 fetch_fundamentals.py AAPL MSFT GOOGL  # fetch/refresh just these tickers
"""
import json, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf

DATA_DIR = "/Users/macproajb/claude_projects/equity_valuation/data"
FUND_PATH = f"{DATA_DIR}/fundamentals.json"
CONST_PATH = f"{DATA_DIR}/sp500_constituents.json"

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    import os
    os.replace(tmp, path)

def fetch_one(ticker):
    tk = yf.Ticker(ticker)
    info = tk.info
    inc = tk.financials
    cf = tk.cashflow

    def row(df, name, n=4):
        if name in df.index:
            vals = df.loc[name].tolist()[:n]
            return [round(x/1e9, 4) if x == x and x is not None else None for x in vals]
        return None

    revenue = row(inc, "Total Revenue")
    ebitda = row(inc, "EBITDA")
    pretax = row(inc, "Pretax Income")
    tax = row(inc, "Tax Provision")
    net_income = row(inc, "Net Income")
    interest = row(inc, "Interest Expense")
    capex = row(cf, "Capital Expenditure")

    out = {
        "shortName": info.get("shortName"),
        "sector_yf": info.get("sector"),
        "industry_yf": info.get("industry"),
        "currentPrice": info.get("currentPrice") or info.get("regularMarketPrice"),
        "beta": info.get("beta"),
        "forwardPE": info.get("forwardPE"),
        "trailingPE": info.get("trailingPE"),
        "enterpriseToEbitda": info.get("enterpriseToEbitda"),
        "sharesOutstanding": info.get("sharesOutstanding"),
        "marketCap": info.get("marketCap"),
        "totalDebt": info.get("totalDebt"),
        "totalCash": info.get("totalCash"),
        "revenue": revenue,
        "ebitda": ebitda,
        "pretax": pretax,
        "tax": tax,
        "net_income": net_income,
        "interest": interest,
        "capex": capex,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "error": None,
    }
    return out

def main():
    args = sys.argv[1:]
    force = "--force" in args
    tickers_arg = [a for a in args if not a.startswith("--")]

    constituents = load_json(CONST_PATH, [])
    all_tickers = [c["ticker"] for c in constituents]
    tickers = tickers_arg if tickers_arg else all_tickers

    fund = load_json(FUND_PATH, {})
    todo = [t for t in tickers if force or t not in fund or fund[t].get("error") is not None]
    total = len(todo)
    print(f"{len(tickers)} requested, {total} need fetching (rest already cached).", flush=True)

    done = 0
    def work(t):
        try:
            return t, fetch_one(t), None
        except Exception as e:
            return t, None, str(e)

    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(work, t): t for t in todo}
        for fut in as_completed(futures):
            t, result, err = fut.result()
            done += 1
            if result is not None:
                fund[t] = result
                print(f"[{done}/{total}] {t} OK  price={result.get('currentPrice')}", flush=True)
            else:
                fund[t] = {"error": err, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                print(f"[{done}/{total}] {t} FAILED: {err}", flush=True)
            if done % 20 == 0:
                save_json(FUND_PATH, fund)
    save_json(FUND_PATH, fund)
    ok = sum(1 for v in fund.values() if v.get("error") is None)
    print(f"\nDone. {ok}/{len(fund)} cached successfully.")

if __name__ == "__main__":
    main()
