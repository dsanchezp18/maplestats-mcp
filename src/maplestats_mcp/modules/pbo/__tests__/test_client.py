"""Tests on records trimmed from the PBO distribution API (2026-09-26)."""

from __future__ import annotations

import base64
import re
from datetime import date

import pytest
import yaml
from bs4 import BeautifulSoup, Tag

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
    # The chart and the print-only credits are counted, and the limits say so.
    assert result.left_out == {"kvlist": 1, "svg": 1}
    assert (result.provenance.limits or "").startswith("Left out: 1 kvlist, 1 svg slice(s)")


async def test_french_labels(httpx_mock):
    httpx_mock.add_response(url=_url("publications/LEG-2526-012-S"), json=_RECORD)
    result = await client.get_publication("LEG-2526-012-S", lang="fr")
    assert result.tables[0].columns == ["Exercice", "Coût total"]
    assert result.publication.title.startswith("Déduction")


def _publication_with(*slices: dict) -> dict:
    document = {**_PBOML, "slices": list(slices)}
    dumped = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    encoded = base64.b64encode(dumped.encode()).decode()
    return {**_RECORD, "pboml_document": {"data-url": "data:text/yaml;base64," + encoded}}


async def test_variables_with_the_same_label_keep_their_own_column(httpx_mock):
    # Rows were keyed by label, so two variables both labelled "2025-26" (one per
    # scenario) collapsed into one key and the later value overwrote the earlier.
    slice_ = {
        "type": "table",
        "variables": {
            "item": {"label": {"en": "Item"}, "is_descriptive": True},
            "baseline": {"label": {"en": "2025-26"}},
            "downside": {"label": {"en": "2025-26"}},
            "third": {"label": {"en": "2025-26"}},
            # A label already shaped like a numbered one is not reused for another column.
            "literal": {"label": {"en": "2025-26 (2)"}},
        },
        "content": [{"item": "GDP", "baseline": 1.7, "downside": 0.9, "third": 0.5, "literal": 4}],
    }
    httpx_mock.add_response(url=_url("publications/LEG-2526-012-S"), json=_publication_with(slice_))
    table = (await client.get_publication("LEG-2526-012-S")).tables[0]
    assert table.columns == ["Item", "2025-26", "2025-26 (3)", "2025-26 (4)", "2025-26 (2)"]
    assert table.rows == [
        {
            "Item": "GDP",
            "2025-26": 1.7,
            "2025-26 (3)": 0.9,
            "2025-26 (4)": 0.5,
            "2025-26 (2)": 4,
        }
    ]


async def test_html_tables_expand_colspan_and_rowspan(httpx_mock):
    # Cells were listed as written, so a header over two columns or a label spanning two
    # rows left the header cells short of the data under them.
    html = (
        '<table><tr><th rowspan="2">Item</th><th colspan="2">2025-26</th></tr>'
        "<tr><th>Low</th><th>High</th></tr>"
        "<tr><td>GDP</td><td>1.7</td><td>2.1</td></tr>"
        '<tr><td colspan="x">Note</td><td colspan="0">kept</td></tr></table>'
    )
    httpx_mock.add_response(
        url=_url("publications/LEG-2526-012-S"),
        json=_publication_with({"type": "html", "content": {"en": html}}),
    )
    table = (await client.get_publication("LEG-2526-012-S")).tables[0]
    assert table.cells == [
        ["Item", "2025-26", "2025-26"],
        ["Item", "Low", "High"],
        ["GDP", "1.7", "2.1"],
        ["Note", "kept"],
    ]


