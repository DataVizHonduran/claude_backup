import os
import requests
import pandas as pd
from typing import Optional, Union


BASE_URL = "https://apps.bea.gov/api/data/"


class BEAClient:
    """Thin wrapper around the BEA REST API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BEA_API_KEY")
        if not self.api_key:
            raise ValueError("BEA_API_KEY not set — export BEA_API_KEY=<your_key>")
        self.session = requests.Session()

    def _get(self, params: dict) -> dict:
        params = {"UserID": self.api_key, "ResultFormat": "JSON", **params}
        r = self.session.get(BASE_URL, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        if "BEAAPI" not in payload:
            raise ValueError(f"Unexpected response: {payload}")
        results = payload["BEAAPI"].get("Results", {})
        if "Error" in results:
            raise ValueError(f"BEA error: {results['Error']}")
        return results

    # ── Discovery ──────────────────────────────────────────────────────────

    def list_datasets(self) -> pd.DataFrame:
        """Return all available datasets."""
        r = self._get({"method": "GetDataSetList"})
        return pd.DataFrame(r["Dataset"])

    def list_parameters(self, dataset: str) -> pd.DataFrame:
        """Return parameters for a dataset."""
        r = self._get({"method": "GetParameterList", "datasetname": dataset})
        return pd.DataFrame(r["Parameter"])

    def list_parameter_values(self, dataset: str, param: str) -> pd.DataFrame:
        """Return valid values for a dataset parameter."""
        r = self._get({
            "method": "GetParameterValues",
            "datasetname": dataset,
            "ParameterName": param,
        })
        key = list(r.keys())[0]
        return pd.DataFrame(r[key])

    # ── Data Fetchers ──────────────────────────────────────────────────────

    def get_nipa(
        self,
        table_name: str,
        frequency: Union[str, list] = "Q",
        year: Union[str, list] = "ALL",
    ) -> pd.DataFrame:
        """
        Fetch NIPA table (GDP, PCE, personal income, etc.).

        table_name: e.g. 'T10101' (GDP), 'T20400' (PCE), 'T60100' (personal income)
        frequency:  'A' annual | 'Q' quarterly | 'M' monthly  (or list)
        year:       'ALL' or list of years e.g. ['2020','2021']
        """
        freq = ",".join(frequency) if isinstance(frequency, list) else frequency
        yr = ",".join(str(y) for y in year) if isinstance(year, list) else year
        r = self._get({
            "method": "GetData",
            "datasetname": "NIPA",
            "TableName": table_name,
            "Frequency": freq,
            "Year": yr,
        })
        rows = r["Data"]
        df = pd.DataFrame(rows)
        df["DataValue"] = pd.to_numeric(df["DataValue"].str.replace(",", ""), errors="coerce")
        return df

    def get_nipa_series(
        self,
        table_name: str,
        line_description: str,
        frequency: str = "Q",
        year: str = "ALL",
    ) -> pd.Series:
        """
        Convenience: pull a single line from a NIPA table as a time-indexed Series.

        line_description: substring match against 'LineDescription' column.
        """
        df = self.get_nipa(table_name, frequency=frequency, year=year)
        mask = df["LineDescription"].str.contains(line_description, case=False, na=False)
        sub = df[mask].copy()
        if sub.empty:
            available = df["LineDescription"].unique().tolist()
            raise ValueError(
                f"No rows matching '{line_description}'. Available:\n" +
                "\n".join(f"  {x}" for x in available[:30])
            )
        # Build datetime index from TimePeriod (e.g. '2023Q1' or '2023')
        def parse_period(p):
            if "Q" in str(p):
                yr, q = p.split("Q")
                month = (int(q) - 1) * 3 + 1
                return pd.Timestamp(f"{yr}-{month:02d}-01")
            return pd.Timestamp(f"{p}-01-01")

        sub = sub.sort_values("TimePeriod")
        sub.index = sub["TimePeriod"].apply(parse_period)
        return sub["DataValue"].rename(line_description)

    def get_gdp_by_industry(
        self,
        table_id: Union[int, str] = 1,
        frequency: str = "Q",
        year: str = "ALL",
        industry: str = "ALL",
    ) -> pd.DataFrame:
        """Fetch GDPbyIndustry table (value added, gross output, etc.)."""
        r = self._get({
            "method": "GetData",
            "datasetname": "GDPbyIndustry",
            "TableID": table_id,
            "Frequency": frequency,
            "Year": year,
            "Industry": industry,
        })
        df = pd.DataFrame(r["Data"])
        df["DataValue"] = pd.to_numeric(df["DataValue"].str.replace(",", ""), errors="coerce")
        return df

    def get_regional(
        self,
        table_name: str,
        line_code: Union[str, int],
        geo_fips: str = "STATE",
        year: str = "ALL",
    ) -> pd.DataFrame:
        """
        Fetch Regional data (state/metro GDP, personal income, etc.).

        table_name:  e.g. 'SAINC1' (personal income), 'SAGDP2N' (real GDP by state)
        line_code:   line number within the table (e.g. 1 for total)
        geo_fips:    'STATE' | 'COUNTY' | 'MSA' | two-digit FIPS (e.g. '06' for CA)
        """
        r = self._get({
            "method": "GetData",
            "datasetname": "Regional",
            "TableName": table_name,
            "LineCode": line_code,
            "GeoFips": geo_fips,
            "Year": year,
        })
        rows = r.get("Data", [])
        df = pd.DataFrame(rows)
        df["DataValue"] = pd.to_numeric(df["DataValue"].str.replace(",", ""), errors="coerce")
        return df

    def get_ita(
        self,
        indicator: str,
        area_or_country: str = "AllCountries",
        frequency: str = "Q",
        year: str = "ALL",
    ) -> pd.DataFrame:
        """
        Fetch International Transactions Accounts (ITA).

        indicator:  e.g. 'BalGds' (goods balance), 'BalSrvs' (services), 'BalCurr' (current acct)
        """
        r = self._get({
            "method": "GetData",
            "datasetname": "ITA",
            "Indicator": indicator,
            "AreaOrCountry": area_or_country,
            "Frequency": frequency,
            "Year": year,
        })
        df = pd.DataFrame(r["Data"])
        df["DataValue"] = pd.to_numeric(df["DataValue"].str.replace(",", ""), errors="coerce")
        return df

    def get_fixed_assets(
        self,
        table_name: str,
        frequency: str = "A",
        year: str = "ALL",
    ) -> pd.DataFrame:
        """Fetch Fixed Assets tables (capital stock, depreciation, investment)."""
        r = self._get({
            "method": "GetData",
            "datasetname": "FixedAssets",
            "TableName": table_name,
            "Frequency": frequency,
            "Year": year,
        })
        df = pd.DataFrame(r["Data"])
        df["DataValue"] = pd.to_numeric(df["DataValue"].str.replace(",", ""), errors="coerce")
        return df
