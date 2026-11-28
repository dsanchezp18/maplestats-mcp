"""A host that challenges automated clients is reported as a block, not as an outage.

StatCan's www150 answered automated clients with a Cloudflare managed challenge from
about 18:25 UTC on 2026-11-17 (HTTP 403, Cf-Mitigated: challenge, a page titled
"Vérification de sécurité / Security Check"). The wording each place gives the caller is
checked here in English and in French: no "retry in a minute", and the sources that still
work. A challenge never opens the breaker (WDS answers on the host that challenges SDMX), so
only the error a challenged call raises and the hint for one raised elsewhere carry it.
Everything is offline.
"""

from __future__ import annotations

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from maplestats_mcp.catalogue import read_catalogue
from maplestats_mcp.server import mcp
from maplestats_mcp.shared import blocked_hosts
from maplestats_mcp.shared.breaker import BREAKER
from maplestats_mcp.shared.error_hints import error_code, hint_for, with_hint
from maplestats_mcp.shared.errors import CloudflareChallenge, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, is_cloudflare_challenge
from maplestats_mcp.shared.i18n import reset_call_lang, set_call_lang

HOST = "www150.statcan.gc.ca"
URL = f"https://{HOST}/t1/wds/rest/getCodeSets"
RETRY_IN_A_MINUTE = "Retry once in a minute"
RETRY_IN_A_MINUTE_FR = "Réessayez une fois dans une minute"


async def _challenged(httpx_mock, statcan_security_check) -> CloudflareChallenge:
    httpx_mock.add_response(url=URL, **statcan_security_check)
    with pytest.raises(CloudflareChallenge) as raised:
        await api_get(URL)
    return raised.value


def _in_french(call):
    token = set_call_lang("fr")
    try:
        return call()
    finally:
        reset_call_lang(token)


# 1. The body check ----


def _response(status: int, content: bytes, headers: dict[str, str] | None = None):
    request = httpx.Request("GET", "https://www150.statcan.gc.ca/x")
    return httpx.Response(status, content=content, headers=headers or {}, request=request)


@pytest.mark.parametrize(
    "title",
    [
        "Vérification de sécurité / Security Check".encode(),
        b"Security Check",
        b"V&eacute;rification de s&eacute;curit&eacute;",
        b"verification de securite",
        b"SECURITY CHECK",
    ],
)
def test_statcan_security_check_page_is_a_challenge_without_its_header(title: bytes):
    page = b"<!DOCTYPE html><html><head><title>" + title + b"</title></head><body></body></html>"
    assert is_cloudflare_challenge(_response(403, page))


def test_just_a_moment_is_still_a_challenge_without_its_header():
    assert is_cloudflare_challenge(_response(403, b"<title>Just a moment...</title>"))


@pytest.mark.parametrize(
    ("status", "content"),
    [
        (403, b"<html><head><title>Forbidden</title></head><body>Access denied.</body></html>"),
        # A page that talks about a security check is not a challenge: the title decides.
        (403, b"<title>Terms</title><p>Complete the Security Check to continue.</p>"),
        # Only a 403 is read for its text; the header carries the rest.
        (200, b"<title>Security Check</title>"),
        (404, b"<title>Security Check</title>"),
    ],
)
def test_other_pages_are_not_challenges_without_the_header(status: int, content: bytes):
    assert not is_cloudflare_challenge(_response(status, content))


def test_the_header_alone_makes_a_challenge():
    headers = {"Cf-Mitigated": "challenge"}
    assert is_cloudflare_challenge(_response(403, b"anything", headers))
    assert is_cloudflare_challenge(_response(503, b"", headers))


async def test_a_header_less_security_check_page_counts_against_the_host(
    httpx_mock, statcan_security_check
):
    headers = {k: v for k, v in statcan_security_check["headers"].items() if k != "Cf-Mitigated"}
    httpx_mock.add_response(url=URL, **{**statcan_security_check, "headers": headers})
    with pytest.raises(CloudflareChallenge, match="Cloudflare bot challenge"):
        await api_get(URL)
    assert BREAKER.snapshot()["hosts"][f"{HOST}/wds"]["errors"]["cloudflare"] == 1


# 2. The error a challenged call raises ----


async def test_a_challenge_says_do_not_retry_and_what_still_works(
    httpx_mock, statcan_security_check
):
    error = await _challenged(httpx_mock, statcan_security_check)
    message = str(error)
    assert isinstance(error, UpstreamUnavailable) and error.host == HOST
    assert "Cloudflare bot challenge" in message and "does not try to bypass" in message
    assert "Fix: do not retry; StatCan's host www150.statcan.gc.ca is challenging" in message
    assert "not answer from memory" in message
    for source in (
        "api.statcan.gc.ca",
        "geo.statcan.gc.ca",
        "Bank of Canada",
        "CMHC",
        "provincial",
        "OECD",
    ):
        assert source in message
    assert RETRY_IN_A_MINUTE not in message


