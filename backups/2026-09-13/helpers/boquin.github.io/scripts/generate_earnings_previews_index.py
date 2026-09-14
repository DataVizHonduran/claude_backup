"""
Generate index.html for earnings preview reports.
Scans reports/earnings-previews/ for markdown files and creates a sortable table.
Filename convention: {TICKER}-preview-{YYYY-MM-DD}.md
"""

import os
import re
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = REPO_ROOT / "reports" / "earnings-previews"


def parse_preview_report(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    filename = os.path.basename(filepath)

    # Filename: TICKER-preview-YYYY-MM-DD.md
    match = re.match(r"^([A-Z0-9]+)-preview-(\d{4}-\d{2}-\d{2})\.md$", filename)
    ticker = match.group(1) if match else "Unknown"
    preview_date = match.group(2) if match else "Unknown"

    # H1 headline
    headline_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    headline = headline_match.group(1).strip() if headline_match else filename

    # Earnings date from the EARNINGS DATE table
    earnings_date_match = re.search(
        r"\*\*Earnings Date\*\*\s*\|\s*([A-Za-z]+ \d{1,2}, \d{4})", content
    )
    if earnings_date_match:
        try:
            earnings_date = datetime.strptime(
                earnings_date_match.group(1), "%B %d, %Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            earnings_date = "Unknown"
    else:
        # fallback: look for bare date near "Earnings Date"
        alt = re.search(r"Earnings Date.*?(\d{4}-\d{2}-\d{2})", content, re.DOTALL)
        earnings_date = alt.group(1) if alt else "Unknown"

    # Summary: first line of SUMMARY section
    summary_match = re.search(r"## SUMMARY\s+(.+?)(?:\n|$)", content, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()
        summary = re.sub(r"\*\*(.+?)\*\*", r"\1", summary)  # strip bold
    else:
        summary = headline

    return {
        "ticker": ticker,
        "headline": headline,
        "summary": summary[:160] + "..." if len(summary) > 160 else summary,
        "preview_date": preview_date,
        "earnings_date": earnings_date,
        "filename": filename,
    }


print(f"Scanning {OUTPUT_DIR} for earnings previews...")
reports = []

for file in sorted(Path(OUTPUT_DIR).glob("*-preview-*.md")):
    try:
        data = parse_preview_report(file)
        reports.append(data)
        print(f"  ✓ {data['ticker']} — earnings {data['earnings_date']}")
    except Exception as e:
        print(f"  ✗ Failed to parse {file.name}: {e}")

# Sort by preview date descending
reports.sort(key=lambda x: x["preview_date"], reverse=True)

print(f"\nFound {len(reports)} earnings previews")

now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

rows_html = ""
for r in reports:
    rows_html += f"""
                    <tr>
                        <td class="ticker">{r['ticker']}</td>
                        <td><a href="{r['filename']}" class="report-link">{r['summary']}</a></td>
                        <td class="date">{r['preview_date']}</td>
                        <td class="date">{r['earnings_date']}</td>
                    </tr>
"""

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Earnings Previews</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #28a745;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}
        .info-box {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .description {{ color: #555; margin-bottom: 15px; line-height: 1.6; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}
        .stat-item {{
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
            text-align: center;
        }}
        .stat-label {{ font-size: 0.9em; color: #666; margin-bottom: 5px; }}
        .stat-value {{ font-size: 1.5em; font-weight: bold; color: #333; }}
        .search-box {{ margin-bottom: 20px; }}
        .search-box input {{
            width: 100%;
            padding: 12px;
            font-size: 16px;
            border: 2px solid #dee2e6;
            border-radius: 6px;
            transition: border-color 0.3s;
        }}
        .search-box input:focus {{ outline: none; border-color: #28a745; }}
        .reports-table {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        table {{ width: 100%; border-collapse: collapse; }}
        thead {{ background: #28a745; color: white; }}
        th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            cursor: pointer;
            user-select: none;
        }}
        th:hover {{ background: #1e7e34; }}
        th::after {{ content: ' ↕'; opacity: 0.5; }}
        tbody tr {{
            border-bottom: 1px solid #dee2e6;
            transition: background-color 0.2s;
        }}
        tbody tr:hover {{ background: #f8f9fa; }}
        td {{ padding: 15px; }}
        .ticker {{ font-weight: bold; color: #28a745; font-size: 1.1em; }}
        .report-link {{ color: #333; text-decoration: none; font-weight: 500; }}
        .report-link:hover {{ color: #28a745; text-decoration: underline; }}
        .date {{ color: #666; font-size: 0.9em; }}
        .badge-upcoming {{
            background: #d4edda;
            color: #155724;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: 600;
        }}
        .last-updated {{
            text-align: center;
            color: #666;
            font-size: 0.9em;
            margin-top: 20px;
        }}
        @media (max-width: 768px) {{
            table {{ font-size: 0.9em; }}
            th, td {{ padding: 10px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔭 Earnings Previews</h1>

        <div class="info-box">
            <p class="description">
                Pre-earnings briefings built from Yahoo Finance data — consensus estimates,
                analyst sentiment, beat/miss track record, and key metrics to watch ahead of each report.
            </p>
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-label">Total Previews</div>
                    <div class="stat-value">{len(reports)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Companies Covered</div>
                    <div class="stat-value">{len(set(r['ticker'] for r in reports))}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Most Recent</div>
                    <div class="stat-value">{reports[0]['ticker'] if reports else 'N/A'}</div>
                </div>
            </div>
        </div>

        <div class="search-box">
            <input type="text" id="searchInput" placeholder="🔍 Search by ticker or keywords...">
        </div>

        <div class="reports-table">
            <table id="reportsTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">Ticker</th>
                        <th onclick="sortTable(1)">Preview</th>
                        <th onclick="sortTable(2)">Preview Date</th>
                        <th onclick="sortTable(3)">Earnings Date</th>
                    </tr>
                </thead>
                <tbody id="reportsBody">
{rows_html}
                </tbody>
            </table>
        </div>

        <div class="last-updated">Last updated: {now_str}</div>
    </div>

    <script>
        const searchInput = document.getElementById('searchInput');
        const reportsBody = document.getElementById('reportsBody');
        const rows = Array.from(reportsBody.querySelectorAll('tr'));

        searchInput.addEventListener('input', function() {{
            const term = this.value.toLowerCase();
            rows.forEach(row => {{
                row.style.display = row.textContent.toLowerCase().includes(term) ? '' : 'none';
            }});
        }});

        let sortDir = {{}};
        function sortTable(col) {{
            const tbody = document.getElementById('reportsBody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const key = `c${{col}}`;
            sortDir[key] = !sortDir[key];
            const asc = sortDir[key];
            rows.sort((a, b) => {{
                const at = a.cells[col].textContent.trim();
                const bt = b.cells[col].textContent.trim();
                if (col === 2 || col === 3) {{
                    const ad = new Date(at), bd = new Date(bt);
                    if (!isNaN(ad) && !isNaN(bd)) return asc ? ad - bd : bd - ad;
                }}
                return asc ? at.localeCompare(bt) : bt.localeCompare(at);
            }});
            rows.forEach(r => tbody.appendChild(r));
        }}
    </script>
</body>
</html>
"""

output_path = OUTPUT_DIR / "index.html"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"\n✅ Generated {output_path}")
