#!/usr/bin/env python3
"""
CTA Signals Commentary — Daily AI Analysis
Reads reports/cta-signals/summary.json, feeds structured data to Gemma 4,
and injects a Markdown commentary section into reports/cta-signals/index.html.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/cta_commentary.py

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/cta-signals/index.html  (commentary injected before </body>)
    reports/cta-signals/commentary-YYYY-MM-DD.md  (archive copy)
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
OUTPUT_DIR = Path("reports/cta-signals")
INDEX_HTML = OUTPUT_DIR / "index.html"
SUMMARY    = OUTPUT_DIR / "summary.json"

MARKER_START = "<!-- cta-commentary-start -->"
MARKER_END   = "<!-- cta-commentary-end -->"

# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def load_data() -> str:
    with open(SUMMARY) as f:
        d = json.load(f)

    lines = []

    for mode in ("fast", "slow"):
        m = d[mode]
        lines.append(f"=== {mode.upper()} MODE (windows: {m['windows']}) ===")
        lines.append(f"Signal count: {m['signal_count']}  |  High-conviction: {m['high_conviction_count']}")

        # Sorted positions (most short → most long)
        pos = sorted(m["latest_positions"].items(), key=lambda x: x[1])
        lines.append("Positioning (most short to most long, scale -50 to +50):")
        lines.append("  " + ", ".join(f"{ccy}: {v:+.1f}" for ccy, v in pos))

        # MA divergence: current position vs 20-day MA (scatter tab)
        ma20 = m.get("ma_positions", {}).get("20", {})
        if ma20:
            divs = []
            for ccy, ma_val in ma20.items():
                cur = m["latest_positions"].get(ccy)
                if cur is not None:
                    divs.append((ccy, cur, ma_val, cur - ma_val))
            divs.sort(key=lambda x: abs(x[3]), reverse=True)
            lines.append("Largest divergences from 20-day MA (current vs MA, diff):")
            for ccy, cur, ma, diff in divs[:8]:
                lines.append(f"  {ccy}: current={cur:+.1f}, 20d-MA={ma:+.1f}, diff={diff:+.1f}")

        # Recent high-conviction signals (last 14 days, top by strength_score)
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
                    f"  {s['date']} {s['currency']} {s['direction']} | "
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
    prompt = f"""[ROLE]: Senior Macro/Quant Analyst specializing in CTA trend-following and exhaustion signals.

[CONVENTION]: Every series below is the USD/CCY exchange rate (units of CCY per 1 USD — for EUR, GBP, AUD, NZD this is the inverse of their normal market quote). A positive position / "Long" signal means CTAs are long USD vs CCY: bullish USD, BEARISH CCY. A negative position / "Short" signal means CTAs are short USD vs CCY: bearish USD, BULLISH CCY. Do NOT describe a positive/"Long" reading as "long [CCY]" or a "crowded long trade in [CCY]" — that reverses the meaning. Instead phrase it as e.g. "CTAs are crowded short INR (long USD/INR)" or "extreme bearish INR positioning". Likewise a negative/"Short" reading is bullish CCY, e.g. "crowded long HUF (short USD/HUF)".

[TASK]: Analyze the following CTA positioning snapshot as of {today}.
Produce a structured Markdown commentary covering:
1. Positioning extremes — which currencies are most overbought / oversold and what it signals
2. Fast vs slow mode divergences — where the two modes disagree and what that implies for trend conviction
3. MA divergences — currencies where current positioning has moved furthest from its 20-day MA (momentum acceleration or reversal risk)
4. Recent high-conviction exhaustion signals — what they suggest about crowded trades
5. Overall risk sentiment (risk-on / risk-off / mixed)
6. One actionable watch-list item for the next 5 trading days

[FORMAT]:
- Markdown headers (##, ###)
- Summary table: | Currency | Position | Fast Signal | Slow Signal | Key Observation |
- Bullet points for each section
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
        .cta-commentary table {{border-collapse:collapse;width:100%;margin:16px 0;}}
        .cta-commentary th,
        .cta-commentary td {{border:1px solid #dee2e6;padding:8px 12px;text-align:left;}}
        .cta-commentary th {{background:#f8f9fa;font-weight:600;}}
        .cta-commentary h2,.cta-commentary h3 {{color:#333;margin:20px 0 8px;}}
        .cta-commentary ul {{padding-left:20px;}}
        .cta-commentary li {{margin:4px 0;}}
      </style>
      <div class="cta-commentary">{body_html}</div>
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    dated_path = OUTPUT_DIR / f"commentary-{today}.md"
    dated_path.write_text(commentary, encoding="utf-8")
    print(f"\nWrote archive: {dated_path}")

    block = build_commentary_block(commentary, generated_at)
    inject_into_index(block)
