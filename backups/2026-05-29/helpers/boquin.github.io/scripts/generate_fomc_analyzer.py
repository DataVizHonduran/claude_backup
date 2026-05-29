#!/usr/bin/env python3
"""
FOMC Statement Analyzer
Loads FOMC statements from vtasca/fomc-statements-minutes on HuggingFace,
compares consecutive statement pairs using Gemma 4, and writes HTML reports.

First run: processes ALL consecutive statement pairs in the dataset.
Subsequent runs: processes only the latest pair (if not already analyzed).

Usage:
    HF_TOKEN=hf_xxx python3 generate_fomc_analyzer.py
    HF_TOKEN=hf_xxx python3 generate_fomc_analyzer.py --force      # reprocess latest pair
    HF_TOKEN=hf_xxx python3 generate_fomc_analyzer.py --dry-run    # load + pair, no LLM

Required env vars:
    HF_TOKEN — HuggingFace API token (needed for Gemma; dataset is public)

Output:
    reports/fomc-analyzer/fomc-{curr_date}.html  (one per analyzed pair)
    reports/fomc-analyzer/index.html             (archive listing)
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import requests
import pandas as pd
import markdown as md_lib
from huggingface_hub import InferenceClient
from cb_monitor_utils import regenerate_cb_monitor

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID    = "google/gemma-4-31B-it"
DATASET_CSV = "https://huggingface.co/datasets/vtasca/fomc-statements-minutes/resolve/main/communications.csv"

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; FOMCAnalyzer/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
}

MARKER_START = "<!-- fomc-analyzer-start -->"
MARKER_END   = "<!-- fomc-analyzer-end -->"

# ---------------------------------------------------------------------------
# Load dataset
# ---------------------------------------------------------------------------

def load_statements() -> pd.DataFrame:
    """Download the FOMC CSV from HuggingFace and return filtered/sorted DataFrame."""
    print("Fetching FOMC dataset ...", file=sys.stderr)
    resp = requests.get(DATASET_CSV, headers=BASE_HEADERS, allow_redirects=True, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))

    # Normalise column names (strip whitespace)
    df.columns = [c.strip() for c in df.columns]

    # Filter to policy statements only (Type == "Statement")
    df = df[df["Type"].str.strip() == "Statement"].copy()

    # Parse dates and sort ascending
    df["_date"] = pd.to_datetime(df["Date"].str.strip(), errors="coerce")
    df = df.dropna(subset=["_date"]).sort_values("_date").reset_index(drop=True)

    print(f"  {len(df)} FOMC statements found "
          f"({df['_date'].iloc[0].date()} → {df['_date'].iloc[-1].date()})", file=sys.stderr)
    return df


# ---------------------------------------------------------------------------
# Pair selection
# ---------------------------------------------------------------------------

def get_pairs_to_process(df: pd.DataFrame, out_dir: Path, force: bool) -> list[tuple[int, int]]:
    """
    Return list of (prev_idx, curr_idx) pairs that need to be processed, oldest first.
    Unprocessed pairs are those without an existing HTML file.
    --force re-queues the latest pair even if it already exists.
    """
    existing = {p.stem.replace("fomc-", "") for p in out_dir.glob("fomc-*.html")}
    all_pairs = [(i - 1, i) for i in range(1, len(df))]

    unprocessed = [
        (pi, ci) for pi, ci in all_pairs
        if df.iloc[ci]["_date"].strftime("%Y-%m-%d") not in existing
    ]

    if force:
        latest = all_pairs[-1]
        if latest not in unprocessed:
            unprocessed = [latest] + unprocessed

    if not unprocessed:
        print("  All pairs already processed.", file=sys.stderr)
        return []

    print(f"  {len(unprocessed)} unprocessed pair(s) remaining.", file=sys.stderr)
    return list(reversed(unprocessed))


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT = """\
Act as a senior economist and central bank strategist.

Below are two consecutive FOMC monetary policy statements. Perform a detailed \
side-by-side comparison and produce the following analysis:

---

## 1. Redlined Statement ({curr_date})

