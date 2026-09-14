"""
Generate index.html for earnings reports
Scans reports/earnings/ for markdown files and creates a sortable table
"""

import os
import re
from datetime import datetime
from pathlib import Path

# Get the parent directory (boquin.github.io)
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = REPO_ROOT / "reports" / "earnings"

def parse_earnings_report(filepath):
    """Extract metadata from earnings report markdown file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract headline (first H1)
    headline_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    headline = headline_match.group(1) if headline_match else "No headline"

    # Extract filename first (format: TICKER-YYYY-MM-DD.md)
    filename = os.path.basename(filepath)

    # Extract ticker from filename (TICKER-YYYY-MM-DD.md)
    filename_ticker_match = re.search(r'^([A-Z0-9]+)-\d{4}-\d{2}-\d{2}\.md$', filename)
    ticker = filename_ticker_match.group(1) if filename_ticker_match else "Unknown"
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    report_date = date_match.group(1) if date_match else "Unknown"

    # Extract earnings date from the report if available
    earnings_date_match = re.search(r'Earnings Release Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})', content)
    if earnings_date_match:
        earnings_date_str = earnings_date_match.group(1)
        try:
            earnings_date_obj = datetime.strptime(earnings_date_str, '%B %d, %Y')
            earnings_date = earnings_date_obj.strftime('%Y-%m-%d')
        except:
            # Try alternate format from press release style
            alt_match = re.search(r'Most Recent Earnings Release:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})', content)
            if alt_match:
                earnings_date = alt_match.group(1)
            else:
                earnings_date = "Unknown"
    else:
        earnings_date = "Unknown"

    # Extract summary (first bullet point from Executive Summary)
    summary_match = re.search(r'## EXECUTIVE SUMMARY\s+\*\s+\*\*(.+?)\*\*', content, re.DOTALL)
    summary = summary_match.group(1).strip() if summary_match else headline

    return {
        'ticker': ticker,
        'headline': headline,
        'summary': summary[:150] + '...' if len(summary) > 150 else summary,
        'report_date': report_date,
        'earnings_date': earnings_date,
        'filename': filename
    }

# Scan for earnings reports
print(f"Scanning {OUTPUT_DIR} for earnings reports...")
reports = []

for file in Path(OUTPUT_DIR).glob('*.md'):
    if file.name == 'README.md':  # Skip README files
        continue
    try:
        report_data = parse_earnings_report(file)
        reports.append(report_data)
        print(f"  ✓ Parsed {report_data['ticker']}")
    except Exception as e:
        print(f"  ✗ Failed to parse {file.name}: {e}")

# Sort reports by report_date (newest first)
reports.sort(key=lambda x: x['report_date'], reverse=True)

# Deduplicate: keep only the most recent report per ticker
seen_tickers = set()
deduplicated_reports = []
for report in reports:
    if report['ticker'] not in seen_tickers:
        deduplicated_reports.append(report)
        seen_tickers.add(report['ticker'])

reports = deduplicated_reports

print(f"\nFound {len(reports)} earnings reports (deduplicated by ticker)")

# Generate HTML content
html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Earnings Tearsheets</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        h1 {{
            color: #333;
            border-bottom: 3px solid #007bff;
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

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}

        .stat-item {{
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
            text-align: center;
        }}

        .stat-label {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }}

        .stat-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #333;
        }}

        .search-box {{
            margin-bottom: 20px;
        }}

        .search-box input {{
            width: 100%;
            padding: 12px;
            font-size: 16px;
            border: 2px solid #dee2e6;
            border-radius: 6px;
            transition: border-color 0.3s;
        }}

        .search-box input:focus {{
            outline: none;
            border-color: #007bff;
        }}

        .reports-table {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
        }}

        thead {{
            background: #007bff;
            color: white;
        }}

        th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            cursor: pointer;
            user-select: none;
        }}

        th:hover {{
            background: #0056b3;
        }}

        th::after {{
            content: ' ↕';
            opacity: 0.5;
        }}

        tbody tr {{
            border-bottom: 1px solid #dee2e6;
            transition: background-color 0.2s;
        }}

        tbody tr:hover {{
            background: #f8f9fa;
        }}

        td {{
            padding: 15px;
        }}

        .ticker {{
            font-weight: bold;
            color: #007bff;
            font-size: 1.1em;
        }}

        .quarter {{
            background: #e7f3ff;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.9em;
            color: #0056b3;
            white-space: nowrap;
        }}

        .report-link {{
            color: #007bff;
            text-decoration: none;
            font-weight: 500;
        }}

        .report-link:hover {{
            text-decoration: underline;
        }}

        .date {{
            color: #666;
            font-size: 0.9em;
        }}

        .last-updated {{
            text-align: center;
            color: #666;
            font-size: 0.9em;
            margin-top: 20px;
        }}

        @media (max-width: 768px) {{
            table {{
                font-size: 0.9em;
            }}

            th, td {{
                padding: 10px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 Earnings Tearsheets</h1>

        <div class="info-box">
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-label">Total Reports</div>
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
            <input type="text" id="searchInput" placeholder="🔍 Search by ticker, quarter, or keywords...">
        </div>

        <div class="reports-table">
            <table id="reportsTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">Ticker</th>
                        <th onclick="sortTable(1)">Headline</th>
                        <th onclick="sortTable(2)">Report Date</th>
                        <th onclick="sortTable(3)">Earnings Date</th>
                    </tr>
                </thead>
                <tbody id="reportsBody">
"""

# Add table rows
for report in reports:
    html_content += f"""
                    <tr>
                        <td class="ticker">{report['ticker']}</td>
                        <td><a href="{report['filename']}" class="report-link">{report['summary']}</a></td>
                        <td class="date">{report['report_date']}</td>
                        <td class="date">{report['earnings_date']}</td>
                    </tr>
"""

html_content += f"""
                </tbody>
            </table>
        </div>

        <div class="last-updated">
            Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
        </div>
    </div>

    <script>
        // Search functionality
        const searchInput = document.getElementById('searchInput');
        const reportsBody = document.getElementById('reportsBody');
        const rows = Array.from(reportsBody.querySelectorAll('tr'));

        searchInput.addEventListener('input', function() {{
            const searchTerm = this.value.toLowerCase();

            rows.forEach(row => {{
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(searchTerm) ? '' : 'none';
            }});
        }});

        // Sort table functionality
        let sortDirection = {{}};

        function sortTable(columnIndex) {{
            const table = document.getElementById('reportsTable');
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            // Determine sort direction
            const key = `col${{columnIndex}}`;
            sortDirection[key] = !sortDirection[key];
            const ascending = sortDirection[key];

            rows.sort((a, b) => {{
                const aText = a.cells[columnIndex].textContent.trim();
                const bText = b.cells[columnIndex].textContent.trim();

                // Try to parse as date for date columns
                if (columnIndex === 2 || columnIndex === 3) {{
                    const aDate = new Date(aText);
                    const bDate = new Date(bText);
                    if (!isNaN(aDate) && !isNaN(bDate)) {{
                        return ascending ? aDate - bDate : bDate - aDate;
                    }}
                }}

                // Default string comparison
                return ascending
                    ? aText.localeCompare(bText)
                    : bText.localeCompare(aText);
            }});

            // Re-append rows in sorted order
            rows.forEach(row => tbody.appendChild(row));
        }}
    </script>
</body>
</html>
"""

# Write index.html
output_path = OUTPUT_DIR / 'index.html'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"\n✅ Generated {output_path}")
print(f"   - {len(reports)} earnings reports indexed")
print(f"   - {len(set(r['ticker'] for r in reports))} unique companies")
