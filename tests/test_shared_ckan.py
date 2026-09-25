from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.shared.ckan import (
    CkanConfig,
    action,
    excerpt,
    parse_dt,
    pick_fra,
    pick_translated,
    pick_translated_list,
    to_bool,
)
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

_CONFIG = CkanConfig(
    source="ckan-test",
    base_url="https://example.invalid/api/3/action/",
    rate_limit_per_second=100.0,
    rate_limit_capacity=100.0,
)


async def test_action_unwraps_successful_envelope(httpx_mock):
    httpx_mock.add_response(
        url="https://example.invalid/api/3/action/site_read",
        json={"help": "h", "success": True, "result": True},
    )
    result = await action(_CONFIG, "site_read")
    assert result is True


async def test_action_raises_not_found_on_404(httpx_mock):
    httpx_mock.add_response(
        url="https://example.invalid/api/3/action/package_show?id=missing",
        status_code=404,
        json={"success": False, "error": {"__type": "Not Found Error", "message": "Not found"}},
    )
    with pytest.raises(NotFound, match="Not found"):
        await action(_CONFIG, "package_show", params={"id": "missing"})


async def test_action_raises_invalid_input_on_400(httpx_mock):
    httpx_mock.add_response(
        url="https://example.invalid/api/3/action/package_search?sort=bogus",
        status_code=400,
        json={"success": False, "error": {"__type": "Search Query Error", "message": "bad sort"}},
    )
    with pytest.raises(InvalidInput, match="bad sort"):
        await action(_CONFIG, "package_search", params={"sort": "bogus"})


async def test_action_raises_upstream_error_on_unsuccessful_envelope(httpx_mock):
    """A 200 response with success: false is a distinct failure mode from
    a 4xx status - still not something a caller should treat as data."""
    httpx_mock.add_response(
        url="https://example.invalid/api/3/action/site_read",
        json={"help": "h", "success": False, "result": None},
    )
    with pytest.raises(UpstreamError):
        await action(_CONFIG, "site_read")


async def test_action_raises_upstream_error_on_missing_result_key(httpx_mock):
    """success: true with no "result" key at all (e.g. a misbehaving
    intermediary CDN/WAF) must not leak a raw KeyError past the typed
    error boundary."""
    httpx_mock.add_response(
        url="https://example.invalid/api/3/action/site_read",
        json={"help": "h", "success": True},
    )
    with pytest.raises(UpstreamError):
        await action(_CONFIG, "site_read")


async def test_action_raises_invalid_input_on_409(httpx_mock):
    """Confirmed live on ckan_montreal: some CKAN deployments return 409
    (not 400) for a malformed fq -- still a caller-input problem, not an
    upstream failure, so every non-404 4xx maps to InvalidInput."""
    httpx_mock.add_response(
        url="https://example.invalid/api/3/action/package_search?fq=bad",
        status_code=409,
        json={"success": False, "error": {"__type": "Search Error", "message": "bad fq"}},
    )
    with pytest.raises(InvalidInput, match="bad fq"):
        await action(_CONFIG, "package_search", params={"fq": "bad"})


async def test_action_raises_upstream_unavailable_on_timeout(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await action(_CONFIG, "site_read")


def test_pick_translated_falls_back_to_english_then_flat():
    assert pick_translated("flat", {"en": "english", "fr": "french"}, "fr") == "french"
    assert pick_translated("flat", {"en": "english"}, "fr") == "english"
    assert pick_translated("flat", None, "fr") == "flat"
    assert pick_translated(None, None, "fr") == ""


def test_pick_translated_keeps_genuinely_empty_string():
    """A publisher deliberately left the French field blank - that is a
    real, present answer, not a missing translation to backfill."""
    assert pick_translated("flat", {"en": "english", "fr": ""}, "fr") == ""


def test_pick_translated_list_keeps_genuinely_empty_list():
    assert pick_translated_list({"en": ["a"], "fr": []}, "fr") == []
    assert pick_translated_list({"en": ["a"]}, "fr") == ["a"]
    assert pick_translated_list(None, "fr") == []


def test_pick_fra_only_applies_for_french():
    assert pick_fra("base", "fra", "fr") == "fra"
    assert pick_fra("base", "fra", "en") == "base"
    assert pick_fra("base", None, "fr") == "base"


def test_pick_fra_keeps_genuinely_empty_string():
    assert pick_fra("base", "", "fr") == ""


def test_parse_dt_handles_missing_and_invalid():
    assert parse_dt(None) is None
    assert parse_dt("") is None
    assert parse_dt("not-a-date") is None
    assert parse_dt("2024-01-01T00:00:00") is not None


def test_excerpt_truncates_with_ellipsis():
    assert excerpt("short", 10) == "short"
    assert excerpt("a very long string indeed", 10) == "a very lon…"


def test_excerpt_handles_zero_max_length():
    assert excerpt("anything", 0) == ""


def test_to_bool_handles_real_bools_and_ckan_string_booleans():
    assert to_bool(True) is True
    assert to_bool(False) is False
    assert to_bool("true") is True
    assert to_bool("True") is True
    assert to_bool("false") is False
    assert to_bool("False") is False
    assert to_bool(None) is False
