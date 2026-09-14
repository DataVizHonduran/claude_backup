"""
Generate index.html for Treasury CTA signals landing page.
Reads summary.json produced by generate_treasury_cta_signals.py.
Calls Gemma (HF_TOKEN required) to generate AI commentary tab.
"""

import os
import re
import sys
import time
import json
import numpy as np
import pandas as pd
import markdown as md_lib
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

try:
    from huggingface_hub import InferenceClient
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False

OUTPUT_DIR                = "reports/treasury-cta-signals"
HIGH_CONVICTION_THRESHOLD = 60
RECENT_SIGNALS_COUNT      = 12

TENOR_ORDER = ['2Y', '5Y', '10Y', '30Y']

# ── Load summary ──────────────────────────────────────────────────────────────
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'r') as f:
    all_summaries = json.load(f)

fast_positions   = all_summaries['fast']['latest_positions']
slow_positions   = all_summaries['slow']['latest_positions']
latest_yields    = all_summaries['fast'].get('latest_yields', {})
data_as_of       = all_summaries['fast'].get('data_as_of', 'N/A')
generated_at     = datetime.fromisoformat(all_summaries['fast']['generated_at'])


# ── Signal table helpers ──────────────────────────────────────────────────────

def build_combined_signals(all_summaries, max_recent=RECENT_SIGNALS_COUNT):
    combined = []
    for mode in ['fast', 'slow']:
        for sig in all_summaries.get(mode, {}).get('signal_metadata', []):
            combined.append({**sig, 'mode': mode.upper()})
    combined.sort(key=lambda x: x['date'], reverse=True)
    return combined[:max_recent]


def build_high_conviction_signals(all_summaries, threshold=HIGH_CONVICTION_THRESHOLD):
    combined = []
    for mode in ['fast', 'slow']:
        for sig in all_summaries.get(mode, {}).get('signal_metadata', []):
            if sig.get('strength_score', 0) >= threshold:
                combined.append({**sig, 'mode': mode.upper()})
    combined.sort(key=lambda x: (x['strength_score'], x['date']), reverse=True)
    return combined[:20]


def render_signal_row(sig):
    direction_class = 'dir-long' if sig['direction'] == 'Long' else 'dir-short'
    direction_arrow = '▲' if sig['direction'] == 'Long' else '▼'
    score       = int(sig.get('strength_score', 0))
    score_class = 'score-high' if score >= 60 else ('score-mid' if score >= 35 else 'score-low')
    consensus_badge = (' <span class="consensus-badge">✓ Consensus</span>'
                       if sig.get('consensus_score', 0) > 0 else '')
    direction_label = ('Long Duration' if sig['direction'] == 'Long'
                       else 'Short Duration')
    return (
        f'<tr>'
        f'<td>{sig["date"]}</td>'
        f'<td><strong>{sig.get("tenor", sig.get("currency", ""))}</strong></td>'
        f'<td class="{direction_class}">{direction_arrow} {direction_label}{consensus_badge}</td>'
        f'<td><span class="mode-badge mode-{sig["mode"].lower()}">{sig["mode"]}</span></td>'
        f'<td class="score-cell {score_class}">{score}</td>'
        f'<td class="peak-cell">{sig.get("peak_position", 0):.1f}</td>'
        f'</tr>'
    )


recent_signals = build_combined_signals(all_summaries)
hc_signals     = build_high_conviction_signals(all_summaries)
recent_rows    = '\n'.join(render_signal_row(s) for s in recent_signals)
hc_rows        = '\n'.join(render_signal_row(s) for s in hc_signals)


# ── CTA reversal charts (z-score of positioning residuals) ───────────────────

