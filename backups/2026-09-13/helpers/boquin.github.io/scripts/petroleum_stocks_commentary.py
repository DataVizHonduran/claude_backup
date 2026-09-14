#!/usr/bin/env python3
"""
Petroleum Stocks Commentary — Weekly AI Analysis
Reads reports/petroleum-stocks/data/ CSVs, feeds structured data to Gemma 4,
and injects a Markdown commentary section into reports/petroleum-stocks/index.html.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/petroleum_stocks_commentary.py

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/petroleum-stocks/index.html  (commentary injected before </body>)
    reports/petroleum-stocks/commentary-YYYY-MM-DD.md  (archive copy)
"""

import os
import sys
import re
import csv
import time
import markdown as md_lib
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID   = "google/gemma-4-31B-it"
OUTPUT_DIR = Path("reports/petroleum-stocks")
INDEX_HTML = OUTPUT_DIR / "index.html"
DATA_DIR   = OUTPUT_DIR / "data"

MARKER_START = "<!-- petro-commentary-start -->"
MARKER_END   = "<!-- petro-commentary-end -->"

PADD_LABELS = {
    "R10": "PADD 1 (East Coast)",
    "R20": "PADD 2 (Midwest)",
    "R30": "PADD 3 (Gulf Coast)",
    "R40": "PADD 4 (Rocky Mtn)",
    "R50": "PADD 5 (West Coast)",
}

PRODUCTS = [
    ("crude",      "CRUDE OIL (ex-SPR)"),
    ("gasoline",   "MOTOR GASOLINE"),
    ("distillate", "DISTILLATE FUEL OIL"),
]

# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def _read_seasonal(product: str) -> list[dict]:
    path = DATA_DIR / f"{product}_seasonal.csv"
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _read_raw_nus_last2(product: str) -> tuple[float, float] | tuple[None, None]:
    """Return (prev_val, latest_val) for NUS from raw CSV, sorted by date."""
    path = DATA_DIR / f"{product}_raw.csv"
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["duoarea"] == "NUS":
                rows.append(row)
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 2:
        return None, None
    return float(rows[-2]["value_mmbbl"]), float(rows[-1]["value_mmbbl"])


def load_data() -> str:
    lines = []

    for product, label in PRODUCTS:
        seasonal = _read_seasonal(product)
        if not seasonal:
            continue

        latest_date = max(r["date"] for r in seasonal)
        rows = [r for r in seasonal if r["date"] == latest_date]

        nus = next((r for r in rows if r["duoarea"] == "NUS"), None)
        if not nus:
            continue

        nus_val = float(nus["value_mmbbl"])
        nus_pct = float(nus["pct_of_range"])

        prev_val, latest_raw = _read_raw_nus_last2(product)
        if prev_val is not None and latest_raw is not None:
            wow = latest_raw - prev_val
            wow_tag = "BUILD" if wow > 0 else "DRAW"
            wow_str = f"{wow:+.1f} ({wow_tag})"
        else:
            wow_str = "N/A"

        lines.append(f"=== {label} — {latest_date} ===")
        lines.append(
            f"NUS Total: {nus_val:.1f} MMBbl | WoW: {wow_str} | "
            f"Seasonal pos: {nus_pct:.1f}% of 5yr range"
        )

        padds = [r for r in rows if r["duoarea"] != "NUS"]
        padds.sort(key=lambda r: r["duoarea"])
        for r in padds:
            code = r["duoarea"]
            label_str = PADD_LABELS.get(code, code)
            val = float(r["value_mmbbl"])
            pct = float(r["pct_of_range"])
            note = "  ← most watched" if code == "R30" and product == "crude" else ""
            lines.append(f"  {label_str}: {val:.1f} MMBbl | pct_range: {pct:.1f}%{note}")

        lines.append("")

    return "\n".join(lines)[:8000]


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_gemma(messages: list[dict], hf_token: str, max_tokens: int = 2048) -> str:
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


def generate_report(data: str, hf_token: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""[ROLE]: Senior petroleum market analyst covering EIA weekly inventory data.

[TASK]: Analyze the following EIA weekly petroleum stocks snapshot as of {today}.
Produce a structured Markdown commentary covering:
1. Crude oil positioning — NUS total vs seasonal norms, WoW build/draw, PADD 3 (Gulf Coast) highlight
2. Gasoline positioning — seasonal tightness/surplus, demand signal
3. Distillate positioning — seasonal tightness/surplus, heating/diesel demand signal
4. Cross-product divergences — where one product is tight while another is loose
5. Price implications — net bullish / bearish / neutral for WTI and refined products
6. One watchlist item for next Wednesday's EIA release

[FORMAT]:
- Markdown headers (##, ###)
- Summary table: | Product | MMBbl | WoW | Seasonal % | Signal |
- Bullet points per section
- Under 600 words total

[DATA]:
{data}"""

    return call_gemma([{"role": "user", "content": prompt}], hf_token)


# ---------------------------------------------------------------------------
# HTML injection
# ---------------------------------------------------------------------------

def build_commentary_block(commentary_md: str, generated_at: str) -> str:
    body_html = md_lib.markdown(commentary_md, extensions=["tables"])
    return f"""{MARKER_START}
<div style="max-width:1400px;margin:40px auto 0;padding:0 20px 40px;">
  <div style="background:white;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);padding:30px;">
    <div style="border-left:4px solid #007bff;padding-left:16px;margin-bottom:20px;">
      <h2 style="color:#333;margin:0 0 4px;">AI Commentary</h2>
      <p style="color:#666;font-size:0.85em;margin:0;">Generated {generated_at} UTC &nbsp;·&nbsp; google/gemma-4-31B-it</p>
    </div>
    <div style="line-height:1.7;color:#444;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <style>
        .petro-commentary table {{border-collapse:collapse;width:100%;margin:16px 0;}}
        .petro-commentary th,
        .petro-commentary td {{border:1px solid #dee2e6;padding:8px 12px;text-align:left;}}
        .petro-commentary th {{background:#f8f9fa;font-weight:600;}}
        .petro-commentary h2,.petro-commentary h3 {{color:#333;margin:20px 0 8px;}}
        .petro-commentary ul {{padding-left:20px;}}
        .petro-commentary li {{margin:4px 0;}}
      </style>
      <div class="petro-commentary">{body_html}</div>
    </div>
  </div>
</div>
{MARKER_END}"""


def inject_into_index(block: str) -> None:
    if not INDEX_HTML.exists():
        print(f"  WARNING: {INDEX_HTML} not found — skipping injection", file=sys.stderr)
        return

    html = INDEX_HTML.read_text(encoding="utf-8")

    html = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        "",
        html,
        flags=re.DOTALL,
    )
    last_body = html.rfind("</body>")
    html = html[:last_body] + block + "\n</body>" + html[last_body + len("</body>"):]

    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"  Injected commentary into {INDEX_HTML}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    today        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    print(f"Loading data from {DATA_DIR} ...")
    data = load_data()
    print(f"  Built {len(data)} chars of structured data")
    print(data)

    print("\nGenerating commentary via Gemma 4 ...")
    commentary = generate_report(data, hf_token)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    dated_path = OUTPUT_DIR / f"commentary-{today}.md"
    dated_path.write_text(commentary, encoding="utf-8")
    print(f"\nWrote archive: {dated_path}")

    block = build_commentary_block(commentary, generated_at)
    inject_into_index(block)
