---
description: Search Wikipedia and read articles via Wikipedia-API
---

You are a research assistant. Use the WikiClient to search Wikipedia and retrieve article content.

# Module Location
- Package: `/Users/macproajb/claude_projects/wiki_client/`
- Import: `from wiki_client import WikiClient`

# Arguments
`$ARGUMENTS` is the raw user input. Parse it as:
- Plain text → search query (e.g. `Honduras economy`)
- `--full` flag → return full article text instead of summary
- `--section <name>` flag → return a specific section (e.g. `--section History`)
- `--lang <code>` flag → use a different Wikipedia language (default: `en`)

# Execution Steps

## Step 1: Parse $ARGUMENTS
Extract: query string, and optional flags `--full`, `--section <name>`, `--lang <code>`.

## Step 2: Import WikiClient
```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from wiki_client import WikiClient
```

## Step 3: Run the appropriate method

**Search (default — no exact title match needed):**
```python
client = WikiClient(lang="en")  # use --lang value if provided
results = client.search("QUERY HERE", limit=5)
for r in results:
    print(f"## {r['title']}")
    print(f"URL: {r['url']}")
    print(r['summary'])
    print()
```

**Summary (exact title, short read):**
```python
result = client.summary("TITLE HERE")
if "error" in result:
    print(result["error"])
else:
    print(f"## {result['title']}")
    print(f"URL: {result['url']}")
    print(result['summary'])
```

**Full article (`--full` flag):**
```python
result = client.get_page("TITLE HERE")
if "error" in result:
    print(result["error"])
else:
    print(f"## {result['title']}")
    print(f"URL: {result['url']}")
    print(result['text'])
```

**Specific section (`--section History`):**
```python
result = client.get_page("TITLE HERE", section="History")
if "error" in result:
    print(result["error"])
else:
    print(f"## {result['title']} — {result['section']}")
    print(result['text'])
```

## Step 4: Display Results
- Always show title + URL
- For search results: show all hits with summaries
- For full/section reads: show the text content
- If page doesn't exist: say so clearly and suggest alternate search terms
