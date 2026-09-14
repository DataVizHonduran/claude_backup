import os
import warnings
import requests
import pandas as pd
from typing import Optional

BASE_URL = "https://aqs.epa.gov/data/api"

# Common parameter codes
PARAM_CODES = {
    "pm25": "88101",
    "pm10": "81102",
    "ozone": "44201",
    "co": "42101",
    "no2": "42602",
    "so2": "42401",
    "nox": "42603",
    "wind_speed": "61103",
    "temp": "62101",
}


class EPAAQSClient:
    """Wrapper around the EPA Air Quality System (AQS) API."""

    def __init__(self, email: Optional[str] = None, key: Optional[str] = None):
        self.email = email or os.environ.get("EPA_AQS_EMAIL")
        self.key = key or os.environ.get("EPA_AQS_KEY")
        if not self.email or not self.key:
            warnings.warn(
                "EPA_AQS_EMAIL / EPA_AQS_KEY not set — register free at "
                "https://aqs.epa.gov/data/api/signup",
                stacklevel=2,
            )
        self.session = requests.Session()

    def _auth(self) -> dict:
        return {"email": self.email, "key": self.key}

    def _get(self, endpoint: str, params: dict) -> list:
        params.update(self._auth())
        r = self.session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        if data.get("Header", [{}])[0].get("status") == "Failed":
            raise ValueError(data.get("Header", [{}])[0].get("error", "EPA AQS error"))
        return data.get("Data", [])

    def _resolve_param(self, param: str) -> str:
        """Accept friendly names ('pm25', 'ozone') or raw codes ('88101')."""
        return PARAM_CODES.get(param.lower(), param)

    def daily_by_county(
        self,
        state: str,
        county: str,
        param: str,
        bdate: str,
        edate: str,
    ) -> pd.DataFrame:
        """Daily AQI/concentration by county.

        Args:
            state: 2-digit FIPS state code, e.g. '36' for NY
            county: 3-digit FIPS county code, e.g. '061' for Manhattan
            param: friendly name ('pm25', 'ozone') or raw code ('88101')
            bdate: 'YYYYMMDD'
            edate: 'YYYYMMDD'
        """
        records = self._get("dailyData/byCounty", {
            "param": self._resolve_param(param),
            "bdate": bdate.replace("-", ""),
            "edate": edate.replace("-", ""),
            "state": state,
            "county": county,
        })
        return self._to_df(records)

    def daily_by_cbsa(
        self,
        cbsa: str,
        param: str,
        bdate: str,
        edate: str,
    ) -> pd.DataFrame:
        """Daily AQI/concentration by Core Based Statistical Area.

        Args:
            cbsa: CBSA code, e.g. '35620' for NYC metro
            param: friendly name or raw code
            bdate: 'YYYYMMDD' or 'YYYY-MM-DD'
            edate: 'YYYYMMDD' or 'YYYY-MM-DD'
        """
        records = self._get("dailyData/byCBSA", {
            "param": self._resolve_param(param),
            "bdate": bdate.replace("-", ""),
            "edate": edate.replace("-", ""),
            "cbsa": cbsa,
        })
        return self._to_df(records)

    def annual_by_county(
        self,
        state: str,
        county: str,
        param: str,
        bdate: str,
        edate: str,
    ) -> pd.DataFrame:
        """Annual summary statistics by county."""
        records = self._get("annualData/byCounty", {
            "param": self._resolve_param(param),
            "bdate": bdate.replace("-", ""),
            "edate": edate.replace("-", ""),
            "state": state,
            "county": county,
        })
        return self._to_df(records)

    def _to_df(self, records: list) -> pd.DataFrame:
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        for col in ("date_local", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        for col in ("arithmetic_mean", "aqi", "first_max_value"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
