"""NYC Open Data (Socrata/SODA) client with SoQL filtering and pagination.

Swap the dataset:
    Change ``dataset_id`` to any 4x4 ID from data.cityofnewyork.us/data:
        43nn-pn8j  NYC Restaurant Inspections (DOHMH)
        833y-fsy8  NYC Motor Vehicle Collisions
        h9gi-nx95  NYC Motor Vehicle Crashes
        nc67-uf89  NYC 311 Service Requests
        pvqr-7yc4  NYC Parking Violations Issued

Swap the query:
    ``where``  → SoQL $where  e.g. "violation_county = 'BX' AND issue_date > '2022-01-01'"
    ``select`` → SoQL $select e.g. "issue_date, COUNT(*) AS cnt"
    ``group``  → SoQL $group  e.g. "issue_date"
    ``order``  → SoQL $order  e.g. "issue_date ASC"
"""
import logging
import os
import time
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from sodapy import Socrata

from .utils import coerce_datetime, coerce_numeric

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
logger = logging.getLogger("nyc_open_data.client")

_DOMAIN = "data.cityofnewyork.us"
_SOCRATA_MAX_PAGE = 50_000


class SodaClient:
    """Client for the NYC Open Data SODA API.

    Args:
        app_token: Socrata app token. Falls back to ``SOCRATA_APP_TOKEN`` env var.
                   Anonymous access works but is throttled to ~1,000 rows/request.
        timeout: HTTP request timeout in seconds (default 30).
    """

    def __init__(
        self,
        app_token: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        token = app_token or os.environ.get("SOCRATA_APP_TOKEN")
        if not token:
            logger.warning(
                "No SOCRATA_APP_TOKEN found — running unauthenticated (throttled). "
                "Register at https://data.cityofnewyork.us/profile/app_tokens"
            )
        self._client = Socrata(_DOMAIN, token, timeout=timeout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        dataset_id: str,
        *,
        where: str = "",
        select: str = "*",
        order: str = "",
        group: str = "",
        limit: int = 50_000,
        page_size: int = 10_000,
        numeric_cols: Optional[list[str]] = None,
        datetime_col: Optional[str] = None,
        datetime_fmt: Optional[str] = None,
        as_index: bool = False,
    ) -> pd.DataFrame:
        """Fetch rows from a SODA dataset with server-side SoQL filtering.

        All filtering, projection, and aggregation happens on Socrata's servers
        before data is transferred — never pull raw rows and filter locally.

        Args:
            dataset_id: 4x4 dataset identifier (e.g. ``"43nn-pn8j"``).
            where: SoQL $where clause (e.g. ``"violation_county = 'BX'"``)
            select: SoQL $select clause (e.g. ``"issue_date, COUNT(*) AS cnt"``)
            order: SoQL $order clause (e.g. ``"issue_date ASC"``)
            group: SoQL $group clause (e.g. ``"issue_date"``)
            limit: Total row ceiling across all pages (default 50,000).
            page_size: Rows per API call, max 50,000 (default 10,000).
            numeric_cols: Columns to cast to float64 after fetch.
            datetime_col: Column to parse as datetime after fetch.
            datetime_fmt: strptime format for ``datetime_col``. None = infer.
            as_index: If True and ``datetime_col`` is set, use it as the index.

        Returns:
            Clean DataFrame. Empty DataFrame (0 rows) if no results.

        Raises:
            requests.HTTPError: On non-retryable HTTP errors.
        """
        page_size = min(page_size, _SOCRATA_MAX_PAGE)
        frames: list[pd.DataFrame] = []
        offset = 0
        fetched = 0

        while fetched < limit:
            batch_limit = min(page_size, limit - fetched)
            rows = self._get_page(
                dataset_id,
                where=where,
                select=select,
                order=order,
                group=group,
                limit=batch_limit,
                offset=offset,
            )

            if not rows:
                break

            frames.append(pd.DataFrame(rows))
            fetched += len(rows)
            offset += len(rows)
            logger.info("dataset=%s fetched=%d total=%d", dataset_id, len(rows), fetched)

            if len(rows) < batch_limit:
                break

        if not frames:
            logger.warning("dataset=%s returned 0 rows", dataset_id)
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)

        if numeric_cols:
            df = coerce_numeric(df, numeric_cols)
        if datetime_col:
            df = coerce_datetime(df, datetime_col, fmt=datetime_fmt, as_index=as_index)

        logger.info("dataset=%s final shape=%s", dataset_id, df.shape)
        return df

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_page(
        self,
        dataset_id: str,
        *,
        where: str,
        select: str,
        order: str,
        group: str,
        limit: int,
        offset: int,
    ) -> list[dict]:
        """Single paginated SODA request with 429 retry."""
        params: dict = {"limit": limit, "offset": offset}
        if where:
            params["where"] = where
        if select and select != "*":
            params["select"] = select
        if order:
            params["order"] = order
        if group:
            params["group"] = group

        for attempt in (1, 2):
            try:
                return self._client.get(dataset_id, **params)
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 429 and attempt == 1:
                    logger.warning("HTTP 429 — rate limited, sleeping 60s then retrying")
                    time.sleep(60)
                    continue
                raise RuntimeError(
                    f"SODA request failed for dataset={dataset_id}: {exc}"
                ) from exc
        return []

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SodaClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
