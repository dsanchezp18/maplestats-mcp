"""dfo_landings/client.py against excerpts of the files recorded live on
2026-11-08 (open.canada.ca package_show and DFO's data hub CSVs).
"""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.dfo_landings import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

HUB = "https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records"
SEA_EN_URL = f"{HUB}/{constants.SEA_DATASET_ID}/attachments/sea-en.csv"
SEA_FR_URL = f"{HUB}/{constants.SEA_DATASET_ID}/attachments/sea-fr.csv"
FW_URL = f"{HUB}/{constants.FRESHWATER_DATASET_ID}/attachments/freshwater-landings-{{year}}.csv"

SEA_PACKAGE = {
    "result": {
        "title": "Commercial Fisheries - Seafisheries Landings - Canada",
        "title_translated": {"en": "Commercial Fisheries - Seafisheries Landings - Canada"},
        "metadata_modified": "2026-09-25T18:12:22",
        "time_period_coverage_start": "1990-01-01 00:00:00",
        "time_period_coverage_end": "2024-12-31 00:00:00",
        "resources": [
            {"name": "1990-2024 EN", "format": "CSV", "language": ["en"], "url": SEA_EN_URL},
            {"name": "1990-2024 FR", "format": "CSV", "language": ["fr"], "url": SEA_FR_URL},
            {"name": "Data Dictionary", "format": "CSV", "language": ["en", "fr"], "url": "x"},
        ],
    }
}
FW_PACKAGE = {
    "result": {
        "title": "Commercial Fisheries - Freshwater Landings - Canada",
        "metadata_modified": "2026-05-08T02:12:17",
        "resources": [
            {
                "name": f"Freshwater Landings - {year}",
                "format": "CSV",
                "language": ["en"],
                "url": FW_URL.format(year=year),
            }
            for year in (2011, 2019)
        ],
    }
}

# Excerpt of the English sea file (cp1252, thousands commas, notes at the end).
SEA_EN = (
    "Year,Province,Species Group,Species,Quantity (kgs),Value (CAD)\r\n"
    "2006,New Brunswick,Shellfish,Clams,x,x\r\n"
    '2024,Nova Scotia,Shellfish,Lobster,"44,521,929","961,890,880"\r\n'
    '2024,Nova Scotia,Shellfish,Total shellfish,"90,000,000","1,500,000,000"\r\n'
    '2024,Canada,Grand total,Grand total,"626,224,846","4,009,150,286"\r\n'
    "2024,Quebec,Pelagics,Herring,109156,99932.74\r\n"
    "Totals may not add up due to rounding.,,,,,\r\n"
    "Species not listed are grouped in each species group’s other category.,,,,,\r\n"
).encode("cp1252")

# The 2011 freshwater file: the Q/V row says V, Q over N.S. and N.B.
FW_2011 = (
    ',,"Freshwater Fisheries - Catches and Landed Values by Species, By Province/Territory, '
    '2011",,,,,\n'
    ",,Nominal catches (Q) in tonnes. Values (V) in thousand dollars,,,,,\n"
    " Species,N.S.,,N.B.,,Ontario,,Canada,\n"
    ",V,Q,V,Q,Q,V,Q,V\n"
    "Alewife,226,111,446,412,-,-,672 ,523 \n"
    'Tullibee (1),,-,-,-," 2 021"," 9 541","2,021 ","9,541 "\n'
    "Other fish,,0 ,-0 ,0 ,,,0,0\n"
    'Total,226,111,446,412,"2,021","9,541","2,693 ","10,064 "\n'
    ",,,,,,,,\n"
    "(1) Includes lake herring, chub and cisco.,,,,,,,,\n"
).encode("utf-8-sig")

FW_2019 = (
    b",,Freshwater 2019,,,\n"
    b" Species,Manitoba,,Canada,\n"
    b",Q,V,Q,V\n"
    b"Yellow Pickerel, 4 028 , 16 253 , 8 244 , 36 460 \n"
    b"Total, 4 028 , 16 253 , 8 244 , 36 460 \n"
)

SEA_FR = (
    "Année,Province,Groupe d'espèces,Espèces,Quantité (kg),Valeur (CAD)\r\n"
    "2024,Nouvelle-Écosse,Mollusques et crustacés,Homard,44521929,961890880.1\r\n"
).encode("cp1252")


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _packages(httpx_mock) -> None:
    httpx_mock.add_response(
        url=re.compile(rf".*package_show\?id={constants.SEA_DATASET_ID}"),
        json=SEA_PACKAGE,
        is_optional=True,
    )
    httpx_mock.add_response(
        url=re.compile(rf".*package_show\?id={constants.FRESHWATER_DATASET_ID}"),
        json=FW_PACKAGE,
        is_optional=True,
    )


