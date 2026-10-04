"""Tests on responses trimmed from statistique.quebec.ca (2026-09-26)."""

from __future__ import annotations

import json
import re

import pytest

from maplestats_mcp.modules.isq import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_SITEMAP = (
    "<urlset>"
    "<url><loc>https://statistique.quebec.ca/fr/produit/tableau/"
    "revenu-disponible-par-habitant-mrc-et-ensemble-du-quebec</loc></url>"
    "<url><loc>https://statistique.quebec.ca/en/produit/tableau/"
    "operating-statistics-indicators-for-movie-theatres-and-drive-ins-quebec</loc></url>"
    "<url><loc>https://statistique.quebec.ca/fr/document/autre</loc></url>"
    "</urlset>"
)
_HEADER = {
    "tableConfig": {
        "dataSource": {
            "fields": "de_group, de_coln,tri_coln,perc_1,perc_1_sign,ic_1",
            "group": {"field": "de_group", "dir": "asc"},
            "sort": [{"field": "tri_coln", "dir": "asc"}],
        },
        "columns": [
            {"type": "group", "field": "de_group"},
            {"field": "de_coln"},
            {"type": "interval", "direction": "left"},
            {
                "title": "<b>Moins de 1 verre</b>",
                "columns": [
                    {"type": "data", "field": "perc_1", "title": "(%)"},
                    {"type": "note", "field": "perc_1_sign"},
                    {"type": "data", "field": "ic_1", "title": "Intervalle de confiance <br>(IC)"},
                ],
            },
        ],
    }
}
_DATA = (
    "de_group;de_coln;tri_coln;perc_1;perc_1_sign;ic_1\n"
    '"<span data-tri=""010"">Jus</span>";"2 portions ou moins";1;"1 015,5";"r";'
    '"4,5 - 5,5"\n'
    '"Jus";"3 portions";2;"";"x";""\n'
)


# Table 4948 (revenu-disponible-composantes-mrc-ensemble-quebec), trimmed from
# p_retrn_header and p_retrn_data on 2026-10-03: year headers and units are
# "titleField" nodes naming a field, not titles.
_HEADER_4948 = {
    "tableConfig": {
        "dataSource": {
            "fields": "co_tertr,tertr,de_codfc_refrn,mesr,lbl_2024,lbl_2023,"
            "an_2024,an_2024_sign,an_2023,an_2023_sign",
            "sort": [{"field": "tri_tertr", "dir": "asc"}],
        },
        "columns": [
            {"title": "Code", "field": "co_tertr"},
            {"title": "MRC", "field": "tertr"},
            {"title": "Composantes", "field": "de_codfc_refrn"},
            {"type": "interval"},
            {
                "titleField": "lbl_2023",
                "columns": [{"type": "data", "field": "an_2023", "titleField": "mesr"}],
            },
            {
                "titleField": "lbl_2024",
                "columns": [
                    {"type": "data", "field": "an_2024", "titleField": "mesr"},
                    {"type": "note", "field": "an_2024_sign"},
                ],
            },
            {"type": "interval"},
        ],
    }
}
_DATA_4948 = (
    "co_tertr;tertr;de_codfc_refrn;mesr;lbl_2024;lbl_2023;"
    "an_2024;an_2024_sign;an_2023;an_2023_sign\n"
    '"01";"Communauté maritime des Îles-de-la-Madeleine";"Rémunération des salariés";'
    '"$/hab";"2024ᵖ";"2023ʳ";"31 944";"";"30 150";""\n'
    '"01";"Communauté maritime des Îles-de-la-Madeleine";"Rémunération des salariés";'
    '"M$";"2024ᵖ";"2023ʳ";"412,5";"";"390,3";""\n'
).encode()


def _page(data: dict) -> str:
    blob = json.dumps({"props": {"pageProps": {"data": data}}})
    return f'<html><script id="__NEXT_DATA__" type="application/json">{blob}</script></html>'


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _ken(name: str) -> re.Pattern[str]:
    return re.compile(re.escape(constants.KEN + name) + r"(\?.*)?$")


