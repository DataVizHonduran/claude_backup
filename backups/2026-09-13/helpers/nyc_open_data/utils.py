"""Type coercion helpers for SODA DataFrames."""
from typing import Optional

import pandas as pd


def coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Cast columns to numeric, silently converting unparseable values to NaN."""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def coerce_datetime(
    df: pd.DataFrame,
    col: str,
    fmt: Optional[str] = None,
    as_index: bool = False,
) -> pd.DataFrame:
    """Parse a column as datetime.

    Args:
        df: Input DataFrame.
        col: Column to parse.
        fmt: strptime format string. None = infer.
        as_index: If True, set the parsed column as the DataFrame index.

    Returns:
        DataFrame with the column cast to datetime64.
    """
    df[col] = pd.to_datetime(df[col], format=fmt, errors="coerce")
    if as_index:
        df = df.set_index(col).sort_index()
    return df
