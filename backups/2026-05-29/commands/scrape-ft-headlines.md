# Scrape FT Headlines → display + optional save + publish

Fetch Financial Times RSS headlines and links for a given section.

## How to invoke

The user can pass an optional section name and/or flags:

- `/scrape-ft-headlines` → top international stories (default)
- `/scrape-ft-headlines markets` → markets section
- `/scrape-ft-headlines tech --save` → technology section, save to markdown file
- `/scrape-ft-headlines --save` → top stories, save to file
- `/scrape-ft-headlines --publish` → regenerate **all** topic feeds and publish to `boquin.xyz/reports/news/`

### `--publish` workflow

When `--publish` is passed, ignore any section name and instead:

1. Run `python3 /Users/macproajb/boquin.github.io/scripts/generate_ft_news.py`
2. `cd /Users/macproajb/boquin.github.io`
3. `git add reports/news/index.html`
4. `git commit -m "update FT news feed — $(date -u '+%d %b %Y %H:%M UTC')"`
5. `git push`
6. Report: articles fetched and the live URL `https://boquin.xyz/reports/news/`

### Adding a new tag to the boquin.xyz news page

When the user asks to add a new topic tag, edit `TOPICS` in
`/Users/macproajb/boquin.github.io/scripts/generate_ft_news.py`:

1. **Find the right FT RSS feed.** Try `https://www.ft.com/<slug>?format=rss` — most
   FT topic/section pages expose one. Verify with:
   ```
   curl -s -o /dev/null -w "%{http_code}" -L "https://www.ft.com/<slug>?format=rss"
   ```
   200 = feed exists. Also check item count:
   ```python
   import feedparser
   f = feedparser.parse("https://www.ft.com/<slug>?format=rss")
   print(f.feed.get("title"), len(f.entries))
   ```

2. **Append a new entry** to the `TOPICS` list (order = left-to-right on the tag bar):
   ```python
   {
       "tag":   "my new topic",          # internal key, lowercase, used in JS filter
       "label": "My New Topic",          # display name on the tag button and badge
       "color": "#0ea5e9",               # text/border colour for badge & active button
       "bg":    "#f0f9ff",               # light background for badge & inactive button
       "feed":  "https://www.ft.com/<slug>?format=rss",
   },
   ```
   Pick a colour not already used (current set: amber `#d97706`, emerald `#059669`,
   red `#dc2626`, blue `#2563eb`, violet `#7c3aed`, orange `#ea580c`).

3. **Rebuild and publish:**
   ```
   /scrape-ft-headlines --publish
   ```

---

Recognised sections (case-insensitive):

| Alias | Feed URL |
|---|---|
| `home`, `top`, *(default)* | `https://www.ft.com/rss/home/international` |
| `world` | `https://www.ft.com/world?format=rss` |
| `markets` | `https://www.ft.com/markets?format=rss` |
| `tech`, `technology` | `https://www.ft.com/technology?format=rss` |
| `opinion` | `https://www.ft.com/opinion?format=rss` |
| `companies` | `https://www.ft.com/companies?format=rss` |
| `alphaville` | `https://www.ft.com/alphaville?format=rss` |
| `economics` | `https://www.ft.com/economics?format=rss` |
| `lex` | `https://www.ft.com/lex?format=rss` |
| `us` | `https://www.ft.com/us?format=rss` |
| `uk` | `https://www.ft.com/uk?format=rss` |
| `asia` | `https://www.ft.com/asia-pacific?format=rss` |
| `emerging` | `https://www.ft.com/emerging-markets?format=rss` |

---

## Script

