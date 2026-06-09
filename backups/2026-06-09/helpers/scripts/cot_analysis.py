"""
CFTC Commitments of Traders (COT) Analysis
Supports: Traders in Financial Futures (TFF) and Disaggregated reports
Output: tidy DataFrame [Date, Market, Sector, Category, Net_Position, Position_Pct_OI]
"""

import warnings
import pandas as pd
import cot_reports as cot

# ── Sector → keyword lookup (matched against Market_and_Exchange_Names) ──────
SECTOR_KEYWORDS = {
    "Currencies": ["EURO FX", "JAPANESE YEN", "BRITISH POUND", "SWISS FRANC",
                   "CANADIAN DOLLAR", "AUSTRALIAN DOLLAR", "NZ DOLLAR", "MEXICAN PESO",
                   "BRAZILIAN REAL", "KOREAN WON"],
    "Rates":      ["T-BONDS", "T-NOTES", "FED FUNDS", "EURODOLLAR", "SOFR",
                   "TREASURY", "INTEREST RATE"],
    "Equities":   ["S&P 500", "S&P-500", "NASDAQ", "DOW JONES", "RUSSELL",
                   "NIKKEI", "VIX", "E-MINI"],
    "Commodities": ["CRUDE OIL", "NATURAL GAS", "GOLD", "SILVER", "COPPER",
                    "CORN", "WHEAT", "SOYBEANS", "COFFEE", "SUGAR", "COTTON",
                    "LEAN HOGS", "LIVE CATTLE", "COCOA"],
}

# ── Trader category definitions per report type ───────────────────────────────
# Each entry: (long_col, short_col, classification_label)
# Note: CFTC Disaggregated has an asymmetric naming quirk — Swap long uses
# single underscore prefix while short uses double underscore.
TFF_CATEGORIES = [
    ("Dealer_Positions_Long_All",    "Dealer_Positions_Short_All",    "Commercial"),
    ("Asset_Mgr_Positions_Long_All", "Asset_Mgr_Positions_Short_All", "Speculator"),
    ("Lev_Money_Positions_Long_All", "Lev_Money_Positions_Short_All", "Speculator"),
    ("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All","Other"),
]

DISAGG_CATEGORIES = [
    ("Prod_Merc_Positions_Long_All", "Prod_Merc_Positions_Short_All", "Commercial"),
    ("Swap_Positions_Long_All",      "Swap__Positions_Short_All",     "Commercial"),
    ("M_Money_Positions_Long_All",   "M_Money_Positions_Short_All",   "Speculator"),
    ("Other_Rept_Positions_Long_All","Other_Rept_Positions_Short_All","Other"),
]

REPORT_CATEGORIES = {
    "traders_in_financial_futures_fut": TFF_CATEGORIES,
    "disaggregated_futopt":             DISAGG_CATEGORIES,
}

# Sectors → which COT report to use
SECTOR_REPORT = {
    "Currencies": "traders_in_financial_futures_fut",
    "Rates":      "traders_in_financial_futures_fut",
    "Equities":   "traders_in_financial_futures_fut",
    "Commodities":"disaggregated_futopt",
}


def fetch_cot_data(report_type: str, start_year: int, end_year: int) -> pd.DataFrame:
    """Download COT data for a range of years and concat into one DataFrame."""
    frames = []
    for yr in range(start_year, end_year + 1):
        try:
            df = cot.cot_year(year=yr, cot_report_type=report_type,
                              store_txt=False, verbose=False)
            frames.append(df)
        except Exception as exc:
            warnings.warn(f"Could not fetch {report_type} for {yr}: {exc}")
    if not frames:
        raise RuntimeError(f"No data fetched for {report_type} {start_year}–{end_year}")
    return pd.concat(frames, ignore_index=True)


def filter_by_sector(df: pd.DataFrame, sector: str) -> pd.DataFrame:
    """Keep rows whose market name contains any sector keyword (case-insensitive)."""
    keywords = SECTOR_KEYWORDS.get(sector, [])
    if not keywords:
        return df
    mask = df["Market_and_Exchange_Names"].str.upper().str.contains(
        "|".join(keywords), na=False
    )
    return df[mask].copy()


def _resolve_date(df: pd.DataFrame) -> pd.Series:
    """Return a normalized datetime Series.

    Prefers Report_Date_as_YYYY-MM-DD (already ISO); falls back to
    As_of_Date_In_Form_YYMMDD which CFTC stores as a 6-digit integer YYMMDD.
    """
    if "Report_Date_as_YYYY-MM-DD" in df.columns:
        return pd.to_datetime(df["Report_Date_as_YYYY-MM-DD"], errors="coerce")
    if "As_of_Date_In_Form_YYMMDD" in df.columns:
        return pd.to_datetime(
            df["As_of_Date_In_Form_YYMMDD"].astype(str).str.zfill(6),
            format="%y%m%d", errors="coerce"
        )
    raise KeyError("No recognized date column found in COT data.")


