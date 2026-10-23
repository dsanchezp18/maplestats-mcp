"""Typed errors raised below a tool read the call's language: French for lang="fr".

Each case triggers a real error path in a module that used to raise English only,
once in English (unchanged) and once with the call language set to French.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from maplestats_mcp.modules.elections_provincial import manitoba
from maplestats_mcp.modules.health_products import api as health_api
from maplestats_mcp.modules.nfd import client as nfd
from maplestats_mcp.modules.reproduce import builders
from maplestats_mcp.shared import http, i18n
from maplestats_mcp.shared.errors import CloudflareChallenge, InvalidInput, UpstreamError


def _challenge() -> None:
    request = httpx.Request("GET", "https://www150.statcan.gc.ca/x")
    response = httpx.Response(403, content=b"Just a moment", request=request)
    http.raise_if_cloudflare_challenge(response)


CASES: list[tuple[str, Callable[[], Any], type[Exception], str, str]] = [
    (
        "nfd empty file",
        lambda: nfd.parse_table("", "https://x/t.csv", None),
        UpstreamError,
        "is empty",
        "est vide",
    ),
    (
        "manitoba missing header",
        lambda: manitoba._header_row([], "summary of results"),
        UpstreamError,
        "has no 'Electoral Division' header",
        "n'a pas d'en-tête",
    ),
    (
        "health products not rows",
        lambda: health_api.as_list("nope"),
        UpstreamError,
        "is not JSON rows",
        "n'est pas composée de lignes JSON",
    ),
    (
        "reproduce bad count",
        lambda: builders._count("x", "limit"),
        InvalidInput,
        "must be a whole number",
        "doit être un nombre entier",
    ),
    (
        "cloudflare challenge",
        _challenge,
        CloudflareChallenge,
        "Cloudflare bot challenge",
        "défi anti-robot Cloudflare",
    ),
]


@pytest.mark.parametrize(("label", "call", "error", "english", "french"), CASES)
def test_the_error_is_english_by_default_and_french_for_a_french_call(
    label: str, call: Callable[[], Any], error: type[Exception], english: str, french: str
) -> None:
    with pytest.raises(error) as plain:
        call()
    assert english in str(plain.value), label

    token = i18n.set_call_lang("fr")
    try:
        with pytest.raises(error) as localized:
            call()
    finally:
        i18n.reset_call_lang(token)
    assert french in str(localized.value), label
    assert english not in str(localized.value), label
