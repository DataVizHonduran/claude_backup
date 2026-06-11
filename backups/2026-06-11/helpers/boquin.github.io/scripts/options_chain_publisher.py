#!/usr/bin/env python3
"""
Options Chain Publisher — fetches OTM options chain for any ticker,
builds the HTML page, calls Gemma 4 for collar/OI commentary,
and injects it into reports/options-chain/<TICKER>/index.html.

Usage (run from repo root):
    HF_TOKEN=hf_xxx python3 scripts/options_chain_publisher.py GOOGL

Required env vars:
    HF_TOKEN  — HuggingFace API token
"""

import os
import re
import sys
import time
import markdown as md_lib
import concurrent.futures
from datetime import date, datetime, timezone
from pathlib import Path

import yfinance as yf
import pandas as pd
from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID     = "google/gemma-4-26B-A4B-it"
REPORT_ROOT  = Path("reports/options-chain")
MARKER_START = "<!-- options-commentary-start -->"
MARKER_END   = "<!-- options-commentary-end -->"
COLLAR_MARKER_START = "<!-- costless-collar-matrix -->"
COLLAR_MARKER_END   = "<!-- costless-collar-matrix-end -->"
COLLAR_FLOORS = {"GOOGL": 300.0}  # ticker → floor price for costless collar

# ---------------------------------------------------------------------------
# Options fetch (ported from claude_projects/options_chain/options_chain.py)
# ---------------------------------------------------------------------------

def get_round_unit(spot):
    if spot < 20:
        return 1
    elif spot < 200:
        return 5
    else:
        return 10


def is_round(strike, unit):
    return round(strike % unit, 4) == 0


def find_nearest_expiry(target, available):
    parsed = sorted(datetime.strptime(e, "%Y-%m-%d").date() for e in available)
    future = [e for e in parsed if e >= target]
    pool = future if future else parsed
    return min(pool, key=lambda x: abs((x - target).days))


def target_expiry_dates(today):
    targets = []
    for month in [3, 6, 9, 12]:
        d = date(today.year, month, 1)
        if d > today:
            targets.append(d)
    targets.append(date(today.year + 1, 1, 1))
    targets.append(date(today.year + 2, 1, 1))
    return targets


def pick_strikes(chain_df, lo, hi, unit, n, ascending):
    mask = (chain_df["strike"] >= lo) & (chain_df["strike"] <= hi)
    filtered = chain_df[mask & chain_df["strike"].apply(lambda x: is_round(x, unit))].copy()
    if len(filtered) < n:
        mask2 = (chain_df["strike"] >= lo * 0.95) & (chain_df["strike"] <= hi * 1.05)
        filtered = chain_df[mask2].copy()
        mid = (lo + hi) / 2
        filtered["_dist"] = (filtered["strike"] - mid).abs()
        filtered = filtered.nsmallest(n, "_dist")
    return filtered.nsmallest(n, "strike") if ascending else filtered.nlargest(n, "strike")


def _option_52wk(sym):
    try:
        fi = yf.Ticker(sym).fast_info
        return sym, fi.get("yearHigh"), fi.get("yearLow")
    except Exception:
        return sym, None, None


def find_put(puts_df, floor):
    if puts_df.empty:
        return None
    idx = (puts_df["strike"] - floor).abs().idxmin()
    return puts_df.loc[idx]


def find_nearest_costless_call(calls_df, spot, put_ask):
    otm = calls_df[calls_df["strike"] > spot].copy()
    if otm.empty:
        return None
    otm = otm[otm["bid"].notna() & (otm["bid"] > 0)]
    if otm.empty:
        return None
    otm["_diff"] = (otm["bid"] - put_ask).abs()
    return otm.loc[otm["_diff"].idxmin()]


