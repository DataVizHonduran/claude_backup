#!/usr/bin/env python3
"""
FX Factor Fair Value — Gemma commentary injection.
Reads summary.json, calls Gemma once per currency (<100 words each),
injects JS-synced commentary beneath the currency explorer chart.

Run:
    HF_TOKEN=... python3 scripts/fx_factor_fairvalue_commentary.py
"""

import os, json, re, time
from pathlib import Path
from datetime import datetime, timezone

from huggingface_hub import InferenceClient

MODEL_ID   = "google/gemma-4-31B-it"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR") or os.path.expanduser("~/boquin.github.io/reports/fx-factor-fairvalue"))
SUMMARY    = OUTPUT_DIR / "summary.json"
INDEX_HTML = OUTPUT_DIR / "index.html"

MARKER_START = "<!-- fx-factor-commentary-start -->"
MARKER_END   = "<!-- fx-factor-commentary-end -->"

FACTOR_LABELS = {
    "MTUM": "Momentum", "SPHB": "High Beta", "IWC": "Micro Cap",
    "IVW": "LG Growth", "IJT": "SC Growth", "IJR": "Small Cap",
    "IJS": "SC Value",  "IJK": "MC Growth",  "QUAL": "Quality",
    "IJJ": "MC Value",  "VYM": "High Div",   "IVE": "LG Value",
    "USMV": "Min Vol",  "SPY": "S&P 500"
}


def call_gemma(messages, hf_token, max_tokens=160):
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(5):
        try:
            stream = client.chat.completions.create(
                messages=messages, temperature=0.2, max_tokens=max_tokens, stream=True,
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
            return "".join(parts).strip()
        except Exception as e:
            is_rate_limit = any(x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if is_rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n  Rate limit — waiting {wait}s…")
                time.sleep(wait)
            else:
                raise


def get_commentary(ccy_data, hf_token):
    ccy      = ccy_data["currency"]
    residual = ccy_data["residual"]
    r2       = ccy_data["r2"]
    actual   = ccy_data["actual"]
    predicted = ccy_data["predicted"]

    factor_names = []
    for v in ccy_data["selected_vars"]:
        ticker = v.replace("/SPY", "")
        factor_names.append(f"{FACTOR_LABELS.get(ticker, ticker)} ({ticker})")
    selected_str = ", ".join(factor_names) if factor_names else "none"
    direction = "overvalued" if residual > 0 else "undervalued"

    prompt = (
        f"[ROLE]: FX macro analyst, precise and terse.\n"
        f"[TASK]: In EXACTLY under 100 words explain or theorize why the selected equity factor styles might "
        f"predict {ccy} and what the {residual:+.1f}% residual implies economically. No headers, no bullets — "
        f"2-3 tight sentences.\n"
        f"[DATA]:\n"
        f"Pair: {ccy} | Current: {actual:.4f} | Model fair value: {predicted:.4f}\n"
        f"Residual: {residual:+.1f}% → {direction} vs factor model\n"
        f"R²: {r2:.3f} (model explains {r2*100:.0f}% of FX variance on holdout)\n"
        f"Selected factors: {selected_str}"
    )
    messages = [{"role": "user", "content": prompt}]
    return call_gemma(messages, hf_token)


def build_block(commentaries, generated_at):
    currencies = list(commentaries.keys())
    # JSON-safe dict for JS
    js_dict = json.dumps(commentaries, ensure_ascii=False)
    first_ccy = currencies[0]
    first_html = commentaries[first_ccy]

    return f"""{MARKER_START}
<div style="margin-top:10px;padding:12px 16px;background:#fafbfc;border-left:3px solid #1a3a2f;border-radius:0 5px 5px 0;font-size:.82rem;color:#444;line-height:1.65">
  <div style="font-size:.65rem;text-transform:uppercase;letter-spacing:.5px;color:#aaa;font-weight:600;margin-bottom:6px">AI Commentary · google/gemma-4-31B-it · {generated_at} UTC</div>
  <div id="fx-ccy-commentary">{first_html}</div>
</div>
<script>
(function() {{
  var FX_COMMENTARY = {js_dict};
  var div = document.getElementById('chart-explorer');
  if (!div) return;
  div.on('plotly_buttonclicked', function(d) {{
    var lbl = d.button.label;
    var el  = document.getElementById('fx-ccy-commentary');
    if (el && FX_COMMENTARY[lbl]) el.innerHTML = FX_COMMENTARY[lbl];
  }});
}})();
</script>
{MARKER_END}"""


def inject(index_html, block):
    html = index_html.read_text(encoding="utf-8")
    html = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        block,
        html,
        flags=re.DOTALL,
    )
    index_html.write_text(html, encoding="utf-8")


def main():
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise ValueError("HF_TOKEN env var required")

    with open(SUMMARY) as f:
        summary = json.load(f)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    commentaries = {}

    for ccy_data in summary:
        ccy = ccy_data["currency"]
        print(f"\n── {ccy} ──")
        try:
            commentaries[ccy] = get_commentary(ccy_data, hf_token)
        except Exception as e:
            print(f"  failed: {e}")
            d = ccy_data
            commentaries[ccy] = (
                f"Model explains {d['r2']*100:.0f}% of {d['currency']} variance. "
                f"Residual: {d['residual']:+.1f}% vs factor fair value."
            )

    block = build_block(commentaries, generated_at)
    inject(INDEX_HTML, block)
    print(f"\nInjected commentary → {INDEX_HTML}")


if __name__ == "__main__":
    main()
