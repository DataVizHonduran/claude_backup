# Gemma Inject — AI briefing for FT News Feed

Generate a Smart Brevity AI summary for one or all topic tags and inject it into `reports/news/index.html`.

## How to invoke

- `/gemma-inject shipping` → regenerate summary for the "shipping" tag only, push
- `/gemma-inject --all` → regenerate all tag summaries and push (same as `--publish`)
- No args → prompt the user for a tag name

---

## `--all` workflow

When `--all` is passed, run the full generator (which regenerates articles + all summaries):

```bash
cd /Users/macproajb/boquin.github.io
python3 scripts/generate_ft_news.py
git add reports/news/index.html
git commit -m "update FT news summaries — $(date -u '+%d %b %Y %H:%M UTC')"
git push
```

Requires `HF_TOKEN` to be set in environment.

---

## Single-tag workflow

When a specific tag is given, patch only the `SUMMARIES` const in the existing HTML —
avoids re-fetching all article feeds.

### Script

```python
import json, os, re, sys, time

try:
    from huggingface_hub import InferenceClient
except ImportError:
    raise SystemExit("pip install huggingface_hub")

import feedparser

HTML_FILE = "/Users/macproajb/boquin.github.io/reports/news/index.html"

TOPICS = {
    "oil and gas":                    {"label": "Oil & Gas",              "feed": "https://www.ft.com/energy?format=rss"},
    "corporate earnings and results": {"label": "Corporate Earnings",     "feed": "https://www.ft.com/companies?format=rss"},
    "middle east war":                {"label": "Middle East War",        "feed": "https://www.ft.com/middle-east?format=rss"},
    "shipping":                       {"label": "Shipping",               "feed": "https://www.ft.com/shipping?format=rss"},
    "artificial intelligence":        {"label": "Artificial Intelligence","feed": "https://www.ft.com/artificial-intelligence?format=rss"},
    "us-china relations":             {"label": "US–China Relations", "feed": "https://www.ft.com/geopolitics?format=rss"},
}

SMART_BREVITY_SYSTEM = (
    'Write in strict Axios "Smart Brevity" style. '
    "Structure: 1. Start with a punchy, 1-sentence lede (no qualifiers). "
    '2. Follow with "**Why it matters:**" and 1-2 sharp causal points. '
    '3. Use bold headers like "**By the numbers**," "**Between the lines**," or "**What\'s next**." '
    "Voice: Crisp, economical sentences. No metaphors, no fluff. "
    "Prioritize clarity and causality. "
    "Format: Bullets for data/insights. Paragraphs must be 1-2 lines max. "
    "Output requirements: Deliver the finished note only. Topic:"
)

def md_to_html(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    parts = re.split(r'\n{2,}', text.strip())
    out = []
    for part in parts:
        lines = [l.strip() for l in part.split('\n') if l.strip()]
        if not lines:
            continue
        is_bullet = [l.startswith('- ') or l.startswith('* ') for l in lines]
        if all(is_bullet):
            out.append('<ul>' + ''.join(f'<li>{l[2:]}</li>' for l in lines) + '</ul>')
        elif not any(is_bullet):
            out.append(f'<p>{" ".join(lines)}</p>')
        else:
            acc, mode = [], None
            for l, bullet in zip(lines, is_bullet):
                if bullet:
                    if mode == 'p' and acc:
                        out.append(f'<p>{" ".join(acc)}</p>'); acc = []
                    mode = 'ul'; acc.append(l[2:])
                else:
                    if mode == 'ul' and acc:
                        out.append('<ul>' + ''.join(f'<li>{i}</li>' for i in acc) + '</ul>'); acc = []
                    mode = 'p'; acc.append(l)
            if acc:
                out.append(('<ul>' + ''.join(f'<li>{i}</li>' for i in acc) + '</ul>') if mode == 'ul' else f'<p>{" ".join(acc)}</p>')
    return ''.join(out)

def generate_summary(tag, label, feed_url, hf_token):
    feed = feedparser.parse(feed_url)
    articles = feed.entries[:40]
    if not articles:
        raise ValueError(f"No entries in feed: {feed_url}")
    lines = "\n".join(
        f"- {e.get('title','')}: {re.sub(chr(10),' ',e.get('summary',''))}"
        for e in articles
    )
    client = InferenceClient(token=hf_token)
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="google/gemma-4-31B-it",
                messages=[
                    {"role": "system", "content": f"{SMART_BREVITY_SYSTEM} {label}"},
                    {"role": "user",   "content": f"Recent headlines:\n{lines}"},
                ],
                temperature=0.2,
                max_tokens=600,
            )
            return md_to_html(resp.choices[0].message.content.strip())
        except Exception as e:
            is_rate_limit = "429" in str(e) or "too many" in str(e).lower()
            if is_rate_limit and attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"Rate limited — retrying in {wait}s…"); time.sleep(wait)
            else:
                raise

def patch_html(tag, html_summary):
    html = open(HTML_FILE, encoding="utf-8").read()
    m = re.search(r'const SUMMARIES\s*=\s*(\{.*?\});', html, re.DOTALL)
    if not m:
        raise ValueError("Could not find SUMMARIES const in index.html")
    summaries = json.loads(m.group(1))
    summaries[tag] = html_summary
    new_const = f"const SUMMARIES = {json.dumps(summaries, ensure_ascii=False)};"
    html = html[:m.start()] + new_const + html[m.end():]
    open(HTML_FILE, "w", encoding="utf-8").write(html)

# --- entry point ---
tag = SKILL_ARGS.strip().lower() if "SKILL_ARGS" in dir() else ""
if not tag:
    raise SystemExit("Usage: /gemma-inject <tag>  (e.g. shipping, 'oil and gas')")

if tag not in TOPICS:
    print(f"Unknown tag '{tag}'. Known tags: {', '.join(TOPICS)}")
    raise SystemExit(1)

hf_token = os.environ.get("HF_TOKEN", "")
if not hf_token:
    raise SystemExit("HF_TOKEN environment variable not set")

info = TOPICS[tag]
print(f"Fetching + summarising: {info['label']} …")
html_summary = generate_summary(tag, info["label"], info["feed"], hf_token)
patch_html(tag, html_summary)
print(f"Patched SUMMARIES['{tag}'] in {HTML_FILE}")
```

### After patching, commit and push

```bash
cd /Users/macproajb/boquin.github.io
git add reports/news/index.html
git commit -m "update FT news summary: <TAG> — $(date -u '+%d %b %Y %H:%M UTC')"
git push
```

---

## Instructions for the agent

1. Parse `SKILL_ARGS`:
   - `--all` → run the `--all` workflow (call `generate_ft_news.py` then git add/commit/push)
   - anything else → treat as a tag name and run the single-tag workflow
2. For single-tag: write the script to `/tmp/gemma_inject.py`, inject `SKILL_ARGS = "<tag>"` at the top, run with `python3 /tmp/gemma_inject.py`
3. Confirm: print how many articles were fetched, the first 100 chars of the generated summary, and confirm the push succeeded
4. `HF_TOKEN` must be in the environment — if it is missing, tell the user to `export HF_TOKEN=...` before running

---

## Adding a new tag

When a new tag is added to `TOPICS` in `generate_ft_news.py`, also add it to the `TOPICS` dict in the script above so `/gemma-inject <new-tag>` works standalone.
