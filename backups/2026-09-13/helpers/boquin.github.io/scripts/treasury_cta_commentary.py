#!/usr/bin/env python3
"""
Treasury CTA Commentary — Daily AI Analysis
Reads reports/treasury-cta-signals/summary.json, feeds structured data to Gemma 4,
and injects a Markdown commentary section into reports/treasury-cta-signals/index.html.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/treasury_cta_commentary.py

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/treasury-cta-signals/index.html  (commentary injected before </body>)
    reports/treasury-cta-signals/commentary-YYYY-MM-DD.md  (archive copy)
"""

import os
import sys
import re
import time
import json
import markdown as md_lib
from datetime import datetime, timezone, timedelta
from pathlib import Path

from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID   = "google/gemma-4-31B-it"
OUTPUT_DIR = Path("reports/treasury-cta-signals")
INDEX_HTML = OUTPUT_DIR / "index.html"
SUMMARY    = OUTPUT_DIR / "summary.json"

MARKER_START = "<!-- treasury-cta-commentary-start -->"
MARKER_END   = "<!-- treasury-cta-commentary-end -->"

# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def load_data() -> str:
    with open(SUMMARY) as f:
        d = json.load(f)

    lines = []

    # Yields (same across modes)
    fast = d["fast"]
    yields = fast.get("latest_yields", {})
    if yields:
        lines.append(f"=== CURRENT YIELDS (as of {fast.get('data_as_of', 'N/A')}) ===")
        lines.append("  " + " | ".join(f"{t}: {v:.2f}%" for t, v in sorted(yields.items())))
        # Yield curve spreads
        y2  = yields.get("2Y",  0)
        y10 = yields.get("10Y", 0)
        y30 = yields.get("30Y", 0)
        lines.append(f"  10Y-2Y spread: {y10 - y2:+.2f}bps  |  30Y-2Y spread: {y30 - y2:+.2f}bps")
        lines.append("")

    for mode in ("fast", "slow"):
        m = d[mode]
        lines.append(f"=== {mode.upper()} MODE (windows: {m['windows']}) ===")
        lines.append(f"Signal count: {m['signal_count']}  |  High-conviction (score≥60): {m['high_conviction_count']}")

        # Sorted positions (most long-duration/negative → most short-duration/positive)
        pos = sorted(m["latest_positions"].items(), key=lambda x: x[1])
        lines.append("SIGN CONVENTION: + = SHORT duration (short futures, rising-yield bet) | - = LONG duration (long futures, falling-yield bet)")
        lines.append("Positioning (most long-duration to most short-duration, scale -50 to +50):")
        lines.append("  " + ", ".join(f"{t}: {v:+.1f}" for t, v in pos))

        # Recent signals (last 14 days, top by strength_score)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
        recent = [
            s for s in m.get("signal_metadata", [])
            if s.get("date", "") >= cutoff
        ]
        recent.sort(key=lambda x: x.get("strength_score", 0), reverse=True)
        if recent:
            lines.append(f"Recent signals (last 14 days, top by strength):")
            for s in recent[:6]:
                lines.append(
                    f"  {s['date']} {s['tenor']} {s['direction']} | "
                    f"strength={s['strength_score']:.1f} "
                    f"(extremity={s['extremity_score']:.1f}, speed={s['speed_score']:.1f}, "
                    f"consensus={s['consensus_score']:.1f}) | "
                    f"peak_pos={s['peak_position']:+.2f}"
                )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_gemma(messages: list[dict], hf_token: str, max_tokens: int = 1200) -> str:
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
    prompt = f"""[ROLE]: Senior Rates/Macro Strategist specializing in CTA trend-following and Treasury exhaustion signals.

[SIGN CONVENTION - CRITICAL]:
In this dataset, position sign is INVERTED from standard fixed-income convention:
  POSITIVE (+) position means CTAs are SHORT duration (short Treasury futures), positioned for RISING yields / FALLING bond prices.
  NEGATIVE (-) position means CTAs are LONG duration (long Treasury futures), positioned for FALLING yields / RISING bond prices.
Never describe a positive position as "long bonds" or "long duration." A high positive score means crowded short-duration / rising-yield positioning.

[TASK]: Analyze the following Treasury CTA positioning snapshot as of {today}.
Produce a structured Markdown commentary covering:
1. Duration crowding — which tenors CTAs are most short-duration (+) or long-duration (-) and what it signals for yield direction
2. Yield curve context — how the 10Y-2Y and 30Y-2Y spreads relate to current positioning
3. Fast vs slow divergences — where the two modes disagree and what that implies for trend conviction
4. Recent exhaustion signals — what high-conviction signals suggest about crowded duration trades
5. One actionable watch-list item for the next 5 trading days

[FORMAT]:
- Markdown headers (##, ###)
- Bullet points for each section
- Under 300 words total

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
        .treasury-cta-commentary table {{border-collapse:collapse;width:100%;margin:16px 0;}}
        .treasury-cta-commentary th,
        .treasury-cta-commentary td {{border:1px solid #dee2e6;padding:8px 12px;text-align:left;}}
        .treasury-cta-commentary th {{background:#f8f9fa;font-weight:600;}}
        .treasury-cta-commentary h2,.treasury-cta-commentary h3 {{color:#333;margin:20px 0 8px;}}
        .treasury-cta-commentary ul {{padding-left:20px;}}
        .treasury-cta-commentary li {{margin:4px 0;}}
      </style>
      <div class="treasury-cta-commentary">{body_html}</div>
    </div>
  </div>
</div>
{MARKER_END}"""


def inject_into_index(block: str) -> None:
    if not INDEX_HTML.exists():
        print(f"  WARNING: {INDEX_HTML} not found — skipping injection", file=sys.stderr)
        return

    html = INDEX_HTML.read_text(encoding="utf-8")

    # Strip ALL existing blocks regardless of count, then insert once before last </body>
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

    print(f"Loading {SUMMARY} ...")
    data = load_data()
    print(f"  Built {len(data)} chars of structured data")

    print("\nGenerating commentary via Gemma 4 ...")
    commentary = generate_report(data, hf_token)

    if not commentary.strip():
        print("ERROR: Gemma returned empty commentary — possible content filter or API issue. Aborting.", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    dated_path = OUTPUT_DIR / f"commentary-{today}.md"
    dated_path.write_text(commentary, encoding="utf-8")
    print(f"\nWrote archive: {dated_path}")

    block = build_commentary_block(commentary, generated_at)
    inject_into_index(block)
