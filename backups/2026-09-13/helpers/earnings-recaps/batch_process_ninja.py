"""
Process all ninja press release txt files into HTML tearsheets.
Skips tickers that already have an HTML file. No AI commentary.
"""
import json, re
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib

REPO_ROOT   = Path(__file__).resolve().parent
NINJA_DIR   = REPO_ROOT / "ninja"
REPORTS_DIR = REPO_ROOT / "reports"
INDEX_HTML  = REPO_ROOT / "index.html"
MANIFEST    = REPORTS_DIR / "manifest.json"

PAGE_CSS = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background:#f5f7fa; margin:0; padding:0; color:#333; }
  .header { background:#1a1a2e; color:white; padding:24px 32px; }
  .header h1 { margin:0; font-size:1.6em; }
  .header .sub { color:#aaa; font-size:0.9em; margin-top:4px; }
  .container { max-width:1000px; margin:32px auto; padding:0 20px 60px; }
  .meta-card { background:white; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,.08);
               padding:20px 24px; margin-bottom:24px; display:flex; gap:24px; flex-wrap:wrap; }
  .meta-item { display:flex; flex-direction:column; }
  .meta-label { font-size:.75em; color:#888; text-transform:uppercase; letter-spacing:.05em; }
  .meta-value { font-size:1.05em; font-weight:600; margin-top:2px; }
  .badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:.8em;
           font-weight:600; background:#e8f4fd; color:#0077cc; }
  .commentary-card { background:white; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,.08);
                     padding:28px 32px; margin-bottom:24px; }
  .commentary-card .card-title { border-left:4px solid #007bff; padding-left:14px; margin-bottom:20px; }
  .commentary-card .card-title h2 { margin:0 0 4px; color:#1a1a2e; }
  .commentary-card .card-title p  { margin:0; color:#888; font-size:.82em; }
  .commentary h2, .commentary h3 { color:#1a1a2e; margin:18px 0 8px; }
  .commentary ul { padding-left:20px; }
  .commentary li { margin:4px 0; line-height:1.6; }
  .commentary p  { line-height:1.7; }
  details { background:white; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,.08); }
  summary { padding:16px 24px; cursor:pointer; font-weight:600; color:#444;
            list-style:none; user-select:none; }
  summary::-webkit-details-marker { display:none; }
  summary::before { content:"▶  "; color:#007bff; }
  details[open] summary::before { content:"▼  "; }
  .raw-text { padding:0 24px 24px; white-space:pre-wrap; font-size:.82em;
              color:#555; line-height:1.6; border-top:1px solid #f0f0f0; margin-top:8px; }
  .back-link { display:inline-block; margin-bottom:20px; color:#007bff; text-decoration:none; font-size:.9em; }
  .back-link:hover { text-decoration:underline; }
</style>
"""


def parse_ninja_file(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    meta = {}
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("Ticker: "):
            meta["ticker"] = line[8:].strip()
        elif line.startswith("Company: "):
            meta["company"] = line[9:].strip()
        elif line.startswith("Filed: "):
            meta["date"] = line[7:].strip()
        elif line.startswith("Type: "):
            meta["label"] = line[6:].strip()
        elif line.startswith("Source: "):
            meta["source"] = line[8:].strip()
        elif line == "" and i > 4:
            body_start = i + 1
            break
    if not all(k in meta for k in ("ticker", "company", "date", "label")):
        return None
    meta["text"] = "\n".join(lines[body_start:]).strip()
    return meta


def build_report_html(exhibit: dict) -> str:
    raw_escaped = exhibit["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{exhibit['ticker']} Earnings Recap — {exhibit['date']}</title>
{PAGE_CSS}
</head>
<body>
<div class="header">
  <h1>📈 {exhibit['ticker']} — Earnings Recap</h1>
  <div class="sub">{exhibit['company']} · Filed {exhibit['date']}</div>
</div>
<div class="container">
  <a class="back-link" href="../index.html">← All Reports</a>
  <div class="meta-card">
    <div class="meta-item"><span class="meta-label">Ticker</span><span class="meta-value">{exhibit['ticker']}</span></div>
    <div class="meta-item"><span class="meta-label">Company</span><span class="meta-value">{exhibit['company']}</span></div>
    <div class="meta-item"><span class="meta-label">Filed</span><span class="meta-value">{exhibit['date']}</span></div>
    <div class="meta-item"><span class="meta-label">Type</span><span class="meta-value"><span class="badge">{exhibit['label']}</span></span></div>
    <div class="meta-item"><span class="meta-label">Characters</span><span class="meta-value">{len(exhibit['text']):,}</span></div>
  </div>
  <div class="commentary-card">
    <div class="card-title">
      <h2>AI Commentary</h2>
      <p>Not yet generated — add HF_TOKEN or ANTHROPIC_API_KEY and re-run fetch_earnings.py</p>
    </div>
    <div class="commentary"><p><em>AI commentary pending.</em></p></div>
  </div>
  <details>
    <summary>Full Press Release Text</summary>
    <div class="raw-text">{raw_escaped}</div>
  </details>
</div>
</body>
</html>"""


def build_index(records: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = ""
    for r in sorted(records, key=lambda x: x["date"], reverse=True):
        fname = f"reports/{r['ticker']}_{r['date']}.html"
        badge_color = "#007bff" if r["label"] == "PRESS_RELEASE" else "#28a745"
        cards += f"""
    <article class="report-card">
      <div class="ticker">{r['ticker']}</div>
      <div class="company">{r['company']}</div>
      <div class="date">{r['date']}</div>
      <span class="badge" style="background:{badge_color}20;color:{badge_color}">{r['label']}</span>
      <a class="view-link" href="{fname}">View Recap →</a>
    </article>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Earnings Recaps — S&P 500</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background:#f5f7fa; margin:0; padding:0; color:#333; }}
  .header {{ background:#1a1a2e; color:white; padding:28px 32px; }}
  .header h1 {{ margin:0; font-size:1.8em; }}
  .header .sub {{ color:#aaa; font-size:.9em; margin-top:6px; }}
  .container {{ max-width:1200px; margin:0 auto; padding:32px 20px 60px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:18px; }}
  .report-card {{ background:white; border-radius:10px;
                  box-shadow:0 2px 6px rgba(0,0,0,.08); padding:20px;
                  display:flex; flex-direction:column; gap:6px;
                  transition:transform .15s,box-shadow .15s; }}
  .report-card:hover {{ transform:translateY(-3px); box-shadow:0 6px 14px rgba(0,0,0,.12); }}
  .ticker {{ font-size:1.6em; font-weight:700; color:#1a1a2e; }}
  .company {{ font-size:.82em; color:#666; }}
  .date {{ font-size:.85em; color:#888; margin-top:2px; }}
  .badge {{ display:inline-block; padding:2px 9px; border-radius:12px;
            font-size:.75em; font-weight:600; margin-top:4px; }}
  .view-link {{ margin-top:auto; padding-top:12px; color:#007bff; text-decoration:none;
                font-weight:600; font-size:.9em; border-top:1px solid #f0f0f0; }}
  .view-link:hover {{ text-decoration:underline; }}
  .meta {{ color:#999; font-size:.83em; margin-bottom:20px; }}
</style>
</head>
<body>
<div class="header">
  <h1>📊 Earnings Recaps</h1>
  <div class="sub">S&P 500 · EDGAR 8-K filings · Updated {now}</div>
</div>
<div class="container">
  <p class="meta">{len(records)} report(s) · Source: SEC EDGAR 8-K filings</p>
  <div class="grid">{cards}
  </div>
</div>
</body>
</html>"""


def main():
    REPORTS_DIR.mkdir(exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    existing_keys = {(r["ticker"], r["date"]) for r in manifest}
    existing_html = {f.stem for f in REPORTS_DIR.glob("*.html") if f.stem != "index"}

    new_count = 0
    for ninja_file in sorted(NINJA_DIR.glob("*.txt")):
        stem = ninja_file.stem  # e.g. LHX_2026-04-30
        if stem in existing_html:
            continue

        exhibit = parse_ninja_file(ninja_file)
        if not exhibit:
            print(f"  SKIP (parse error): {ninja_file.name}")
            continue

        key = (exhibit["ticker"], exhibit["date"])
        html = build_report_html(exhibit)
        out = REPORTS_DIR / f"{stem}.html"
        out.write_text(html, encoding="utf-8")

        if key not in existing_keys:
            manifest.append({
                "ticker":  exhibit["ticker"],
                "company": exhibit["company"],
                "date":    exhibit["date"],
                "label":   exhibit["label"],
            })
            existing_keys.add(key)

        new_count += 1
        print(f"  {stem}")

    print(f"\n{new_count} new tearsheets generated. Total: {len(manifest)}")

    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    INDEX_HTML.write_text(build_index(manifest), encoding="utf-8")
    print("manifest.json + index.html updated.")


if __name__ == "__main__":
    main()