def fetch_collars(ticker_sym, floor_price):
    tk = yf.Ticker(ticker_sym)
    fi = tk.fast_info
    spot = fi["lastPrice"]
    h52 = fi["yearHigh"]
    l52 = fi["yearLow"]

    today = date.today()
    available = tk.options
    if not available:
        return None

    seen, selected = set(), []
    for td in target_expiry_dates(today):
        exp = find_nearest_expiry(td, available).strftime("%Y-%m-%d")
        if exp not in seen:
            seen.add(exp)
            selected.append(exp)

    rows = []
    for exp in selected:
        try:
            chain = tk.option_chain(exp)
        except Exception:
            continue

        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        put_row = find_put(chain.puts, floor_price)
        if put_row is None:
            continue

        put_strike = put_row["strike"]
        put_ask = put_row["ask"] if pd.notna(put_row.get("ask")) and put_row["ask"] > 0 else put_row["lastPrice"]
        put_bid = put_row["bid"] if pd.notna(put_row.get("bid")) else None
        put_oi = int(put_row["openInterest"]) if pd.notna(put_row.get("openInterest")) else None

        if pd.isna(put_ask) or put_ask <= 0:
            continue

        call_row = find_nearest_costless_call(chain.calls, spot, put_ask)
        if call_row is None:
            continue

        call_strike = call_row["strike"]
        call_bid = call_row["bid"]
        call_oi = int(call_row["openInterest"]) if pd.notna(call_row.get("openInterest")) else None
        net_cost = round(put_ask - call_bid, 2)

        rows.append({
            "expiry": exp,
            "dte": dte,
            "put_strike": put_strike,
            "put_bid": put_bid,
            "put_ask": put_ask,
            "put_oi": put_oi,
            "call_strike": call_strike,
            "call_bid": call_bid,
            "call_oi": call_oi,
            "net_cost": net_cost,
            "floor_pct": (put_strike / spot - 1) * 100,
            "cap_pct": (call_strike / spot - 1) * 100,
        })

    return {"ticker": ticker_sym.upper(), "spot": spot, "h52": h52, "l52": l52, "floor": floor_price, "rows": rows}


