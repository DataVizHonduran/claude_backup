"""Shared utility: rebuild reports/cb-monitor/index.html from all watcher dirs."""
from __future__ import annotations
import sys
from pathlib import Path

_CSS = """        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 960px; margin: 0 auto; padding: 20px;
               background: #f5f5f5; color: #333; }
        .container { background: white; padding: 40px; border-radius: 8px;
                     box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
        h1 { color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 10px; }
        .cb-section { margin: 36px 0; }
        .cb-section h2 { color: #1a237e; border-left: 4px solid #1a237e;
                         padding-left: 12px; margin-bottom: 6px; font-size: 1.2em; }
        .section-desc { color: #555; margin: 0 0 14px; font-size: 0.95em; line-height: 1.5; }
        .report-list { list-style: none; padding: 0; margin: 0; }
        .report-list li { border-left: 4px solid #3949ab; padding: 10px 14px; margin: 8px 0;
                          background: #f8f9fa; border-radius: 0 6px 6px 0;
                          display: flex; align-items: center; justify-content: space-between; }
        .report-list a { color: #1a237e; text-decoration: none; font-weight: 500; font-size: 1em; }
        .report-list a:hover { text-decoration: underline; }
        .report-date { color: #888; font-size: 0.85em; }
        .badge-latest { font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
                        padding: 3px 8px; border-radius: 10px; margin-left: 8px; }
        .no-reports { color: #aaa; font-style: italic; }
        .back-link { display: inline-block; margin-bottom: 20px; color: #1a237e; text-decoration: none; }
        .back-link:hover { text-decoration: underline; }"""

# Each entry: (html_title, dir_name, glob, filename_prefix, display_label, description)
_SECTIONS = [
    ("🏛️ Fed District Monitor", "fed-monitor", "fed-district-monitor-*.html",
     "fed-district-monitor-", "Fed District Monitor",
     "Federal Reserve district research publications and economic analysis tracking."),
    ("🦅 US Fed Watcher", "fed-watcher", "fed-watcher-*.html",
     "fed-watcher-", "Fed Watcher",
     "FOMC member speeches, testimonies, and policy signals tracked every 3 days — hawk/dove spectrum, thematic analysis, and dissent watch, powered by Gemma 4."),
    ("📋 FOMC Statement Analyzer", "fomc-analyzer", "fomc-*.html",
     "fomc-", "FOMC Analysis",
     "Redline comparison of consecutive FOMC policy statements — thematic shifts in inflation and forward guidance language, and a hawkish/dovish tonal verdict, powered by Gemma 4."),
    ("🇪🇺 ECB &amp; Eurozone Monitor", "ecb-monitor", "ecb-monitor-*.html",
     "ecb-monitor-", "ECB Monitor",
     "Daily AI-enriched research digest from ECB, Bundesbank, Banque de France, Banca d’Italia, Banco de España, DNB, and Central Bank of Ireland — powered by Gemma 4."),
    ("🏦 ECB Watcher", "ecb-watcher", "ecb-watcher-*.html",
     "ecb-watcher-", "ECB Watcher",
     "All 25 Governing Council members tracked every 3 days — hawk/dove spectrum, thematic analysis, dissent watch, and policy signal evolution, powered by Gemma 4."),
    ("🇯🇵 BOJ Watcher", "boj-watcher", "boj-watcher-*.html",
     "boj-watcher-", "BOJ Watcher",
     "All 9 Policy Board members tracked every 3 days — hawk/dove spectrum, yen/inflation thematic analysis, and dissent watch, powered by Gemma 4."),
    ("🇦🇺 RBA Watcher", "rba-watcher", "rba-watcher-*.html",
     "rba-watcher-", "RBA Watcher",
     "All 9 Monetary Policy Board members tracked every 3 days — hawk/dove spectrum, trimmed mean CPI, labor market and AUD thematic analysis, powered by Gemma 4."),
    ("🇲🇽 Banxico Watcher", "banxico-watcher", "banxico-watcher-*.html",
     "banxico-watcher-", "Banxico Watcher",
     "All 5 Junta de Gobierno members tracked every 3 days — hawk/dove spectrum, core CPI, MXN dynamics, and individual vote dissent watch, powered by Gemma 4."),
    ("🇨🇦 BOC Watcher", "boc-watcher", "boc-watcher-*.html",
     "boc-watcher-", "BOC Watcher",
     "All 6 Governing Council members tracked every 3 days — hawk/dove spectrum, CPI-trim/median, CAD dynamics, and housing market thematic analysis, powered by Gemma 4."),
    ("🇧🇷 BCB Watcher", "bcb-watcher", "bcb-watcher-*.html",
     "bcb-watcher-", "BCB Watcher",
     "All 9 COPOM members tracked every 3 days — hawk/dove spectrum, IPCA inflation, BRL dynamics, and individual vote dissent watch, powered by Gemma 4."),
    ("🇨🇭 SNB Watcher", "snb-watcher", "snb-watcher-*.html",
     "snb-watcher-", "SNB Watcher",
     "All 3 Governing Board members tracked every 3 days — CHF/FX intervention, CPI 0-2% target, negative rate risk, powered by Gemma 4."),
    ("🇸🇪 Riksbank Watcher", "riksbank-watcher", "riksbank-watcher-*.html",
     "riksbank-watcher-", "Riksbank Watcher",
     "All 5 Executive Board members tracked every 3 days — hawk/dove spectrum, CPIF inflation, SEK dynamics, and individual vote dissent watch, powered by Gemma 4."),
]


def add_section(title: str, dir_name: str, glob_pat: str, prefix: str, label: str, desc: str) -> None:
    """Register a new central bank section. Call before regenerate_cb_monitor runs."""
    _SECTIONS.append((title, dir_name, glob_pat, prefix, label, desc))


def regenerate_cb_monitor(repo_root: Path) -> None:
    """Rebuild reports/cb-monitor/index.html from all watcher directories."""
    cb_dir = repo_root / "reports" / "cb-monitor"
    if not cb_dir.exists():
        return
    sections_html = []
    for title, dir_name, glob_pat, prefix, label, desc in _SECTIONS:
        watcher_dir = repo_root / "reports" / dir_name
        reports = sorted(watcher_dir.glob(glob_pat), reverse=True) if watcher_dir.exists() else []
        if reports:
            items = []
            for i, p in enumerate(reports):
                badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
                date_str = p.stem[len(prefix):]
                items.append(
                    f'        <li><a href="../{dir_name}/{p.name}">{label} — {date_str}{badge}</a>'
                    f'<span class="report-date">{date_str}</span></li>'
                )
            list_html = "\n".join(items)
        else:
            list_html = '        <li class="no-reports">No reports yet.</li>'
        sections_html.append(
            f'\n    <section class="cb-section">\n        <h2>{title}</h2>\n'
            f'        <p class="section-desc">{desc}</p>\n'
            f'        <ul class="report-list">\n{list_html}\n        </ul>\n    </section>'
        )
    hub = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '    <title>Central Bank Monitor</title>\n'
        f'    <style>\n{_CSS}\n    </style>\n</head>\n<body>\n<div class="container">\n'
        '    <a href="../../index.html" class="back-link">← Back to Portfolio</a>\n'
        '    <h1>\U0001f3e6 Central Bank Monitor</h1>\n'
        + "".join(sections_html)
        + '\n</div>\n</body>\n</html>\n'
    )
    (cb_dir / "index.html").write_text(hub, encoding="utf-8")
    print(f"[cb-monitor] Hub updated: {cb_dir / 'index.html'}", file=sys.stderr)
