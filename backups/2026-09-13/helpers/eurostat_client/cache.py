"""Session factory: requests-cache + urllib3 retry strategy."""
import logging
from datetime import timedelta

import requests
import requests_cache
from urllib3.util.retry import Retry

logger = logging.getLogger("eurostat_client.cache")

_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def build_session(
    cache_name: str = "eurostat_cache",
    expire_after: int = 3600,
    retries: int = 5,
) -> requests_cache.CachedSession:
    session = requests_cache.CachedSession(
        cache_name=cache_name,
        expire_after=timedelta(seconds=expire_after),
        allowable_codes=[200],
    )

    retry = Retry(
        total=retries,
        backoff_factor=1,
        status_forcelist=_RETRY_STATUS_CODES,
        raise_on_status=False,
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    logger.debug("Session built: cache=%s ttl=%ds retries=%d", cache_name, expire_after, retries)
    return session
