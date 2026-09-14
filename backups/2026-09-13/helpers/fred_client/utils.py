"""Data cleaning and alignment utilities."""
import logging

import pandas as pd

logger = logging.getLogger("fred_client.utils")


def clean_and_align(df: pd.DataFrame, freq: str = "MS") -> pd.DataFrame:
    """Convert, coerce, and resample a FRED DataFrame to a consistent frequency.

    Args:
        df: Raw DataFrame with a date-like index and string/object value columns.
        freq: Pandas offset alias for target frequency (default ``"MS"`` = month start).

    Returns:
        DataFrame with DatetimeIndex and numeric columns resampled to ``freq``.
    """
    df = df.copy()
    df.index = pd.to_datetime(df.index, errors="coerce")

    invalid = df.index.isna().sum()
    if invalid:
        logger.warning("Dropped %d rows with unparseable dates", invalid)
        df = df[df.index.notna()]

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.resample(freq).last()
    logger.debug("Aligned to freq=%s → %d rows", freq, len(df))
    return df
