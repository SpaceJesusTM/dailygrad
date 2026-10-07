"""Fetch and extract the text of a web article.

Article URLs come from the internet and are untrusted, so every request is checked:
only http(s), only public addresses (re-checked on each redirect), and a capped download.
"""

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests
import trafilatura

from dailygrad import web

TIMEOUT = (5, 15)  # seconds: connect, read
DOWNLOAD_DEADLINE = 30  # seconds for a whole download, however slowly the bytes arrive
MAX_REDIRECTS = 5
MAX_DOWNLOAD_BYTES = 2_000_000
MAX_TEXT_CHARS = 8000  # roughly 2,000 tokens: leaves most of an 8k context free
HTML_TYPES = ("text/html", "application/xhtml+xml")


class UnsafeURLError(ValueError):
    pass


def fetch_article_text(url: str) -> str:
    """Return the main text of the page at `url`, or "" if none could be extracted. Raises on fetch errors."""
    text = trafilatura.extract(download(url), include_comments=False, include_tables=False)
    return (text or "").strip()[:MAX_TEXT_CHARS]


def check_url(url: str) -> None:
    """Raise UnsafeURLError unless `url` is http(s) and its host resolves only to public addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURLError(f"not an http(s) URL: {url}")
    try:
        addresses = socket.getaddrinfo(parts.hostname, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise UnsafeURLError(f"cannot resolve host {parts.hostname}: {exc}") from exc

    for *_, sockaddr in addresses:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        # is_global is False for loopback, private, link-local, shared and reserved ranges.
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURLError(f"host {parts.hostname} resolves to a non-public address")


def download(url: str) -> bytes:
    """Download an HTML page, following redirects by hand so each hop is checked."""
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        # No retries here: a failed article is simply skipped.
        response = requests.get(
            url, headers={"User-Agent": web.USER_AGENT}, timeout=TIMEOUT, stream=True, allow_redirects=False
        )
        try:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith(HTML_TYPES):
                raise ValueError(f"not an HTML page ({content_type or 'no content type'}): {url}")
            return _read_capped(response)
        finally:
            response.close()
    raise ValueError(f"too many redirects: {url}")


def _read_capped(response: requests.Response) -> bytes:
    """Read at most MAX_DOWNLOAD_BYTES of the (decompressed) body. A larger page is cut short."""
    deadline = time.monotonic() + DOWNLOAD_DEADLINE
    chunks, size = [], 0
    for chunk in response.iter_content(chunk_size=65536):
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_DOWNLOAD_BYTES:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"download took longer than {DOWNLOAD_DEADLINE}s")
    return b"".join(chunks)[:MAX_DOWNLOAD_BYTES]
