---
description: Fetch up to 10 Wikipedia articles on a topic and synthesize a Smart Brevity essay
---

You are a research orchestrator. Use WikiClient to gather Wikipedia content on the given topic, then synthesize a concise Axios-style brief.

# Arguments
`$ARGUMENTS` is the raw topic (e.g., `strait of hormuz`, `bretton woods system`).

# Execution Steps

## Step 1: Import WikiClient
```python
import sys
sys.path.insert(0, '/Users/macproajb/claude_projects')
from wiki_client import WikiClient
client = WikiClient(lang="en")
```

## Step 2: Search for up to 10 articles
```python
topic = "$ARGUMENTS"
results = client.search(topic, limit=10)
```

If `results` is empty, stop and tell the user: `No Wikipedia articles found for "{topic}". Try a different search term.`

## Step 3: Fetch full page text for each result (cap at 3000 chars each)
```python
research = []
for r in results:
    page = client.get_page(r["title"])
    if "error" not in page:
        text = page["text"][:3000]
        research.append(f"## Article: {page['title']}\nURL: {page['url']}\n\n{text}")

compiled = "\n\n---\n\n".join(research)
```

## Step 4: Synthesize
Read the compiled research above and write a brief essay on the topic using this exact format:

Write in strict Axios "Smart Brevity" style. Structure:
1. Start with a punchy, 1-sentence lede (no qualifiers).
2. Follow with "**Why it matters:**" and 1-2 sharp causal points.
3. Use bold headers like "**By the numbers**," "**Between the lines**," or "**What's next**."

Voice: Crisp, economical sentences. No metaphors, no fluff. Prioritize clarity and causality.
Format: Bullets for data/insights. Paragraphs must be 1-2 lines max.
Output requirements: Do NOT display the brief in the terminal. Write it only to disk (Step 5). Include a "**Sources**" section at the end listing each Wikipedia article as a numbered list with title and URL.

## Step 5: Save to disk
After outputting the brief, save it to `~/claude_projects/wiki_client/wiki_briefs/`. Use a filename derived from the topic (lowercase, spaces replaced with underscores, `.md` extension). Example: topic "karl popper" → `karl_popper.md`.

```python
import os

output_dir = os.path.expanduser("~/claude_projects/wiki_client/wiki_briefs")
os.makedirs(output_dir, exist_ok=True)

filename = topic.strip().lower().replace(" ", "_") + ".md"
filepath = os.path.join(output_dir, filename)

# brief_text should contain the full synthesized brief (including Sources section)
with open(filepath, "w") as f:
    f.write(brief_text)

print(f"Saved to {filepath}")
```

Tell the user only the saved filepath. No other output.
