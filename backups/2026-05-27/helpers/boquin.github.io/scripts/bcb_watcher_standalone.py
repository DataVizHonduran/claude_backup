#!/usr/bin/env python3
"""
BCB Watcher — Standalone Script
Mirrors rba_watcher_standalone.py for Brazil's COPOM (Comitê de Política Monetária).

Data sources (zero paid APIs):
  - api.bcb.gov.br — Selic rate history via SGS series 432 (public, no auth)
  - Google News RSS — financial media coverage (feedparser)
  NOTE: bcb.gov.br is a JavaScript/SharePoint SPA with no accessible static API.
        Official document content is captured via SGS rate data + media coverage.

LLM layer:
  - HuggingFace Inference API (google/gemma-4-31B-it)

Usage:
    HF_TOKEN=hf_xxx python3 scripts/bcb_watcher_standalone.py
    HF_TOKEN=hf_xxx python3 scripts/bcb_watcher_standalone.py --days 14
    HF_TOKEN=hf_xxx python3 scripts/bcb_watcher_standalone.py --dry-run
    HF_TOKEN=hf_xxx python3 scripts/bcb_watcher_standalone.py --fetch-articles

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/bcb-watcher/bcb-watcher-YYYY-MM-DD.html
    reports/bcb-watcher/bcb-watcher-YYYY-MM-DD.md
"""

import os
import sys
import re
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from pathlib import Path

import requests
import feedparser
import markdown as md_lib
from bs4 import BeautifulSoup
from huggingface_hub import InferenceClient
from cb_monitor_utils import regenerate_cb_monitor

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID = "google/gemma-4-31B-it"

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BCBWatcher/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Encoding": "gzip, deflate",
}

RATE_LIMIT_SLEEP = 0.3

BCB_BASE     = "https://www.bcb.gov.br"
# Date-range endpoint — no per-call limit (ultimos/{n} caps at 20)
BCB_SGS_API  = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial={start}&dataFinal={end}"
BCB_FOCUS_API = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoTop5Inflacao12Meses?$filter=Indicador%20eq%20'IPCA'&$top=1&$format=json&$orderby=Data%20desc&$select=Indicador,Data,Media,Mediana"
# COPOM official documents (Comunicado + Ata) — may be geo-restricted to BR/Azure IPs
BCB_COPOM_DOCS_URL = "https://olinda.bcb.gov.br/olinda/service/DocumentosCopom/versao/v1/odata/Documentos"
BCB_COPOM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

NEWS_QUERIES = [
    '"Banco Central do Brasil" OR "BCB" OR "COPOM" interest rates inflation 2026',
    '"Gabriel Galipolo" COPOM rates Brazil 2026',
    '"Ailton Aquino" OR "Paulo Picchetti" OR "Diogo Abreu" BCB 2026',
    'COPOM "Selic" decision Brazil monetary policy 2026',
    '"IPCA" Brazil inflation "Banco Central" 2026',
    'Brazil real BRL "Banco Central" monetary policy 2026',
    'Brazil "taxa Selic" OR "Selic rate" COPOM hawk dove 2026',
]

