"""Tests for bis/client.py, shaped on live responses from 2026-10-26: SDMX-CSV
with "ID:Label" headers and "code: label" cells, quoted cells holding commas,
series-level rows with an empty TIME_PERIOD (and FREQ), a DSD picked by URN
among several, 404 for no data, and short keys the API would silently widen."""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.bis import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

CATALOGUE = re.compile(r"https://stats\.bis\.org/api/v2/structure/dataflow/BIS/\*/\*")
STRUCTURE = re.compile(r"https://stats\.bis\.org/api/v2/structure/dataflow/BIS/WS_\w+/[\d.]+\?.*")
DATA = re.compile(r"https://stats\.bis\.org/api/v2/data/dataflow/BIS/.*")

_DSD_URN = "urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure=BIS:BIS_DSR(1.0)"


def _catalogue():
    flows = [
        {"id": "WS_DSR", "name": "Debt service ratios", "version": "1.0", "structure": _DSD_URN},
        {
            "id": "WS_CBPOL",
            "name": "Central bank policy rates",
            "version": "1.0",
            "structure": "urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure=BIS:BIS_CBPOL(1.0)",
        },
    ]
    return {"meta": {}, "data": {"dataflows": flows}}


def _enum(codelist):
    return {"enumeration": f"urn:sdmx:org.sdmx.infomodel.codelist.Codelist=BIS:{codelist}(1.0)"}


def _dsd(dsd_id, dims):
    return {
        "id": dsd_id,
        "agencyID": "BIS",
        "version": "1.0",
        "dataStructureComponents": {
            "dimensionList": {
                "dimensions": [
                    {"id": d, "position": i, "localRepresentation": _enum(cl)}
                    for i, (d, cl) in enumerate(dims, start=1)
                ]
            }
        },
    }


def _codelist(cl, codes):
    return {
        "id": cl,
        "agencyID": "BIS",
        "version": "1.0",
        "codes": [{"id": c, "name": n} for c, n in codes],
    }


def _dsr_structure():
    # A second, unrelated DSD comes first: the right one is picked by URN.
    return {
        "data": {
            "dataStructures": [
                _dsd("OTHER", [("FREQ", "CL_FREQ")]),
                _dsd(
                    "BIS_DSR",
                    [
                        ("DSR_BORROWERS", "CL_TC_BORROWERS"),
                        ("FREQ", "CL_FREQ"),
                        ("BORROWERS_CTY", "CL_AREA"),
                    ],
                ),
            ],
            "codelists": [
                _codelist("CL_FREQ", [("Q", "Quarterly"), ("A", "Annual")]),
                _codelist("CL_AREA", [("CA", "Canada"), ("US", "United States")]),
                _codelist("CL_TC_BORROWERS", [("H", "Households & NPISHs"), ("P", "Private")]),
            ],
            "conceptSchemes": [
                {
                    "concepts": [
                        {"id": "FREQ", "name": "Frequency"},
                        {"id": "BORROWERS_CTY", "name": "Borrowers' country"},
                    ]
                }
            ],
        }
    }


def _fix_positions(structure):
    """Positions out of list order: sorted by `position`, not by list order."""
    dims = structure["data"]["dataStructures"][1]["dataStructureComponents"]["dimensionList"]
    for dim, position in zip(dims["dimensions"], (3, 1, 2), strict=True):
        dim["position"] = position
    return structure


_HEADER = (
    "STRUCTURE,STRUCTURE_ID,ACTION,FREQ:Frequency,BORROWERS_CTY:Borrowers' country,"
    "DSR_BORROWERS:Borrowers,TIME_PERIOD:Time period or range,OBS_VALUE:Observation Value,"
    "UNIT_MEASURE:Unit of measure,UNIT_MULT:Unit Multiplier,TITLE_TS:Title (tseries level)\n"
)


def _row(area, area_name, sector, period, value, unit="367: Per cent", title=None):
    title = title or f"{area_name} - {sector}"
    return (
        f"dataflow,BIS:WS_DSR(1.0): Debt service ratios,I,Q: Quarterly,{area}: {area_name},"
        f'{sector}: Sector {sector},{period},{value},"{unit}",0: Units,{title}\n'
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _mock_dsr(httpx_mock, csv_text):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=_fix_positions(_dsr_structure()))
    httpx_mock.add_response(url=DATA, text=csv_text)


