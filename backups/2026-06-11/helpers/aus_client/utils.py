"""Parsers: ABS SDMX-JSON 2.0 → tidy DataFrame, RBA statistical-table CSV → DataFrame."""
import csv
import io

import pandas as pd


def sdmx_json_to_df(response: dict) -> pd.DataFrame:
    """Parse an ABS SDMX-JSON 2.0 data message into a tidy DataFrame.

    Series keys (e.g. "0:1:0:0:0") are positionally decoded against
    data.structures[0].dimensions.series; observation keys against
    dimensions.observation[0] (TIME_PERIOD). Returns one row per
    (series dims..., TIME_PERIOD, value), DatetimeIndex on TIME_PERIOD.
    """
    data = response["data"]
    structure = data["structures"][0]
    series_dims = structure["dimensions"]["series"]
    time_values = structure["dimensions"]["observation"][0]["values"]

    rows = []
    for series_key, series_obj in data["dataSets"][0]["series"].items():
        idxs = [int(i) for i in series_key.split(":")]
        dim_codes = {
            dim["id"]: dim["values"][idx]["id"]
            for dim, idx in zip(series_dims, idxs)
        }
        for obs_idx, obs_val in series_obj["observations"].items():
            row = dict(dim_codes)
            row["TIME_PERIOD"] = time_values[int(obs_idx)]["id"]
            row["value"] = float(obs_val[0])
            rows.append(row)

    df = pd.DataFrame(rows)
    df["TIME_PERIOD"] = _parse_time_period(df["TIME_PERIOD"])
    return df.set_index("TIME_PERIOD").sort_index()


def _parse_time_period(series: pd.Series) -> pd.DatetimeIndex:
    """Parse ABS TIME_PERIOD strings: annual (2020), quarterly (2020-Q1), monthly (2020-01)."""
    sample = series.iloc[0]
    if "-Q" in sample:
        return pd.PeriodIndex(series.str.replace("-Q", "Q"), freq="Q").to_timestamp()
    if len(sample) == 4:
        return pd.to_datetime(series, format="%Y")
    return pd.to_datetime(series)


def parse_rba_csv(raw_text: str) -> pd.DataFrame:
    """Parse an RBA statistical-table CSV (e.g. f1-data.csv) into a DataFrame.

    Skips the metadata header block (Title/Description/Frequency/Type/Units/
    Source/Publication date), uses the "Series ID" row as column names, and
    parses the leading date column (mixes "04-Jan-2011" and "30/06/1922"
    formats, so dayfirst=True).
    """
    rows = list(csv.reader(io.StringIO(raw_text)))
    header_idx = next(i for i, r in enumerate(rows) if r and r[0] == "Series ID")
    columns = rows[header_idx][1:]

    dates, values = [], []
    for r in rows[header_idx + 1:]:
        if not r or not r[0].strip():
            continue
        dates.append(r[0])
        padded = (r[1:1 + len(columns)] + [""] * len(columns))[:len(columns)]
        values.append(padded)

    df = pd.DataFrame(values, columns=columns)
    df = df.apply(pd.to_numeric, errors="coerce")
    df.index = pd.to_datetime(dates, dayfirst=True)
    df.index.name = "Date"
    return df.sort_index()
