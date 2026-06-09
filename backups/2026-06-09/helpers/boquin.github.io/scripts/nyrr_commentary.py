#!/usr/bin/env python3
"""
NYRR Timeline Commentary — AI Analysis via Gemma 4
Reads data/nyrr_timeline_state.json, calls Gemma 4 for a readable race-by-race
breakdown with 9+1 strategy notes, injects into reports/nyrr/index.html.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/nyrr_commentary.py

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/nyrr/index.html  (commentary injected before </body>)
"""

import os
import re
import sys
import time
import json
import markdown as md_lib
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).parent.parent
STATE_FILE  = REPO_ROOT / "data" / "nyrr_timeline_state.json"
INDEX_HTML  = REPO_ROOT / "reports" / "nyrr" / "index.html"

MODEL_ID = "google/gemma-4-31B-it"

MARKER_START = "<!-- nyrr-commentary-start -->"
MARKER_END   = "<!-- nyrr-commentary-end -->"
# ---------------------------------------------------------------------------


def load_data() -> str:
    state = json.loads(STATE_FILE.read_text())
    content = state.get("content", "").strip()
    if not content:
        raise RuntimeError("State file has no content yet — run nyrr_watcher.py first.")
    last_changed = state.get("last_changed", "unknown")
    changelog = state.get("changelog", [])
    recent = "\n".join(
        f"- {e['date']}: {e.get('summary','changed')}" for e in changelog[-5:]
    ) or "None yet"
    return (
        f"Last changed: {last_changed}\n"
        f"Recent changelog:\n{recent}\n\n"
        f"--- FULL TIMELINE CONTENT ---\n{content[:6000]}"
    )


def call_gemma(data: str, hf_token: str) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    messages = [
        {
            "role": "user",
            "content": (
                "[ROLE]: You are a friendly NYC running coach helping a runner earn "
                "9+1 guaranteed entry into the TCS NYC Marathon.\n"
                "[TASK]: Parse the NYRR race registration timeline below and write a "
                "clear, cheerful breakdown with these sections:\n"
                "## What's Open Right Now\n"
                "## Sold Out — Already Gone\n"
                "## Not Yet Announced\n"
                "## 9+1 Strategy Notes\n"
                "[FORMAT]: Markdown with ## headers and bullet points. "
                "Friendly tone — like texting a running buddy. Under 500 words. "
                "Highlight key dates in **bold**.\n"
                f"[DATA]:\n{data}"
            ),
        }
    ]
    for attempt in range(5):
        try:
            stream = client.chat.completions.create(
                messages=messages,
                temperature=0.25,
                max_tokens=1024,
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
        except Exception as exc:
            is_rate = any(x in str(exc) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if is_rate and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"[nyrr_commentary] rate limited, waiting {wait}s…", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def build_block(commentary_md: str, generated_at: str) -> str:
    body_html = md_lib.markdown(commentary_md, extensions=["tables"])
    return f"""{MARKER_START}
<div style="max-width:860px;margin:0 auto 0;padding:0 1rem 2rem;">
  <div style="background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:1.5rem;">
    <div style="border-left:4px solid #ff6b35;padding-left:1rem;margin-bottom:1.2rem;">
      <h2 style="color:#1e293b;margin:0 0 .25rem;font-size:1rem;text-transform:uppercase;letter-spacing:.07em;">AI Breakdown</h2>
      <p style="color:#94a3b8;font-size:.78rem;margin:0;">Generated {generated_at} UTC &middot; google/gemma-4-31B-it</p>
    </div>
    <div class="nyrr-commentary" style="line-height:1.75;color:#334155;font-size:.92rem;">
      <style>
        .nyrr-commentary h2{{color:#ff6b35;font-size:.85rem;text-transform:uppercase;letter-spacing:.07em;margin:1.2rem 0 .5rem;}}
        .nyrr-commentary ul{{padding-left:1.2rem;margin:.4rem 0;}}
        .nyrr-commentary li{{margin:.3rem 0;}}
        .nyrr-commentary strong{{color:#1e293b;}}
        .nyrr-commentary table{{border-collapse:collapse;width:100%;margin:.8rem 0;}}
        .nyrr-commentary th,.nyrr-commentary td{{border:1px solid #e2e8f0;padding:6px 10px;text-align:left;font-size:.85rem;}}
        .nyrr-commentary th{{background:#f8fafc;font-weight:600;}}
      </style>
      {body_html}
    </div>
  </div>
</div>
{MARKER_END}"""


PLACEHOLDER = "<!-- nyrr-commentary-here -->"

def inject(index_html: Path, block: str) -> None:
    html = index_html.read_text(encoding="utf-8")
    # Strip any existing commentary block
    html = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        "",
        html,
        flags=re.DOTALL,
    )
    # Inject at placeholder (keep placeholder so re-runs find it)
    if PLACEHOLDER in html:
        html = html.replace(PLACEHOLDER, block + "\n\n        " + PLACEHOLDER, 1)
    else:
        # Fallback: before </body>
        last_body = html.rfind("</body>")
        html = html[:last_body] + block + "\n</body>" + html[last_body + len("</body>"):]
    index_html.write_text(html, encoding="utf-8")


def main() -> None:
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("[nyrr_commentary] ERROR: HF_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M")

    print("[nyrr_commentary] loading timeline data…")
    data = load_data()

    print("[nyrr_commentary] calling Gemma 4…")
    commentary_md = call_gemma(data, hf_token)

    block = build_block(commentary_md, now_str)
    inject(INDEX_HTML, block)
    print(f"[nyrr_commentary] injected → {INDEX_HTML}")


if __name__ == "__main__":
    main()