```python
import feedparser
import sys
import os
from datetime import datetime, timezone
import re

FEEDS = {
    "home":           "https://www.ft.com/rss/home/international",
    "top":            "https://www.ft.com/rss/home/international",
    "world":          "https://www.ft.com/world?format=rss",
    "markets":        "https://www.ft.com/markets?format=rss",
    "tech":           "https://www.ft.com/technology?format=rss",
    "technology":     "https://www.ft.com/technology?format=rss",
    "opinion":        "https://www.ft.com/opinion?format=rss",
    "companies":      "https://www.ft.com/companies?format=rss",
    "alphaville":     "https://www.ft.com/alphaville?format=rss",
    "economics":      "https://www.ft.com/economics?format=rss",
    "lex":            "https://www.ft.com/lex?format=rss",
    "us":             "https://www.ft.com/us?format=rss",
    "uk":             "https://www.ft.com/uk?format=rss",
    "asia":           "https://www.ft.com/asia-pacific?format=rss",
    "emerging":       "https://www.ft.com/emerging-markets?format=rss",
    # energy / commodities aliases
    "energy":         "https://www.ft.com/energy?format=rss",
    "oil & gas":      "https://www.ft.com/energy?format=rss",
    "oil and gas":    "https://www.ft.com/energy?format=rss",
    "gas":            "https://www.ft.com/natural-gas?format=rss",
    "natural gas":    "https://www.ft.com/natural-gas?format=rss",
    "natural-gas":    "https://www.ft.com/natural-gas?format=rss",
    "commodities":    "https://www.ft.com/commodities?format=rss",
    # geo aliases
    "emerging markets": "https://www.ft.com/emerging-markets?format=rss",
    "asia pacific":   "https://www.ft.com/asia-pacific?format=rss",
}

def slugify(text):
    """Convert a human phrase to a URL slug: lowercase, '&'→'and', spaces→'-'."""
    text = text.lower().replace("&", "and")
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text

def parse_args(args_str):
    """Return (section, save_flag) from the args string passed to the skill."""
    parts = [p.strip() for p in args_str.split() if p.strip()]
    save = "--save" in [p.lower() for p in parts]
    parts = [p for p in parts if p.lower() != "--save"]
    section = " ".join(parts).lower() if parts else "home"
    return section, save

def fmt_date(entry):
    """Return a short date/time string from an RSS entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return dt.strftime("%d %b %Y %H:%M UTC")
    return ""

def scrape(section="home", save=False, cwd="."):
    if section in FEEDS:
        feed_url = FEEDS[section]
    else:
        feed_url = f"https://www.ft.com/{slugify(section)}?format=rss"
    print(f"Fetching FT RSS: {feed_url}")
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        print(f"ERROR: could not parse feed — {feed.bozo_exception}")
        return

    now_str = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    section_title = feed.feed.get("title", section.upper())
    entries = feed.entries
    print(f"\n{'='*72}")
    print(f"  Financial Times — {section_title}")
    print(f"  {len(entries)} headlines  |  fetched {now_str}")
    print(f"{'='*72}\n")

    lines_md = [
        f"# Financial Times — {section_title}",
        f"*Fetched {now_str} | {feed_url}*\n",
    ]

    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "").strip()
        link  = entry.get("link", "")
        desc  = entry.get("summary", "").strip()
        date  = fmt_date(entry)

        # strip CDATA residue and trailing whitespace
        title = re.sub(r'\s+', ' ', title).strip()
        desc  = re.sub(r'\s+', ' ', desc).strip()

        print(f"{i:2d}. {title}")
        if date:
            print(f"    {date}")
        if desc:
            print(f"    {desc}")
        print(f"    {link}\n")

        lines_md.append(f"## {i}. {title}")
        if date:
            lines_md.append(f"*{date}*")
        if desc:
            lines_md.append(f"> {desc}")
        lines_md.append(f"[Read on FT]({link})\n")

    if save:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        fname = f"ft_{section}_{ts}.md"
        out_path = os.path.join(cwd, fname)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines_md))
        print(f"Saved {len(entries)} headlines → {out_path}")

    return entries

# --- entry point ---
args_str = SKILL_ARGS if "SKILL_ARGS" in dir() else ""
section, save = parse_args(args_str)
entries = scrape(section=section, save=save, cwd=os.getcwd())
```

---

## Instructions for the agent

1. Parse the user's args: extract section keyword (default `home`) and whether `--save` was requested.
2. Set `SKILL_ARGS` to whatever the user passed, then run the script via `python3 -c "..."` **or** write it to a temp file and run it.
   - Preferred: write to `/tmp/ft_scrape.py`, inject the args at the top as `SKILL_ARGS = "<args>"`, then `python3 /tmp/ft_scrape.py`.
3. Print the results inline. If `--save` was used, report the output file path.
4. Do **not** attempt to follow FT article links or scrape article bodies — FT is paywalled; the RSS feed is the authoritative free data source.
5. If the user asks for a section not in the table, try `https://www.ft.com/<section>?format=rss` — many FT topic/section pages expose RSS.

---

## Key notes

- FT RSS refreshes every **15 minutes** (`<ttl>15</ttl>`).
- Each item has: `title`, `link` (ft.com/content/…), `description` (summary), `pubDate`, and a `media:thumbnail` image URL (not captured by default — available via `entry.media_thumbnail[0]['url']` if needed).
- `feedparser` handles CDATA-wrapped CDATA and namespaces automatically.
- The `/rss/home/international` feed is the international front page; `/rss/home` redirects to it.
