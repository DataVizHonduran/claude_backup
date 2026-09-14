# EIA Monday SPR Scrape

Fetch the latest Strategic Petroleum Reserve inventory from `spr.doe.gov` (updated weekly) and show a 12-week table of level + week-on-week change.

## What this does

1. **Current snapshot** — downloads `https://www.spr.doe.gov/dir/images/img2.jpg` (DOE updates this image weekly), reads it visually to extract: sweet/sour/total inventory (MMB) and monthly oil movements table.
2. **12-week history** — fetches EIA weekly series `WCSSTUS1` from `https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WCSSTUS1&f=W` and prints level + WoW change.

## Step 1 — Read the DOE image

```python
import requests, base64, anthropic, json

SPR_IMG = "https://www.spr.doe.gov/dir/images/img2.jpg"

img_bytes = requests.get(SPR_IMG, headers={"Cache-Control": "no-cache"}, timeout=30).content

client = anthropic.Anthropic()
msg = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=1024,
    messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.standard_b64encode(img_bytes).decode()}},
        {"type": "text", "text": """Extract all data from this SPR inventory table. Return ONLY valid JSON:
{
  "as_of_date": "YYYY-MM-DD",
  "inventory_mmb": {"sweet": <float>, "sour": <float>, "total": <float>},
  "monthly_movements": [
    {"month": "MMM-YY", "return_purchase_barrels": <float>,
     "drawdown_sales_exchange_barrels": <float>, "net_movement": <float>}
  ],
  "footnotes": {"<letter>": "<description>"}
}
Negative values as negative floats. JSON only."""}
    ]}]
)

raw = msg.content[0].text.strip()
if raw.startswith("```"):
    raw = raw.split("```")[1]
    if raw.startswith("json"):
        raw = raw[4:]
snapshot = json.loads(raw.strip())
```

## Step 2 — Fetch 12-week history from EIA (no API key needed)

Use `WebFetch` on `https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WCSSTUS1&f=W` with prompt:
> "Extract ALL rows from the data table that fall in the last 6 months. Return every date and value as CSV: date,value (one per line, no headers)."

Parse the CSV response into a DataFrame, convert kbbl → MMB, compute `diff()` for WoW change, take `tail(12)`.

## Step 3 — Print table

```
Week Ending     Level (MMB)    WoW Chg
----------------------------------------
YYYY-MM-DD            XXX.X      +/-X.X
...
```

Then print the current snapshot from the image:
```
Current (as of YYYY-MM-DD): Sweet X.X | Sour X.X | Total X.X MMB
```

Followed by the monthly movements table and footnotes.

## Key facts

- Image URL: `https://www.spr.doe.gov/dir/images/img2.jpg` — add `Cache-Control: no-cache` header
- EIA series: `WCSSTUS1` — weekly, thousands of barrels
- No API key required for EIA HTML page; Anthropic API key required for image vision step
- If running without an API key, skip Step 1 and use only Step 2 (EIA history table)
- Image data is embedded as a JPG (not HTML) — must use vision to extract values

## Without API key (fallback)

Skip the DOE image entirely. Fetch EIA history (Step 2) and print the 12-week table only.