def test_sea_parser_converts_kilograms_and_flags_suppression_and_totals():
    rows, notes = client.parse_sea_csv(SEA_EN.decode("cp1252"))
    clams, lobster, group_total, grand, herring = rows
    assert clams["suppressed"] and clams["quantity_tonnes"] is None
    assert lobster["quantity_tonnes"] == 44521.929 and lobster["value_dollars"] == 961890880.0
    assert group_total["is_total"] and grand["is_total"] and not lobster["is_total"]
    assert herring["quantity_tonnes"] == 109.156 and herring["value_dollars"] == 99932.74
    assert notes[0] == "Totals may not add up due to rounding."


def test_freshwater_parser_reads_pairs_as_quantity_then_value():
    rows, notes = client.parse_freshwater_csv(FW_2011.decode("utf-8-sig"), 2011, "en")
    alewife = {r["region"]: r for r in rows if r["species"] == "Alewife"}
    # The mislabelled 2011 sub-header: N.S. 226 + N.B. 446 = Canada 672 (quantity).
    assert alewife["Nova Scotia"]["quantity_tonnes"] == 226.0
    assert alewife["Nova Scotia"]["value_dollars"] == 111000.0
    assert alewife["Canada"]["quantity_tonnes"] == 672.0
    assert "Ontario" not in alewife  # "-" cells: nothing reported
    tullibee = {r["region"]: r for r in rows if r["species"] == "Tullibee"}
    assert tullibee["Ontario"]["quantity_tonnes"] == 2021.0
    assert tullibee["Ontario"]["value_dollars"] == 9541000.0
    other = {r["region"]: r for r in rows if r["species"] == "Other fish"}
    assert other["New Brunswick"]["quantity_tonnes"] == 0.0
    assert notes == ["(1) Includes lake herring, chub and cisco."]
    assert any(r["is_total"] and r["region"] == "Canada" for r in rows)


async def test_sea_landings_default_to_the_latest_year_and_filter(httpx_mock):
    _packages(httpx_mock)
    httpx_mock.add_response(url=SEA_EN_URL, content=SEA_EN)
    result = await client.get_landings(region="nova scotia", species="lobster")
    assert result.years == [2024]
    assert [(r.region, r.species, r.quantity_tonnes) for r in result.rows] == [
        ("Nova Scotia", "Lobster", 44521.929)
    ]
    assert result.provenance.commercial_use == "allowed"
    assert "Open Government Licence" in (result.provenance.licence or "")


async def test_sea_landings_can_drop_totals_and_filter_by_group(httpx_mock):
    _packages(httpx_mock)
    httpx_mock.add_response(url=SEA_EN_URL, content=SEA_EN)
    result = await client.get_landings(year=2024, species_group="shellfish", include_totals=False)
    assert [r.species for r in result.rows] == ["Lobster"]


async def test_french_reads_the_french_file(httpx_mock):
    _packages(httpx_mock)
    httpx_mock.add_response(url=SEA_FR_URL, content=SEA_FR)
    result = await client.get_landings(region="nouvelle-ecosse", species="homard", lang="fr")
    assert result.rows[0].region == "Nouvelle-Écosse"
    assert result.rows[0].value_dollars == 961890880.1


async def test_freshwater_years_read_one_file_each(httpx_mock):
    _packages(httpx_mock)
    httpx_mock.add_response(url=FW_URL.format(year=2011), content=FW_2011)
    httpx_mock.add_response(url=FW_URL.format(year=2019), content=FW_2019)
    result = await client.get_landings(
        "freshwater", start_year=2011, end_year=2019, species="total"
    )
    assert result.years == [2011, 2019]
    canada = {r.year: r.quantity_tonnes for r in result.rows if r.region == "Canada"}
    assert canada == {2011: 2693.0, 2019: 8244.0}


async def test_input_errors(httpx_mock):
    _packages(httpx_mock)
    with pytest.raises(InvalidInput):
        await client.get_landings(year=2020, start_year=2019)
    with pytest.raises(InvalidInput):
        await client.get_landings("freshwater", species_group="pelagics")
    with pytest.raises(InvalidInput):
        await client.get_landings(limit=0)
    with pytest.raises(NotFound):
        await client.get_landings("freshwater", year=2024)


async def test_list_tables_reports_years_and_files(httpx_mock):
    _packages(httpx_mock)
    result = await client.list_tables()
    sea, fresh = result.tables
    assert (sea.first_year, sea.last_year, len(sea.files)) == (1990, 2024, 2)
    assert (fresh.first_year, fresh.last_year) == (2011, 2019)
    assert fresh.value_unit_published == "thousands of dollars"