async def test_list_datasets_has_notes_in_both_languages(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    result = await client.list_datasets()
    assert [d.id for d in result.datasets] == ["WS_CBPOL", "WS_DSR"]
    assert result.datasets[1].description.startswith("Debt service ratios of households")
    assert "BIS is cited" in (result.provenance.licence or "")
    french = await client.list_datasets(lang="fr")
    assert french.datasets[1].description.startswith("Ratios du service de la dette")
    assert (french.provenance.licence or "").startswith("Source : Banque des règlements")


async def test_describe_orders_by_position_and_picks_dsd_by_urn(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=_fix_positions(_dsr_structure()))
    result = await client.describe_dataset("ws_dsr")
    assert result.key_template == "FREQ.BORROWERS_CTY.DSR_BORROWERS"
    assert result.example_key == "*.CA.*"
    assert result.dimensions[1].name == "Borrowers' country"
    # No concept name: the dimension id stands in.
    assert result.dimensions[2].name == "DSR_BORROWERS"
    request = httpx_mock.get_requests()[-1]
    assert request.headers["Accept"] == "application/vnd.sdmx.structure+json;version=1.0.0"
    assert "references=all" in str(request.url) and "/WS_DSR/1.0" in str(request.url)


async def test_unknown_dataset_lists_the_datasets(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    with pytest.raises(NotFound, match="WS_CBPOL, WS_DSR"):
        await client.describe_dataset("WS_NOPE")
    with pytest.raises(InvalidInput):
        await client.describe_dataset("ws dsr; drop")


async def test_get_series_groups_sorts_and_reads_labels(httpx_mock):
    _mock_dsr(
        httpx_mock,
        _HEADER
        + _row("CA", "Canada", "H", "2025-Q2", 14.1)
        + _row("CA", "Canada", "H", "2025-Q1", 14.3)
        + _row("US", "United States", "H", "2025-Q1", 8.0)
        + _row("US", "United States", "H", "2025-Q2", "NaN")
        + _row("CA", "Canada", "H", "2025-Q3", ""),
    )
    result = await client.get_series("WS_DSR", "q.ca+us.h", start_period="2025-Q1")
    assert result.key == "Q.CA+US.H"
    canada, us = result.series
    assert canada.key == "Q.CA.H" and canada.title == "Canada - H"
    assert [o.period for o in canada.observations] == ["2025-Q1", "2025-Q2"]
    assert (canada.latest_period, canada.latest_value) == ("2025-Q2", 14.1)
    assert canada.unit == "Per cent" and canada.unit_multiplier == "Units"
    assert canada.dimensions[1].code == "CA" and canada.dimensions[1].label == "Canada"
    assert [o.period for o in us.observations] == ["2025-Q1"]
    request = httpx_mock.get_requests()[-1]
    assert request.headers["Accept"].startswith("application/vnd.sdmx.data+csv;version=2.0.0")
    assert "c%5BTIME_PERIOD%5D=ge%3A2025-Q1" in str(request.url)
    assert result.csv_url.endswith("format=csv")


async def test_series_level_rows_fill_attributes(httpx_mock):
    """WS_TC sends attribute-only rows with empty FREQ and TIME_PERIOD."""
    attributes_only = (
        "dataflow,BIS:WS_DSR(1.0): Debt service ratios,I,,CA: Canada,H: Sector H,,,"
        '"770: Percentage of GDP",0: Units,Canada - households\n'
    )
    observation = (
        "dataflow,BIS:WS_DSR(1.0): Debt service ratios,I,Q: Quarterly,CA: Canada,"
        "H: Sector H,2026-Q1,100.0,,,\n"
    )
    _mock_dsr(httpx_mock, _HEADER + attributes_only + observation)
    result = await client.get_series("WS_DSR", "Q.CA.H", last_n=1)
    (series,) = result.series
    assert series.unit == "Percentage of GDP"
    assert series.title == "Canada - households"
    assert series.observations[0].value == 100.0


async def test_short_key_is_refused_before_any_data_call(httpx_mock):
    """The API reads Q.CA on WS_DSR as Q.CA.* and returns every sector."""
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=_fix_positions(_dsr_structure()))
    with pytest.raises(InvalidInput, match="needs 3 parts in the order FREQ.BORROWERS_CTY"):
        await client.get_series("WS_DSR", "Q.CA")
    with pytest.raises(InvalidInput, match="needs 3 parts"):
        await client.get_series("WS_DSR", "Q.CA/../x.H")
    assert not any("/data/" in str(r.url) for r in httpx_mock.get_requests())


async def test_open_key_without_period_is_refused(httpx_mock):
    structure = _fix_positions(_dsr_structure())
    codes = [(f"C{i:02d}", f"Area {i}") for i in range(30)]
    structure["data"]["codelists"][1] = _codelist("CL_AREA", codes)
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=structure)
    with pytest.raises(InvalidInput, match="can match up to 120 series"):
        await client.get_series("WS_DSR", "*.*.*")


async def test_no_data_404_is_not_found(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=_fix_positions(_dsr_structure()))
    httpx_mock.add_response(url=DATA, status_code=404, text="<Error>No results for query</Error>")
    with pytest.raises(NotFound, match="No data in BIS dataset WS_DSR for key Q.ZZ.P"):
        await client.get_series("WS_DSR", "Q.ZZ.P")


async def test_server_errors_are_unavailable(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, status_code=503, is_reusable=True)
    with pytest.raises(UpstreamUnavailable, match="BIS statistics API did not answer"):
        await client.list_datasets()


