"""shared/csv_files.py: streamed, capped, host-checked CSV reads, and the decode fallback.

fetch_rows used to buffer the whole response through shared/http.get_raw and
compare its length to the cap afterwards, and its redirect loop checked only that
a hop was https. It now streams through shared/file_download.download().
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from maplestats_mcp.shared import csv_files, file_download
from maplestats_mcp.shared.errors import (
    CloudflareChallenge,
    InvalidInput,
    NotFound,
    UpstreamError,
)
from maplestats_mcp.shared.rate_limiter import TokenBucket

URL = "https://data.example.invalid/files/prices.csv"
OTHER = "https://elsewhere.example.invalid/prices.csv"
CHUNK = b"x" * 16_384


def _limiter() -> TokenBucket:
    return TokenBucket(rate=1000.0, capacity=1000.0)


async def _fetch(url: str = URL, **kwargs):
    return await csv_files.fetch_rows(url, limiter=_limiter(), ttl=60, context="test", **kwargs)


class _Body:
    """A response body that counts the chunks the reader actually pulled."""

    def __init__(self, chunks: int, chunk: bytes = CHUNK) -> None:
        self.total = chunks
        self.chunk = chunk
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.total):
            self.pulled += 1
            yield self.chunk


def _stream(httpx_mock, body: _Body, *, status: int = 200, headers: dict | None = None, url=URL):
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers or {}, content=body)

    httpx_mock.add_callback(respond, url=url)


async def test_reads_rows_and_trims_header_names(httpx_mock):
    httpx_mock.add_response(url=URL, content=b"\xef\xbb\xbfYear , Value\n2020,1\n2021,2\n")
    rows, cached = await _fetch()
    assert rows == [{"Year": "2020", "Value": "1"}, {"Year": "2021", "Value": "2"}]
    assert cached is False
    assert (await _fetch())[1] is True


async def test_stops_reading_when_the_body_outgrows_the_cap(httpx_mock, monkeypatch):
    monkeypatch.setattr(csv_files, "MAX_FILE_BYTES", 100_000)
    body = _Body(chunks=400)  # 6.5 MB on offer, no Content-Length
    _stream(httpx_mock, body)
    with pytest.raises(UpstreamError, match="larger than"):
        await _fetch()
    # 100,000 bytes is seven 16 KB chunks; the other ~390 were never pulled.
    assert body.pulled <= 8


async def test_refuses_a_declared_length_over_the_cap_without_reading(httpx_mock, monkeypatch):
    monkeypatch.setattr(csv_files, "MAX_FILE_BYTES", 100_000)
    body = _Body(chunks=10)
    _stream(httpx_mock, body, headers={"content-length": "5000000"})
    with pytest.raises(UpstreamError, match="5,000,000 bytes"):
        await _fetch()
    assert body.pulled == 0


async def test_html_answer_is_not_found(httpx_mock):
    httpx_mock.add_response(url=URL, content=b"\n  <!DOCTYPE html><html><body>404</body></html>")
    with pytest.raises(NotFound, match="web page"):
        await _fetch()


async def test_404_is_not_found(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=404)
    with pytest.raises(NotFound):
        await _fetch()


async def test_follows_https_redirects_to_the_blob(httpx_mock):
    blob = "https://blob.example.invalid/store/prices.csv?sig=x"
    httpx_mock.add_response(url=URL, status_code=302, headers={"location": blob})
    httpx_mock.add_response(url=blob, content=b"a,b\n1,2\n")
    rows, _ = await _fetch()
    assert rows == [{"a": "1", "b": "2"}]


async def test_redirect_to_http_is_refused(httpx_mock):
    httpx_mock.add_response(
        url=URL, status_code=301, headers={"location": "http://data.example.invalid/p.csv"}
    )
    with pytest.raises(UpstreamError, match="https"):
        await _fetch()


async def test_redirect_hop_off_the_callers_allow_list_is_refused_unrequested(httpx_mock):
    # Only the first URL is mocked: a request to OTHER would fail the test as an
    # unmatched request (UpstreamUnavailable), not as UpstreamError.
    httpx_mock.add_response(url=URL, status_code=302, headers={"location": OTHER})
    with pytest.raises(UpstreamError, match="elsewhere.example.invalid"):
        await _fetch(allowed_hosts=["data.example.invalid"])


async def test_allow_list_lets_a_listed_redirect_target_through(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=302, headers={"location": OTHER})
    httpx_mock.add_response(url=OTHER, content=b"a,b\n1,2\n")
    rows, _ = await _fetch(allowed_hosts=["data.example.invalid", "elsewhere.example.invalid"])
    assert rows == [{"a": "1", "b": "2"}]


async def test_allow_list_applies_to_the_first_url_too(httpx_mock):
    with pytest.raises(InvalidInput, match="data.example.invalid"):
        await _fetch(allowed_hosts=["elsewhere.example.invalid"])


@pytest.mark.parametrize(
    "target",
    [
        "https://127.0.0.1/p.csv",
        "https://[::1]/p.csv",
        "https://169.254.169.254/latest/meta-data.csv",
        "https://localhost/p.csv",
        "https://printer.localhost/p.csv",
    ],
)
async def test_default_hop_rule_never_follows_to_a_private_address(httpx_mock, target):
    httpx_mock.add_response(url=URL, status_code=302, headers={"location": target})
    with pytest.raises(UpstreamError):
        await _fetch()


async def test_too_many_redirects_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=302, headers={"location": URL}, is_reusable=True)
    with pytest.raises(UpstreamError, match="redirected more than"):
        await _fetch()


def test_decode_falls_back_to_latin_1_after_cp1252():
    assert csv_files.decode(b"\xef\xbb\xbfcaf\xc3\xa9") == "café"  # UTF-8 with a BOM
    assert csv_files.decode("café".encode("cp1252")) == "café"  # Windows-1252
    # 0x81 is undefined in Windows-1252; one stray byte must not lose the file.
    assert csv_files.decode(b"caf\xe9 \x81") == "café \x81"


async def test_stray_cp1252_undefined_byte_still_reads(httpx_mock):
    httpx_mock.add_response(url=URL, content=b"name,note\ncaf\xe9,x\x81y\n")
    rows, _ = await _fetch()
    assert rows == [{"name": "café", "note": "x\x81y"}]


# shared/file_download.py: an error answer is read only up to a cap.


async def test_error_body_is_read_only_up_to_the_cap(httpx_mock):
    body = _Body(chunks=500)  # an 8 MB error page
    _stream(httpx_mock, body, status=404)
    with pytest.raises(NotFound):
        await file_download.download(
            URL,
            allow_host=lambda host: True,
            limiter_for=lambda host: _limiter(),
            max_bytes=1_000_000,
            context="test",
        )
    # 64 KB is four 16 KB chunks.
    assert body.pulled <= 5


async def test_cloudflare_challenge_is_still_recognised_from_the_capped_body(
    httpx_mock, cloudflare_challenge
):
    httpx_mock.add_response(url=URL, **cloudflare_challenge)
    with pytest.raises(CloudflareChallenge):
        await file_download.download(
            URL,
            allow_host=lambda host: True,
            limiter_for=lambda host: _limiter(),
            max_bytes=1_000_000,
            context="test",
        )


async def test_403_challenge_found_only_in_the_body_is_recognised(httpx_mock):
    # No Cf-Mitigated header: is_cloudflare_challenge falls back to the page text,
    # which must still be there after the capped read.
    httpx_mock.add_response(
        url=URL, status_code=403, content=b"<html><title>Just a moment...</title></html>"
    )
    with pytest.raises(CloudflareChallenge):
        await file_download.download(
            URL,
            allow_host=lambda host: True,
            limiter_for=lambda host: _limiter(),
            max_bytes=1_000_000,
            context="test",
        )
