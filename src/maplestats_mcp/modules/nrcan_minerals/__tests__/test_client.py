"""Tests on lines trimmed from NRCan's mineral production files (2026-10-03)."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.nrcan_minerals import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_PAGE = """<html><body><main><form id="Form1"><select id="vYear" name="vYear">
<option value="2025" selected="selected">2025p</option><option value="2019">2019</option>
<option value="2018">2018</option></select></form></main></body></html>"""

# 2019 onward: quoted cells, a Symbol column, ".." and "x".
_NEW = (
    '﻿"Preliminary estimate of the mineral production in Canada, 2025(1),(2)","","",""\n'
    '"","","","","","","",""\n'
    '"Year","Type","Commodity","Province or Territory","Category","Value","Units","Symbol"\n'
    '"2025","Metals","Gold","Ontario","Quantity produced","74,883","Kilograms","p"\n'
    '"2025","Metals","Gold","Canada","Quantity shipped","184,456","Kilograms","p"\n'
    '"2025","Metals","Gold","Canada","Value of shipments","x","Thousands of dollars","p"\n'
    '"2025","Metals","Cobalt","Prince Edward Island","Quantity produced","..","Metric tonnes",""\n'
    '"2025","Metals","Iron, agglomerates(4)","Canada","Value of shipments","1,000",'
    '"Thousands of dollars","p"\n'
    '"2025","Metals","Iron, concentrates(4)","Canada","Value of shipments","2,000",'
    '"Thousands of dollars","p"\n'
    '"2025","Total annual mineral production, including coal¹(14)","Grand total","Canada",'
    '"Value of shipments","69,317,583","Thousands of dollars","p"\n'
    '"Source: Statistics Canada","","","","","","",""\n'
)
# 1990-2018: no Symbol column, plain decimals, historical grand totals.
_OLD = (
    '﻿"Mineral production in Canada, 2018",,,,,,\n'
    ",,,,,,\n"
    "Year,Commodity,Commodity Group,Province/Territory,Value Type,Units,Value\n"
    "2018,Gold,Metals,Canada,Quantity shipped,kilograms,191881.859\n"
    "2018,Gold,Metals,Canada,Value of shipments,thousands of dollars,\n"
    "2018,Iron ore,Metals,Canada,Value of shipments,thousands of dollars,x\n"
    '2018,"Grand total, 2017","Historical data (1988 - 2018), by Province or Territory",'
    "Canada,Value of shipments,thousands of dollars,45323180.277\n"
    '2018,"Grand total, 2018","Historical data (1988 - 2018), by Province or Territory",'
    "Canada,Value of shipments,thousands of dollars,49049260\n"
    "(1) Marketable production.,,,,,,\n"
    "Source: Natural Resources Canada,,,,,,\n"
)


def _mock(httpx_mock, *years: int) -> None:
    httpx_mock.add_response(url=constants.ANNUAL_PAGE, text=_PAGE)
    for year in years:
        body = _OLD if year <= 2018 else _NEW.replace("2025", str(year))
        httpx_mock.add_response(url=constants.CSV_URL.format(year=year), text=body)


def test_names_and_values():
    assert client.clean_name("Lime¹(10)") == "Lime"
    assert client.clean_name("Potash (K₂O)(3)") == "Potash (K₂O)"
    assert client.clean_name("in Canada, 2025(1),(2)") == "in Canada, 2025"
    assert client.parse_value("2,309", "p") == (2309.0, "preliminary")
    assert client.parse_value("x") == (None, "confidential")
    assert client.parse_value("..") == (None, "not_available")
    assert client.parse_value("27058554.021") == (27058554.021, "final")
    assert client.parse_years(_PAGE) == [2025, 2019, 2018]


def test_both_layouts():
    new = client.parse_csv(_NEW, 2025)
    assert new.title == "Preliminary estimate of the mineral production in Canada, 2025"
    assert new.rows[0].commodity == "Gold" and new.rows[0].symbol == "preliminary"
    assert new.rows[-1].group == "Total annual mineral production, including coal"
    old = client.parse_csv(_OLD, 2018)
    assert [(r.commodity, r.year, r.value) for r in old.rows[-2:]] == [
        ("Grand total", 2017, 45323180.277),
        ("Grand total", 2018, 49049260.0),
    ]
    assert old.rows[1].symbol == "not_available"
    with pytest.raises(UpstreamError):
        client.parse_csv("<html>error</html>", 2018)


async def test_production_filters(httpx_mock):
    _mock(httpx_mock, 2025)
    latest = await client.get_production(commodity="gold", province="ca", category="quantity")
    assert latest.year == 2025 and latest.preliminary
    assert [(r.category, r.value) for r in latest.rows] == [("Quantity shipped", 184456.0)]
    assert "Iron, concentrates" in latest.commodities
    with pytest.raises(NotFound):
        await client.get_production(1989)
    with pytest.raises(InvalidInput):
        await client.get_production(province="Atlantis")


async def test_french_provenance_notes_and_errors(httpx_mock):
    _mock(httpx_mock, 2025)
    result = await client.get_production(commodity="gold", lang="fr")
    assert (result.provenance.freshness or "").startswith("annuelle : une estimation")
    assert "lignes dans le fichier 2025" in (result.provenance.coverage or "")
    assert "anglais seulement" in (result.provenance.limits or "")
    assert (result.provenance.licence or "").startswith("Avis de Ressources naturelles Canada")
    with pytest.raises(InvalidInput, match="province inconnue"):
        await client.get_production(province="Atlantis", lang="fr")
    with pytest.raises(NotFound, match="^Aucune correspondance trouvée : nrcan_minerals"):
        await client.get_production(1989, lang="fr")


async def test_series_across_layouts(httpx_mock):
    _mock(httpx_mock, 2018, 2019, 2025)
    gold = await client.get_series("gold", category="quantity_shipped")
    assert [(p.year, p.value, p.units) for p in gold.points] == [
        (2018, 191881.859, "kilograms"),
        (2019, 184456.0, "Kilograms"),
        (2025, 184456.0, "Kilograms"),
    ]
    total = await client.get_series("Grand total")
    # The 2018 file's 2017 grand total is not taken as a 2018 point.
    assert (total.points[0].year, total.points[0].value) == (2018, 49049260.0)
    # "iron" is one commodity before 2019 and two after.
    iron = await client.get_series("iron")
    assert [p.year for p in iron.points] == [2018] and iron.missing_years == [2019, 2025]
    assert "Iron, agglomerates" in iron.note
    with pytest.raises(InvalidInput):
        await client.get_series("gold", category="tonnes")
