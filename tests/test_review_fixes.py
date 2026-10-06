"""Regression tests for the issues found in the repository review."""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from maplestats_mcp import config
from maplestats_mcp.modules.ised.ip_horizons import store
from maplestats_mcp.modules.ised.ip_horizons.schemas import IpHorizonsFile
from maplestats_mcp.modules.phac_infobase import client as phac
from maplestats_mcp.server import mcp
from maplestats_mcp.shared import capped_io, wfs
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.rate_limiter import TokenBucket
from maplestats_mcp.shared.security import _client_key, with_http_security
from maplestats_mcp.shared.timeouts import ToolTimeoutMiddleware
from maplestats_mcp.shared.usage import UsageMiddleware, UsageStats

# ---- usage counting vs. the timeout


def test_usage_middleware_wraps_the_timeout_middleware_on_the_real_server() -> None:
    kinds = [type(m) for m in mcp.middleware]
    assert kinds.index(UsageMiddleware) < kinds.index(ToolTimeoutMiddleware)


async def test_a_timed_out_call_is_counted_as_an_error() -> None:
    stats = UsageStats()
    server = FastMCP("t")
    server.add_middleware(UsageMiddleware(stats))  # same order as server.py
    server.add_middleware(ToolTimeoutMiddleware(0.05))

    @server.tool
    async def slow() -> str:
        await asyncio.sleep(5)
        return "x"

    async with Client(server) as client:
        with pytest.raises(ToolError, match="did not finish"):
            await client.call_tool("slow", {})
    assert stats.snapshot()["by_tool"] == {"slow": {"ok": 0, "error": 1}}


async def test_a_timeout_error_raised_by_the_tool_is_not_reported_as_the_deadline() -> None:
    server = FastMCP("t")
    server.add_middleware(ToolTimeoutMiddleware(30))

    @server.tool
    async def inner_timeout() -> str:
        raise TimeoutError("upstream wait gave up")

    async with Client(server) as client:
        with pytest.raises(ToolError) as caught:
            await client.call_tool("inner_timeout", {})
    assert "did not finish within" not in str(caught.value)


# ---- proxy headers and auth ordering


def _scope(forwarded: str | None, client: str = "10.0.0.1") -> dict:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": headers,
        "client": (client, 1),
    }


def test_client_key_reads_the_address_the_trusted_proxy_appended() -> None:
    # The caller wrote "6.6.6.6"; the proxy appended the address it saw.
    scope = _scope("6.6.6.6, 203.0.113.9")
    assert _client_key(scope, trust_proxy_headers=True) == "203.0.113.9"
    assert _client_key(scope, trust_proxy_headers=True, proxy_hops=2) == "6.6.6.6"
    assert _client_key(scope, trust_proxy_headers=True, proxy_hops=5) == "6.6.6.6"
    assert _client_key(scope, trust_proxy_headers=False) == "10.0.0.1"


async def _status(app, scope) -> int:
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


async def _ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_a_spoofed_leftmost_address_does_not_give_a_fresh_rate_limit_bucket() -> None:
    app = with_http_security(
        _ok, rate_limit_requests=2, rate_limit_window_seconds=60, trust_proxy_headers=True
    )
    statuses = [await _status(app, _scope(f"1.1.1.{n}, 203.0.113.9")) for n in range(3)]
    assert statuses == [200, 200, 429]


async def test_wrong_tokens_spend_the_rate_limit() -> None:
    app = with_http_security(_ok, auth_token="secret", rate_limit_requests=2)
    scope = _scope(None)
    scope["headers"] = [(b"authorization", b"Bearer nope")]
    assert [await _status(app, scope) for _ in range(3)] == [401, 401, 429]


