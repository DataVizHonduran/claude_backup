# FactSet Earnings Insight — weekly macro brief

Fetch the latest FactSet Earnings Insight PDF and produce a ≤300-word macro-focused brief.

---

## Step 1 — Find the PDF URL

Use WebSearch with query:
```
site:insight.factset.com earnings insight weekly
```

Look for a result linking to a PDF at `insight.factset.com/hubfs/earningsinsight/EarningsInsight_*.pdf`. Extract the direct PDF URL.

**Fallback:** If WebSearch doesn't surface a direct PDF link, construct the URL from today's date:
```
https://insight.factset.com/hubfs/earningsinsight/EarningsInsight_MM.DD.YY.pdf
```
where `MM.DD.YY` uses today's date (e.g. `07.25.25`). Try the most recent Friday if today is not Friday.

---

## Step 2 — Download and summarize

Set `PDF_URL` to the URL found in Step 1, then run this script:

```python
import requests, base64, anthropic, os, sys

PDF_URL = "__PDF_URL__"  # injected by agent

headers = {"User-Agent": "ResearchBot jeannealbertoreading@gmail.com"}
print(f"Downloading: {PDF_URL}")
r = requests.get(PDF_URL, headers=headers, timeout=30)
r.raise_for_status()
pdf_b64 = base64.standard_b64encode(r.content).decode()
print(f"Downloaded {len(r.content):,} bytes — calling Claude for summary…")

client = anthropic.Anthropic()
msg = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=600,
    messages=[{
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64
                }
            },
            {
                "type": "text",
                "text": """You are summarizing the FactSet Earnings Insight report for a macro investor. Write a tight ≤300-word brief. Rules:

- Lead with the blended S&P 500 EPS growth rate (YoY %) for the current quarter — state what % of companies have reported and what % beat estimates, plus the median and mean EPS beat magnitude.
- Next: blended revenue growth rate, % of companies beating revenue estimates, and the median/mean revenue beat size.
- Call out 1-2 sector outliers — sectors significantly above or below the blended average on EPS or revenue growth. Name the sector and the gap.
- End with macro signals only: direction of forward estimate revisions, implied full-year earnings trajectory, any margin pressure or demand-softening flags visible in the aggregate data.
- DO NOT mention individual stock names or stock price movements.
- DO NOT speculate beyond what the report states.
- Use numbers where the report gives them. Label the report date/week at the top."""
            }
        ]
    }]
)

print("\n" + "="*72)
print(msg.content[0].text)
print("="*72)
```

Write the script to `/private/tmp/claude-501/-Users-macproajb-claude-projects/b8a30dd4-708f-489f-baf8-5b45891c65ee/scratchpad/factset_insight.py`, replacing `__PDF_URL__` with the actual URL, then run:
```
python3 /private/tmp/claude-501/-Users-macproajb-claude-projects/b8a30dd4-708f-489f-baf8-5b45891c65ee/scratchpad/factset_insight.py
```

---

## Output

Print the brief inline. No file saved.

## Error handling

- **403/404 on PDF URL:** Try the prior Friday's date. If still failing, report the URL attempted and ask the user to paste the PDF link from `insight.factset.com/topic/earnings`.
- **`requests` not installed:** `pip install requests` silently, then retry.