@pytest.fixture
def dynamic(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.SITE}/fr{constants.TABLE_PATH}4074",
        text=_page({"type": "dynamique", "no": 4074, "nom": "Verres d'eau", "sujets": []}),
    )
    httpx_mock.add_response(url=_ken("p_retrn_header"), json=_HEADER)
    httpx_mock.add_response(url=_ken("p_retrn_titre"), text="Nombre de verres d'eau")
    httpx_mock.add_response(url=_ken("p_retrn_data"), text=_DATA)
    httpx_mock.add_response(url=_ken("p_retrn_note_html"), text="<p>Source : ISQ.</p>")
    httpx_mock.add_response(
        url=_ken("p_retrn_signe"),
        text='"signe";"desc";"type"\n"r";"Donnée révisée.";"per"\n"TEST_1";"x";"per"\n',
    )


def test_column_tree_labels_and_flags():
    columns = client.columns_from_tree(_HEADER["tableConfig"]["columns"])
    assert [(c.field, c.label, c.flag_field) for c in columns] == [
        ("de_group", "Groupe", None),
        ("de_coln", "Libellé", None),
        ("perc_1", "Moins de 1 verre / (%)", "perc_1_sign"),
        ("ic_1", "Moins de 1 verre / Intervalle de confiance (IC)", None),
    ]


def test_values_parse_french_numbers():
    assert client.parse_value("1 015,1") == 1015.1
    assert client.parse_value("41 164") == 41164
    assert client.parse_value("4,5 - 5,5") == "4,5 - 5,5"
    assert client.parse_value("..") == ".."
    assert client.parse_value("") is None


async def test_dynamic_table_by_number(dynamic):
    table = await client.get_table("4074", lang="fr")
    assert table.kind == "dynamic" and table.number == 4074
    assert table.title == "Nombre de verres d'eau"
    assert table.columns[0] == "Groupe" and "Libellé" in table.columns
    assert table.rows[0]["Groupe"] == "Jus"  # HTML stripped
    assert table.rows[0]["Moins de 1 verre / (%)"] == 1015.5
    assert table.flags == [{"Moins de 1 verre / (%)": "r"}, {"Moins de 1 verre / (%)": "x"}]
    assert table.total_rows == 2 and table.notes == "Source : ISQ."
    assert table.flag_legend == {"r": "Donnée révisée."}


async def test_title_field_headers_give_years_units_and_flags(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.SITE}/en{constants.TABLE_PATH}4948",
        text=_page(
            {
                "type": "dynamique",
                "no": 4948,
                "nom": "Disposable income¹ and its components, RCMs² and all of Québec²",
                "sujets": [],
            }
        ),
    )
    httpx_mock.add_response(url=_ken("p_retrn_header"), json=_HEADER_4948)
    httpx_mock.add_response(
        url=_ken("p_retrn_titre"), text="Revenu disponible¹ et ses composantes, par MRC²"
    )
    httpx_mock.add_response(url=_ken("p_retrn_data"), content=_DATA_4948)
    httpx_mock.add_response(url=_ken("p_retrn_note_html"), text="<p>p : Données provisoires.</p>")
    httpx_mock.add_response(url=_ken("p_retrn_signe"), text='"signe";"desc";"type"\n')
    table = await client.get_table("4948", lang="en")
    assert table.title.startswith("Disposable income")  # the English page's title
    assert table.columns == ["Code", "MRC", "Composantes", "Unité", "2023", "2024"]
    assert [(r["Unité"], r["2024"], r["2023"]) for r in table.rows] == [
        ("$/hab", 31944, 30150),
        ("M$", 412.5, 390.3),
    ]
    assert table.flags[0] == {"2024": "p", "2023": "r"}


def test_split_mark_reads_superscript_flags():
    assert client.split_mark("2024ᵖ") == ("2024", "p")
    assert client.split_mark("2021") == ("2021", "")


async def test_static_table_falls_back_to_other_language(httpx_mock):
    slug = "population-par-groupe-age"
    httpx_mock.add_response(url=f"{constants.SITE}/en{constants.TABLE_PATH}{slug}", status_code=404)
    httpx_mock.add_response(
        url=f"{constants.SITE}/fr{constants.TABLE_PATH}{slug}",
        text=_page(
            {
                "type": "statique",
                "nom": "Population",
                "excel": "population.xlsx",
                "html": "<table><tr><td>Groupe</td><td>2016</td></tr><tr><td></td></tr>"
                "<tr><td>TOTAL</td><td>197 806</td></tr></table>",
            }
        ),
    )
    table = await client.get_table(slug, lang="en")
    assert table.kind == "static"
    assert table.cells == [["Groupe", "2016"], ["TOTAL", "197 806"]]
    assert table.excel_url == f"{constants.SITE}/fr/fichier/population.xlsx"


