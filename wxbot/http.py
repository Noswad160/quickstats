import logging
import time

import requests

from .config import USER_AGENT

log = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def get_json(url: str, params: dict | None = None, retries: int = 3, timeout: float = 20.0):
    """GET with simple exponential backoff on network errors, 429 and 5xx."""
    for attempt in range(retries + 1):
        try:
            resp = _session.get(url, params=params, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} from {url}", response=resp)
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status is None or status == 429 or status >= 500
            if attempt == retries or not retryable:
                raise
            delay = 2 ** (attempt + 1)
            log.warning("GET %s failed (%s); retrying in %ss", url, exc, delay)
            time.sleep(delay)
