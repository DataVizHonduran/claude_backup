"""Shared utility: rebuild reports/cb-monitor/index.html from all watcher dirs."""
from __future__ import annotations
import sys
from pathlib import Path

_CSS = """        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 1100px; margin: 0 auto; padding: 20px;
               background: #f5f5f5; color: #333; }
        .page-header { background: white; padding: 24px 32px; border-radius: 8px;
                       box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin-bottom: 24px; }
        .page-header h1 { color: #1a237e; border-bottom: 3px solid #1a237e;
                          padding-bottom: 10px; margin: 0 0 8px; }
        .back-link { display: inline-block; color: #1a237e; text-decoration: none;
                     margin-bottom: 12px; font-size: 0.9em; }
        .back-link:hover { text-decoration: underline; }
        .card-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
        @media (max-width: 900px) { .card-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 580px) { .card-grid { grid-template-columns: 1fr; } }
        .card { background: white; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);
                padding: 20px; display: flex; flex-direction: column; }
        .card-summary { font-size: 1.05em; font-weight: 700; color: #1a237e;
                        border-left: 4px solid #1a237e; padding-left: 10px; margin: 0 0 8px;
                        cursor: pointer; list-style: none; }
        .card-summary::-webkit-details-marker { display: none; }
        .card-summary::after { content: " ▾"; font-size: 0.85em; color: #999; }
        details:not([open]) > .card-summary::after { content: " ▸"; }
        .card-desc { font-size: 0.82em; color: #666; line-height: 1.4; margin: 0 0 14px; }
        .latest-link { display: block; background: #1a237e; color: white; text-decoration: none;
                       padding: 8px 12px; border-radius: 5px; font-size: 0.88em; font-weight: 600;
                       text-align: center; margin-bottom: 10px; }
        .latest-link:hover { background: #283593; }
        .badge { font-size: 0.72em; background: #e8f5e9; color: #2e7d32;
                 padding: 2px 6px; border-radius: 8px; margin-left: 6px; }
        .archive-toggle { margin-top: 4px; }
        .archive-toggle summary { font-size: 0.82em; color: #3949ab; cursor: pointer;
                                  user-select: none; padding: 4px 0; list-style: none; }
        .archive-toggle summary::-webkit-details-marker { display: none; }
        .archive-toggle summary::before { content: "▶ "; font-size: 0.75em; }
        .archive-toggle[open] summary::before { content: "▼ "; }
        .archive-toggle summary:hover { color: #1a237e; }
        .archive-list { list-style: none; padding: 0; margin: 6px 0 0; }
        .archive-list li { padding: 4px 0; border-bottom: 1px solid #f0f0f0; }
        .archive-list li:last-child { border-bottom: none; }
        .archive-list a { color: #3949ab; text-decoration: none; font-size: 0.82em; }
        .archive-list a:hover { text-decoration: underline; }
        .report-date { color: #aaa; font-size: 0.78em; float: right; }
        .no-reports { color: #aaa; font-style: italic; font-size: 0.85em; }"""

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
    cards_html = []
    for title, dir_name, glob_pat, prefix, label, desc in _SECTIONS:
        watcher_dir = repo_root / "reports" / dir_name
        reports = sorted(watcher_dir.glob(glob_pat), reverse=True) if watcher_dir.exists() else []
        if reports:
            latest = reports[0]
            latest_date = latest.stem[len(prefix):]
            latest_html = (
                f'        <a href="../{dir_name}/{latest.name}" class="latest-link">'
                f'{label} — {latest_date} <span class="badge">latest</span></a>\n'
            )
            archive = reports[1:]
            if archive:
                items = []
                for p in archive:
                    date_str = p.stem[len(prefix):]
                    items.append(
                        f'                <li><a href="../{dir_name}/{p.name}">{date_str}</a>'
                        f'<span class="report-date">{date_str}</span></li>'
                    )
                archive_html = (
                    f'        <details class="archive-toggle">\n'
                    f'            <summary>Archive ({len(archive)} reports)</summary>\n'
                    f'            <ul class="archive-list">\n' + "\n".join(items) + '\n            </ul>\n'
                    f'        </details>\n'
                )
            else:
                archive_html = ""
        else:
            latest_html = '        <p class="no-reports">No reports yet.</p>\n'
            archive_html = ""
        cards_html.append(
            f'\n    <div class="card">\n'
            f'        <details open>\n'
            f'            <summary class="card-summary">{title}</summary>\n'
            f'        <div class="card-desc">{desc}</div>\n'
            f'{latest_html}{archive_html}'
            f'        </details>\n    </div>'
        )
    hub = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '    <title>Central Bank Monitor</title>\n'
        f'    <style>\n{_CSS}\n    </style>\n</head>\n<body>\n'
        '<div class="page-header">\n'
        '    <a href="../../index.html" class="back-link">← Back to Portfolio</a>\n'
        '    <h1>\U0001f3e6 Central Bank Monitor</h1>\n</div>\n'
        '<div class="card-grid">\n'
        + "".join(cards_html)
        + '\n</div>\n</body>\n</html>\n'
    )
    (cb_dir / "index.html").write_text(hub, encoding="utf-8")
    print(f"[cb-monitor] Hub updated: {cb_dir / 'index.html'}", file=sys.stderr)
