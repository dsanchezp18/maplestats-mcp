"""Download errors and redirect handling in modules/statcan/lode/files.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan import lang
from maplestats_mcp.modules.statcan.lode import files
from maplestats_mcp.shared.errors import NotFound, UpstreamError

URL = "https://www150.statcan.gc.ca/n1/pub/x/y/data.zip"


async def test_a_missing_archive_is_not_found_not_unavailable(httpx_mock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=URL, status_code=404)
    with pytest.raises(NotFound, match="no file at"):
        await files._download(URL, "data.csv", tmp_path / "data.csv")


async def test_a_missing_archive_is_reported_in_french(httpx_mock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=URL, status_code=404)
    lang.use_lang("fr")
    try:
        with pytest.raises(NotFound, match="aucun fichier"):
            await files._download(URL, "data.csv", tmp_path / "data.csv")
    finally:
        lang.use_lang("en")


async def test_a_redirect_off_the_data_host_is_refused(httpx_mock, tmp_path: Path) -> None:
    httpx_mock.add_response(
        url=URL, status_code=302, headers={"location": "https://evil.example/data.zip"}
    )
    with pytest.raises(UpstreamError, match="evil.example"):
        await files._download(URL, "data.csv", tmp_path / "data.csv")


async def test_a_redirect_to_plain_http_is_refused(httpx_mock) -> None:
    httpx_mock.add_response(
        url=URL,
        method="HEAD",
        status_code=301,
        headers={"location": "http://www150.statcan.gc.ca/data.zip"},
    )
    with pytest.raises(UpstreamError, match="does not follow"):
        await files.head_size(URL)


async def test_a_redirect_on_the_data_host_is_followed(httpx_mock) -> None:
    moved = "https://www150.statcan.gc.ca/n1/pub/moved.zip"
    httpx_mock.add_response(url=URL, method="HEAD", status_code=301, headers={"location": moved})
    httpx_mock.add_response(
        url=moved, method="HEAD", headers={"content-length": "12", "last-modified": "x"}
    )
    assert await files.head_size(URL) == (12, "x")
