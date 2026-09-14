import io
import os
import zipfile
import requests
import pandas as pd
from typing import Union

BASE = "https://www150.statcan.gc.ca/t1/wds/rest"
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "_cache")


def _vid(v: Union[str, int]) -> int:
    """Accept 'v2062811', 2062811, or '2062811' → int."""
    s = str(v).lstrip("vV")
    return int(s)


def _parse_points(points: list, name: str) -> pd.Series:
    records = {}
    for p in points:
        try:
            records[pd.Timestamp(p["refPer"])] = float(p["value"])
        except (ValueError, TypeError):
            pass
    return pd.Series(records, name=name).sort_index()


class StatsCanClient:
    """Thin wrapper around the Statistics Canada WDS REST API.

    No API key required.  All endpoints are public.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "statscan-client/1.0"

    # ------------------------------------------------------------------
    # Core data fetch
    # ------------------------------------------------------------------

    def get_series(
        self,
        vector_id: Union[str, int],
        n_periods: int = 200,
    ) -> pd.Series:
        """Fetch a single series by vector ID.

        vector_id can be 'v2062811', 2062811, or '2062811'.
        n_periods: number of most-recent observations (no date ceiling exists
        in the free API, so use a large value to get full history).
        """
        vid = _vid(vector_id)
        payload = [{"vectorId": vid, "latestN": n_periods}]
        r = self.session.post(
            f"{BASE}/getDataFromVectorsAndLatestNPeriods",
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()[0]
        if result["status"] != "SUCCESS":
            raise ValueError(f"API error for vector {vid}: {result}")
        pts = result["object"]["vectorDataPoint"]
        return _parse_points(pts, str(vector_id))

    def get_multi(
        self,
        vector_ids: list,
        n_periods: int = 200,
    ) -> pd.DataFrame:
        """Fetch multiple series. Returns DatetimeIndex DataFrame, one col per vector."""
        payload = [{"vectorId": _vid(v), "latestN": n_periods} for v in vector_ids]
        r = self.session.post(
            f"{BASE}/getDataFromVectorsAndLatestNPeriods",
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        frames = {}
        for result in r.json():
            if result["status"] != "SUCCESS":
                continue
            obj = result["object"]
            vid = f"v{obj['vectorId']}"
            frames[vid] = _parse_points(obj["vectorDataPoint"], vid)
        return pd.DataFrame(frames)

    # ------------------------------------------------------------------
    # Table / exploration helpers
    # ------------------------------------------------------------------

    def get_cube_metadata(self, pid: int) -> dict:
        """Return dimension structure for a table (product ID).

        Useful for mapping dimension member names → coordinates / vector IDs.
        Returns the 'object' dict from the API response.
        """
        r = self.session.post(
            f"{BASE}/getCubeMetadata",
            json=[{"productId": pid}],
            timeout=20,
        )
        r.raise_for_status()
        result = r.json()[0]
        if result["status"] != "SUCCESS":
            raise ValueError(f"Metadata error for pid {pid}: {result}")
        return result["object"]

    def get_table(self, pid: int, force_refresh: bool = False) -> pd.DataFrame:
        """Download the full table CSV for a product ID.

        Caches the zip file locally under statscan_client/_cache/.
        Subsequent calls use the cache; pass force_refresh=True to re-download.

        Returns a DataFrame with columns: REF_DATE, all dimension columns,
        VECTOR, COORDINATE, VALUE — filtered to rows where STATUS is NaN
        (i.e., valid data).
        """
        os.makedirs(_CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(_CACHE_DIR, f"{pid}-eng.zip")

        if not os.path.exists(cache_path) or force_refresh:
            r = self.session.get(
                f"{BASE}/getFullTableDownloadCSV/{pid}/en", timeout=20
            )
            r.raise_for_status()
            url = r.json()["object"]
            resp = self.session.get(url, timeout=120)
            resp.raise_for_status()
            with open(cache_path, "wb") as f:
                f.write(resp.content)

        with zipfile.ZipFile(cache_path) as z:
            csv_name = next(n for n in z.namelist() if n.endswith(".csv") and "Meta" not in n)
            with z.open(csv_name) as f:
                df = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)

        df["REF_DATE"] = pd.to_datetime(df["REF_DATE"])
        return df

    def search(self, keyword: str, active_only: bool = True) -> pd.DataFrame:
        """Search all StatsCan tables by keyword (title match, case-insensitive).

        Downloads the full cube list on first call (~5 MB); subsequent calls
        are instant (stored in memory for the session).

        archived values: '2' = CURRENT (active), '1' = ARCHIVED.
        active_only=True (default) filters to archived=='2'.

        Returns a DataFrame with columns: productId, cansimId, cubeTitleEn,
        frequencyCode, cubeStartDate, cubeEndDate, archived.
        """
        if not hasattr(self, "_cubes_df"):
            r = self.session.get(f"{BASE}/getAllCubesListLite", timeout=60)
            r.raise_for_status()
            rows = r.json()
            self._cubes_df = pd.DataFrame([{
                "productId": x.get("productId"),
                "cansimId": x.get("cansimId"),
                "cubeTitleEn": x.get("cubeTitleEn"),
                "frequencyCode": x.get("frequencyCode"),
                "cubeStartDate": x.get("cubeStartDate", "")[:10],
                "cubeEndDate": x.get("cubeEndDate", "")[:10],
                "archived": str(x.get("archived", "1")),
            } for x in rows])

        kw = keyword.lower()
        mask = self._cubes_df["cubeTitleEn"].str.lower().str.contains(kw, na=False)
        df = self._cubes_df[mask]
        if active_only:
            df = df[df["archived"] == "2"]
        return df.reset_index(drop=True)
