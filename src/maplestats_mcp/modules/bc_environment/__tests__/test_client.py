"""Mocked tests for the BC Ministry of Environment module.

Fixtures copy the live layouts of 2026-10-03: CRLF line ends, DATE_PST in
fixed UTC-8, a -6999 missing code in PM25.csv, a Windows-1252 en dash in a
hydrometric station name, leading spaces in Stage.csv, wide snow files with
empty cells, and archives sorted for range reads.
"""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.bc_environment import client, constants
from maplestats_mcp.modules.bc_environment.tools import (
    bc_env_get_air_parameter_data,
    bc_env_get_air_station_data,
    bc_env_get_aqhi,
    bc_env_get_snow_readings,
    bc_env_get_snow_station_data,
    bc_env_get_snow_surveys,
    bc_env_get_streamflow,
    bc_env_get_well_levels,
    bc_env_list_air_stations,
    bc_env_list_snow_stations,
    bc_env_list_streamflow_gauges,
    bc_env_list_wells,
)
from maplestats_mcp.shared.errors import InvalidInput, NotFound


def crlf(text: str) -> bytes:
    return text.strip("\n").replace("\n", "\r\n").encode("utf-8") + b"\r\n"


STATIONS_CSV = crlf(
    """SERIAL_CODE,EMS_ID,STATION_NAME,LOCATION,CITY,CATEGORY,STATION_ENVIRONMENT,STATION_OWNER,DATE_ESTABLISHED,NOTES,LATITUDE,LONGITUDE,HEIGHT(m),STATUS,URL,URL2,PM25_INSTRUMENT,PM25,PM25_UNIT,O3,O3_UNIT,TEMP,TEMP_UNIT,DATE,DATE_PST,URL_Station
261,E238212,Abbotsford Central,"",Abbotsford,METRO VANCOUVER,"",MVRD,"","",49.0426,-122.3098,58,ON,https://envistaweb.env.gov.bc.ca/x,,PM25_T640,3.1,ug/m3,2.7,ppb,14.6,Deg.C,Saturday,2026-10-03 09:00,x
16,0550502,Williams Lake Columneetza School,"",Williams Lake,OPERATIONAL,"",ENV,"","",52.14428,-122.150391,631,ON,https://envistaweb.env.gov.bc.ca/y,,PM25_SHARP5030i,0.6,ug/m3,"","",7.7,Deg.C,Saturday,2026-10-03 09:00,y"""
)

STATION_FILE = crlf(
    """DATE_PST,STATION,EMS_ID,LATITUDE,LONGITUDE,PM25,O3,TEMP_MEAN,PM25_24,DATE_LOCAL,DATE
2026-10-03 09:00,Abbotsford Central,E238212,49.0426,-122.3098,3.3,2.4,13,4.5,2026-10-03 10:00,Saturday 3 October 2026 10AM (PDT)
2026-10-03 08:00,Abbotsford Central,E238212,49.0426,-122.3098,,1.6,12.2,4.52,2026-10-03 09:00,Saturday 3 October 2026 09AM (PDT)"""
)

PM25_FILE = crlf(
    """DATE_PST,STATION_NAME,RAW_VALUE,REPORTED_VALUE,INSTRUMENT,UNITS,PARAMETER,EMS_ID,LATITUDE,LONGITUDE
2026-10-03 09:00,Abbotsford Central,,,PM25_T640,ug/m3,PM25,E238212,49.0426,-122.3098
2026-10-03 08:00,Abbotsford Central,3.286397,3.3,PM25_T640,ug/m3,PM25,E238212,49.0426,-122.3098
2026-10-03 07:00,Abbotsford Central,-6999,-6999,PM25_T640,ug/m3,PM25,E238212,49.0426,-122.3098
2026-10-03 09:00,Williams Lake Columneetza School,0.61,0.6,PM25_SHARP5030i,ug/m3,PM25,0550502,52.1,-122.1"""
)

AQHI_WEB = crlf(
    """AQHI_AREA,LATITUDE,LONGITUDE,DATE_LOCAL,VALUE,FORECAST_TODAY,FORECAST_TONIGHT,FORECAST_TOMORROW,FORECAST_TOMORROW_NIGHT,DATE_PST,DATE,URL,FORECAST_TODAY_CHAR,FORECAST_TONIGHT_CHAR,FORECAST_TOMORROW_CHAR,FORECAST_TOMORROW_NIGHT_CHAR,AQHICURRENT_Text1,AQHICURRENT_Text2,AQHICURRENT_Text3,AQHIPLUS_Text,VALUE_CHAR
Kamloops,50.67,-120.33,2026-10-03 10:00,11,2,2,3,3,2026-10-03 09:00,Saturday,https://www.env.gov.bc.ca/epd/bcairquality/data/aqhi.html?id=AQHI-KAMLOOPS,2,2,3,3,Very High Risk,a,b,,10+"""
)

