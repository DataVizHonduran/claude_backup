"""
Daily SP500 earnings screener via api-ninjas.com.
Selects 30 random tickers, fetches transcripts, keeps those within last 45 days,
saves to earnings-recaps/ninja/ and pushes to GitHub.
"""

import os
import random
import time
import subprocess
import sys
from datetime import date, timedelta

import requests

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.environ.get("API_NINJAS_KEY", "")
REPO_URL = "git@github.com:DataVizHonduran/earnings-recaps.git"
LOCAL_REPO = os.path.expanduser("~/claude_projects/earnings-recaps")
NINJA_DIR = os.path.join(LOCAL_REPO, "ninja")
WINDOW_DAYS = 45
SAMPLE_SIZE = 30
SLEEP_SEC = 0.35  # ~50 req/min free-tier headroom

# ── SP500 tickers (static list, May 2026) ─────────────────────────────────────
SP500_TICKERS = (
    "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
    "APD", "ABNB", "AKAM", "ALB", "ARE", "ALGN", "ALLE", "LNT", "ALL", "GOOGL",
    "GOOG", "MO", "AMZN", "AMCR", "AEE", "AAL", "AEP", "AXP", "AIG", "AMT",
    "AWK", "AMP", "AME", "AMGN", "APH", "ADI", "ANSS", "AON", "APA", "AAPL",
    "AMAT", "APTV", "ACGL", "ADM", "ANET", "AJG", "AIZ", "T", "ATO", "ADSK",
    "AZO", "AVB", "AVY", "AXON", "BKR", "BALL", "BAC", "BAX", "BDX", "WRB",
    "BRK-B", "BBY", "BIO", "TECH", "BIIB", "BLK", "BX", "BA", "BCR", "BKNG",
    "BWA", "BSX", "BMY", "AVGO", "BR", "BRO", "BF-B", "BLDR", "BG", "CDNS",
    "CZR", "CPT", "CPB", "COF", "CAH", "KMX", "CCL", "CARR", "CTLT", "CAT",
    "CBOE", "CBRE", "CDW", "CE", "COR", "CNC", "CNX", "CDAY", "CF", "CRL",
    "SCHW", "CHTR", "CVX", "CMG", "CB", "CHD", "CI", "CINF", "CTAS", "CSCO",
    "C", "CFG", "CLX", "CME", "CMS", "KO", "CTSH", "CL", "CMCSA", "CAG",
    "COP", "ED", "STZ", "CEG", "COO", "CPRT", "GLW", "CPAY", "CTVA", "CSGP",
    "COST", "CTRA", "CCI", "CSX", "CMI", "CVS", "DHR", "DRI", "DVA", "DAY",
    "DE", "DAL", "DVN", "DXCM", "FANG", "DLR", "DFS", "DG", "DLTR", "D",
    "DPZ", "DOV", "DOW", "DHI", "DTE", "DUK", "DD", "EMN", "ETN", "EBAY",
    "ECL", "EIX", "EW", "EA", "ELV", "LLY", "EMR", "ENPH", "ETR", "EOG",
    "EPAM", "EQT", "EFX", "EQIX", "EQR", "ESS", "EL", "ETSY", "EG", "EVRG",
    "ES", "EXC", "EXPE", "EXPD", "EXR", "XOM", "FFIV", "FDS", "FICO", "FAST",
    "FRT", "FDX", "FIS", "FITB", "FSLR", "FE", "FI", "FLT", "FMC", "F",
    "FTNT", "FTV", "FOXA", "FOX", "BEN", "FCX", "GRMN", "IT", "GE", "GEHC",
    "GEV", "GEN", "GNRC", "GD", "GIS", "GM", "GPC", "GILD", "GS", "HAL",
    "HIG", "HAS", "HCA", "DOC", "HSIC", "HSY", "HES", "HPE", "HLT", "HOLX",
    "HD", "HON", "HRL", "HST", "HWM", "HPQ", "HUBB", "HUM", "HBAN", "HII",
    "IBM", "IEX", "IDXX", "ITW", "INCY", "IR", "PODD", "INTC", "ICE", "IFF",
    "IP", "IPG", "INTU", "ISRG", "IVZ", "INVH", "IQV", "IRM", "JBHT", "JBL",
    "JKHY", "J", "JNJ", "JCI", "JPM", "JNPR", "K", "KVUE", "KDP", "KEY",
    "KEYS", "KMB", "KIM", "KMI", "KLAC", "KHC", "KR", "LHX", "LH", "LRCX",
    "LW", "LVS", "LDOS", "LEN", "LIN", "LYV", "LKQ", "LMT", "L", "LOW",
    "LULU", "LYB", "MTB", "MRO", "MPC", "MKTX", "MAR", "MMC", "MLM", "MAS",
    "MA", "MTCH", "MKC", "MCD", "MCK", "MDT", "MRK", "META", "MET", "MTD",
    "MGM", "MCHP", "MU", "MSFT", "MAA", "MRNA", "MHK", "MOH", "TAP", "MDLZ",
    "MPWR", "MNST", "MCO", "MS", "MOS", "MSI", "MSCI", "NDAQ", "NTAP", "NFLX",
    "NEM", "NWSA", "NWS", "NEE", "NKE", "NI", "NDSN", "NSC", "NTRS", "NOC",
    "NCLH", "NRG", "NUE", "NVR", "NVDA", "NWL", "NXPI", "ORLY", "OXY", "ODFL",
    "OMC", "ON", "OKE", "ORCL", "OTIS", "PCAR", "PKG", "PLTR", "PANW", "PARA",
    "PH", "PAYX", "PAYC", "PYPL", "PNR", "PEP", "PFE", "PCG", "PM", "PSX",
    "PNW", "PNC", "POOL", "PPG", "PPL", "PFG", "PG", "PGR", "PLD", "PRU",
    "PEG", "PTC", "PSA", "PHM", "QRVO", "PWR", "QCOM", "DGX", "RL", "RJF",
    "RTX", "O", "REG", "REGN", "RF", "RSG", "RMD", "RVTY", "ROL", "ROP",
    "ROST", "RCL", "SPGI", "CRM", "SBAC", "SLB", "STX", "SRE", "NOW", "SHW",
    "SPG", "SWKS", "SJM", "SW", "SNA", "SOLV", "SO", "LUV", "SWK", "SBUX",
    "STT", "STLD", "STE", "SYK", "SMCI", "SYF", "SNPS", "SYY", "TMUS", "TROW",
    "TTWO", "TPR", "TRGP", "TGT", "TEL", "TDY", "TFX", "TER", "TSLA", "TXN",
    "TXT", "TMO", "TJX", "TSCO", "TT", "TDG", "TRV", "TRMB", "TFC", "TYL",
    "TSN", "USB", "UBER", "UDR", "ULTA", "UNP", "UAL", "UPS", "URI", "UNH",
    "UHS", "VLO", "VTR", "VLTO", "VRSN", "VRSK", "VZ", "VRTX", "VTRS", "VICI",
    "V", "VST", "VMC", "WRK", "WAB", "WBA", "WMT", "DIS", "WBD", "WM", "WAT",
    "WEC", "WFC", "WELL", "WST", "WDC", "WY", "WHR", "WMB", "WTW", "GWW",
    "WYNN", "XEL", "XYL", "YUM", "ZBRA", "ZBH", "ZTS",
)