async def test_a_rowspan_cell_keeps_its_column_when_a_later_row_ends_before_it(httpx_mock):
    # A cell carried down past the end of a row's own cells was added only when it came
    # right after them, so with a gap in between (the row ends at column 0, the carried
    # "c" sits at column 2) it was dropped from the rows below.
    html = (
        '<table><tr><th rowspan="2">a</th><th>b</th><th rowspan="3">c</th></tr>'
        "<tr><td>1</td></tr><tr><td>2</td></tr></table>"
    )
    httpx_mock.add_response(
        url=_url("publications/LEG-2526-012-S"),
        json=_publication_with({"type": "html", "content": {"en": html}}),
    )
    table = (await client.get_publication("LEG-2526-012-S")).tables[0]
    assert table.cells == [["a", "b", "c"], ["a", "1", "c"], ["2", "", "c"]]


def _grid(html: str) -> list[list[str]]:
    table = BeautifulSoup(html, "html.parser").find("table")
    assert isinstance(table, Tag)
    return client._html_grid(table)


def test_spans_are_counts_a_table_cannot_turn_into_millions_of_cells():
    cell = BeautifulSoup('<td colspan="100000000" rowspan="x">c</td>', "html.parser").td
    assert cell is not None
    # Browsers read at most 1000 columns; a rowspan is cut to the rows the table has left.
    assert client._span(cell, "colspan", constants.HTML_MAX_COLSPAN) == 1000
    assert client._span(cell, "rowspan", 5) == 1
    for raw, expected in [
        ("3", 3),
        ("0", 1),
        ("-2", 1),
        (" 4 ", 4),
        ("9" * 10, 5),
        ("9" * 5000, 5),
    ]:
        cell = BeautifulSoup(f'<td rowspan="{raw}">c</td>', "html.parser").td
        assert cell is not None
        assert client._span(cell, "rowspan", 5) == min(expected, 5), raw
    # "²" is a digit to str.isdigit() but not to int(), which would raise.
    cell = BeautifulSoup('<td colspan="²">c</td>', "html.parser").td
    assert cell is not None
    assert client._span(cell, "colspan", 1000) == 1


def test_html_grid_caps_a_colspan_and_survives_a_number_too_long_for_int():
    assert [len(row) for row in _grid('<table><tr><td colspan="5000">x</td></tr></table>')] == [
        1000
    ]
    long_number = "9" * 5000
    assert [
        len(row) for row in _grid(f'<table><tr><td colspan="{long_number}">x</td></tr></table>')
    ] == [1000]


def test_spans_past_the_cell_budget_are_not_expanded(monkeypatch):
    # Cells that each span many rows and columns would expand to rows x columns entries
    # apiece; past the budget a span counts as 1.
    monkeypatch.setattr(constants, "HTML_MAX_SPAN_CELLS", 4)
    html = (
        '<table><tr><td colspan="4">a</td><td rowspan="3">b</td></tr>'
        "<tr><td>z</td></tr><tr><td>y</td></tr></table>"
    )
    assert _grid(html) == [["a", "a", "a", "a", "b"], ["z"], ["y"]]
    # A rowspan is counted as the rows the table has left (2 more here), not as written.
    html = (
        '<table><tr><td rowspan="65534">r</td></tr><tr><td>z</td></tr><tr><td>y</td></tr></table>'
    )
    assert _grid(html) == [["r"], ["r", "z"], ["r", "y"]]


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


async def test_french_department_count_falls_back_to_the_english_acronym(httpx_mock):
    # request_summary shows the English acronym when a department has no French one,
    # but the count by department used the French key alone and filed it as "unknown".
    ndb = {
        "name_en": "Federal Economic Development Agency",
        "name_fr": "Agence fédérale de développement économique",
        "acronym_en": "FedDev",
        "acronym_fr": None,
    }
    register = [_request(1, "IR0001", department=ndb), _request(2, "IR0002", department=ndb)]
    httpx_mock.add_response(
        url=_url("information-requests?page=1"),
        json={"data": register, "meta": {"current_page": 1, "last_page": 1, "total": 2}},
    )
    result = await client.search_information_requests(lang="fr")
    assert [r.department_acronym for r in result.requests] == ["FedDev", "FedDev"]
    assert result.by_department == {"FedDev": 2}


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
