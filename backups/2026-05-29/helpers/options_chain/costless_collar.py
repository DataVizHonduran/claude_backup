#!/usr/bin/env python3
"""
Costless collar finder: for each liquid maturity, find the call strike
whose bid covers the floor put's ask (net cost ≈ 0).

Usage: python3 costless_collar.py <TICKER> <FLOOR_PRICE>
"""
import sys
from datetime import date, datetime
import yfinance as yf
import pandas as pd


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


def find_put(puts_df, floor):
    """Nearest strike to floor_price in the puts chain."""
    if puts_df.empty:
        return None
    idx = (puts_df["strike"] - floor).abs().idxmin()
    return puts_df.loc[idx]


def find_nearest_costless_call(calls_df, spot, put_ask):
    """
    OTM call (above spot) whose bid is closest to put_ask.
    Minimises |call_bid - put_ask| → net cost nearest zero.
    """
    otm = calls_df[calls_df["strike"] > spot].copy()
    if otm.empty:
        return None
    otm = otm[otm["bid"].notna() & (otm["bid"] > 0)]
    if otm.empty:
        return None
    otm["_diff"] = (otm["bid"] - put_ask).abs()
    return otm.loc[otm["_diff"].idxmin()]


def fetch(ticker_sym, floor_price):
    tk = yf.Ticker(ticker_sym)
    fi = tk.fast_info
    spot = fi["lastPrice"]
    h52 = fi["yearHigh"]
    l52 = fi["yearLow"]

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

        exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
        dte = (exp_date - today).days

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

    return {
        "ticker": ticker_sym.upper(),
        "spot": spot,
        "h52": h52,
        "l52": l52,
        "floor": floor_price,
        "rows": rows,
    }


def _pct(v, plus=False):
    sign = "+" if (plus and v >= 0) else ""
    return f"{sign}{v:.1f}%"


def _money(v):
    return f"${v:.2f}"


def build_html(data):
    ticker = data["ticker"]
    spot = data["spot"]
    h52 = data["h52"]
    l52 = data["l52"]
    floor = data["floor"]
    rows = data["rows"]

    tbody = ""
    for r in rows:
        net = r["net_cost"]
        net_cls = "credit" if net < 0 else ("zero" if net == 0 else "debit")
        net_lbl = f"${abs(net):.2f} {'credit' if net < 0 else ('even' if net == 0 else 'debit')}"
        put_oi = f'{r["put_oi"]:,}' if r["put_oi"] else "—"
        call_oi = f'{r["call_oi"]:,}' if r["call_oi"] else "—"

        tbody += f"""
        <tr>
          <td><strong>{r['expiry']}</strong><br><span class="dte">{r['dte']}d</span></td>
          <td class="put-col">{_money(r['put_strike'])}<br><span class="sub">{_pct(r['floor_pct'])} vs spot</span></td>
          <td class="put-col">{_money(r['put_ask'])}<br><span class="sub">bid {_money(r['put_bid']) if r['put_bid'] else '—'} | OI {put_oi}</span></td>
          <td class="call-col">{_money(r['call_strike'])}<br><span class="sub">{_pct(r['cap_pct'], plus=True)} vs spot</span></td>
          <td class="call-col">{_money(r['call_bid'])}<br><span class="sub">OI {call_oi}</span></td>
          <td class="{net_cls}">{net_lbl}</td>
        </tr>"""

    if not rows:
        tbody = '<tr><td colspan="6" style="text-align:center;color:#888;padding:24px">No collar data available for these expiries.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{ticker} Costless Collars</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f6fa;color:#1a1d27;padding:24px;margin:0}}
  h1{{font-size:1.4rem;font-weight:600;margin-bottom:6px}}
  .meta{{display:flex;gap:32px;margin-bottom:20px;font-size:.85rem;color:#666;flex-wrap:wrap}}
  .meta span strong{{color:#111}}
  .explain{{background:#fff;border-left:4px solid #3a5fc8;padding:10px 16px;font-size:.82rem;color:#444;border-radius:0 6px 6px 0;margin-bottom:20px;line-height:1.5}}
  table{{border-collapse:collapse;width:100%;font-size:.84rem;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
  th{{background:#e8eaf2;color:#555;text-align:left;padding:10px 14px;font-weight:600;border-bottom:2px solid #d0d5e8}}
  th.put-h{{background:#fdf0f0;color:#8b2020}}
  th.call-h{{background:#edf7f1;color:#1a5c30}}
  td{{padding:9px 14px;border-bottom:1px solid #eef0f6;vertical-align:top}}
  td.put-col{{background:#fffafa}}
  td.call-col{{background:#f5fcf7}}
  .sub{{font-size:.75rem;color:#888;margin-top:2px;display:block}}
  .dte{{font-size:.74rem;color:#aaa}}
  td.credit{{color:#1a7a3c;font-weight:600}}
  td.zero{{color:#3a5fc8;font-weight:600}}
  td.debit{{color:#b03030;font-weight:600}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{filter:brightness(.97)}}
</style>
</head>
<body>
<h1>{ticker} — Costless Collar Matrix</h1>
<div class="meta">
  <span>Spot <strong>${spot:.2f}</strong></span>
  <span>Floor Input <strong>${floor:.2f}</strong> ({_pct((floor/spot-1)*100)} vs spot)</span>
  <span>52wk High <strong>${h52:.2f}</strong></span>
  <span>52wk Low <strong>${l52:.2f}</strong></span>
  <span>Generated {date.today().isoformat()}</span>
</div>
<div class="explain">
  <strong>Collar structure:</strong> Buy put @ floor strike + sell call @ cap strike.
  For each expiry, the call is solved as the OTM strike whose bid is closest to the put ask (net cost ≈ 0).
  <strong>Net cost</strong> = put ask − call bid. <em>Credit</em> = you receive cash. <em>Debit</em> = you pay.
</div>
<table>
  <thead>
    <tr>
      <th>Expiry</th>
      <th class="put-h">Put Strike</th>
      <th class="put-h">Put Ask</th>
      <th class="call-h">Call Strike (Cap)</th>
      <th class="call-h">Call Bid</th>
      <th>Net Cost</th>
    </tr>
  </thead>
  <tbody>{tbody}</tbody>
</table>
</body>
</html>"""


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 costless_collar.py <TICKER> <FLOOR_PRICE>")
        sys.exit(1)

    sym = sys.argv[1].upper()
    try:
        floor = float(sys.argv[2])
    except ValueError:
        print(f"Invalid floor price: {sys.argv[2]}")
        sys.exit(1)

    print(f"Fetching {sym} options (floor ${floor:.2f})...")
    data = fetch(sym, floor)

    html = build_html(data)
    out = f"collar_{sym}.html"
    with open(out, "w") as f:
        f.write(html)

    print(f"Saved: {out}")
    print(f"Spot ${data['spot']:.2f} | Floor input ${floor:.2f} | {len(data['rows'])} expiries")
    for r in data["rows"]:
        print(
            f"  {r['expiry']} ({r['dte']}d)  "
            f"Put ${r['put_strike']:.0f} ask ${r['put_ask']:.2f}  |  "
            f"Call ${r['call_strike']:.0f} bid ${r['call_bid']:.2f}  |  "
            f"Net ${r['net_cost']:+.2f}"
        )


if __name__ == "__main__":
    main()
