import requests
import json
import time
from urllib.parse import urlparse

URLS = [
    "https://junkbondinvestor.substack.com",
    "https://www.semianalysis.com",
    "https://epbresearch.substack.com",
    "https://thechangeconstant.substack.com",
    "https://hfiresearch.substack.com",
    "https://www.notboring.co",
    "https://macrocreditthinking.substack.com",
    "https://macromostly.substack.com",
    "https://rupakghose.substack.com",
    "https://www.newcomer.co",
    "https://globalmacromethod.substack.com",
    "https://thematicmarkets.substack.com",
    "https://thesundaydrive.substack.com",
    "https://www.doomberg.com",
    "https://technically.substack.com",
    "https://openinsights.substack.com",
    "https://www.chinatalk.media",
    "https://capitalmischief.substack.com",
    "https://sovereignvibe.substack.com",
    "https://robinjbrooks.substack.com",
    "https://www.parentdata.org",
    "https://debtserious.substack.com",
    "https://cartadocondado.substack.com",
    "https://thecentralbankswatcher.substack.com",
    "https://10xdisruptivestocks.substack.com",
    "https://yetanothervalueblog.substack.com",
    "https://www.weightythoughts.com",
    "https://chaufa.substack.com",
    "https://quantseeker.substack.com",
    "https://reboundcapital.substack.com",
    "https://stevesaretsky.substack.com",
    "https://macromusings.substack.com",
    "https://airlinerevenueeconomics.substack.com",
    "https://neilsethi.substack.com",
    "https://www.publicnotice.co",
    "https://lbmacro.substack.com",
    "https://quantumnomia.substack.com",
    "https://whirligigbear.substack.com",
    "https://therosenreport.substack.com",
    "https://helenemeisler.substack.com",
    "https://quantenthusiasts.substack.com",
    "https://www.commoditycontext.com",
    "https://energyoutlookadvisors.substack.com",
    "https://chartstorm.substack.com",
    "https://damnang.substack.com",
    "https://macrocharts.substack.com",
    "https://polimetrics.substack.com",
    "https://dualityresearch.substack.com",
    "https://www.capitalwars.com",
    "https://thesignal.substack.com",
    "https://asgoghie.substack.com",
    "https://worksinprogress.substack.com",
    "https://demographyunplugged.substack.com",
    "https://bojwatchtower.substack.com",
    "https://tscs.substack.com",
    "https://michaelwgreen.substack.com",
    "https://latinamericariskreport.substack.com",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}

def fetch_posts(base_url):
    api_url = f"{base_url.rstrip('/')}/api/v1/posts?limit=5"
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            posts = []
            for p in data:
                title = p.get("title", "")
                slug = p.get("slug", "")
                canonical = p.get("canonical_url") or f"{base_url}/p/{slug}"
                subtitle = p.get("subtitle") or p.get("description") or ""
                date = (p.get("post_date") or p.get("published_at") or "")[:10]
                if title:
                    posts.append({"title": title, "url": canonical, "date": date, "description": subtitle})
            return posts
    except Exception:
        pass
    return []

seen = set()
unique_urls = []
for u in URLS:
    if u not in seen:
        seen.add(u)
        unique_urls.append(u)

results = {}
for url in unique_urls:
    posts = fetch_posts(url)
    domain = urlparse(url).netloc
    results[domain] = posts
    status = f"{len(posts)} posts" if posts else "FAILED"
    print(f"{domain}: {status}")
    time.sleep(0.3)

with open("/Users/macproajb/claude_projects/reports/substack_posts.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\nDone. {len(results)} newsletters. Saved to substack_posts.json")