async def test_bad_periods_are_refused_in_french():
    with pytest.raises(InvalidInput, match="^Entrée invalide : start_period '2020Q1'"):
        await client.get_series("WS_DSR", "Q.CA.P", start_period="2020Q1", lang="fr")
    with pytest.raises(InvalidInput, match="last_n"):
        await client.get_series("WS_DSR", "Q.CA.P", last_n=0)


async def test_observation_cap_keeps_latest_of_each_series(httpx_mock, monkeypatch):
    monkeypatch.setattr(client.constants, "MAX_OBSERVATIONS", 2)
    _mock_dsr(
        httpx_mock,
        _HEADER
        + "".join(_row("CA", "Canada", "H", f"202{y}-Q1", y) for y in range(5))
        + "".join(_row("US", "United States", "H", f"202{y}-Q1", y) for y in range(5)),
    )
    result = await client.get_series("WS_DSR", "Q.CA+US.H", last_n=5)
    assert [o.period for o in result.series[0].observations] == ["2024-Q1"]
    assert "only the last 1 of each series" in result.notes[0]


def _cbpol_structure():
    return {
        "data": {
            "dataStructures": [
                _dsd("BIS_CBPOL", [("FREQ", "CL_FREQ"), ("REF_AREA", "CL_BIS_GL_REF_AREA")])
            ],
            "codelists": [
                _codelist("CL_FREQ", [("M", "Monthly")]),
                _codelist("CL_BIS_GL_REF_AREA", [("CA", "Canada"), ("US", "United States")]),
            ],
        }
    }


_CBPOL_HEADER = (
    "STRUCTURE,STRUCTURE_ID,ACTION,FREQ:Frequency,REF_AREA:Reference area,"
    "TIME_PERIOD:Time period or range,OBS_VALUE:Observation Value,"
    "UNIT_MEASURE:Unit of measure,COMPILATION:Compilation\n"
)


def _cbpol(area, name, period, value):
    return (
        f"dataflow,BIS:WS_CBPOL(1.0): Central bank policy rates,I,M: Monthly,{area}: {name},"
        f'{period},{value},368: Per cent per year,"From 1 Jun 1994 onwards: target, overnight"\n'
    )


async def test_compare_ranks_canada_trims_stale_series_and_notes_euro(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=_cbpol_structure())
    httpx_mock.add_response(
        url=DATA,
        text=_CBPOL_HEADER
        + _cbpol("CA", "Canada", "2026-08", 2.5)
        + _cbpol("CA", "Canada", "2026-09", 2.25)
        + _cbpol("US", "United States", "2026-09", 3.875)
        + _cbpol("JP", "Japan", "2026-09", 1.25)
        + _cbpol("XM", "Euro area", "2026-09", 2.5)
        # France stopped in 1998: lastNObservations still sends its last values.
        + _cbpol("FR", "France", "1998-12", 3.0),
    )
    result = await client.compare_countries("policy_rate", compare_with=["G7", "euro area"])
    assert [c.area_code for c in result.countries] == ["CA", "US", "JP", "XM"]
    # XM is an aggregate and is not ranked; 2026-09 has CA, US and JP.
    assert (result.canada_rank, result.rank_period, result.ranked_countries) == (2, "2026-09", 3)
    assert any("FR, DE, IT" in n for n in result.notes)
    assert any("EURO_AREA" in n for n in result.notes)
    request = httpx_mock.get_requests()[-1]
    assert "/WS_CBPOL/1.0/M.CA+US+GB+FR+DE+IT+JP+XM" in str(request.url)
    assert "lastNObservations=60" in str(request.url)


async def test_compare_needs_canada_and_known_indicator(httpx_mock):
    with pytest.raises(InvalidInput, match="Unknown indicator 'gdp'"):
        await client.compare_countries("gdp")
    with pytest.raises(InvalidInput, match="not a BIS area code"):
        await client.compare_countries("policy_rate", compare_with=["Canada"])
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=_cbpol_structure())
    httpx_mock.add_response(
        url=DATA, text=_CBPOL_HEADER + _cbpol("US", "United States", "2026-09", 3.9)
    )
    with pytest.raises(NotFound, match="no policy_rate values for Canada"):
        await client.compare_countries("policy_rate", compare_with=["US"])


async def test_compare_in_french(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=STRUCTURE, json=_cbpol_structure())
    httpx_mock.add_response(url=DATA, text=_CBPOL_HEADER + _cbpol("CA", "Canada", "2026-09", 2.25))
    result = await client.compare_countries("policy_rate", compare_with=["NZ"], lang="fr")
    assert result.indicator_label.startswith("Taux directeur")
    assert result.notes == [
        (
            "Aucune valeur pour : NZ (non couverts par WS_CBPOL, ou sans "
            "données pour les périodes demandées)."
        )
    ]
    assert result.canada_rank is None
