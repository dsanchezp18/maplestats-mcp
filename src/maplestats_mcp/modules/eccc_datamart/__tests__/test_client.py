"""Client tests with the quirks seen live on data-donnees.az.ec.gc.ca on 2026-10-03.

npri_2024_sample.csv holds six rows of the live NPRI 2024 single-year CSV, kept
in its Windows-1252 encoding with every field quoted and the trailing blank
line. ghgrp_sample.csv holds six rows of the live GHGRP CSV (UTF-8 with a
byte-order mark) with the public contact columns blanked. Listings follow the
live api/path_contents shape: sizes as rounded text, null display names,
relative paths, and a 302 from api/file to a signed blob URL on the same host.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import pytest

from maplestats_mcp.modules.eccc_datamart import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent
NPRI_BODY = (_HERE / "npri_2024_sample.csv").read_bytes()
GHGRP_BODY = (_HERE / "ghgrp_sample.csv").read_bytes()
NPRI_NAME = "NPRI-INRP_DataDonnées_2024.csv"
GHGRP_NAME = "PDGES-GHGRP-GHGEmissionsGES-2004-Present.csv"
BASE = "https://data-donnees.az.ec.gc.ca"


def _item(path: str, size: str, directory: bool = False, en=None, fr=None) -> dict:
    return {
        "content_length": "0 B" if directory else size,
        "display_name": {"en": en, "fr": fr},
        "is_directory": directory,
        "last_modified": "2026-03-25",
        "name": path.rsplit("/", 1)[-1],
        "path": path.lstrip("/"),
    }


def _listing(parent: str | None, items: list[dict], catalogue_id: str | None = None) -> dict:
    return {"path_catalogue_id": catalogue_id, "path_contents": items, "path_parent": parent}


def _listing_url(path: str) -> re.Pattern[str]:
    return re.compile(re.escape(f"{constants.LISTING_URL}?path={quote(path, safe='')}") + "$")


def _mock_listing(httpx_mock, path: str, body) -> None:
    httpx_mock.add_response(url=_listing_url(path), json=body, is_reusable=True)


def _mock_file(httpx_mock, path: str, body: bytes) -> None:
    public = f"{BASE}/public/{quote(path, safe='/')}?se=2026-10-03&sig=abc"
    httpx_mock.add_response(
        url=client.file_url(path), status_code=302, headers={"location": public}
    )
    httpx_mock.add_response(url=public, content=body, headers={"content-length": str(len(body))})


NPRI_ITEMS = [
    _item(f"{constants.NPRI_FOLDER}/.dir_metadata.json", "204 B"),
    _item(f"{constants.NPRI_FOLDER}/348504f1-43a6-4e0c-aee5-fc470b1dc888.xml", "94 KiB"),
    _item(f"{constants.NPRI_FOLDER}/NPRI-INRP_DataDonnées_2023.csv", "38 MiB"),
    _item(f"{constants.NPRI_FOLDER}/{NPRI_NAME}", "36 MiB"),
    _item(f"{constants.NPRI_FOLDER}/NPRI-INRP_DataDonnées_2024.xlsx", "8 MiB"),
]
GHGRP_ITEMS = [
    _item(f"{constants.GHGRP_FOLDER}/Lisez Moi - Read Me - Emissions by Gas par gaz.csv", "9 KiB"),
    _item(f"{constants.GHGRP_FOLDER}/{GHGRP_NAME}", "10 MiB"),
    _item(f"{constants.GHGRP_FOLDER}/a8ba14b7-7f23-462a-bdbb-83b0ef629823.xml", "78 KiB"),
]


@pytest.fixture(autouse=True)
def _clear_caches():
    cache_module._caches.clear()
    file_download.clear_cache()
    yield
    file_download.clear_cache()


def test_paths_from_urls_and_text():
    assert client.normalize_path("substances/monitor/") == "/substances/monitor"
    assert client.normalize_path(f"{BASE}/data/air/monitor?lang=en") == "/air/monitor"
    assert client.normalize_path(f"{BASE}/api/file?path=%2Fair%2Fa%20b.csv") == "/air/a b.csv"
    assert client.normalize_path("") == "/"
    for bad in ("/air/../etc", "https://example.com/data/air"):
        with pytest.raises(InvalidInput):
            client.normalize_path(bad)


def test_rounded_sizes_and_the_cap():
    assert client.size_bytes("36 MiB") == 36 * 1024 * 1024
    assert client.size_bytes("3 KiB") == 3072
    assert client.size_bytes("57 B") == 57
    assert client.size_bytes("") is None
    # 40 MiB rounds a file that may be just under the cap, so it is tried.
    entry = client.parse_entry(_item("/a/big.csv", "40 MiB"), None, "en")
    assert entry.readable
    assert not client.parse_entry(_item("/a/big.csv", "375 MiB"), None, "en").readable


def test_entry_kinds():
    kinds = {
        name: client.parse_entry(_item(f"/f/{name}", "1 KiB"), "abc", "en").kind
        for name in (
            "data.csv",
            "2022_PAH-HAP.zip",
            "NPRI_DataDictionary.docx",
            "Lisez Moi - Read Me.csv",
            "abc.xml",
            "map.png",
        )
    }
    assert kinds == {
        "data.csv": "table",
        "2022_PAH-HAP.zip": "archive",
        "NPRI_DataDictionary.docx": "documentation",
        "Lisez Moi - Read Me.csv": "documentation",
        "abc.xml": "documentation",
        "map.png": "other",
    }


async def test_browse_sorts_folders_first_and_links_the_catalogue(httpx_mock):
    folder = "/substances/monitor/greenhouse-gas-reporting-program-ghgrp-facility-greenhouse-gas-ghg-data"
    items = [*GHGRP_ITEMS, _item(f"{folder}/sub", "", directory=True, en="Sub", fr="Sous")]
    _mock_listing(httpx_mock, folder, _listing("/substances/monitor", items, "a8ba"))
    _mock_listing(
        httpx_mock,
        "/substances/monitor",
        _listing("/substances", [_item(folder, "", True, en="GHGRP", fr="PDGES")]),
    )
    result = await client.browse(folder, lang="fr")
    assert result.entries[0].kind == "folder" and result.entries[0].title == "Sous"
    assert result.title == "PDGES"
    assert result.catalogue_url == "https://open.canada.ca/data/fr/dataset/a8ba"
    assert result.files == 3 and result.folders == 1
    assert result.provenance.licence and "Licence du gouvernement ouvert – Canada" in (
        result.provenance.licence
    )
    assert result.attribution.startswith("Contient des informations")
    assert (result.provenance.coverage or "").startswith("Les listes et les fichiers")
    english = await client.browse(folder)
    assert english.provenance.licence and "Open Government Licence - Canada" in (
        english.provenance.licence
    )


async def test_french_errors_and_notes(httpx_mock):
    with pytest.raises(InvalidInput, match="^Entrée invalide : eccc_datamart : offset"):
        await client.browse("/", offset=-1, lang="fr")
    _mock_listing(httpx_mock, constants.NPRI_FOLDER, _listing("/x", NPRI_ITEMS))
    with pytest.raises(InvalidInput, match="aucun tableau annuel de l'INRP pour 2015"):
        await client.npri_facilities(year=2015, lang="fr")
    with pytest.raises(InvalidInput, match="province inconnue"):
        await client.npri_facilities(province="Atlantis", lang="fr")
    _mock_file(httpx_mock, f"{constants.NPRI_FOLDER}/{NPRI_NAME}", NPRI_BODY)
    result = await client.npri_facilities(npri_id="1", lang="fr")
    assert "furannes) ; ne comparer" in result.notes[0]
    assert (result.provenance.coverage or "").startswith("Une ligne par installation")


async def test_browse_unknown_path_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_listing_url("/nope"), status_code=404, json="Path not found.")
    with pytest.raises(NotFound):
        await client.browse("/nope")


async def test_browse_on_a_file_points_to_the_reader(httpx_mock):
    _mock_listing(httpx_mock, "/license-en.txt", _listing("/", [_item("license-en.txt", "3 KiB")]))
    with pytest.raises(InvalidInput, match="is a file"):
        await client.browse("/license-en.txt")


async def test_search_walks_three_levels_and_ranks_titles(httpx_mock):
    _mock_listing(
        httpx_mock,
        "/",
        _listing(
            None,
            [_item("substances", "", True, "substances", "substances"), _item("x.txt", "1 B")],
        ),
    )
    _mock_listing(
        httpx_mock,
        "/substances",
        _listing("/", [_item("substances/monitor", "", True, "monitor", "surveillance")]),
    )
    _mock_listing(
        httpx_mock,
        "/substances/monitor",
        _listing(
            "/substances",
            [
                _item(
                    constants.GHGRP_FOLDER,
                    "",
                    True,
                    "Greenhouse Gas Reporting Program (GHGRP)",
                    "Programme de déclaration des gaz à effet de serre (PDGES)",
                ),
                _item("substances/monitor/fish-health", "", True, None, None),
            ],
        ),
    )
    found = await client.search("gaz à effet de serre", lang="fr")
    assert found.indexed_folders == 4
    assert found.hits[0].path == constants.GHGRP_FOLDER
    assert found.hits[0].title.startswith("Programme")
    prefix = await client.search("greenh report")
    assert prefix.hits[0].path == constants.GHGRP_FOLDER
    nameonly = await client.search("fish")
    assert nameonly.hits[0].path == "/substances/monitor/fish-health"
    with pytest.raises(InvalidInput):
        await client.search("fish", topic="nowhere")
    with pytest.raises(InvalidInput):
        await client.search("  ")


async def test_archives_and_big_files_are_refused_without_download(httpx_mock):
    folder = "/air/naps/2022"
    _mock_listing(
        httpx_mock,
        folder,
        _listing("/air/naps", [_item(f"{folder}/2022_PAH-HAP.zip", "608 KiB")]),
    )
    with pytest.raises(InvalidInput, match="does not open archives"):
        await client.read_file(f"{folder}/2022_PAH-HAP.zip")
    bulk = constants.NPRI_BULK_FOLDER
    _mock_listing(
        httpx_mock,
        bulk,
        _listing("/x", [_item(f"{bulk}/NPRI-INRP_ReleasesRejets_1993-present.csv", "375 MiB")]),
    )
    with pytest.raises(InvalidInput, match="cap"):
        await client.read_file(f"{bulk}/NPRI-INRP_ReleasesRejets_1993-present.csv")


async def test_read_file_decodes_windows_1252_and_filters(httpx_mock):
    _mock_listing(httpx_mock, constants.NPRI_FOLDER, _listing("/x", NPRI_ITEMS, "3485"))
    path = f"{constants.NPRI_FOLDER}/{NPRI_NAME}"
    _mock_file(httpx_mock, path, NPRI_BODY)
    rows = await client.read_file(
        path,
        filters={"Province / Province": "ON"},
        columns=["Nom de l'installation / Facility Name", "Unités / Units"],
    )
    assert rows.format == "csv" and rows.total_rows == 2
    assert rows.all_columns[0] == "Année / Year"
    assert rows.rows[0]["Unités / Units"] == "kg"
    assert rows.attribution == constants.OGL_ATTRIBUTION


async def test_describe_lists_documentation_with_excerpt(httpx_mock):
    _mock_listing(
        httpx_mock,
        constants.GHGRP_FOLDER,
        _listing("/x", GHGRP_ITEMS, "a8ba14b7-7f23-462a-bdbb-83b0ef629823"),
    )
    _mock_listing(httpx_mock, "/substances/monitor", _listing("/substances", []))
    path = f"{constants.GHGRP_FOLDER}/{GHGRP_NAME}"
    readme = f"{constants.GHGRP_FOLDER}/Lisez Moi - Read Me - Emissions by Gas par gaz.csv"
    _mock_file(httpx_mock, path, GHGRP_BODY)
    _mock_file(
        httpx_mock,
        readme,
        "Programme de déclaration des gaz à effet de serre (PDGES)\r\nÀ jour".encode("cp1252"),
    )
    structure = await client.describe_file(path)
    assert structure.sheets[0].column_names[0].startswith("GHGRP ID No.")
    docs = {d.name: d for d in structure.documentation}
    assert docs["Lisez Moi - Read Me - Emissions by Gas par gaz.csv"].excerpt == (
        "Programme de déclaration des gaz à effet de serre (PDGES)\nÀ jour"
    )
    assert docs["a8ba14b7-7f23-462a-bdbb-83b0ef629823.xml"].excerpt is None


async def test_npri_lookup_filters_and_ranks_in_tonnes(httpx_mock):
    _mock_listing(httpx_mock, constants.NPRI_FOLDER, _listing("/x", NPRI_ITEMS))
    _mock_file(httpx_mock, f"{constants.NPRI_FOLDER}/{NPRI_NAME}", NPRI_BODY)
    result = await client.npri_facilities(npri_id="1", order="largest")
    assert result.year == 2024 and result.available_years == [2023, 2024]
    assert result.total_records == 3 and result.facilities == 1
    first = result.records[0]
    assert first.substance.startswith("PM10") and first.units == "tonnes"
    assert first.grand_total == pytest.approx(118.131)
    assert first.road_dust == pytest.approx(6.765)
    assert first.province == "AB" and first.naics == "322112"
    mercury = await client.npri_facilities(province="Ontario", substance="mercure", lang="fr")
    assert mercury.total_records == 2
    assert mercury.records[0].substance.startswith("Mercure")
    by_name = await client.npri_facilities(facility="thunder bay")
    assert [r.npri_id for r in by_name.records] == ["930"]


async def test_npri_year_without_single_year_table(httpx_mock):
    _mock_listing(httpx_mock, constants.NPRI_FOLDER, _listing("/x", NPRI_ITEMS))
    with pytest.raises(InvalidInput, match="bulk"):
        await client.npri_facilities(year=2015)
    with pytest.raises(InvalidInput, match="province"):
        await client.npri_facilities(province="Atlantis")


async def test_ghgrp_lookup_years_province_and_ranking(httpx_mock):
    _mock_listing(httpx_mock, constants.GHGRP_FOLDER, _listing("/x", GHGRP_ITEMS))
    _mock_file(httpx_mock, f"{constants.GHGRP_FOLDER}/{GHGRP_NAME}", GHGRP_BODY)
    result = await client.ghgrp_facilities(year=2023, year_to=2024, order="largest")
    assert result.years == [2004, 2023, 2024]
    assert result.total_records == 4 and result.facilities == 2
    assert result.records[0].ghgrp_id == "G10003"
    assert result.records[0].npri_id is None  # the file says 0
    assert result.total_co2e_sum == pytest.approx(53337.564 + 254601.216 + 52134.791 + 257499.354)
    quebec = await client.ghgrp_facilities(province="QC", company="résolu")
    assert {r.year for r in quebec.records} == {2023, 2024}
    assert quebec.records[0].npri_id == "983"
    history = await client.ghgrp_facilities(ghgrp_id="g10001")
    assert len(history.records) == 3
    with pytest.raises(InvalidInput):
        await client.ghgrp_facilities(year=1990)
    with pytest.raises(InvalidInput):
        await client.ghgrp_facilities(year_to=2020)


def test_renamed_column_fails_loudly():
    header = ["GHGRP ID No.", "Reference Year"]
    with pytest.raises(UpstreamError, match="layout"):
        client.locate(header, client.GHGRP_COLUMNS, "GHGRP")
