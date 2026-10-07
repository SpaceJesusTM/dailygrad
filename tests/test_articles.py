"""URL safety and article extraction, with DNS and HTTP faked. Trafilatura itself runs for real."""

import ipaddress
import socket

import pytest
import requests

from dailygrad import articles

PUBLIC_IP = "93.184.216.34"

ARTICLE_HTML = (
    b"<html><head><title>Model X</title></head><body>"
    b"<nav>Home | About | Careers</nav>"
    b"<article><h1>Model X released</h1>"
    b"<p>" + b"Model X is a new open model that runs on a laptop. " * 6 + b"</p>"
    b"<p>It was trained on public data and released under an open licence.</p></article>"
    b"<footer>Copyright Lab Inc.</footer></body></html>"
)


class FakeResponse:
    def __init__(self, status_code=200, body=b"", content_type="text/html; charset=utf-8", location=None):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type else {}
        if location:
            self.headers["Location"] = location
        self.chunks = [body[i : i + 1000] for i in range(0, len(body), 1000)]
        self.chunks_read = 0
        self.closed = False

    @property
    def is_redirect(self):
        return "Location" in self.headers and self.status_code in (301, 302, 303, 307, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk

    def close(self):
        self.closed = True


@pytest.fixture
def dns(monkeypatch):
    """Fake DNS: maps host names to lists of IPs. IP literals resolve to themselves."""
    hosts = {"example.com": [PUBLIC_IP]}

    def getaddrinfo(host, port, type=0):
        try:
            ips = [str(ipaddress.ip_address(host))]
        except ValueError:
            if host not in hosts:
                raise socket.gaierror("Name or service not known")
            ips = hosts[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return hosts


@pytest.fixture
def pages(monkeypatch, dns):
    """Fake HTTP: maps URLs to FakeResponses. Requested URLs are recorded in pages.requested."""

    class Pages(dict):
        requested = []
        options = []

    pages = Pages()

    def get(url, **options):
        pages.requested.append(url)
        pages.options.append(options)
        return pages[url]

    monkeypatch.setattr(requests, "get", get)
    return pages


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http:///no-host",
        "example.com/no-scheme",
    ],
)
def test_check_url_rejects_non_http_urls(dns, url):
    with pytest.raises(articles.UnsafeURLError, match="not an http"):
        articles.check_url(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "0.0.0.0",  # unspecified
        "10.0.0.5",  # private
        "172.16.1.1",  # private
        "192.168.1.10",  # private
        "169.254.169.254",  # link-local, cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "224.0.0.1",  # multicast
        "::1",  # loopback
        "fe80::1",  # link-local
        "fc00::1",  # unique local
        "::ffff:10.0.0.1",  # private IPv4 mapped into IPv6
    ],
)
def test_check_url_rejects_non_public_addresses(dns, ip):
    dns["internal.example"] = [ip]
    literal = f"[{ip}]" if ":" in ip else ip

    for url in ("https://internal.example/page", f"http://{literal}/page"):
        with pytest.raises(articles.UnsafeURLError, match="non-public address"):
            articles.check_url(url)


def test_check_url_rejects_localhost_and_hosts_with_any_private_address(dns):
    dns["localhost"] = ["127.0.0.1"]
    dns["mixed.example"] = [PUBLIC_IP, "192.168.0.1"]

    for url in ("http://localhost:8080/admin", "https://mixed.example/"):
        with pytest.raises(articles.UnsafeURLError):
            articles.check_url(url)


def test_check_url_rejects_unresolvable_hosts(dns):
    with pytest.raises(articles.UnsafeURLError, match="cannot resolve"):
        articles.check_url("https://no-such-host.example/")


def test_check_url_accepts_public_hosts(dns):
    dns["v6.example"] = ["2606:4700:4700::1111"]

    articles.check_url("https://example.com/post?id=1")
    articles.check_url("http://v6.example/post")


