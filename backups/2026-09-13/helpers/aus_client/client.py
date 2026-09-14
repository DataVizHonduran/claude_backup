"""Clients for Australian macro data: ABS Data API (SDMX-JSON) and RBA statistical tables (CSV)."""
from typing import Optional

import pandas as pd

from .cache import build_session
from .utils import parse_rba_csv, sdmx_json_to_df

_ABS_BASE = "https://data.api.abs.gov.au/rest"
_ABS_DATA_HEADERS = {"Accept": "application/vnd.sdmx.data+json"}
_ABS_STRUCT_HEADERS = {"Accept": "application/vnd.sdmx.structure+json"}

_RBA_BASE = "https://www.rba.gov.au/statistics/tables/csv"


class AbsClient:
    """Client for the ABS Data API (SDMX-JSON 2.0). No API key required."""

    def __init__(self, cache_expire: int = 3600, retries: int = 5):
        self._session = build_session(cache_name="abs_cache", expire_after=cache_expire, retries=retries)
        self._dataflows: Optional[pd.DataFrame] = None

    def search_dataflows(self, keyword: str) -> pd.DataFrame:
        """Search ABS dataflows by keyword (substring match on name).

        Returns DataFrame[id, version, name].
        """
        if self._dataflows is None:
            r = self._session.get(
                f"{_ABS_BASE}/dataflow/ABS",
                params={"format": "json"},
                headers=_ABS_STRUCT_HEADERS,
            )
            r.raise_for_status()
            flows = r.json()["data"]["dataflows"]
            self._dataflows = pd.DataFrame(
                [{"id": f["id"], "version": f["version"], "name": f["name"]} for f in flows]
            )
        kw = keyword.lower()
        mask = self._dataflows["name"].str.lower().str.contains(kw, na=False)
        return self._dataflows[mask].reset_index(drop=True)

    def get_dimensions(self, flow_id: str, version: Optional[str] = None) -> dict:
        """Return {dim_id: {code: label}} for a dataflow's dimensions, for building keys."""
        version = version or self._latest_version(flow_id)
        r = self._session.get(
            f"{_ABS_BASE}/datastructure/ABS/{flow_id}/{version}",
            params={"references": "children", "format": "json"},
            headers=_ABS_STRUCT_HEADERS,
        )
        r.raise_for_status()
        body = r.json()["data"]
        dims = body["dataStructures"][0]["dataStructureComponents"]["dimensionList"]["dimensions"]
        codelists = {cl["id"]: cl for cl in body.get("codelists", [])}

        result = {}
        for dim in dims:
            enum = dim.get("localRepresentation", {}).get("enumeration")
            if not enum:
                continue
            cl_id = enum.split("=")[-1].split("(")[0].split(":")[-1]
            cl = codelists.get(cl_id)
            if cl:
                result[dim["id"]] = {c["id"]: c["name"] for c in cl["codes"]}
        return result

    def get_data(
        self,
        flow_id: str,
        key: str = "all",
        version: Optional[str] = None,
        start_period: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch data for a dataflow.

        key: dot-separated dimension key in dataflow dimension order
             (e.g. "M13.3.1599.20.AUS.M" for LF unemployment rate), or
             "all" for every series.
        version: dataflow version (e.g. "1.0.0"); auto-resolved if omitted.
        start_period: e.g. "2015-01" or "2015-Q1".
        """
        version = version or self._latest_version(flow_id)
        params = {"format": "jsondata"}
        if start_period:
            params["startPeriod"] = start_period
        r = self._session.get(
            f"{_ABS_BASE}/data/ABS,{flow_id},{version}/{key}",
            params=params,
            headers=_ABS_DATA_HEADERS,
        )
        r.raise_for_status()
        return sdmx_json_to_df(r.json())

    def _latest_version(self, flow_id: str) -> str:
        r = self._session.get(
            f"{_ABS_BASE}/dataflow/ABS/{flow_id}",
            params={"format": "json"},
            headers=_ABS_STRUCT_HEADERS,
        )
        r.raise_for_status()
        return r.json()["data"]["dataflows"][0]["version"]


class RbaClient:
    """Client for RBA statistical-table CSV downloads. No API key required."""

    def __init__(self, cache_expire: int = 3600, retries: int = 5):
        self._session = build_session(cache_name="rba_cache", expire_after=cache_expire, retries=retries)

    def get_table(self, table_id: str) -> pd.DataFrame:
        """Download and parse an RBA statistical table (e.g. "F1", "F11", "G1").

        Returns DatetimeIndex DataFrame, one column per Series ID.
        """
        r = self._session.get(f"{_RBA_BASE}/{table_id.lower()}-data.csv")
        r.raise_for_status()
        return parse_rba_csv(r.text)

    def get_series(self, table_id: str, series_id: str) -> pd.Series:
        """Fetch a single named series (Series ID) from an RBA table."""
        return self.get_table(table_id)[series_id].rename(series_id)