def _build_cta_reversal_divs(output_dir, tenor_order, mode='fast', pct_window=252, pct_upper=0.95, pct_lower=0.05):
    """Build one 2-row Plotly chart per tenor: yield + CTA positioning percentile rank.
    Returns a dict {tenor: html_div_string}."""
    pos_df    = pd.read_csv(os.path.join(output_dir, f'positions_{mode}.csv'),
                            index_col=0, parse_dates=True)
    yields_df = pd.read_csv(os.path.join(output_dir, 'yields.csv'),
                            index_col=0, parse_dates=True)

    upper_val = pct_upper * 100
    lower_val = pct_lower * 100

    divs = {}
    for tenor in tenor_order:
        if tenor not in pos_df.columns or tenor not in yields_df.columns:
            continue

        pos = pos_df[tenor].dropna()
        yld = yields_df[tenor].reindex(pos.index).ffill()

        # Rolling percentile rank (0–100) over lookback window
        pct = pos.rolling(pct_window, min_periods=126).rank(pct=True) * 100

        # Crossback reversal markers
        prev_pct = pct.shift(1)
        sell_rev = pos.index[(prev_pct > upper_val) & (pct <= upper_val)]
        buy_rev  = pos.index[(prev_pct < lower_val) & (pct >= lower_val)]

        # Convert to plain Python lists — avoids binary bdata encoding that old Plotly CDN can't decode
        x_dates  = [d.strftime('%Y-%m-%d') for d in yld.index]
        y_yld    = yld.values.tolist()
        x_pct    = [d.strftime('%Y-%m-%d') for d in pct.index]
        y_pct    = pct.values.tolist()
        x_sell   = [d.strftime('%Y-%m-%d') for d in sell_rev]
        y_sell   = pct.reindex(sell_rev).values.tolist()
        x_buy    = [d.strftime('%Y-%m-%d') for d in buy_rev]
        y_buy    = pct.reindex(buy_rev).values.tolist()

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.45, 0.55],
            vertical_spacing=0.06,
            subplot_titles=(
                f"{tenor} Treasury Yield",
                f"{tenor} CTA Positioning Percentile ({pct_window}d rolling) — Reversal Signals",
            ),
        )

        # Row 1: yield
        fig.add_trace(go.Scatter(
            x=x_dates, y=y_yld,
            name=f"{tenor} Yield",
            line=dict(color="#1f77b4", width=1.5),
            hovertemplate="%{x}: %{y:.2f}%<extra></extra>",
        ), row=1, col=1)

        # Row 2: positioning percentile
        fig.add_trace(go.Scatter(
            x=x_pct, y=y_pct,
            name="Positioning Pct",
            line=dict(color="#444", width=1.2),
            hovertemplate="%{x}: %{y:.1f}th pctile<extra>Percentile</extra>",
        ), row=2, col=1)

        fig.add_hline(y=50,        line=dict(color="#aaa", width=1, dash="dot"),  row=2, col=1)
        fig.add_hline(y=upper_val, line=dict(color="#dc3545", width=1, dash="dash"), row=2, col=1)
        fig.add_hline(y=lower_val, line=dict(color="#28a745", width=1, dash="dash"), row=2, col=1)

        if x_sell:
            fig.add_trace(go.Scatter(
                x=x_sell, y=y_sell,
                mode="markers", name="Short Unwind",
                marker=dict(symbol="triangle-down", size=12, color="#dc3545",
                            line=dict(color="white", width=1)),
                hovertemplate="%{x}: %{y:.1f}th pctile<extra>Short Unwind</extra>",
            ), row=2, col=1)

        if x_buy:
            fig.add_trace(go.Scatter(
                x=x_buy, y=y_buy,
                mode="markers", name="Long Unwind",
                marker=dict(symbol="triangle-up", size=12, color="#28a745",
                            line=dict(color="white", width=1)),
                hovertemplate="%{x}: %{y:.1f}th pctile<extra>Long Unwind</extra>",
            ), row=2, col=1)

        # Background shading on row 1: extreme percentile episodes
        for above, color in [(True, "rgba(220,53,69,0.07)"), (False, "rgba(40,167,69,0.07)")]:
            in_ep, ep_start = False, None
            for dt, pv in pct.items():
                extreme = (pv > upper_val) if above else (pv < lower_val)
                if not in_ep and extreme:
                    in_ep, ep_start = True, dt.strftime('%Y-%m-%d')
                elif in_ep and not extreme:
                    fig.add_vrect(x0=ep_start, x1=dt.strftime('%Y-%m-%d'), fillcolor=color,
                                  layer="below", line_width=0, row=1, col=1)
                    in_ep = False
            if in_ep:
                fig.add_vrect(x0=ep_start, x1=pct.index[-1].strftime('%Y-%m-%d'), fillcolor=color,
                              layer="below", line_width=0, row=1, col=1)

        fig.update_layout(
            height=480, template="plotly_white",
            margin=dict(t=60, l=55, r=20, b=40),
            hovermode="x unified",
            legend=dict(orientation="h", x=0.01, y=-0.08, font=dict(size=11)),
            showlegend=True,
        )
        fig.update_yaxes(ticksuffix="%", row=1, col=1)
        fig.update_yaxes(title_text="Percentile (0–100)", range=[0, 100], row=2, col=1)

        divs[tenor] = pio.to_html(fig, full_html=False, include_plotlyjs=False,
                                   div_id=f'reversal-chart-{mode}-{tenor}',
                                   config={"displayModeBar": False})
    return divs


