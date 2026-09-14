import os
import io
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import requests

_BASE_URL = "https://files.stlouisfed.org/files/htdocs/fred-md/monthly"
_CACHE_DIR = Path.home() / ".cache" / "fredmd"

_TRANSFORM_MAP = {
    1: "level",
    2: "first_diff",
    3: "second_diff",
    4: "log",
    5: "log_first_diff",
    6: "log_second_diff",
    7: "pct_change_diff",
}


class FredMDClient:
    """Download and parse FRED-MD monthly macro dataset."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def download(self, vintage: str | None = None) -> tuple[pd.DataFrame, dict]:
        """Fetch FRED-MD data.

        Parameters
        ----------
        vintage : str or None
            "YYYY-MM" for a specific release, None for current vintage.

        Returns
        -------
        (df, transforms) where df has DatetimeIndex and transforms is
        {series_name: int_code}.
        """
        filename = f"{vintage}.csv" if vintage else "current.csv"
        cache_key = vintage if vintage else "current"
        cache_path = _CACHE_DIR / f"{cache_key}.csv"

        if cache_path.exists():
            return self._parse(cache_path.read_bytes())

        url = f"{_BASE_URL}/{filename}"
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()
        raw = resp.content

        cache_path.write_bytes(raw)
        return self._parse(raw)

    def apply_transforms(
        self, df: pd.DataFrame, transforms: dict
    ) -> pd.DataFrame:
        """Apply McCracken transformation codes to make series stationary."""
        out = {}
        for col in df.columns:
            code = int(transforms.get(col, 1))
            s = df[col]
            if code == 1:
                out[col] = s
            elif code == 2:
                out[col] = s.diff()
            elif code == 3:
                out[col] = s.diff().diff()
            elif code == 4:
                out[col] = np.log(s)
            elif code == 5:
                out[col] = np.log(s).diff()
            elif code == 6:
                out[col] = np.log(s).diff().diff()
            elif code == 7:
                out[col] = s.pct_change().diff()
            else:
                out[col] = s
        return pd.DataFrame(out, index=df.index).iloc[2:]  # drop 2 NaN rows

    def list_vintages(self, start_year: int = 2015) -> list[str]:
        """Return YYYY-MM strings for all known vintages from start_year to now."""
        today = datetime.today()
        vintages = []
        for year in range(start_year, today.year + 1):
            for month in range(1, 13):
                if year == today.year and month > today.month:
                    break
                vintages.append(f"{year}-{month:02d}")
        return vintages

    def transform_legend(self) -> pd.DataFrame:
        """Return human-readable table of transformation codes."""
        return pd.DataFrame(
            list(_TRANSFORM_MAP.items()), columns=["code", "description"]
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse(self, raw: bytes) -> tuple[pd.DataFrame, dict]:
        buf = io.BytesIO(raw)
        # Row 0: series names (header); Row 1: transform codes
        header = pd.read_csv(buf, nrows=1, index_col=0)
        series_names = header.columns.tolist()

        buf.seek(0)
        codes_row = pd.read_csv(buf, skiprows=1, nrows=1, header=None).iloc[0, 1:]
        transforms = {
            name: int(float(code))
            for name, code in zip(series_names, codes_row)
            if not pd.isna(code)
        }

        buf.seek(0)
        df = pd.read_csv(
            buf,
            skiprows=2,
            header=None,
            names=["date"] + series_names,
            index_col=0,
            parse_dates=True,
        )
        # Drop the trailing footnote row that FRED-MD appends
        df = df[df.index.notna()]

        return df, transforms
