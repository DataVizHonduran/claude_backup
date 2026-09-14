"""Pick which tickers a refresh run should target.

Usage:
  python3 select_tickers.py 20        # 20 stalest (oldest updated_at) tickers
  python3 select_tickers.py all       # every S&P 500 constituent
Prints a space-separated ticker list to stdout.
"""
import json, sys

DATA_DIR = "/Users/macproajb/claude_projects/equity_valuation/data"

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "20"
    const = json.load(open(f"{DATA_DIR}/sp500_constituents.json"))
    all_tickers = [c["ticker"] for c in const]

    if arg == "all":
        print(" ".join(all_tickers))
        return

    n = int(arg)
    try:
        val = json.load(open(f"{DATA_DIR}/valuations.json"))
    except FileNotFoundError:
        val = {}

    # Tickers never successfully computed are "infinitely stale" -- refresh first.
    never_computed = [t for t in all_tickers if t not in val]
    computed_sorted = sorted(val.keys(), key=lambda t: val[t].get("updated_at", ""))

    picks = (never_computed + computed_sorted)[:n]
    print(" ".join(picks))

if __name__ == "__main__":
    main()
