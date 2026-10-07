"""Shared HTTP helper so every request gets a timeout, retries and a User-Agent."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dailygrad import __version__

TIMEOUT = (5, 20)  # seconds: connect, read


def _build_session() -> requests.Session:
    retry = Retry(total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = f"DailyGrad/{__version__}"
    return session


_session = _build_session()


def get(url: str, params: dict | None = None) -> requests.Response:
    response = _session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response
