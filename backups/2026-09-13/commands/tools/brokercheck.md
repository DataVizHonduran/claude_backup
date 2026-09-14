---
description: Look up a Wall Street professional on FINRA BrokerCheck and NFA BASIC, return a merged career profile with employment history, licenses, and disclosures.
---

Look up `$ARGUMENTS` on FINRA BrokerCheck and NFA BASIC. Arguments format: `"First Last, Firm Name"` (e.g., `"David Solomon, Goldman Sachs"`).

# Step 1 — Parse name and firm

Split `$ARGUMENTS` on the first comma. Trim whitespace. Store as `person_name` and `firm_name`. If no comma is present, treat the entire string as `person_name` and set `firm_name` to empty string.

# Step 2 — Search BrokerCheck

Run this Bash command to search for the individual:

```bash
python3 - << 'PYEOF'
import json, urllib.request, urllib.parse, sys

person_name = "$ARGUMENTS".split(",")[0].strip()
parts = "$ARGUMENTS".split(",", 1)
firm_name = parts[1].strip() if len(parts) > 1 else ""

params = {
    "query": person_name,
    "type": "individual",
    "hl": "true",
    "nrows": "10",
    "includePrevious": "true",
}
if firm_name:
    params["firm"] = firm_name

url = "https://api.brokercheck.finra.org/search/individual?" + urllib.parse.urlencode(params)
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://brokercheck.finra.org/",
    "Accept": "application/json",
})
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.load(r)

hits = data.get("hits", {}).get("hits", [])
total = data.get("hits", {}).get("total", 0)

if not hits:
    print("NO_RESULTS")
    sys.exit(0)

# Score hits: prefer Active scope, then match on firm name in current employments
def score(h):
    s = h["_source"]
    active = 1 if s.get("ind_bc_scope") == "Active" else 0
    firms = [e.get("firm_name","").lower() for e in s.get("ind_current_employments",[])]
    firm_match = 1 if any(firm_name.lower() in f for f in firms) else 0
    return active + firm_match

hits.sort(key=score, reverse=True)

print(f"Total results: {total}")
for i, h in enumerate(hits[:5]):
    s = h["_source"]
    name = f"{s.get('ind_firstname','')} {s.get('ind_middlename','')} {s.get('ind_lastname','')}".strip()
    crd = s.get("ind_source_id","")
    scope = s.get("ind_bc_scope","")
    firms = [e.get("firm_name","") for e in s.get("ind_current_employments",[])]
    print(f"{i+1}. {name} | CRD:{crd} | {scope} | Firms: {firms}")

best = hits[0]["_source"]
crd = best["ind_source_id"]
print(f"\nBEST_CRD:{crd}")
PYEOF
```

If output is `NO_RESULTS`, stop and tell the user no FINRA record was found for that name/firm.

If there are multiple results, present the top 5 to the user and ask which one to pull. Wait for user selection before proceeding.

Extract the CRD number from the output (e.g., `CRD:1616414` → `1616414`).

# Step 3 — Fetch BrokerCheck detail

```bash
python3 - << 'PYEOF'
import json, urllib.request, sys

crd = "REPLACE_WITH_CRD"

url = f"https://api.brokercheck.finra.org/search/individual/{crd}"
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://brokercheck.finra.org/",
    "Accept": "application/json",
})
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.load(r)

hits = data.get("hits", {}).get("hits", [])
if not hits:
    print("DETAIL_ERROR")
    sys.exit(0)

content_str = hits[0]["_source"]["content"]
record = json.loads(content_str)
print(json.dumps(record, indent=2))
PYEOF
```

Replace `REPLACE_WITH_CRD` with the actual CRD number. Capture the full JSON record.

# Step 4 — Search NFA BASIC

NFA uses a JSON-RPC API. Run this Bash command in parallel with Step 3 (do not wait — fire both simultaneously):

