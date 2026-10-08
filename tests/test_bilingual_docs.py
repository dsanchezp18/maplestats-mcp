"""Prompts and docs:// resources answer in the language asked for.

Every prompt takes `lang`; before, "fr" returned the English text. Resources
cannot take a parameter (that would make them templates), so each English
`docs://<module>/<name>` has a French twin at `docs://<module>/fr/<name>`.
"""

from __future__ import annotations

import re

import pytest
from fastmcp import Client
from mcp.types import TextContent, TextResourceContents

from maplestats_mcp.server import mcp

# prompt name -> (arguments, a phrase only the French body has)
PROMPTS = {
    "find_and_fetch_boc_series": ({"topic": "inflation"}, "Pour trouver et obtenir"),
    "compare_boc_series": ({"series_names": "FXUSDCAD, FXEURCAD"}, "Pour comparer"),
    "find_and_query_cmhc_table": ({"topic": "loyers"}, "Pour trouver et obtenir"),
    "find_and_query_eccc_collection": ({"topic": "crues"}, "Pour trouver et obtenir"),
    "eccc_severe_weather_check": ({"location": "Québec"}, "Pour vérifier les alertes"),
    "find_and_fetch_series": ({"topic": "chômage"}, "Pour trouver et obtenir"),
    "look_up_classification": ({"topic": "commerce de détail"}, "Pour chercher une classification"),
    "build_sdmx_or_key": (
        {"product_id": 18100004, "dimension_position": 2},
        "Pour interroger tous les codes",
    ),
}

# English resource uri -> French twin
TWINS = {
    "docs://boc/well-known-series": "docs://boc/fr/series-courantes",
    "docs://boc/gotchas": "docs://boc/fr/pieges",
    "docs://cmhc/well-known-categories": "docs://cmhc/fr/categories-courantes",
    "docs://cmhc/gotchas": "docs://cmhc/fr/pieges",
    "docs://eccc/well-known-collections": "docs://eccc/fr/collections-courantes",
    "docs://eccc/gotchas": "docs://eccc/fr/pieges",
    "docs://statcan/addressing": "docs://statcan/fr/adressage",
    "docs://statcan/gotchas": "docs://statcan/fr/pieges",
}

_URI = re.compile(r"docs://[a-z0-9/_-]+")


async def _prompt_text(name: str, arguments: dict[str, object], lang: str) -> str:
    async with Client(mcp) as client:
        result = await client.get_prompt(
            name, {**{k: str(v) for k, v in arguments.items()}, "lang": lang}
        )
    return "\n".join(m.content.text for m in result.messages if isinstance(m.content, TextContent))


async def _resource_text(client: Client, uri: str) -> str:
    contents = await client.read_resource(uri)
    return "".join(c.text for c in contents if isinstance(c, TextResourceContents))


@pytest.mark.parametrize("name", PROMPTS)
async def test_prompt_body_follows_lang(name):
    arguments, french_phrase = PROMPTS[name]
    english = await _prompt_text(name, arguments, "en")
    french = await _prompt_text(name, arguments, "fr")
    assert english != french
    assert french_phrase in french
    assert french_phrase not in english


@pytest.mark.parametrize("name", PROMPTS)
async def test_french_prompt_points_to_resources_that_exist(name):
    arguments, _ = PROMPTS[name]
    french = await _prompt_text(name, arguments, "fr")
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
    cited = set(_URI.findall(french))
    assert cited <= uris, sorted(cited - uris)
    # a French body sends the reader to the French twin where one exists
    english_only = {u for u in cited if u in TWINS}
    assert not english_only, sorted(english_only)


async def test_every_docs_resource_has_a_french_twin():
    async with Client(mcp) as client:
        resources = {str(r.uri): r for r in await client.list_resources()}
        for english, french in TWINS.items():
            assert english in resources and french in resources, (english, french)
            en_text = await _resource_text(client, english)
            fr_text = await _resource_text(client, french)
            assert fr_text != en_text
            # the French twin is written for a francophone reader, not copied
            assert re.search(r"\b(le|la|les|des|une|pour|dans)\b", fr_text)
            assert len(fr_text) > 0.6 * len(en_text), french