AQHI_HISTORY = crlf(
    """DATE_PST,AQHI_AREA,STATION_NAME,AQHI,LATITUDE,LONGITUDE,DATE_LOCAL,DATE,AQHI_CHAR,AQHI_INT
2026-10-03 09:00,Kamloops,Kamloops Federal Building,1.00,50.6,-120.3,2026-10-03 10:00,x,1,1
2026-10-03 08:00,Kamloops,Kamloops Federal Building,-999,50.6,-120.3,2026-10-03 09:00,x,,"""
)

AIR = constants.AIR_RAW


async def test_list_air_stations_filters_by_parameter(httpx_mock):
    httpx_mock.add_response(url=constants.AIR_STATIONS_URL, content=STATIONS_CSV)
    result = await bc_env_list_air_stations(parameter="O3")
    assert [s.ems_id for s in result.stations] == ["E238212"]
    assert result.stations[0].units["PM25"] == "ug/m3"
    assert "Open Government Licence - British Columbia" in (result.provenance.licence or "")


async def test_station_file_is_reshaped_with_utc_and_units(httpx_mock):
    httpx_mock.add_response(url=constants.AIR_STATIONS_URL, content=STATIONS_CSV)
    httpx_mock.add_response(url=f"{AIR}/Station/E238212.csv", content=STATION_FILE)
    result = await bc_env_get_air_station_data("abbotsford central", ["PM25", "PM25_24"])
    first = result.readings[0]
    assert (first.time_pst, first.time_utc, first.parameter, first.value) == (
        "2026-10-03 09:00",
        "2026-10-03 17:00",
        "PM25",
        3.3,
    )
    assert first.unit == "ug/m3"
    assert result.readings[1].parameter == "PM25_24" and result.readings[1].unit == "ug/m3"
    missing = [r for r in result.readings if r.time_pst.endswith("08:00") and r.parameter == "PM25"]
    assert missing[0].value is None


async def test_ambiguous_air_station_is_refused(httpx_mock):
    httpx_mock.add_response(url=constants.AIR_STATIONS_URL, content=STATIONS_CSV)
    with pytest.raises(NotFound):
        await bc_env_get_air_station_data("Nowhere")


async def test_parameter_file_latest_only_skips_missing_hours_and_codes(httpx_mock):
    httpx_mock.add_response(url=f"{AIR}/Air_Quality/PM25.csv", content=PM25_FILE)
    result = await bc_env_get_air_parameter_data("pm2.5", latest_only=True)
    by_station = {r.ems_id: r for r in result.readings}
    assert by_station["E238212"].time_pst == "2026-10-03 08:00"
    assert by_station["E238212"].raw_value == pytest.approx(3.286397)
    assert by_station["0550502"].value == 0.6


async def test_parameter_file_reports_missing_code(httpx_mock):
    httpx_mock.add_response(url=f"{AIR}/Air_Quality/PM25.csv", content=PM25_FILE)
    result = await bc_env_get_air_parameter_data("PM25", station="E238212", end="2026-10-03 07:00")
    assert result.readings[0].value is None and result.readings[0].missing_code == "-6999"


async def test_unknown_parameter_is_invalid():
    with pytest.raises(InvalidInput):
        await bc_env_get_air_parameter_data("PM3")


async def test_aqhi_current_and_history(httpx_mock):
    httpx_mock.add_response(url=constants.AQHI_URL, content=AQHI_WEB)
    httpx_mock.add_response(url=f"{AIR}/Station/AQHI-KAMLOOPS.csv", content=AQHI_HISTORY)
    result = await bc_env_get_aqhi("kamloops", history_hours=2)
    assert result.areas[0].aqhi == "10+" and result.areas[0].area_id == "AQHI-KAMLOOPS"
    assert [h.aqhi for h in result.history] == [1.0, None]