async def test_the_french_challenge_error_is_french(httpx_mock, statcan_security_check):
    httpx_mock.add_response(url=URL, **statcan_security_check)
    token = set_call_lang("fr")
    try:
        with pytest.raises(CloudflareChallenge) as raised:
            await api_get(URL)
    finally:
        reset_call_lang(token)
    message = str(raised.value)
    assert "défi anti-robot Cloudflare" in message
    assert "Solution : ne réessayez pas" in message
    assert "l'hôte de Statistique Canada www150.statcan.gc.ca" in message
    assert "Toujours accessibles" in message and "la Banque du Canada" in message
    assert "Fix:" not in message and "Still working" not in message
    assert RETRY_IN_A_MINUTE_FR not in message


async def test_the_challenge_error_gets_its_code_but_no_generic_retry_hint(
    httpx_mock, statcan_security_check
):
    error = await _challenged(httpx_mock, statcan_security_check)
    hinted = with_hint(error, "en")
    assert hinted is not None
    text = str(hinted)
    assert text.startswith("[upstream_unavailable] ")
    assert RETRY_IN_A_MINUTE not in text and "down or slow" not in text
    assert text.count("Fix:") == 1
    # The error keeps its class, so usage counting and the smoke runner still read it.
    assert isinstance(hinted, CloudflareChallenge)
    assert error_code(error) == "upstream_unavailable"


async def test_another_host_gets_the_generic_steer_not_statcans_list(
    httpx_mock, cloudflare_challenge
):
    url = "https://data.example.invalid/x"
    httpx_mock.add_response(url=url, **cloudflare_challenge)
    with pytest.raises(CloudflareChallenge) as raised:
        await api_get(url)
    message = str(raised.value)
    assert "Fix: do not retry; the host data.example.invalid is challenging" in message
    assert "If search_tools or plan_query lists another source" in message
    assert "api.statcan.gc.ca" not in message and "Statistique" not in message


# 3. The hint for a challenge with no message of its own ----


def test_a_challenge_raised_without_a_message_of_its_own_still_says_do_not_retry():
    bare = CloudflareChallenge("a module's own text")
    hint = hint_for(bare, "en")
    assert hint.startswith("Fix: do not retry") and "retry once" not in hint.lower()
    assert RETRY_IN_A_MINUTE not in hint
    french = hint_for(bare, "fr")
    assert french.startswith("Solution : ne réessayez pas")
    assert RETRY_IN_A_MINUTE_FR not in french
    # A plain outage keeps the retry hint.
    assert RETRY_IN_A_MINUTE in hint_for(UpstreamUnavailable("down"), "en")
    assert RETRY_IN_A_MINUTE_FR in hint_for(UpstreamUnavailable("down"), "fr")


# 4. The shared wording ----


def test_still_working_names_only_sources_the_server_has():
    """Each prefix the messages name is a family of tools in the registry (the CCEI space,
    the census profile, the geo layers, the Bank of Canada, CMHC, the OECD)."""
    catalogue = read_catalogue()
    assert catalogue is not None
    names = [
        tool["name"] if isinstance(tool, dict) else tool
        for module in catalogue.values()
        for tool in module["tools"]
    ]
    for prefix in blocked_hosts.STILL_WORKING_PREFIXES:
        assert any(name.startswith(prefix) for name in names), prefix
        assert prefix in blocked_hosts.still_working(HOST, False), prefix
        assert prefix in blocked_hosts.still_working(HOST, True), prefix


def test_only_statcan_hosts_get_the_statcan_list():
    assert blocked_hosts.still_working("www12.statcan.gc.ca", False).startswith(" Still working")
    assert "api.statcan.gc.ca" not in blocked_hosts.still_working("example.invalid", False)


# 5. Through the server, as a client sees it ----


async def test_a_wds_tool_answers_the_block_with_its_fixes_and_no_retry_hint(
    httpx_mock, statcan_security_check
):
    """wds_get_cube_metadata through call_tool, with www150 challenging: the error a model
    reads names the block and what works, and does not say to retry in a minute."""
    httpx_mock.add_response(is_reusable=True, **statcan_security_check)
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as raised:
            await client.call_tool(
                "call_tool",
                {"name": "wds_get_cube_metadata", "arguments": {"product_id": "14100287"}},
            )
    text = str(raised.value)
    assert "[upstream_unavailable]" in text
    # The challenge's own fix, then the cube-metadata tool's: no other source carries WDS member ids.
    assert text.count("Fix:") == 2 and "do not retry" in text
    assert "carried by no other source" in text
    assert "Still working: api.statcan.gc.ca" in text
    assert RETRY_IN_A_MINUTE not in text and "down or slow" not in text