def clean_and_unify(df: pd.DataFrame, report_type: str) -> pd.DataFrame:
    """
    Normalize column names, parse dates, drop fully-null columns.
    Warns if expected trader columns are missing — this typically indicates
    data predating 2006, when the TFF and Disaggregated formats were introduced.
    """
    df = df.copy()
    df.columns = df.columns.str.strip()
    df.dropna(axis=1, how="all", inplace=True)

    df["Date"] = _resolve_date(df)

    expected = {c for triple in REPORT_CATEGORIES[report_type] for c in triple[:2]}
    missing = expected - set(df.columns)
    if missing:
        warnings.warn(
            f"Missing expected columns for {report_type}: {missing}. "
            "This may indicate pre-2006 data or a report definition change."
        )
    return df


def _safe_col(df: pd.DataFrame, col: str) -> pd.Series:
    """Return column as numeric, or zeros if the column is absent."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0)
    return pd.Series(0.0, index=df.index)


def calculate_positions(df: pd.DataFrame, report_type: str) -> pd.DataFrame:
    """
    Aggregate long/short positions per trader classification and compute:
      Net_Position    = total longs − total shorts  (for the classification)
      Position_Pct_OI = Net_Position / Open_Interest_All × 100

    Non-Reportable positions are the residual:
        NonRept = Open_Interest_All − (sum of all Reportable Long or Short positions)
    CFTC derives this implicitly; it represents small traders below reporting thresholds.
    The COT file includes NonRept_Positions_Long_All and _Short_All for convenience,
    but always use Open_Interest_All (not a sub-sum) as the % OI denominator to ensure
    the denominator is mathematically sound and internally consistent.

    Multiple entries with the same label (e.g., Prod_Merc + Swap both → "Commercial")
    are accumulated and emitted as a single row, so the output has exactly one row per
    (Date, Market, Category) combination.
    """
    categories = REPORT_CATEGORIES[report_type]
    oi = pd.to_numeric(df["Open_Interest_All"], errors="coerce").fillna(0)

    # Accumulate net positions by label
    accum: dict[str, pd.Series] = {}
    for long_col, short_col, label in categories:
        net = _safe_col(df, long_col) - _safe_col(df, short_col)
        accum[label] = accum.get(label, pd.Series(0.0, index=df.index)) + net

    rows = []
    for label, net in accum.items():
        pct = net / oi.replace(0, float("nan")) * 100
        rows.append(df[["Date", "Market_and_Exchange_Names"]].assign(
            Category=label,
            Net_Position=net,
            Position_Pct_OI=pct,
        ))

    return pd.concat(rows, ignore_index=True)


def build_output(df: pd.DataFrame, report_type: str) -> pd.DataFrame:
    """Clean → calculate → return tidy [Date, Market, Category, Net_Position, Position_Pct_OI]."""
    df = clean_and_unify(df, report_type)
    result = calculate_positions(df, report_type)
    result = result.rename(columns={"Market_and_Exchange_Names": "Market"})
    result = result[["Date", "Market", "Category", "Net_Position", "Position_Pct_OI"]]
    result.sort_values(["Market", "Date", "Category"], inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


def main(
    sectors: list[str] | None = None,
    start_year: int = 2010,
    end_year: int = 2024,
) -> pd.DataFrame:
    """
    Fetch, process, and return COT positioning data for the requested sectors.

    TFF report used for: Currencies, Rates, Equities
    Disaggregated report used for: Commodities
    """
    if start_year < 2007:
        warnings.warn(
            "TFF and Disaggregated reports begin in 2006. "
            "Pre-2007 requests will fall back to whatever CFTC has available "
            "and may lack full trader-category breakdowns."
        )

    if sectors is None:
        sectors = list(SECTOR_REPORT.keys())

    # Group sectors by required report type to minimize redundant downloads
    report_to_sectors: dict[str, list[str]] = {}
    for sector in sectors:
        rtype = SECTOR_REPORT[sector]
        report_to_sectors.setdefault(rtype, []).append(sector)

    output_frames = []
    for report_type, sector_list in report_to_sectors.items():
        raw = fetch_cot_data(report_type, start_year, end_year)
        for sector in sector_list:
            filtered = filter_by_sector(raw, sector)
            if filtered.empty:
                warnings.warn(f"No rows matched for sector '{sector}' in {report_type}")
                continue
            processed = build_output(filtered, report_type)
            processed.insert(2, "Sector", sector)
            output_frames.append(processed)

    if not output_frames:
        raise RuntimeError("No data produced. Check sector names and year range.")

    final = pd.concat(output_frames, ignore_index=True)
    final.sort_values(["Sector", "Market", "Date", "Category"], inplace=True)
    final.reset_index(drop=True, inplace=True)
    return final


if __name__ == "__main__":
    df = main(sectors=["Currencies", "Equities", "Commodities"], start_year=2020, end_year=2024)
    print(df.head(20).to_string())
    print(f"\nShape: {df.shape}")
    print(f"\nSectors: {df['Sector'].unique()}")
    print(f"Categories: {df['Category'].unique()}")
    print(f"\nPosition_Pct_OI range: {df['Position_Pct_OI'].min():.1f}% to {df['Position_Pct_OI'].max():.1f}%")

    # Spot-check: zero-sum identity per (Date, Market)
    # Commercial + Speculator + Other + NonRept ≈ 0 (within rounding)
    # We omit NonRept from our output, so the residual here represents it.
    check = df.groupby(["Date", "Market"])["Net_Position"].sum()
    max_residual = check.abs().max()
    print(f"\nMax residual (excl. NonRept) per date/market: {max_residual:,.0f} contracts")
