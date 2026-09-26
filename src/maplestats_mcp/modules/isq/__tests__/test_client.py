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