SNOW_WFS = {
    "type": "FeatureCollection",
    "features": [
        {
            "properties": {
                "LOCATION_ID": "2C21P",
                "LOCATION_NAME": "Fernie",
                "ELEVATION": 988,
                "STATUS": "Active",
                "LATITUDE": 49.48825,
                "LONGITUDE": -115.072611,
                "OPERATOR": "BC Hydro",
            },
            "geometry": {"type": "Point", "coordinates": [-115.07, 49.49]},
        },
        {
            "properties": {
                "LOCATION_ID": "1A15P",
                "LOCATION_NAME": "Knudsen Lake",
                "ELEVATION": 1580,
                "STATUS": "Inactive",
                "LATITUDE": 54.3,
                "LONGITUDE": -120.78,
                "OPERATOR": "BC ENV",
            },
            "geometry": None,
        },
    ],
}


async def test_snow_stations_from_wfs(httpx_mock):
    httpx_mock.add_response(json=SNOW_WFS)
    result = await bc_env_list_snow_stations(status="active")
    assert [s.station_id for s in result.stations] == ["2C21P"]
    assert result.stations[0].operator == "BC Hydro"


SNOWALL = crlf(
    """Location ID,Location Name,Status,Latitude,Longitude,Elevation,DateTime,SW,Unit_SW,Grade_SW,SD,Unit_SD,Grade_SD
1A12P,Kaza Lake,Active,56.02,-126.29,1257,2026-10-01T17:15:00+00:00,2,mm,Undefined,-1,cm,Undefined
1A12P,Kaza Lake,Active,56.02,-126.29,1257,2026-10-01T17:30:00+00:00,3,mm,Good,,,"""
)


async def test_snow_station_file_is_tidy_with_grades(httpx_mock):
    httpx_mock.add_response(url=f"{constants.SNOW_BASE}/SnowAll/1A12P.csv", content=SNOWALL)
    result = await bc_env_get_snow_station_data("1a12p")
    assert [(r.time_utc, r.variable, r.value, r.grade) for r in result.readings] == [
        ("2026-10-01 17:30:00", "SW", 3.0, "Good"),
        ("2026-10-01 17:15:00", "SD", -1.0, "Undefined"),
        ("2026-10-01 17:15:00", "SW", 2.0, "Undefined"),
    ]


async def test_snow_station_id_is_checked():
    with pytest.raises(InvalidInput):
        await bc_env_get_snow_station_data("../x")


SW_WIDE = crlf(
    """DATE(UTC),1A01P Yellowhead Lake,2F01AP Trout Creek West
2026-10-01 00:00,1,
2026-10-01 01:00,,4"""
)


async def test_wide_snow_file_reshaped_and_empty_cells_dropped(httpx_mock):
    httpx_mock.add_response(url=f"{constants.SNOW_BASE}/SW.csv", content=SW_WIDE)
    result = await bc_env_get_snow_readings("sw")
    assert [(r.time_utc, r.station_id, r.station_name, r.value) for r in result.readings] == [
        ("2026-10-01 01:00:00", "2F01AP", "Trout Creek West", 4.0),
        ("2026-10-01 00:00:00", "1A01P", "Yellowhead Lake", 1.0),
    ]
    assert result.readings[0].unit == "mm"


def _fake_remote(monkeypatch, url: str, body: bytes) -> list[tuple[int, int]]:
    calls: list[tuple[int, int]] = []

    async def size(target: str) -> int:
        assert target == url
        return len(body)

    async def ranged(target: str, start: int, end: int) -> bytes:
        assert target == url
        calls.append((start, end))
        return body[start : end + 1]

    monkeypatch.setattr(client.remote_zip, "remote_size", size)
    monkeypatch.setattr(client, "_range", ranged)
    monkeypatch.setattr(constants, "RANGE_CHUNK_BYTES", 64)
    return calls


def _snow_archive() -> bytes:
    lines = ["DATE(UTC),1A01P Yellowhead Lake,2F01AP Trout Creek West"]
    for day in range(1, 29):
        for hour in (0, 12):
            lines.append(f"2023-02-{day:02d} {hour:02d}:00,{day},{100 + day}")
    return crlf("\n".join(lines))


async def test_snow_archive_period_is_found_by_range_search(httpx_mock, monkeypatch):
    httpx_mock.add_response(url=f"{constants.SNOW_BASE}/SW.csv", content=SW_WIDE)
    url = f"{constants.SNOW_BASE}/SW_Archive.csv"
    body = _snow_archive()
    calls = _fake_remote(monkeypatch, url, body)
    result = await bc_env_get_snow_readings(
        "SW", ["2F01AP"], start="2023-02-20", end="2023-02-21 00:00"
    )
    assert [(r.time_utc, r.value) for r in result.readings] == [
        ("2023-02-21 00:00:00", 121.0),
        ("2023-02-20 12:00:00", 120.0),
        ("2023-02-20 00:00:00", 120.0),
    ]
    assert sum(end - start + 1 for start, end in calls) < len(body) * 2


