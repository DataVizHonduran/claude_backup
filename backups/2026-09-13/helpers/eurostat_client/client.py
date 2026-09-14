"""Eurostat Statistics API client."""
import json
import logging
import os
import time
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Optional

import pandas as pd

from .cache import build_session
from .utils import jsonstat_to_df

logger = logging.getLogger("eurostat_client.client")

_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
_TOC_URL = "https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc/json"
_META_CACHE_PATH = os.path.join(os.path.dirname(__file__), "metadata_cache.json")


class EurostatClient:
    """Client for the Eurostat Statistics REST API.

    No API key required. Responses are cached in SQLite (eurostat_cache.sqlite).

    Args:
        cache_expire: Cache TTL in seconds (default 3600).
        retries: Max retry attempts on transient errors (default 5).
    """

    def __init__(self, cache_expire: int = 3600, retries: int = 5) -> None:
        self._session = build_session(expire_after=cache_expire, retries=retries)
        self._toc: Optional[pd.DataFrame] = None  # populated lazily by search_catalog

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def search_catalog(self, query: str, top_n: int = 10) -> pd.DataFrame:
        """Search the Eurostat TOC for datasets matching a query.

        Args:
            query: Plain-English description (e.g. ``"GDP quarterly"``).
            top_n: Number of results to return (default 10).

        Returns:
            DataFrame[score, code, title, type, last_update], sorted by score desc.
        """
        if self._toc is None:
            self._toc = self._fetch_toc()

        q_tokens = set(query.lower().split())

        def _score(title: str) -> float:
            t = title.lower()
            token_hit = sum(1 for tok in q_tokens if tok in t) / max(len(q_tokens), 1)
            fuzzy = SequenceMatcher(None, query.lower(), t).ratio()
            return 0.6 * token_hit + 0.4 * fuzzy

        scores = self._toc["title"].map(_score)
        result = self._toc.copy()
        result.insert(0, "score", scores.round(3))
        result = result.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
        logger.info("search_catalog(%r) → %d results", query, len(result))
        return result

    def _fetch_toc(self) -> pd.DataFrame:
        resp = self._get_raw(_TOC_URL, {"lang": "EN"})
        data = resp.json()
        rows: list[dict] = []
        _flatten_toc(data, rows)
        df = pd.DataFrame(rows, columns=["code", "title", "type", "last_update"])
        logger.info("TOC loaded: %d datasets", len(df))
        return df

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    def get_dimensions(self, dataset_code: str) -> dict:
        """Return all dimension codes and labels for a dataset.

        Results are persisted to metadata_cache.json so repeat calls are free.

        Args:
            dataset_code: Eurostat dataset code (e.g. ``"namq_10_gdp"``).

        Returns:
            Dict ``{dim_id: {code: label, ...}, ...}``.
        """
        cache = self._load_meta_cache()
        if dataset_code in cache:
            logger.debug("get_dimensions(%s) → from metadata_cache", dataset_code)
            return cache[dataset_code]["dimensions"]

        # Fetch a minimal slice — single geo value to get dimension metadata
        resp = self._get_raw(
            f"{_BASE}/{dataset_code}",
            {"format": "JSON", "lang": "EN"},
        )
        data = resp.json()

        dims: dict[str, dict[str, str]] = {}
        for dim_id in data.get("id", []):
            cat = data["dimension"][dim_id]["category"]
            dims[dim_id] = {code: cat["label"].get(code, code) for code in cat["index"]}

        cache[dataset_code] = {
            "fetched": str(date.today()),
            "dimensions": dims,
        }
        self._save_meta_cache(cache)
        logger.info("get_dimensions(%s) → %d dims, cached", dataset_code, len(dims))
        return dims

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def get_data(self, dataset_code: str, **filters: Any) -> pd.DataFrame:
        """Fetch data from a Eurostat dataset.

        Args:
            dataset_code: Dataset code (e.g. ``"namq_10_gdp"``).
            **filters: Dimension filters as keyword args
                       (e.g. ``geo="EA20"``, ``unit="CLV_I10"``).
                       Multi-value: pass a list → joined with ``+``
                       (e.g. ``geo=["DE","FR"]``).

        Returns:
            DataFrame indexed by TIME_PERIOD (DatetimeIndex), sorted chronologically.
            Non-time dimensions appear as columns alongside ``value``.
        """
        params: dict[str, Any] = {"format": "JSON", "lang": "EN"}
        for k, v in filters.items():
            params[k] = "+".join(v) if isinstance(v, list) else v

        resp = self._get_raw(f"{_BASE}/{dataset_code}", params)
        df = jsonstat_to_df(resp.json())
        logger.info("get_data(%s, %s) → %d rows", dataset_code, filters, len(df))
        return df

    # ------------------------------------------------------------------
    # Metadata cache helpers
    # ------------------------------------------------------------------

    def _load_meta_cache(self) -> dict:
        if os.path.exists(_META_CACHE_PATH):
            with open(_META_CACHE_PATH, "r") as f:
                return json.load(f)
        return {}

    def _save_meta_cache(self, cache: dict) -> None:
        with open(_META_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_raw(self, url: str, params: Optional[dict] = None):
        t0 = time.perf_counter()
        response = self._session.get(url, params=params or {})
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
        return response


# ------------------------------------------------------------------
# TOC helpers
# ------------------------------------------------------------------

def _flatten_toc(node: dict, rows: list[dict]) -> None:
    """Recursively walk the Eurostat TOC tree and collect leaf dataset entries."""
    code = node.get("code", "")
    title = node.get("title", "")
    node_type = node.get("type", "")
    last_update = node.get("lastUpdate", "")

    if code and node_type in ("dataset", "table"):
        rows.append({"code": code, "title": title, "type": node_type, "last_update": last_update})

    for child in node.get("children", []):
        _flatten_toc(child, rows)