def _build_reversal_stats_html(output_dir, tenor_order, mode='fast', pct_window=252, pct_upper=0.95, pct_lower=0.05):
    """Return an HTML table of hit rate / avg / median gain in bps for each tenor × signal × horizon."""
    pos_df    = pd.read_csv(os.path.join(output_dir, f'positions_{mode}.csv'), index_col=0, parse_dates=True)
    yields_df = pd.read_csv(os.path.join(output_dir, 'yields.csv'), index_col=0, parse_dates=True)
    horizons  = [5, 10, 21, 63]
    rows = []

    upper_val = pct_upper * 100
    lower_val = pct_lower * 100

    for tenor in tenor_order:
        if tenor not in pos_df.columns or tenor not in yields_df.columns:
            continue
        pos = pos_df[tenor].dropna()
        yld = yields_df[tenor].reindex(pos.index).ffill()
        pct = pos.rolling(pct_window, min_periods=126).rank(pct=True) * 100
        prev_pct = pct.shift(1)
        signals = [
            ('Short Unwind', pos.index[(prev_pct > upper_val) & (pct <= upper_val)], -1),
            ('Long Unwind',  pos.index[(prev_pct < lower_val) & (pct >= lower_val)], 1),
        ]
        for sig_name, sig_idx, direction in signals:
            row = {'Tenor': tenor, 'Signal': sig_name, 'N': len(sig_idx)}
            for h in horizons:
                gains = []
                for dt in sig_idx:
                    loc = yld.index.get_loc(dt)
                    fwd = loc + h
                    if fwd >= len(yld):
                        continue
                    dy = yld.iloc[fwd] - yld.iloc[loc]
                    gains.append(-direction * dy * 100)
                if gains:
                    g = np.array(gains)
                    row[f'Hit{h}']  = round((g > 0).mean() * 100, 0)
                    row[f'Avg{h}']  = round(g.mean(), 1)
                    row[f'Med{h}']  = round(np.median(g), 1)
                else:
                    row[f'Hit{h}'] = row[f'Avg{h}'] = row[f'Med{h}'] = '—'
            rows.append(row)

    def _cell(v, is_hit=False, is_bps=False):
        if v == '—':
            return f'<td style="color:#aaa">—</td>'
        if is_hit:
            color = '#155724' if v >= 55 else ('#856404' if v >= 48 else '#721c24')
            return f'<td style="color:{color};font-weight:600">{int(v)}%</td>'
        if is_bps:
            color = '#155724' if v > 0 else ('#721c24' if v < 0 else '#333')
            return f'<td style="color:{color}">{v:+.1f}</td>'
        return f'<td>{v}</td>'

    header = (
        '<tr style="background:var(--navy);color:white">'
        '<th rowspan="2" style="padding:8px 12px">Tenor</th>'
        '<th rowspan="2" style="padding:8px 12px">Signal</th>'
        '<th rowspan="2" style="padding:8px 12px">N</th>'
        + ''.join(f'<th colspan="3" style="padding:8px 12px;text-align:center">{lbl}</th>'
                  for lbl in ['1 Week','2 Weeks','1 Month','3 Months'])
        + '</tr>'
        '<tr style="background:#2a3a5e;color:white">'
        + ''.join('<th style="padding:6px 10px;font-size:0.78rem">Hit%</th>'
                  '<th style="padding:6px 10px;font-size:0.78rem">Avg(bp)</th>'
                  '<th style="padding:6px 10px;font-size:0.78rem">Med(bp)</th>' for _ in horizons)
        + '</tr>'
    )

    body = ''
    for i, r in enumerate(rows):
        bg = '' if i % 2 == 0 else 'background:#f9f9f9;'
        sig_color = 'color:#dc3545' if 'Short' in r['Signal'] else 'color:#28a745'
        body += (
            f'<tr style="{bg}">'
            f'<td style="padding:8px 12px;font-weight:700">{r["Tenor"]}</td>'
            f'<td style="padding:8px 12px;font-weight:600;{sig_color}">{r["Signal"]}</td>'
            f'<td style="padding:8px 12px;color:#666">{r["N"]}</td>'
            + ''.join(
                _cell(r[f'Hit{h}'], is_hit=True) +
                _cell(r[f'Avg{h}'], is_bps=True) +
                _cell(r[f'Med{h}'], is_bps=True)
                for h in horizons
            )
            + '</tr>'
        )

    return (
        '<table style="width:100%;border-collapse:collapse;font-size:0.87rem;'
        'background:white;border-radius:10px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(0,0,0,0.07)">'
        + header + '<tbody>' + body + '</tbody></table>'
    )


# ── CTA positioning bar chart ─────────────────────────────────────────────────

def create_position_bar_chart(positions, mode):
    tenors = [t for t in TENOR_ORDER if t in positions]
    values = [positions[t] for t in tenors]
    colors = ['#28a745' if v > 0 else '#dc3545' for v in values]

    fig = go.Figure(go.Bar(
        x=tenors, y=values,
        marker_color=colors,
        text=[f'{v:+.1f}' for v in values],
        textposition='outside',
        textfont=dict(size=14, color='#333'),
    ))
    fig.update_layout(
        title=dict(
            text=f'CTA Positioning — {mode.upper()} Mode',
            x=0.5, xanchor='center', font=dict(size=16, color='#1a1a2e')
        ),
        xaxis=dict(title='Tenor', tickfont=dict(size=13)),
        yaxis=dict(title='Position Score', range=[-55, 55],
                   zeroline=True, zerolinecolor='black', zerolinewidth=1.5,
                   tickfont=dict(size=12)),
        plot_bgcolor='white',
        width=540, height=380,
        margin=dict(t=60, b=60, l=60, r=30),
        showlegend=False,
    )
    fig.add_annotation(
        text="+ = Short Duration / − = Long Duration",
        xref='paper', yref='paper', x=0.5, y=-0.17,
        showarrow=False, font=dict(size=11, color='grey')
    )
    return fig


