import requests
import anthropic
import base64
import json
from datetime import datetime

SPR_IMAGE_URL = "https://www.spr.doe.gov/dir/images/img2.jpg"

EXTRACT_PROMPT = """Extract all data from this SPR inventory table and return ONLY valid JSON with this structure:
{
  "as_of_date": "YYYY-MM-DD",
  "inventory_mmb": {
    "sweet": <float>,
    "sour": <float>,
    "total": <float>
  },
  "monthly_movements": [
    {
      "month": "MMM-YY",
      "return_purchase_barrels": <float>,
      "drawdown_sales_exchange_barrels": <float>,
      "net_movement": <float>
    }
  ],
  "footnotes": {
    "<letter>": "<description>"
  }
}
Negative values should be negative floats (not in parentheses). Return JSON only, no prose."""


def fetch_image() -> bytes:
    resp = requests.get(SPR_IMAGE_URL, headers={"Cache-Control": "no-cache"}, timeout=30)
    resp.raise_for_status()
    return resp.content


def parse_image(image_bytes: bytes) -> dict:
    client = anthropic.Anthropic()
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64
                    }
                },
                {
                    "type": "text",
                    "text": EXTRACT_PROMPT
                }
            ]
        }]
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def print_summary(data: dict):
    inv = data["inventory_mmb"]
    print(f"\nSPR Inventory — as of {data['as_of_date']}")
    print(f"  Sweet:  {inv['sweet']:.1f} MMB")
    print(f"  Sour:   {inv['sour']:.1f} MMB")
    print(f"  Total:  {inv['total']:.1f} MMB")

    print(f"\n{'Month':<10} {'Return/Purchase':>16} {'Drawdown':>16} {'Net':>10}")
    print("-" * 55)
    for row in data["monthly_movements"]:
        print(
            f"{row['month']:<10}"
            f"{row['return_purchase_barrels']:>16.1f}"
            f"{row['drawdown_sales_exchange_barrels']:>16.1f}"
            f"{row['net_movement']:>10.1f}"
        )

    if data.get("footnotes"):
        print("\nFootnotes:")
        for k, v in data["footnotes"].items():
            print(f"  {k} = {v}")


if __name__ == "__main__":
    print(f"Fetching SPR image ({SPR_IMAGE_URL})...")
    image_bytes = fetch_image()
    print(f"Downloaded {len(image_bytes):,} bytes. Parsing with Claude vision...")
    data = parse_image(image_bytes)
    print_summary(data)
    out_path = f"spr_{datetime.today().strftime('%Y-%m-%d')}.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nSaved → {out_path}")
