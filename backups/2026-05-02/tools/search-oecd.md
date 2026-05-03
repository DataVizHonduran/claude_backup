---
description: Search OECD dataflow catalog by natural-language description — returns ranked mnemonic/agency hits
---

Find the right OECD dataflow ID for any topic. No data fetched — lookup only.

# Module
- `from oecd_client import OecdClient`

# Execution

```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from oecd_client import OecdClient

c = OecdClient()

# Run 1–3 query variants to maximise recall
for q in [QUERY_VARIANTS]:
    hits = c.search(q, top_n=8)
    print(f"\n=== {q} ===")
    print(hits[["score", "id", "name", "agency"]].to_string())
```

Pick the best match (highest score + name makes sense). Return `id` and `agency` — pass directly to `get_data()` in `get-oecd-data`. Note any key dimensions to filter (check Key Dataflows table in `get-oecd-data.md`).

# Guidelines
- Try 2–3 query variants if first-pass scores are all below 0.55 (e.g. "current account" → "balance of payments" → "BOP")
- Catalog lazy-loads on first call; subsequent searches are instant in-memory
- If top result is ambiguous, show user top 3–5 and ask which one they want
- Output only the ranked table — no data fetching, no charting
