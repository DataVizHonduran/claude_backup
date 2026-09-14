"""JSON-stat 2.0 parser → tidy pandas DataFrame."""
import itertools
import logging

import pandas as pd

logger = logging.getLogger("eurostat_client.utils")


_TIME_DIM_NAMES = {"TIME_PERIOD", "time", "TIME"}


def jsonstat_to_df(response: dict) -> pd.DataFrame:
    """Parse a Eurostat JSON-stat 2.0 response into a tidy DataFrame.

    Handles both dense (list) and sparse (dict) value representations.
    TIME_PERIOD / time dimension is parsed to a DatetimeIndex. None values
    are dropped.
    """
    ids = response["id"]        # dimension order
    sizes = response["size"]    # codes per dimension
    dims = response["dimension"]
    raw_values = response["value"]

    # Normalise: sparse dict {str_idx: val} → lookup by int; list → index directly
    if isinstance(raw_values, dict):
        value_lookup: dict[int, float] = {int(k): v for k, v in raw_values.items()}
        def _get(i: int):
            return value_lookup.get(i)
    else:
        def _get(i: int):
            return raw_values[i] if i < len(raw_values) else None

    # Build ordered code list per dimension
    dim_codes: list[list[str]] = []
    for dim_id in ids:
        cat = dims[dim_id]["category"]
        pos_to_code = {v: k for k, v in cat["index"].items()}
        dim_codes.append([pos_to_code[i] for i in range(len(pos_to_code))])

    # Map flat index → dimension combo, skip nulls
    rows = []
    for flat_idx, combo in enumerate(itertools.product(*dim_codes)):
        val = _get(flat_idx)
        if val is None:
            continue
        row = dict(zip(ids, combo))
        row["value"] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    time_col = next((c for c in df.columns if c in _TIME_DIM_NAMES), None)
    if time_col:
        df[time_col] = _parse_time_period(df[time_col])
        df = df.set_index(time_col).sort_index()
        df.index.name = "TIME_PERIOD"

    logger.debug("jsonstat_to_df: %d rows, dims=%s", len(df), ids)
    return df


def _parse_time_period(series: pd.Series) -> pd.DatetimeIndex:
    """Parse Eurostat TIME_PERIOD strings to Timestamps.

    Handles annual (2020), quarterly (2020-Q1), and monthly (2020-01) formats.
    """
    sample = series.iloc[0]
    if "-Q" in sample:
        # 2020-Q1 → 2020Q1 → period → timestamp (quarter start)
        return pd.PeriodIndex(series.str.replace("-Q", "Q"), freq="Q").to_timestamp()
    if len(sample) == 4:
        return pd.to_datetime(series, format="%Y")
    return pd.to_datetime(series)


def infer_freq(series: pd.Series) -> str:
    """Infer time frequency from a DatetimeIndex series: 'A', 'Q', or 'M'."""
    idx = series.index
    if len(idx) < 2:
        return "unknown"
    delta = (idx[1] - idx[0]).days
    if delta > 300:
        return "A"
    if delta > 60:
        return "Q"
    return "M"
