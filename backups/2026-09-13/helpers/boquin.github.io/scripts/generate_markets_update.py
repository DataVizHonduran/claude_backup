"""
Daily US Markets Update — Gemma 4 economist analyst notes.

Checks the FRED release calendar for the past 48 hours, matches against a
whitelist of major releases, pulls the relevant data series for each match,
and generates a sell-side-style analyst note via Gemma 4 on HuggingFace.

Usage:
    FRED_API_KEY=xxx HF_TOKEN=xxx python scripts/generate_markets_update.py

GitHub Actions secrets required:
    FRED_API_KEY
    HF_TOKEN

Adding a new release: add one entry each to RELEASE_WHITELIST and RELEASE_SERIES.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from huggingface_hub import InferenceClient
import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID  = "google/gemma-4-31B-it"
FRED_BASE = "https://api.stlouisfed.org/fred"
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", 48))
OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "markets-update"

# FRED release IDs for major US macro releases.
# Add a new entry here (and in RELEASE_SERIES below) to cover more releases.
RELEASE_WHITELIST = {
    # --- Tier 1: highest market impact ---
    50:  "Employment Situation (NFP)",
    10:  "Consumer Price Index (CPI)",
    46:  "Producer Price Index (PPI)",
    54:  "Personal Income and Outlays (PCE)",
    53:  "Gross Domestic Product (GDP)",
    9:   "Advance Retail Sales",
    180: "Unemployment Insurance Weekly Claims",
    13:  "Industrial Production and Capacity Utilization",
    # --- Tier 2: high market impact ---
    192: "Job Openings and Labor Turnover Survey (JOLTS)",
    194: "ADP National Employment Report",
    291: "Existing Home Sales",
    97:  "New Residential Sales",
    27:  "New Residential Construction",
    95:  "Durable Goods Orders",
    51:  "U.S. International Trade in Goods and Services",
    188: "U.S. Import and Export Price Indexes",
    11:  "Employment Cost Index",
    47:  "Productivity and Costs",
    229: "Construction Spending",
    14:  "Consumer Credit (G.19)",
    # --- Tier 3: supplemental / regional ---
    91:  "University of Michigan Consumer Sentiment",
    321: "Empire State Manufacturing Survey",
    351: "Philadelphia Fed Manufacturing Survey",
    219: "Chicago Fed National Activity Index (CFNAI)",
    221: "Chicago Fed National Financial Conditions Index",
    191: "Senior Loan Officer Opinion Survey",
    199: "S&P Case-Shiller Home Price Index",
    171: "FHFA House Price Index",
    25:  "Manufacturing and Trade Inventories and Sales",
    # --- Tier 4: additional coverage ---
    290: "Monthly Wholesale Trade",
    22:  "H.8 Assets and Liabilities of Commercial Banks",
    21:  "H.6 Money Stock Measures",
    323: "Trimmed Mean PCE Inflation Rate (Dallas Fed)",
    179: "Quarterly Retail E-Commerce Sales",
    435: "Advance Economic Indicators",
    374: "Texas Manufacturing Outlook Survey",
    443: "Business Formation Statistics",
    190: "Primary Mortgage Market Survey",
    231: "Charge-Off and Delinquency Rates on Loans",
}

# Series to pull for each release (FRED release_id → list of (label, series_id)).
# Any series that FRED rejects is skipped automatically — no crash.
RELEASE_SERIES = {
    50: [  # NFP
        ("Nonfarm Payrolls (thousands, SA)",            "PAYEMS"),
        ("Unemployment Rate (%, SA)",                   "UNRATE"),
        ("U-6 Underemployment Rate (%, SA)",            "U6RATE"),
        ("Labor Force Participation Rate (%, SA)",      "CIVPART"),
        ("Avg Hourly Earnings, Private ($/hr, SA)",     "CES0500000003"),
        ("Avg Weekly Hours, Private (hrs, SA)",         "AWHNONAG"),
        ("Private Payrolls (thousands, SA)",            "USPRIV"),
        ("Government Payrolls (thousands, SA)",         "USGOVT"),
        ("Manufacturing Payrolls (thousands, SA)",      "MANEMP"),
        ("Long-term Unemployed 27+ weeks (thousands)",  "UEMP27OV"),
    ],
    10: [  # CPI
        ("CPI All Items (index, SA)",                   "CPIAUCSL"),
        ("Core CPI ex Food & Energy (index, SA)",       "CPILFESL"),
        ("CPI Food (index, unadj)",                     "CPIUFDSL"),
        ("CPI Energy (index, unadj)",                   "CPIENGSL"),
        ("CPI Shelter (index, SA)",                     "CUSR0000SAH1"),
        ("CPI Medical Care (index, unadj)",             "CPIMEDSL"),
        ("CPI Transportation (index, unadj)",           "CPITRNSL"),
    ],
    46: [  # PPI
        ("PPI All Commodities (index)",                 "PPIACO"),
        ("PPI Final Demand ex Food & Energy (index, SA)","PPIFES"),
        ("PPI Finished Goods (index, SA)",              "PPIGFD"),
        ("PPI Services (index, SA)",                    "PPIS"),
    ],
    54: [  # PCE
        ("PCE Price Index (index, SA)",                 "PCEPI"),
        ("Core PCE Price Index (index, SA)",            "PCEPILFE"),
        ("Personal Income (bn $, SAAR)",                "PI"),
        ("Personal Consumption Expenditures (bn $, SA)","PCE"),
        ("Personal Saving Rate (%, SA)",                "PSAVERT"),
    ],
    53: [  # GDP
        ("Real GDP (bn 2017$, SAAR)",                   "GDPC1"),
        ("GDP Deflator (index, SA)",                    "GDPDEF"),
        ("Real Private Investment (bn 2017$, SAAR)",    "GPDIC1"),
        ("Real Government Consumption (bn 2017$, SAAR)","GCEC1"),
        ("Real Exports (bn 2017$, SAAR)",               "EXPGSC1"),
        ("Real Imports (bn 2017$, SAAR)",               "IMPGSC1"),
    ],
    9: [  # Advance Retail Sales
        ("Retail Sales Total (mn $, SA)",               "RSAFS"),
        ("Retail Sales ex Autos (mn $, SA)",            "RSFSXMV"),
        ("Retail Sales ex Autos & Gas (mn $, SA)",      "RSFSDG"),
    ],
    180: [  # Jobless Claims
        ("Initial Jobless Claims (thousands, SA)",      "ICSA"),
        ("Continued Claims (thousands, SA)",            "CCSA"),
        ("4-Week Avg Initial Claims (thousands, SA)",   "IC4WSA"),
    ],
    13: [  # Industrial Production
        ("Industrial Production Index (index, SA)",     "INDPRO"),
        ("Capacity Utilization, Total (%, SA)",         "TCU"),
        ("Manufacturing Production (index, SA)",        "IPMAN"),
        ("Mining Production (index, SA)",               "IPB10001N"),
        ("Utilities Production (index, SA)",            "IPG2211S"),
    ],
    192: [  # JOLTS
        ("Job Openings (thousands, SA)",                "JTSJOL"),
        ("Hires (thousands, SA)",                       "JTSHIL"),
        ("Quits (thousands, SA)",                       "JTSQUL"),
        ("Quits Rate (%, SA)",                          "JTSQUR"),
        ("Layoffs & Discharges Rate (%, SA)",           "JTSLDR"),
    ],
    194: [  # ADP
        ("ADP Private Nonfarm Employment (thousands)",  "ADPWNUSNERSA"),
    ],
    291: [  # Existing Home Sales
        ("Existing Home Sales (SAAR, thousands)",       "EXHOSLUSM495S"),
    ],
    97: [  # New Home Sales
        ("New One-Family Houses Sold (SAAR, thousands)","HSN1F"),
        ("New Home Median Sales Price ($)",             "MSPNHSUS"),
    ],
    27: [  # New Residential Construction
        ("Housing Starts Total (SAAR, thousands)",      "HOUST"),
        ("Housing Starts 1-Unit (SAAR, thousands)",     "HOUST1F"),
        ("Building Permits Total (SAAR, thousands)",    "PERMIT"),
        ("Building Permits 1-Unit (SAAR, thousands)",   "PERMIT1"),
    ],
    95: [  # Durable Goods
        ("Durable Goods New Orders (mn $, SA)",         "DGORDER"),
        ("Core Capex Orders ex Aircraft (mn $, SA)",    "NEWORDER"),
    ],
    51: [  # Trade Balance
        ("Trade Balance, Goods & Services (mn $, SA)",  "BOPGSTB"),
        ("Goods Trade Balance (mn $, SA)",              "BOPGTB"),
    ],
    188: [  # Import/Export Prices
        ("Import Price Index (index)",                  "IR"),
        ("Export Price Index (index)",                  "IQ"),
    ],
    11: [  # Employment Cost Index
        ("ECI Total Compensation, All Civilian (SA)",   "ECIALLCIV"),
        ("ECI Wages & Salaries, Private (SA)",          "ECIWAG"),
    ],
    47: [  # Productivity & Costs
        ("Nonfarm Business Output per Hour (SA)",       "OPHNFB"),
        ("Unit Labor Costs, Nonfarm Business (SA)",     "ULCNFB"),
    ],
    229: [  # Construction Spending
        ("Total Construction Spending (mn $, SA)",      "TTLCONS"),
        ("Private Residential Construction (mn $, SA)", "PRRESCON"),
        ("Private Nonresidential Construction (mn $, SA)","TLNRESCONS"),
    ],
    14: [  # Consumer Credit
        ("Total Consumer Credit (bn $, SA)",            "TOTALSL"),
        ("Revolving Credit (bn $, SA)",                 "REVOLSL"),
        ("Nonrevolving Credit (bn $, SA)",              "NONREVSL"),
    ],
    91: [  # Michigan Sentiment
        ("Consumer Sentiment Index",                    "UMCSENT"),
        ("5-Year Inflation Expectations (%)",           "MICH"),
    ],
    321: [  # Empire State Manufacturing
        ("NY Fed General Business Conditions",          "GAFDISA066MSFRBNY"),
    ],
    351: [  # Philly Fed Manufacturing
        ("Philly Fed Business Activity Index",          "GAPHIFRBPHI"),
    ],
    219: [  # CFNAI
        ("Chicago Fed National Activity Index",         "CFNAI"),
        ("CFNAI 3-Month Moving Average",                "CFNAIMA3"),
    ],
    221: [  # NFCI
        ("Chicago Fed National Financial Conditions",   "NFCI"),
        ("NFCI Credit Subindex",                        "NFCICREDIT"),
        ("NFCI Risk Subindex",                          "NFCIRISK"),
    ],
    191: [  # Senior Loan Officer Survey
        ("Net % Tightening C&I Loans — Large Firms",   "DRTSCILM"),
        ("Net % Tightening Credit Card Standards",      "DRTSCLCC"),
        ("Net % Tightening Mortgage Standards",         "DRTSSP500"),
    ],
    199: [  # Case-Shiller
        ("Case-Shiller US Home Price Index (SA)",       "CSUSHPISA"),
        ("Case-Shiller 20-City Composite (SA)",         "SPCS20RSA"),
    ],
    171: [  # FHFA HPI
        ("FHFA House Price Index (purchase-only, SA)",  "USSTHPI"),
    ],
    25: [  # Business Inventories
        ("Total Business Inventories/Sales Ratio",      "ISRATIO"),
        ("Manufacturing Inventories/Sales Ratio",       "MNFCTRIRSA"),
        ("Retail Inventories/Sales Ratio",              "RETAILIRSA"),
    ],
    290: [  # Wholesale Trade
        ("Wholesale Inventories (mn $, SA)",            "WHLSLRIMSA"),
        ("Wholesale Sales (mn $, SA)",                  "WHLSLRSMSA"),
    ],
    22: [  # H.8 Commercial Banks
        ("Commercial & Industrial Loans (bn $, SA)",    "BUSLOANS"),
        ("Real Estate Loans (bn $, SA)",                "REALLN"),
        ("Consumer Loans (bn $, SA)",                   "CONSUMER"),
        ("Total Deposits (bn $, SA)",                   "DPSACBW027SBOG"),
    ],
    21: [  # H.6 Money Stock
        ("M2 Money Stock (bn $, SA)",                   "M2SL"),
        ("M1 Money Stock (bn $, SA)",                   "M1SL"),
    ],
    323: [  # Trimmed Mean PCE
        ("12-Month Trimmed Mean PCE Inflation (%)",     "PCETRIM12M159SFRBDAL"),
        ("1-Month Trimmed Mean PCE Inflation (%)",      "PCETRIM1M158SFRBDAL"),
    ],
    179: [  # Quarterly E-Commerce
        ("E-Commerce Retail Sales (mn $, SA)",          "ECOMSA"),
        ("E-Commerce as % of Total Retail (%)",         "ECOMPCTSA"),
    ],
    435: [  # Advance Economic Indicators
        ("Advance Trade Balance in Goods (mn $, SA)",   "ADVANCETRADE"),
    ],
    374: [  # Texas Manufacturing
        ("Texas Manufacturing Business Activity",       "TXMFGBCINDX"),
    ],
    443: [  # Business Formation
        ("Business Applications Total (SA)",            "BABATOTALSAUS"),
        ("High-Propensity Business Applications (SA)",  "HBABATOTALSAUS"),
    ],
    190: [  # Freddie Mac Mortgage Survey
        ("30-Year Fixed Mortgage Rate (%)",             "MORTGAGE30US"),
        ("15-Year Fixed Mortgage Rate (%)",             "MORTGAGE15US"),
    ],
    231: [  # Charge-Off & Delinquency
        ("Credit Card Delinquency Rate (%)",            "DRCCLACBS"),
        ("Consumer Loan Delinquency Rate (%)",          "DRCONGACBS"),
        ("C&I Loan Delinquency Rate (%)",               "DRBLACBS"),
        ("Credit Card Charge-Off Rate (%)",             "CORCCACBS"),
    ],
    192: [  # JOLTS (Job Openings and Labor Turnover Survey)
        ("Job Openings (thousands, SA)", "JTSJOL"),
        ("Hires (thousands, SA)", "JTSHIL"),
        ("Quits (thousands, SA)", "JTSQUL"),
        ("Quits Rate (%, SA)", "JTSQUR"),
        ("Layoffs & Discharges Rate (%, SA)", "JTSLDR"),
    ],
    14: [  # G.19 Consumer Credit
        ("Total Consumer Credit (bn $, SA)", "TOTALSL"),
        ("Revolving Credit (bn $, SA)", "REVOLSL"),
        ("Nonrevolving Credit (bn $, SA)", "NONREVSL"),
    ],
    351: [  # Philly Fed: Use GACDFSA066MSFRBPHI for General Business Activity
        ("Philly Fed Business Activity Index", "GACDFSA066MSFRBPHI"),
        ("Philly Fed New Orders Index",        "NOBNDIF066MSFRBPHI"),
    ],
    374: [  # Dallas Fed: Use BACTSAMFRBDAL for General Business Activity
        ("Texas Mfg Business Activity Index", "BACTSAMFRBDAL"),
        ("Texas Mfg Outlook Index",           "TXMFGGTINDX"),
    ],
}

# Which 1-2 series to feature as inline charts per release.
# Falls back to the first 2 series in RELEASE_SERIES for unlisted releases.
CHART_SERIES = {
    50:  ["PAYEMS", "UNRATE"],
    10:  ["CPIAUCSL", "CPILFESL"],
    46:  ["PPIACO", "PPIFES"],
    54:  ["PCEPILFE", "PSAVERT"],
    53:  ["GDPC1"],
    9:   ["RSAFS", "RSFSXMV"],
    180: ["ICSA", "IC4WSA"],
    13:  ["INDPRO", "TCU"],
    192: ["JTSJOL", "JTSQUR"],
    194: ["ADPWNUSNERSA"],
    291: ["EXHOSLUSM495S"],
    97:  ["HSN1F", "MSPNHSUS"],
    27:  ["HOUST", "PERMIT"],
    95:  ["DGORDER", "NEWORDER"],
    51:  ["BOPGSTB"],
    11:  ["ECIALLCIV"],
    47:  ["OPHNFB", "ULCNFB"],
    91:  ["UMCSENT", "MICH"],
    219: ["CFNAI", "CFNAIMA3"],
    221: ["NFCI"],
    199: ["CSUSHPISA", "SPCS20RSA"],
    22:  ["BUSLOANS", "REALLN"],
    21:  ["M2SL"],
    323: ["PCETRIM12M159SFRBDAL"],
    190: ["MORTGAGE30US", "MORTGAGE15US"],
    231: ["DRCCLACBS", "CORCCACBS"],
    192: ["JTSJOL", "JTSQUR"],      # Track openings vs quits for labor tightness
    14:  ["REVOLSL", "NONREVSL"],   # Compare credit card vs auto/student loans
    351: ["GACDFSA066MSFRBPHI"],
    374: ["BACTSAMFRBDAL"],
}

SYSTEM_PROMPT = """\
You are an economist at a top investment bank. The user will provide you with \
a structured data summary of a recent US economic release. Read it carefully \
and produce a professional analyst-style note structured exactly as follows:

