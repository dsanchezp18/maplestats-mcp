"""Represent error paths, null fields and paging, beyond test_client.py's happy paths.

The representative records below keep the shape of live responses captured
2026-10-03 from https://represent.opennorth.ca/representatives/house-of-commons/?limit=2
and https://represent.opennorth.ca/representatives/?limit=2&offset=3000: an
office may omit `tel` or `fax` altogether (not empty), `postal` holds line
breaks, `extra` carries `preferred_languages`, district names use an em dash
(sent as \\u2014), unknown text fields are "" rather than null, and every list
page's `meta` has `offset`, `limit`, `total_count`, `previous` and `next`
(a path, or null on the last page).
"""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.represent import client
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable

BASE = "https://represent.opennorth.ca"


def _url(path_and_query: str) -> re.Pattern[str]:
    return re.compile(re.escape(BASE + path_and_query))


PARM_BAINS = {
    "name": "Parm Bains",
    "district_name": "Richmond East—Steveston",
    "elected_office": "MP",
    "source_url": "https://www.ourcommons.ca/Members/en/search?caucusId=all&province=all",
    "first_name": "Parm",
    "last_name": "Bains",
    "party_name": "Liberal",
    "email": "parm.bains@parl.gc.ca",
    "url": "https://www.ourcommons.ca/Members/en/parm-bains(111067)",
    "personal_url": "",
    "photo_url": (
        "https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/"
        "BainsParm_Lib.jpg"
    ),
    "gender": "M",
    "offices": [
        {
            "fax": "1 613 992-1385",
            "tel": "1 613 992-1385",
            "type": "legislature",
            "postal": "House of Commons\nOttawa ON  K1A 0A6",
        },
        {
            "tel": "1 604 257-2900",
            "type": "constituency",
            "postal": "Main office - Richmond\n230-11331 Coppersmith Way\nRichmond BC  V7A 5J9",
        },
    ],
    "extra": {"preferred_languages": ["English"]},
    "representative_set_name": "House of Commons",
    "related": {
        "representative_set_url": "/representative-sets/house-of-commons/",
        "boundary_url": "/boundaries/federal-electoral-districts-2023-representation-order/59028/",
    },
}


def _bc_councillor(name: str, office: str, district: str, tel: str) -> dict:
    """A BC municipal record as served live: almost every text field is ""."""
    first, last = name.split()
    return {
        "name": name,
        "district_name": district,
        "elected_office": office,
        "source_url": "https://www.civicinfo.bc.ca/people",
        "first_name": first,
        "last_name": last,
        "party_name": "",
        "email": "",
        "url": "",
        "personal_url": "",
        "photo_url": "",
        "gender": "",
        "offices": [{"tel": tel, "type": "legislature"}],
        "extra": {},
        "representative_set_name": "British Columbia municipal councils",
        "related": {
            "representative_set_url": "/representative-sets/british-columbia-municipal-councils/",
            "boundary_url": "/boundaries/census-subdivisions/5955030/",
        },
    }


async def test_live_shaped_mp_record_parses_offices_and_extra(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representatives/?name__icontains=bains&limit=20&offset=0"),
        json={
            "objects": [PARM_BAINS],
            "meta": {"offset": 0, "limit": 20, "total_count": 1, "previous": None, "next": None},
        },
    )
    result = await client.search_representatives(name="bains")
    [mp] = result.representatives
    assert mp.level == "federal"
    assert mp.district_name == "Richmond East—Steveston"
    assert mp.personal_url is None
    assert mp.boundary and mp.boundary.endswith("/59028/")
    assert mp.extra == {"preferred_languages": ["English"]}
    # The second office has no fax key at all; it reads as absent, not an error.
    assert [(o.type, o.fax) for o in mp.offices] == [
        ("legislature", "1 613 992-1385"),
        ("constituency", None),
    ]
    assert mp.offices[1].postal and "\n230-11331 Coppersmith Way\n" in mp.offices[1].postal


async def test_municipal_scan_follows_meta_next_across_pages(httpx_mock, monkeypatch):
    # PAGE_SIZE shrunk to 2 so two live-shaped pages stand in for the four
    # 1,000-row pages a real scan of 3,810 representatives takes.
    monkeypatch.setattr(client.constants, "PAGE_SIZE", 2)
    httpx_mock.add_response(
        url=_url("/representatives/?elected_office__icontains=o&limit=2&offset=0"),
        json={
            "objects": [PARM_BAINS, _bc_councillor("Rob Fraser", "Mayor", "Taylor", "1")],
            "meta": {
                "offset": 0,
                "limit": 2,
                "total_count": 3,
                "previous": None,
                "next": "/representatives/?elected_office__icontains=o&limit=2&offset=2",
            },
        },
    )
    httpx_mock.add_response(
        url=_url("/representatives/?elected_office__icontains=o&limit=2&offset=2"),
        json={
            "objects": [_bc_councillor("Dan Rye", "Councillor", "Castlegar", "2")],
            "meta": {
                "offset": 2,
                "limit": 2,
                "total_count": 3,
                "previous": "/representatives/?elected_office__icontains=o&limit=2&offset=0",
                "next": None,
            },
        },
    )
    result = await client.search_representatives(office="o", level="municipal", limit=5)
    assert [r.name for r in result.representatives] == ["Rob Fraser", "Dan Rye"]
    assert {r.level for r in result.representatives} == {"municipal"}
    assert result.representatives[1].email is None  # "" read as absent
    assert result.total_count == 2
    assert result.has_more is False
    # The scan stopped at next=null instead of asking for a third page.
    assert len(httpx_mock.get_requests()) == 2


