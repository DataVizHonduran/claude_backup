import os
import warnings
import requests
import pandas as pd
from typing import Optional, Union


BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BASE_URL_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"


def _period_to_date(year: str, period: str) -> pd.Timestamp:
    """Convert BLS year + period code to a Timestamp."""
    p = period.upper()
    if p.startswith("M"):          # M01 – M12 monthly
        month = int(p[1:])
        return pd.Timestamp(f"{year}-{month:02d}-01")
    if p.startswith("Q"):          # Q01 – Q04 quarterly
        quarter = int(p[1:])
        month = (quarter - 1) * 3 + 1
        return pd.Timestamp(f"{year}-{month:02d}-01")
    if p.startswith("A"):          # A01 annual
        return pd.Timestamp(f"{year}-01-01")
    if p.startswith("S"):          # S01 / S02 semi-annual
        half = int(p[1:])
        month = 1 if half == 1 else 7
        return pd.Timestamp(f"{year}-{month:02d}-01")
    # fallback
    return pd.Timestamp(f"{year}-01-01")


class BLSClient:
    """Thin wrapper around the BLS Public Data API (v2 with key, v1 fallback)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BLS_API_KEY")
        if not self.api_key:
            warnings.warn(
                "BLS_API_KEY not set — falling back to v1 (25 series max, 10yr history). "
                "Register free at https://data.bls.gov/registrationEngine/",
                stacklevel=2,
            )
        self.session = requests.Session()

    def _post(self, series_ids: list, start_year: str, end_year: str) -> list:
        payload = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if self.api_key:
            payload["registrationkey"] = self.api_key
            url = BASE_URL
        else:
            url = BASE_URL_V1

        r = self.session.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "")
        if status != "REQUEST_SUCCEEDED":
            msgs = data.get("message", [])
            raise ValueError(f"BLS API error ({status}): {msgs}")
        return data["Results"]["series"]

    def get_series(
        self,
        series_id: str,
        start_year: Union[str, int] = 2005,
        end_year: Union[str, int] = 2025,
    ) -> pd.Series:
        """Fetch a single BLS series. Returns DatetimeIndex pd.Series."""
        result = self._post([series_id], str(start_year), str(end_year))
        rows = result[0]["data"]
        records = {
            _period_to_date(r["year"], r["period"]): float(r["value"])
            for r in rows
            if r["value"] != "-"
        }
        s = pd.Series(records, name=series_id).sort_index()
        return s

    def get_multi(
        self,
        series_ids: list,
        start_year: Union[str, int] = 2005,
        end_year: Union[str, int] = 2025,
    ) -> pd.DataFrame:
        """
        Fetch multiple BLS series. Returns DatetimeIndex DataFrame, one col per series.
        v2 limit: 50 series per call. v1 limit: 25.
        """
        result = self._post(series_ids, str(start_year), str(end_year))
        frames = {}
        for series in result:
            sid = series["seriesID"]
            rows = series["data"]
            records = {
                _period_to_date(r["year"], r["period"]): float(r["value"])
                for r in rows
                if r["value"] != "-"
            }
            frames[sid] = pd.Series(records).sort_index()
        return pd.DataFrame(frames)
