
import json
import httpx
from py_clob_client.client import ClobClient

# The slugs from the URLs provided by the user.
slugs = [
    "maduro-out-by-march-31-2026",
    "which-company-has-best-ai-model-end-of-2025",
    "anthropic-ipo-closing-market-cap"
]

def fetch_polymarket_data():
    """
    Fetches trade data for a list of Polymarket slugs and saves it to a JSON file.
    """
    try:
        client = ClobClient("https://clob.polymarket.com")
        print("Successfully connected to Polymarket CLOB API.")
    except Exception as e:
        print(f"Error connecting to Polymarket CLOB API: {e}")
        return

    all_markets = []
    next_cursor = None
    while True:
        try:
            url = "https://clob.polymarket.com/markets"
            params = {}
            if next_cursor:
                params["next_cursor"] = next_cursor
            
            res = httpx.get(url, params=params)
            res.raise_for_status()
            
            markets_response = res.json()
            all_markets.extend(markets_response['data'])
            next_cursor = markets_response.get('next_cursor')
            
            if not next_cursor:
                break
        except Exception as e:
            print(f"Error fetching markets: {e}")
            return
    
    print(f"Found {len(all_markets)} markets.")

    charts_data = []

    for slug in slugs:
        print(f"Processing slug: {slug}")
        market_found = False
        for market in all_markets:
            if market['market_slug'] == slug:
                market_found = True
                print(f"Found market: {market['question']}")
                try:
                    # We still use the client to get trades, as that part was working.
                    trades = client.get_trades(market['condition_id'])
                    print(f"Found {len(trades)} trades for market {market['condition_id']}")

                    # Process trades to create chart data
                    trades.sort(key=lambda t: t.timestamp)
                    
                    chart_points = []
                    for trade in trades:
                        # timestamp is in nanoseconds, convert to milliseconds for JS charts
                        chart_points.append({
                            "x": trade.timestamp / 1_000_000,
                            "y": trade.price
                        })

                    charts_data.append({
                        "title": market['question'],
                        "data": chart_points
                    })
                except Exception as e:
                    print(f"Error fetching trades for market {market['condition_id']}: {e}")
                break
        
        if not market_found:
            print(f"Market with slug '{slug}' not found.")

    # Save the data to a JSON file
    try:
        with open("polymarket_data.json", "w") as f:
            json.dump(charts_data, f, indent=4)
        print("Successfully saved data to polymarket_data.json")
    except Exception as e:
        print(f"Error saving data to JSON file: {e}")

if __name__ == "__main__":
    fetch_polymarket_data()