```bash
python3 - << 'PYEOF'
import json, urllib.request, sys

person_name = "$ARGUMENTS".split(",")[0].strip()
# Split "First Last" into last/first for NFA search (last name is searchMain)
parts = person_name.strip().split()
last_name = parts[-1] if parts else person_name
first_name = " ".join(parts[:-1]) if len(parts) > 1 else ""

url = "https://www.nfa.futures.org/BasicNet/basic-api/DataHandlerSearch.ashx"
options = {
    "pageIndex": 0,
    "pageSize": 50,
    "totalPages": 0,
    "totalCount": 0,
    "sort": [{"active": True, "column": "INDIVIDUAL_NAME", "direction": "asc", "ctrl": "sort_individual_name"}],
    "filters": {"memStatus": "", "regTypes": "", "regActions": ""},
    "filterOptions": {"memStatus": None, "regTypes": None, "regActions": None}
}
payload = {
    "id": 1,
    "method": "getIndividualSearchResults",
    "params": [last_name, first_name, options]
}
body = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(url, data=body, headers={
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json; charset=utf-8",
    "X-JSON-RPC": "getIndividualSearchResults",
    "Referer": "https://www.nfa.futures.org/BasicNet/basic-search-results.aspx",
    "Origin": "https://www.nfa.futures.org",
})
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    result = data.get("result", {})
    if not result.get("success"):
        print("NFA_ERROR: API returned success=false")
        sys.exit(0)
    rows = result.get("result", {}).get("result", {}).get("rows", [])
    if not rows:
        print("NFA_NO_RESULTS")
    else:
        print(json.dumps(rows, indent=2))
except Exception as e:
    print(f"NFA_ERROR:{e}")
PYEOF
```

If output is `NFA_NO_RESULTS` or starts with `NFA_ERROR`, note "No NFA registration found" and continue with BrokerCheck data only.

If rows are returned, each row represents an NFA-registered individual. Find the best name match. Each row contains registration status, firm affiliations, and registration types. Extract:
- Registration status (Active/Inactive)
- Firm name(s) and dates from the row data
- Any disciplinary actions noted in the row
- NFA ID for the matched individual (to link: `https://www.nfa.futures.org/BasicNet/Details.aspx?entityid={nfa_id}`)

# Step 5 — Parse and merge

**Identity** (from BrokerCheck)
- `basicInformation.firstName` + `lastName` + `middleName`
- `basicInformation.individualId` (CRD#)
- `basicInformation.bcScope` (Active / InActive)

**Employment History** — merge BrokerCheck + NFA, union by (firm name, begin date), deduplicate, sort most recent first. Tag each entry with source: `[BD]` for BrokerCheck, `[NFA]` for NFA-only entries.
- BrokerCheck: `currentEmployments[]` + `previousEmployments[]` → firm name, dates, city/state
- NFA: employment history entries not already present in BrokerCheck → firm name, dates, city/state

**Licenses & Exams** (from BrokerCheck)
- `productExamCategory[]` → exam name + date (Series 7, SIE, etc.)
- `stateExamCategory[]` → exam name + date (Series 63, 65, 66, etc.)
- `principalExamCategory[]` → exam name + date (Series 24, etc.)
- NFA registrations (Forex Dealer Member AP, IB, etc.) if present

**Disclosures**
- BrokerCheck: `disclosures[]` — count, type, disposition
- NFA: disciplinary actions if present
- If both clean → "No disclosures on record (BrokerCheck + NFA)"

# Step 6 — Output format

Reply in this format (plain text, no HTML):

```
BROKERCHECK + NFA SUMMARY — [Full Name] (CRD# [number])
Status: [Active/InActive] | BrokerCheck: https://brokercheck.finra.org/individual/summary/[CRD]
NFA Status: [Active/Inactive/No record]

EMPLOYMENT HISTORY
[Year]–present  [Current Firm], [City, State]  [BD]
[Year]–[Year]   [Prior Firm], [City, State]     [BD]
[Year]–[Year]   [NFA-only Firm], [City, State]  [NFA]
... (all entries, merged)

LICENSES
[Series X] — [Full exam name] ([date passed])
[NFA registration type] — ([date])
...

DISCLOSURES
[Count] disclosure(s) on record: [brief type/disposition summary]
— OR —
No disclosures on record (BrokerCheck + NFA).
```

Keep the summary tight. No filler. Flag anything notable: gaps in registration, NFA-only stints (may indicate FX/futures-only role), disclosures, unusual number of firms.
