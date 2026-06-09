import os, time
from huggingface_hub import InferenceClient

client = InferenceClient(token=os.environ["HF_TOKEN"])

SYSTEM_PROMPT = """You are a macro rates strategist. You receive CTA positioning data for US Treasuries
and write a concise, institutional-quality market note. Focus on:
- Current CTA crowding levels and their risk implications
- Fast vs slow mode divergences and what they signal
- Specific exhaustion/reversal risks by tenor
- Actionable trade ideas with clear triggers and rationale
Be direct, data-driven, and specific. No preamble. Use numbers from the data."""

USER_CONTENT = """=== TREASURY CTA EXHAUSTION SIGNALS — as of 2026-06-03 (generated 2026-06-05) ===

--- TAB 1: CTA EXHAUSTION OVERVIEW ---

Current Treasury Yield Snapshot:
| Tenor | Yield  | Fast Position | Slow Position | CTA Lean        |
|-------|--------|---------------|---------------|-----------------|
| 2Y    | 4.08%  | +28.5         | +18.1         | Short Duration  |
| 5Y    | 4.21%  | +30.1         | +21.0         | Short Duration  |
| 10Y   | 4.49%  | +24.2         | +15.2         | Short Duration  |
| 30Y   | 4.99%  | +18.2         | +14.0         | Short Duration  |

Note: + = Short Duration / − = Long Duration. All tenors currently short duration.
Fast Mode windows: 20/50/100-day. Slow Mode windows: 50/100/200-day.
Signal uses 252-day rolling z-score of CTA positioning; extremes flagged at ±1.5σ.

--- TAB 2: CTA TREASURY REVERSAL — Z-Score Signals ---

Fast Mode — Signal Count: 119 total, 34 high-conviction
Slow Mode — Signal Count: 80 total, 13 high-conviction

Recent Fast Mode Signals (2025-2026):
- 2025-11-14: 30Y → Long Unwind signal | peak_pos=-23.3, strength=25.3
- 2025-11-10: 10Y → Long Unwind signal | peak_pos=-24.6, strength=19.1
- 2025-11-04: 2Y  → Long Unwind signal | peak_pos=-22.0, strength=13.6
- 2025-10-31: 5Y  → Long Unwind signal | peak_pos=-21.2, strength=15.6
- 2025-10-08: 5Y  → Long Unwind signal | peak_pos=-26.5, strength=15.1
- 2025-01-30: 10Y → Short Unwind signal | peak_pos=+26.2, strength=17.2
- 2025-01-29: 30Y → Short Unwind signal | peak_pos=+30.5, strength=15.3
- 2025-01-27: 5Y  → Short Unwind signal | peak_pos=+20.3, strength=14.4
- 2024-10-21: 2Y  → Long Unwind | peak_pos=-33.6, strength=34.9 (HIGH CONVICTION)
- 2024-10-15: 5Y  → Long Unwind | peak_pos=-31.1, strength=33.4 (HIGH CONVICTION)

Recent Slow Mode Signals (2025-2026):
- 2026-03-17: 30Y → Long Unwind | strength=3.1 (weak)
- 2026-03-10: 2Y  → Long Unwind | peak_pos=-20.6, strength=9.4
- 2026-01-02: 10Y → Long Unwind | peak_pos=-14.0, strength=6.6
- 2025-12-31: 5Y  → Long Unwind | peak_pos=-21.3, strength=8.8
- 2025-05-16: 10Y → Long Unwind | strength=34.7 (HIGH CONVICTION)
- 2024-12-25: 5Y  → Long Unwind | peak_pos=-21.1, strength=56.8 (HIGH CONVICTION)
- 2024-12-19: 2Y  → Long Unwind | peak_pos=-22.8, strength=54.3 (HIGH CONVICTION)
- 2024-11-28: 10Y → Long Unwind | peak_pos=-17.8, strength=54.2 (HIGH CONVICTION)
- 2024-11-14: 30Y → Long Unwind | peak_pos=-14.6, strength=51.7 (HIGH CONVICTION)

--- TAB 3: LATEST GEMMA COMMENTARY (2026-06-05) ---

1. Duration Crowding: CTAs universally short duration across the curve. Most acute: 5Y (+30.1 Fast) and 2Y (+28.5 Fast).
2. Yield Curve Context: Positively sloped (10Y-2Y: +0.41bps; 30Y-2Y: +0.91bps). CTAs most aggressively short front/belly, least short 30Y — implying a "bear-flattening" preference.
3. Fast vs. Slow Divergences: Both modes aligned positive. Fast significantly higher than Slow (5Y: +30.1 vs +21.0), indicating accelerating momentum.
4. Exhaustion Risk: Fast mode overstretched vs Slow mode — entering zone where minor yield dip could trigger rapid short-squeeze.
5. Actionable Watch: Break below 4.40% in 10Y could catalyze fast-mode unwind → violent bond rally.

=== END DATA ===

Please provide a concise market note (~300 words) synthesizing these three data sources:
1. What is the current CTA positioning story (Tab 1)?
2. What do the historical reversal signals tell us about the current setup (Tab 2)?
3. What are the key risks and trade ideas right now, incorporating the commentary context (Tab 3)?"""

for attempt in range(3):
    try:
        resp = client.chat.completions.create(
            model="google/gemma-3-27b-it",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": USER_CONTENT},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        print(resp.choices[0].message.content.strip())
        break
    except Exception as e:
        if ("429" in str(e) or "too many" in str(e).lower()) and attempt < 2:
            wait = 30 * (attempt + 1)
            print(f"Rate limited, waiting {wait}s...")
            time.sleep(wait)
        else:
            raise
