"""Tests on pages and files shaped like the real NFD ones (checked 2026-10-02).

Each fixture copies a quirk seen live: the single-quoted dictionary link of
table 2, a caption with no space ("4.Area of ..."), the French page in
Windows-1252 with HTML entities, bilingual CSVs with a BOM and CRLF, the
six-column property-losses layout, footnote markers in labels, "YK" for
Yukon, repeated keys, blank values with a quality code, case-sensitive
quality codes, a table mixing rates and totals, and a comments file that
answers 404.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.nfd import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

CAUSE_CSV_PATH = "/download/data/csv/NFD - Area burned by cause class - EN FR.csv"
LOSSES_CSV_PATH = "/download/data/csv/NFD - Property losses from fires - EN FR.csv"
HARVEST_CSV_PATH = "/download/data/csv/NFD - Net Merchantable Volume of Roundwood Harvested.csv"
RATES_CSV_PATH = "/download/data/csv/NFD - Rate and amount of herbicides applied by product.csv"
SCARIF_CSV_PATH = "/download/data/csv/NFD - Area of scarification by ownership - EN FR.csv"


def _link(path: str, badge: str) -> str:
    return f'<a href="{path}" download><span class="badge">{badge}</span></a>'


def _table(caption: str, csv_path: str, dd: str, comments: str | None, dd_quote: str = '"') -> str:
    comment_row = (
        f'<tr><td>Data Comments</td><td><a href="{comments}" download>XLS</a></td></tr>'
        if comments
        else ""
    )
    return f"""