def _hydro_archive() -> bytes:
    header = (
        "Location ID, Location Name, Status, Latitude, Longitude, Date/Time(UTC), "
        "Parameter, Value, Unit, Grade"
    )
    lines = [header]
    for station in ("08HA0018", "08HA0022", "08LC0006"):
        for day in range(1, 11):
            lines.append(
                f"{station},Creek at Road,Active,48.7,-123.6,2024-08-{day:02d} 00:00:00,"
                f"Discharge,{day / 10:.3f},m^3/s,RISC E"
            )
    return crlf("\n".join(lines))


async def test_hydrometric_archive_reads_one_station_by_range(httpx_mock, monkeypatch):
    httpx_mock.add_response(
        url=f"{constants.WATER_BASE}/",
        content=b'<tr><td><a href="Discharge_Archive_2023Oct_2025Oct.csv">x</a>    </td>'
        b'<td align="right">2026-09-22 14:15  </td><td align="right">138M</td></tr>',
    )
    url = f"{constants.WATER_BASE}/Discharge_Archive_2023Oct_2025Oct.csv"
    _fake_remote(monkeypatch, url, _hydro_archive())
    result = await bc_env_get_streamflow("08ha0022", start="2024-08-03", end="2024-08-04")
    assert result.files == ["Discharge_Archive_2023Oct_2025Oct.csv"]
    assert [(r.time_utc, r.value) for r in result.readings] == [
        ("2024-08-04 00:00:00", 0.4),
        ("2024-08-03 00:00:00", 0.3),
    ]


DISCHARGE = (
    "Location ID, Location Name, Status, Latitude, Longitude, Date/Time(UTC), Parameter, "
    "Value, Unit, Grade\r\n"
    "08LC0006,Bessette Creek at Whitevale Road–Shuswap Ave,Active,50.2,-118.9,"
    "2026-10-01 00:00:00,Discharge,1.25,m^3/s,RISC U\r\n"
).encode("cp1252")
STAGE = crlf(
    """Location ID, Location Name, Status, Latitude, Longitude, Date/Time(UTC), Parameter, Value, Unit, Grade
08DC0001, Upper Creek, Active, 55.1, -129.1, 2026-10-01 00:20, Stage, 0.512, m, Unspecified"""
)


async def test_hydrometric_station_list_reads_cp1252_and_stage_spaces(httpx_mock):
    httpx_mock.add_response(url=f"{constants.WATER_BASE}/Discharge.csv", content=DISCHARGE)
    httpx_mock.add_response(url=f"{constants.WATER_BASE}/Stage.csv", content=STAGE)
    result = await bc_env_list_streamflow_gauges()
    names = {s.station_id: s for s in result.stations}
    assert names["08LC0006"].name == "Bessette Creek at Whitevale Road–Shuswap Ave"
    assert names["08DC0001"].parameters == ["stage"]
    assert names["08DC0001"].latest_utc == "2026-10-01 00:20:00"


async def test_hydrometric_station_id_is_checked():
    with pytest.raises(InvalidInput):
        await bc_env_get_streamflow("Koksilah")


WELL_RECENT = crlf(
    '''"Time","Value","Approval","myLocation"
"2025-10-04 00:00",14.2172856240791,"Approved","OW002"
"2026-10-02 19:00",14.109,"Working","OW002"'''
)


async def test_well_levels_newest_first(httpx_mock):
    httpx_mock.add_response(url=f"{constants.WELL_BASE}/OW002-recent.csv", content=WELL_RECENT)
    result = await bc_env_get_well_levels("2", series="hourly")
    assert result.well_id == "OW002"
    assert [(x.time, x.approval) for x in result.levels] == [
        ("2026-10-02 19:00", "Working"),
        ("2025-10-04 00:00", "Approved"),
    ]


async def test_missing_well_file_is_not_found(httpx_mock):
    httpx_mock.add_response(url=f"{constants.WELL_BASE}/OW999-average.csv", status_code=404)
    with pytest.raises(NotFound):
        await bc_env_get_well_levels("OW999")


