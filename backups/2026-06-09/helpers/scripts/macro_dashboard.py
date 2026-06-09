#!/usr/bin/env python3
"""
Macro Dashboard Generator
=========================
Produces a standalone 13-tab Bloomberg-styled HTML report for any country.

Usage:
    python3 scripts/macro_dashboard.py
    python3 scripts/macro_dashboard.py --country "Mexico"
    python3 scripts/macro_dashboard.py --country "United States"
"""

import argparse
import datetime
import difflib
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import anthropic
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import requests
import wbgapi as wb
import yfinance as yf
from dotenv import load_dotenv
from plotly.subplots import make_subplots

# ── Path / env ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / "fred_client" / ".env")

try:
    from fred_client import FredClient
    _FRED = FredClient()
    _HAS_FRED = True
except Exception:
    _HAS_FRED = False

# ── Globals ───────────────────────────────────────────────────────────────────
TODAY      = datetime.date.today()
CURR_YEAR  = TODAY.year
_IMF_BASE  = "https://www.imf.org/external/datamapper/api/v1"
_AI_MODEL  = "claude-sonnet-4-6"

# ── Bloomberg palette ─────────────────────────────────────────────────────────
_BG   = "#0d1117"
_BG2  = "#161b22"
_ACC  = "#00d4aa"
_TEXT = "#e6edf3"
_MUTE = "#8b949e"
_BRD  = "#30363d"
_GR2  = "#21262d"
_RED  = "#ff6b6b"
_GOLD = "#ffd700"
_BLUE = "#58a6ff"

_BLAYOUT = dict(
    paper_bgcolor=_BG2, plot_bgcolor=_BG,
    font=dict(family="'Courier New', monospace", size=11, color=_TEXT),
    xaxis=dict(showgrid=True, gridcolor=_GR2, gridwidth=0.5,
               showline=False, zeroline=False, tickfont=dict(size=10, color=_MUTE)),
    yaxis=dict(showgrid=True, gridcolor=_GR2, gridwidth=0.5,
               showline=False, zeroline=True, zerolinecolor=_BRD, zerolinewidth=1,
               tickfont=dict(size=10, color=_MUTE)),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)",
                font=dict(size=10, color=_MUTE), orientation="h",
                yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(l=55, r=15, t=45, b=40),
    height=295,
    hovermode="x unified",
    hoverlabel=dict(bgcolor=_BG2, bordercolor=_BRD, font=dict(color=_TEXT, size=11)),
)

# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e6edf3; font-family: 'Courier New', Courier, monospace; font-size: 13px; line-height: 1.5; }
a { color: #58a6ff; }
.hdr { background: #161b22; border-bottom: 2px solid #00d4aa; padding: 14px 24px; display: flex; align-items: flex-start; justify-content: space-between; }
.hdr-brand { color: #00d4aa; font-size: 10px; letter-spacing: 3px; margin-bottom: 4px; }
.hdr-title { color: #e6edf3; font-size: 20px; font-weight: bold; letter-spacing: 1px; }
.hdr-meta { text-align: right; color: #8b949e; font-size: 11px; line-height: 1.8; }
.hdr-meta strong { color: #e6edf3; }
.tab-nav { background: #161b22; border-bottom: 1px solid #30363d; display: flex; flex-wrap: wrap; position: sticky; top: 0; z-index: 100; padding: 0 8px; box-shadow: 0 2px 8px rgba(0,0,0,.5); }
.tab-btn { background: none; border: none; border-bottom: 2px solid transparent; color: #8b949e; cursor: pointer; font-family: 'Courier New', monospace; font-size: 11px; letter-spacing: .5px; padding: 10px 12px; transition: all .15s; white-space: nowrap; }
.tab-btn:hover { color: #e6edf3; }
.tab-btn.active { color: #00d4aa; border-bottom-color: #00d4aa; }
.tab-panel { display: none; padding: 20px 24px 40px; }
.tab-panel.active { display: block; }
.sh { color: #00d4aa; font-size: 12px; font-weight: bold; letter-spacing: 1.5px; text-transform: uppercase; border-bottom: 1px solid #30363d; padding-bottom: 8px; margin: 22px 0 12px; }
.sh:first-child { margin-top: 0; }
.panel { background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 14px 16px; margin-bottom: 12px; }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
.g3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 10px; }
.g4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 10px; margin-bottom: 10px; }
.cb { background: #161b22; border: 1px solid #30363d; border-radius: 3px; overflow: hidden; }
.commentary { color: #c9d1d9; line-height: 1.8; max-width: 1100px; margin-bottom: 14px; }
.commentary p { margin-bottom: 11px; font-size: 13px; }
.commentary p:last-child { margin-bottom: 0; }
.tbl-wrap { overflow-x: auto; margin-bottom: 12px; }
table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
thead th { background: #0d1117; color: #00d4aa; font-weight: normal; padding: 6px 10px; text-align: right; border-bottom: 1px solid #30363d; white-space: nowrap; letter-spacing: .3px; }
thead th:first-child { text-align: left; min-width: 190px; }
tbody td { padding: 5px 10px; text-align: right; border-bottom: 1px solid #21262d; color: #e6edf3; white-space: nowrap; }
tbody td:first-child { text-align: left; color: #8b949e; }
tbody tr:hover td { background: #1c2128; }
tbody tr:last-child td { border-bottom: none; }
.snap-g { display: grid; grid-template-columns: repeat(3,1fr); gap: 10px; margin-bottom: 12px; }
.snap { background: #0d1117; border: 1px solid #30363d; border-radius: 3px; padding: 11px 13px; }
.snap-lbl { color: #8b949e; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; }
.snap-val { color: #00d4aa; font-size: 21px; font-weight: bold; margin: 5px 0 3px; }
.snap-sub { color: #8b949e; font-size: 11px; }
.resilience-wrap { text-align: center; padding: 20px; }
.r-score { display: inline-block; border: 2px solid #00d4aa; color: #00d4aa; font-size: 34px; font-weight: bold; padding: 14px 28px; border-radius: 3px; letter-spacing: 3px; }
.r-lbl { color: #8b949e; font-size: 12px; letter-spacing: 1px; margin-top: 8px; }
.pros-cons { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.pro-box { background: rgba(0,212,170,.05); border: 1px solid rgba(0,212,170,.25); border-radius: 3px; padding: 13px; }
.con-box { background: rgba(255,107,107,.05); border: 1px solid rgba(255,107,107,.25); border-radius: 3px; padding: 13px; }
.pro-box h3 { color: #00d4aa; font-size: 11px; letter-spacing: 1px; margin-bottom: 10px; }
.con-box h3 { color: #ff6b6b; font-size: 11px; letter-spacing: 1px; margin-bottom: 10px; }
.pc-item { display: flex; gap: 8px; padding: 6px 0; border-bottom: 1px solid #21262d; font-size: 12px; color: #c9d1d9; line-height: 1.5; }
.pc-item:last-child { border-bottom: none; }
.pu { color: #00d4aa; flex-shrink: 0; }
.pd { color: #ff6b6b; flex-shrink: 0; }
.cal-g { display: grid; grid-template-columns: repeat(auto-fill,minmax(280px,1fr)); gap: 9px; }
.cal-card { background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 10px 12px; display: flex; gap: 10px; align-items: flex-start; }
.cal-db { background: #0d1117; border: 1px solid #30363d; border-radius: 2px; text-align: center; min-width: 46px; padding: 5px; flex-shrink: 0; }
.cal-mo { color: #00d4aa; font-size: 9px; letter-spacing: 1px; text-transform: uppercase; }
.cal-dy { color: #e6edf3; font-size: 17px; font-weight: bold; line-height: 1; }
.cal-info { flex: 1; }
.cal-ttl { color: #e6edf3; font-size: 12px; font-weight: bold; margin-bottom: 3px; }
.cal-dsc { color: #8b949e; font-size: 11px; margin-bottom: 4px; }
.cal-tp { display: inline-block; padding: 2px 7px; border-radius: 2px; font-size: 10px; }
.t-cb { background: rgba(88,166,255,.15); color: #58a6ff; }
.t-dt { background: rgba(255,215,0,.15); color: #ffd700; }
.t-po { background: rgba(255,107,107,.15); color: #ff6b6b; }
.tl { list-style: none; border-left: 2px solid #30363d; padding-left: 20px; }
.tl-item { position: relative; padding: 7px 0; }
.tl-item::before { content: ''; position: absolute; left: -24px; top: 12px; width: 7px; height: 7px; border-radius: 50%; background: #00d4aa; }
.tl-dt { color: #00d4aa; font-size: 11px; font-weight: bold; margin-bottom: 3px; }
.tl-tx { color: #c9d1d9; font-size: 12px; line-height: 1.6; }
.src-g { display: grid; grid-template-columns: repeat(auto-fill,minmax(240px,1fr)); gap: 9px; }
.src-card { background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 11px; }
.src-sec { color: #00d4aa; font-size: 11px; font-weight: bold; margin-bottom: 6px; }
.src-list { list-style: none; }
.src-list li { color: #8b949e; font-size: 11px; padding: 3px 0; border-bottom: 1px solid #21262d; }
.src-list li:last-child { border-bottom: none; }
.dis-box { background: rgba(255,215,0,.04); border: 1px solid rgba(255,215,0,.2); border-radius: 3px; padding: 16px 20px; color: #8b949e; font-size: 12px; line-height: 1.8; max-width: 900px; }
.dis-box p { margin-bottom: 10px; }
.dis-box p:last-child { margin-bottom: 0; }
.na { color: #8b949e; font-style: italic; font-size: 11px; padding: 10px 0; }
.warn { color: #ffd700; font-size: 11px; }
"""

# ── Country metadata ──────────────────────────────────────────────────────────
COUNTRY_META = {
    "united states": dict(name="United States", wb="US",  iso3="USA", currency="USD", sym="$",
        cb="Federal Reserve (Fed)", equity="^GSPC",    use_fred=True,  oecd=True,  usd=True,  fx=None),
    "usa":           dict(name="United States", wb="US",  iso3="USA", currency="USD", sym="$",
        cb="Federal Reserve (Fed)", equity="^GSPC",    use_fred=True,  oecd=True,  usd=True,  fx=None),
    "canada":        dict(name="Canada",        wb="CA",  iso3="CAN", currency="CAD", sym="C$",
        cb="Bank of Canada (BoC)", equity="^GSPTSE",  use_fred=False, oecd=True,  usd=False, fx="CADUSD=X"),
    "mexico":        dict(name="Mexico",        wb="MX",  iso3="MEX", currency="MXN", sym="MXN",
        cb="Banco de México (Banxico)", equity="^MXX", use_fred=False, oecd=True,  usd=False, fx="MXNUSD=X"),
    "germany":       dict(name="Germany",       wb="DE",  iso3="DEU", currency="EUR", sym="€",
        cb="European Central Bank (ECB)", equity="^GDAXI", use_fred=False, oecd=True, usd=False, fx="EURUSD=X"),
    "france":        dict(name="France",        wb="FR",  iso3="FRA", currency="EUR", sym="€",
        cb="European Central Bank (ECB)", equity="^FCHI",  use_fred=False, oecd=True, usd=False, fx="EURUSD=X"),
    "united kingdom":dict(name="United Kingdom",wb="GB",  iso3="GBR", currency="GBP", sym="£",
        cb="Bank of England (BoE)", equity="^FTSE",   use_fred=False, oecd=True,  usd=False, fx="GBPUSD=X"),
    "uk":            dict(name="United Kingdom",wb="GB",  iso3="GBR", currency="GBP", sym="£",
        cb="Bank of England (BoE)", equity="^FTSE",   use_fred=False, oecd=True,  usd=False, fx="GBPUSD=X"),
    "italy":         dict(name="Italy",         wb="IT",  iso3="ITA", currency="EUR", sym="€",
        cb="European Central Bank (ECB)", equity="FTSEMIB.MI", use_fred=False, oecd=True, usd=False, fx="EURUSD=X"),
    "spain":         dict(name="Spain",         wb="ES",  iso3="ESP", currency="EUR", sym="€",
        cb="European Central Bank (ECB)", equity="^IBEX", use_fred=False, oecd=True, usd=False, fx="EURUSD=X"),
    "japan":         dict(name="Japan",         wb="JP",  iso3="JPN", currency="JPY", sym="¥",
        cb="Bank of Japan (BoJ)", equity="^N225",     use_fred=False, oecd=True,  usd=False, fx="JPYUSD=X"),
    "china":         dict(name="China",         wb="CN",  iso3="CHN", currency="CNY", sym="¥",
        cb="People's Bank of China (PBoC)", equity="000001.SS", use_fred=False, oecd=False, usd=False, fx="CNYUSD=X"),
    "south korea":   dict(name="South Korea",   wb="KR",  iso3="KOR", currency="KRW", sym="₩",
        cb="Bank of Korea (BoK)", equity="^KS11",     use_fred=False, oecd=True,  usd=False, fx="KRWUSD=X"),
    "korea":         dict(name="South Korea",   wb="KR",  iso3="KOR", currency="KRW", sym="₩",
        cb="Bank of Korea (BoK)", equity="^KS11",     use_fred=False, oecd=True,  usd=False, fx="KRWUSD=X"),
    "australia":     dict(name="Australia",     wb="AU",  iso3="AUS", currency="AUD", sym="A$",
        cb="Reserve Bank of Australia (RBA)", equity="^AXJO", use_fred=False, oecd=True, usd=False, fx="AUDUSD=X"),
    "india":         dict(name="India",         wb="IN",  iso3="IND", currency="INR", sym="₹",
        cb="Reserve Bank of India (RBI)", equity="^BSESN", use_fred=False, oecd=False, usd=False, fx="INRUSD=X"),
    "indonesia":     dict(name="Indonesia",     wb="ID",  iso3="IDN", currency="IDR", sym="IDR",
        cb="Bank Indonesia", equity="^JKSE",          use_fred=False, oecd=False, usd=False, fx="IDRUSD=X"),
    "brazil":        dict(name="Brazil",        wb="BR",  iso3="BRA", currency="BRL", sym="R$",
        cb="Banco Central do Brasil (BCB)", equity="^BVSP", use_fred=False, oecd=False, usd=False, fx="BRLUSD=X"),
    "argentina":     dict(name="Argentina",     wb="AR",  iso3="ARG", currency="ARS", sym="ARS",
        cb="Banco Central de la República Argentina (BCRA)", equity="^MERV", use_fred=False, oecd=False, usd=False, fx="ARSUSD=X"),
    "colombia":      dict(name="Colombia",      wb="CO",  iso3="COL", currency="COP", sym="COP",
        cb="Banco de la República", equity="^COLCAP", use_fred=False, oecd=True,  usd=False, fx="COPUSD=X"),
    "chile":         dict(name="Chile",         wb="CL",  iso3="CHL", currency="CLP", sym="CLP",
        cb="Banco Central de Chile", equity="^IPSA",  use_fred=False, oecd=True,  usd=False, fx="CLPUSD=X"),
    "peru":          dict(name="Peru",          wb="PE",  iso3="PER", currency="PEN", sym="PEN",
        cb="Banco Central de Reserva del Perú (BCRP)", equity="^SPBLPGPT", use_fred=False, oecd=False, usd=False, fx="PENUSD=X"),
    "south africa":  dict(name="South Africa",  wb="ZA",  iso3="ZAF", currency="ZAR", sym="R",
        cb="South African Reserve Bank (SARB)", equity="^J203.JO", use_fred=False, oecd=False, usd=False, fx="ZARUSD=X"),
    "nigeria":       dict(name="Nigeria",       wb="NG",  iso3="NGA", currency="NGN", sym="₦",
        cb="Central Bank of Nigeria (CBN)", equity="^NGSEINDX", use_fred=False, oecd=False, usd=False, fx="NGNUSD=X"),
    "turkey":        dict(name="Turkey",        wb="TR",  iso3="TUR", currency="TRY", sym="₺",
        cb="Central Bank of the Republic of Türkiye (TCMB)", equity="XU100.IS", use_fred=False, oecd=True, usd=False, fx="TRYUSD=X"),
    "poland":        dict(name="Poland",        wb="PL",  iso3="POL", currency="PLN", sym="PLN",
        cb="Narodowy Bank Polski (NBP)", equity="^WIG20", use_fred=False, oecd=True, usd=False, fx="PLNUSD=X"),
    "switzerland":   dict(name="Switzerland",   wb="CH",  iso3="CHE", currency="CHF", sym="CHF",
        cb="Swiss National Bank (SNB)", equity="^SSMI", use_fred=False, oecd=True, usd=False, fx="CHFUSD=X"),
    "new zealand":   dict(name="New Zealand",   wb="NZ",  iso3="NZL", currency="NZD", sym="NZ$",
        cb="Reserve Bank of New Zealand (RBNZ)", equity="^NZ50", use_fred=False, oecd=True, usd=False, fx="NZDUSD=X"),
    "saudi arabia":  dict(name="Saudi Arabia",  wb="SA",  iso3="SAU", currency="SAR", sym="SAR",
        cb="Saudi Central Bank (SAMA)", equity="^TASI.SR", use_fred=False, oecd=False, usd=False, fx="SARUSD=X"),
    "thailand":      dict(name="Thailand",      wb="TH",  iso3="THA", currency="THB", sym="฿",
        cb="Bank of Thailand (BoT)", equity="^SET.BK",use_fred=False, oecd=False, usd=False, fx="THBUSD=X"),
    "netherlands":   dict(name="Netherlands",   wb="NL",  iso3="NLD", currency="EUR", sym="€",
        cb="European Central Bank (ECB)", equity="^AEX", use_fred=False, oecd=True, usd=False, fx="EURUSD=X"),
    "sweden":        dict(name="Sweden",        wb="SE",  iso3="SWE", currency="SEK", sym="SEK",
        cb="Riksbank", equity="^OMX",             use_fred=False, oecd=True,  usd=False, fx="SEKUSD=X"),
    "norway":        dict(name="Norway",        wb="NO",  iso3="NOR", currency="NOK", sym="NOK",
        cb="Norges Bank", equity="OBX.OL",         use_fred=False, oecd=True,  usd=False, fx="NOKUSD=X"),
    "eurozone":      dict(name="Eurozone",      wb="XC",  iso3="EMU", currency="EUR", sym="€",
        cb="European Central Bank (ECB)", equity="^STOXX50E", use_fred=False, oecd=True, usd=False, fx="EURUSD=X"),
    "euro area":     dict(name="Eurozone",      wb="XC",  iso3="EMU", currency="EUR", sym="€",
        cb="European Central Bank (ECB)", equity="^STOXX50E", use_fred=False, oecd=True, usd=False, fx="EURUSD=X"),
}

# ── Events database (upcoming events from TODAY) ──────────────────────────────
_EVENTS = {
    "_global": [
        # FOMC 2026
        {"date": "2026-05-06", "title": "FOMC Meeting Day 1",      "desc": "Federal Open Market Committee convenes", "type": "cb"},
        {"date": "2026-05-07", "title": "FOMC Rate Decision",      "desc": "Fed policy rate & press conference",      "type": "cb"},
        {"date": "2026-06-17", "title": "FOMC Meeting Day 1",      "desc": "Federal Open Market Committee convenes", "type": "cb"},
        {"date": "2026-06-18", "title": "FOMC Rate Decision + SEP","desc": "Fed rate decision & dot-plot projections","type": "cb"},
        {"date": "2026-07-29", "title": "FOMC Meeting Day 1",      "desc": "Federal Open Market Committee convenes", "type": "cb"},
        {"date": "2026-07-30", "title": "FOMC Rate Decision",      "desc": "Fed policy rate & press conference",      "type": "cb"},
        {"date": "2026-09-16", "title": "FOMC Meeting Day 1",      "desc": "Federal Open Market Committee convenes", "type": "cb"},
        {"date": "2026-09-17", "title": "FOMC Rate Decision + SEP","desc": "Fed rate decision & updated projections", "type": "cb"},
        {"date": "2026-10-28", "title": "FOMC Meeting Day 1",      "desc": "Federal Open Market Committee convenes", "type": "cb"},
        {"date": "2026-10-29", "title": "FOMC Rate Decision",      "desc": "Fed policy rate & press conference",      "type": "cb"},
        # ECB 2026
        {"date": "2026-06-05", "title": "ECB Governing Council",   "desc": "ECB rate decision (Frankfurt)",           "type": "cb"},
        {"date": "2026-07-24", "title": "ECB Governing Council",   "desc": "ECB rate decision",                       "type": "cb"},
        {"date": "2026-09-11", "title": "ECB Governing Council",   "desc": "ECB rate decision + staff projections",   "type": "cb"},
        {"date": "2026-10-30", "title": "ECB Governing Council",   "desc": "ECB rate decision",                       "type": "cb"},
    ],
    "united states": [
        {"date": "2026-05-08", "title": "U.S. Jobs Report (Apr)",  "desc": "Non-Farm Payrolls & unemployment (BLS)", "type": "dt"},
        {"date": "2026-05-13", "title": "U.S. CPI (April)",        "desc": "Consumer Price Index YoY & MoM (BLS)",   "type": "dt"},
        {"date": "2026-05-15", "title": "U.S. Retail Sales (Apr)", "desc": "Monthly retail & food services report",  "type": "dt"},
        {"date": "2026-05-29", "title": "U.S. GDP Q1 2026 (2nd)",  "desc": "BEA second estimate of Q1 real GDP",     "type": "dt"},
        {"date": "2026-06-05", "title": "U.S. Jobs Report (May)",  "desc": "Non-Farm Payrolls & unemployment (BLS)", "type": "dt"},
        {"date": "2026-06-12", "title": "U.S. CPI (May)",          "desc": "Consumer Price Index YoY & MoM",         "type": "dt"},
        {"date": "2026-07-03", "title": "U.S. Jobs Report (Jun)",  "desc": "Non-Farm Payrolls & unemployment",       "type": "dt"},
        {"date": "2026-07-10", "title": "U.S. CPI (June)",         "desc": "Consumer Price Index YoY & MoM",         "type": "dt"},
        {"date": "2026-07-30", "title": "U.S. GDP Q2 2026 (Adv)", "desc": "BEA advance estimate of Q2 real GDP",    "type": "dt"},
        {"date": "2026-08-07", "title": "U.S. Jobs Report (Jul)",  "desc": "Non-Farm Payrolls & unemployment",       "type": "dt"},
        {"date": "2026-09-11", "title": "U.S. CPI (August)",       "desc": "Consumer Price Index YoY & MoM",         "type": "dt"},
        {"date": "2026-11-03", "title": "U.S. Midterm Elections",  "desc": "U.S. House & Senate midterm elections",  "type": "po"},
    ],
    "eurozone": [
        {"date": "2026-05-15", "title": "Eurozone GDP Q1 2026",    "desc": "Flash estimate Eurozone GDP (Eurostat)", "type": "dt"},
        {"date": "2026-05-19", "title": "Eurozone CPI (April)",    "desc": "Flash CPI estimate (Eurostat)",          "type": "dt"},
        {"date": "2026-06-17", "title": "Eurozone CPI (May)",      "desc": "Final CPI release (Eurostat)",           "type": "dt"},
        {"date": "2026-07-15", "title": "Eurozone CPI (June)",     "desc": "Flash CPI estimate (Eurostat)",          "type": "dt"},
        {"date": "2026-07-31", "title": "Eurozone GDP Q2 2026",    "desc": "Flash estimate Eurozone GDP",            "type": "dt"},
    ],
    "germany": [
        {"date": "2026-05-14", "title": "Germany GDP Q1 2026",     "desc": "Federal Statistical Office (Destatis)", "type": "dt"},
        {"date": "2026-05-22", "title": "Germany Ifo Business",    "desc": "Ifo Business Climate Index (May)",       "type": "dt"},
        {"date": "2026-06-24", "title": "Germany Ifo Business",    "desc": "Ifo Business Climate Index (June)",      "type": "dt"},
        {"date": "2026-09-27", "title": "Germany Federal Election","desc": "Federal parliamentary elections",         "type": "po"},
    ],
    "united kingdom": [
        {"date": "2026-05-08", "title": "BoE MPC Decision",        "desc": "Bank of England rate decision",          "type": "cb"},
        {"date": "2026-06-19", "title": "BoE MPC Decision",        "desc": "Bank of England rate decision + MPR",    "type": "cb"},
        {"date": "2026-08-07", "title": "BoE MPC Decision",        "desc": "Bank of England rate decision",          "type": "cb"},
        {"date": "2026-09-18", "title": "BoE MPC Decision",        "desc": "Bank of England rate decision",          "type": "cb"},
        {"date": "2026-10-16", "title": "UK CPI (September)",      "desc": "ONS Consumer Price Index",               "type": "dt"},
        {"date": "2026-10-23", "title": "UK Retail Sales (Sep)",   "desc": "ONS monthly retail sales",               "type": "dt"},
    ],
    "japan": [
        {"date": "2026-05-01", "title": "BoJ Policy Decision",     "desc": "Bank of Japan rate decision + Outlook", "type": "cb"},
        {"date": "2026-06-17", "title": "BoJ Policy Decision",     "desc": "Bank of Japan rate decision",            "type": "cb"},
        {"date": "2026-07-31", "title": "BoJ Policy Decision",     "desc": "Bank of Japan rate decision + Outlook", "type": "cb"},
        {"date": "2026-09-19", "title": "BoJ Policy Decision",     "desc": "Bank of Japan rate decision",            "type": "cb"},
        {"date": "2026-10-30", "title": "BoJ Policy Decision",     "desc": "Bank of Japan rate decision + Outlook", "type": "cb"},
        {"date": "2026-05-20", "title": "Japan CPI (April)",       "desc": "Statistics Bureau CPI release",          "type": "dt"},
    ],
    "mexico": [
        {"date": "2026-05-15", "title": "Banxico Rate Decision",   "desc": "Banco de México policy rate",            "type": "cb"},
        {"date": "2026-06-26", "title": "Banxico Rate Decision",   "desc": "Banco de México policy rate",            "type": "cb"},
        {"date": "2026-08-07", "title": "Banxico Rate Decision",   "desc": "Banco de México policy rate",            "type": "cb"},
        {"date": "2026-09-25", "title": "Banxico Rate Decision",   "desc": "Banco de México policy rate",            "type": "cb"},
        {"date": "2026-05-22", "title": "Mexico CPI (Quincenal)", "desc": "INEGI bi-weekly CPI release",            "type": "dt"},
        {"date": "2026-05-29", "title": "Mexico GDP Q1 2026",      "desc": "INEGI advance GDP estimate",             "type": "dt"},
    ],
    "brazil": [
        {"date": "2026-05-07", "title": "Copom Rate Decision",     "desc": "BCB Selic rate decision",               "type": "cb"},
        {"date": "2026-06-18", "title": "Copom Rate Decision",     "desc": "BCB Selic rate decision",               "type": "cb"},
        {"date": "2026-08-06", "title": "Copom Rate Decision",     "desc": "BCB Selic rate decision",               "type": "cb"},
        {"date": "2026-09-17", "title": "Copom Rate Decision",     "desc": "BCB Selic rate decision",               "type": "cb"},
        {"date": "2026-10-04", "title": "Brazil General Election", "desc": "Presidential & congressional elections", "type": "po"},
    ],
    "china": [
        {"date": "2026-05-15", "title": "China GDP Q1 Release",    "desc": "National Bureau of Statistics",          "type": "dt"},
        {"date": "2026-05-15", "title": "China CPI & PPI (Apr)",   "desc": "NBS Consumer & Producer Price data",     "type": "dt"},
        {"date": "2026-06-15", "title": "China Retail Sales",      "desc": "NBS May retail sales & industrial output","type": "dt"},
        {"date": "2026-07-15", "title": "China GDP Q2 2026",       "desc": "National Bureau of Statistics",          "type": "dt"},
    ],
    "india": [
        {"date": "2026-06-06", "title": "RBI MPC Decision",        "desc": "Reserve Bank of India rate decision",   "type": "cb"},
        {"date": "2026-08-08", "title": "RBI MPC Decision",        "desc": "Reserve Bank of India rate decision",   "type": "cb"},
        {"date": "2026-10-09", "title": "RBI MPC Decision",        "desc": "Reserve Bank of India rate decision",   "type": "cb"},
        {"date": "2026-05-31", "title": "India GDP Q4 FY2026",     "desc": "Ministry of Statistics (MoSPI)",         "type": "dt"},
    ],
}

# ── Country resolver ──────────────────────────────────────────────────────────
def resolve_country(query: str):
    q = query.lower().strip()
    if q in COUNTRY_META:
        return COUNTRY_META[q].copy()
    matches = difflib.get_close_matches(q, COUNTRY_META.keys(), n=1, cutoff=0.55)
    if matches:
        return COUNTRY_META[matches[0]].copy()
    try:
        results = list(wb.economy.get(q=query))
        if results:
            e = results[0]
            return dict(name=e.name, wb=e.id, iso3=e.id, currency="LCU", sym="",
                        cb=f"Central Bank of {e.name}", equity=None, use_fred=False,
                        oecd=False, usd=False, fx=f"{e.id}USD=X")
    except Exception:
        pass
    return None

# ── Data helpers ──────────────────────────────────────────────────────────────
def wb_fetch(indicators: list, wb_code: str, years: int = 12) -> pd.DataFrame:
    """World Bank DataFrame: index=indicators, cols=int years."""
    try:
        df = wb.data.DataFrame(indicators, wb_code, mrv=years)
        if df is None or (hasattr(df, 'empty') and df.empty):
            return pd.DataFrame(index=indicators)
        df.columns = [int(str(c)[2:]) if str(c).startswith('YR') else c for c in df.columns]
        int_cols = sorted([c for c in df.columns if isinstance(c, int)])
        return df[int_cols] if int_cols else df
    except Exception:
        return pd.DataFrame(index=indicators)


def imf_fetch(indicators: list, iso3: str, years: int = 14) -> pd.DataFrame:
    """IMF DataMapper: index=indicators, cols=int years."""
    rows = {}
    for ind in indicators:
        try:
            r = requests.get(f"{_IMF_BASE}/{ind}/{iso3}", timeout=12)
            if r.status_code == 200:
                vals = r.json().get("values", {}).get(ind, {}).get(iso3, {})
                if vals:
                    rows[ind] = {int(k): float(v) for k, v in vals.items()
                                 if v is not None and not (isinstance(v, float) and str(v) == 'nan')}
        except Exception:
            pass
    if not rows:
        return pd.DataFrame(index=indicators)
    df = pd.DataFrame(rows).T
    cutoff = CURR_YEAR - years
    int_cols = sorted([c for c in df.columns if isinstance(c, int) and c >= cutoff])
    return df[int_cols] if int_cols else df


def fred_series(series_id: str, freq: str = "A", start_year: int = None) -> pd.Series:
    if not _HAS_FRED:
        return pd.Series(dtype=float)
    try:
        start = f"{start_year or CURR_YEAR - 14}-01-01"
        df = _FRED.get_series(series_id, freq=freq, observation_start=start)
        if df.empty:
            return pd.Series(dtype=float)
        s = df.iloc[:, 0]
        if freq == "A":
            s.index = s.index.year
        elif freq in ("Q", "QS"):
            s.index = s.index.to_period("Q").astype(str)
        return s.dropna()
    except Exception:
        return pd.Series(dtype=float)


def fig_html(fig: go.Figure, ht: int = 295) -> str:
    lay = {**_BLAYOUT, "height": ht}
    fig.update_layout(**lay)
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       config={"displayModeBar": False, "responsive": True})


def _safe(v, fmt=".1f"):
    if v is None or (isinstance(v, float) and (str(v) in ('nan', 'inf', '-inf'))):
        return "—"
    try:
        return f"{v:{fmt}}"
    except Exception:
        return "—"


def df_to_html(df: pd.DataFrame, pct_rows: list = None, usd_rows: list = None,
               bn_rows: list = None, highlight_last: bool = True) -> str:
    if df is None or df.empty:
        return '<p class="na">Data not available — World Bank / IMF</p>'
    pct_rows  = pct_rows  or []
    usd_rows  = usd_rows  or []
    bn_rows   = bn_rows   or []
    cols = list(df.columns)
    html = '<div class="tbl-wrap"><table><thead><tr><th>Metric</th>'
    for c in cols:
        html += f"<th>{c}</th>"
    html += "</tr></thead><tbody>"
    for metric, row in df.iterrows():
        html += f"<tr><td>{metric}</td>"
        for i, (c, val) in enumerate(row.items()):
            if pd.isna(val):
                cell = "—"
            elif metric in bn_rows:
                cell = f"{val:,.2f}B"
            elif metric in pct_rows:
                cell = f"{val:.1f}%"
            elif metric in usd_rows:
                cell = f"${val:,.0f}"
            else:
                cell = f"{val:,.1f}"
            style = ' style="color:#00d4aa"' if highlight_last and i == len(cols) - 1 else ""
            html += f"<td{style}>{cell}</td>"
        html += "</tr>"
    html += "</tbody></table></div>"
    return html


def ai_comment(section: str, data_str: str, country: str, instructions: str) -> str:
    """Generate commentary from Claude API given section data."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    try:
        resp = client.messages.create(
            model=_AI_MODEL,
            max_tokens=1600,
            system=(
                "You are a hard-nosed macroeconomic analyst writing for institutional investors "
                "and professional economists. Rules: strictly data-driven — cite specific numbers "
                "from the data provided; no marketing language; no speculation beyond observed "
                "trends and official policy signals; complete sentences with substantive economic "
                "context; Bloomberg terminal editorial voice. No bullet points in paragraph sections."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Country: {country}\nSection: {section}\n\n"
                    f"Data:\n{data_str}\n\n"
                    f"{instructions}"
                )
            }]
        )
        return resp.content[0].text.strip()
    except Exception as e:
        return f"<em>Commentary unavailable: {e}</em>"


# ── Data fetchers ─────────────────────────────────────────────────────────────
def fetch_gdp(meta: dict) -> dict:
    print("    World Bank GDP indicators...")
    wb_inds = ["NY.GDP.MKTP.CD", "NY.GDP.MKTP.KD.ZG", "NY.GDP.PCAP.CD",
               "NE.CON.PRVT.ZS", "NE.GDI.TOTL.ZS", "NE.CON.GOVT.ZS",
               "NE.EXP.GNFS.ZS", "NE.IMP.GNFS.ZS"]
    wdf = wb_fetch(wb_inds, meta["wb"], years=12)

    print("    IMF GDP indicators...")
    idf = imf_fetch(["NGDPD", "NGDP_RPCH", "NGDPDPC"], meta["iso3"], years=12)

    # Nominal GDP series (USD billions)
    if "NGDPD" in idf.index and not idf.loc["NGDPD"].dropna().empty:
        nom = idf.loc["NGDPD"].dropna()
    elif "NY.GDP.MKTP.CD" in wdf.index:
        nom = (wdf.loc["NY.GDP.MKTP.CD"].dropna() / 1e9)
    else:
        nom = pd.Series(dtype=float)

    # Real growth
    if "NY.GDP.MKTP.KD.ZG" in wdf.index:
        rgdp = wdf.loc["NY.GDP.MKTP.KD.ZG"].dropna()
    elif "NGDP_RPCH" in idf.index:
        rgdp = idf.loc["NGDP_RPCH"].dropna()
    else:
        rgdp = pd.Series(dtype=float)

    # Per capita
    if "NGDPDPC" in idf.index and not idf.loc["NGDPDPC"].dropna().empty:
        pcap = idf.loc["NGDPDPC"].dropna() * 1000
    elif "NY.GDP.PCAP.CD" in wdf.index:
        pcap = wdf.loc["NY.GDP.PCAP.CD"].dropna()
    else:
        pcap = pd.Series(dtype=float)

    # Annual table (years as cols)
    years_10 = sorted(set(
        list(nom.index[-10:] if len(nom) > 10 else nom.index) +
        list(rgdp.index[-10:] if len(rgdp) > 10 else rgdp.index)
    ))
    years_10 = [y for y in years_10 if isinstance(y, int) and y >= CURR_YEAR - 10]

    rows = {}
    rows["Nominal GDP (USD B)"]    = {y: nom.get(y, float("nan")) for y in years_10}
    rows["Nominal GDP YoY (%)"]    = {y: (nom.pct_change() * 100).get(y, float("nan")) for y in years_10}
    rows["Real GDP YoY (%)"]       = {y: rgdp.get(y, float("nan")) for y in years_10}
    for lbl, ind in [("Consumption (% GDP)", "NE.CON.PRVT.ZS"),
                     ("Investment (% GDP)",   "NE.GDI.TOTL.ZS"),
                     ("Govt Spending (% GDP)","NE.CON.GOVT.ZS")]:
        if ind in wdf.index:
            rows[lbl] = {y: wdf.loc[ind].get(y, float("nan")) for y in years_10}
    if "NE.EXP.GNFS.ZS" in wdf.index and "NE.IMP.GNFS.ZS" in wdf.index:
        rows["Net Exports (% GDP)"] = {
            y: wdf.loc["NE.EXP.GNFS.ZS"].get(y, float("nan")) - wdf.loc["NE.IMP.GNFS.ZS"].get(y, float("nan"))
            for y in years_10}
    rows["Per Capita GDP (USD)"]   = {y: pcap.get(y, float("nan")) for y in years_10}
    pcap_yoy = pcap.pct_change() * 100
    rows["Per Capita YoY (%)"]     = {y: pcap_yoy.get(y, float("nan")) for y in years_10}
    annual_tbl = pd.DataFrame(rows).T[years_10] if years_10 else pd.DataFrame()

    # Figures
    figs = {}
    if not nom.empty:
        f = go.Figure(go.Bar(x=list(nom.index), y=list(nom.values),
                             marker_color=_ACC, name="Nominal GDP"))
        f.update_layout(title_text="Nominal GDP (USD Billions)", title_font_color=_ACC)
        figs["nom"] = f

    if not rgdp.empty:
        colors = [_ACC if v >= 0 else _RED for v in rgdp.values]
        f = go.Figure(go.Bar(x=list(rgdp.index), y=list(rgdp.values),
                             marker_color=colors, name="Real GDP Growth"))
        f.update_layout(title_text="Real GDP Growth YoY (%)", title_font_color=_ACC)
        figs["rgdp"] = f

    comp_keys = ["NE.CON.PRVT.ZS", "NE.GDI.TOTL.ZS", "NE.CON.GOVT.ZS"]
    if not wdf.empty and any(k in wdf.index for k in comp_keys):
        yr_avail = [c for c in wdf.columns if isinstance(c, int)]
        f = go.Figure()
        for ind, lbl, col in [("NE.CON.PRVT.ZS", "Consumption", _ACC),
                               ("NE.GDI.TOTL.ZS", "Investment",  _BLUE),
                               ("NE.CON.GOVT.ZS", "Govt Spend",  _GOLD)]:
            if ind in wdf.index:
                f.add_trace(go.Bar(x=yr_avail, y=list(wdf.loc[ind]),
                                   name=lbl, marker_color=col))
        if "NE.EXP.GNFS.ZS" in wdf.index and "NE.IMP.GNFS.ZS" in wdf.index:
            net = wdf.loc["NE.EXP.GNFS.ZS"] - wdf.loc["NE.IMP.GNFS.ZS"]
            f.add_trace(go.Bar(x=yr_avail, y=list(net), name="Net Exports", marker_color=_RED))
        f.update_layout(barmode="relative", title_text="GDP Composition (% of GDP)",
                        title_font_color=_ACC)
        figs["comp"] = f

    return dict(wdf=wdf, idf=idf, nom=nom, rgdp=rgdp, pcap=pcap,
                annual_tbl=annual_tbl, figs=figs)


def fetch_inflation(meta: dict) -> dict:
    print("    World Bank CPI indicators...")
    wdf = wb_fetch(["FP.CPI.TOTL.ZG", "SL.UEM.TOTL.ZS"], meta["wb"], years=12)
    idf = imf_fetch(["PCPIPCH", "PCPIEPCH"], meta["iso3"], years=12)

    if "FP.CPI.TOTL.ZG" in wdf.index and not wdf.loc["FP.CPI.TOTL.ZG"].dropna().empty:
        cpi = wdf.loc["FP.CPI.TOTL.ZG"].dropna()
    elif "PCPIPCH" in idf.index:
        cpi = idf.loc["PCPIPCH"].dropna()
    else:
        cpi = pd.Series(dtype=float)

    years_10 = sorted([y for y in cpi.index if isinstance(y, int) and y >= CURR_YEAR - 10])
    rows = {}
    rows["Headline CPI YoY (%)"] = {y: cpi.get(y, float("nan")) for y in years_10}

    annual_tbl = pd.DataFrame(rows).T[years_10] if years_10 else pd.DataFrame()

    figs = {}
    if not cpi.empty:
        recent = cpi[cpi.index >= CURR_YEAR - 10] if len(cpi) > 10 else cpi
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(recent.index), y=list(recent.values),
                               mode="lines+markers", name="Headline CPI",
                               line=dict(color=_RED, width=2)))
        # Typical 2% target line
        f.add_hline(y=2, line_dash="dash", line_color=_MUTE,
                    annotation_text="2% Target", annotation_font_color=_MUTE)
        f.update_layout(title_text="Headline CPI YoY (%)", title_font_color=_ACC)
        figs["cpi"] = f

    return dict(wdf=wdf, idf=idf, cpi=cpi, annual_tbl=annual_tbl, figs=figs)


def fetch_monetary(meta: dict) -> dict:
    print("    Fetching monetary / rates data...")
    idf = imf_fetch(["FPOLM", "PCPIEPCH"], meta["iso3"], years=12)

    # Policy rate: try FRED for US
    if meta["use_fred"]:
        pr = fred_series("FEDFUNDS", freq="A")
        y2 = fred_series("GS2", freq="A")
        y10 = fred_series("GS10", freq="A")
        y30 = fred_series("GS30", freq="A")
        # Monthly payrolls for labor tab (stored here for reuse)
        payrolls = fred_series("PAYEMS", freq="MS", start_year=CURR_YEAR - 3)
    else:
        pr = pd.Series(dtype=float)
        y2 = pd.Series(dtype=float)
        y10 = pd.Series(dtype=float)
        y30 = pd.Series(dtype=float)
        payrolls = pd.Series(dtype=float)

    # Fallback: IMF policy rate indicator
    if pr.empty and "FPOLM" in idf.index:
        pr = idf.loc["FPOLM"].dropna()

    latest_rate = float(pr.iloc[-1]) if not pr.empty else float("nan")
    latest_y10  = float(y10.iloc[-1]) if not y10.empty else float("nan")

    figs = {}
    years = sorted(set(list(pr.index) + list(y10.index) + list(y2.index)))
    years = [y for y in years if isinstance(y, (int, str))]

    if not pr.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(pr.index), y=list(pr.values),
                               mode="lines", name="Policy Rate", line=dict(color=_ACC, width=2)))
        if not y2.empty:
            f.add_trace(go.Scatter(x=list(y2.index), y=list(y2.values),
                                   mode="lines", name="2Y Yield", line=dict(color=_BLUE, width=1.5)))
        if not y10.empty:
            f.add_trace(go.Scatter(x=list(y10.index), y=list(y10.values),
                                   mode="lines", name="10Y Yield", line=dict(color=_GOLD, width=1.5)))
        f.update_layout(title_text="Interest Rates (%)", title_font_color=_ACC)
        figs["rates"] = f

    # Yield curve snapshot (US FRED)
    yc_maturities = []
    if meta["use_fred"] and _HAS_FRED:
        ycm = {
            "1M": "GS1M", "3M": "GS3M", "6M": "GS6M", "1Y": "GS1",
            "2Y": "GS2",  "5Y": "GS5",  "7Y": "GS7",  "10Y": "GS10",
            "20Y": "GS20","30Y": "GS30"
        }
        yc_vals = {}
        for mat, sid in ycm.items():
            s = fred_series(sid, freq="MS", start_year=CURR_YEAR - 1)
            if not s.empty:
                yc_vals[mat] = float(s.iloc[-1])
        if yc_vals:
            f = go.Figure(go.Scatter(
                x=list(yc_vals.keys()), y=list(yc_vals.values()),
                mode="lines+markers", line=dict(color=_ACC, width=2),
                marker=dict(color=_ACC, size=6)
            ))
            f.update_layout(title_text=f"Yield Curve (Current)", title_font_color=_ACC)
            figs["yc"] = f
            yc_maturities = yc_vals

    # Annual table
    years_10 = sorted([y for y in set(list(pr.index) + list(y10.index)) if isinstance(y, int) and y >= CURR_YEAR - 10])
    rows = {}
    rows["Policy Rate (%)"] = {y: pr.get(y, float("nan")) for y in years_10}
    rows["2Y Bond Yield (%)"] = {y: y2.get(y, float("nan")) for y in years_10}
    rows["10Y Bond Yield (%)"] = {y: y10.get(y, float("nan")) for y in years_10}
    annual_tbl = pd.DataFrame(rows).T[years_10] if years_10 else pd.DataFrame()

    return dict(pr=pr, y2=y2, y10=y10, y30=y30, payrolls=payrolls,
                yc_maturities=yc_maturities, latest_rate=latest_rate,
                latest_y10=latest_y10, annual_tbl=annual_tbl, figs=figs)


def fetch_labor(meta: dict) -> dict:
    print("    World Bank labor indicators...")
    wdf = wb_fetch(["SL.UEM.TOTL.ZS", "SL.TLF.CACT.ZS", "SL.EMP.TOTL.SP.ZS"],
                   meta["wb"], years=12)

    unemp = wdf.loc["SL.UEM.TOTL.ZS"].dropna() if "SL.UEM.TOTL.ZS" in wdf.index else pd.Series(dtype=float)
    lfpr  = wdf.loc["SL.TLF.CACT.ZS"].dropna() if "SL.TLF.CACT.ZS" in wdf.index else pd.Series(dtype=float)
    emp   = wdf.loc["SL.EMP.TOTL.SP.ZS"].dropna() if "SL.EMP.TOTL.SP.ZS" in wdf.index else pd.Series(dtype=float)

    years_10 = sorted([y for y in set(list(unemp.index) + list(lfpr.index)) if isinstance(y, int) and y >= CURR_YEAR - 10])
    rows = {}
    rows["Unemployment Rate (%)"]         = {y: unemp.get(y, float("nan")) for y in years_10}
    rows["Labor Force Participation (%)"] = {y: lfpr.get(y, float("nan")) for y in years_10}
    rows["Employment-to-Pop Ratio (%)"]   = {y: emp.get(y, float("nan")) for y in years_10}
    annual_tbl = pd.DataFrame(rows).T[years_10] if years_10 else pd.DataFrame()

    figs = {}
    if not unemp.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(unemp.index), y=list(unemp.values),
                               mode="lines+markers", name="Unemployment Rate",
                               line=dict(color=_RED, width=2)))
        f.update_layout(title_text="Unemployment Rate (%)", title_font_color=_ACC)
        figs["unemp"] = f

    if not lfpr.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(lfpr.index), y=list(lfpr.values),
                               mode="lines+markers", name="LFPR",
                               line=dict(color=_BLUE, width=2)))
        f.update_layout(title_text="Labor Force Participation Rate (%)", title_font_color=_ACC)
        figs["lfpr"] = f

    if not emp.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(emp.index), y=list(emp.values),
                               mode="lines+markers", name="Emp/Pop",
                               line=dict(color=_GOLD, width=2)))
        f.update_layout(title_text="Employment-to-Population Ratio (%)", title_font_color=_ACC)
        figs["emp"] = f

    return dict(wdf=wdf, unemp=unemp, lfpr=lfpr, emp=emp,
                annual_tbl=annual_tbl, figs=figs)


def fetch_fiscal(meta: dict) -> dict:
    print("    IMF fiscal indicators...")
    idf = imf_fetch(["GGR_NGDP", "GGX_NGDP", "GGXCNL_NGDP", "GGXWDG_NGDP"],
                    meta["iso3"], years=12)
    wdf = wb_fetch(["GC.REV.XGRT.GD.ZS", "GC.XPN.TOTL.GD.ZS", "GC.DOD.TOTL.GD.ZS"],
                   meta["wb"], years=12)

    rev   = idf.loc["GGR_NGDP"].dropna() if "GGR_NGDP" in idf.index else \
            (wdf.loc["GC.REV.XGRT.GD.ZS"].dropna() if "GC.REV.XGRT.GD.ZS" in wdf.index else pd.Series(dtype=float))
    exp   = idf.loc["GGX_NGDP"].dropna() if "GGX_NGDP" in idf.index else \
            (wdf.loc["GC.XPN.TOTL.GD.ZS"].dropna() if "GC.XPN.TOTL.GD.ZS" in wdf.index else pd.Series(dtype=float))
    bal   = idf.loc["GGXCNL_NGDP"].dropna() if "GGXCNL_NGDP" in idf.index else pd.Series(dtype=float)
    debt  = idf.loc["GGXWDG_NGDP"].dropna() if "GGXWDG_NGDP" in idf.index else \
            (wdf.loc["GC.DOD.TOTL.GD.ZS"].dropna() if "GC.DOD.TOTL.GD.ZS" in wdf.index else pd.Series(dtype=float))

    years_10 = sorted([y for y in set(list(rev.index) + list(debt.index)) if isinstance(y, int) and y >= CURR_YEAR - 10])
    rows = {}
    rows["Revenue (% GDP)"]      = {y: rev.get(y, float("nan")) for y in years_10}
    rows["Expenditure (% GDP)"]  = {y: exp.get(y, float("nan")) for y in years_10}
    rows["Fiscal Balance (% GDP)"] = {y: bal.get(y, float("nan")) for y in years_10}
    rows["Public Debt (% GDP)"]  = {y: debt.get(y, float("nan")) for y in years_10}
    annual_tbl = pd.DataFrame(rows).T[years_10] if years_10 else pd.DataFrame()

    figs = {}
    if not rev.empty and not exp.empty:
        common_y = sorted(set(rev.index) & set(exp.index))
        f = go.Figure()
        f.add_trace(go.Scatter(x=common_y, y=[rev.get(y, None) for y in common_y],
                               mode="lines+markers", name="Revenue", line=dict(color=_ACC, width=2)))
        f.add_trace(go.Scatter(x=common_y, y=[exp.get(y, None) for y in common_y],
                               mode="lines+markers", name="Expenditure", line=dict(color=_RED, width=2)))
        f.update_layout(title_text="Govt Revenue vs Expenditure (% GDP)", title_font_color=_ACC)
        figs["rev_exp"] = f

    if not bal.empty:
        colors = [_ACC if v >= 0 else _RED for v in bal.values]
        f = go.Figure(go.Bar(x=list(bal.index), y=list(bal.values), marker_color=colors, name="Fiscal Balance"))
        f.update_layout(title_text="Fiscal Balance (% GDP)", title_font_color=_ACC)
        figs["balance"] = f

    if not debt.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(debt.index), y=list(debt.values),
                               mode="lines+markers", name="Debt/GDP",
                               line=dict(color=_GOLD, width=2),
                               fill="tozeroy", fillcolor="rgba(255,215,0,0.07)"))
        f.add_hline(y=60, line_dash="dash", line_color=_MUTE,
                    annotation_text="60% Maastricht", annotation_font_color=_MUTE)
        f.update_layout(title_text="Public Debt (% GDP)", title_font_color=_ACC)
        figs["debt"] = f

    return dict(idf=idf, wdf=wdf, rev=rev, exp=exp, bal=bal, debt=debt,
                annual_tbl=annual_tbl, figs=figs)


def fetch_external(meta: dict) -> dict:
    print("    World Bank external sector indicators...")
    wdf = wb_fetch(["BN.CAB.XOKA.GD.ZS", "BX.GSR.GNFS.CD", "BM.GSR.GNFS.CD",
                    "FI.RES.TOTL.CD"], meta["wb"], years=12)
    idf = imf_fetch(["BCA_NGDPD"], meta["iso3"], years=12)

    ca   = (idf.loc["BCA_NGDPD"].dropna() if "BCA_NGDPD" in idf.index else
            wdf.loc["BN.CAB.XOKA.GD.ZS"].dropna() if "BN.CAB.XOKA.GD.ZS" in wdf.index else pd.Series(dtype=float))
    exp  = wdf.loc["BX.GSR.GNFS.CD"].dropna() / 1e9 if "BX.GSR.GNFS.CD" in wdf.index else pd.Series(dtype=float)
    imp  = wdf.loc["BM.GSR.GNFS.CD"].dropna() / 1e9 if "BM.GSR.GNFS.CD" in wdf.index else pd.Series(dtype=float)
    res  = wdf.loc["FI.RES.TOTL.CD"].dropna() / 1e9 if "FI.RES.TOTL.CD" in wdf.index else pd.Series(dtype=float)
    tb   = exp - imp if (not exp.empty and not imp.empty) else pd.Series(dtype=float)

    # FX: local currency vs USD daily (5yr)
    fx_df = pd.DataFrame()
    if not meta.get("usd") and meta.get("fx"):
        try:
            tk = yf.Ticker(meta["fx"])
            hist = tk.history(period="5y")
            if not hist.empty:
                fx_df = hist[["Close"]].rename(columns={"Close": f"{meta['currency']}/USD"})
        except Exception:
            pass

    years_10 = sorted([y for y in set(list(ca.index) + list(res.index)) if isinstance(y, int) and y >= CURR_YEAR - 10])
    rows = {}
    rows["Current Account (% GDP)"] = {y: ca.get(y, float("nan")) for y in years_10}
    rows["Exports (USD B)"]         = {y: exp.get(y, float("nan")) for y in years_10}
    rows["Imports (USD B)"]         = {y: imp.get(y, float("nan")) for y in years_10}
    rows["Trade Balance (USD B)"]   = {y: tb.get(y, float("nan")) for y in years_10}
    rows["FX Reserves (USD B)"]     = {y: res.get(y, float("nan")) for y in years_10}
    annual_tbl = pd.DataFrame(rows).T[years_10] if years_10 else pd.DataFrame()

    figs = {}
    if not ca.empty:
        colors = [_ACC if v >= 0 else _RED for v in ca.values]
        f = go.Figure(go.Bar(x=list(ca.index), y=list(ca.values), marker_color=colors, name="CA Balance"))
        f.update_layout(title_text="Current Account Balance (% GDP)", title_font_color=_ACC)
        figs["ca"] = f

    if not tb.empty:
        f = go.Figure()
        f.add_trace(go.Bar(x=list(tb.index), y=list(tb.values),
                           marker_color=[_ACC if v >= 0 else _RED for v in tb.values],
                           name="Trade Balance"))
        f.update_layout(title_text="Trade Balance (USD Billions)", title_font_color=_ACC)
        figs["tb"] = f

    if not res.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=list(res.index), y=list(res.values),
                               mode="lines+markers", name="FX Reserves",
                               line=dict(color=_BLUE, width=2),
                               fill="tozeroy", fillcolor="rgba(88,166,255,0.07)"))
        f.update_layout(title_text="FX Reserves (USD Billions)", title_font_color=_ACC)
        figs["res"] = f

    if not fx_df.empty:
        col = fx_df.columns[0]
        f = go.Figure()
        f.add_trace(go.Scatter(x=fx_df.index, y=fx_df[col],
                               mode="lines", name=col,
                               line=dict(color=_GOLD, width=1.5)))
        f.update_layout(title_text=f"Exchange Rate: {col} (5Y Daily)", title_font_color=_ACC)
        figs["fx"] = f

    return dict(wdf=wdf, idf=idf, ca=ca, exp=exp, imp=imp, tb=tb, res=res,
                fx_df=fx_df, annual_tbl=annual_tbl, figs=figs)


def fetch_financial(meta: dict) -> dict:
    print("    Financial conditions data...")
    wdf = wb_fetch(["FB.AST.NPER.ZS", "FS.AST.DOMS.GD.ZS"], meta["wb"], years=5)

    npl = wdf.loc["FB.AST.NPER.ZS"].dropna() if "FB.AST.NPER.ZS" in wdf.index else pd.Series(dtype=float)
    cred = wdf.loc["FS.AST.DOMS.GD.ZS"].dropna() if "FS.AST.DOMS.GD.ZS" in wdf.index else pd.Series(dtype=float)

    # Equity index YTD
    equity_ytd = float("nan")
    equity_idx = None
    if meta.get("equity"):
        try:
            tk = yf.Ticker(meta["equity"])
            hist = tk.history(period="1y")
            if not hist.empty:
                ytd_start = hist[hist.index >= f"{CURR_YEAR}-01-01"]
                if not ytd_start.empty:
                    equity_ytd = (float(hist["Close"].iloc[-1]) / float(ytd_start["Close"].iloc[0]) - 1) * 100
                    equity_idx = hist["Close"]
        except Exception:
            pass

    # Summary table
    snap_data = {
        "NPL Ratio (%)":             float(npl.iloc[-1]) if not npl.empty else float("nan"),
        "Private Credit/GDP (%)":    float(cred.iloc[-1]) if not cred.empty else float("nan"),
        f"Equity Index YTD (%)":     equity_ytd,
    }

    figs = {}
    if equity_idx is not None and not equity_idx.empty:
        f = go.Figure()
        f.add_trace(go.Scatter(x=equity_idx.index, y=equity_idx.values,
                               mode="lines", name=meta.get("equity", "Equity"),
                               line=dict(color=_ACC, width=1.5)))
        f.update_layout(title_text="Equity Index (1Y)", title_font_color=_ACC)
        figs["equity"] = f

    # Spread proxy: if US, BBB-Treasury spread via FRED
    if meta["use_fred"] and _HAS_FRED:
        try:
            spread = fred_series("BAMLH0A1HYBBEY", freq="MS", start_year=CURR_YEAR - 3)
            if not spread.empty:
                f = go.Figure()
                f.add_trace(go.Scatter(x=spread.index, y=spread.values,
                                       mode="lines", name="HY Spread",
                                       line=dict(color=_RED, width=1.5)))
                f.update_layout(title_text="HY Credit Spread (%) — FCI Proxy", title_font_color=_ACC)
                figs["spread"] = f
        except Exception:
            pass

    return dict(wdf=wdf, npl=npl, cred=cred, snap_data=snap_data, figs=figs)


# ── Commentary generator ──────────────────────────────────────────────────────
def _series_to_str(s: pd.Series, name: str, unit: str = "") -> str:
    if s is None or s.empty:
        return f"{name}: No data available\n"
    recent = s.tail(8)
    lines = [f"  {k}: {v:.2f}{unit}" for k, v in recent.items()]
    return f"{name}:\n" + "\n".join(lines) + "\n"


def generate_commentary(meta: dict, data: dict) -> dict:
    country = meta["name"]
    comments = {}
    gdp  = data["gdp"]
    inf  = data["inflation"]
    mon  = data["monetary"]
    lab  = data["labor"]
    fis  = data["fiscal"]
    ext  = data["external"]
    fin  = data["financial"]

    # Executive summary (1,000 words)
    print("    [AI] Executive summary...")
    exec_data = (
        _series_to_str(gdp["rgdp"], "Real GDP Growth", "%") +
        _series_to_str(inf["cpi"],  "Headline CPI YoY", "%") +
        _series_to_str(mon["pr"],   "Policy Rate", "%") +
        _series_to_str(lab["unemp"],"Unemployment Rate", "%") +
        _series_to_str(fis["bal"],  "Fiscal Balance (% GDP)", "%") +
        _series_to_str(fis["debt"], "Public Debt (% GDP)", "%") +
        _series_to_str(ext["ca"],   "Current Account (% GDP)", "%")
    )
    comments["executive"] = ai_comment(
        "Executive Summary", exec_data, country,
        "Write a comprehensive 1,000-word executive summary covering: growth momentum, "
        "inflation trends, monetary and fiscal policy stance, and key economic headwinds "
        "and tailwinds. Be specific — cite exact data points from the provided series."
    )

    # GDP
    print("    [AI] GDP commentary...")
    gdp_data = _series_to_str(gdp["nom"], "Nominal GDP (USD B)") + \
               _series_to_str(gdp["rgdp"], "Real GDP Growth", "%") + \
               _series_to_str(gdp["pcap"], "Per Capita GDP (USD)")
    comments["gdp"] = ai_comment("GDP & Economic Output", gdp_data, country,
        "Write 3-4 paragraphs analyzing GDP trends, sectoral contributions, and growth drivers. "
        "Cite specific figures. Integrate relevant economic context.")

    # Inflation
    print("    [AI] Inflation commentary...")
    comments["inflation"] = ai_comment("Inflation & Price Trends",
        _series_to_str(inf["cpi"], "Headline CPI YoY", "%"), country,
        "Write 3-4 paragraphs covering inflation trajectory, comparison to central bank target, "
        "supply-side vs demand-side drivers, and wage-inflation dynamics.")

    # Monetary
    print("    [AI] Monetary policy commentary...")
    mon_data = _series_to_str(mon["pr"], "Policy Rate", "%") + \
               _series_to_str(mon["y10"], "10Y Bond Yield", "%")
    comments["monetary"] = ai_comment("Monetary Policy", mon_data, country,
        "Write 3-4 paragraphs on monetary policy stance, rate trajectory, forward guidance, "
        "and implications for financial conditions and the real economy.")

    # Labor
    print("    [AI] Labor market commentary...")
    lab_data = _series_to_str(lab["unemp"], "Unemployment Rate", "%") + \
               _series_to_str(lab["lfpr"], "LFPR", "%")
    comments["labor"] = ai_comment("Labor Market Dynamics", lab_data, country,
        "Write 3-4 paragraphs on labor market tightness, wage dynamics, participation trends, "
        "and structural employment factors.")

    # Fiscal
    print("    [AI] Fiscal commentary...")
    fis_data = _series_to_str(fis["rev"],  "Revenue (% GDP)", "%") + \
               _series_to_str(fis["exp"],  "Expenditure (% GDP)", "%") + \
               _series_to_str(fis["bal"],  "Fiscal Balance (% GDP)", "%") + \
               _series_to_str(fis["debt"], "Public Debt (% GDP)", "%")
    comments["fiscal"] = ai_comment("Fiscal Position & Debt", fis_data, country,
        "Write 3-4 paragraphs on fiscal stance, budgetary discipline, debt sustainability, "
        "and fiscal impulse to the economy.")

    # External
    print("    [AI] External sector commentary...")
    ext_data = _series_to_str(ext["ca"], "Current Account (% GDP)", "%") + \
               _series_to_str(ext["tb"], "Trade Balance (USD B)") + \
               _series_to_str(ext["res"], "FX Reserves (USD B)")
    comments["external"] = ai_comment("External Sector", ext_data, country,
        "Write 3-4 paragraphs on trade dynamics, current account sustainability, "
        "capital flows, currency stability, and reserve adequacy.")

    # Financial
    print("    [AI] Financial conditions commentary...")
    fin_data = f"Snap data: {fin['snap_data']}\n" + _series_to_str(fin["npl"], "NPL Ratio", "%")
    comments["financial"] = ai_comment("Financial Conditions", fin_data, country,
        "Write 3-4 paragraphs on financial system resilience, credit market conditions, "
        "equity market performance, and potential asset price vulnerabilities.")

    # Pros & Cons
    print("    [AI] Pros & cons...")
    all_data = exec_data + gdp_data + fis_data + ext_data
    comments["pros_cons"] = ai_comment("Pros & Cons", all_data, country,
        "Based strictly on the data, provide: "
        "STRENGTHS: 3-6 bullet points (start each with '+'). "
        "CONCERNS: 3-6 bullet points (start each with '-'). "
        "Each point must cite a specific data observation.")

    # Outlook & Resilience Rating
    print("    [AI] Outlook & resilience score...")
    comments["outlook"] = ai_comment("Outlook & Resilience", all_data, country,
        "Write: (1) Two paragraphs on the economic outlook. "
        "(2) A Macro Resilience Rating from 1 to 5 in 0.5 increments, strictly derived "
        "from the quantitative data. Format the final rating exactly as: "
        "'RESILIENCE RATING: X.X/5' on its own line.")

    # Geopolitical timeline
    print("    [AI] Geopolitical timeline...")
    comments["timeline"] = ai_comment("Geopolitical Timeline", exec_data, country,
        "List the 5 most significant geopolitical or economic policy events for this country "
        "in the last 5 years. Format each as: 'DATE | EVENT | One-sentence economic impact.' "
        "Only cite verifiable, publicly documented events. Use format: Month YYYY | ...")

    return comments


# ── Tab HTML builders ─────────────────────────────────────────────────────────
def _figs_row(figs: dict, keys: list, cls: str = "g2") -> str:
    cells = ""
    for k in keys:
        if k in figs:
            cells += f'<div class="cb">{fig_html(figs[k])}</div>'
        else:
            cells += '<div class="cb" style="padding:20px"><p class="na">Chart not available</p></div>'
    if not cells:
        return ""
    return f'<div class="{cls}">{cells}</div>'


def _commentary_html(text: str) -> str:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    inner = "".join(f"<p>{p}</p>" for p in paras)
    return f'<div class="commentary">{inner}</div>'


def tab_executive(data: dict, comments: dict, meta: dict) -> str:
    gdp  = data["gdp"]
    inf  = data["inflation"]
    mon  = data["monetary"]
    lab  = data["labor"]

    # Sparkline charts (4 across)
    figs_exec = {}
    if not gdp["nom"].empty:
        f = go.Figure(go.Bar(x=list(gdp["nom"].tail(5).index),
                             y=list(gdp["nom"].tail(5).values), marker_color=_ACC))
        f.update_layout(title_text="Nominal GDP (USD B)", showlegend=False)
        figs_exec["nom"] = f
    if not gdp["rgdp"].empty:
        vals = gdp["rgdp"].tail(5)
        f = go.Figure(go.Bar(x=list(vals.index), y=list(vals.values),
                             marker_color=[_ACC if v >= 0 else _RED for v in vals]))
        f.update_layout(title_text="Real GDP Growth (%)", showlegend=False)
        figs_exec["rgdp"] = f
    if not inf["cpi"].empty:
        vals = inf["cpi"].tail(5)
        f = go.Figure(go.Scatter(x=list(vals.index), y=list(vals.values),
                                 mode="lines+markers", line=dict(color=_RED, width=2)))
        f.update_layout(title_text="Headline CPI YoY (%)", showlegend=False)
        figs_exec["cpi"] = f
    if not mon["pr"].empty:
        vals = mon["pr"].tail(5)
        f = go.Figure(go.Scatter(x=list(vals.index), y=list(vals.values),
                                 mode="lines+markers", line=dict(color=_BLUE, width=2)))
        f.update_layout(title_text="Policy Rate (%)", showlegend=False)
        figs_exec["rate"] = f

    charts_html = _figs_row(figs_exec, ["nom", "rgdp", "cpi", "rate"], "g4")

    # Timeline
    raw_tl = comments.get("timeline", "")
    tl_items = ""
    for line in raw_tl.split("\n"):
        line = line.strip()
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                dt_str = parts[0]
                rest = " | ".join(parts[1:])
                tl_items += f'<li class="tl-item"><div class="tl-dt">{dt_str}</div><div class="tl-tx">{rest}</div></li>'
    timeline_html = f'<ul class="tl">{tl_items}</ul>' if tl_items else '<p class="na">Timeline not available</p>'

    return f"""
    <div class="sh">Executive Overview — Last 5 Years</div>
    {charts_html}
    <div class="sh">1,000-Word Economic Overview</div>
    <div class="panel">{_commentary_html(comments.get("executive",""))}</div>
    <div class="sh">Key Geopolitical & Policy Timeline</div>
    <div class="panel">{timeline_html}</div>
    """


def tab_events(meta: dict) -> str:
    today_dt = TODAY
    country_key = meta["name"].lower()
    events = []

    # Global + country-specific events
    for src_key in ["_global", country_key]:
        for ev in _EVENTS.get(src_key, []):
            try:
                evd = datetime.date.fromisoformat(ev["date"])
                if evd >= today_dt:
                    events.append({**ev, "_dt": evd})
            except Exception:
                pass

    events.sort(key=lambda e: e["_dt"])
    events = events[:30]

    type_map = {"cb": ("t-cb", "CENTRAL BANK"), "dt": ("t-dt", "ECONOMIC DATA"), "po": ("t-po", "POLITICAL")}

    cards = ""
    for ev in events:
        dt = ev["_dt"]
        cls, lbl = type_map.get(ev.get("type", "dt"), ("t-dt", "DATA"))
        cards += f"""
        <div class="cal-card">
          <div class="cal-db">
            <div class="cal-mo">{dt.strftime('%b')}</div>
            <div class="cal-dy">{dt.day:02d}</div>
          </div>
          <div class="cal-info">
            <div class="cal-ttl">{ev['title']}</div>
            <div class="cal-dsc">{ev.get('desc','')}</div>
            <span class="cal-tp {cls}">{lbl}</span>
          </div>
        </div>"""

    if not cards:
        cards = '<p class="na">No upcoming events found for this country.</p>'

    return f"""
    <div class="sh">Upcoming Economic Calendar — {meta['name']}</div>
    <div class="panel">
      <p style="color:#8b949e;font-size:11px;margin-bottom:12px;">
        Dates shown from {today_dt.strftime('%B %d, %Y')} forward.
        Central bank meetings, key data releases, and political events.
      </p>
      <div class="cal-g">{cards}</div>
    </div>"""


def tab_gdp(data: dict, comments: dict) -> str:
    d = data["gdp"]
    pct_rows = ["Nominal GDP YoY (%)", "Real GDP YoY (%)", "Consumption (% GDP)",
                "Investment (% GDP)", "Govt Spending (% GDP)", "Net Exports (% GDP)", "Per Capita YoY (%)"]
    bn_rows  = ["Nominal GDP (USD B)"]
    usd_rows = ["Per Capita GDP (USD)"]
    return f"""
    <div class="sh">GDP Charts</div>
    {_figs_row(d['figs'], ['nom','rgdp','comp'], 'g3')}
    <div class="sh">Annual Data (Last 10 Years)</div>
    <div class="panel">
      {df_to_html(d['annual_tbl'], pct_rows=pct_rows, bn_rows=bn_rows, usd_rows=usd_rows)}
      <p class="warn" style="margin-top:8px">Sources: World Bank (NY.GDP.MKTP.CD, NY.GDP.MKTP.KD.ZG), IMF WEO (NGDPD, NGDP_RPCH)</p>
    </div>
    <div class="sh">Analysis</div>
    <div class="panel">{_commentary_html(comments.get('gdp',''))}</div>"""


def tab_inflation(data: dict, comments: dict) -> str:
    d = data["inflation"]
    pct_rows = ["Headline CPI YoY (%)"]
    return f"""
    <div class="sh">Inflation Charts</div>
    {_figs_row(d['figs'], ['cpi'], 'g2')}
    <div class="sh">Annual Data (Last 10 Years)</div>
    <div class="panel">
      {df_to_html(d['annual_tbl'], pct_rows=pct_rows)}
      <p class="warn" style="margin-top:8px">Sources: World Bank (FP.CPI.TOTL.ZG), IMF WEO (PCPIPCH)</p>
    </div>
    <div class="sh">Analysis</div>
    <div class="panel">{_commentary_html(comments.get('inflation',''))}</div>"""


def tab_monetary(data: dict, comments: dict, meta: dict) -> str:
    d = data["monetary"]
    latest_r  = _safe(d["latest_rate"], ".2f")
    latest_y10 = _safe(d["latest_y10"], ".2f")
    pct_rows  = ["Policy Rate (%)", "2Y Bond Yield (%)", "10Y Bond Yield (%)"]

    snap = f"""
    <div class="snap-g">
      <div class="snap"><div class="snap-lbl">POLICY RATE (CURRENT)</div>
        <div class="snap-val">{latest_r}%</div>
        <div class="snap-sub">{meta['cb']}</div></div>
      <div class="snap"><div class="snap-lbl">10Y BOND YIELD</div>
        <div class="snap-val">{latest_y10}%</div>
        <div class="snap-sub">Latest available</div></div>
      <div class="snap"><div class="snap-lbl">OECD MEMBER</div>
        <div class="snap-val">{"YES" if meta.get("oecd") else "NO"}</div>
        <div class="snap-sub">Market classification</div></div>
    </div>"""

    yc_html = ""
    if "yc" in d["figs"]:
        yc_html = f'<div class="sh">Yield Curve Snapshot</div>{_figs_row(d["figs"], ["yc"], "g2")}'

    return f"""
    <div class="sh">Policy Snapshot</div>
    <div class="panel">{snap}</div>
    <div class="sh">Interest Rate History</div>
    {_figs_row(d['figs'], ['rates'], 'g2')}
    {yc_html}
    <div class="sh">Annual Rate Data (Last 10 Years)</div>
    <div class="panel">
      {df_to_html(d['annual_tbl'], pct_rows=pct_rows)}
      <p class="warn" style="margin-top:8px">Sources: FRED (FEDFUNDS, GS2, GS10, GS30 — US only), IMF WEO (FPOLM)</p>
    </div>
    <div class="sh">Analysis</div>
    <div class="panel">{_commentary_html(comments.get('monetary',''))}</div>"""


def tab_labor(data: dict, comments: dict, mon: dict) -> str:
    d = data["labor"]
    pct_rows = ["Unemployment Rate (%)", "Labor Force Participation (%)", "Employment-to-Pop Ratio (%)"]

    # Monthly payrolls chart (US FRED)
    payrolls_html = ""
    if not mon["payrolls"].empty:
        pr = mon["payrolls"]
        chg = pr.diff() / 1000  # convert to millions
        f = go.Figure(go.Bar(x=list(chg.index), y=list(chg.dropna().values),
                             marker_color=[_ACC if v >= 0 else _RED for v in chg.dropna().values],
                             name="Monthly Employment Change"))
        f.update_layout(title_text="Monthly Employment Change (Millions)", title_font_color=_ACC)
        payrolls_html = f"""
        <div class="sh">Monthly Employment Change (Last 36 Months — FRED)</div>
        <div class="g2"><div class="cb">{fig_html(f)}</div></div>"""

    return f"""
    <div class="sh">Labor Market Charts</div>
    {_figs_row(d['figs'], ['unemp','lfpr','emp'], 'g3')}
    <div class="sh">Annual Data (Last 10 Years)</div>
    <div class="panel">
      {df_to_html(d['annual_tbl'], pct_rows=pct_rows)}
      <p class="warn" style="margin-top:8px">Source: World Bank (SL.UEM.TOTL.ZS, SL.TLF.CACT.ZS, SL.EMP.TOTL.SP.ZS)</p>
    </div>
    {payrolls_html}
    <div class="sh">Analysis</div>
    <div class="panel">{_commentary_html(comments.get('labor',''))}</div>"""


def tab_fiscal(data: dict, comments: dict) -> str:
    d = data["fiscal"]
    pct_rows = ["Revenue (% GDP)", "Expenditure (% GDP)", "Fiscal Balance (% GDP)", "Public Debt (% GDP)"]
    return f"""
    <div class="sh">Fiscal Charts</div>
    {_figs_row(d['figs'], ['rev_exp','balance','debt'], 'g3')}
    <div class="sh">Annual Data (Last 10 Years)</div>
    <div class="panel">
      {df_to_html(d['annual_tbl'], pct_rows=pct_rows)}
      <p class="warn" style="margin-top:8px">Sources: IMF WEO (GGR_NGDP, GGX_NGDP, GGXCNL_NGDP, GGXWDG_NGDP), World Bank</p>
    </div>
    <div class="sh">Analysis</div>
    <div class="panel">{_commentary_html(comments.get('fiscal',''))}</div>"""


def tab_external(data: dict, comments: dict, meta: dict) -> str:
    d = data["external"]
    pct_rows  = ["Current Account (% GDP)"]
    bn_rows   = ["Exports (USD B)", "Imports (USD B)", "Trade Balance (USD B)", "FX Reserves (USD B)"]
    fx_html   = ""
    if "fx" in d["figs"]:
        fx_html = f"""
        <div class="sh">Exchange Rate: {meta['currency']} vs USD (5Y Daily)</div>
        {_figs_row(d['figs'], ['fx'], 'g2')}"""

    return f"""
    <div class="sh">External Sector Charts</div>
    {_figs_row(d['figs'], ['ca','tb','res'], 'g3')}
    <div class="sh">Annual Data (Last 10 Years)</div>
    <div class="panel">
      {df_to_html(d['annual_tbl'], pct_rows=pct_rows, bn_rows=bn_rows)}
      <p class="warn" style="margin-top:8px">Sources: IMF WEO (BCA_NGDPD), World Bank (BN.CAB, BX.GSR, FI.RES)</p>
    </div>
    {fx_html}
    <div class="sh">Analysis</div>
    <div class="panel">{_commentary_html(comments.get('external',''))}</div>"""


def tab_financial(data: dict, comments: dict, meta: dict) -> str:
    d = data["financial"]
    snap = d["snap_data"]

    snap_html = '<div class="snap-g">'
    for k, v in snap.items():
        val_str = f"{v:.1f}%" if not (isinstance(v, float) and str(v) == "nan") else "N/A"
        snap_html += f'<div class="snap"><div class="snap-lbl">{k.upper()}</div><div class="snap-val">{val_str}</div></div>'
    snap_html += "</div>"

    figs_keys = list(d["figs"].keys())
    return f"""
    <div class="sh">Financial Conditions Snapshot</div>
    <div class="panel">{snap_html}</div>
    <div class="sh">Charts</div>
    {_figs_row(d['figs'], figs_keys[:2], 'g2')}
    <div class="sh">Analysis</div>
    <div class="panel">{_commentary_html(comments.get('financial',''))}</div>
    <div class="sh">Data Notes</div>
    <div class="panel">
      <p class="warn">Sources: World Bank (FB.AST.NPER.ZS — NPL ratio, FS.AST.DOMS.GD.ZS — Private Credit/GDP),
      yfinance (equity index), FRED (HY spread — US only).<br>
      Credit-to-GDP gap: BIS methodology. Housing price data: national statistics bureaus — flagged if unavailable.</p>
    </div>"""


def tab_pros_cons(comments: dict) -> str:
    raw = comments.get("pros_cons", "")
    pros, cons = [], []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("+"):
            pros.append(line[1:].strip())
        elif line.startswith("-"):
            cons.append(line[1:].strip())

    def _items(lst, cls, arrow_cls):
        if not lst:
            return '<p class="na">No items generated.</p>'
        return "".join(f'<div class="pc-item"><span class="{arrow_cls}">{"▲" if cls=="pro-box" else "▼"}</span><span>{i}</span></div>' for i in lst)

    return f"""
    <div class="sh">Strengths & Concerns — Data-Grounded</div>
    <div class="pros-cons">
      <div class="pro-box"><h3>▲ STRENGTHS</h3>{_items(pros,'pro-box','pu')}</div>
      <div class="con-box"><h3>▼ CONCERNS</h3>{_items(cons,'con-box','pd')}</div>
    </div>"""


def tab_outlook(comments: dict) -> str:
    raw = comments.get("outlook", "")
    # Extract resilience score
    score_str = "—"
    lines = []
    for line in raw.split("\n"):
        if "RESILIENCE RATING:" in line.upper():
            parts = line.upper().replace("RESILIENCE RATING:", "").strip().split("/")
            try:
                score_str = parts[0].strip()
            except Exception:
                pass
        else:
            lines.append(line)
    text = "\n\n".join(p.strip() for p in " ".join(lines).split("  ") if p.strip())

    try:
        score_float = float(score_str)
        stars = "★" * int(score_float) + ("½" if score_float % 1 else "") + "☆" * (5 - int(score_float + 0.49))
    except Exception:
        stars = ""

    return f"""
    <div class="sh">Macro Outlook</div>
    <div class="panel">{_commentary_html(text)}</div>
    <div class="sh">Macro Resilience Rating</div>
    <div class="panel">
      <div class="resilience-wrap">
        <div class="r-score">{score_str} / 5</div>
        <div style="font-size:22px;color:#00d4aa;margin:8px 0">{stars}</div>
        <div class="r-lbl">MACRO RESILIENCE RATING — Strictly quantitative; 0.5 increment scale</div>
      </div>
    </div>"""


def tab_sources(meta: dict) -> str:
    return f"""
    <div class="sh">Data Sources by Section</div>
    <div class="src-g">
      <div class="src-card"><div class="src-sec">GDP & ECONOMIC OUTPUT</div>
        <ul class="src-list">
          <li>World Bank: NY.GDP.MKTP.CD, NY.GDP.MKTP.KD.ZG, NY.GDP.PCAP.CD</li>
          <li>World Bank: NE.CON.PRVT.ZS, NE.GDI.TOTL.ZS, NE.CON.GOVT.ZS</li>
          <li>IMF DataMapper: NGDPD, NGDP_RPCH, NGDPDPC</li>
          <li>Release dates: World Bank Data API (api.worldbank.org/v2)</li>
        </ul>
      </div>
      <div class="src-card"><div class="src-sec">INFLATION & PRICES</div>
        <ul class="src-list">
          <li>World Bank: FP.CPI.TOTL.ZG (CPI YoY %)</li>
          <li>IMF DataMapper: PCPIPCH, PCPIEPCH</li>
          <li>National statistics bureaus (country-specific)</li>
        </ul>
      </div>
      <div class="src-card"><div class="src-sec">MONETARY POLICY</div>
        <ul class="src-list">
          <li>{"FRED: FEDFUNDS, GS2, GS10, GS30 (U.S. only)" if meta["use_fred"] else "IMF DataMapper: FPOLM"}</li>
          <li>IMF DataMapper: FPOLM (policy rate)</li>
          <li>Central bank: {meta['cb']}</li>
        </ul>
      </div>
      <div class="src-card"><div class="src-sec">LABOR MARKET</div>
        <ul class="src-list">
          <li>World Bank: SL.UEM.TOTL.ZS (unemployment)</li>
          <li>World Bank: SL.TLF.CACT.ZS (labor force participation)</li>
          <li>World Bank: SL.EMP.TOTL.SP.ZS (employment/pop)</li>
          {"<li>FRED: PAYEMS (monthly payrolls — US only)</li>" if meta['use_fred'] else ""}
        </ul>
      </div>
      <div class="src-card"><div class="src-sec">FISCAL POSITION</div>
        <ul class="src-list">
          <li>IMF WEO: GGR_NGDP, GGX_NGDP, GGXCNL_NGDP, GGXWDG_NGDP</li>
          <li>World Bank: GC.REV.XGRT.GD.ZS, GC.XPN.TOTL.GD.ZS, GC.DOD.TOTL.GD.ZS</li>
        </ul>
      </div>
      <div class="src-card"><div class="src-sec">EXTERNAL SECTOR</div>
        <ul class="src-list">
          <li>IMF WEO: BCA_NGDPD (current account)</li>
          <li>World Bank: BN.CAB.XOKA.GD.ZS, BX.GSR.GNFS.CD, BM.GSR.GNFS.CD, FI.RES.TOTL.CD</li>
          {"<li>yfinance: " + meta['fx'] + " (FX daily)</li>" if meta.get('fx') else ""}
        </ul>
      </div>
      <div class="src-card"><div class="src-sec">FINANCIAL CONDITIONS</div>
        <ul class="src-list">
          <li>World Bank: FB.AST.NPER.ZS (NPL ratio), FS.AST.DOMS.GD.ZS</li>
          <li>yfinance: {meta.get('equity','—')} (equity index)</li>
          {"<li>FRED: BAMLH0A1HYBBEY (HY spread — US)</li>" if meta['use_fred'] else ""}
          <li>BIS: Credit-to-GDP gap (flagged if unavailable)</li>
        </ul>
      </div>
      <div class="src-card"><div class="src-sec">COMMENTARY GENERATION</div>
        <ul class="src-list">
          <li>Anthropic Claude API ({_AI_MODEL})</li>
          <li>Strictly data-grounded; no external conjecture</li>
          <li>All figures cited from data fetched above</li>
        </ul>
      </div>
    </div>"""


def tab_disclaimer() -> str:
    return f"""
    <div class="sh">Disclaimer</div>
    <div class="dis-box">
      <p><strong style="color:#ffd700">DATA RELEASE DATES:</strong>
      All data presented in this dashboard use actual release dates as published by the respective
      statistical agencies (World Bank, IMF, national bureaus). Figures are not adjusted for
      fiscal year conventions unless explicitly noted. Latest available vintage used as of
      {TODAY.strftime('%B %d, %Y')}. World Bank data typically lags by 1–2 years;
      IMF WEO projections are flagged separately from historical observations.</p>
      <p><strong style="color:#ffd700">NOT INVESTMENT ADVICE:</strong>
      This dashboard is produced for informational and analytical purposes only.
      Nothing contained herein constitutes investment advice, a solicitation, or an offer
      to buy or sell any security or financial instrument. Past economic performance does not
      guarantee future outcomes. Users should conduct their own independent research and consult
      qualified financial advisors before making investment decisions.</p>
      <p><strong style="color:#ffd700">DATA ACCURACY:</strong>
      While data is sourced from reputable public institutions (World Bank, IMF, FRED, OECD),
      errors or omissions may exist. Some indicators may be unavailable for certain countries
      and are flagged accordingly. AI-generated commentary is based solely on the data fetched
      and should be independently verified against primary sources.</p>
      <p>Generated: {TODAY.strftime('%B %d, %Y')} | Model: {_AI_MODEL} | Tool: Macro Dashboard Generator</p>
    </div>"""


# ── HTML assembler ────────────────────────────────────────────────────────────
_TAB_LABELS = [
    "01 EXECUTIVE", "02 EVENTS", "03 GDP", "04 INFLATION",
    "05 MONETARY", "06 LABOR", "07 FISCAL", "08 EXTERNAL",
    "09 FINANCIAL", "10 PROS & CONS", "11 OUTLOOK", "12 SOURCES", "13 DISCLAIMER"
]

def build_html(meta: dict, tab_contents: list) -> str:
    nav = "".join(
        f'<button class="tab-btn{" active" if i==0 else ""}" onclick="showTab({i})">{lbl}</button>'
        for i, lbl in enumerate(_TAB_LABELS)
    )
    panels = "".join(
        f'<div class="tab-panel{" active" if i==0 else ""}" id="tp{i}">{tc}</div>'
        for i, tc in enumerate(tab_contents)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Macro Dashboard: {meta['name']}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="hdr">
  <div>
    <div class="hdr-brand">MACROECONOMIC DASHBOARD</div>
    <div class="hdr-title">{meta['name'].upper()}</div>
  </div>
  <div class="hdr-meta">
    <div>Central Bank: <strong>{meta['cb']}</strong></div>
    <div>Currency: <strong>{meta['currency']}</strong></div>
    <div>Classification: <strong>{"OECD Member" if meta.get("oecd") else "Non-OECD"}</strong></div>
    <div>Report Date: <strong>{TODAY.strftime('%B %d, %Y')}</strong></div>
  </div>
</div>
<nav class="tab-nav">{nav}</nav>
<div>{panels}</div>
<script>
function showTab(n){{
  document.querySelectorAll('.tab-btn').forEach((b,i)=>b.classList.toggle('active',i===n));
  document.querySelectorAll('.tab-panel').forEach((p,i)=>p.classList.toggle('active',i===n));
}}
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Macro Dashboard Generator")
    parser.add_argument("--country", type=str, help="Country name")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  MACRO DASHBOARD GENERATOR")
    print("=" * 60)
    print("\n  READY FOR ANALYSIS\n")

    country_input = args.country or input("  Enter country name: ").strip()

    meta = resolve_country(country_input)
    while meta is None:
        print(f"  ✗ '{country_input}' not recognized. Try a different spelling.")
        country_input = input("  Enter country name: ").strip()
        meta = resolve_country(country_input)

    print(f"\n  Country : {meta['name']} ({meta['wb']}) | {meta['iso3']}")
    print(f"  Currency: {meta['currency']} | CB: {meta['cb']}")
    print(f"  OECD: {'Yes' if meta.get('oecd') else 'No'} | USD-based: {'Yes' if meta.get('usd') else 'No'}")
    print("\n  [1/3] Fetching macroeconomic data...\n")

    data = {
        "gdp":       fetch_gdp(meta),
        "inflation": fetch_inflation(meta),
        "monetary":  fetch_monetary(meta),
        "labor":     fetch_labor(meta),
        "fiscal":    fetch_fiscal(meta),
        "external":  fetch_external(meta),
        "financial": fetch_financial(meta),
    }

    print("\n  [2/3] Generating AI commentary (Claude API)...\n")
    comments = generate_commentary(meta, data)

    print("\n  [3/3] Assembling HTML dashboard...\n")
    tab_contents = [
        tab_executive(data, comments, meta),
        tab_events(meta),
        tab_gdp(data, comments),
        tab_inflation(data, comments),
        tab_monetary(data, comments, meta),
        tab_labor(data, comments, data["monetary"]),
        tab_fiscal(data, comments),
        tab_external(data, comments, meta),
        tab_financial(data, comments, meta),
        tab_pros_cons(comments),
        tab_outlook(comments),
        tab_sources(meta),
        tab_disclaimer(),
    ]

    html = build_html(meta, tab_contents)

    out_dir = _ROOT / "reports" / "macro"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{meta['iso3']}_{TODAY.strftime('%Y-%m-%d')}.html"
    out_file.write_text(html, encoding="utf-8")

    print(f"  ✓ Dashboard saved → {out_file}")
    print(f"  Open in browser: open \"{out_file}\"\n")


if __name__ == "__main__":
    main()
