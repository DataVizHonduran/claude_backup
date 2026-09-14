"""OECD SDMX REST API client."""
import logging
import time
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Any, Optional

import pandas as pd

from .cache import build_session
from .utils import parse_csv_response

logger = logging.getLogger("oecd_client.client")

_BASE = "https://sdmx.oecd.org/public/rest"
_SDMX_NS = "{urn:sdmx:org.sdmx.infomodel.datastructure.Dataflow=2.0}"
_STRUCT_NS = "urn:sdmx:org.sdmx.infomodel.structure.DataStructureDefinition=2.0"

# SDMX 2.1 namespaces present in dataflow XML
_NS = {
    "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "m": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}


class OecdClient:
    """Client for the OECD SDMX REST API.

    No API key required — the OECD API is public and free.

    Args:
        cache_expire: Response cache TTL in seconds (default 3600).
        retries: Max retry attempts on transient/rate-limit errors (default 5).
    """

    def __init__(self, cache_expire: int = 3600, retries: int = 5) -> None:
        self._session = build_session(expire_after=cache_expire, retries=retries)
        self._catalog: Optional[pd.DataFrame] = None
        self._structures: dict[str, dict[int, str]] = {}  # dataflow_id → {position: dim_id}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_dataflows(self, agency: str = "all") -> pd.DataFrame:
        """Return available OECD dataflows.

        Args:
            agency: Agency identifier (default ``"all"``).

        Returns:
            DataFrame with columns ``[id, name, agency, version]``.
        """
        url = f"{_BASE}/dataflow/{agency}"
        root = self._get_xml(url)

        rows = []
        for df_el in root.iter("{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure}Dataflow"):
            agency_id = df_el.get("agencyID", "")
            df_id = df_el.get("id", "")
            version = df_el.get("version", "")
            name_el = df_el.find(
                "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common}Name"
            )
            name = name_el.text if name_el is not None else ""
            rows.append({"id": df_id, "name": name, "agency": agency_id, "version": version})

        result = pd.DataFrame(rows, columns=["id", "name", "agency", "version"])
        if agency == "all":
            self._catalog = result
        logger.info("list_dataflows(%s) → %d rows", agency, len(result))
        return result

    def search(self, query: str, top_n: int = 10) -> pd.DataFrame:
        """Find dataflows by natural-language query.

        Scores each dataflow name against ``query`` using token overlap +
        fuzzy similarity, then returns the top matches.

        Args:
            query: Plain-English description (e.g. ``"GDP growth"``).
            top_n: Number of results to return (default 10).

        Returns:
            DataFrame with columns ``[score, id, name, agency, version]``,
            sorted descending by score. Pass ``id`` and ``agency`` directly
            to ``get_data()``.
        """
        if self._catalog is None:
            self._catalog = self.list_dataflows()

        q_tokens = set(query.lower().split())

        def _score(name: str) -> float:
            name_lower = name.lower()
            # token overlap: fraction of query words found in the name
            token_hit = sum(1 for t in q_tokens if t in name_lower) / max(len(q_tokens), 1)
            # fuzzy similarity on the full strings
            fuzzy = SequenceMatcher(None, query.lower(), name_lower).ratio()
            return 0.6 * token_hit + 0.4 * fuzzy

        scores = self._catalog["name"].map(_score)
        result = self._catalog.copy()
        result.insert(0, "score", scores.round(3))
        result = result.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
        return result

    def get_data(
        self,
        agency: str,
        dataflow: str,
        filters: str = "",
        key: Optional[dict] = None,
        version: str = "*",
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Retrieve data from an OECD dataflow.

        Args:
            agency: Agency identifier (e.g. ``"OECD.SDD.STES"``).
            dataflow: Dataflow identifier (e.g. ``"DSD_STES@DF_CLI"``).
            filters: Dot-separated dimension key (e.g. ``".M.LI...AA...H"``).
                     Use ``+`` for multiple values, empty segment = all values.
            key: Dict of ``{dimension_id: value}`` to pin (e.g. ``{"MEASURE": "BCICP"}``).
                 Fetches structure once to resolve positions, then builds the dot-key.
                 Ignored when ``filters`` is also provided.
            version: Dataflow version (default ``"*"`` = latest).
            **kwargs: Extra query params forwarded to the API
                      (e.g. ``startPeriod="2020-01"``, ``endPeriod="2024-12"``).

        Returns:
            DataFrame indexed by TIME_PERIOD (if present) with all dimension
            and observation columns.
        """
        if key and not filters:
            filters = self._build_key(agency, dataflow, key)
            logger.info("key=%s → filters=%r", key, filters)

        if version and version != "*":
            path = f"{_BASE}/data/{agency},{dataflow},{version}/{filters}"
        else:
            path = f"{_BASE}/data/{agency},{dataflow}/{filters}"
        params: dict[str, Any] = {
            "format": "csvfilewithlabels",
            "dimensionAtObservation": "AllDimensions",
            **kwargs,
        }
        response = self._get_raw(path, params)
        df = parse_csv_response(response.text)
        logger.info("get_data(%s/%s) → %d rows", dataflow, filters, len(df))
        return df

    def _build_key(self, agency: str, dataflow: str, key: dict) -> str:
        """Build a dot-separated SDMX key string from a dimension dict."""
        pos_map = self._get_dim_positions(agency, dataflow)
        if not pos_map:
            return ""
        n_dims = max(pos_map.keys())
        # invert: dim_id → position
        id_to_pos = {v: k for k, v in pos_map.items()}
        segments = [""] * n_dims
        for dim_id, value in key.items():
            pos = id_to_pos.get(dim_id)
            if pos is not None:
                segments[pos - 1] = str(value)
        return ".".join(segments)

    def _get_dim_positions(self, agency: str, dataflow: str) -> dict[int, str]:
        """Return {position: dim_id} for a dataflow, cached per session."""
        cache_key = f"{agency},{dataflow}"
        if cache_key in self._structures:
            return self._structures[cache_key]

        # DSD id is the part before '@' in the dataflow id
        dsd_id = dataflow.split("@")[0]
        url = f"{_BASE}/datastructure/{agency}/{dsd_id}/*"
        try:
            root = self._get_xml(url)
        except Exception:
            return {}

        dsd_ns = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
        pos_map: dict[int, str] = {}
        for dim in root.iter(f"{{{dsd_ns}}}Dimension"):
            pos = dim.get("position")
            dim_id = dim.get("id")
            if pos and dim_id:
                pos_map[int(pos)] = dim_id

        self._structures[cache_key] = pos_map
        logger.info("_get_dim_positions(%s) → %d dims", dataflow, len(pos_map))
        return pos_map

    def get_structure(self, agency: str, dataflow_id: str, version: str = "*") -> dict:
        """Return dimension metadata for a dataflow.

        Args:
            agency: Agency identifier (e.g. ``"OECD.SDD.STES"``).
            dataflow_id: Dataflow ID without agency prefix (e.g. ``"DSD_STES"``).
            version: Structure version (default ``"*"`` = latest).

        Returns:
            Dict mapping dimension position → ``{id, name, codes}``.
        """
        url = f"{_BASE}/datastructure/{agency}/{dataflow_id}/{version}"
        root = self._get_xml(url)

        dims: dict[int, dict] = {}
        dsd_ns = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
        com_ns = "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"

        for dim in root.iter(f"{{{dsd_ns}}}Dimension"):
            pos = int(dim.get("position", 0))
            dim_id = dim.get("id", "")
            dims[pos] = {"id": dim_id, "name": dim_id, "codes": []}

        logger.info("get_structure(%s/%s) → %d dimensions", dataflow_id, version, len(dims))
        return dims

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

    def _get_xml(self, url: str, params: Optional[dict] = None) -> ET.Element:
        response = self._get_raw(url, params)
        return ET.fromstring(response.content)