async def test_null_instead_of_absent_fields_do_not_break_parsing(httpx_mock):
    # Defensive: JSON null where the live API sends "" or a list, on both a
    # representative and the postcode envelope (null lists, null centroid).
    httpx_mock.add_response(
        url=_url("/postcodes/T5J0N3/"),
        json={
            "code": "T5J0N3",
            "city": None,
            "province": None,
            "centroid": None,
            "boundaries_centroid": None,
            "boundaries_concordance": None,
            "representatives_centroid": [
                {
                    "name": None,
                    "district_name": None,
                    "party_name": None,
                    "offices": None,
                    "extra": None,
                    "related": None,
                },
                {
                    "name": "Office Only",
                    "offices": [None, "not an office", {"type": None, "tel": None}],
                    "extra": ["unexpected", "list"],
                    "related": {"representative_set_url": None},
                },
            ],
            "representatives_concordance": None,
        },
    )
    result = await client.lookup_postcode("T5J0N3")
    assert result.city is None
    assert (result.centroid_latitude, result.centroid_longitude) == (None, None)
    assert result.boundaries == []
    assert result.boundary_sets == []  # nothing to fetch details for
    blank, office_only = result.representatives
    assert (blank.name, blank.offices, blank.extra, blank.level) == ("", [], {}, None)
    assert office_only.extra == {}
    assert [(o.type, o.tel) for o in office_only.offices] == [(None, None)]


async def test_missing_boundary_set_detail_is_flagged_not_fatal(httpx_mock):
    # One set's detail 404s (an HTML page, as live): the lookup still answers.
    httpx_mock.add_response(
        url=_url("/postcodes/K1A0A6/"),
        json={
            "code": "K1A0A6",
            "city": "OTTAWA",
            "province": "ON",
            "centroid": {"type": "Point", "coordinates": [-75.6996, 45.4215]},
            "boundaries_centroid": [
                {
                    "url": "/boundaries/ottawa-wards/somerset/",
                    "name": "Somerset",
                    "related": {"boundary_set_url": "/boundary-sets/ottawa-wards/"},
                    "boundary_set_name": "Ottawa ward",
                    "external_id": None,
                }
            ],
            "boundaries_concordance": [],
            "representatives_centroid": [PARM_BAINS],
        },
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/ottawa-wards/"),
        status_code=404,
        text="<!DOCTYPE html><html><title>Not Found</title></html>",
        headers={"content-type": "text/html"},
    )
    result = await client.lookup_postcode("K1A 0A6")
    assert result.boundaries[0].external_id is None
    [info] = result.boundary_sets
    assert (info.slug, info.name, info.detail_loaded) == ("ottawa-wards", "Ottawa ward", False)
    assert result.oldest_boundary_update is None
    # An MP but no provincial member matched, so only that level is flagged.
    assert any("No provincial representative" in n for n in result.notes)


@pytest.mark.parametrize(
    ("status", "error", "match"),
    [
        (429, UpstreamUnavailable, "60 requests per minute"),
        (500, UpstreamError, "HTTP 500"),
        (502, UpstreamError, "HTTP 502"),
    ],
)
async def test_transient_statuses_are_retried_then_typed(httpx_mock, status, error, match):
    httpx_mock.add_response(url=_url("/postcodes/T5J0N3/"), status_code=status, is_reusable=True)
    with pytest.raises(error, match=match):
        await client.lookup_postcode("T5J0N3", include_set_details=False)
    # shared/http.api_get makes three attempts before giving up.
    assert len(httpx_mock.get_requests()) == 3


async def test_html_body_with_200_is_an_upstream_error_not_retried(httpx_mock):
    # A proxy or maintenance page answering 200 with HTML instead of JSON.
    httpx_mock.add_response(
        url=_url("/representative-sets/?limit=1000"),
        text="<!DOCTYPE html><html><title>Down for maintenance</title></html>",
        headers={"content-type": "text/html"},
    )
    with pytest.raises(UpstreamError, match="did not return JSON"):
        await client.list_representative_sets()
    assert len(httpx_mock.get_requests()) == 1


async def test_invalid_inputs_are_rejected_before_any_request(httpx_mock):
    with pytest.raises(InvalidInput, match="offset"):
        await client.search_representatives(name="a", offset=-1)
    with pytest.raises(InvalidInput, match="level"):
        await client.search_representatives(name="a", level="regional")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput, match="slug"):
        await client.search_representatives(representative_set="House of Commons!")
    with pytest.raises(InvalidInput, match="limit"):
        await client.list_boundary_sets(limit=51)
    with pytest.raises(InvalidInput, match="finite"):
        await client.lookup_point(45.0, float("inf"))
    with pytest.raises(InvalidInput, match="postcode"):
        await client.lookup_postcode("")
    assert httpx_mock.get_requests() == []
