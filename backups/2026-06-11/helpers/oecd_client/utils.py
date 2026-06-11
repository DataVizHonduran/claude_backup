"""Parsing helpers for OECD SDMX CSV responses."""
from io import StringIO

import pandas as pd


def parse_csv_response(text: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(text))
    if "TIME_PERIOD" in df.columns:
        df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"], format="mixed")
        df = df.set_index("TIME_PERIOD").sort_index()
    return df
