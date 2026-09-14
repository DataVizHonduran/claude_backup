#!/usr/bin/env python3
"""
FIFA World Cup 2026 Dashboard Commentary — AI Analysis per chart page.
Re-aggregates ESPN boxscore data (same source as build_wc2026_charts.py),
feeds a compact stats summary per chart to Gemma, and injects commentary
into each individual chart page in reports/fifa-wc-2026/.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/wc2026_commentary.py

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/fifa-wc-2026/{goals_shots,possession_shots,conversion_shots,
        longball_pass,crosses}.html  (commentary injected before </body>)
"""

import os
import re
import sys
import time
import statistics
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "wc2026"))
from espn_soccer_client import ESPNSoccerClient, aggregate_player_stats, aggregate_team_stats

import markdown as md_lib
from huggingface_hub import InferenceClient

MODEL_ID = "google/gemma-3-27b-it"
OUT_DIR = Path(__file__).parent.parent / "reports" / "fifa-wc-2026"
MATCH_RANGE = "20260601-20260701"

MARKER_START = "<!-- wc2026-commentary-start -->"
MARKER_END = "<!-- wc2026-commentary-end -->"


def call_gemma(prompt: str, hf_token: str, max_tokens: int = 700) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(5):
        try:
            resp = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            is_rate_limit = any(x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if is_rate_limit and attempt < 4:
                wait = 30 * (attempt + 1)
                print(f"  HF rate limit — waiting {wait}s (attempt {attempt+1}/5) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def top_n(rows, key, n=8, reverse=True):
    return sorted(rows, key=lambda r: r[key], reverse=reverse)[:n]


def player_summary(players, x_stat, y_stat, x_label, y_label, min_goals=0):
    rows = [p for p in players.values() if p["minutes"] >= 90 and p.get("totalGoals", 0) >= min_goals]
    for p in rows:
        p["_x"] = p[x_stat] / p["minutes"] * 90
        p["_y"] = p[y_stat] / p["minutes"] * 90
    lines = [f"Top performers by {y_label} (min 90 minutes played):"]
    for p in top_n(rows, "_y", 10):
        lines.append(f"  {p['name']} ({p['team']}, {p['confederation']}): {x_label}={p['_x']:.2f}, {y_label}={p['_y']:.2f}, minutes={p['minutes']:.0f}")
    if rows:
        lines.append(f"League medians: {x_label}={statistics.median(r['_x'] for r in rows):.2f}, {y_label}={statistics.median(r['_y'] for r in rows):.2f}")
    return "\n".join(lines)


def team_summary(teams, x_stat, y_stat, x_label, y_label):
    rows = [{"team": name, **rec} for name, rec in teams.items()]
    lines = [f"Teams ranked by {y_label}:"]
    for r in top_n(rows, y_stat, 10):
        lines.append(f"  {r['team']} ({r['confederation']}, FIFA rank {r['rank']}): {x_label}={r[x_stat]:.2f}, {y_label}={r[y_stat]:.2f}, matches={r['matches']}")
    lines.append(f"League medians: {x_label}={statistics.median(r[x_stat] for r in rows):.2f}, {y_label}={statistics.median(r[y_stat] for r in rows):.2f}")
    return "\n".join(lines)


def build_commentary_block(commentary_md: str, generated_at: str) -> str:
    body_html = md_lib.markdown(commentary_md, extensions=["tables"])
    return f"""{MARKER_START}
<div class="wc2026-commentary-wrap" style="max-width:1100px;margin:1.5rem auto 0;padding:0 1rem 2rem;">
  <style>
    .wc2026-commentary-wrap .wc2026-commentary-card {{background:#fafafa;border:1px solid #e5e5e5;border-radius:8px;padding:1.25rem 1.5rem;}}
    .wc2026-commentary-wrap .wc2026-commentary-body {{line-height:1.6;color:#444;font-family:system-ui,sans-serif;font-size:0.92rem;}}
    .wc2026-commentary table {{border-collapse:collapse;width:100%;margin:12px 0;font-size:0.85rem;}}
    .wc2026-commentary th, .wc2026-commentary td {{border:1px solid #dee2e6;padding:6px 10px;text-align:left;}}
    .wc2026-commentary th {{background:#f1f1f1;font-weight:600;}}
    .wc2026-commentary ul {{padding-left:20px;}}
    @media (max-width: 600px) {{
      .wc2026-commentary-wrap {{padding:0 0.5rem 1.5rem;}}
      .wc2026-commentary-wrap .wc2026-commentary-card {{padding:1rem;}}
      .wc2026-commentary-wrap .wc2026-commentary-body {{font-size:1rem;}}
      .wc2026-commentary table, .wc2026-commentary th, .wc2026-commentary td {{font-size:0.95rem;}}
      .wc2026-commentary th, .wc2026-commentary td {{padding:6px 8px;}}
    }}
  </style>
  <div class="wc2026-commentary-card">
    <div style="border-left:4px solid #007bff;padding-left:12px;margin-bottom:12px;">
      <h2 style="color:#333;margin:0 0 4px;font-size:1.1rem;">AI Commentary</h2>
      <p style="color:#666;font-size:0.8rem;margin:0;">Generated {generated_at} UTC &nbsp;·&nbsp; google/gemma-3-27b-it</p>
    </div>
    <div class="wc2026-commentary-body">
      <div class="wc2026-commentary">{body_html}</div>
    </div>
  </div>
</div>
{MARKER_END}"""


def inject(path: Path, block: str):
    html = path.read_text(encoding="utf-8")
    html = re.sub(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n?", "", html, flags=re.DOTALL)
    body_open = html.index("<body>") + len("<body>")
    html = html[:body_open] + "\n" + block + "\n" + html[body_open:]
    path.write_text(html, encoding="utf-8")
    print(f"  Injected commentary into {path}")


CHARTS = [
    {
        "file": "goals_shots.html",
        "kind": "player",
        "x_stat": "totalShots", "y_stat": "totalGoals",
        "x_label": "Shots/90", "y_label": "Goals/90",
        "min_goals": 1,
        "role": "Senior football scouting analyst",
        "focus": "player finishing efficiency (Goals/90 vs Shots/90) at the FIFA World Cup 2026",
    },
    {
        "file": "possession_shots.html",
        "kind": "team",
        "x_stat": "totalShots", "y_stat": "possessionPct",
        "x_label": "Shots/match", "y_label": "Possession%",
        "role": "Senior football tactics analyst",
        "focus": "team playing style — possession share vs shot volume per match at the FIFA World Cup 2026",
    },
    {
        "file": "conversion_shots.html",
        "kind": "team",
        "x_stat": "totalShots", "y_stat": "shotPct",
        "x_label": "Shots/match", "y_label": "Shot Conversion%",
        "role": "Senior football tactics analyst",
        "focus": "team finishing efficiency — shot conversion rate vs shot volume at the FIFA World Cup 2026",
    },
    {
        "file": "longball_pass.html",
        "kind": "team",
        "x_stat": "passPct", "y_stat": "longballPct",
        "x_label": "Pass%", "y_label": "Long Ball%",
        "role": "Senior football tactics analyst",
        "focus": "team style spectrum — direct (long ball) vs possession-based (pass accuracy) play at the FIFA World Cup 2026",
    },
    {
        "file": "crosses.html",
        "kind": "team",
        "x_stat": "totalCrosses", "y_stat": "accurateCrosses",
        "x_label": "Total Crosses/match", "y_label": "Accurate Crosses/match",
        "role": "Senior football tactics analyst",
        "focus": "team crossing volume and accuracy at the FIFA World Cup 2026",
    },
]


def main():
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching completed matches ({MATCH_RANGE}) ...")
    client = ESPNSoccerClient(league="fifa.world")
    event_ids = client.completed_match_ids(MATCH_RANGE)
    print(f"  {len(event_ids)} completed matches")

    players = aggregate_player_stats(client, event_ids, stat_names=("totalGoals", "totalShots", "shotsOnTarget"))
    teams = aggregate_team_stats(client, event_ids)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    for cfg in CHARTS:
        path = OUT_DIR / cfg["file"]
        if not path.exists():
            print(f"  WARNING: {path} not found — skipping", file=sys.stderr)
            continue

        if cfg["kind"] == "player":
            data = player_summary(players, cfg["x_stat"], cfg["y_stat"], cfg["x_label"], cfg["y_label"], cfg.get("min_goals", 0))
        else:
            data = team_summary(teams, cfg["x_stat"], cfg["y_stat"], cfg["x_label"], cfg["y_label"])

        print(f"\n--- {cfg['file']} ---\n{data}\n")

        prompt = f"""[ROLE]: {cfg['role']}.

[TASK]: Analyze {cfg['focus']}, based on the data below (all completed matches so far this tournament).
Write a short Markdown commentary covering:
1. Standout performers/teams and what makes them notable
2. What the data says about playing style or finishing trends
3. One outlier or surprising data point
4. One thing to watch in upcoming matches

[FORMAT]: Markdown with a ## header, bullet points, under 250 words total. No preamble.

[DATA]:
{data}"""

        print(f"Generating commentary for {cfg['file']} via Gemma ...")
        commentary = call_gemma(prompt, hf_token)
        print(commentary)

        block = build_commentary_block(commentary, generated_at)
        inject(path, block)


if __name__ == "__main__":
    main()
