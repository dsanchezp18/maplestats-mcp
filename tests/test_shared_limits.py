"""Memory and safety bounds in the shared helpers: cache bytes, download
locks, inflation per chunk, redirect hosts, Retry-After dates, CKAN errors."""

from __future__ import annotations

import zlib
from datetime import UTC, datetime

import httpx
import pytest

from maplestats_mcp import config
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared import ckan, file_download, remote_zip, zip_stream
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.http import retry_after_seconds


async def test_cache_evicts_past_the_byte_budget(monkeypatch):
    monkeypatch.setattr(config, "get_cache_max_bytes", lambda: 200_000)
    ttl = 98_765

    async def big():
        return "x" * 60_000

    for index in range(6):
        await cache_module.cached_fetch(f"limits-big-{index}", ttl, big)
    stored = cache_module._caches[ttl]
    assert 0 < len(stored) <= 3
    assert "limits-big-5" in stored  # the newest survives, the oldest went first
    assert sum(cache_module._sizes[ttl].values()) <= 200_000


async def test_cache_skips_a_result_bigger_than_the_whole_budget(monkeypatch):
    monkeypatch.setattr(config, "get_cache_max_bytes", lambda: 10_000)
    calls = 0

    async def huge():
        nonlocal calls
        calls += 1
        return [f"{index}" + "y" * 1000 for index in range(50)]

    await cache_module.cached_fetch("limits-huge", 98_766, huge)
    _, cached = await cache_module.cached_fetch("limits-huge", 98_766, huge)
    assert cached is False and calls == 2


def test_approx_size_grows_with_content():
    small = cache_module.approx_size({"a": [1, 2, 3]})
    large = cache_module.approx_size({"a": [f"{i}" + "z" * 10_000 for i in range(100)]})
    assert large > 1_000_000 > small


async def test_download_locks_are_dropped_after_use():
    file_download.clear_cache()

    async def fetch():
        return file_download.Downloaded(b"data", "https://x.example/f", "text/csv")

    for index in range(20):
        await file_download.cached_download(f"limits-lock-{index}", 60, fetch)
    assert file_download._CACHE.lock_count() == 0


async def test_download_lock_survives_a_failed_fetch():
    async def fail():
        raise UpstreamError("boom")

    with pytest.raises(UpstreamError):
        await file_download.cached_download("limits-fail", 60, fail)
    assert file_download._CACHE.lock_count() == 0


async def test_member_stream_stops_a_deflate_bomb_within_one_chunk(monkeypatch):
    inflated = b"0" * 5_000_000
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    payload = compressor.compress(inflated) + compressor.flush()
    header = b"PK\x03\x04" + b"\x00" * 22 + (0).to_bytes(2, "little") * 2
    blob = header + payload

    async def fetch_range(url, start, end):
        return blob[start : end + 1]

    monkeypatch.setattr(remote_zip, "fetch_range", fetch_range)
    member = remote_zip.ZipMember("bomb.csv", len(payload), len(inflated), 8, 0)
    stream = zip_stream.MemberStream(
        "https://x.example/a.zip",
        member,
        chunk_bytes=len(payload) + 10,
        first_chunk_bytes=len(payload) + 10,
        max_scan_bytes=10_000_000,
        max_inflated_bytes=100_000,
    )
    with pytest.raises(zip_stream.ScanLimitExceeded):
        async for _ in stream.batches():
            pass
    # The chunk inflates to 5 MB; the reader stopped one byte past the ceiling.
    assert stream.inflated == 0


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        ("https://www150.statcan.gc.ca/a.zip", "https://www12.statcan.gc.ca/b.zip", True),
        ("https://open.canada.ca/x", "https://acct.blob.core.windows.net/c/f.zip", True),
        ("https://www150.statcan.gc.ca/a.zip", "https://evil.example/a.zip", False),
        ("https://www150.statcan.gc.ca/a.zip", "http://www150.statcan.gc.ca/a.zip", False),
        ("https://www150.statcan.gc.ca/a.zip", "https://169.254.169.254/latest", False),
        ("https://www150.statcan.gc.ca/a.zip", "https://localhost/a.zip", False),
        ("https://data.gov.bc.ca/a.zip", "https://other.gov.bc.ca/a.zip", True),
        ("https://www.ttc.ca/a.zip", "https://ttc.ca.evil.example/a.zip", False),
    ],
)
def test_redirect_hosts(source, target, allowed):
    assert remote_zip.redirect_allowed(httpx.URL(source), httpx.URL(target)) is allowed


async def test_range_read_refuses_an_off_site_redirect(httpx_mock):
    httpx_mock.add_response(
        url="https://www150.statcan.gc.ca/a.zip",
        status_code=302,
        headers={"location": "https://evil.example/a.zip"},
    )
    with pytest.raises(UpstreamError, match="not followed"):
        await remote_zip.fetch_range("https://www150.statcan.gc.ca/a.zip", 0, 9)


def test_retry_after_accepts_seconds_and_http_dates():
    now = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
    assert retry_after_seconds("7", now) == 7.0
    assert retry_after_seconds("Sat, 03 Oct 2026 12:00:20 GMT", now) == 20.0
    assert retry_after_seconds("Sat, 03 Oct 2026 11:00:00 GMT", now) == 0.0
    assert retry_after_seconds("soon", now) is None
    assert retry_after_seconds("", now) is None


def test_ckan_error_detail_is_one_short_line():
    request = httpx.Request("GET", "https://x.example/api/3/action/package_search")
    html = "<html><body><h1>502 Bad Gateway</h1>\n\n" + "<p>nginx</p>" * 200 + "</body></html>"
    exc = httpx.HTTPStatusError(
        "bad", request=request, response=httpx.Response(502, text=html, request=request)
    )
    detail = ckan._error_detail(exc)
    assert "<" not in detail and "\n" not in detail and len(detail) <= 201
    assert detail.startswith("502 Bad Gateway")


def test_ckan_validation_error_names_the_field():
    body = {"success": False, "error": {"__type": "Validation Error", "rows": ["Must be int"]}}
    assert ckan._envelope_detail(body) == "Validation Error (rows: ['Must be int'])"