async def test_wells_join_wfs_listing_and_regions(httpx_mock):
    httpx_mock.add_response(
        json={
            "features": [
                {
                    "properties": {
                        "OBSERVATION_WELL_NUMBER": "002",
                        "OBSERVATION_WELL_STATUS": "Active",
                        "CITY": "Abbotsford",
                        "STREET_ADDRESS": "HUNTINGDON RD.",
                        "WELL_TAG_NUMBER": 26787,
                        "GROUND_ELEVATION": 193.1,
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.34165, 49.0171]},
                },
                {
                    "properties": {"OBSERVATION_WELL_NUMBER": "001"},
                    "geometry": None,
                },
            ]
        }
    )
    httpx_mock.add_response(
        url=f"{constants.WELL_BASE}/",
        content=b'<tr><td><a href="OW002-data.csv">OW002-data.csv</a>     </td>'
        b'<td align="right">2026-10-03 09:30  </td><td align="right">9.7M</td></tr>',
    )
    httpx_mock.add_response(
        url=constants.WELL_REGIONS_URL,
        content=crlf(
            '"","EMS_ID","Well_Num","Well_Name","REGION_NAME"\n"1","1","002","x","South Coast"'
        ),
    )
    result = await bc_env_list_wells()
    assert [(w.well_id, w.region, w.latitude) for w in result.wells] == [
        ("OW002", "South Coast", 49.0171)
    ]
    assert result.wells[0].data_updated == "2026-10-03 09:30"


SURVEYS = crlf(
    """Snow Course Name, Number, Elev. metres, Date of Survey, Snow Depth cm, Water Equiv. mm,  Survey Code, Snow Line Elev. m, Density %, Survey Period
HANSARD,1A06A,608,2026/02/27,42,130,,,31,01-Mar
PRINCE GEORGE AIRPORT,1A10,689,2026/01/05,45,66,,,15,01-Jan"""
)


async def test_snow_surveys_parse_slash_dates(httpx_mock):
    httpx_mock.add_response(url=f"{constants.SNOW_BASE}/allmss_current.csv", content=SURVEYS)
    result = await bc_env_get_snow_surveys("1a10")
    assert [(s.course, s.survey_date, s.water_equivalent_mm) for s in result.surveys] == [
        ("PRINCE GEORGE AIRPORT", "2026-01-05", 66.0)
    ]


def test_period_bounds_and_archive_spans():
    assert client.bound("2024", end=True, lang="en", name="end") == "2024-12-31 23:59:59"
    assert client.bound("2024-02", end=True, lang="en", name="end") == "2024-02-29 23:59:59"
    assert client.bound("2024-02-03T05", end=False, lang="en", name="s") == "2024-02-03 05:00:00"
    with pytest.raises(InvalidInput):
        client.bound("yesterday", end=False, lang="en", name="start")
    assert client.archive_span("Discharge_Archive_2015Oct_2017Oct.csv", "Discharge") == (
        "2015-10-01 00:00:00",
        "2017-10-01 00:00:00",
    )
    assert client.archive_span("Stage_Archive_Pre_20151001.csv", "Stage") == (
        None,
        "2015-10-01 00:00:00",
    )
    assert client.archive_span("Discharge_Archive_Post_20251001.csv", "Discharge") == (
        "2025-10-01 00:00:00",
        None,
    )
    assert client.archive_span("Stage.csv", "Stage") is None


# French (lang="fr"): provenance text, licence, notes and errors; English unchanged.


async def test_french_air_stations_provenance(httpx_mock):
    httpx_mock.add_response(url=constants.AIR_STATIONS_URL, content=STATIONS_CSV)
    result = await bc_env_list_air_stations(parameter="O3", lang="fr")
    assert "Licence du gouvernement ouvert – Colombie-Britannique" in (
        result.provenance.licence or ""
    )
    assert result.provenance.freshness == "Réécrit toutes les heures (valeurs de l'heure courante)."
    assert " ; les unités" in (result.provenance.coverage or "")


async def test_english_air_stations_provenance_unchanged(httpx_mock):
    httpx_mock.add_response(url=constants.AIR_STATIONS_URL, content=STATIONS_CSV)
    result = await bc_env_list_air_stations(parameter="O3")
    assert result.provenance.freshness == "Rewritten every hour (current-hour values)."


async def test_french_station_notes_and_errors(httpx_mock):
    httpx_mock.add_response(url=constants.AIR_STATIONS_URL, content=STATIONS_CSV)
    httpx_mock.add_response(url=f"{AIR}/Station/E238212.csv", content=STATION_FILE)
    result = await bc_env_get_air_station_data("abbotsford central", ["PM25"], lang="fr")
    assert result.notes[0].startswith("Données brutes non vérifiées")
    with pytest.raises(InvalidInput, match="Entrée invalide : limit doit être compris"):
        await bc_env_list_air_stations(limit=0, lang="fr")