Reproduce the full text of the **current statement** with inline redline markup:
- ~~Struck-through text~~ for every phrase or sentence **removed** vs. the previous statement.
- **Bold text** for every phrase or sentence **added** vs. the previous statement.
- Unchanged text shown normally.

Then present a summary table with three columns: **Removed** | **Added** | **Significance**.

## 2. Thematic Shifts

Analyze shifts in:
- **Inflation** — e.g., characterisation as transitory vs. persistent, pace of progress.
- **Labor Markets & Growth** — e.g., cooling vs. robust, risks to employment.
- **Forward Guidance** — e.g., signals about future rate moves, data-dependency language.

## 3. Tonal Assessment

Conclude with a short paragraph: Did the committee shift **Hawkish** or **Dovish** \
(or remain Neutral) compared to the previous statement? Explain why based on the specific \
text changes identified above.

---

PREVIOUS STATEMENT ({prev_date}):
{prev_text}

---

CURRENT STATEMENT ({curr_date}):
{curr_text}
"""


def build_prompt(prev_date: str, prev_text: str, curr_date: str, curr_text: str) -> str:
    return ANALYSIS_PROMPT.format(
        prev_date=prev_date,
        prev_text=prev_text.strip(),
        curr_date=curr_date,
        curr_text=curr_text.strip(),
    )


# ---------------------------------------------------------------------------
# Gemma call
# ---------------------------------------------------------------------------

def call_gemma(messages: list[dict], hf_token: str, max_tokens: int = 3000) -> str:
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
            is_rate_limit = any(
                x in str(e)
                for x in ("429", "503", "504", "Too Many Requests",
                          "Service Temporarily Unavailable", "Gateway Time-out")
            )
            if is_rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n  HF rate limit — waiting {wait}s (attempt {attempt+1}/5) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

HTML_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 1000px; margin: 0 auto; padding: 20px;
    line-height: 1.6; background: #f5f5f5; color: #333;
}
.container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
h1 { color: #1565c0; border-bottom: 3px solid #1565c0; padding-bottom: 10px; }
h2 { color: #1565c0; border-bottom: 2px solid #e3f2fd; padding-bottom: 6px; margin-top: 36px; }
h3 { color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
.meta { color: #777; font-size: 0.85em; margin: 6px 0 20px; }
.back-link { display: inline-block; margin-bottom: 20px; color: #1565c0; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9em; }
th { background: #1565c0; color: white; padding: 10px 12px; text-align: left; }
td { border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
pre {
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}
code { background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }
blockquote {
    border-left: 4px solid #1565c0; margin: 16px 0; padding: 8px 16px;
    background: #e3f2fd; border-radius: 0 4px 4px 0; color: #333;
}
ul, ol { padding-left: 1.5em; }
li { margin: 4px 0; }
hr { border: none; border-top: 2px solid #eee; margin: 32px 0; }
a { color: #1565c0; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FOMC Statement Analysis — {curr_date} vs {prev_date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">← FOMC Analyzer Archive</a>
    <h1>📋 FOMC Statement Analysis</h1>
    <h2 style="border:none;margin-top:0;font-size:1.2em;color:#555;">
        {curr_date} vs {prev_date}
    </h2>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Model: {model} &nbsp;|&nbsp;
        Source: <a href="https://huggingface.co/datasets/vtasca/fomc-statements-minutes" target="_blank">vtasca/fomc-statements-minutes</a>
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
    <title>FOMC Statement Analyzer — Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #1565c0; border-bottom: 3px solid #1565c0; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #1565c0; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #1565c0; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #e8f5e9; color: #2e7d32;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>📋 FOMC Statement Analyzer</h1>
    <p class="description">
        Side-by-side redline comparison of consecutive FOMC monetary policy statements —
        thematic shifts in inflation, labor market, and forward guidance language,
        with a hawkish/dovish tonal verdict, powered by Gemma 4.
    </p>
    <ul class="report-list">
        {items}
    </ul>
</div>
</body>
</html>"""


def markdown_to_html(text: str) -> str:
    return md_lib.markdown(text, extensions=["tables", "fenced_code", "nl2br"])


