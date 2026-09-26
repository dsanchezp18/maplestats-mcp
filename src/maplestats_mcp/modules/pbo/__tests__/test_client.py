"""Tests on records trimmed from the PBO distribution API (2026-09-26)."""

from __future__ import annotations

import base64
import re

import pytest
import yaml

from maplestats_mcp.modules.pbo import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_PBOML = {
    "pboml": {"version": "1.0.0"},
    "document": {"id": "LEG-2526-012-S"},
    "slices": [
        {"type": "heading", "content": {"en": "Summary", "fr": "Résumé"}},
        {"type": "markdown", "content": {"en": "The measure costs $2.4 billion.", "fr": "x"}},
        {
            "type": "table",
            "referenced_as": {"en": "Table 1", "fr": "Tableau 1"},
            "label": {"en": "5-Year Cost", "fr": "Coût sur 5 ans"},
            "sources": [{"en": "PBO.", "fr": "DPB."}],
            "variables": {
                "year": {"label": {"en": "Fiscal year", "fr": "Exercice"}, "is_descriptive": True},
                "cost": {"label": {"en": "Total cost", "fr": "Coût total"}, "type": "number"},
            },
            "content": [{"year": {"en": "2025-2026", "fr": "2025-2026"}, "cost": 2393}],
        },
        {
            "type": "html",
            "content": {"en": "<table><tr><td>GDP</td><td>1.7</td></tr><tr></tr></table>"},
        },
        {"type": "kvlist", "print_only": True, "content": [{"key": {"content": "author"}}]},
        {
            "type": "kvlist",
            "label": {"en": "Data Sources"},
            "content": [
                {"key": {"content": {"en": "Model"}}, "value": {"content": {"en": "SPSD/M"}}}
            ],
        },
        {"type": "svg", "content": "<svg/>"},
    ],
}
_RECORD = {
    "id": "LEG-2526-012-S",
    "type": "LEG",
    "title_en": "Accelerated capital cost allowance",
    "title_fr": "Déduction pour amortissement accéléré",
    "release_date": "2026-02-18T05:00:00.000000Z",
    "metadata": {"abstract_en": "This note provides a cost estimate.", "abstract_fr": "Note."},
    "permalinks": {"en": {"website": "https://www.pbo-dpb.ca/en/publications/LEG-2526-012-S"}},
    "artifacts": {"main": {"en": {"public": "https://distribution.pbo-dpb.ca/abc"}}},
    "pboml_document": {
        "data-url": "data:text/yaml;base64,"
        + base64.b64encode(
            yaml.safe_dump(_PBOML, sort_keys=False, allow_unicode=True).encode()
        ).decode()
    },
}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _url(path: str) -> re.Pattern[str]:
    return re.compile(re.escape(constants.API + path) + r"(\?.*)?$")


async def test_publication_tables_and_text(httpx_mock):
    httpx_mock.add_response(url=_url("publications/LEG-2526-012-S"), json={"data": _RECORD})
    result = await client.get_publication("leg-2526-012-s")
    assert result.has_structured_content
    assert result.publication.type_label == "Legislative costing note"
    assert result.publication.pdf_url == "https://distribution.pbo-dpb.ca/abc"
    table, html, kv = result.tables
    assert table.reference == "Table 1" and table.columns == ["Fiscal year", "Total cost"]
    assert table.rows == [{"Fiscal year": "2025-2026", "Total cost": 2393}]
    assert table.sources == ["PBO."]
    assert html.kind == "html" and html.cells == [["GDP", "1.7"]]
    assert kv.rows == [{"key": "Model", "value": "SPSD/M"}]  # print_only credits skipped
    assert result.text == "## Summary\n\nThe measure costs $2.4 billion."


async def test_french_labels(httpx_mock):
    httpx_mock.add_response(url=_url("publications/LEG-2526-012-S"), json=_RECORD)
    result = await client.get_publication("LEG-2526-012-S", lang="fr")
    assert result.tables[0].columns == ["Exercice", "Coût total"]
    assert result.publication.title.startswith("Déduction")


async def test_archived_publication_has_no_structure(httpx_mock):
    record = {**_RECORD, "id": "LIBARC-0809-001", "type": "LIBARC", "pboml_document": None}
    httpx_mock.add_response(url=_url("publications/LIBARC-0809-001"), json=record)
    result = await client.get_publication("LIBARC-0809-001")
    assert not result.has_structured_content and result.tables == [] and result.text is None


async def test_list_and_search(httpx_mock):
    httpx_mock.add_response(
        url=_url("publications"),
        json={"data": [_RECORD], "meta": {"total": 17, "current_page": 1, "last_page": 2}},
    )
    listing = await client.search_publications(types=["LEG"])
    assert listing.total_matched == 17 and listing.last_page == 2
    assert listing.publications[0].abstract == "This note provides a cost estimate."
    httpx_mock.add_response(
        url=_url("search"),
        json=[
            {"type": "Publication", "score": 1000, "payload": _RECORD},
            {"type": "Blog", "score": 900, "payload": {"id": "x"}},
            {"type": "Publication", "score": 800, "payload": {**_RECORD, "type": "RP"}},
        ],
    )
    found = await client.search_publications("capital cost", types=["LEG"])
    assert found.total_matched == 1 and found.publications[0].id == "LEG-2526-012-S"


async def test_errors(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.get_publication("../etc")
    with pytest.raises(InvalidInput):
        await client.search_publications(types=["XX"])
    httpx_mock.add_response(url=_url("publications/RP-9999-999-S"), status_code=404)
    with pytest.raises(NotFound):
        await client.get_publication("RP-9999-999-S")