async def test_search_folds_accents_and_filters_language(httpx_mock):
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=_SITEMAP, is_reusable=True)
    result = await client.search_tables("Québec MRC revenu", lang="all")
    assert [t.table for t in result.tables] == [
        "revenu-disponible-par-habitant-mrc-et-ensemble-du-quebec"
    ]
    english = await client.search_tables("movie theatres", lang="en")
    assert english.total_matched == 1 and english.tables[0].lang == "en"


async def test_search_merges_french_and_english_pages_of_one_slug(httpx_mock):
    slug = "revenu-disponible-composantes-mrc-ensemble-quebec"
    sitemap = (
        f"<urlset><url><loc>{constants.SITE}/en{constants.TABLE_PATH}{slug}</loc></url>"
        f"<url><loc>{constants.SITE}/fr{constants.TABLE_PATH}{slug}</loc></url></urlset>"
    )
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=sitemap)
    result = await client.search_tables("revenu disponible composantes mrc", lang="all")
    assert result.total_matched == 1
    hit = result.tables[0]
    assert hit.lang == "fr" and hit.languages == ["en", "fr"] and "/fr/" in hit.url


async def test_bad_inputs():
    with pytest.raises(InvalidInput):
        await client.get_table("https://example.com/x")
    with pytest.raises(InvalidInput):
        await client.get_table("../etc")
    with pytest.raises(InvalidInput):
        await client.search_tables("  ")


async def test_not_a_table_page(httpx_mock):
    httpx_mock.add_response(url=f"{constants.SITE}/fr{constants.TABLE_PATH}999", text="<html/>")
    httpx_mock.add_response(url=f"{constants.SITE}/en{constants.TABLE_PATH}999", status_code=404)
    with pytest.raises(NotFound):
        await client.get_table("999", lang="fr")


# French (lang="fr"): titles with accents from the table pages, French errors
# and provenance; English unchanged.

_SLUG_FR = "indicateurs-mensuels-emploi-et-taux-de-chomage-par-region-administrative"


async def test_french_search_reads_accented_titles_from_the_page(httpx_mock):
    sitemap = f"<urlset><url><loc>{constants.SITE}/fr{constants.TABLE_PATH}{_SLUG_FR}</loc></url></urlset>"
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=sitemap)
    httpx_mock.add_response(
        url=f"{constants.SITE}/fr{constants.TABLE_PATH}{_SLUG_FR}",
        text=_page(
            {
                "type": "statique",
                "nom": "Indicateurs mensuels : emploi et taux de chômage par région administrative",
            }
        ),
    )
    result = await client.search_tables("taux de chômage région", lang="fr")
    assert result.tables[0].title == (
        "Indicateurs mensuels : emploi et taux de chômage par région administrative"
    )
    assert result.provenance.freshness == "le plan du site est lu une fois par jour"
    assert "Institut de la statistique du Québec" in (result.provenance.licence or "")


async def test_french_search_keeps_slug_title_when_the_page_fails(httpx_mock):
    sitemap = f"<urlset><url><loc>{constants.SITE}/fr{constants.TABLE_PATH}{_SLUG_FR}</loc></url></urlset>"
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=sitemap)
    httpx_mock.add_response(
        url=f"{constants.SITE}/fr{constants.TABLE_PATH}{_SLUG_FR}", status_code=404
    )
    result = await client.search_tables("chomage", lang="fr")
    assert result.tables[0].title.startswith("Indicateurs mensuels emploi")


async def test_english_search_does_not_fetch_pages(httpx_mock):
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=_SITEMAP)
    english = await client.search_tables("movie theatres", lang="en")
    assert english.tables[0].title.startswith("Operating statistics")
    assert english.provenance.freshness == "the sitemap is read once a day"
    assert len(httpx_mock.get_requests()) == 1


async def test_french_errors():
    with pytest.raises(InvalidInput, match="query doit contenir au moins un mot"):
        await client.search_tables("  ", lang="fr")
    with pytest.raises(InvalidInput, match="n'est ni un identifiant de tableau"):
        await client.get_table("Pas un slug!", lang="fr")