<table class="table">
<caption>
<strong>{caption}</strong>
</caption>
<thead><tr><th>Resource Type</th><th>Formats</th></tr></thead>
<tbody>
<tr><td>Data</td><td>{_link(csv_path.replace("csv", "xlsx"), "XLSX")}{_link(csv_path, "CSV")}</td></tr>
<tr><td>Data Dictionary</td><td><a class='x' href={dd_quote}{dd}{dd_quote} download>XLSX</a></td></tr>
{comment_row}
</tbody>
</table>
"""


def _page(titles: dict[str, str], sections: dict[str, str], comments: bool = True) -> str:
    cause_dd = "/en/data/data_dictionary/NFD - Area burned by cause class - EN FR DD.xlsx"
    return (
        "<html><body><nav><h2>Language selection</h2></nav>"
        '<div id="content"><h1>Download</h1>'
        f"<h2>{sections['fires']}</h2>"
        + _table(titles["3.2.1"], CAUSE_CSV_PATH, cause_dd, None)
        + _table(
            titles["3.3"],
            LOSSES_CSV_PATH,
            "/en/data/data_dictionary/NFD - Property losses from fires - EN FR DD.xlsx",
            "/en/data/comments/NFD - Property losses from fires - EN FR COMMENTS.xls"
            if comments
            else None,
        )
        + f"<h2>{sections['harvest']}</h2>"
        + _table(
            titles["5.1"],
            HARVEST_CSV_PATH,
            "/en/data/data_dictionary/NFD - Harvest DD.xlsx",
            "/en/data/comments/NFD - Harvest COMMENTS.xls",
            dd_quote="'",
        )
        + _table(
            titles["6.2"], SCARIF_CSV_PATH, "/en/data/data_dictionary/NFD - Scarif DD.xlsx", None
        )
        + f"<h2>{sections['pest']}</h2>"
        + _table(
            titles["8.2.3"], RATES_CSV_PATH, "/en/data/data_dictionary/NFD - Rates DD.xlsx", None
        )
        + "</div></body></html>"
    )


EN_TITLES = {
    "3.2.1": "3.2.1.  Area burned by cause class",
    "3.3": "3.3. Property  losses from fires",
    "5.1": "5.1.  Net merchantable volume of roundwood harvested by ownership, category and  species group",
    "6.2": "6.2.  Area of scarification by ownership",
    "8.2.3": "8.2.3.  Rate and amount of herbicides applied by product",
}
EN_SECTIONS = {"fires": "Forest Fires", "harvest": "Harvest", "pest": "Pest Control"}
# 4 has no space after the number on the real page; the French page mixes
# Windows-1252 bytes with HTML entities.
FR_TITLES = {
    "3.2.1": "3.2.1 Superficie incendiée par origine",
    "3.3": "3.3.  Dommage à la propriété dues aux incendies",
    "5.1": "5.1.  Volume marchand net de bois rond r&eacute;colt&eacute;",
    "6.2": "6.2.  Superficie scarifiée par propriétaire",
    "8.2.3": "8.2.3.  Taux et quantité d&rsquo;herbicides épandus par produit",
}
FR_SECTIONS = {"fires": "Incendies de for&ecirc;t", "harvest": "R&eacute;colte", "pest": "Produits"}

EN_PAGE = _page(EN_TITLES, EN_SECTIONS)
FR_PAGE = _page(FR_TITLES, FR_SECTIONS).replace("/en/data", "/fr/data").encode("cp1252")

CAUSE_CSV = (
    "﻿Year,Année,ISO,Jurisdiction,Juridiction,Cause,Origine,Area (hectares),"
    "Data Qualifier,Superficie (en hectare),Qualificatifs de données\r\n"
    "2023,2023,AB,Alberta,Alberta,Human activity,Activité humaine,100.5,a,100.5,a\r\n"
    "2023,2023,AB,Alberta,Alberta,Natural cause,Cause naturelle,3000,a,3000,a\r\n"
    "2023,2023,BC,British Columbia,Colombie-Britannique,Human activity,Activité humaine,"
    "200,a,200,a\r\n"
    "2023,2023,BC,British Columbia,Colombie-Britannique,Natural cause,Cause naturelle,"
    "2000000.25,a,2000000.25,a\r\n"
    "2022,2022,PE,Prince Edward Island,Île-du-Prince-Édouard,Human activity,"
    "Activité humaine,0.02,a,0.02,a\r\n"
    "2022,2022,PE,Prince Edward Island,Île-du-Prince-Édouard,Human activity,"
    "Activité humaine,18,a,18,a\r\n"
    "2022,2022,QC,Quebec,Québec,Natural cause,Cause naturelle,,u,,u\r\n"
).encode()

# Property losses: six columns, combined year heading, no label pairs.
LOSSES_CSV = (
    "﻿Year / Année,ISO,Jurisdiction,Juridiction,Dollars,"
    "Data qualifier / Qualificatifs de données\r\n"
    "2020,BC,British Columbia,Colombie-Britannique,344684,a\r\n"
    "2020,NP,National parks,Parcs nationaux,,u\r\n"
    "2021,BC,British Columbia,Colombie-Britannique,12,E\r\n"
    "2021,BC,British Columbia,Colombie-Britannique,3,e\r\n"
).encode()

HARVEST_CSV = (
    "﻿Year,Année,ISO,Jurisdiction,Juridiction,Category,Catégorie,Species group,"
    "Groupe d'espèces,Tenure (En),Tenure (Fr),Volume (cubic metres),Data qualifier,"
    "Volume (en mètre cube),Qualificatifs de données\r\n"
    "2005,2005,NB,New Brunswick,Nouveau-Brunswick,Fuelwood*b and firewood*c,"
    "Bois de chauffage*b et de foyer*c,Unspecified,Indéterminée,Federal land,"
    "Terres fédérales,,u,,u\r\n"
    "2005,2005,NB,New Brunswick,Nouveau-Brunswick,Pulpwood,Bois à pâte,Softwoods,"
    "Résineux,Provincial land,Terres provinciales,1500000,a,1500000,a\r\n"
    "2005,2005,NB,New Brunswick,Nouveau-Brunswick,Pulpwood,Bois à pâte,Softwoods,"
    "Résineux,Provincial land,Terres provinciales,500,E,500,E\r\n"
    "2006,2006,NB,New Brunswick,Nouveau-Brunswick,Pulpwood,Bois à pâte,Hardwoods,"
    "Feuillus,Private land,Terres privées,70,,70,\r\n"
).encode()

RATES_CSV = (
    "﻿Year,Année,ISO,Jurisdiction,Juridiction,Product,Produit,Unit of Measure,"
    "Unité de mesure,Value,Data qualifier,Valeur,Qualificatifs de données\r\n"
    "2020,2020,ON,Ontario,Ontario,Glyphosate,Glyphosate,Rate (kg/ha),Dose (kg/ha),2,a,2,a\r\n"
    "2020,2020,ON,Ontario,Ontario,Glyphosate,Glyphosate,Total applied (kg),"
    "Total appliqué (kg),9000,a,9000,a\r\n"
    "2020,2020,ON,Ontario,Ontario,Glyphosate,Glyphosate,Total applied (kg),"
    "Total appliqué (kg),1000,a,1000,a\r\n"
).encode()

# Scarification codes Yukon "YK" on some rows and "YT" on others.
SCARIF_CSV = (
    "﻿Year,Année,ISO,Jurisdiction,Juridiction,Tenure (En),Tenure (Fr),Area (hectares),"
    "Data qualifier,Superficie (en hectare),Qualificatifs de données\r\n"
    "1990,1990,YK,Yukon,Yukon,Federal land,Terres fédérales,5,a,5,a\r\n"
    "2020,2020,YT,Yukon,Yukon,Federal land,Terres fédérales,7,p,7,p\r\n"
).encode()


def _dictionary(title: str, source: str) -> bytes:
    book = Workbook()
    english = book.active
    assert english is not None
    english.title = "English"
    from datetime import datetime

    for row in (
        ("Title", title),
        ("Filename", "NFD - x - EN FR"),
        ("Last update", datetime(2026, 6, 17)),  # noqa: DTZ001
        ("Source(s)", source),
    ):
        english.append(row)
    french = book.create_sheet("Francais")
    for row in (
        ("Titre", f"{title} (fr)"),
        ("Nom de fichier", "x"),
        ("Dernière mise à jour", datetime(2026, 6, 17)),  # noqa: DTZ001
        ("Source(s)", f"{source} (fr)"),
    ):
        french.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _url(path: str) -> str:
    return client._file_url(path)


@pytest.fixture(autouse=True)
def _setup():
    cache_module._caches.clear()
    yield


def _mock_pages(httpx_mock):
    httpx_mock.add_response(url=constants.PAGE_EN, text=EN_PAGE, is_reusable=True)
    httpx_mock.add_response(url=constants.PAGE_FR, content=FR_PAGE, is_reusable=True)


async def test_catalogue_lists_tables_in_numeric_order(httpx_mock):
    _mock_pages(httpx_mock)
    result = await client.list_tables()
    assert [t.table_id for t in result.tables] == ["3.2.1", "3.3", "5.1", "6.2", "8.2.3"]
    first = result.tables[0]
    assert first.title == "Area burned by cause class" and first.section == "Forest Fires"
    assert first.csv_url == (
        "http://nfdp.ccfm.org/download/data/csv/NFD%20-%20Area%20burned%20by%20cause%20class"
        "%20-%20EN%20FR.csv"
    )
    assert first.comments_url is None
    harvest = next(t for t in result.tables if t.table_id == "5.1")
    # The dictionary link of this table is single-quoted on the real page.
    assert harvest.dictionary_url and harvest.dictionary_url.endswith("Harvest%20DD.xlsx")
    assert harvest.comments_url and harvest.title.endswith("species group")
    assert result.sections == ["Forest Fires", "Harvest", "Pest Control"]


async def test_catalogue_french_titles_and_section_filter(httpx_mock):
    _mock_pages(httpx_mock)
    result = await client.list_tables("recolte", lang="fr")
    assert [t.table_id for t in result.tables] == ["5.1", "6.2"]
    titles = {t.table_id: t.title for t in (await client.list_tables(lang="fr")).tables}
    assert titles["3.2.1"] == "Superficie incendiée par origine"
    assert titles["8.2.3"].startswith("Taux et quantité d’herbicides")
    assert (await client.list_tables(lang="fr")).sections[0] == "Incendies de forêt"
    dictionary = next(
        t for t in (await client.list_tables(lang="fr")).tables if t.table_id == "3.2.1"
    )
    assert dictionary.dictionary_url and "/fr/data/data_dictionary/" in dictionary.dictionary_url


async def test_unknown_section_filter_lists_sections(httpx_mock):
    _mock_pages(httpx_mock)
    with pytest.raises(InvalidInput, match="Forest Fires"):
        await client.list_tables("wolves")


async def test_empty_page_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=constants.PAGE_EN, text="<html><body>maintenance</body></html>")
    httpx_mock.add_response(url=constants.PAGE_FR, text="<html></html>")
    with pytest.raises(UpstreamError, match="no tables"):
        await client.list_tables()


async def test_describe_with_dictionary(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV)
    httpx_mock.add_response(
        url=_url("/en/data/data_dictionary/NFD - Area burned by cause class - EN FR DD.xlsx"),
        content=_dictionary("Area burned by jurisdiction and cause class", "CWFIS"),
    )
    result = await client.describe_table("3.2.1")
    assert result.unit == "hectares" and result.value_label == "Area (hectares)"
    assert (result.first_year, result.last_year, result.n_rows) == (2022, 2023, 7)
    assert result.dictionary_title == "Area burned by jurisdiction and cause class"
    assert result.source == "CWFIS" and str(result.last_updated) == "2026-06-17"
    cause = result.dimensions[0]
    assert cause.key == "cause" and cause.values == ["Human activity", "Natural cause"]
    assert [j.iso for j in result.jurisdictions] == ["AB", "BC", "PE", "QC"]
    assert set(result.qualifiers) == {"a", "u"}
    assert any("1 combinations" in q for q in result.quirks)
    assert any("Blank values" in q for q in result.quirks)
    assert result.provenance.as_of is not None


async def test_describe_survives_an_unreadable_dictionary(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV)
    httpx_mock.add_response(
        url=_url("/en/data/data_dictionary/NFD - Area burned by cause class - EN FR DD.xlsx"),
        status_code=404,
    )
    result = await client.describe_table("3.2.1")
    assert result.dictionary_title is None and result.last_updated is None


async def test_describe_french(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV)
    httpx_mock.add_response(
        url=_url("/fr/data/data_dictionary/NFD - Area burned by cause class - EN FR DD.xlsx"),
        content=_dictionary("Area burned", "CWFIS"),
    )
    result = await client.describe_table("3.2.1", lang="fr")
    assert result.unit == "hectares" and result.value_label == "Superficie (en hectare)"
    assert result.dictionary_title == "Area burned (fr)"
    assert result.qualifiers["u"].startswith("nombres non disponibles")
    assert result.dimensions[0].values == ["Activité humaine", "Cause naturelle"]


async def test_table_id_forms(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(SCARIF_CSV_PATH), content=SCARIF_CSV, is_reusable=True)
    for form in ("6.2", " 6.2. ", "6.2."):
        result = await client.query_table(form)
        assert result.table_id == "6.2"
    with pytest.raises(InvalidInput, match="table ids are"):
        await client.query_table("99")


async def test_query_filters_in_either_language(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV, is_reusable=True)
    english = await client.query_table(
        "3.2.1", province="bc", year_from=2023, filters={"cause": "natural cause"}
    )
    assert [(r.iso, r.value, r.unit) for r in english.rows] == [("BC", 2000000.25, "hectares")]
    french = await client.query_table(
        "3.2.1",
        province=["Colombie-Britannique", "Alberta"],
        filters={"Origine": ["cause naturelle"]},
        lang="fr",
    )
    assert [(r.iso, r.jurisdiction, r.dimensions) for r in french.rows] == [
        ("AB", "Alberta", {"cause": "Cause naturelle"}),
        ("BC", "Colombie-Britannique", {"cause": "Cause naturelle"}),
    ]
    assert french.title == "Superficie incendiée par origine"
    assert french.qualifiers == {"a": "valeur actuelle"}


async def test_blank_value_is_null_with_its_code(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV)
    result = await client.query_table("3.2.1", province="QC")
    row = result.rows[0]
    assert row.value is None and row.qualifiers == ["u"] and row.n_missing == 1
    assert "u" in result.qualifiers
    dropped = await client.query_table("3.2.1", province="QC", drop_missing=True)
    assert dropped.rows == []


async def test_repeated_keys_are_kept_and_summed_when_grouped(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV, is_reusable=True)
    plain = await client.query_table("3.2.1", province="PE")
    assert [r.value for r in plain.rows] == [0.02, 18.0]
    assert any("repeat" in n for n in plain.notes)
    grouped = await client.query_table("3.2.1", province="PE", group_by=["year", "cause"])
    assert grouped.rows[0].value == pytest.approx(18.02) and grouped.rows[0].n_rows == 2
    assert grouped.group_by == ["year", "cause"]
    # Live 2026-10-03: province="BC", group_by=["year"] gave jurisdiction null
    # on every row although only BC was summed.
    assert grouped.rows[0].iso == "PE" and grouped.rows[0].jurisdiction


async def test_group_by_year_sums_provinces_and_ignores_blank(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV)
    result = await client.query_table("3.2.1", group_by=["Year"])
    by_year = {r.year: r for r in result.rows}
    assert by_year[2023].value == pytest.approx(2003300.75)
    assert by_year[2022].value == pytest.approx(18.02) and by_year[2022].n_missing == 1
    assert by_year[2022].qualifiers == ["a", "u"]
    assert by_year[2022].iso is None and by_year[2022].dimensions == {}


async def test_property_losses_layout_and_non_provincial_codes(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(LOSSES_CSV_PATH), content=LOSSES_CSV, is_reusable=True)
    result = await client.query_table("3.3")
    assert result.unit == "dollars"
    assert [(r.year, r.iso, r.value) for r in result.rows] == [
        (2020, "BC", 344684.0),
        (2020, "NP", None),
        (2021, "BC", 12.0),
        (2021, "BC", 3.0),
    ]
    assert result.rows[0].dimensions == {}
    summed = await client.query_table("3.3", group_by=["year"])
    assert any("non-provincial" in n for n in summed.notes)
    httpx_mock.add_response(
        url=_url("/en/data/data_dictionary/NFD - Property losses from fires - EN FR DD.xlsx"),
        status_code=404,
    )
    description = await client.describe_table("3.3")
    assert any("national parks" in q for q in description.quirks)
    assert description.value_label == "Dollars" and description.unit == "dollars"


async def test_footnote_markers_are_split_from_labels(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(HARVEST_CSV_PATH), content=HARVEST_CSV, is_reusable=True)
    result = await client.query_table("5.1", filters={"category": "Fuelwood and firewood"})
    row = result.rows[0]
    assert row.dimensions["category"] == "Fuelwood and firewood"
    assert row.footnotes == ["b", "c"] and row.value is None
    french = await client.query_table(
        "5.1", filters={"categorie": "bois de chauffage et de foyer"}, lang="fr"
    )
    assert french.rows[0].dimensions["category"] == "Bois de chauffage et de foyer"
    assert result.unit == "cubic metres"


async def test_missing_qualifier_and_case_sensitive_codes(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(HARVEST_CSV_PATH), content=HARVEST_CSV)
    result = await client.query_table("5.1", filters={"category": "Pulpwood"})
    assert [(r.value, r.qualifiers) for r in result.rows] == [
        (1500000.0, ["a"]),
        (500.0, ["E"]),
        (70.0, []),
    ]
    assert "E" in result.qualifiers and "estimated by Statistics Canada" in result.qualifiers["E"]


async def test_yukon_alias(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(SCARIF_CSV_PATH), content=SCARIF_CSV, is_reusable=True)
    for spelling in ("YK", "yt", "Yukon"):
        result = await client.query_table("6.2", province=spelling)
        assert [(r.year, r.iso) for r in result.rows] == [(1990, "YT"), (2020, "YT")]
    httpx_mock.add_response(
        url=_url("/en/data/data_dictionary/NFD - Scarif DD.xlsx"), status_code=404
    )
    description = await client.describe_table("6.2")
    assert [j.iso for j in description.jurisdictions] == ["YT"]
    assert any("YK" in q for q in description.quirks)


async def test_unit_of_measure_must_not_be_summed_blindly(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(RATES_CSV_PATH), content=RATES_CSV, is_reusable=True)
    plain = await client.query_table("8.2.3")
    assert plain.unit is None
    assert [r.unit for r in plain.rows] == [
        "Rate (kg/ha)",
        "Total applied (kg)",
        "Total applied (kg)",
    ]
    with pytest.raises(InvalidInput, match="mixes rates and totals"):
        await client.query_table("8.2.3", group_by=["year"])
    totals = await client.query_table(
        "8.2.3", group_by=["year"], filters={"unit_of_measure": "Total applied (kg)"}
    )
    assert totals.rows[0].value == 10000 and totals.rows[0].unit == "Total applied (kg)"
    both = await client.query_table("8.2.3", group_by=["year", "unit_of_measure"])
    assert {r.dimensions["unit_of_measure"] for r in both.rows} == {
        "Rate (kg/ha)",
        "Total applied (kg)",
    }


async def test_bad_arguments(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV, is_reusable=True)
    with pytest.raises(InvalidInput, match="Atlantis"):
        await client.query_table("3.2.1", province="Atlantis")
    with pytest.raises(InvalidInput, match="Unknown column 'colour'"):
        await client.query_table("3.2.1", filters={"colour": "red"})
    with pytest.raises(InvalidInput, match="Human activity"):
        await client.query_table("3.2.1", filters={"cause": "Lightning"})
    with pytest.raises(InvalidInput, match="did you mean 'Natural cause'"):
        await client.query_table("3.2.1", filters={"cause": "natural"})
    with pytest.raises(InvalidInput, match="year_from"):
        await client.query_table("3.2.1", year_from=2024, year_to=2020)
    with pytest.raises(InvalidInput, match="limit"):
        await client.query_table("3.2.1", limit=0)


async def test_limit_caps_rows_and_says_so(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV)
    result = await client.query_table("3.2.1", limit=2)
    assert (result.returned_count, result.matched_count) == (2, 7)
    assert (result.provenance.limits or "").startswith("Returned the most recent 2 of 7 rows")
    full = await client.query_table("3.2.1", limit=7)
    newest = sorted((r.year or 0 for r in full.rows), reverse=True)[:2]
    assert sorted(r.year or 0 for r in result.rows) == sorted(newest)
    assert "Open Government Licence - Canada" in (result.provenance.licence or "")
    assert "Licence" not in (result.provenance.freshness or "")


async def test_french_notes_limits_errors_and_licence(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=CAUSE_CSV, is_reusable=True)
    result = await client.query_table("3.2.1", limit=2, lang="fr")
    limits = result.provenance.limits or ""
    assert limits.startswith("Résultat limité à 2 lignes sur 7 (période la plus récente)")
    assert (result.provenance.licence or "").startswith("Licence du gouvernement ouvert – Canada")
    assert "Conditions d'utilisation de la BNDF\xa0:" in (result.provenance.licence or "")
    assert (result.provenance.freshness or "").startswith("Mise à jour quelques fois par année")
    plain = await client.query_table("3.2.1", province="PE", lang="fr")
    assert any("se répètent dans le fichier" in n for n in plain.notes)
    with pytest.raises(InvalidInput, match=r"^Entrée invalide\xa0: colonne 'colour' inconnue"):
        await client.query_table("3.2.1", filters={"colour": "red"}, lang="fr")
    with pytest.raises(InvalidInput, match="vouliez-vous dire 'Natural cause'"):
        await client.query_table("3.2.1", filters={"cause": "natural"}, lang="fr")
    with pytest.raises(InvalidInput, match="aucune administration 'Atlantis'"):
        await client.query_table("3.2.1", province="Atlantis", lang="fr")


async def test_french_frame_for_a_file_error(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=b"a,b,c\r\n1,2,3\r\n")
    with pytest.raises(UpstreamError, match="le fichier de la BNDF n'a pas pu être lu"):
        await client.query_table("3.2.1", lang="fr")


async def test_unexpected_columns_are_an_upstream_error(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), content=b"a,b,c\r\n1,2,3\r\n")
    with pytest.raises(UpstreamError, match="unexpected columns"):
        await client.query_table("3.2.1")


async def test_html_answer_for_a_csv_is_not_found(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), text="<!DOCTYPE html><html>oops</html>")
    with pytest.raises(NotFound, match="not a CSV"):
        await client.query_table("3.2.1")


async def test_server_error_and_timeout(httpx_mock):
    _mock_pages(httpx_mock)
    httpx_mock.add_response(url=_url(CAUSE_CSV_PATH), status_code=500, is_reusable=True)
    with pytest.raises(UpstreamError, match="HTTP 500"):
        await client.query_table("3.2.1")
    cache_module._caches.clear()
    httpx_mock.reset()
    _mock_pages(httpx_mock)
    import httpx

    httpx_mock.add_exception(
        httpx.ConnectTimeout("slow"), url=_url(CAUSE_CSV_PATH), is_reusable=True
    )
    with pytest.raises(UpstreamUnavailable, match="did not answer"):
        await client.query_table("3.2.1")


async def test_redirect_to_https_is_followed(httpx_mock):
    httpx_mock.add_response(
        url=constants.PAGE_EN,
        status_code=301,
        headers={"location": "https://nfdp.ccfm.org/en/download.php"},
    )
    httpx_mock.add_response(url="https://nfdp.ccfm.org/en/download.php", text=EN_PAGE)
    httpx_mock.add_response(url=constants.PAGE_FR, content=FR_PAGE)
    result = await client.list_tables()
    assert result.count == 5


class _FakeSheet:
    def __init__(self, name: str, rows: list[list[object]]) -> None:
        self.name = name
        self._rows = rows
        self.nrows = len(rows)

    def row_values(self, index: int) -> list[object]:
        return self._rows[index]


def _fake_workbook(monkeypatch):
    sheets = [
        _FakeSheet(
            "21_EN",
            [
                ["ISO", "Jurisdiction", "Year", "Protection Zone", "Comment", "Footnotes"],
                ["BC", "British Columbia", 2019.0, "Intensive", "Method changed.", "*a note"],
                ["BC", "British Columbia", 2020.0, "Intensive", "Method changed.", "*a note"],
                ["MB", "Manitoba", 2020.0, "", "Not compiled.", ""],
                ["MB", "Manitoba", 2021.0, "", "", ""],
            ],
        ),
        _FakeSheet(
            "21_FR",
            [
                ["ISO", "Juridiction", "Année", "Commentaire", "Renvois"],
                ["BC", "Colombie-Britannique", 2019.0, "Méthode modifiée.", ""],
            ],
        ),
    ]
    import xlrd

    monkeypatch.setattr(
        xlrd, "open_workbook", lambda **kwargs: SimpleNamespace(sheets=lambda: sheets)
    )


async def test_comments_merge_identical_text_across_years(httpx_mock, monkeypatch):
    _mock_pages(httpx_mock)
    _fake_workbook(monkeypatch)
    httpx_mock.add_response(
        url=_url("/en/data/comments/NFD - Harvest COMMENTS.xls"), content=b"not read"
    )
    result = await client.table_comments("5.1")
    assert [(c.iso, c.years, c.comment) for c in result.comments] == [
        ("BC", [2019, 2020], "Method changed."),
        ("MB", [2020], "Not compiled."),
    ]
    assert result.comments[0].footnotes == "*a note"
    assert result.comments[0].context == "Protection Zone: Intensive"
    filtered = await client.table_comments("5.1", province="manitoba", year_from=2020)
    assert [c.iso for c in filtered.comments] == ["MB"]


async def test_comments_french_sheet(httpx_mock, monkeypatch):
    _mock_pages(httpx_mock)
    _fake_workbook(monkeypatch)
    httpx_mock.add_response(
        url=_url("/en/data/comments/NFD - Harvest COMMENTS.xls"), content=b"not read"
    )
    result = await client.table_comments("5.1", lang="fr")
    assert result.comments[0].comment == "Méthode modifiée."


async def test_table_without_comments_link_or_file(httpx_mock):
    _mock_pages(httpx_mock)
    none_listed = await client.table_comments("3.2.1")
    assert none_listed.comments == [] and "no comments workbook" in none_listed.notes[0]
    httpx_mock.add_response(
        url=_url("/en/data/comments/NFD - Property losses from fires - EN FR COMMENTS.xls"),
        status_code=404,
    )
    gone = await client.table_comments("3.3")
    assert gone.comments == [] and "404" in gone.notes[0]