def test_download_requests_safely(pages):
    pages["https://example.com/post"] = FakeResponse(body=ARTICLE_HTML)

    assert articles.download("https://example.com/post") == ARTICLE_HTML

    (options,) = pages.options
    assert options["allow_redirects"] is False
    assert options["stream"] is True
    assert options["timeout"] == articles.TIMEOUT
    assert pages["https://example.com/post"].closed


def test_download_follows_redirects_to_public_hosts(pages, dns):
    dns["cdn.example"] = [PUBLIC_IP]
    pages["https://example.com/short"] = FakeResponse(302, location="https://cdn.example/a/")
    pages["https://cdn.example/a/"] = FakeResponse(301, location="final")  # relative redirect
    pages["https://cdn.example/a/final"] = FakeResponse(body=ARTICLE_HTML)

    assert articles.download("https://example.com/short") == ARTICLE_HTML


@pytest.mark.parametrize("target", ["http://169.254.169.254/latest/meta-data/", "http://localhost/", "file:///etc/passwd"])
def test_download_refuses_redirects_to_unsafe_destinations(pages, dns, target):
    dns["localhost"] = ["127.0.0.1"]
    pages["https://example.com/post"] = FakeResponse(302, location=target)

    with pytest.raises(articles.UnsafeURLError):
        articles.download("https://example.com/post")

    assert pages.requested == ["https://example.com/post"]  # the unsafe target was never requested


def test_download_gives_up_on_redirect_loops(pages):
    pages["https://example.com/loop"] = FakeResponse(302, location="https://example.com/loop")

    with pytest.raises(ValueError, match="too many redirects"):
        articles.download("https://example.com/loop")

    assert len(pages.requested) == articles.MAX_REDIRECTS + 1


def test_download_caps_the_body_size(pages, monkeypatch):
    monkeypatch.setattr(articles, "MAX_DOWNLOAD_BYTES", 2500)
    page = pages["https://example.com/huge"] = FakeResponse(body=b"x" * 50_000)

    assert articles.download("https://example.com/huge") == b"x" * 2500
    assert page.chunks_read == 3  # stopped reading instead of draining the response


def test_download_stops_when_the_deadline_passes(pages, monkeypatch):
    monkeypatch.setattr(articles, "DOWNLOAD_DEADLINE", -1)
    pages["https://example.com/slow"] = FakeResponse(body=b"x" * 5000)

    with pytest.raises(TimeoutError):
        articles.download("https://example.com/slow")


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", None])
def test_download_rejects_non_html(pages, content_type):
    pages["https://example.com/file"] = FakeResponse(body=b"%PDF-1.7", content_type=content_type)

    with pytest.raises(ValueError, match="not an HTML page"):
        articles.download("https://example.com/file")


def test_download_raises_on_http_errors(pages):
    pages["https://example.com/gone"] = FakeResponse(404)

    with pytest.raises(requests.HTTPError):
        articles.download("https://example.com/gone")


def test_fetch_article_text_extracts_the_main_content(pages):
    pages["https://example.com/post"] = FakeResponse(body=ARTICLE_HTML)

    text = articles.fetch_article_text("https://example.com/post")

    assert "Model X is a new open model that runs on a laptop." in text
    assert "released under an open licence" in text
    assert "Careers" not in text and "Copyright" not in text


def test_fetch_article_text_caps_the_extracted_text(pages, monkeypatch):
    monkeypatch.setattr(articles, "MAX_TEXT_CHARS", 120)
    pages["https://example.com/post"] = FakeResponse(body=ARTICLE_HTML)

    assert len(articles.fetch_article_text("https://example.com/post")) == 120


def test_fetch_article_text_returns_empty_when_nothing_is_extractable(pages):
    pages["https://example.com/app"] = FakeResponse(body=b"<html><body><div id='root'></div></body></html>")

    assert articles.fetch_article_text("https://example.com/app") == ""