# ── Quarter → estimated report date ──────────────────────────────────────────
QUARTER_MONTH = {1: (0, 5, 1), 2: (0, 8, 1), 3: (0, 11, 1), 4: (1, 2, 1)}
# offset_years, month, day


def estimated_report_date(year: int, quarter: int) -> date:
    yr_off, mo, day = QUARTER_MONTH.get(quarter, (0, 5, 1))
    return date(year + yr_off, mo, day)


def within_window(year: int, quarter: int) -> bool:
    cutoff = date.today() - timedelta(days=WINDOW_DAYS)
    return estimated_report_date(year, quarter) >= cutoff


# ── Repo bootstrap ────────────────────────────────────────────────────────────
def ensure_repo():
    if not os.path.isdir(LOCAL_REPO):
        print(f"Cloning {REPO_URL} ...")
        subprocess.run(["git", "clone", REPO_URL, LOCAL_REPO], check=True)
    else:
        subprocess.run(["git", "-C", LOCAL_REPO, "pull", "--rebase"], check=True)
    os.makedirs(NINJA_DIR, exist_ok=True)


# ── API call ──────────────────────────────────────────────────────────────────
def fetch_transcript(ticker: str) -> dict | None:
    url = "https://api.api-ninjas.com/v1/earningstranscript"
    try:
        r = requests.get(
            url,
            params={"ticker": ticker},
            headers={"X-Api-Key": API_KEY},
            timeout=15,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        # API may return a list or a dict
        if isinstance(data, list):
            return data[0] if data else None
        return data if data else None
    except Exception as e:
        print(f"  [{ticker}] error: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not API_KEY:
        sys.exit("API_NINJAS_KEY env var not set")

    ensure_repo()

    tickers = random.sample(SP500_TICKERS, SAMPLE_SIZE)
    today_str = date.today().isoformat()
    saved = []

    print(f"\n{today_str} — screening {SAMPLE_SIZE} random SP500 tickers\n")

    for ticker in tickers:
        time.sleep(SLEEP_SEC)
        data = fetch_transcript(ticker)

        if not data:
            print(f"  {ticker:6s}  no data")
            continue

        year = data.get("year") or data.get("fiscal_year")
        quarter = data.get("quarter") or data.get("fiscal_quarter")
        company = data.get("company", ticker)
        transcript = data.get("transcript", "")

        if not year or not quarter or not transcript:
            print(f"  {ticker:6s}  missing fields (year={year}, q={quarter}, len={len(transcript)})")
            continue

        year, quarter = int(year), int(quarter)
        est_date = estimated_report_date(year, quarter)
        in_window = within_window(year, quarter)

        print(f"  {ticker:6s}  {year} Q{quarter}  est={est_date}  {'✓ IN WINDOW' if in_window else '✗ too old'}")

        if not in_window:
            continue

        fname = f"{ticker}_{year}_Q{quarter}.txt"
        fpath = os.path.join(NINJA_DIR, fname)

        if os.path.exists(fpath):
            print(f"         already saved, skipping")
            continue

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"Ticker: {ticker}\n")
            f.write(f"Company: {company}\n")
            f.write(f"Year: {year}\n")
            f.write(f"Quarter: {quarter}\n")
            f.write(f"Estimated Report Date: {est_date}\n\n")
            f.write(transcript)

        print(f"         saved → ninja/{fname}")
        saved.append(fname)

    print(f"\nSaved {len(saved)} transcript(s) today.")

    if saved:
        subprocess.run(["git", "-C", LOCAL_REPO, "add", "ninja/"], check=True)
        msg = f"ninja: {today_str} — {len(saved)} transcript(s) added"
        subprocess.run(["git", "-C", LOCAL_REPO, "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", LOCAL_REPO, "pull", "--rebase"], check=True)
        subprocess.run(["git", "-C", LOCAL_REPO, "push"], check=True)
        print("Pushed to GitHub.")
    else:
        print("Nothing to push.")


if __name__ == "__main__":
    main()
