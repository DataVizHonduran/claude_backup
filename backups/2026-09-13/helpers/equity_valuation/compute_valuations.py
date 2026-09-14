"""Compute DCF v2 (EBITDA-build / FCFE-variant) + peer comps + blended PT for every
ticker with cached fundamentals. Generalizes the methodology built for the 10-name
pilot to run mechanically across the full S&P 500.

Usage:
  python3 compute_valuations.py              # recompute everyone with valid fundamentals
  python3 compute_valuations.py AAPL MSFT    # recompute just these (still uses full
                                              # peer universe for comps)
"""
import json, sys, time

DATA_DIR = "/Users/macproajb/claude_projects/equity_valuation/data"
CONST_PATH = f"{DATA_DIR}/sp500_constituents.json"
FUND_PATH = f"{DATA_DIR}/fundamentals.json"
OUT_PATH = f"{DATA_DIR}/valuations.json"

RF = 0.043
ERP = 0.055
TERM_G = 0.025
# Rate-regulated/dividend-discount-style sectors: capex is largely rate-base growth
# recovered through allowed ROE, not something a standard unregulated-firm FCFF DCF
# should net against EBITDA -- doing so understates value (confirmed empirically:
# routing Utilities through the EBITDA/capex build put ~20 of 31 names into negative
# DCF territory even though none are distressed). Use the net-income FCFE variant
# instead, same convention as banks/REITs.
FIN_SECTORS = {"Financials", "Real Estate", "Utilities"}

def load(path):
    with open(path) as f:
        return json.load(f)

def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    import os
    os.replace(tmp, path)

def raw_cagr(vals):
    """Unfloored/uncapped CAGR off vals[0] (most recent) vs vals[min(3,len-1)].
    None if not computable (requires both endpoints strictly positive -- a CAGR
    across a sign change, e.g. a loss year, isn't a meaningful growth rate)."""
    if not vals or vals[0] is None or vals[0] <= 0:
        return None
    n = min(3, len(vals) - 1)
    while n > 0 and (vals[n] is None or vals[n] <= 0):
        n -= 1
    if n == 0:
        return None
    try:
        g = (vals[0] / vals[n]) ** (1 / n) - 1
    except Exception:
        return None
    if isinstance(g, complex):
        return None
    return g

def cagr(vals, floor=TERM_G, cap=0.20):
    """Floored/capped wrapper around raw_cagr."""
    g = raw_cagr(vals)
    if g is None:
        return None
    return max(floor, min(cap, g))

def fade_growth(g1, year, term=TERM_G):
    if year <= 5:
        return g1
    return g1 - (g1 - term) * (year - 5) / 5

def dcf_ebitda_build(rev0, ebitda_margin, capex_int, tax_rate, g1, wacc, net_debt, shares):
    rev = rev0
    pv_sum = 0.0
    last_fcf = None
    for y in range(1, 11):
        g = fade_growth(g1, y)
        rev = rev * (1 + g)
        ebitda = rev * ebitda_margin
        capex = rev * capex_int
        fcf = ebitda * (1 - tax_rate) - capex
        pv_sum += fcf / (1 + wacc) ** y
        last_fcf = fcf
    tv = last_fcf * (1 + TERM_G) / (wacc - TERM_G)
    pv_tv = tv / (1 + wacc) ** 10
    ev = pv_sum + pv_tv
    eq = ev - net_debt
    return eq / shares if shares else None

def dcf_fcfe_build(ni0, g1, ke, shares):
    pv_sum = 0.0
    ni = ni0
    last_ni = None
    for y in range(1, 11):
        g = fade_growth(g1, y)
        ni = ni * (1 + g)
        pv_sum += ni / (1 + ke) ** y
        last_ni = ni
    tv = last_ni * (1 + TERM_G) / (ke - TERM_G)
    pv_tv = tv / (1 + ke) ** 10
    eq = pv_sum + pv_tv
    return eq / shares if shares else None

def build_peer_map(constituents, fund):
    by_sub = {}
    by_sector = {}
    for c in constituents:
        t = c["ticker"]
        f = fund.get(t)
        if not f or f.get("error") or not f.get("marketCap"):
            continue
        by_sub.setdefault(c["sub_industry"], []).append((t, f["marketCap"]))
        by_sector.setdefault(c["sector"], []).append((t, f["marketCap"]))
    for d in (by_sub, by_sector):
        for k in d:
            d[k].sort(key=lambda x: -x[1])
    return by_sub, by_sector

