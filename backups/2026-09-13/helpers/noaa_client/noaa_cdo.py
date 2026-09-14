import os
import time
import warnings
import requests
import pandas as pd
from typing import Optional, Union

BASE_URL = "https://www.ncdc.noaa.gov/cdo-web/api/v2"


class NOAAClient:
    """Wrapper around the NOAA Climate Data Online (CDO) API v2."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("NOAA_CDO_TOKEN")
        if not self.token:
            warnings.warn(
                "NOAA_CDO_TOKEN not set — register free at https://www.ncdc.noaa.gov/cdo-web/token",
                stacklevel=2,
            )
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({"token": self.token})

    def _get(self, endpoint: str, params: dict) -> dict:
        r = self.session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_data(
        self,
        dataset: str,
        station_ids: Union[str, list],
        datatype_ids: Union[str, list],
        start: str,
        end: str,
        units: str = "standard",
    ) -> pd.DataFrame:
        """Fetch CDO observations with automatic pagination.

        Args:
            dataset: 'GHCND' (daily) or 'GSOM' (monthly summary)
            station_ids: single station ID or list
            datatype_ids: e.g. ['TMAX', 'TMIN', 'PRCP'] or 'PRCP'
            start: 'YYYY-MM-DD'
            end: 'YYYY-MM-DD'
            units: 'standard' or 'metric'
        """
        if isinstance(station_ids, str):
            station_ids = [station_ids]
        if isinstance(datatype_ids, str):
            datatype_ids = [datatype_ids]

        params = {
            "datasetid": dataset,
            "stationid": station_ids,
            "datatypeid": datatype_ids,
            "startdate": start,
            "enddate": end,
            "units": units,
            "limit": 1000,
            "offset": 1,
            "includemetadata": "true",
        }

        records = []
        while True:
            data = self._get("data", params)
            meta = data.get("metadata", {}).get("resultset", {})
            batch = data.get("results", [])
            records.extend(batch)

            count = meta.get("count", 0)
            offset = meta.get("offset", 1)
            limit = meta.get("limit", 1000)

            if offset + limit - 1 >= count or not batch:
                break

            params["offset"] = offset + limit
            time.sleep(0.2)  # respect 5 req/sec limit

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        if "value" in df.columns:
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.sort_values("date").reset_index(drop=True)

    def get_data_wide(
        self,
        dataset: str,
        station_ids: Union[str, list],
        datatype_ids: Union[str, list],
        start: str,
        end: str,
        units: str = "standard",
    ) -> pd.DataFrame:
        """Like get_data() but pivoted: date × datatype columns."""
        df = self.get_data(dataset, station_ids, datatype_ids, start, end, units)
        if df.empty:
            return df
        pivot_cols = ["datatype"]
        if "station" in df.columns and len(df["station"].unique()) > 1:
            pivot_cols = ["station", "datatype"]
        wide = df.pivot_table(index="date", columns=pivot_cols, values="value", aggfunc="mean")
        wide.columns = ["_".join(c) if isinstance(c, tuple) else c for c in wide.columns]
        return wide.reset_index()

    def search_stations(
        self,
        city: Optional[str] = None,
        state: Optional[str] = None,
        dataset: str = "GHCND",
        limit: int = 25,
    ) -> pd.DataFrame:
        """Search for stations by location."""
        params = {"datasetid": dataset, "limit": limit}
        if city:
            params["locationid"] = f"CITY:{city}"
        if state:
            params["locationid"] = f"FIPS:{state}"
        data = self._get("stations", params)
        results = data.get("results", [])
        return pd.DataFrame(results) if results else pd.DataFrame()