# ---------------------------------------------------------------------------
# COPOM hawk/dove baselines — 9 members vote at every meeting (8/year)
# BCB DOES publish individual votes in atas (minutes) released ~6 weeks after.
# Galipolo-led board (all 9 from Lula administration as of 2025) has been
# aggressively hawkish — tightening cycle from 10.5% (Jan 2024) to 14.75% peak.
# ---------------------------------------------------------------------------
BASELINES = {
    # --- Governor ---
    "Gabriel Galipolo": (
        "Hawkish — President (Governor) since Jan 2025; Lula nominee but operationally hawkish; "
        "led aggressive tightening cycle from 10.5% to 14.75% peak; "
        "prioritizes inflation convergence to 3% target; Selic at 14.50% as of Jun 2026"
    ),
    # --- Deputy Governors ---
    "Ailton de Aquino Santos": (
        "Hawkish — Deputy Governor for Regulation; consistent supporter of tightening cycle; "
        "limited public commentary but votes in line with board consensus"
    ),
    "Carolina de Assis Barros": (
        "Neutral/Hawkish — Deputy Governor for Prudential and Exchange; "
        "focuses on financial stability and FX reserves; rarely deviates from board consensus"
    ),
    "Diogo Guilherme Abreu": (
        "Neutral — Deputy Governor for International Affairs; "
        "emphasis on external sector, CAE, and capital flows; limited domestic rate commentary"
    ),
    "Gilneu Francisco Astolfi Vivan": (
        "Neutral — Deputy Governor for Financial System Organization; "
        "operational/structural focus; limited monetary policy commentary"
    ),
    "Izabela Moreira Corrêa": (
        "Neutral — Deputy Governor for Institutional Relations and Citizenship; "
        "institutional communications focus; limited independent rate commentary"
    ),
    "Marcos Antonio Martins Pinto": (
        "Neutral/Hawkish — Deputy Governor for Financial Regulation; "
        "regulatory focus; limited public rate stance"
    ),
    "Paulo Picchetti": (
        "Hawkish — Deputy Governor for Economic Policy; "
        "chief economist of the board; key driver of rate decision rationale; "
        "research background in inflation dynamics and labor markets"
    ),
    "Rodrigo Alves Teixeira": (
        "Neutral — Deputy Governor for Administration; "
        "administrative role; minimal rate commentary"
    ),
}

