"""Clients that keep their own httpx client still send `request_headers()`.

StatCan's www150 host pins a connection to one backend (probed 2026-09-27,
see shared/http.py), so every request there carries `Connection: close`,
and every request identifies this client. These paths bypass `api_get`:
remote_zip's HEAD and range reads, the LODE and PUMF whole-archive
downloads and LODE's range previews and HEADs.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import httpx
import pytest

from maplestats_mcp.modules.statcan.lode import files as lode_files
from maplestats_mcp.modules.statcan.pumf import tabulate
from maplestats_mcp.shared import remote_zip

STATCAN_ZIP = "https://www150.statcan.gc.ca/n1/pub/71m0001x/2021001/2026-01-CSV.zip"
OTHER_ZIP = "https://ckan0.cf.opendata.inter.prod-toronto.ca/download/x.zip"


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("pub0126.csv", "PROV,FINALWT\n48,100\n")
        bundle.writestr("LFS_PUMF_EPA_FGMD_codebook.csv", "x\n")
    return buffer.getvalue()


def _serve(blob: bytes, *, head_status: int = 200):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(head_status, headers={"content-length": str(len(blob))})
        if "range" not in request.headers:
            return httpx.Response(200, content=blob)
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        part = blob[start : end + 1]
        return httpx.Response(
            206,
            content=part,
            headers={"content-range": f"bytes {start}-{start + len(part) - 1}/{len(blob)}"},
        )

    return respond


def _assert_fresh(requests: list[httpx.Request]) -> None:
    assert requests
    assert all(r.headers["connection"] == "close" for r in requests)
    assert all(r.headers["user-agent"].startswith("maplestats-mcp/") for r in requests)


async def test_remote_zip_listing_and_member_reads(httpx_mock):
    blob = _zip()
    httpx_mock.add_callback(_serve(blob), url=STATCAN_ZIP, is_reusable=True)
    members, _ = await remote_zip.list_members(STATCAN_ZIP)
    await remote_zip.read_member(STATCAN_ZIP, members[0])
    await remote_zip.fetch_range(STATCAN_ZIP, 0, 3)
    sent = httpx_mock.get_requests()
    assert {r.method for r in sent} == {"HEAD", "GET"}
    _assert_fresh(sent)


async def test_remote_zip_size_fallback_after_a_failed_head(httpx_mock):
    # Toronto's host answered HEAD with 502 (2026-10-01); the one-byte range
    # that replaces it keeps the shared headers too.
    blob = _zip()
    httpx_mock.add_callback(_serve(blob, head_status=502), url=STATCAN_ZIP, is_reusable=True)
    members, total = await remote_zip.list_members(STATCAN_ZIP)
    assert total == len(blob)
    assert len(members) == 2
    ranged = [r for r in httpx_mock.get_requests() if r.method == "GET"]
    assert ranged[0].headers["range"] == "bytes=0-0"
    _assert_fresh(httpx_mock.get_requests())


async def test_remote_zip_other_hosts_keep_the_connection(httpx_mock):
    blob = _zip()
    httpx_mock.add_callback(_serve(blob), url=OTHER_ZIP, is_reusable=True)
    await remote_zip.list_members(OTHER_ZIP)
    sent = httpx_mock.get_requests()
    assert all(r.headers.get("connection") != "close" for r in sent)
    assert all(r.headers["user-agent"].startswith("maplestats-mcp/") for r in sent)


async def test_lode_download_previews_and_head(httpx_mock, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAPLE_LODE_CACHE_DIR", str(tmp_path / "lode"))
    blob = _zip()
    httpx_mock.add_callback(_serve(blob), url=STATCAN_ZIP, is_reusable=True)
    target = lode_files.cache_path(STATCAN_ZIP, "pub0126.csv")
    await lode_files._download(STATCAN_ZIP, "pub0126.csv", target)
    assert target.read_text().startswith("PROV")
    await lode_files._range(STATCAN_ZIP, 0, 9)
    size, _ = await lode_files.head_size(STATCAN_ZIP)
    assert size == len(blob)
    sent = httpx_mock.get_requests()
    assert [r.method for r in sent] == ["GET", "GET", "HEAD"]
    assert "range" not in sent[0].headers
    assert sent[1].headers["range"] == "bytes=0-9"
    _assert_fresh(sent)


async def test_pumf_whole_archive_download(httpx_mock, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAPLE_PUMF_CACHE_DIR", str(tmp_path / "pumf"))
    blob = _zip()
    httpx_mock.add_callback(_serve(blob), url=STATCAN_ZIP, is_reusable=True)
    member = remote_zip.ZipMember("pub0126.csv", 0, 0, 8, 0)
    target = tmp_path / "pumf" / "k" / "pub0126.csv"
    await tabulate._download(STATCAN_ZIP, member, target)
    assert target.read_text().startswith("PROV")
    sent = httpx_mock.get_requests()
    assert len(sent) == 1
    _assert_fresh(sent)


@pytest.mark.parametrize("status", [503])
async def test_remote_zip_retry_keeps_the_headers(httpx_mock, status):
    blob = _zip()
    httpx_mock.add_response(url=STATCAN_ZIP, method="GET", status_code=status)
    httpx_mock.add_callback(_serve(blob), url=STATCAN_ZIP, is_reusable=True)
    assert await remote_zip.fetch_range(STATCAN_ZIP, 0, 3) == blob[:4]
    sent = httpx_mock.get_requests()
    assert len(sent) == 2
    _assert_fresh(sent)
    assert sent[0].headers["range"] == sent[1].headers["range"] == "bytes=0-3"