fig_fast = create_position_bar_chart(fast_positions, 'fast')
fig_slow = create_position_bar_chart(slow_positions, 'slow')

fast_chart_div = pio.to_html(fig_fast, full_html=False, include_plotlyjs=False)
slow_chart_div = pio.to_html(fig_slow, full_html=False, include_plotlyjs=False)

print("Building CTA Treasury Reversal charts...")
reversal_chart_divs_fast = _build_cta_reversal_divs(OUTPUT_DIR, TENOR_ORDER, mode='fast')
reversal_chart_divs_slow = _build_cta_reversal_divs(OUTPUT_DIR, TENOR_ORDER, mode='slow')
reversal_stats_fast = _build_reversal_stats_html(OUTPUT_DIR, TENOR_ORDER, mode='fast')
reversal_stats_slow = _build_reversal_stats_html(OUTPUT_DIR, TENOR_ORDER, mode='slow')

def _reversal_grid(chart_divs):
    return ''.join(
        f'<div style="background:white;border-radius:10px;padding:14px;'
        f'box-shadow:0 2px 8px rgba(0,0,0,0.07);">{chart_divs.get(t,"")}</div>'
        for t in TENOR_ORDER
    )

reversal_grid_fast = _reversal_grid(reversal_chart_divs_fast)
reversal_grid_slow = _reversal_grid(reversal_chart_divs_slow)


# ── Yield snapshot table ──────────────────────────────────────────────────────

def render_yield_row(tenor):
    yld = latest_yields.get(tenor, 'N/A')
    fp  = fast_positions.get(tenor, 0)
    sp  = slow_positions.get(tenor, 0)
    avg = (fp + sp) / 2

    pos_label = ('Short Duration' if avg > 10
                 else 'Long Duration' if avg < -10
                 else 'Neutral')
    pos_class = ('dir-short' if avg > 10
                 else 'dir-long' if avg < -10
                 else '')
    return (
        f'<tr>'
        f'<td><strong>{tenor}</strong></td>'
        f'<td>{yld:.2f}%</td>'
        f'<td>{fp:+.1f}</td>'
        f'<td>{sp:+.1f}</td>'
        f'<td class="{pos_class}">{pos_label}</td>'
        f'</tr>'
    )


yield_rows = '\n'.join(render_yield_row(t) for t in TENOR_ORDER if t in latest_yields)

# Fast / Slow signal count summary
fast_total = all_summaries['fast']['signal_count']
slow_total = all_summaries['slow']['signal_count']
fast_hc    = all_summaries['fast']['high_conviction_count']
slow_hc    = all_summaries['slow']['high_conviction_count']


# ── Chart links ───────────────────────────────────────────────────────────────
def chart_card(tenor, mode):
    fname = f"{tenor}_exhaustion_{mode}.html"
    return (
        f'<a href="{fname}" class="chart-card">'
        f'<div class="chart-tenor">{tenor}</div>'
        f'<div class="chart-mode">{mode.upper()}</div>'
        f'</a>'
    )


chart_links_fast = ' '.join(chart_card(t, 'fast') for t in TENOR_ORDER)
chart_links_slow = ' '.join(chart_card(t, 'slow') for t in TENOR_ORDER)


# ── AI Commentary (Gemma) ──────────────────────────────────────────────────────

MODEL_ID = "google/gemma-4-31B-it"
COMMENTARY_ARCHIVE = os.path.join(OUTPUT_DIR, f"commentary-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md")

