"""StatCan's national database: an outer zip holding nested per-agency zips.

The fixture mirrors what the real archive was seen to do on 2026-10-02:
data_sources.csv is Windows-1252, ids carry apostrophes, feeds may omit
feed_info.txt and calendar.txt, a feed's agency.txt can name a zone other
than its province's, and several rows have neither a licence page nor an
attribution line.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping
from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.transit import client, constants, national, zipstream
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember

SOURCES = (
    "custom_id,prov_terr,data_page,direct_url,license_url,attribution\n"
    "regina_transit,sk,https://open.regina.ca/,https://x/regina.zip,"
    "https://open.regina.ca/pages/terms-of-use,Contains information licensed under the "
    "Open Government Licence - The City of Regina\n"
    "exo_l'assomption,qc,,https://x/exo.zip,https://www.donneesquebec.ca/licence/,"
    '"Horaires et parcours planifiés (GTFS), dans Données Québec"\n'
    "ride_ck,on,,,,\n"
    "translink_vancouver,bc,,,https://www.translink.ca/terms,Route and arrival data used "
    "in this product or service is provided by permission of TransLink\n"
    "calgary_transit,ab,,,https://data.calgary.ca/stories/s/u45n-7awa,Contains information "
    "licensed under the Open Government Licence - City of Calgary\n"
    "ghost_transit,ab,,,https://x/terms,Contains information\n"
)
VALIDATION = (
    "custom_id,agency_name,feed_service_window_start,feed_service_window_end,"
    "num_warning,num_info,num_error\n"
    "regina_transit,Regina Transit,2025-01-01,2025-03-31,12,0,0\n"
    "exo_l'assomption,exo L'Assomption,2025-01-01,2025-03-31,3,0,1\n"
    "ride_ck,Ride CK,2025-01-01,2025-03-31,0,0,0\n"
    "translink_vancouver,TransLink,2025-01-01,2025-03-31,0,0,0\n"
    "calgary_transit,Calgary Transit,2025-01-01,2025-03-31,0,0,0\n"
    "ghost_transit,Ghost Transit,2025-01-01,2025-03-31,0,0,0\n"
)

# Regina's feed has no feed_info.txt and no calendar.txt (the window then
# comes from the validator), and agency.txt names the zone.
REGINA = {
    "agency.txt": "agency_id,agency_name,agency_timezone\nR,Regina Transit,America/Regina\n",
    "routes.txt": "route_id,route_short_name,route_long_name,route_type\n1,1,Albert,3\n",
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,Albert & 11th,50.4452,-104.6189\n"
        "S2,Rochdale,50.4600,-104.6500\n"
    ),
    "calendar_dates.txt": "service_id,date,exception_type\nWK,20250211,1\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id\n1,WK,T1,North,0\n",
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\nT1,08:10:00,08:10:00,S2,2\n"
    ),
}
EXO = {
    "feed_info.txt": (
        "feed_publisher_name,feed_version,feed_start_date,feed_end_date\nexo,v2,20250106,20250331\n"
    ),
    "agency.txt": "agency_id,agency_name,agency_timezone\nE,exo,America/Halifax\n",
    "routes.txt": "route_id,route_short_name,route_long_name,route_type\n9,9,Éléphant,3\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS1,Adhémar,45.7,-73.4\n",
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
        "start_date,end_date\nWK,1,1,1,1,1,0,0,20250106,20250331\n"
    ),
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id\n9,WK,T1,Terminus,0\n",
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,25:10:00,25:10:00,S1,1\n"
    ),
}
ROOT = constants.NATIONAL_ROOT


def _zip(files: Mapping[str, bytes | str], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content, compress_type=method)
    return buffer.getvalue()


def _outer() -> bytes:
    return _zip(
        {
            f"{ROOT}data_sources.csv": SOURCES.encode("cp1252"),
            f"{ROOT}validation_summary.csv": VALIDATION,
            f"{ROOT}gtfs/regina_transit/gtfs.zip": _zip(REGINA),
            f"{ROOT}gtfs/exo_l'assomption/gtfs.zip": _zip(EXO),
            f"{ROOT}gtfs/calgary_transit/gtfs.zip": _zip(REGINA),
            f"{ROOT}gtfs/ride_ck/gtfs.zip": _zip(REGINA),
            f"{ROOT}gtfs/translink_vancouver/gtfs.zip": _zip(REGINA),
        }
    )


@pytest.fixture(autouse=True)
def _reset():
    cache_module._caches.clear()
    client._NATIONAL.clear()
    yield
    client._NATIONAL.clear()


def _serve(httpx_mock, body: bytes | None = None) -> None:
    body = body or _outer()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(body))})
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    httpx_mock.add_callback(respond, url=constants.NATIONAL_URL, is_reusable=True)


async def test_catalogue_statuses_and_terms(httpx_mock):
    _serve(httpx_mock)
    result = await client.list_national_agencies()
    by_key = {a.key: a for a in result.agencies}
    assert result.total_matches == 6
    regina = by_key["national:regina_transit"]
    assert regina.status == "available"
    assert regina.province == "SK"
    assert regina.licence_url == "https://open.regina.ca/pages/terms-of-use"
    assert "Open Government Licence - The City of Regina" in regina.attribution
    assert "Adapted from Statistics Canada" in regina.attribution
    assert (regina.service_window_start, regina.service_window_end) == (
        date(2025, 1, 1),
        date(2025, 3, 31),
    )
    # The cp1252 byte in data_sources.csv arrives as the accented letter.
    assert "Données Québec" in by_key["national:exo_l'assomption"].attribution
    assert by_key["national:exo_l'assomption"].validator_errors == 1
    overlap = by_key["national:calgary_transit"]
    assert (overlap.status, overlap.live_agency_key) == ("overlaps_live", "calgary")
    assert by_key["national:ride_ck"].status == "excluded"
    assert "neither a licence page nor an attribution" in (
        by_key["national:ride_ck"].status_reason or ""
    )
    assert "TransLink" in (by_key["national:translink_vancouver"].status_reason or "")
    # In data_sources.csv but missing from the archive.
    assert by_key["national:ghost_transit"].status == "excluded"
    assert "absent from the archive" in (by_key["national:ghost_transit"].status_reason or "")
    assert result.provenance.as_of == constants.NATIONAL_AS_OF
    assert "Statistics Canada Open Licence" in (result.provenance.licence or "")


async def test_catalogue_filters(httpx_mock):
    _serve(httpx_mock)
    sk = await client.list_national_agencies(province="sk")
    assert [a.key for a in sk.agencies] == ["national:regina_transit"]
    named = await client.list_national_agencies(query="assomption", status="available")
    assert [a.key for a in named.agencies] == ["national:exo_l'assomption"]
    with pytest.raises(InvalidInput, match="status"):
        await client.list_national_agencies(status="bogus")


async def test_overlapping_and_excluded_agencies_are_not_served(httpx_mock):
    _serve(httpx_mock)
    with pytest.raises(InvalidInput, match="agency='calgary'"):
        await client.search_routes("national:calgary_transit")
    with pytest.raises(InvalidInput, match="neither a licence page"):
        await client.search_stops("national:ride_ck", "x")
    with pytest.raises(InvalidInput, match="TransLink"):
        await client.get_feed_info("national:translink_vancouver")
    with pytest.raises(InvalidInput, match="Unknown agency"):
        await client.search_routes("national:nowhere")


async def test_feed_info_reads_the_nested_zip(httpx_mock):
    _serve(httpx_mock)
    info = await client.get_feed_info("national:exo_l'assomption")
    assert (info.route_count, info.stop_count) == (1, 1)
    assert info.feed_end_date == date(2025, 3, 31)
    assert info.agency.database == "statcan"
    assert info.provenance.url == constants.NATIONAL_URL
    assert info.provenance.as_of == constants.NATIONAL_AS_OF
    limits = info.provenance.limits or ""
    licence = info.provenance.licence or ""
    assert "Données Québec" in licence and "Statistics Canada Open Licence" in licence
    assert "taken as is" in limits
    assert "StatCan validator window 2025-01-01 to 2025-03-31" in (info.provenance.coverage or "")


async def test_tools_work_on_a_national_agency(httpx_mock):
    _serve(httpx_mock)
    routes = await client.search_routes("national:exo_l'assomption", "elephant")
    assert [r.route_id for r in routes.routes] == ["9"]
    stops = await client.search_stops("national:regina_transit", "rochdale")
    assert [s.stop_id for s in stops.stops] == ["S2"]
    # 2025-02-11 is a Tuesday; the trip runs only through calendar_dates.txt.
    stop = await client.get_stop_departures(
        "national:regina_transit", "S1", service_date="2025-02-11", start_time="00:00"
    )
    assert [(d.trip_id, d.local_time) for d in stop.departures] == [("T1", "08:00:00")]
    summary = await client.get_route_summary(
        "national:regina_transit", "1", service_date="2025-02-11"
    )
    assert summary.trips_on_date == 1
    # The after-midnight trip of the previous service day (Monday 2025-01-06 -> Tuesday).
    night = await client.get_stop_departures(
        "national:exo_l'assomption", "S1", service_date="2025-01-07", start_time="00:00"
    )
    # The trip of the day itself (25:10 on the 7th is 01:10 on the 8th) and the
    # one that began on the 6th and runs past midnight into the 7th.
    assert [(d.local_time, d.after_midnight_of_previous_service_day) for d in night.departures] == [
        ("01:10:00", True),
        ("01:10:00", False),
    ]


async def test_date_outside_the_snapshot_window_names_the_window(httpx_mock):
    _serve(httpx_mock)
    # No feed_info.txt: the validator window from validation_summary.csv applies.
    with pytest.raises(InvalidInput, match="2025-01-01 to 2025-03-31.*2025 snapshot"):
        await client.get_stop_departures("national:regina_transit", "S1", service_date="2026-10-02")
    with pytest.raises(InvalidInput, match="2025-01-06 to 2025-03-31"):
        await client.get_route_summary("national:exo_l'assomption", "9", service_date="2026-10-02")


async def test_timezone_comes_from_the_feed_with_a_province_fallback(httpx_mock):
    _serve(httpx_mock)
    # exo's agency.txt names a zone other than the province table's (the
    # fixture says Halifax for a Quebec feed): the feed's own value is used.
    await client._resolve("national:exo_l'assomption")
    assert await client._timezone("national:exo_l'assomption") == "America/Halifax"
    assert await client._timezone("national:regina_transit") == "America/Regina"
    assert await client._timezone("oc_transpo") == "America/Toronto"


def test_province_table_covers_the_provinces():
    assert constants.PROVINCE_TIMEZONES["sk"] == "America/Regina"
    assert len(constants.PROVINCE_TIMEZONES) == 13


async def test_overlap_keys_name_live_agencies():
    assert set(constants.NATIONAL_OVERLAPS.values()) <= set(constants.AGENCIES)


def test_build_agencies_tolerates_blank_columns():
    agencies = national.build_agencies(
        [{"custom_id": "via_rail", "prov_terr": "", "license_url": "x", "attribution": "y"}],
        [],
        {national.member_path("via_rail")},
    )
    agency = agencies["national:via_rail"]
    assert agency.province == "CA"
    assert agency.name_en == "Via Rail"
    assert agency.status == "overlaps_live"
    assert agency.window_start is None


async def test_nested_zip_is_bounded(httpx_mock, monkeypatch):
    body = _outer()
    _serve(httpx_mock, body)
    monkeypatch.setattr(constants, "NATIONAL_MAX_INFLATED_BYTES", 100)
    catalog = await client._load_national()
    member = catalog.members[national.member_path("regina_transit")]
    with pytest.raises(UpstreamError, match="inflates past"):
        await zipstream.read_nested_zip(constants.NATIONAL_URL, member)
    big = ZipMember(member.name, 10**9, 10**9, 8, member.header_offset)
    monkeypatch.setattr(constants, "NATIONAL_MAX_INFLATED_BYTES", 60 * 1024 * 1024)
    with pytest.raises(UpstreamError, match="compressed"):
        await zipstream.read_nested_zip(constants.NATIONAL_URL, big)


async def test_nested_stored_member_round_trips(httpx_mock):
    inner = _zip(REGINA)
    outer = _zip({f"{ROOT}gtfs/x/gtfs.zip": inner}, method=zipfile.ZIP_STORED)
    _serve(httpx_mock, outer)
    from maplestats_mcp.shared.remote_zip import list_members

    members, _ = await list_members(constants.NATIONAL_URL)
    data = await zipstream.read_nested_zip(constants.NATIONAL_URL, members[0])
    assert data == inner
