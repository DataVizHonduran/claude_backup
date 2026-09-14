import os
import time
import datetime
import requests
import pandas as pd
from typing import Optional, Union

BASE_URL = "https://banks.data.fdic.gov/api"


def _repdte_to_date(repdte: str) -> pd.Timestamp:
    """Convert FDIC REPDTE string '20251231' to Timestamp."""
    return pd.Timestamp(f"{repdte[:4]}-{repdte[4:6]}-{repdte[6:8]}")


class FDICClient:
    """Wrapper around the FDIC BankFind Suite API. No key required."""

    def __init__(self):
        self.session = requests.Session()

    def _get(self, endpoint: str, params: dict) -> list:
        params.setdefault("output", "json")
        for attempt in range(3):
            r = self.session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json().get("data", [])
        r.raise_for_status()
        return []

    def search_institutions(
        self,
        name: Optional[str] = None,
        state: Optional[str] = None,
        active: Optional[bool] = True,
        limit: int = 50,
    ) -> pd.DataFrame:
        """Search banks/thrifts by name prefix and/or state.

        Returns DataFrame with CERT, NAME, CITY, STNAME, ASSET, ACTIVE, CHARTER.
        name is treated as a prefix wildcard (e.g. "Wells" matches "Wells Fargo...").
        """
        filters = []
        if name:
            # API uses Lucene prefix wildcard — append * for prefix match
            prefix = name.replace(" ", "*") + "*"
            filters.append(f"NAME:{prefix}")
        if state:
            filters.append(f"STNAME:{state.upper()}")
        if active is True:
            filters.append("ACTIVE:1")
        elif active is False:
            filters.append("ACTIVE:0")

        params = {
            "fields": "CERT,NAME,CITY,STNAME,ASSET,ACTIVE,CHARTER,REPDTE",
            "limit": limit,
            "sort_by": "ASSET",
            "sort_order": "DESC",
        }
        if filters:
            params["filters"] = " AND ".join(filters)

        rows = self._get("institutions", params)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([r["data"] for r in rows])

    def get_financials(
        self,
        cert: int,
        fields: str = "REPDTE,ASSET,DEP,LNLSNET,NETINC,ROA,ROE,INTINC,TIER1,NTLNLSR,NCLNLSR",
        start_date: str = "2015-01-01",
        end_date: Optional[str] = None,
        limit: int = 60,
    ) -> pd.DataFrame:
        """Fetch quarterly financials for one institution by FDIC cert number.

        Returns DatetimeIndex DataFrame. Each column is one requested field.
        """
        if end_date is None:
            end_date = datetime.date.today().strftime("%Y-%m-%d")

        start_repdte = start_date.replace("-", "")
        end_repdte = end_date.replace("-", "")

        params = {
            "filters": f"CERT:{cert} AND REPDTE:[{start_repdte} TO {end_repdte}]",
            "fields": fields if "REPDTE" in fields else f"REPDTE,{fields}",
            "limit": limit,
            "sort_by": "REPDTE",
            "sort_order": "ASC",
        }
        rows = self._get("financials", params)
        if not rows:
            return pd.DataFrame()

        records = []
        for r in rows:
            d = r["data"]
            d["_date"] = _repdte_to_date(d["REPDTE"])
            records.append(d)

        df = pd.DataFrame(records).set_index("_date")
        df.index.name = "date"
        df.drop(columns=["REPDTE"], inplace=True, errors="ignore")
        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")
            if not converted.isna().all():
                df[col] = converted
        return df

    def get_multi_financials(
        self,
        certs: list,
        field: str,
        start_date: str = "2015-01-01",
        end_date: Optional[str] = None,
        limit: int = 60,
    ) -> pd.DataFrame:
        """Fetch a single financial field for multiple banks.

        Returns DatetimeIndex DataFrame, one column per cert.
        """
        frames = {}
        for cert in certs:
            df = self.get_financials(cert, fields=f"REPDTE,{field}",
                                     start_date=start_date, end_date=end_date,
                                     limit=limit)
            if not df.empty and field in df.columns:
                frames[cert] = df[field]
        return pd.DataFrame(frames)

    def get_failures(
        self,
        state: Optional[str] = None,
        start_year: int = 2000,
        end_year: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch bank/thrift failure records.

        Returns DataFrame with CERT, NAME, CITY, STALP, FAILDATE, SAVR, RESTYPE, COST.
        """
        if end_year is None:
            end_year = datetime.date.today().year

        start_repdte = f"{start_year}0101"
        end_repdte = f"{end_year}1231"

        filters = [f"FAILDATE:[{start_repdte} TO {end_repdte}]"]
        if state:
            filters.append(f"PSTALP:{state.upper()}")

        params = {
            "filters": " AND ".join(filters),
            "fields": "CERT,NAME,CITY,PSTALP,FAILDATE,SAVR,RESTYPE,COST",
            "limit": 500,
            "sort_by": "FAILDATE",
            "sort_order": "ASC",
        }
        rows = self._get("failures", params)
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([r["data"] for r in rows])
        df["FAILDATE"] = pd.to_datetime(df["FAILDATE"], errors="coerce")
        df["COST"] = pd.to_numeric(df["COST"], errors="coerce")
        return df

    def get_industry_summary(
        self,
        fields: str = "REPDTE,ASSET,DEP,NETINC,LNLS,NTLNLS,NCLNLS,EQ",
        start_year: int = 2015,
        end_year: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch annual industry-level aggregate statistics for US commercial banks.

        Returns DatetimeIndex DataFrame. Annual frequency — one row per year.
        Key fields: ASSET, DEP (deposits), NETINC (net income), LNLS (gross loans),
        NTLNLS (net charge-offs $), NCLNLS (noncurrent loans $), EQ (equity).
        """
        if end_year is None:
            end_year = datetime.date.today().year

        start_iso = f"{start_year}-01-01T00:00:00"
        end_iso = f"{end_year}-12-31T00:00:00"

        params = {
            "filters": (
                f'STNAME:"United States" AND CB_SI:CB '
                f"AND REPDTE:[{start_iso} TO {end_iso}]"
            ),
            "fields": fields if "REPDTE" in fields else f"REPDTE,{fields}",
            "limit": end_year - start_year + 2,
            "sort_by": "REPDTE",
            "sort_order": "ASC",
        }
        rows = self._get("summary", params)
        if not rows:
            return pd.DataFrame()

        records = []
        for r in rows:
            d = r["data"]
            d["_date"] = pd.Timestamp(d["REPDTE"][:10])
            records.append(d)

        df = pd.DataFrame(records).set_index("_date")
        df.index.name = "date"
        df.drop(columns=["REPDTE"], inplace=True, errors="ignore")
        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")
            if not converted.isna().all():
                df[col] = converted
        return df