def regenerate_index(out_dir: Path) -> None:
    # Collect all fomc-YYYY-MM-DD.html files, sorted newest first
    pattern = re.compile(r"fomc-(\d{4}-\d{2}-\d{2})\.html")
    reports = sorted(
        [p for p in out_dir.glob("fomc-*.html") if pattern.match(p.name)],
        reverse=True,
    )
    items = []
    for i, path in enumerate(reports):
        date_str = pattern.match(path.name).group(1)
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">FOMC Analysis — {date_str}{badge}</a>'
            f'<span class="report-date">{date_str}</span>'
            f'</li>'
        )
    (out_dir / "index.html").write_text(
        INDEX_TEMPLATE.format(
            items="\n        ".join(items) if items else "<li>No reports yet.</li>"
        ),
        encoding="utf-8",
    )


def save_report(
    analysis: str,
    prev_date: str,
    curr_date: str,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    body_html = markdown_to_html(analysis)
    html = HTML_TEMPLATE.format(
        curr_date=curr_date,
        prev_date=prev_date,
        generated_at=generated_at,
        model=MODEL_ID,
        css=HTML_CSS,
        body=body_html,
    )
    out_path = out_dir / f"fomc-{curr_date}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FOMC Statement Analyzer")
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory (default: reports/fomc-analyzer/ relative to script)",
    )
    parser.add_argument("--force", action="store_true",
                        help="Reprocess the latest pair even if HTML already exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N pairs (oldest unprocessed first)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Load dataset and select pairs, but skip LLM and file writes")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root  = script_dir.parent
    default_out = repo_root / "reports" / "fomc-analyzer"
    out_dir = Path(args.output_dir) if args.output_dir else default_out

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    # 1. Load
    df = load_statements()

    # 2. Determine pairs
    pairs = get_pairs_to_process(df, out_dir, force=args.force)
    if args.limit:
        pairs = pairs[:args.limit]
    if not pairs:
        print("Nothing to do.", file=sys.stderr)
        return

    print(f"\n{len(pairs)} pair(s) to process.", file=sys.stderr)

    if args.dry_run:
        for prev_idx, curr_idx in pairs:
            prev_row = df.iloc[prev_idx]
            curr_row = df.iloc[curr_idx]
            prev_date = prev_row["_date"].strftime("%Y-%m-%d")
            curr_date = curr_row["_date"].strftime("%Y-%m-%d")
            print(f"\n[DRY RUN] {prev_date} → {curr_date}")
            print(f"  Prev excerpt: {str(prev_row['Text'])[:120]} ...")
            print(f"  Curr excerpt: {str(curr_row['Text'])[:120]} ...")
        return

    # 3. Process each pair
    for pair_num, (prev_idx, curr_idx) in enumerate(pairs, 1):
        prev_row = df.iloc[prev_idx]
        curr_row = df.iloc[curr_idx]
        prev_date = prev_row["_date"].strftime("%Y-%m-%d")
        curr_date = curr_row["_date"].strftime("%Y-%m-%d")

        print(f"\n[{pair_num}/{len(pairs)}] Analyzing {prev_date} → {curr_date} ...", file=sys.stderr)

        prompt = build_prompt(
            prev_date=prev_date,
            prev_text=str(prev_row["Text"]),
            curr_date=curr_date,
            curr_text=str(curr_row["Text"]),
        )

        est_tokens = len(prompt) // 4
        print(f"  Prompt ~{est_tokens:,} tokens", file=sys.stderr)

        messages = [{"role": "user", "content": prompt}]
        analysis = call_gemma(messages, hf_token=hf_token, max_tokens=3000)

        out_path = save_report(analysis, prev_date, curr_date, out_dir)
        print(f"  Saved → {out_path}", file=sys.stderr)

        # Rate limit courtesy sleep between pairs (batch run only)
        if pair_num < len(pairs):
            time.sleep(3)

    # 4. Rebuild archive index
    regenerate_index(out_dir)
    regenerate_cb_monitor(out_dir.parent.parent)
    print(f"\nIndex → {out_dir / 'index.html'}", file=sys.stderr)
    print("Done.")


if __name__ == "__main__":
    main()