def fetch(ticker_sym):
    tk = yf.Ticker(ticker_sym)
    fi = tk.fast_info
    spot = fi["lastPrice"]
    h52 = fi["yearHigh"]
    l52 = fi["yearLow"]
    unit = get_round_unit(spot)

    today = date.today()
    targets = target_expiry_dates(today)
    available = tk.options
    if not available:
        raise ValueError(f"No options listed for {ticker_sym}")

    seen, selected = set(), []
    for td in targets:
        exp = find_nearest_expiry(td, available).strftime("%Y-%m-%d")
        if exp not in seen:
            seen.add(exp)
            selected.append(exp)

    rows = []
    for exp in selected:
        try:
            chain = tk.option_chain(exp)
        except Exception:
            continue

        call_lo, call_hi = spot * 1.20, spot * 1.30
        put_lo,  put_hi  = spot * 0.70, spot * 0.80

        calls = pick_strikes(chain.calls, call_lo, call_hi, unit, 5, ascending=True)
        puts  = pick_strikes(chain.puts,  put_lo,  put_hi,  unit, 5, ascending=False)

        def fmt_row(r, rtype):
            oi = int(r["openInterest"]) if pd.notna(r.get("openInterest")) else None
            return {
                "Expiry": exp,
                "Type": rtype,
                "Strike": r["strike"],
                "Last": r["lastPrice"],
                "contractSymbol": r["contractSymbol"],
                "OI": oi,
            }

        for _, r in calls.iterrows():
            rows.append(fmt_row(r, "CALL"))
        for _, r in puts.iterrows():
            rows.append(fmt_row(r, "PUT"))

    print(f"Fetching 52wk ranges for {len(rows)} option contracts...")
    symbols = [r["contractSymbol"] for r in rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        wk_data = {sym: (h, l) for sym, h, l in ex.map(_option_52wk, symbols)}

    for r in rows:
        h, l = wk_data.get(r["contractSymbol"], (None, None))
        r["H52"] = h
        r["L52"] = l
        del r["contractSymbol"]

    return {"ticker": ticker_sym.upper(), "spot": spot, "h52": h52, "l52": l52, "rows": rows}


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _range_chart(last, h52, l52):
    track = '<rect x="4" y="5" width="72" height="4" rx="2" fill="#d0d5e0"/>'
    if h52 is None or l52 is None or h52 == l52:
        return f'<svg width="80" height="14" style="vertical-align:middle;display:block">{track}</svg>'
    pct = max(0.0, min(100.0, (last - l52) / (h52 - l52) * 100))
    cx = 4 + pct / 100 * 72
    return (
        f'<svg width="80" height="14" style="vertical-align:middle;display:block">'
        f'{track}'
        f'<circle cx="{cx:.1f}" cy="7" r="4" fill="#3a5fc8"/>'
        f'</svg>'
    )


def build_html(data):
    ticker, spot, h52, l52 = data["ticker"], data["spot"], data["h52"], data["l52"]
    expiries = list(dict.fromkeys(r["Expiry"] for r in data["rows"]))

    panels = ""
    for i, exp in enumerate(expiries):
        active = "active" if i == 0 else ""
        tbody = ""
        for r in (x for x in data["rows"] if x["Expiry"] == exp):
            cls = "call" if r["Type"] == "CALL" else "put"
            oi = f'{r["OI"]:,}' if r["OI"] is not None else "—"
            h = f'${r["H52"]:.2f}' if r["H52"] is not None else "—"
            l = f'${r["L52"]:.2f}' if r["L52"] is not None else "—"
            chart = _range_chart(r["Last"], r["H52"], r["L52"])
            tbody += (
                f'<tr class="{cls}">'
                f'<td><span class="badge {cls}">{r["Type"]}</span></td>'
                f'<td>${r["Strike"]:.2f}</td>'
                f'<td>${r["Last"]:.2f}</td>'
                f'<td>{h}</td>'
                f'<td>{l}</td>'
                f'<td>{oi}</td>'
                f'<td>{chart}</td>'
                f'</tr>\n'
            )
        panels += (
            f'<div class="panel {active}" id="p{i}">'
            f'<table><thead><tr>'
            f'<th>Type</th><th>Strike</th><th>Last</th>'
            f'<th>52wk High</th><th>52wk Low</th><th>Open Interest</th><th>52wk Range</th>'
            f'</tr></thead><tbody>\n{tbody}</tbody></table></div>\n'
        )

    tabs = "".join(
        f'<button class="tab{"  active" if i == 0 else ""}" onclick="show({i})">{exp}</button>'
        for i, exp in enumerate(expiries)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{ticker} Options Chain</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f6fa;color:#1a1d27;padding:24px;margin:0}}
  h1{{font-size:1.4rem;font-weight:600;margin-bottom:6px;color:#111}}
  .meta{{display:flex;gap:32px;margin-bottom:20px;font-size:.85rem;color:#666}}
  .meta span strong{{color:#111}}
  .tabs{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
  .tab{{background:#e2e5ef;border:none;border-radius:6px;padding:6px 14px;font-size:.82rem;font-weight:600;color:#555;cursor:pointer;transition:background .15s,color .15s}}
  .tab.active{{background:#3a5fc8;color:#fff}}
  .tab:hover:not(.active){{background:#cdd2e8}}
  .panel{{display:none}}
  .panel.active{{display:block}}
  table{{border-collapse:collapse;width:100%;font-size:.84rem}}
  th{{background:#e8eaf2;color:#666;text-align:left;padding:8px 12px;border-bottom:2px solid #d0d5e8;font-weight:500}}
  td{{padding:7px 12px;border-bottom:1px solid #e8eaf2}}
  tr.call td{{background:#edf7f1}}
  tr.put td{{background:#fdf0f0}}
  tr.call:hover td{{background:#ddf0e6}}
  tr.put:hover td{{background:#fae0e0}}
  .badge{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:.73rem;font-weight:700}}
  .badge.call{{background:#c8ecd8;color:#1a7a3c}}
  .badge.put{{background:#fad4d4;color:#b03030}}
</style>
</head>
<body>
<h1>{ticker} — OTM Options Chain</h1>
<div class="meta">
  <span>Spot <strong>${spot:.2f}</strong></span>
  <span>52wk High <strong>${h52:.2f}</strong></span>
  <span>52wk Low <strong>${l52:.2f}</strong></span>
  <span>Generated {date.today().isoformat()}</span>
</div>
<div class="tabs">{tabs}</div>
{panels}
<script>
function show(i){{
  document.querySelectorAll('.panel').forEach((p,j)=>p.classList.toggle('active',j===i));
  document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',j===i));
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Gemma data formatter
# ---------------------------------------------------------------------------

def load_data(data: dict) -> str:
    ticker, spot, h52, l52 = data["ticker"], data["spot"], data["h52"], data["l52"]
    rows = data["rows"]

    lines = [f"{ticker} — Spot ${spot:.2f} | 52wk ${l52:.2f}–${h52:.2f}", ""]

    expiries = list(dict.fromkeys(r["Expiry"] for r in rows))

    lines.append("=== COLLAR COMBINATIONS (by expiry) ===")
    for exp in expiries:
        calls = [r for r in rows if r["Expiry"] == exp and r["Type"] == "CALL"]
        puts  = [r for r in rows if r["Expiry"] == exp and r["Type"] == "PUT"]
        lines.append(f"\nExpiry {exp}:")

        combos = []
        for c in calls:
            for p in puts:
                net = c["Last"] - p["Last"]
                combos.append((abs(net), net, c, p))
        combos.sort(key=lambda x: x[0])

        for _, net, c, p in combos[:10]:
            direction = "debit" if net > 0 else "credit"
            c_oi = f'{c["OI"]:,}' if c["OI"] is not None else "n/a"
            p_oi = f'{p["OI"]:,}' if p["OI"] is not None else "n/a"
            lines.append(
                f'  CALL ${c["Strike"]:.0f} last=${c["Last"]:.2f} OI={c_oi} | '
                f'PUT ${p["Strike"]:.0f} last=${p["Last"]:.2f} OI={p_oi} | '
                f'net=${abs(net):.2f} {direction}'
            )

    lines.append("\n=== OI EXTREMES ===")
    calls_oi = sorted([r for r in rows if r["Type"] == "CALL" and r["OI"]], key=lambda x: x["OI"], reverse=True)
    puts_oi  = sorted([r for r in rows if r["Type"] == "PUT"  and r["OI"]], key=lambda x: x["OI"], reverse=True)
    lines.append("Highest OI calls:")
    for r in calls_oi[:5]:
        lines.append(f'  {r["Expiry"]} CALL ${r["Strike"]:.0f} OI={r["OI"]:,} last=${r["Last"]:.2f}')
    lines.append("Highest OI puts:")
    for r in puts_oi[:5]:
        lines.append(f'  {r["Expiry"]} PUT ${r["Strike"]:.0f} OI={r["OI"]:,} last=${r["Last"]:.2f}')

    lines.append("\n=== PRICE vs 52wk RANGE ===")
    for r in rows:
        if r["H52"] is None or r["L52"] is None or r["H52"] == r["L52"]:
            continue
        pct = (r["Last"] - r["L52"]) / (r["H52"] - r["L52"]) * 100
        if pct > 75:
            lines.append(f'  HIGH {r["Expiry"]} {r["Type"]} ${r["Strike"]:.0f}: last=${r["Last"]:.2f} at {pct:.0f}% of 52wk range')
        elif pct < 25:
            lines.append(f'  LOW  {r["Expiry"]} {r["Type"]} ${r["Strike"]:.0f}: last=${r["Last"]:.2f} at {pct:.0f}% of 52wk range')

    text = "\n".join(lines)
    return text[:8000]


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


def generate_report(data_text: str, hf_token: str, ticker: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""[ROLE]: Senior derivatives strategist specializing in equity collars and structured overlays.

[TASK]: Analyze the following OTM options chain snapshot for {ticker} as of {today}.
Produce a structured Markdown commentary covering:
1. **Best collar combinations** — identify 2-3 specific (put strike, call strike, expiry) pairs with favorable cost/protection profile. State net debit/credit and what market scenario each collar hedges.
2. **OI hot spots** — where is open interest concentrating? What does that imply for gamma exposure or pinning risk near expiry?
3. **52wk range context** — which contracts are historically cheap or expensive relative to their own 52wk price range? What does that suggest about implied vol or positioning?
4. **One actionable trade idea** — name specific strikes and expiry. Include the net cost and max profit/loss profile.

[FORMAT]:
- Markdown with ## headers
- Use a summary table for collar combinations: | Expiry | Put Strike | Call Strike | Net Cost | Scenario |
- Bullet points for OI and 52wk sections
- Under 600 words total

[DATA]:
{data_text}"""

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
      <p style="color:#666;font-size:0.85em;margin:0;">Generated {generated_at} UTC &nbsp;&middot;&nbsp; google/gemma-4-26B-A4B-it</p>
    </div>
    <div style="line-height:1.7;color:#444;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <style>
        .options-commentary table {{border-collapse:collapse;width:100%;margin:16px 0;}}
        .options-commentary th,
        .options-commentary td {{border:1px solid #dee2e6;padding:8px 12px;text-align:left;}}
        .options-commentary th {{background:#f8f9fa;font-weight:600;}}
        .options-commentary h2,.options-commentary h3 {{color:#333;margin:20px 0 8px;}}
        .options-commentary ul {{padding-left:20px;}}
        .options-commentary li {{margin:4px 0;}}
      </style>
      <div class="options-commentary">{body_html}</div>
    </div>
  </div>
</div>
{MARKER_END}"""


def inject_into_html(index_html: Path, block: str) -> None:
    html = index_html.read_text(encoding="utf-8")
    html = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        "",
        html,
        flags=re.DOTALL,
    )
    last_body = html.rfind("</body>")
    html = html[:last_body] + block + "\n</body>" + html[last_body + len("</body>"):]
    index_html.write_text(html, encoding="utf-8")
    print(f"  Injected commentary into {index_html}")


def build_collar_block(collar_data: dict, gen_at: str) -> str:
    spot = collar_data["spot"]
    h52 = collar_data["h52"]
    l52 = collar_data["l52"]
    floor = collar_data["floor"]
    rows = collar_data["rows"]
    floor_pct = (floor / spot - 1) * 100

    tbody = ""
    for i, r in enumerate(rows):
        last = i == len(rows) - 1
        border = "none" if last else "1px solid #eef0f6"
        net = r["net_cost"]
        if net < 0:
            net_style = "color:#1a7a3c;font-weight:600"
            net_lbl = f"${abs(net):.2f} credit"
        elif net == 0:
            net_style = "color:#3a5fc8;font-weight:600"
            net_lbl = "even"
        else:
            net_style = "color:#b03030;font-weight:600"
            net_lbl = f"${net:.2f} debit"
        put_oi_str = f'{r["put_oi"]:,}' if r["put_oi"] else "—"
        put_bid_str = f'${r["put_bid"]:.2f}' if r["put_bid"] else "—"
        tbody += f"""
    <tr>
      <td style="padding:9px 14px;border-bottom:{border};vertical-align:top"><strong>{r['expiry']}</strong><br><span style="font-size:.74rem;color:#aaa">{r['dte']}d</span></td>
      <td style="padding:9px 14px;border-bottom:{border};vertical-align:top;background:#fffafa">${r['put_strike']:.2f}<br><span style="font-size:.75rem;color:#888;margin-top:2px;display:block">{r['floor_pct']:+.1f}% vs spot</span></td>
      <td style="padding:9px 14px;border-bottom:{border};vertical-align:top;background:#fffafa">${r['put_ask']:.2f}<br><span style="font-size:.75rem;color:#888;margin-top:2px;display:block">bid {put_bid_str} | OI {put_oi_str}</span></td>
      <td style="padding:9px 14px;border-bottom:{border};vertical-align:top;background:#f5fcf7">${r['call_strike']:.2f}<br><span style="font-size:.75rem;color:#888;margin-top:2px;display:block">{r['cap_pct']:+.1f}% vs spot</span></td>
      <td style="padding:9px 14px;border-bottom:{border};vertical-align:top;background:#f5fcf7">${r['call_bid']:.2f}</td>
      <td style="padding:9px 14px;border-bottom:{border};vertical-align:top;{net_style}">{net_lbl}</td>
    </tr>"""

    if not rows:
        tbody = '<tr><td colspan="6" style="text-align:center;color:#888;padding:24px">No collar data available.</td></tr>'

    return f"""{COLLAR_MARKER_START}
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f6fa;color:#1a1d27;padding:24px 0 0;margin:0">
<h2 style="font-size:1.2rem;font-weight:600;margin-bottom:6px">Costless Collar Matrix — ${floor:.0f} Floor</h2>
<div style="display:flex;gap:32px;margin-bottom:14px;font-size:.85rem;color:#666;flex-wrap:wrap">
  <span>Spot <strong style="color:#111">${spot:.2f}</strong></span>
  <span>Floor <strong style="color:#111">${floor:.2f}</strong> ({floor_pct:+.1f}% vs spot)</span>
  <span>52wk High <strong style="color:#111">${h52:.2f}</strong></span>
  <span>52wk Low <strong style="color:#111">${l52:.2f}</strong></span>
  <span>Generated {gen_at} UTC</span>
</div>
<div style="background:#fff;border-left:4px solid #3a5fc8;padding:10px 16px;font-size:.82rem;color:#444;border-radius:0 6px 6px 0;margin-bottom:16px;line-height:1.5">
  <strong>Collar structure:</strong> Buy put @ floor strike + sell call @ cap strike.
  For each expiry the call is solved as the OTM strike whose bid is closest to the put ask (net cost ≈ 0).
  <strong>Net cost</strong> = put ask − call bid. <em>Credit</em> = you receive cash. <em>Debit</em> = you pay.
</div>
<table style="border-collapse:collapse;width:100%;font-size:.84rem;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.07)">
  <thead>
    <tr>
      <th style="background:#e8eaf2;color:#555;text-align:left;padding:10px 14px;font-weight:600;border-bottom:2px solid #d0d5e8">Expiry</th>
      <th style="background:#fdf0f0;color:#8b2020;text-align:left;padding:10px 14px;font-weight:600;border-bottom:2px solid #d0d5e8">Put Strike</th>
      <th style="background:#fdf0f0;color:#8b2020;text-align:left;padding:10px 14px;font-weight:600;border-bottom:2px solid #d0d5e8">Put Ask</th>
      <th style="background:#edf7f1;color:#1a5c30;text-align:left;padding:10px 14px;font-weight:600;border-bottom:2px solid #d0d5e8">Call Strike (Cap)</th>
      <th style="background:#edf7f1;color:#1a5c30;text-align:left;padding:10px 14px;font-weight:600;border-bottom:2px solid #d0d5e8">Call Bid</th>
      <th style="background:#e8eaf2;color:#555;text-align:left;padding:10px 14px;font-weight:600;border-bottom:2px solid #d0d5e8">Net Cost</th>
    </tr>
  </thead>
  <tbody>{tbody}
  </tbody>
</table>
</div>
{COLLAR_MARKER_END}"""


def inject_collar_into_html(index_html: Path, block: str) -> None:
    html = index_html.read_text(encoding="utf-8")
    html = re.sub(
        re.escape(COLLAR_MARKER_START) + r".*?" + re.escape(COLLAR_MARKER_END),
        "",
        html,
        flags=re.DOTALL,
    )
    last_body = html.rfind("</body>")
    html = html[:last_body] + block + "\n</body>" + html[last_body + len("</body>"):]
    index_html.write_text(html, encoding="utf-8")
    print(f"  Injected collar matrix into {index_html}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/options_chain_publisher.py <TICKER>")
        sys.exit(1)

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    sym = sys.argv[1].upper()
    out_dir  = REPORT_ROOT / sym
    out_html = out_dir / "index.html"
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    gen_at   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    print(f"Fetching {sym} options...")
    data = fetch(sym)
    expiries = list(dict.fromkeys(r["Expiry"] for r in data["rows"]))
    print(f"  Spot ${data['spot']:.2f} | 52wk ${data['l52']:.2f}–${data['h52']:.2f} | {len(data['rows'])} rows | {len(expiries)} expiries")

    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(data)
    out_html.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_html}")

    print("\nBuilding Gemma data summary...")
    data_text = load_data(data)
    print(f"  {len(data_text)} chars")

    print("\nGenerating commentary via Gemma 4...")
    commentary = generate_report(data_text, hf_token, sym)

    archive = out_dir / f"commentary-{today}.md"
    archive.write_text(commentary, encoding="utf-8")
    print(f"\nWrote archive: {archive}")

    block = build_commentary_block(commentary, gen_at)
    inject_into_html(out_html, block)

    floor_price = COLLAR_FLOORS.get(sym)
    if floor_price is not None:
        print(f"\nComputing costless collar (floor ${floor_price:.0f})...")
        collar_data = fetch_collars(sym, floor_price)
        if collar_data and collar_data["rows"]:
            collar_block = build_collar_block(collar_data, gen_at)
            inject_collar_into_html(out_html, collar_block)
            print(f"  {len(collar_data['rows'])} collar expiries computed")

    print(f"\nDone — {out_html}")
    print("Next: git add reports/options-chain/ index.html && git commit -m '...' && git pull --rebase && git push")
