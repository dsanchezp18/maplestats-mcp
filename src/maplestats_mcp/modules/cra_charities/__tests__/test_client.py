"""Tests for cra_charities/client.py, shaped on the live payloads read 2026-10-10."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from maplestats_mcp.modules.cra_charities import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_IDENT = "ident-resource"
_GEN = "general-resource"
_DIR = "directors-resource"

_PACKAGES = {
    "success": True,
    "result": {
        "results": [
            {"id": "old", "title": "2023 List of charities", "resources": []},
            {
                "id": "pkg2024",
                "title": "2024 List of charities",
                "resources": [
                    {"id": "pdf", "name": "Codes Lists", "datastore_active": False},
                    {"id": _IDENT, "name": "Identification", "datastore_active": True},
                    {"id": _GEN, "name": "General information", "datastore_active": True},
                    {
                        "id": _DIR,
                        "name": "Charities Businesses Directors/Officers",
                        "datastore_active": True,
                    },
                ],
            },
            {"id": "other", "title": "CEWS Registry", "resources": []},
        ]
    },
}

_ROW = {
    "BN": "119219814RR0001",
    "Category": "0100",
    "Sub Category": "0099",
    "Designation": "C",
    "Legal Name": "THE CANADIAN RED CROSS SOCIETY",
    "Account Name": "THE CANADIAN RED CROSS SOCIETY LA SOCI�T�",
    "Address Line 1": "B - 120 MCDONALD ST",
    "Address Line 2": None,
    "City": "SAINT JOHN",
    "Province": "NB",
    "Postal Code": "E2J1M5",
    "Country": "CA",
}


def _ds(records, total=None):
    return {"success": True, "result": {"records": records, "total": total or len(records)}}


def _discovery(httpx_mock):
    httpx_mock.add_response(url=re.compile(r".*package_search.*"), json=_PACKAGES)


async def test_search_resolves_newest_year_and_parses(httpx_mock):
    _discovery(httpx_mock)
    httpx_mock.add_response(url=re.compile(r".*datastore_search.*"), json=_ds([_ROW], 7))
    result = await client.search_charities("red cross", province="nb", lang="fr")
    assert result.list_year == 2024
    assert result.total_count == 7
    charity = result.charities[0]
    assert charity.designation == "Organisme de bienfaisance"
    assert charity.address_line_2 is None
    request = httpx_mock.get_requests()[-1]
    assert f"resource_id={_IDENT}" in str(request.url)
    assert json.loads(request.url.params["filters"]) == {"Province": "NB"}
    assert request.url.params["q"] == "red cross"
    assert (
        result.provenance.licence and "Licence du gouvernement ouvert" in result.provenance.licence
    )


async def test_search_with_business_number_is_exact_filter(httpx_mock):
    _discovery(httpx_mock)
    httpx_mock.add_response(url=re.compile(r".*datastore_search.*"), json=_ds([_ROW]))
    await client.search_charities("119219814")
    request = httpx_mock.get_requests()[-1]
    assert json.loads(request.url.params["filters"]) == {"BN": "119219814RR0001"}
    assert "q" not in request.url.params


async def test_search_requires_a_criterion_and_valid_codes():
    with pytest.raises(InvalidInput):
        await client.search_charities()
    with pytest.raises(InvalidInput):
        await client.search_charities("x", designation="Z")
    with pytest.raises(InvalidInput):
        await client.search_charities("x", province="Ontario")
    with pytest.raises(InvalidInput):
        await client.search_charities("x", limit=0)


async def test_falls_back_to_pinned_list_when_discovery_finds_nothing(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*package_search.*"), json={"success": True, "result": {"results": []}}
    )
    httpx_mock.add_response(url=re.compile(r".*datastore_search.*"), json=_ds([_ROW]))
    result = await client.search_charities("red cross")
    assert result.list_year == constants.FALLBACK_YEAR
    request = httpx_mock.get_requests()[-1]
    assert constants.FALLBACK_RESOURCES["Identification"] in str(request.url)


async def test_get_charity_joins_general_information(httpx_mock):
    _discovery(httpx_mock)
    httpx_mock.add_response(url=re.compile(r".*datastore_search.*"), json=_ds([_ROW]))
    httpx_mock.add_response(
        url=re.compile(r".*datastore_search.*"),
        json=_ds(
            [
                {
                    "BN": _ROW["BN"],
                    "FPE": "2024-03-31",
                    "Program #1 Code": "10",
                    "Program #1 %": "100",
                    "Program #1 Desc": "Relief",
                    "Program #2 Code": None,
                    "Program #2 %": None,
                    "Program #2 Desc": None,
                }
            ]
        ),
    )
    detail = await client.get_charity("119 219 814 rr0001")
    assert detail.fiscal_period_end == date(2024, 3, 31)
    assert [p.description for p in detail.programs] == ["Relief"]
    assert detail.charity.city == "SAINT JOHN"


async def test_get_charity_not_found(httpx_mock):
    _discovery(httpx_mock)
    httpx_mock.add_response(url=re.compile(r".*datastore_search.*"), json=_ds([]))
    with pytest.raises(NotFound):
        await client.get_charity("000000000")


async def test_bad_business_number_is_refused():
    with pytest.raises(InvalidInput):
        await client.get_charity("12345")


async def test_get_directors_parses_flags_and_dates(httpx_mock):
    _discovery(httpx_mock)
    httpx_mock.add_response(
        url=re.compile(r".*datastore_search.*"),
        json=_ds(
            [
                {
                    "BN": _ROW["BN"],
                    "FPE": "2024-03-31",
                    "Last Name": "HUBBS",
                    "First Name": "MIRANDA",
                    "Initials": None,
                    "Position": "CHAIR",
                    "At Arm's Length": "Y",
                    "Start Date": "2017-06-17",
                    "End Date": None,
                },
                {
                    "BN": _ROW["BN"],
                    "FPE": "2024-03-31",
                    "Last Name": "GILES",
                    "First Name": "GAVIN",
                    "Position": "DIRECTOR",
                    "At Arm's Length": "N",
                    "Start Date": "2010-06-20",
                    "End Date": "2023-06-25",
                },
            ],
            20,
        ),
    )
    result = await client.get_directors("119219814")
    assert result.total_count == 20 and result.returned_count == 2
    assert result.directors[0].at_arms_length is True
    assert result.directors[1].at_arms_length is False
    assert result.directors[1].end_date == date(2023, 6, 25)