ROLES = {
    "Gabriel Galipolo":            "Presidente (Governor)",
    "Ailton de Aquino Santos":     "Diretor de Regulação",
    "Carolina de Assis Barros":    "Diretora Prudencial e Câmbio",
    "Diogo Guilherme Abreu":       "Diretor de Assuntos Internacionais",
    "Gilneu Francisco Astolfi Vivan": "Diretor de Organização do SFN",
    "Izabela Moreira Corrêa":      "Diretora de Relacionamento Institucional",
    "Marcos Antonio Martins Pinto": "Diretor de Regulação Financeira",
    "Paulo Picchetti":             "Diretor de Política Econômica",
    "Rodrigo Alves Teixeira":      "Diretor de Administração",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> requests.Response | None:
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=BASE_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                time.sleep(RATE_LIMIT_SLEEP)
                return resp
            if resp.status_code in (429, 503):
                wait = 30 * (attempt + 1)
                print(f"  Rate limited ({resp.status_code}) — waiting {wait}s ...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  HTTP {resp.status_code} for {url}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Fetch error ({url}): {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    return None


def _soup(url: str) -> BeautifulSoup | None:
    resp = _get(url)
    if resp is None:
        return None
    return BeautifulSoup(resp.text, "html.parser")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_rss_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _parse_bcb_date(text: str) -> datetime | None:
    """Parse BCB date strings: '16/04/2026', '2026-04-16', 'April 16, 2026', etc."""
    text = text.strip()
    patterns = [
        ("%d/%m/%Y",  r"\d{1,2}/\d{1,2}/\d{4}"),
        ("%Y-%m-%d",  r"\d{4}-\d{2}-\d{2}"),
        ("%B %d, %Y", r"\w+ \d{1,2}, \d{4}"),
        ("%d %B %Y",  r"\d{1,2} \w+ \d{4}"),
    ]
    for fmt, pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return datetime.strptime(m.group(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Layer 1: BCB SGS API — Selic rate decisions
# BCB's bcb.gov.br is a JavaScript SPA backed by authenticated SharePoint;
# the public api.bcb.gov.br SGS endpoint is the accessible official data source.
# ---------------------------------------------------------------------------

def fetch_selic_decisions(days: int = 90) -> list[dict]:
    """
    Fetch Selic target rate history from BCB SGS series 432 (date-range endpoint).
    Returns one entry per rate change detected, labelled as COPOM rate decisions.
    """
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=max(days, 90))
    url = BCB_SGS_API.format(
        start=start_dt.strftime("%d/%m/%Y"),
        end=end_dt.strftime("%d/%m/%Y"),
    )
    print(f"Fetching Selic rate history from BCB SGS API ...", file=sys.stderr)
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            print(f"  SGS API returned {resp.status_code}", file=sys.stderr)
            return []
        data = resp.json()
    except Exception as e:
        print(f"  SGS API error: {e}", file=sys.stderr)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items = []
    prev_rate = None
    current_rate = None

    for row in data:
        try:
            rate = float(row["valor"])
            dt = datetime.strptime(row["data"], "%d/%m/%Y").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        current_rate = rate
        if prev_rate is not None and rate != prev_rate:
            if dt >= cutoff:
                change_bp = round((rate - prev_rate) * 100)
                direction = "cut" if change_bp < 0 else "hike"
                items.append({
                    "source":  "BCB SGS — COPOM Rate Decision",
                    "date":    dt.strftime("%Y-%m-%d"),
                    "title":   f"COPOM {direction} {abs(change_bp)}bps: Selic {prev_rate:.2f}% → {rate:.2f}%",
                    "speaker": "COPOM",
                    "url":     f"{BCB_BASE}/en/monetarypolicy/copomcommunique",
                    "text":    (
                        f"Selic target rate changed by {change_bp:+d}bps on {dt.strftime('%Y-%m-%d')}. "
                        f"New rate: {rate:.2f}%. Previous rate: {prev_rate:.2f}%."
                    ),
                })
        prev_rate = rate

    if current_rate is not None:
        print(f"  Current Selic rate: {current_rate:.2f}% | Rate changes in last {days}d: {len(items)}", file=sys.stderr)
    return items


def fetch_copom_documents(days: int = 90) -> list[dict]:
    """
    Fetch official COPOM Comunicados (rate decision statements) and Atas (minutes)
    from the BCB DocumentosCopom OLINDA OData API.
    Endpoint may be geo-restricted to Brazilian/Azure IPs; gracefully returns []
    on 403 so dry-runs pass locally — will succeed in GitHub Actions.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    params = {
        "$format":  "json",
        "$orderby": "DataPublicacao desc",
        "$select":  "NumeroReuniao,DataPublicacao,TipoDocumento,UrlEnglish",
        "$top":     "10",
    }
    headers = {
        "User-Agent": BCB_COPOM_UA,
        "Accept":     "application/json",
        "Referer":    "https://www.bcb.gov.br/",
    }
    print("Fetching COPOM documents from BCB OLINDA API ...", file=sys.stderr)
    try:
        resp = requests.get(BCB_COPOM_DOCS_URL, params=params, headers=headers, timeout=20)
        if resp.status_code == 403:
            print("  COPOM OLINDA 403 — likely geo-restricted; skipping (will succeed in CI).", file=sys.stderr)
            return []
        if resp.status_code != 200:
            print(f"  COPOM OLINDA returned {resp.status_code}", file=sys.stderr)
            return []
        rows = resp.json().get("value", [])
    except Exception as e:
        print(f"  COPOM OLINDA error: {e}", file=sys.stderr)
        return []

    items = []
    for row in rows:
        tipo = row.get("TipoDocumento", "")
        if tipo not in ("Comunicado", "Ata"):
            continue

        raw_date = row.get("DataPublicacao", "")
        # BCB returns ISO format: '2026-03-19T00:00:00' or '2026-03-19'
        pub_dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                pub_dt = datetime.strptime(raw_date[:19] if "T" in raw_date else raw_date, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

        if pub_dt and pub_dt < cutoff:
            continue

        date_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else raw_date[:10]
        reuniao  = row.get("NumeroReuniao", "")
        url_en   = row.get("UrlEnglish", "") or f"{BCB_BASE}/en/monetarypolicy/copomcommunique"
        source_label = "COPOM Comunicado (Rate Statement)" if tipo == "Comunicado" else "COPOM Ata (Minutes)"

        items.append({
            "source":  source_label,
            "date":    date_str,
            "title":   f"COPOM Meeting #{reuniao} — {tipo} ({date_str})",
            "speaker": "COPOM",
            "url":     url_en,
            "text":    f"Official {tipo} for COPOM meeting #{reuniao} published {date_str}. See: {url_en}",
        })

    print(f"  COPOM documents fetched: {len(items)} (Comunicados + Atas)", file=sys.stderr)
    return items


def fetch_ipca_expectations() -> list[dict]:
    """Fetch BCB Focus top-5 IPCA consensus expectations for context."""
    print("Fetching IPCA consensus expectations (BCB Focus) ...", file=sys.stderr)
    try:
        resp = requests.get(BCB_FOCUS_API, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json().get("value", [])
        if not data:
            return []
        row = data[0]
        return [{
            "source":  "BCB Focus — IPCA 12m Consensus",
            "date":    row.get("Data", ""),
            "title":   f"Top-5 IPCA 12m consensus: mean {row.get('Media', 'n/a')}%, median {row.get('Mediana', 'n/a')}%",
            "speaker": "BCB Market Survey",
            "url":     f"{BCB_BASE}/en/monetarypolicy/inflation-expectations",
            "text":    (
                f"BCB Focus survey top-5 IPCA 12-month expectation as of {row.get('Data','n/a')}: "
                f"mean {row.get('Media','n/a')}%, median {row.get('Mediana','n/a')}%. "
                f"Target: 3.0% ±1.5pp."
            ),
        }]
    except Exception as e:
        print(f"  Focus API error: {e}", file=sys.stderr)
        return []


def scrape_bcb_speeches(days: int = 30) -> list[dict]:
    """
    Attempt to scrape BCB speech listings. bcb.gov.br is an Angular SPA backed
    by authenticated SharePoint — direct scraping is not possible without session
    cookies. Returns empty list gracefully; media coverage via news queries
    captures official speech content.
    """
    print("BCB speech scraping skipped (site is JS SPA / requires auth). Using news layer.", file=sys.stderr)
    return []


def fetch_article_text(url: str, max_chars: int = 3000) -> str:
    if not url or "pdf" in url.lower():
        return ""
    resp = _get(url, timeout=30)
    if not resp:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = (
        soup.select_one("article, .speech-content, .content-body, main, #main, #content")
        or soup.body
    )
    if not body:
        return ""
    text = re.sub(r"\s{3,}", "\n\n", body.get_text(separator=" ", strip=True))
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Layer 2: Google News RSS
# ---------------------------------------------------------------------------

def search_google_news(query: str, max_results: int = 10) -> list[dict]:
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_results]:
        pub_date = _parse_rss_date(entry)
        items.append({
            "source":  "Google News RSS",
            "query":   query,
            "date":    pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title":   getattr(entry, "title", ""),
            "url":     getattr(entry, "link", ""),
            "summary": _strip_html(getattr(entry, "summary", "")),
        })
    return items


def search_news(queries: list[str], days: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen_urls: set[str] = set()
    results = []

    for q in queries:
        print(f"  News search: {q[:60]} ...", file=sys.stderr)
        for item in search_google_news(q):
            if item["url"] in seen_urls:
                continue
            if item["date"]:
                try:
                    d = datetime.fromisoformat(item["date"]).replace(tzinfo=timezone.utc)
                    if d < cutoff:
                        continue
                except ValueError:
                    pass
            seen_urls.add(item["url"])
            results.append(item)
        time.sleep(0.5)

    print(f"  Total news items after dedup: {len(results)}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_context_prompt(
    selic_decisions: list[dict],
    copom_documents: list[dict],
    ipca_expectations: list[dict],
    speeches: list[dict],
    news: list[dict],
    days: int,
    today: str,
) -> str:

    def _fmt_items(items: list[dict], include_text: bool = True) -> str:
        parts = []
        for it in items:
            chunk = f"[{it.get('date', 'n/a')}] {it.get('title', '')} — {it.get('speaker', it.get('source', ''))}"
            if it.get("url"):
                chunk += f"\nURL: {it['url']}"
            body = it.get("text") or it.get("summary", "")
            if include_text and body:
                chunk += f"\nExcerpt: {body[:800]}"
            parts.append(chunk)
        return "\n\n".join(parts) if parts else "(none found)"

    baselines_md = "\n".join(
        f"- {k} ({ROLES.get(k, 'Member')}): {v}" for k, v in BASELINES.items()
    )

    official_docs = selic_decisions + copom_documents + ipca_expectations
    note_on_bcb_site = (
        "NOTE: bcb.gov.br is a JavaScript SPA backed by authenticated SharePoint. "
        "Speech transcripts and COPOM minutes are not directly scrappable. "
        "COPOM decisions are sourced from BCB's public SGS time series (api.bcb.gov.br). "
        "Financial media in the news section provides coverage of official statements, "
        "speeches, and COPOM minutes summaries."
    )

    prompt = f"""You are a Brazilian monetary policy analyst producing a BCB Watcher report.
Today: {today}
Coverage period: last {days} days

## Known Hawk/Dove Baselines (use as prior, only override with direct evidence)
{baselines_md}

---

## DATA GATHERED

### 1. Official BCB Data — COPOM Documents, Selic Decisions & IPCA Expectations ({len(official_docs)} items)
{_fmt_items(official_docs)}

### 2. BCB Official Speeches
{note_on_bcb_site}
(0 items — see financial news section for speech coverage)

### 3. Financial News ({len(news)} items)
{_fmt_items(news, include_text=False)}

---

## REQUIRED OUTPUT

Produce the full BCB Watcher report in this exact structure:

### Executive Summary (≤150 words)
Brief overview of the most significant COPOM decisions and member communications from the past {days} days.

### COPOM Member Pronouncements

| Date | Official | Role | Venue/Context | Key Statement | Policy Signal | Evolution vs Baseline |
|------|----------|------|---------------|---------------|---------------|-----------------------|

### Official COPOM Communications

| Date | Document Type | Title | Key Takeaways | Policy Implications |
|------|---------------|-------|---------------|---------------------|

### Thematic Analysis

**1. IPCA & Inflation Outlook (IPCA vs 3% target, core IPCA)**
**2. Labor Market (CAGED, unemployment, wages)**
**3. Fiscal Policy & Public Debt (primary surplus/deficit, debt/GDP)**
**4. BRL / External Sector (exchange rate, current account, capital flows)**
**5. Neutral Rate Estimate & Real Rate Stance (r* estimates, real ex-ante rate)**
**6. Forward Guidance Evolution (pace of easing/tightening, conditionality)**

### Hawk-Dove Spectrum Analysis

```
HAWKISH (favor slower easing / higher-for-longer / tightening)
├─ [Names and recent positioning]

NEUTRAL/DATA-DEPENDENT
├─ [Names and recent positioning]

DOVISH (favor faster easing / lower rates)
└─ [Names and recent positioning]
```

**Key Shifts Identified:**

### All 9 COPOM Members Focus

| Official | Role | Current Stance | Key Quote |
|----------|------|----------------|-----------|

### Dissent Watch
(Note: BCB publishes individual member votes in atas (minutes) ~6 weeks after each meeting.
Flag any known vote dissents or speech-based divergence from consensus.)

---

Rules:
- Only cite verifiable information from the data above.
- If an official has no statements in the data, note "No public comments found".
- Policy Signal classification: Hawkish / Dovish / Neutral / Mixed
- 90-DAY RECENCY RULE: Only reference specific prior statements when they appear in the data above; otherwise use "Consistent with historical [lean] baseline".
- Key BCB-specific context:
  - Selic target rate: 14.50% (as of June 2026; aggressive tightening from 10.5% Jan 2024 low)
  - Inflation gauge: IPCA (headline), IPCA-EX (core ex-food/energy); target 3.0% ±1.5pp
  - COPOM meets 8×/year; atas (minutes) published ~6 weeks after meeting
  - Relatório de Política Monetária (RPM) published quarterly
  - All 9 board members: Governor + 8 Deputy Governors (Diretores)
  - Individual votes ARE published in atas (rare for EM)
  - Key external risks: BRL volatility, fiscal credibility, US tariffs, commodity prices
  - Fiscal dominance risk: Lula government's spending plans create recurring tension with CB
"""
    return prompt


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_gemma(messages: list[dict], hf_token: str, max_tokens: int = 4096) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(5):
        try:
            stream = client.chat.completions.create(
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
                stream=True,
            )
            parts = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
                    print(delta, end="", flush=True)
            print()
            return "".join(parts)
        except Exception as e:
            is_rate_limit = any(x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if is_rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n  HF rate limit — waiting {wait}s (attempt {attempt+1}/5) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# HTML / output
# ---------------------------------------------------------------------------

HTML_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 1000px; margin: 0 auto; padding: 20px;
    line-height: 1.6; background: #f5f5f5; color: #333;
}
.container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
h1 { color: #009C3B; border-bottom: 3px solid #009C3B; padding-bottom: 10px; }
h2 { color: #009C3B; border-bottom: 2px solid #e6f7ee; padding-bottom: 6px; margin-top: 36px; }
h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
h4 { color: #555; margin-top: 20px; }
.meta { color: #777; font-size: 0.85em; margin: 6px 0 20px; }
.back-link { display: inline-block; margin-bottom: 20px; color: #009C3B; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }
th { background: #009C3B; color: white; padding: 10px 12px; text-align: left; }
td { border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }
pre code { background: none; padding: 0; }
blockquote {
    border-left: 4px solid #009C3B; margin: 16px 0; padding: 8px 16px;
    background: #e6f7ee; border-radius: 0 4px 4px 0; color: #333;
}
strong { color: #111; }
ul, ol { padding-left: 1.5em; }
li { margin: 4px 0; }
hr { border: none; border-top: 2px solid #eee; margin: 32px 0; }
a { color: #009C3B; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BCB Watcher — {date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">&#8592; BCB Watcher Archive</a>
    <h1>&#127463;&#127479; BCB Watcher &#8212; {date}</h1>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Coverage: last {days} days &nbsp;|&nbsp;
        Sources: BCB COPOM OLINDA &middot; BCB SGS API &middot; Google News RSS &nbsp;|&nbsp;
        Model: {model}
    </p>
    <hr>
    {body}
</div>
</body>
</html>"""

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BCB Watcher &#8212; Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #009C3B; border-bottom: 3px solid #009C3B; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #009C3B; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #009C3B; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
        .back-link {{ display: inline-block; margin-bottom: 20px; color: #009C3B; text-decoration: none; }}
        .back-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
<div class="container">
    <a href="../../index.html" class="back-link">&#8592; Back to Portfolio</a>
    <h1>&#127463;&#127479; BCB Watcher</h1>
    <p class="description">
        Banco Central do Brasil COPOM speeches, rate decisions, and monetary policy signals &#8212; tracked every 3 days
        using <strong>BCB SGS API</strong> and Google News RSS,
        analyzed by Gemma 4. All 9 COPOM members covered.
    </p>
    <ul class="report-list">
        {{items}}
    </ul>
</div>
</body>
</html>"""


def _markdown_to_html(md_text: str) -> str:
    return md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )


def regenerate_index(out_dir: Path) -> None:
    reports = sorted(out_dir.glob("bcb-watcher-*.html"), reverse=True)
    items = []
    for i, path in enumerate(reports):
        date_str = path.stem.replace("bcb-watcher-", "")
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">BCB Watcher &#8212; {date_str}{badge}</a>'
            f'<span class="report-date">{date_str}</span>'
            f'</li>'
        )
    (out_dir / "index.html").write_text(
        INDEX_TEMPLATE.format(items="\n        ".join(items) if items else "<li>No reports yet.</li>"),
        encoding="utf-8",
    )


def save_output(report: str, today: str, out_dir: Path, days: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    md_header = (
        f"# BCB Watcher — {today}\n\n"
        f"**Generated:** {generated_at} UTC  \n"
        f"**Coverage:** {days} days ending {today}  \n"
        f"**Model:** {MODEL_ID}\n\n"
        "---\n\n"
    )
    md_path = out_dir / f"bcb-watcher-{today}.md"
    md_path.write_text(md_header + report, encoding="utf-8")

    body_html = _markdown_to_html(report)
    html_content = HTML_TEMPLATE.format(
        date=today,
        generated_at=generated_at,
        days=days,
        model=MODEL_ID,
        css=HTML_CSS,
        body=body_html,
    )
    html_path = out_dir / f"bcb-watcher-{today}.html"
    html_path.write_text(html_content, encoding="utf-8")

    regenerate_index(out_dir)
    regenerate_cb_monitor(out_dir.parent.parent)

    print(f"\nMarkdown : {md_path}", file=sys.stderr)
    print(f"HTML     : {html_path}", file=sys.stderr)
    print(f"Index    : {out_dir / 'index.html'}", file=sys.stderr)
    return html_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BCB Watcher — standalone scrape + LLM analysis")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to write output files (default: reports/bcb-watcher/)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip LLM call and file write")
    parser.add_argument("--fetch-articles", action="store_true",
                        help="Fetch full article text for news items (slower, uses more tokens)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports/bcb-watcher")

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== BCB Watcher — {today} (lookback {args.days}d) ===", file=sys.stderr)

    # --- Scrape ---
    selic_decisions   = fetch_selic_decisions(days=max(args.days, 90))
    copom_documents   = fetch_copom_documents(days=max(args.days, 90))
    ipca_expectations = fetch_ipca_expectations()
    speeches          = scrape_bcb_speeches(days=args.days)
    news              = search_news(NEWS_QUERIES, days=args.days)

    if args.fetch_articles and not args.dry_run:
        print(f"Fetching article text for up to 10 news items ...", file=sys.stderr)
        for item in news[:10]:
            if item.get("url"):
                item["text"] = fetch_article_text(item["url"])

    total = len(selic_decisions) + len(copom_documents) + len(ipca_expectations) + len(news)
    print(f"\n--- Scrape summary ---", file=sys.stderr)
    print(f"  Selic decisions: {len(selic_decisions)}", file=sys.stderr)
    print(f"  COPOM docs:      {len(copom_documents)}", file=sys.stderr)
    print(f"  IPCA expectns:   {len(ipca_expectations)}", file=sys.stderr)
    print(f"  News items:      {len(news)}", file=sys.stderr)
    print(f"  TOTAL:           {total}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] Skipping LLM call.", file=sys.stderr)
        return

    if total == 0:
        print("No data gathered — aborting.", file=sys.stderr)
        sys.exit(1)

    # --- Build prompt ---
    context = build_context_prompt(selic_decisions, copom_documents, ipca_expectations, speeches, news, args.days, today)

    est_tokens = len(context) // 4
    print(f"\nContext prompt: ~{est_tokens:,} tokens", file=sys.stderr)
    if est_tokens > 90_000:
        print("  WARNING: prompt may exceed model context — truncating news.", file=sys.stderr)
        news = news[:20]
        context = build_context_prompt(selic_decisions, copom_documents, ipca_expectations, speeches, news, args.days, today)

    # --- LLM ---
    print("\n--- Calling Gemma 4 ---", file=sys.stderr)
    messages = [
        {"role": "system", "content": "You are a senior Brazilian monetary policy analyst at a top investment bank."},
        {"role": "user",   "content": context},
    ]
    report = call_gemma(messages, hf_token, max_tokens=4096)

    # --- Save ---
    save_output(report, today, out_dir, args.days)
    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
