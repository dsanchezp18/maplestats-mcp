"""The archive tools only build www12 URLs; they must say when www12 is blocked."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.census_profile_archive import client, constants
from maplestats_mcp.shared import cache as cache_module


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


async def test_download_link_notes_the_cloudflare_challenge(httpx_mock, cloudflare_challenge):
    httpx_mock.add_response(url=constants.REACHABILITY_URL, **cloudflare_challenge)
    result = await client.get_download_link(2016, "canada_provinces_territories", "csv")
    assert result.url.startswith("https://www12.statcan.gc.ca/")
    assert result.provenance.limits is not None
    assert "Cloudflare" in result.provenance.limits
    assert "17100123" in result.provenance.limits


async def test_blocked_note_follows_lang(httpx_mock, cloudflare_challenge):
    httpx_mock.add_response(url=constants.REACHABILITY_URL, **cloudflare_challenge)
    result = await client.get_download_link(2016, "canada_provinces_territories", "csv", "fr")
    assert result.provenance.limits == constants.BLOCKED_NOTE_FR
    assert "vérification de sécurité Cloudflare :" in result.provenance.limits
    english = await client.list_geography_levels(2016)
    assert english.provenance.limits == constants.BLOCKED_NOTE


async def test_download_link_has_no_note_when_www12_answers(httpx_mock):
    httpx_mock.add_response(url=constants.REACHABILITY_URL, text="<html>profile</html>")
    result = await client.get_download_link(2016, "canada_provinces_territories", "csv")
    assert result.provenance.limits is None


async def test_probe_is_cached_between_calls(httpx_mock, cloudflare_challenge):
    httpx_mock.add_response(url=constants.REACHABILITY_URL, **cloudflare_challenge)
    await client.list_geography_levels(2016)
    await client.get_download_link(2011, "canada_provinces_territories", "csv")
    assert len(httpx_mock.get_requests()) == 1
