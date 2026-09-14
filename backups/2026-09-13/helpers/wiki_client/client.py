import wikipediaapi


class WikiClient:
    def __init__(self, lang: str = "en"):
        self.wiki = wikipediaapi.Wikipedia(
            language=lang,
            user_agent="wiki-skill/1.0 (claude-code-tool)"
        )
        self.lang = lang

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Search Wikipedia and return top results with summary + URL."""
        page = self.wiki.page(query)
        results = []
        if page.exists():
            results.append({
                "title": page.title,
                "summary": page.summary[:500] + ("..." if len(page.summary) > 500 else ""),
                "url": page.fullurl,
            })
        # Try opensearch via the underlying API for broader results
        try:
            import urllib.request, json, urllib.parse
            q = urllib.parse.quote(query)
            url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={q}&limit={limit}&format=json"
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
            titles, _, urls = data[1], data[2], data[3]
            seen = {r["title"] for r in results}
            for title, link in zip(titles, urls):
                if title not in seen:
                    p = self.wiki.page(title)
                    results.append({
                        "title": title,
                        "summary": p.summary[:500] + ("..." if len(p.summary) > 500 else "") if p.exists() else "",
                        "url": link,
                    })
                    seen.add(title)
                    if len(results) >= limit:
                        break
        except Exception:
            pass
        return results

    def get_page(self, title: str, section: str = None) -> dict:
        """Fetch a Wikipedia page. If section given, return that section only."""
        page = self.wiki.page(title)
        if not page.exists():
            return {"error": f"Page '{title}' does not exist."}
        if section:
            for s in page.sections:
                if s.title.lower() == section.lower():
                    return {"title": page.title, "section": s.title, "text": s.text, "url": page.fullurl}
            return {"error": f"Section '{section}' not found in '{page.title}'."}
        return {"title": page.title, "text": page.text, "url": page.fullurl}

    def summary(self, title: str) -> dict:
        """Return lead summary paragraph only."""
        page = self.wiki.page(title)
        if not page.exists():
            return {"error": f"Page '{title}' does not exist."}
        return {"title": page.title, "summary": page.summary, "url": page.fullurl}