def get_peers(ticker, sub_industry, sector, by_sub, by_sector, n=4):
    pool = [t for t, _ in by_sub.get(sub_industry, []) if t != ticker]
    if len(pool) < 2:
        pool = [t for t, _ in by_sector.get(sector, []) if t != ticker]
    return pool[:n]

def compute_one(ticker, meta, fund, by_sub, by_sector):
    f = fund.get(ticker)
    if not f or f.get("error"):
        return None
    price = f.get("currentPrice")
    shares_raw = f.get("sharesOutstanding")
    beta = f.get("beta") if f.get("beta") is not None else 1.0
    if not price or not shares_raw:
        return None
    shares = shares_raw / 1e9

    sector = meta["sector"]
    variant = "fcfe" if sector in FIN_SECTORS else "ebitda"

    net_debt = None
    if f.get("totalDebt") is not None and f.get("totalCash") is not None:
        net_debt = (f["totalDebt"] - f["totalCash"]) / 1e9

    notes = []
    dcf_price = None

    if variant == "ebitda":
        revenue = f.get("revenue")
        ebitda = f.get("ebitda")
        if not revenue or not ebitda or revenue[0] in (None, 0) or ebitda[0] is None:
            variant = "fcfe"  # fall back if EBITDA build isn't possible
            notes.append("ebitda-data-missing, used FCFE fallback")
        else:
            margins = [ebitda[i] / revenue[i] for i in range(min(3, len(ebitda)))
                       if ebitda[i] is not None and revenue[i]]
            # 3yr average, not just the latest year -- guards against one-off items
            # (impairments, etc.) sitting in yfinance's reported EBITDA line for a
            # single year and swamping the whole DCF (e.g. APD FY25).
            ebitda_margin = sum(margins) / len(margins) if margins else ebitda[0] / revenue[0]
            if ebitda_margin <= 0:
                notes.append("negative-avg-ebitda-margin")
            capex = f.get("capex")
            if capex and any(c is not None for c in capex[:3]):
                intens = [abs(capex[i]) / revenue[i] for i in range(min(3, len(capex)))
                          if capex[i] is not None and revenue[i]]
                capex_int = sum(intens) / len(intens) if intens else 0.05
            else:
                capex_int = 0.05
                notes.append("capex-estimated")

            tax = f.get("tax"); pretax = f.get("pretax")
            if tax and pretax:
                rates = [tax[i] / pretax[i] for i in range(min(3, len(tax)))
                         if pretax[i] not in (None, 0) and tax[i] is not None]
                tax_rate = sum(rates) / len(rates) if rates else 0.21
            else:
                tax_rate = 0.21
                notes.append("tax-rate-estimated")
            tax_rate = max(0.05, min(0.30, tax_rate))

            g1_rev = cagr(revenue)
            g1_ebitda_raw = raw_cagr(ebitda)
            g1_rev_raw = raw_cagr(revenue)
            g1 = g1_rev if g1_rev is not None else TERM_G
            if (g1_rev_raw is not None and g1_ebitda_raw is not None
                    and g1_rev_raw > 0 and g1_ebitda_raw < 0):
                # revenue/EBITDA diverging in sign (the UNH case) -- trust EBITDA growth instead
                g1 = max(TERM_G, min(0.30, g1_ebitda_raw if g1_ebitda_raw > 0 else TERM_G))
                notes.append("margin/revenue-divergence override: grew EBITDA directly, not revenue x flat margin")

            interest = f.get("interest")
            total_debt = f.get("totalDebt")
            if interest and interest[0] and total_debt:
                kd = max(interest[0] * 1e9 / total_debt, RF)
                kd = min(kd, 0.08)
            else:
                kd = RF
            mcap = f.get("marketCap") or 0
            debt = total_debt or 0
            v_tot = mcap + debt
            e_over_v = mcap / v_tot if v_tot else 1.0
            d_over_v = debt / v_tot if v_tot else 0.0
            ke = max(RF + beta * ERP, 0.07)  # floor: low-beta names can still have volatile/cyclical earnings (e.g. P&C insurers) that CAPM beta alone doesn't price
            wacc = e_over_v * ke + d_over_v * kd * (1 - tax_rate)
            # WACC floor scales up with leverage: plain E/V*Ke + D/V*Kd*(1-tax) gives
            # too much credit to cheap after-tax debt at extreme leverage (e.g. CHTR at
            # 83% D/V), because it treats Ke as leverage-independent even when observed
            # beta doesn't fully capture that risk. A rising floor is a simple, monotonic
            # guardrail against that -- not a substitute for a proper levered-beta model.
            wacc = max(wacc, 0.045 + 0.06 * d_over_v)

            if net_debt is None:
                net_debt = 0.0
                notes.append("net-debt-missing, assumed 0")

            dcf_price = dcf_ebitda_build(revenue[0], ebitda_margin, capex_int, tax_rate, g1, wacc, net_debt, shares)
            if dcf_price is None or dcf_price <= 0:
                # EBITDA/capex build failed (thin or negative normalized margin, often
                # a one-off charge or genuinely capex-heavy name) -- fall back to the
                # net-income FCFE variant rather than dropping the name entirely.
                notes.append("ebitda-build-non-positive, fell back to FCFE/net-income variant")
                variant = "fcfe"

    if variant == "fcfe":
        ni = f.get("net_income")
        if not ni or ni[0] is None:
            pretax = f.get("pretax")
            if pretax and pretax[0] is not None:
                ni = [p * 0.79 for p in pretax]
                notes.append("net-income-estimated from pretax")
            else:
                return None  # truly no usable earnings data
        g1 = cagr(ni, cap=0.12)
        if g1 is None:
            g1 = TERM_G
        ke = max(RF + beta * ERP, 0.07)  # floor: low-beta names can still have volatile/cyclical earnings (e.g. P&C insurers) that CAPM beta alone doesn't price
        dcf_price = dcf_fcfe_build(ni[0], g1, ke, shares)

    if dcf_price is None or dcf_price <= 0:
        return None

    # ---- comps ----
    peers = get_peers(ticker, meta["sub_industry"], meta["sector"], by_sub, by_sector)
    peer_pes, peer_evs = [], []
    for p in peers:
        pf = fund.get(p)
        if not pf or pf.get("error"):
            continue
        if pf.get("forwardPE") and 0 < pf["forwardPE"] < 100:
            peer_pes.append(pf["forwardPE"])
        if pf.get("enterpriseToEbitda") and 0 < pf["enterpriseToEbitda"] < 60:
            peer_evs.append(pf["enterpriseToEbitda"])

    own_pe = f.get("forwardPE")
    own_ev = f.get("enterpriseToEbitda")
    pe_p = ev_p = comp_p = None
    # Clamp the peer/own multiple ratio: an own multiple that's extreme relative to
    # peers (near-zero from financial-engineering leverage, e.g. CHTR at 3x forward
    # P/E, or inflated from a near-zero-earnings base) otherwise blows the implied
    # price up or down by 5-10x on a single distorted input.
    if peer_pes and own_pe and own_pe > 0:
        peer_pe_avg = sum(peer_pes) / len(peer_pes)
        ratio = max(0.4, min(2.5, peer_pe_avg / own_pe))
        pe_p = price * ratio
    if peer_evs and own_ev and own_ev > 0 and f.get("ebitda") and f["ebitda"][0] and net_debt is not None:
        peer_ev_avg = sum(peer_evs) / len(peer_evs)
        ratio = max(0.4, min(2.5, peer_ev_avg / own_ev))
        ev_p = (own_ev * ratio * f["ebitda"][0] - net_debt) / shares

    prices = [x for x in (pe_p, ev_p) if x is not None and x > 0]
    comp_p = sum(prices) / len(prices) if prices else None

    if comp_p is not None:
        blended = 0.5 * dcf_price + 0.5 * comp_p
    else:
        blended = dcf_price
        notes.append("no-peer-comps-available, DCF-only PT")

    upside = (blended - price) / price * 100
    # Winsorize: at this scale (500 mechanically-screened names) a handful of extreme
    # capital-structure or cyclical-earnings-recovery cases (e.g. a heavily levered
    # equity stub, or a cyclical recovering off a near-zero base) still produce a
    # blow-up despite the guardrails above. Cap the displayed target rather than
    # publish a number that reads as broken; the underlying signal (strong buy/sell)
    # is preserved, just not at face-melting magnitude.
    if upside > 150:
        upside = 150.0
        blended = price * 2.5
        notes.append("upside capped at +150% (raw estimate was more extreme)")
    elif upside < -90:
        upside = -90.0
        blended = price * 0.10
        notes.append("downside capped at -90% (raw estimate was more extreme)")
    rating = "buy" if upside > 8 else ("sell" if upside < -8 else "hold")

    return dict(
        ticker=ticker, name=meta["name"], sector=sector, sub_industry=meta["sub_industry"],
        price=round(price, 2), dcf_price=round(dcf_price, 2),
        comp_p=round(comp_p, 2) if comp_p else None,
        pt=round(blended, 2), upside=round(upside, 1), rating=rating,
        variant=variant, peers=peers[:3], notes=notes,
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

def make_explainer(r, f):
    t, name, sector = r["ticker"], r["name"], r["sector"]
    price, pt, upside, rating = r["price"], r["pt"], r["upside"], r["rating"]
    verb = {"buy": "trades below", "sell": "trades above", "hold": "trades near"}[rating]
    dcf_vs_comp = ""
    if r["comp_p"] is not None:
        gap = abs(r["dcf_price"] - r["comp_p"]) / max(r["comp_p"], 1) * 100
        if gap > 40:
            dcf_vs_comp = (f" DCF (${r['dcf_price']:.0f}) and peer comps (${r['comp_p']:.0f}) diverge "
                           f"sharply here — read the two as bracketing genuine uncertainty about {name}'s "
                           f"forward growth, not a converging estimate.")
        else:
            dcf_vs_comp = f" DCF (${r['dcf_price']:.0f}) and peer comps (${r['comp_p']:.0f}) broadly agree."
    else:
        dcf_vs_comp = " No peer comps were available (thin sub-industry peer set); the target is DCF-only."
    flag = ""
    if "margin/revenue-divergence override: grew EBITDA directly, not revenue x flat margin" in r["notes"]:
        flag = " Revenue and EBITDA have moved in opposite directions historically, so growth is modeled off EBITDA directly rather than compounding revenue growth onto a flat margin."
    variant_note = ""
    if r["variant"] == "fcfe":
        variant_note = " As a financial/real-estate name, the DCF uses net income as an FCFE proxy discounted at cost of equity, per standard sector convention."
    return (f"{name} ({sector}) {verb} our blended 12-month target of ${pt:.0f} "
            f"({upside:+.1f}% {'upside' if upside >= 0 else 'downside'} from ${price:.2f}), "
            f"a 50/50 blend of a 10-year fade DCF (normalized capex, true debt-weighted WACC) "
            f"and peer-multiple comps within its sub-industry.{dcf_vs_comp}{flag}{variant_note} "
            f"Auto-generated from trailing yfinance financials — treat as a mechanical screen, not "
            f"analyst-reviewed research.")

def main():
    constituents = load(CONST_PATH)
    fund = load(FUND_PATH)
    meta_by_ticker = {c["ticker"]: c for c in constituents}
    by_sub, by_sector = build_peer_map(constituents, fund)

    args = sys.argv[1:]
    target_tickers = args if args else list(meta_by_ticker.keys())

    existing = load(OUT_PATH) if __import__("os").path.exists(OUT_PATH) else {}
    ok, skipped = 0, 0
    for t in target_tickers:
        meta = meta_by_ticker.get(t)
        if not meta:
            continue
        try:
            r = compute_one(t, meta, fund, by_sub, by_sector)
        except Exception as e:
            r = None
            print(f"{t}: ERROR {e}")
        if r is None:
            skipped += 1
            existing.pop(t, None)
            continue
        r["explainer"] = make_explainer(r, fund[t])
        existing[t] = r
        ok += 1
    save(OUT_PATH, existing)
    print(f"Computed {ok} valuations, skipped {skipped} (insufficient data). Total in store: {len(existing)}")

if __name__ == "__main__":
    main()
