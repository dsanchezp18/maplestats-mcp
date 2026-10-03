"""Error paths and live-shaped files the hand-written fixtures in test_client.py miss.

The two live fixtures below are trimmed copies of the real files fetched on
2026-10-03 (HTTP 200, `Content-Type: text/plain`, `Last-Modified: Thu, 30 Jul
2026 14:17:44 GMT`): bytes kept exactly, only rows dropped. Never hits the
network; every response is mocked with pytest-httpx.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from maplestats_mcp.modules.nfd import client
from maplestats_mcp.modules.nfd.__tests__.test_client import (
    CAUSE_CSV,
    CAUSE_CSV_PATH,
    LOSSES_CSV_PATH,
    _mock_pages,
    _url,
)
from maplestats_mcp.shared.errors import NotFound, UpstreamError

LAST_MODIFIED = "Thu, 30 Jul 2026 14:17:44 GMT"

# http://nfdp.ccfm.org/download/data/csv/NFD%20-%20Area%20burned%20by%20cause%20class%20-%20EN%20FR.csv
# captured 2026-10-03. Quirks kept: UTF-8 BOM and CRLF, Nova Scotia's French
# name without its accent ("Nouvelle-Ecosse", unlike the losses file), a
# blank value whose qualifier is "a" rather than u/U/n (1999 PE, the only
# blank in the file), and unrounded decimals (2025 YT).
LIVE_CAUSE_CSV = (
    b"\xef\xbb\xbfYear,Ann\xc3\xa9e,ISO,Jurisdiction,Juridiction,Cause,Origine,Area (hectares),"
    b"Data Qualifier,Superficie (en hectare),Qualificatifs de donn\xc3\xa9es\r\n"
    b"1990,1990,AB,Alberta,Alberta,Human activity,Activit\xc3\xa9 humaine,2393.8,a,2393.8,a\r\n"
    b"1990,1990,AB,Alberta,Alberta,Natural cause,Cause naturelle,55482.6,a,55482.6,a\r\n"
    b"1990,1990,AB,Alberta,Alberta,Unspecified,Ind\xc3\xa9termin\xc3\xa9e,1008.8,a,1008.8,a\r\n"
    b"1990,1990,NS,Nova Scotia,Nouvelle-Ecosse,Human activity,Activit\xc3\xa9 humaine,"
    b"1029.09,a,1029.09,a\r\n"
    b"1990,1990,NS,Nova Scotia,Nouvelle-Ecosse,Natural cause,Cause naturelle,0.2,a,0.2,a\r\n"
    b"1990,1990,NS,Nova Scotia,Nouvelle-Ecosse,Unspecified,Ind\xc3\xa9termin\xc3\xa9e,"
    b"38.87,a,38.87,a\r\n"
    b"1999,1999,PE,Prince Edward Island,\xc3\x8ele-du-Prince-\xc3\x89douard,Natural cause,"
    b"Cause naturelle,,a,,a\r\n"
    b"2025,2025,YT,Yukon,Yukon,Natural cause,Cause naturelle,137314.6633,a,137314.6633,a\r\n"
    b"2025,2025,YT,Yukon,Yukon,Unspecified,Ind\xc3\xa9termin\xc3\xa9e,40255.17,a,40255.17,a\r\n"
)

# http://nfdp.ccfm.org/download/data/csv/NFD%20-%20Property%20losses%20from%20fires%20-%20EN%20FR.csv
# captured 2026-10-03. Every qualifier code the file uses (a, n, u, U, e, E,
# p, r), blanks only with n/u/U, and zeros published as "0" with "a".
LIVE_LOSSES_CSV = (
    b"\xef\xbb\xbfYear / Ann\xc3\xa9e,ISO,Jurisdiction,Juridiction,Dollars,"
    b"Data qualifier / Qualificatifs de donn\xc3\xa9es\r\n"
    b"1970,AB,Alberta,Alberta,,n\r\n"
    b"1970,BC,British Columbia,Colombie-Britannique,344684,a\r\n"
    b"1970,NL,Newfoundland and Labrador,Terre-Neuve-et-Labrador,0,a\r\n"
    b"1970,NP,National parks,Parcs nationaux,,u\r\n"
    b"1970,NS,Nova Scotia,Nouvelle-\xc3\x89cosse,0,a\r\n"
    b"1996,ON,Ontario,Ontario,1484770,p\r\n"
    b"1997,PE,Prince Edward Island,\xc3\x8ele-du-Prince-\xc3\x89douard,9000,r\r\n"
    b"1998,NS,Nova Scotia,Nouvelle-\xc3\x89cosse,4000,e\r\n"
    b"2019,AB,Alberta,Alberta,,U\r\n"
    b"2020,ON,Ontario,Ontario,345002,E\r\n"
)

LIVE_HEADERS = {"Content-Type": "text/plain", "Last-Modified": LAST_MODIFIED}


# ------------------------------------------------------------- live shapes


async def test_live_cause_file_parses_with_its_real_quirks(httpx_mock: HTTPXMock) -> None:
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=LIVE_CAUSE_CSV, headers=LIVE_HEADERS)
    result = await client.query_table("3.2.1", province="Nouvelle-Écosse", lang="fr")
    # The accented spelling a user types still finds the file's unaccented one.
    assert [(r.iso, r.jurisdiction, r.value) for r in result.rows] == [
        ("NS", "Nouvelle-Ecosse", 1029.09),
        ("NS", "Nouvelle-Ecosse", 0.2),
        ("NS", "Nouvelle-Ecosse", 38.87),
    ]
    assert result.rows[2].dimensions == {"cause": "Indéterminée"}
    assert LAST_MODIFIED in (result.provenance.freshness or "")

    # A blank figure marked "a" (actual) is still a missing value, never 0.
    blank = await client.query_table("3.2.1", province="PE")
    assert [(r.year, r.value, r.qualifiers, r.n_missing) for r in blank.rows] == [
        (1999, None, ["a"], 1)
    ]
    yukon = await client.query_table("3.2.1", province="YT", group_by=["year"])
    assert yukon.rows[0].value == pytest.approx(137314.6633 + 40255.17)


async def test_live_losses_file_every_qualifier_code(httpx_mock: HTTPXMock) -> None:
    _mock_pages(httpx_mock)
    httpx_mock.add_response(
        url=_url(LOSSES_CSV_PATH), content=LIVE_LOSSES_CSV, headers=LIVE_HEADERS
    )
    httpx_mock.add_response(
        url=_url("/en/data/data_dictionary/NFD - Property losses from fires - EN FR DD.xlsx"),
        status_code=404,
    )
    description = await client.describe_table("3.3")
    assert sorted(description.qualifiers) == ["E", "U", "a", "e", "n", "p", "r", "u"]
    assert (description.first_year, description.last_year, description.n_rows) == (1970, 2020, 10)
    result = await client.query_table("3.3", year_to=1970)
    # Published zeros stay 0.0; blanks (n, u) become null.
    assert [(r.iso, r.value, r.qualifiers) for r in result.rows] == [
        ("AB", None, ["n"]),
        ("BC", 344684.0, ["a"]),
        ("NL", 0.0, ["a"]),
        ("NP", None, ["u"]),
        ("NS", 0.0, ["a"]),
    ]


# ---------------------------------------------------------------- errors


async def test_csv_404_is_not_found(httpx_mock: HTTPXMock) -> None:
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), status_code=404)
    with pytest.raises(NotFound, match="no file at"):
        await client.query_table("3.2.1")


async def test_transient_statuses_are_retried(httpx_mock: HTTPXMock) -> None:
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), status_code=429)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV)
    result = await client.query_table("3.2.1")
    assert result.matched_count == 7
    assert len(httpx_mock.get_requests(url=_url(CAUSE_CSV_PATH))) == 2


async def test_persistent_503_gives_up_after_three_tries(httpx_mock: HTTPXMock) -> None:
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), status_code=503, is_reusable=True)
    with pytest.raises(UpstreamError, match="HTTP 503"):
        await client.query_table("3.2.1")
    assert len(httpx_mock.get_requests(url=_url(CAUSE_CSV_PATH))) == 3


async def test_passthrough_status_is_not_parsed_as_data(httpx_mock: HTTPXMock) -> None:
    """get_raw hands 406/409 back unraised (StatCan needs them), so _download must check."""
    _mock_pages(httpx_mock)
    httpx_mock.add_response(
        url=_url(CAUSE_CSV_PATH), status_code=409, text="<html><body>Conflict</body></html>"
    )
    with pytest.raises(UpstreamError, match="HTTP 409"):
        await client.query_table("3.2.1")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"", "is empty"),
        (LIVE_CAUSE_CSV.split(b"\r\n")[0] + b"\r\n", "header and no rows"),
        (LIVE_CAUSE_CSV.replace(b",38.87,a,38.87,a", b",38.87,a"), "line 7: 9 columns"),
        (LIVE_CAUSE_CSV.replace(b"2025,2025,YT", b"2025-26,2025,YT", 1), "year '2025-26'"),
    ],
    ids=["empty", "header-only", "short-row", "bad-year"],
)
async def test_malformed_csv_is_an_upstream_error(
    httpx_mock: HTTPXMock, body: bytes, message: str
) -> None:
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=body)
    with pytest.raises(UpstreamError, match=message):
        await client.query_table("3.2.1")


async def test_cp1252_csv_without_bom_decodes(httpx_mock: HTTPXMock) -> None:
    """The French Download page is Windows-1252; a CSV saved the same way must still read."""
    _mock_pages(httpx_mock)
    legacy = CAUSE_CSV.decode("utf-8-sig").encode("cp1252")
    assert not legacy.startswith(b"\xef\xbb\xbf")
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=legacy)
    result = await client.query_table("3.2.1", province="PE", lang="fr")
    assert {r.jurisdiction for r in result.rows} == {"Île-du-Prince-Édouard"}
    assert {r.dimensions["cause"] for r in result.rows} == {"Activité humaine"}