def _build_gemma_prompt(all_summaries, latest_yields, data_as_of):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = []

    y = latest_yields
    lines.append(f"=== CURRENT YIELDS (as of {data_as_of}) ===")
    lines.append("  " + " | ".join(f"{t}: {v:.2f}%" for t, v in sorted(y.items())))
    y2, y10, y30 = y.get("2Y", 0), y.get("10Y", 0), y.get("30Y", 0)
    lines.append(f"  10Y-2Y: {y10-y2:+.2f}bps  |  30Y-2Y: {y30-y2:+.2f}bps\n")

    for mode in ("fast", "slow"):
        m = all_summaries[mode]
        lines.append(f"=== {mode.upper()} MODE ({m['windows']}) ===")
        lines.append(f"Signals: {m['signal_count']}  |  High-conviction (≥60): {m['high_conviction_count']}")
        pos = sorted(m["latest_positions"].items(), key=lambda x: x[1])
        lines.append("Positions (+ = short duration / - = long duration):")
        lines.append("  " + ", ".join(f"{t}: {v:+.1f}" for t, v in pos))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
        recent = sorted(
            [s for s in m.get("signal_metadata", []) if s.get("date", "") >= cutoff],
            key=lambda x: x.get("strength_score", 0), reverse=True
        )[:6]
        if recent:
            lines.append("Recent signals (14d, by strength):")
            for s in recent:
                lines.append(
                    f"  {s['date']} {s['tenor']} {s['direction']} | "
                    f"strength={s['strength_score']:.1f} peak={s['peak_position']:+.1f}"
                )
        lines.append("")

    data = "\n".join(lines)
    return f"""[ROLE]: Senior Rates/Macro Strategist — CTA trend-following and Treasury exhaustion signals.

SIGN CONVENTION: POSITIVE (+) = CTAs SHORT duration (rising-yield bet). NEGATIVE (-) = CTAs LONG duration (falling-yield bet).

[TASK]: Analyze Treasury CTA positioning as of {today}. Produce structured Markdown commentary:
1. Duration crowding — which tenors CTAs are most positioned and what it signals
2. Yield curve context — how spreads relate to positioning
3. Fast vs slow divergences — where modes disagree and what it implies for trend conviction
4. Recent exhaustion signals — what high-conviction signals say about crowded duration trades
5. One actionable watch-list item for the next 5 trading days

[FORMAT]: Markdown headers (##, ###), bullet points, under 350 words.

[DATA]:
{data}"""


