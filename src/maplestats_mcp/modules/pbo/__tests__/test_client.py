"""Tests on records trimmed from the PBO distribution API (2026-09-26)."""

from __future__ import annotations

import base64
import re
from datetime import date

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


def _request(number: int, internal: str, **extra):
    record = {
        "id": number,
        "internal_id": internal,
        "request_date": "2025-02-24T00:00:00-05:00",
        "deadline_date": "2025-03-10T00:00:00-04:00",
        "extension_date": None,
        "request_status": "completed",
        "disposition_status": "all_disclosed",
        "summary_en": "Information about the Canada Housing Infrastructure Fund.",
        "summary_fr": "Informations concernant le Fonds canadien pour les infrastructures "
        "liées au logement.",
        "disposition_note_en": None,
        "disposition_note_fr": None,
        "permalinks": {"en": {"website": f"https://www.pbo-dpb.ca/en/x/{internal}"}},
        "department": {
            "name_en": "Housing, Infrastructure and Communities Canada",
            "name_fr": "Logement, Infrastructures et Collectivités Canada",
            "acronym_en": "HICC",
            "acronym_fr": "LICC",
        },
    }
    record.update(extra)
    return record


_DND = {
    "name_en": "National Defence",
    "name_fr": "Défense nationale",
    "acronym_en": "DND",
    "acronym_fr": "MDN",
}
_REGISTER = [
    _request(
        1126,
        "IR0957",
        request_date="2026-08-24T00:00:00-04:00",
        deadline_date="2026-09-08T00:00:00-04:00",
        extension_date="2026-09-29T00:00:00-04:00",
        request_status="pending",
        disposition_status=None,
    ),
    _request(
        1061,
        "IR0889",
        request_date="2026-01-08T00:00:00-05:00",
        deadline_date="2026-01-22T00:00:00-05:00",
        request_status="pending_correspondence",
        disposition_status=None,
        department=_DND,
        summary_en="Defence industrial strategy",
        summary_fr="Stratégie industrielle de défense",
    ),
    _request(979, "IR0816"),
    _request(
        718,
        "IR0080a",
        request_date="2008-12-01T00:00:00-05:00",
        disposition_status="nothing_disclosed",
        department=_DND,
        summary_en="Recurring: data on Economic and Fiscal Statement",
        summary_fr="Récurrent : données sur l'énoncé économique",
        disposition_note_en="Consult IR0080a for a copy of legal opinion.",
    ),
]


def _mock_register(httpx_mock):
    # Two pages, as the live list does (40 per page there).
    httpx_mock.add_response(
        url=_url("information-requests?page=1"),
        json={"data": _REGISTER[:2], "meta": {"current_page": 1, "last_page": 2, "total": 4}},
    )
    httpx_mock.add_response(
        url=_url("information-requests?page=2"),
        json={"data": _REGISTER[2:], "meta": {"current_page": 2, "last_page": 2, "total": 4}},
    )


async def test_information_request_register_filters_and_counts(httpx_mock, monkeypatch):
    monkeypatch.setattr(client, "_today", lambda: date(2026, 9, 27))
    _mock_register(httpx_mock)
    everything = await client.search_information_requests()
    assert everything.total_matched == 4
    assert everything.by_disposition == {"none": 2, "all_disclosed": 1, "nothing_disclosed": 1}
    assert everything.by_department == {"HICC": 2, "DND": 2}

    open_ = await client.search_information_requests(status="open")
    assert [r.id for r in open_.requests] == ["IR0957", "IR0889"]
    # The extension (Sept. 29) is not yet past; the DND request is 248 days late.
    assert [r.days_past_deadline for r in open_.requests] == [0, 248]

    dnd = await client.search_information_requests(department="défense")
    assert {r.id for r in dnd.requests} == {"IR0889", "IR0080a"}
    assert (await client.search_information_requests(department="mdn")).total_matched == 2

    french = await client.search_information_requests("liees au LOGEMENT", lang="fr")
    assert [r.id for r in french.requests] == ["IR0957", "IR0816"]
    assert french.requests[0].department_acronym == "LICC"
    assert french.requests[0].status_label == "En attente"

    dated = await client.search_information_requests(since="2025", until="2026-01")
    assert [r.id for r in dated.requests] == ["IR0889", "IR0816"]


async def test_information_request_letters(httpx_mock):
    _mock_register(httpx_mock)
    httpx_mock.add_response(
        url=_url("information-requests/718"),
        json={
            "data": {
                **_REGISTER[3],
                "contacts": [{"firstname": "not passed on"}],
                "files": [
                    {
                        "document_type": "request_letter",
                        "mime": "application/pdf",
                        "urls": {"en": {"public": "https://s3/en"}, "fr": {"public": None}},
                    },
                    {
                        "document_type": "reply_letter",
                        "mime": "application/pdf",
                        "bilingual": True,
                        "urls": {"public": "https://s3/both"},
                    },
                ],
            }
        },
    )
    result = await client.get_information_request("ir0080A", lang="fr")
    assert result.request.disposition_label == "Aucune communication"
    assert result.request.disposition_note == "Consult IR0080a for a copy of legal opinion."
    # The French letter is missing, so the English one stands in.
    assert [(f.label, f.url) for f in result.files] == [
        ("Lettre de demande", "https://s3/en"),
        ("Lettre de réponse", "https://s3/both"),
    ]
    assert "contacts" not in result.model_dump()


async def test_information_request_errors(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.get_information_request("../1")
    with pytest.raises(InvalidInput):
        await client.search_information_requests(status="late")
    with pytest.raises(InvalidInput):
        await client.search_information_requests(since="March 2024")
    _mock_register(httpx_mock)
    with pytest.raises(NotFound):
        await client.get_information_request("IR9999")


async def test_french_errors_and_provenance(httpx_mock):
    with pytest.raises(InvalidInput, match="^Entrée invalide : pbo : statut inconnu"):
        await client.search_information_requests(status="late", lang="fr")
    with pytest.raises(InvalidInput, match="AAAA, AAAA-MM ou AAAA-MM-JJ"):
        await client.search_information_requests(since="mars 2024", lang="fr")
    with pytest.raises(InvalidInput, match="since \\(2025\\) est postérieur à until"):
        await client.search_information_requests(since="2025", until="2024", lang="fr")
    _mock_register(httpx_mock)
    result = await client.search_information_requests(lang="fr")
    assert (result.provenance.coverage or "").endswith("les plus récentes d'abord")
    assert (result.provenance.freshness or "").startswith("au fil des publications du DPB")
    assert (result.provenance.licence or "").startswith(
        "Conditions du directeur parlementaire du budget"
    )
    with pytest.raises(NotFound, match="aucune demande d'information IR9999"):
        await client.get_information_request("IR9999", lang="fr")