def test_trusted_proxy_hops_setting(monkeypatch) -> None:
    monkeypatch.delenv("MAPLE_TRUSTED_PROXY_HOPS", raising=False)
    assert config.get_trusted_proxy_hops() == 1
    monkeypatch.setenv("MAPLE_TRUSTED_PROXY_HOPS", "2")
    assert config.get_trusted_proxy_hops() == 2
    monkeypatch.setenv("MAPLE_TRUSTED_PROXY_HOPS", "zero")
    assert config.get_trusted_proxy_hops() == 1


# ---- rate limiter and config


async def test_token_bucket_waits_in_a_loop_and_rejects_a_zero_rate() -> None:
    bucket = TokenBucket(rate=200.0, capacity=1.0)
    await asyncio.wait_for(asyncio.gather(*(bucket.acquire() for _ in range(5))), timeout=5)
    with pytest.raises(ValueError):
        TokenBucket(rate=0, capacity=1)


def test_delta_scan_seconds_never_pass_the_tool_timeout(monkeypatch) -> None:
    monkeypatch.setenv("MAPLE_TOOL_TIMEOUT_SECONDS", "5")
    monkeypatch.delenv("MAPLE_DELTA_MAX_SCAN_SECONDS", raising=False)
    assert config.get_delta_max_scan_seconds() < config.get_tool_timeout_seconds()


# ---- hostile XML


BILLION = (
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
    b"<ows:ExceptionReport xmlns:ows='http://www.opengis.net/ows/1.1'>&b;</ows:ExceptionReport>"
)


def test_wfs_refuses_entity_declarations_and_falls_back_to_raw_text() -> None:
    text = wfs._extract_exception_text(BILLION)
    assert text.startswith("<?xml")  # raw-text fallback, no expansion


# ---- ZIP and download size caps


def test_copy_capped_stops_past_the_cap() -> None:
    sink = io.BytesIO()
    with pytest.raises(capped_io.FileTooLarge):
        capped_io.copy_capped(io.BytesIO(b"x" * 3_000_000), sink, 2_000_000, "big.csv")
    assert capped_io.copy_capped(io.BytesIO(b"abc"), io.BytesIO(), 10, "ok") == 3
    assert issubclass(capped_io.FileTooLarge, UpstreamError)


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_phac_damaged_zip_member_is_a_typed_error() -> None:
    body = bytearray(_zip({"a.csv": b"x" * 5000}))
    # Forge the declared size (local header and central directory) to 10 bytes:
    # zipfile stops there and the CRC no longer matches.
    for marker, offset in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        at = bytes(body).find(marker)
        body[at + offset : at + offset + 4] = (10).to_bytes(4, "little")
    with pytest.raises(UpstreamError, match="damaged ZIP member"):
        phac.zip_member(bytes(body), None, "https://example.test/a.zip")
    assert phac.zip_member(_zip({"a.csv": b"x" * 500}), None, "https://example.test/a.zip")


def _file() -> IpHorizonsFile:
    return IpHorizonsFile(
        ip_type="patent", table="main", text_format=False, name="f", url="https://x.test/f.zip"
    )


async def test_ip_horizons_zip_without_a_csv_is_a_typed_error(tmp_path: Path, monkeypatch) -> None:
    async def fake_fetch(file, zip_path: Path) -> None:
        zip_path.write_bytes(_zip({"readme.txt": b"hello"}))

    monkeypatch.setattr(store, "_fetch_zip", fake_fetch)
    target = tmp_path / "t.parquet"
    with pytest.raises(UpstreamError, match="no CSV"):
        await store._download(_file(), target)
    assert not list(tmp_path.glob("*.part"))


async def test_ip_horizons_unreadable_zip_is_a_typed_error(tmp_path: Path, monkeypatch) -> None:
    async def fake_fetch(file, zip_path: Path) -> None:
        zip_path.write_bytes(b"this is not a zip")

    monkeypatch.setattr(store, "_fetch_zip", fake_fetch)
    with pytest.raises(UpstreamError, match="could not be unpacked"):
        await store._download(_file(), tmp_path / "t.parquet")