def _call_gemma(prompt, hf_token):
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(5):
        try:
            stream = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1200,
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
            rate_limit = any(x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n  HF rate limit — waiting {wait}s (attempt {attempt+1}/5)...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def generate_commentary_tab(all_summaries, latest_yields, data_as_of):
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token or not HF_AVAILABLE:
        print("  HF_TOKEN not set or huggingface_hub unavailable — skipping AI commentary tab")
        return "", ""

    print("\nGenerating AI commentary via Gemma...")
    prompt = _build_gemma_prompt(all_summaries, latest_yields, data_as_of)
    commentary_md = _call_gemma(prompt, hf_token)

    if not commentary_md.strip():
        print("  WARNING: Gemma returned empty output — skipping tab", file=sys.stderr)
        return "", ""

    # Archive to dated .md file
    with open(COMMENTARY_ARCHIVE, "w") as f:
        f.write(commentary_md)
    print(f"  Archived → {COMMENTARY_ARCHIVE}")

    generated_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    body_html = md_lib.markdown(commentary_md, extensions=["tables"])
    tab_html = f"""<div style="background:white;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.07);padding:30px;max-width:900px;">
  <div style="border-left:4px solid #e94560;padding-left:16px;margin-bottom:20px;">
    <h2 style="color:#1a1a2e;margin:0 0 4px;border:none;padding:0;">AI Commentary</h2>
    <p style="color:#888;font-size:0.83rem;margin:0;">Generated {generated_ts} UTC &nbsp;·&nbsp; {MODEL_ID}</p>
  </div>
  <style>
    .ai-commentary h2,.ai-commentary h3{{color:#1a1a2e;margin:18px 0 8px;}}
    .ai-commentary ul{{padding-left:20px;}} .ai-commentary li{{margin:4px 0;}}
    .ai-commentary table{{border-collapse:collapse;width:100%;margin:12px 0;}}
    .ai-commentary th,.ai-commentary td{{border:1px solid #dee2e6;padding:7px 11px;}}
    .ai-commentary th{{background:#f8f9fa;font-weight:600;}}
  </style>
  <div class="ai-commentary" style="line-height:1.7;color:#444;">{body_html}</div>
</div>"""
    return tab_html, commentary_md


commentary_tab_html, _ = generate_commentary_tab(all_summaries, latest_yields, data_as_of)
has_commentary = bool(commentary_tab_html)

_commentary_btn = (
    '<button class="page-tab-btn" onclick="switchPage(\'commentary\', this)">AI Commentary</button>'
    if has_commentary else ''
)


# ── Build HTML ─────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Treasury CTA Exhaustion Signals</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
  :root {{
    --navy:  #1a1a2e;
    --teal:  #16213e;
    --blue:  #0f3460;
    --accent:#e94560;
    --green: #28a745;
    --red:   #dc3545;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f7fa;
    color: #333;
  }}
  header {{
    background: linear-gradient(135deg, var(--navy), var(--blue));
    color: white;
    padding: 28px 40px;
  }}
  header h1 {{ font-size: 2rem; margin-bottom: 4px; }}
  header p  {{ opacity: 0.75; font-size: 0.95rem; }}
  .badge-row {{ display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; }}
  .badge {{
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.82rem;
  }}
  main {{ max-width: 1300px; margin: 0 auto; padding: 30px 24px; }}
  h2 {{
    font-size: 1.25rem; color: var(--navy);
    border-bottom: 2px solid var(--accent);
    padding-bottom: 6px; margin-bottom: 18px;
  }}
  /* ── Yield snapshot ── */
  .yield-table {{
    width: 100%; border-collapse: collapse; margin-bottom: 32px;
    background: white; border-radius: 10px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  }}
  .yield-table th, .yield-table td {{
    padding: 12px 16px; text-align: center; font-size: 0.9rem;
  }}
  .yield-table th {{
    background: var(--navy); color: white; font-weight: 600;
  }}
  .yield-table tr:nth-child(even) {{ background: #f9f9f9; }}
  /* ── Bar charts ── */
  .charts-grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
    margin-bottom: 32px;
  }}
  .chart-box {{
    background: white; border-radius: 10px; padding: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  }}
  /* ── Range selector ── */
  .range-bar {{
    display: flex; align-items: center; gap: 6px; margin-bottom: 18px;
  }}
  .range-btn {{
    padding: 4px 14px; border-radius: 14px; cursor: pointer;
    border: 1.5px solid #aaa; background: white;
    font-weight: 600; color: #555; font-size: 0.82rem;
    transition: all 0.15s;
  }}
  .range-btn.active {{ background: var(--navy); color: white; border-color: var(--navy); }}
  /* ── Top-level page tabs ── */
  .page-tab-bar {{
    display: flex; gap: 0; margin: 0 0 30px;
    border-bottom: 3px solid var(--navy);
  }}
  .page-tab-btn {{
    padding: 10px 28px; cursor: pointer;
    border: none; border-radius: 8px 8px 0 0;
    background: #e8eaf0; font-weight: 700;
    color: var(--navy); font-size: 0.95rem;
    transition: all 0.2s; margin-right: 4px;
  }}
  .page-tab-btn.active {{ background: var(--navy); color: white; }}
  .page-tab-pane {{ display: none; }}
  .page-tab-pane.active {{ display: block; }}
  /* ── Mode tabs (inner) ── */
  .tab-bar {{
    display: flex; gap: 8px; margin-bottom: 14px;
  }}
  .tab-btn {{
    padding: 7px 20px; border-radius: 20px; cursor: pointer;
    border: 2px solid var(--navy); background: white;
    font-weight: 600; color: var(--navy); font-size: 0.88rem;
    transition: all 0.2s;
  }}
  .tab-btn.active {{ background: var(--navy); color: white; }}
  .tab-pane {{ display: none; }}
  .tab-pane.active {{ display: block; }}
  /* ── Chart card links ── */
  .chart-cards {{
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 32px;
  }}
  .chart-card {{
    display: flex; flex-direction: column; align-items: center;
    justify-content: center;
    width: 110px; height: 80px;
    background: white; border-radius: 10px;
    border: 2px solid #ddd;
    text-decoration: none; color: var(--navy);
    transition: all 0.2s;
    box-shadow: 0 2px 6px rgba(0,0,0,0.07);
  }}
  .chart-card:hover {{
    border-color: var(--accent); box-shadow: 0 4px 12px rgba(233,69,96,0.2);
    transform: translateY(-2px);
  }}
  .chart-tenor {{ font-size: 1.1rem; font-weight: 700; }}
  .chart-mode  {{ font-size: 0.72rem; color: #888; text-transform: uppercase; }}
  /* ── Signal tables ── */
  .signal-table {{
    width: 100%; border-collapse: collapse; margin-bottom: 32px;
    background: white; border-radius: 10px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  }}
  .signal-table th, .signal-table td {{
    padding: 10px 14px; text-align: center; font-size: 0.87rem;
  }}
  .signal-table th   {{ background: var(--navy); color: white; font-weight: 600; }}
  .signal-table tr:nth-child(even) {{ background: #f9f9f9; }}
  .dir-long  {{ color: var(--green); font-weight: 600; }}
  .dir-short {{ color: var(--red);   font-weight: 600; }}
  .mode-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 0.78rem; font-weight: 700; letter-spacing: 0.5px;
  }}
  .mode-fast {{ background: #fff3cd; color: #856404; }}
  .mode-slow {{ background: #cce5ff; color: #004085; }}
  .score-high {{ color: #155724; font-weight: 700; }}
  .score-mid  {{ color: #856404; font-weight: 600; }}
  .score-low  {{ color: #888;    font-weight: 400; }}
  .score-cell {{ font-size: 0.95rem; font-variant-numeric: tabular-nums; }}
  .peak-cell  {{ font-variant-numeric: tabular-nums; }}
  .consensus-badge {{
    background: #d4edda; color: #155724;
    border-radius: 10px; padding: 1px 6px; font-size: 0.75rem;
    margin-left: 4px;
  }}
  /* ── Stats cards ── */
  .stats-row {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
    margin-bottom: 32px;
  }}
  .stat-card {{
    background: white; border-radius: 10px; padding: 18px 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07); text-align: center;
  }}
  .stat-value {{ font-size: 1.8rem; font-weight: 700; color: var(--navy); }}
  .stat-label {{ font-size: 0.8rem; color: #888; margin-top: 4px; }}
  footer {{
    text-align: center; padding: 28px;
    color: #aaa; font-size: 0.82rem; margin-top: 20px;
  }}
  @media (max-width: 768px) {{
    .charts-grid {{ grid-template-columns: 1fr; }}
    .stats-row   {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<header>
  <h1>🏛️ Treasury CTA Exhaustion Signals</h1>
  <p>Trend-following positioning model applied to 2Y / 5Y / 10Y / 30Y US Treasury yields</p>
  <div class="badge-row">
    <span class="badge">Data as of {data_as_of}</span>
    <span class="badge">Generated {generated_at.strftime('%Y-%m-%d %H:%M')}</span>
    <span class="badge">FRED: DGS2 · DGS5 · DGS10 · DGS30</span>
    <span class="badge">Fast (20/50/100) + Slow (50/100/200)</span>
  </div>
</header>

<main>

  <!-- ── Top-level page tabs ── -->
  <div class="page-tab-bar">
    <button class="page-tab-btn active" onclick="switchPage('overview', this)">CTA Exhaustion</button>
    <button class="page-tab-btn"        onclick="switchPage('reversal', this)">CTA Treasury Reversal</button>
    {_commentary_btn}
  </div>

  <!-- ══ Tab: CTA Exhaustion (existing content) ══ -->
  <div id="page-tab-overview" class="page-tab-pane active">

    <!-- ── Current yield snapshot ── -->
    <h2>Current Treasury Yield Snapshot</h2>
    <table class="yield-table">
      <thead>
        <tr>
          <th>Tenor</th>
          <th>Yield</th>
          <th>Fast Position</th>
          <th>Slow Position</th>
          <th>CTA Lean</th>
        </tr>
      </thead>
      <tbody>
        {yield_rows}
      </tbody>
    </table>

    <!-- ── Positioning bar charts ── -->
    <h2>CTA Positioning by Mode</h2>
    <div class="charts-grid">
      <div class="chart-box">{fast_chart_div}</div>
      <div class="chart-box">{slow_chart_div}</div>
    </div>

    <!-- ── Chart links ── -->
    <h2>Individual Tenor Charts</h2>
    <div class="tab-bar">
      <button class="tab-btn active" onclick="switchTab('fast', this)">Fast Mode (20/50/100)</button>
      <button class="tab-btn"       onclick="switchTab('slow', this)">Slow Mode (50/100/200)</button>
    </div>
    <div id="tab-fast" class="tab-pane active">
      <div class="chart-cards">{chart_links_fast}</div>
    </div>
    <div id="tab-slow" class="tab-pane">
      <div class="chart-cards">{chart_links_slow}</div>
    </div>

  </div><!-- /page-tab-overview -->

  <!-- ══ Tab: CTA Treasury Reversal ══ -->
  <div id="page-tab-reversal" class="page-tab-pane">
    <h2>CTA Treasury Reversal — Positioning Percentile Signals</h2>
    <p style="color:#666;font-size:0.9rem;margin-bottom:14px;">
      252-day rolling percentile rank of CTA positioning (100 = most short-duration in the past year, 0 = most long-duration).
      Extremes flag crowded positions; crossbacks through the 95th/5th percentile mark the unwind.
      <span style="color:#dc3545;font-weight:600;">▼ Short Unwind</span> = crowded short-duration bet reversing &nbsp;·&nbsp;
      <span style="color:#28a745;font-weight:600;">▲ Long Unwind</span> = crowded long-duration bet reversing.
    </p>
    <!-- inner Fast/Slow tabs -->
    <div class="tab-bar" id="reversal-tab-bar">
      <button class="tab-btn active" onclick="switchReversalMode('fast', this)">Fast (20/50/100)</button>
      <button class="tab-btn"       onclick="switchReversalMode('slow', this)">Slow (50/100/200)</button>
    </div>
    <div class="range-bar">
      <span style="font-size:0.82rem;color:#888;margin-right:8px;">Range:</span>
      <button class="range-btn active" onclick="setReversalRange('all', this)">All</button>
      <button class="range-btn" onclick="setReversalRange(10, this)">10Y</button>
      <button class="range-btn" onclick="setReversalRange(5, this)">5Y</button>
      <button class="range-btn" onclick="setReversalRange(3, this)">3Y</button>
      <button class="range-btn" onclick="setReversalRange(1, this)">1Y</button>
    </div>
    <!-- Fast mode -->
    <div id="reversal-tab-fast" class="tab-pane active">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
        {reversal_grid_fast}
      </div>
      <h2 style="margin-top:32px">Signal Performance — Fast Mode</h2>
      <p style="color:#666;font-size:0.85rem;margin-bottom:14px;">
        Positive = signal was correct. Hit% ≥ 55 highlighted green, ≤ 48 red.
      </p>
      {reversal_stats_fast}
    </div>
    <!-- Slow mode -->
    <div id="reversal-tab-slow" class="tab-pane">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
        {reversal_grid_slow}
      </div>
      <h2 style="margin-top:32px">Signal Performance — Slow Mode</h2>
      <p style="color:#666;font-size:0.85rem;margin-bottom:14px;">
        Positive = signal was correct. Hit% ≥ 55 highlighted green, ≤ 48 red.
      </p>
      {reversal_stats_slow}
    </div>
  </div><!-- /page-tab-reversal -->

  <!-- ══ Tab: AI Commentary ══ -->
  {'<div id="page-tab-commentary" class="page-tab-pane">' + commentary_tab_html + '</div>' if has_commentary else ''}

</main>

<footer>
  Data sourced from FRED (Federal Reserve Bank of St. Louis) · DGS2, DGS5, DGS10, DGS30<br>
  CTA exhaustion model: dual-mode EMA positioning with rolling percentile thresholds, ROC filter, RSI confirmation, and strength scoring.<br>
  Positive position = short duration (rising yields) · Negative position = long duration (falling yields)
</footer>

<script>
function setReversalRange(years, btn) {{
  document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  // Determine active reversal mode
  const activeRPane = document.querySelector('#reversal-tab-fast.active, #reversal-tab-slow.active');
  const rMode = (activeRPane && activeRPane.id.includes('slow')) ? 'slow' : 'fast';
  const ids = ['2Y','5Y','10Y','30Y'].map(t => 'reversal-chart-' + rMode + '-' + t);
  const end = new Date();
  const endStr = end.toISOString().slice(0,10);
  let startStr;
  if (years === 'all') {{
    startStr = '2010-01-01';
  }} else {{
    const s = new Date();
    s.setFullYear(s.getFullYear() - years);
    startStr = s.toISOString().slice(0,10);
  }}
  ids.forEach(id => {{
    const el = document.getElementById(id);
    if (!el) return;
    // Compute visible y ranges from trace data within the selected x window
    let y1min = Infinity, y1max = -Infinity;
    let y2min = Infinity, y2max = -Infinity;
    el.data.forEach(trace => {{
      const xs = trace.x, ys = trace.y;
      if (!xs || !ys) return;
      const axis = trace.yaxis || 'y';
      for (let i = 0; i < xs.length; i++) {{
        if (xs[i] >= startStr && xs[i] <= endStr && ys[i] != null && isFinite(ys[i])) {{
          if (axis === 'y' || axis === 'y1') {{
            y1min = Math.min(y1min, ys[i]);
            y1max = Math.max(y1max, ys[i]);
          }} else if (axis === 'y2') {{
            y2min = Math.min(y2min, ys[i]);
            y2max = Math.max(y2max, ys[i]);
          }}
        }}
      }}
    }});
    const p1 = (y1max - y1min) * 0.06 || 0.1;
    const p2 = (y2max - y2min) * 0.10 || 0.2;
    Plotly.relayout(id, {{
      'xaxis.range':  [startStr, endStr],
      'yaxis.range':  [y1min - p1, y1max + p1],
      'yaxis2.range': [0, 100]
    }});
  }});
}}
function switchPage(page, btn) {{
  document.querySelectorAll('.page-tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.page-tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-tab-' + page).classList.add('active');
  btn.classList.add('active');
}}
function switchTab(mode, btn) {{
  const bar = document.querySelector('#page-tab-overview .tab-bar');
  bar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  ['fast','slow'].forEach(m => {{
    const p = document.getElementById('tab-' + m);
    if (p) p.classList.toggle('active', m === mode);
  }});
}}
function switchReversalMode(mode, btn) {{
  const bar = document.getElementById('reversal-tab-bar');
  bar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  ['fast','slow'].forEach(m => {{
    const p = document.getElementById('reversal-tab-' + m);
    if (p) p.classList.toggle('active', m === mode);
  }});
  // Re-apply current range to the newly visible charts
  const activeRangeBtn = document.querySelector('.range-btn.active');
  if (activeRangeBtn) {{
    const label = activeRangeBtn.textContent.trim();
    const years = label === 'All' ? 'all' : parseInt(label);
    setReversalRange(years, activeRangeBtn);
  }}
}}
</script>

</body>
</html>"""

out_path = os.path.join(OUTPUT_DIR, 'index.html')
with open(out_path, 'w') as f:
    f.write(html)

print(f"✅ index.html written → {out_path}")
print(f"   Fast: {fast_total} signals ({fast_hc} high-conviction)")
print(f"   Slow: {slow_total} signals ({slow_hc} high-conviction)")
