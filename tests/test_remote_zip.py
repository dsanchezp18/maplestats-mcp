"""shared/remote_zip.py against a real ZIP served through range requests."""

from __future__ import annotations

import io
import re
import zipfile

import httpx
import pytest

from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.errors import UpstreamError

URL = "https://www150.statcan.gc.ca/n1/pub/x/file.zip"


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.csv", "a,b\n" + "1,2\n" * 5000, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("Français/codebook.txt", "étiquette", compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


def _serve(body: bytes):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(body))})
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    return respond


async def test_lists_and_reads_members_by_range(httpx_mock):
    body = _archive()
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    members, total = await remote_zip.list_members(URL)
    assert total == len(body)
    assert [m.name for m in members] == ["data.csv", "Français/codebook.txt"]
    by_name = {m.name: m for m in members}
    assert (await remote_zip.read_member(URL, by_name["data.csv"])).startswith(b"a,b\n1,2")
    assert (
        await remote_zip.read_member(URL, by_name["Français/codebook.txt"])
    ).decode() == "étiquette"


async def test_server_without_range_support_is_an_error(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=URL, headers={"content-length": "100"})
    httpx_mock.add_response(method="GET", url=URL, status_code=200, content=b"x" * 100)
    with pytest.raises(UpstreamError, match="range"):
        await remote_zip.list_members(URL)
