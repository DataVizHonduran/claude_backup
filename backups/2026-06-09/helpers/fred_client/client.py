"""FRED API client."""
import logging
import os
import time
from typing import Any, Optional

import pandas as pd
from dotenv import load_dotenv

from .cache import build_session
from .utils import clean_and_align

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
logger = logging.getLogger("fred_client.client")

_BASE_URL = "https://api.stlouisfed.org/fred"


class FredClient:
    """Client for the St. Louis Fed FRED REST API.

    Args:
        api_key: FRED API key. Falls back to ``FRED_API_KEY`` env var.
        cache_expire: Response cache TTL in seconds (default 3600).
        retries: Max retry attempts on transient errors (default 5).

    Raises:
        ValueError: If no API key is found.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_expire: int = 3600,
        retries: int = 5,
    ) -> None:
        self._api_key = api_key or os.environ.get("FRED_API_KEY")
        if not self._api_key:
            raise ValueError(
                "FRED API key not found. Pass api_key= or set FRED_API_KEY in your environment."
            )
        self._session = build_session(expire_after=cache_expire, retries=retries)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_series(
        self,
        series_id: str,
        freq: str = "MS",
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch observations for a FRED series.

        Args:
            series_id: FRED series identifier (e.g. ``"GDP"``).
            freq: Pandas offset alias for alignment (default ``"MS"``).
            **kwargs: Extra query parameters forwarded to the API
                (e.g. ``observation_start="2000-01-01"``).

        Returns:
            DataFrame with a DatetimeIndex and a single numeric column
            named after ``series_id``, resampled to ``freq``.
        """
        params = {"series_id": series_id, **kwargs}
        data = self._get("/series/observations", params)
        observations = data.get("observations", [])

        df = pd.DataFrame(observations).set_index("date")[["value"]]
        df.columns = [series_id]
        df = clean_and_align(df, freq=freq)

        logger.info("get_series(%s) → %d rows", series_id, len(df))
        return df

    def get_categories(self, category_id: int = 0) -> pd.DataFrame:
        """Fetch child categories for a given FRED category.

        Args:
            category_id: FRED category ID (default 0 = root).

        Returns:
            DataFrame of category metadata (id, name, parent_id).
        """
        data = self._get("/category/children", {"category_id": category_id})
        categories = data.get("categories", [])
        df = pd.DataFrame(categories)
        logger.info("get_categories(%d) → %d rows", category_id, len(df))
        return df

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an authenticated GET request against the FRED API.

        Args:
            endpoint: API path (e.g. ``"/series/observations"``).
            params: Query parameters (api_key and file_type are injected).

        Returns:
            Parsed JSON response as a dict.

        Raises:
            requests.HTTPError: On non-2xx responses after retries.
        """
        url = _BASE_URL + endpoint
        params = {**params, "api_key": self._api_key, "file_type": "json"}

        t0 = time.perf_counter()
        response = self._session.get(url, params=params)
        elapsed = time.perf_counter() - t0

        from_cache = getattr(response, "from_cache", False)
        logger.debug(
            "GET %s [%s] %.3fs HTTP %d",
            url,
            "CACHE" if from_cache else "NETWORK",
            elapsed,
            response.status_code,
        )

        response.raise_for_status()
        return response.json()
