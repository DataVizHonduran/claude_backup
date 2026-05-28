#!/usr/bin/env python3
import sys
import concurrent.futures
import yfinance as yf
import pandas as pd
from datetime import date, datetime


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
        put_lo, put_hi = spot * 0.70, spot * 0.80

        calls = pick_strikes(chain.calls, call_lo, call_hi, unit, 5, ascending=True)
        puts = pick_strikes(chain.puts, put_lo, put_hi, unit, 5, ascending=False)

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


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 options_chain.py <TICKER>")
        sys.exit(1)

    sym = sys.argv[1].upper()
    print(f"Fetching {sym} options...")
    data = fetch(sym)

    html = build_html(data)
    out = f"options_chain_{sym}.html"
    with open(out, "w") as f:
        f.write(html)

    print(f"Saved: {out}")
    print(f"Spot ${data['spot']:.2f} | 52wk ${data['l52']:.2f}–${data['h52']:.2f} | {len(data['rows'])} rows")


if __name__ == "__main__":
    main()