1. Executive Summary — 1-2 concise paragraphs outlining the overall tone and \
key policy signals.
2. Five Main Views — exactly five bullet points capturing the central messages.
3. Macro Characterization — one paragraph each on (i) growth, (ii) labor \
market, and (iii) inflation, reflecting how the data describes them.
4. Cyclical Alignment — Use the provided 10-year Z-scores and percentiles to \
classify the current regime. Identify if the print suggests a 'late-cycle' \
overheating, a 'mid-cycle' pause, or a structural 'regime shift.'
5. Policy Outlook — provide a reasoned forecast for the next Fed move (timing \
and direction), grounded in the data and balance of risks.

Style guidelines:
- Write in the tone of a sell-side economist's client note (tight, analytical, \
jargon-appropriate).
- Avoid generic filler; anchor every judgment in the numbers provided.
- Interpret Z-scores: A Z-score > |2.0| should be treated as a significant \
regime-defining event.
- Compute and reference month-on-month and year-on-year changes where relevant.\
"""

class CyclicalEngine:
    def __init__(self, api_key):
        self.api_key = api_key

    def get_metrics(self, series_id, lookback_years=10):
        """Computes regime-aware statistics: Z-score and Percentiles."""
        try:
            # Fetch 120 months for a decade-long baseline
            obs = fetch_series(series_id, self.api_key, limit=lookback_years * 12)
            values = [float(o['value']) for o in obs if o['value'] != "."]
            
            if len(values) < 2: return "Insufficient history."

            latest = values[-1]
            mean = np.mean(values)
            std = np.std(values)
            
            # Mathematical Magnitude (Z-score)
            z_score = (latest - mean) / std if std > 0 else 0
            # Historical Rarity (Percentile)
            percentile = (sum(1 for v in values if v <= latest) / len(values)) * 100

            return (
                f"10Y REGIME: {percentile:.1f}th Percentile | "
                f"Z-Score: {z_score:+.2f}σ | "
                f"10Y Range: [{min(values):,.2f}, {max(values):,.2f}]"
            )
        except Exception:
            return "Cyclical Data Unavailable."

# ---------------------------------------------------------------------------
# FRED helpers
# ---------------------------------------------------------------------------

def fred_get(endpoint: str, params: dict, api_key: str, retries: int = 3) -> dict:
    params = {"api_key": api_key, "file_type": "json", **params}
    for attempt in range(retries):
        resp = requests.get(f"{FRED_BASE}/{endpoint}", params=params, timeout=30)
        if resp.status_code < 500:
            resp.raise_for_status()
            return resp.json()
        wait = 2 ** attempt
        print(f"  FRED {resp.status_code} on {endpoint}, retrying in {wait}s "
              f"(attempt {attempt+1}/{retries}) ...", file=sys.stderr)
        time.sleep(wait)
    resp.raise_for_status()
    return resp.json()


# Releases that FRED does not register in its release calendar.
# For these, we detect updates by checking last_updated on a representative series.
CALENDAR_EXEMPT = {
    291: "EXHOSLUSM495S",  # Existing Home Sales — NAR; no FRED calendar entries
    351: "GACDFSA066MSFRBPHI", # Corrected Philly Fed
    374: "BACTSAMFRBDAL",      # Corrected Dallas Fed
}


def recent_release_ids(api_key: str, lookback_hours: int) -> set[int]:
    """Return FRED release IDs that published data in the last `lookback_hours`."""
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = fred_get("releases/dates", {
        "realtime_start": since,
        "realtime_end":   today,
        "limit":          1000,
        "include_release_dates_with_no_data": "false",
    }, api_key)
    found = {int(r["release_id"]) for r in data.get("release_dates", [])}

    # Fallback: for releases with no FRED calendar, check series last_updated.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    for release_id, series_id in CALENDAR_EXEMPT.items():
        try:
            meta = fred_get("series", {"series_id": series_id}, api_key)
            series = meta.get("seriess", [{}])[0]
            last_updated_str = series.get("last_updated", "")
            if last_updated_str:
                # FRED format: "2026-04-13 09:17:49-05:00" — parse offset-aware
                last_updated = datetime.fromisoformat(last_updated_str.replace(" ", "T"))
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=timezone.utc)
                if last_updated >= cutoff:
                    print(f"  Calendar-exempt release {release_id} detected via "
                          f"{series_id} last_updated={last_updated_str}", file=sys.stderr)
                    found.add(release_id)
        except Exception as e:
            print(f"  WARNING: calendar-exempt check failed for release {release_id} "
                  f"({series_id}): {e}", file=sys.stderr)

    return found


def fetch_series(series_id: str, api_key: str, limit: int = 13) -> list[dict]:
    data = fred_get("series/observations", {
        "series_id":  series_id,
        "sort_order": "desc",
        "limit":      limit,
    }, api_key)
    obs = [o for o in data.get("observations", []) if o["value"] != "."]
    return list(reversed(obs))

##original claude suggestion
# def build_data_block(release_id: int, release_name: str, api_key: str) -> str:
#     series_list = RELEASE_SERIES.get(release_id, [])
#     lines = [f"{release_name.upper()} — LATEST FRED DATA\n"]
#     seen = set()
#     for label, sid in series_list:
#         if sid in seen:
#             continue
#         seen.add(sid)
#         try:
#             obs = fetch_series(sid, api_key)
#         except Exception as e:
#             print(f"  WARNING: skipping {sid} — {e}", file=sys.stderr)
#             continue
#         if not obs:
#             continue
#         lines.append(f"{label}  [{sid}]")
#         for o in obs:
#             lines.append(f"  {o['date'][:7]}  {float(o['value']):>12.3f}")
#         lines.append("")
#     return "\n".join(lines)

def build_enhanced_data_block(release_id, release_name, api_key):
    engine = CyclicalEngine(api_key)
    series_list = RELEASE_SERIES.get(release_id, [])
    lines = [f"--- {release_name.upper()}: CYCLE-AWARE SUMMARY ---", ""]
    
    for label, sid in series_list:
        try:
            # Tactical Momentum (Last 13 months for MoM/YoY)
            tactical_obs = fetch_series(sid, api_key, limit=13)
            # Cyclical Context (10-year statistical distribution)
            cyclical_context = engine.get_metrics(sid)

            lines.append(f"SERIES: {label} [{sid}]")
            lines.append(f"CONTEXT: {cyclical_context}")
            lines.append("DATA:")
            for o in tactical_obs:
                lines.append(f"  {o['date'][:7]}  {float(o['value']):>12.3f}")
            lines.append("-" * 40)
        except Exception: continue
        
    return "\n".join(lines)

def build_chart_data(release_id: int, api_key: str, n_months: int = 24) -> list[dict]:
    """Fetch 1-2 featured series for inline Chart.js charts (24 months of history)."""
    sid_list = CHART_SERIES.get(release_id)
    if sid_list is None:
        sid_list = [sid for _, sid in RELEASE_SERIES.get(release_id, [])[:2]]
    label_map = {sid: label for label, sid in RELEASE_SERIES.get(release_id, [])}
    charts = []
    for sid in sid_list:
        try:
            obs = fetch_series(sid, api_key, limit=n_months)
        except Exception as e:
            print(f"  WARNING: chart series {sid} failed — {e}", file=sys.stderr)
            continue
        if not obs:
            continue
        charts.append({
            "label":     label_map.get(sid, sid),
            "series_id": sid,
            "dates":     [o["date"][:7] for o in obs],
            "values":    [float(o["value"]) for o in obs],
        })
    return charts


def generate_charts_html(chart_data: list[dict]) -> str:
    """Return an HTML snippet with Chart.js line charts for the featured series."""
    if not chart_data:
        return ""
    parts = []
    for i, cd in enumerate(chart_data):
        chart_id    = f"mu_chart_{i}"
        label_short = cd["label"].split("(")[0].strip()
        latest      = cd["values"][-1] if cd["values"] else None
        latest_str  = f"{latest:,.3f}".rstrip("0").rstrip(".") if latest is not None else ""
        dates_json  = json.dumps(cd["dates"])
        values_json = json.dumps(cd["values"])
        parts.append(f"""
        <div class="mu-chart-wrap">
            <div class="mu-chart-title">{label_short}
                <span class="mu-chart-latest">{latest_str}</span>
            </div>
            <canvas id="{chart_id}" height="120"></canvas>
            <script>
            (function(){{
                new Chart(document.getElementById('{chart_id}'), {{
                    type: 'line',
                    data: {{
                        labels: {dates_json},
                        datasets: [{{
                            data: {values_json},
                            borderColor: '#003366',
                            backgroundColor: 'rgba(0,51,102,0.07)',
                            borderWidth: 2,
                            pointRadius: 2.5,
                            pointHoverRadius: 5,
                            fill: true,
                            tension: 0.3
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            legend: {{ display: false }},
                            tooltip: {{
                                callbacks: {{
                                    label: function(c) {{
                                        return c.parsed.y.toLocaleString(undefined, {{maximumFractionDigits: 3}});
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{
                                ticks: {{ maxTicksLimit: 8, font: {{ size: 11 }} }},
                                grid: {{ display: false }}
                            }},
                            y: {{
                                ticks: {{
                                    font: {{ size: 11 }},
                                    callback: function(v) {{
                                        if (Math.abs(v) >= 1000000) return (v/1000000).toFixed(1)+'M';
                                        if (Math.abs(v) >= 1000)    return (v/1000).toFixed(0)+'K';
                                        return v.toLocaleString(undefined,{{maximumFractionDigits:2}});
                                    }}
                                }},
                                grid: {{ color: 'rgba(0,0,0,0.06)' }}
                            }}
                        }}
                    }}
                }});
            }})();
            </script>
        </div>""")
    grid_cols = "1fr 1fr" if len(parts) > 1 else "1fr"
    return f"""
    <div class="mu-charts" style="display:grid;grid-template-columns:{grid_cols};gap:24px;margin-bottom:32px;">
        {"".join(parts)}
    </div>"""


# ---------------------------------------------------------------------------
# Gemma inference
# ---------------------------------------------------------------------------

def generate_note(data_block: str, hf_token: str, retries: int = 5) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": (
            "Please analyze the following economic data and produce your economist note:\n\n"
            + data_block
        )},
    ]
    for attempt in range(retries):
        try:
            stream = client.chat.completions.create(
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
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
            is_rate_limit = "429" in str(e) or "Too Many Requests" in str(e)
            if is_rate_limit and attempt < retries - 1:
                wait = 60 * (attempt + 1)   # 60s, 120s, 180s, 240s
                print(f"\n  HF rate limit (429), waiting {wait}s before retry "
                      f"(attempt {attempt+1}/{retries}) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def markdown_to_html_body(md: str) -> str:
    """Minimal markdown → HTML for the analyst note sections."""
    import re
    lines = md.split("\n")
    html_parts = []
    in_ul = False

    for line in lines:
        # H3 ### or H2 ##
        if line.startswith("### "):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<h3>{line[4:].strip()}</h3>")
        elif line.startswith("## "):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<h2>{line[3:].strip()}</h2>")
        elif line.startswith("# "):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<h2>{line[2:].strip()}</h2>")
        # Numbered section headings like "1. Executive Summary"
        elif re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            title = re.sub(r"^\d+\.\s+\*\*(.+?)\*\*.*", r"\1", line)
            rest  = re.sub(r"^\d+\.\s+\*\*.+?\*\*\s*[—-]?\s*", "", line)
            html_parts.append(f'<h3 class="section-heading">{title}</h3>')
            if rest.strip():
                html_parts.append(f"<p>{_inline(rest)}</p>")
        # Bullet points
        elif line.strip().startswith("- ") or line.strip().startswith("* "):
            if not in_ul: html_parts.append("<ul>"); in_ul = True
            html_parts.append(f"<li>{_inline(line.strip()[2:])}</li>")
        # Blank line
        elif not line.strip():
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append("")
        else:
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<p>{_inline(line)}</p>")

    if in_ul:
        html_parts.append("</ul>")
    return "\n".join(html_parts)


def _inline(text: str) -> str:
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    return text


def get_ref_month(data_block: str) -> str:
    """Return the most recent YYYY-MM observation period found in a data block."""
    import re
    matches = re.findall(r"  (\d{4}-\d{2})  ", data_block)
    return max(matches) if matches else ""


def extract_ref_month_from_html(html_path: Path) -> str:
    """Read a report HTML and return its reference month (YYYY-MM)."""
    import re
    try:
        content = html_path.read_text(encoding="utf-8")
        # Fast path: meta tag written by render_html
        m = re.search(r'<meta name="reference-month" content="(\d{4}-\d{2})"', content)
        if m:
            return m.group(1)
        # Fallback: scan the raw data block for observation dates
        matches = re.findall(r"  (\d{4}-\d{2})  ", content)
        return max(matches) if matches else ""
    except Exception:
        return ""


def extract_release_date_from_html(html_path: Path) -> str:
    """Read a report HTML and return its release date (YYYY-MM-DD), or '' if absent."""
    import re
    try:
        content = html_path.read_text(encoding="utf-8")
        m = re.search(r'<meta name="release-date" content="(\d{4}-\d{2}-\d{2})"', content)
        return m.group(1) if m else ""
    except Exception:
        return ""


def fmt_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except Exception:
        return date_str


def fmt_month(month_str: str) -> str:
    try:
        return datetime.strptime(month_str + "-01", "%Y-%m-%d").strftime("%B %Y")
    except Exception:
        return month_str


def render_html(release_name: str, date_str: str, data_block: str, note_md: str,
                chart_data: list | None = None) -> str:
    note_html = markdown_to_html_body(note_md)
    # Extract key metrics for summary cards (latest value of first 3 series)
    card_html = ""
    lines = data_block.split("\n")
    cards = []
    current_label = None
    for line in lines:
        if "[" in line and "]" in line and not line.startswith(" "):
            current_label = line.split("[")[0].strip()
        elif line.startswith("  ") and current_label:
            parts = line.split()
            if len(parts) == 2:
                cards.append((current_label, parts[0], parts[1]))
                current_label = None
        if len(cards) == 4:
            break

    for label, period, value in cards:
        short = label.split("(")[0].strip()
        card_html += f"""
        <div class="card">
            <h3>{value}</h3>
            <p>{short}</p>
            <p class="card-period">{period}</p>
        </div>"""

    ref_month  = get_ref_month(data_block)
    charts_html = generate_charts_html(chart_data or [])
    chartjs_cdn = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>'
                   if charts_html else "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="reference-month" content="{ref_month}">
    <meta name="release-date" content="{date_str}">
    <title>{release_name} — {date_str}</title>
    {chartjs_cdn}
    <style>
        :root {{
            --fed-blue: #003366;
            --fed-gold: #b8860b;
            --light-bg: #f8f9fa;
            --border-color: #dee2e6;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #fff;
        }}
        header {{
            background: linear-gradient(135deg, var(--fed-blue) 0%, #004080 100%);
            color: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
        header h1 {{ font-size: 2rem; margin-bottom: 8px; }}
        header .subtitle {{ opacity: 0.9; font-size: 1.1rem; }}
        header .meta {{ opacity: 0.75; font-size: 0.9rem; margin-top: 6px; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: var(--light-bg);
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid var(--fed-blue);
        }}
        .card h3 {{ color: var(--fed-blue); font-size: 1.8rem; margin-bottom: 4px; }}
        .card p {{ color: #666; font-size: 0.85rem; }}
        .card .card-period {{ color: #999; font-size: 0.8rem; }}
        .note-body {{ max-width: 860px; }}
        .note-body h2 {{
            color: var(--fed-blue);
            border-bottom: 2px solid var(--fed-blue);
            padding-bottom: 8px;
            margin: 30px 0 15px;
            font-size: 1.3rem;
        }}
        .note-body h3 {{
            color: var(--fed-blue);
            margin: 25px 0 10px;
            font-size: 1.1rem;
        }}
        .note-body h3.section-heading {{
            background: var(--light-bg);
            border-left: 4px solid var(--fed-gold);
            padding: 8px 14px;
            border-radius: 0 4px 4px 0;
            margin: 28px 0 12px;
        }}
        .note-body p {{ margin-bottom: 12px; color: #444; }}
        .note-body ul {{ margin: 10px 0 16px 24px; }}
        .note-body li {{ margin-bottom: 6px; color: #444; }}
        .note-body strong {{ color: #222; }}
        .data-block {{
            background: #f4f6f9;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 20px;
            margin-top: 40px;
            font-family: 'SF Mono', 'Fira Code', monospace;
            font-size: 0.8rem;
            color: #555;
            white-space: pre;
            overflow-x: auto;
        }}
        .data-block summary {{
            font-family: inherit;
            font-size: 0.9rem;
            cursor: pointer;
            color: var(--fed-blue);
            margin-bottom: 12px;
            font-weight: 600;
        }}
        footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid var(--border-color);
            font-size: 0.85rem;
            color: #888;
        }}
        footer a {{ color: var(--fed-blue); }}
        .mu-chart-wrap {{
            background: var(--light-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px 20px 12px;
        }}
        .mu-chart-title {{
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--fed-blue);
            margin-bottom: 10px;
        }}
        .mu-chart-latest {{
            font-weight: 400;
            color: #555;
            margin-left: 8px;
        }}
    </style>
</head>
<body>
    <header>
        <h1>📊 {release_name}</h1>
        <div class="subtitle">Economist Analyst Note</div>
        <div class="meta">Generated {date_str} · Data: FRED · Model: Gemma 4 31B</div>
    </header>

    <div class="summary-cards">
        {card_html}
    </div>

    {charts_html}

    <div class="note-body">
        {note_html}
    </div>

    <details class="data-block">
        <summary>Raw data fed to model</summary>
{data_block}
    </details>

    <footer>
        <p>Data sourced from <a href="https://fred.stlouisfed.org">FRED</a> ·
        Analysis generated by <a href="https://huggingface.co/google/gemma-4-31B-it">Gemma 4 31B-IT</a> ·
        <a href="index.html">← All reports</a></p>
    </footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

def update_index(reports: list[dict]) -> None:
    """Regenerate the markets-update index.html from all HTML files in the dir."""
    existing = sorted(OUTPUT_DIR.glob("markets-update-*.html"), reverse=True)

    # existing is sorted newest-first, so the first file seen for a given
    # (slug, ref_month) is the most recently Generated — skip later duplicates.
    seen_keys:  set[tuple] = set()   # (slug, ref_month) dedup
    seen_fnames: set[str]  = set()
    rows = ""
    for f in existing:
        seen_fnames.add(f.name)
        name = f.stem  # e.g. markets-update-2026-04-07-employment-situation
        # split("-", 5) → ['markets','update','YYYY','MM','DD','slug...']
        parts = name.split("-", 5)
        if len(parts) >= 6:
            date_part = "-".join(parts[2:5])   # YYYY-MM-DD
            slug = parts[5]                     # employment-situation
        elif len(parts) == 5:
            date_part = "-".join(parts[2:5])
            slug = ""
        else:
            date_part = ""
            slug = ""

        release_title    = " ".join(w.capitalize() for w in slug.split("-")) if slug else name
        ref_month        = extract_ref_month_from_html(f)
        # Use release-date meta if present, otherwise fall back to filename date
        release_date_raw = extract_release_date_from_html(f) or date_part
        release_date_fmt = fmt_date(release_date_raw)
        generated_fmt    = fmt_date(date_part)
        ref_month_fmt    = fmt_month(ref_month) if ref_month else "—"

        dedup_key = (slug, ref_month)
        if dedup_key in seen_keys:
            print(f"  Index: skipping duplicate {f.name} (same report+ref_month, keeping newer)", file=sys.stderr)
            continue
        seen_keys.add(dedup_key)

        rows += (
            f'<tr>'
            f'<td><a href="{f.name}">{release_title}</a></td>'
            f'<td>{ref_month_fmt}</td>'
            f'<td>{release_date_fmt}</td>'
            f'<td>{generated_fmt}</td>'
            f'</tr>\n'
        )

    # Also include any just-generated reports not yet on disk when this runs
    for r in reports:
        fname = Path(r["path"]).name
        if fname in seen_fnames:
            continue
        release_title    = r.get("release_name", Path(r["path"]).stem)
        ref_month        = r.get("ref_month", "")
        ref_month_fmt    = fmt_month(ref_month) or "—"
        release_date_fmt = fmt_date(r.get("release_date", r["date"]))
        generated_fmt    = fmt_date(r["date"])

        stem_parts = Path(r["path"]).stem.split("-", 5)
        slug = stem_parts[5] if len(stem_parts) >= 6 else Path(r["path"]).stem
        dedup_key = (slug, ref_month)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        rows += (
            f'<tr>'
            f'<td><a href="{fname}">{release_title}</a></td>'
            f'<td>{ref_month_fmt}</td>'
            f'<td>{release_date_fmt}</td>'
            f'<td>{generated_fmt}</td>'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>US Markets Update — Archive</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 960px; margin: 40px auto; padding: 20px; color: #333; }}
        h1 {{ color: #003366; border-bottom: 2px solid #003366; padding-bottom: 10px; margin-bottom: 24px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #003366; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #dee2e6; }}
        td:nth-child(2), td:nth-child(3), td:nth-child(4) {{ white-space: nowrap; color: #555; font-size: 0.9rem; }}
        tr:hover {{ background: #f8f9fa; }}
        a {{ color: #003366; }}
        .meta {{ color: #888; font-size: 0.9rem; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h1>📊 US Markets Update</h1>
    <p class="meta">Daily analyst notes on major US economic releases. Generated by Gemma 4 31B via FRED data.</p>
    <table>
        <thead><tr><th>Report</th><th>Reference Month</th><th>Release Date</th><th>Generated</th></tr></thead>
        <tbody>
{rows}
        </tbody>
    </table>
</body>
</html>"""

    index_path = OUTPUT_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"  Index updated: {index_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    fred_key = os.environ.get("FRED_API_KEY")
    hf_token = os.environ.get("HF_TOKEN")

    if not fred_key:
        print("ERROR: FRED_API_KEY not set.", file=sys.stderr); sys.exit(1)
    if not hf_token:
        print("ERROR: HF_TOKEN not set.", file=sys.stderr); sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Checking FRED release calendar (last {LOOKBACK_HOURS}h) ...", file=sys.stderr)
    fired = recent_release_ids(fred_key, LOOKBACK_HOURS)
    matched = {rid: name for rid, name in RELEASE_WHITELIST.items() if rid in fired}

    if not matched:
        print("No whitelisted releases in the last 48h — nothing to do.", file=sys.stderr)
        sys.exit(0)

    print(f"Matched releases: {list(matched.values())}", file=sys.stderr)

    generated = []
    for release_id, release_name in matched.items():
        slug = release_name.split("(")[0].strip().lower().replace(" ", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        out_path = OUTPUT_DIR / f"markets-update-{today}-{slug}.html"

        if out_path.exists():
            print(f"  Already exists, skipping: {out_path.name}", file=sys.stderr)
            generated.append({"path": str(out_path), "date": today, "release_name": release_name,
                               "ref_month": extract_ref_month_from_html(out_path)})
            continue

        print(f"\n--- {release_name} ---", file=sys.stderr)
        print(f"  Fetching FRED series ...", file=sys.stderr)
        data_block = build_enhanced_data_block(release_id, release_name, fred_key)
        ref_month  = get_ref_month(data_block)

        # Skip generation if an existing file for this slug already covers the
        # same reference month (same release event published on a prior run).
        existing_for_slug = sorted(OUTPUT_DIR.glob(f"markets-update-*-{slug}.html"), reverse=True)
        dup_file = next((f for f in existing_for_slug
                         if extract_ref_month_from_html(f) == ref_month), None)
        if dup_file:
            print(f"  Duplicate: ref_month {ref_month} already covered by {dup_file.name} — skipping LLM call.",
                  file=sys.stderr)
            generated.append({"path": str(dup_file), "date": today, "release_name": release_name,
                               "ref_month": ref_month})
            continue

        chart_data = build_chart_data(release_id, fred_key)

        print(f"  Generating analyst note via {MODEL_ID} ...\n", file=sys.stderr)
        note_md = generate_note(data_block, hf_token)

        html = render_html(release_name, today, data_block, note_md, chart_data)
        out_path.write_text(html, encoding="utf-8")
        print(f"\n  Saved: {out_path}", file=sys.stderr)
        generated.append({
            "path":         str(out_path),
            "date":         today,
            "release_name": release_name,
            "ref_month":    ref_month,
        })

    update_index(generated)
    print(f"\nDone. {len(generated)} report(s) written.", file=sys.stderr)


if __name__ == "__main__":
    main()
