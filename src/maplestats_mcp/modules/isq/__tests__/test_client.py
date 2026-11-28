"""Tests on responses trimmed from statistique.quebec.ca (2026-09-26)."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from maplestats_mcp.modules.isq import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

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


def test_zero_padded_codes_stay_text_but_plain_numbers_parse():
    assert client.parse_value("01") == "01"
    assert client.parse_value("007") == "007"
    assert client.parse_value("-01") == "-01"
    assert client.parse_value("01,5") == "01,5"
    # A lone zero and a decimal below one are quantities.
    assert client.parse_value("0") == 0 and isinstance(client.parse_value("0"), int)
    assert client.parse_value("0,5") == 0.5
    assert client.parse_value("-0,5") == -0.5
    assert client.parse_value("10") == 10
    assert client.parse_value("1 015,1") == 1015.1


def test_code_column_is_text_throughout_when_some_codes_are_zero_padded():
    # Codes 01 to 09 then 10: parsed cell by cell they were "01" but 10, a
    # column of mixed types. Only label and code columns are held as text.
    body = 'co_tertr;an_2024\n"09";"5"\n"10";"0,5"\n"11";"0"\n'
    tree = [
        {"title": "Code", "field": "co_tertr"},
        {"title": "2024", "type": "data", "field": "an_2024"},
    ]
    rows, _ = client.parse_rows(body, client.columns_from_tree(tree))
    assert [r["Code"] for r in rows] == ["09", "10", "11"]
    # The value column is untouched, 0 and 0,5 included.
    assert [r["2024"] for r in rows] == [5, 0.5, 0]


def test_zero_padded_values_in_a_data_column_are_still_numbers():
    # Only label and code columns are held as text: a value column always parses
    # numbers, so "05" then 10 is 5 then 10, not a string and an int.
    body = 'c;v\n"1";"05"\n"2";"10"\n'
    tree = [{"title": "C", "field": "c"}, {"title": "V", "type": "data", "field": "v"}]
    rows, _ = client.parse_rows(body, client.columns_from_tree(tree))
    assert [r["V"] for r in rows] == [5, 10]
    assert [r["C"] for r in rows] == [1, 2]


def test_numeric_label_column_without_padding_still_parses():
    body = 'annee;an_2024\n"2023";"5"\n"2024";"6"\n'
    tree = [{"title": "Année", "field": "annee"}, {"type": "data", "field": "an_2024"}]
    rows, _ = client.parse_rows(body, client.columns_from_tree(tree))
    assert [r["Année"] for r in rows] == [2023, 2024]


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
    # The published code is "01": read as a number it came back as 1.
    assert [r["Code"] for r in table.rows] == ["01", "01"]
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


# The engine answers a failure of p_retrn_data with HTTP 200 and no rows, or a
# web page. Neither is a table, and neither may stay in the cache for 6 hours.


def _mock_dynamic_start(httpx_mock, rows_body: str, *, page: bool = True, lang: str = "en") -> None:
    if page:
        httpx_mock.add_response(
            url=f"{constants.SITE}/{lang}{constants.TABLE_PATH}4074",
            text=_page({"type": "dynamique", "no": 4074, "nom": "Verres d'eau", "sujets": []}),
        )
    httpx_mock.add_response(url=_ken("p_retrn_header"), json=_HEADER)
    httpx_mock.add_response(url=_ken("p_retrn_titre"), text="Nombre de verres d'eau")
    httpx_mock.add_response(url=_ken("p_retrn_data"), text=rows_body)


@pytest.mark.parametrize(
    "bad_body",
    [
        "",
        " \r\n",
        "<!DOCTYPE html>\n<html><body>Service indisponible</body></html>\n",
        "<html>\n<body>Erreur</body>\n</html>",
        # Delimited, but not this table's rows.
        'message;code\n"erreur";"500"\n',
    ],
)
async def test_bad_rows_body_is_refused_and_not_cached(httpx_mock, bad_body):
    _mock_dynamic_start(httpx_mock, bad_body)
    with pytest.raises(UpstreamError, match="did not return the table's rows"):
        await client.get_table("4074")
    # The source recovers: the same table must be read again, not served from
    # the cache the bad answer would have been stored in.
    _mock_dynamic_start(httpx_mock, _DATA, page=False)
    httpx_mock.add_response(url=_ken("p_retrn_note_html"), text="<p>Source : ISQ.</p>")
    httpx_mock.add_response(url=_ken("p_retrn_signe"), text='"signe";"desc";"type"\n')
    table = await client.get_table("4074")
    assert table.total_rows == 2
    assert table.rows[0]["Moins de 1 verre / (%)"] == 1015.5


async def test_bad_rows_body_error_is_french_with_lang_fr(httpx_mock):
    _mock_dynamic_start(httpx_mock, "<html></html>", lang="fr")
    with pytest.raises(UpstreamError, match="n'a pas renvoyé les lignes du tableau"):
        await client.get_table("4074", lang="fr")


async def test_a_table_with_a_header_and_no_rows_is_still_a_table(httpx_mock):
    header_only = "de_group;de_coln;tri_coln;perc_1;perc_1_sign;ic_1\n"
    _mock_dynamic_start(httpx_mock, header_only)
    httpx_mock.add_response(url=_ken("p_retrn_note_html"), text="")
    httpx_mock.add_response(url=_ken("p_retrn_signe"), text='"signe";"desc";"type"\n')
    table = await client.get_table("4074")
    assert table.rows == [] and table.total_rows == 0


# Plurals. shared/search.py keeps French words ending in -is or -us whole
# ("revenus", "emplois"), while a slug has the title's own form.


@pytest.mark.parametrize(
    "query",
    [
        "revenus disponibles",
        "revenu disponible",
        "revenus disponible",
        "revenu disponibles",
        "Revenus Disponibles MRC",
    ],
)
async def test_search_meets_singular_and_plural_forms_of_a_slug(httpx_mock, query):
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=_SITEMAP)
    result = await client.search_tables(query, lang="all")
    assert [t.table for t in result.tables] == [
        "revenu-disponible-par-habitant-mrc-et-ensemble-du-quebec"
    ]


async def test_search_plural_slug_words_meet_a_singular_query(httpx_mock):
    sitemap = (
        f"<urlset><url><loc>{constants.SITE}/fr{constants.TABLE_PATH}"
        "emplois-vacants-par-region</loc></url></urlset>"
    )
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=sitemap, is_reusable=True)
    for query in ("emploi vacant", "emplois vacants"):
        assert (await client.search_tables(query, lang="all")).total_matched == 1


async def test_search_plural_rule_does_not_make_unrelated_words_meet(httpx_mock):
    sitemap = (
        f"<urlset><url><loc>{constants.SITE}/fr{constants.TABLE_PATH}"
        "prix-des-logements</loc></url></urlset>"
    )
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=sitemap)
    assert (await client.search_tables("pris", lang="all")).total_matched == 0


# shared/search.py folds "-eaux" to "-eal" ("niveaux" -> "niveal") but leaves the
# singular "niveau" whole, so the two never met; and a final "x" is a plural only
# after eu, au or ou ("index" and "prix" are not plurals).
_NIVEAUX_SLUGS = (
    "niveaux-de-vie-par-region",
    "niveau-de-scolarite-par-region",
    "reseaux-routiers-du-quebec",
    "bureau-de-poste-par-region",
    "consumer-price-index-quebec",
)


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("niveau de vie", "niveaux-de-vie-par-region"),
        ("niveaux de vie", "niveaux-de-vie-par-region"),
        ("niveaux scolarite", "niveau-de-scolarite-par-region"),
        ("niveau scolarite", "niveau-de-scolarite-par-region"),
        ("reseau routier", "reseaux-routiers-du-quebec"),
        ("réseaux routiers", "reseaux-routiers-du-quebec"),
        ("bureaux de poste", "bureau-de-poste-par-region"),
        ("consumer price index", "consumer-price-index-quebec"),
    ],
)
async def test_search_meets_eau_and_eaux(httpx_mock, query, slug):
    sitemap = "<urlset>" + "".join(
        f"<url><loc>{constants.SITE}/fr{constants.TABLE_PATH}{name}</loc></url>"
        for name in _NIVEAUX_SLUGS
    )
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=sitemap + "</urlset>")
    result = await client.search_tables(query, lang="all")
    assert [t.table for t in result.tables] == [slug]


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("inde", "consumer-price-index-quebec"),
        ("pri", "prix-des-logements"),
        ("prix", "pris-moyens-par-region"),
        ("pris", "prix-des-logements"),
    ],
)
async def test_search_does_not_strip_x_from_words_that_are_not_plurals(httpx_mock, query, slug):
    sitemap = (
        f"<urlset><url><loc>{constants.SITE}/en{constants.TABLE_PATH}{slug}</loc></url></urlset>"
    )
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=sitemap)
    assert (await client.search_tables(query, lang="all")).total_matched == 0


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


# The table argument may be a page URL: only the real host is accepted. A
# string-prefix check passed both "statistique.quebec.ca.attacker.example" and
# "statistique.quebec.ca@attacker.example" (whose host is the part after "@").


@pytest.mark.parametrize(
    "url",
    [
        "https://statistique.quebec.ca.attacker.example/produit/tableau/x",
        "https://statistique.quebec.ca@attacker.example/produit/tableau/x",
        "https://attacker.example/produit/tableau/x?https://statistique.quebec.ca",
        "https://attacker.example\\@statistique.quebec.ca/produit/tableau/x",
        "http://statistique.quebec.ca/produit/tableau/x",
        "https://statistique.quebec.ca:8443/produit/tableau/x",
        "https://statistique.quebec.ca/fr/document/autre",
        "https://statistique.quebec.ca/?next=/produit/tableau/x",
    ],
)
async def test_table_url_must_be_the_real_host(url):
    with pytest.raises(InvalidInput, match="statistique.quebec.ca table page"):
        await client.get_table(url)
    with pytest.raises(InvalidInput, match="doit être une page de tableau"):
        await client.get_table(url, lang="fr")


async def test_table_url_off_site_sends_no_request(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.get_table("https://statistique.quebec.ca@attacker.example/produit/tableau/x")
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize(
    "url",
    [
        f"{constants.SITE}/fr{constants.TABLE_PATH}4074",
        f"{constants.SITE}/en{constants.TABLE_PATH}some-table-slug",
        f"https://STATISTIQUE.QUEBEC.CA:443/fr{constants.TABLE_PATH}4074",
    ],
)
def test_real_table_url_is_accepted(url):
    assert client._page_url(url, "en") == url


# A body is read only up to the cap: the first one declares no Content-Length
# and never ends, so a reader that buffers the whole response would not return.


class _EndlessBody(httpx.AsyncByteStream):
    def __init__(self, chunk: int = 1024) -> None:
        self.chunk = chunk
        self.sent = 0

    async def __aiter__(self):
        while True:
            self.sent += self.chunk
            yield b"x" * self.chunk


async def test_body_over_the_cap_stops_the_read(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "MAX_BYTES", 10_000)
    body = _EndlessBody()
    httpx_mock.add_response(url=constants.SITEMAP_URL, stream=body)
    with pytest.raises(UpstreamError, match="larger than 10,000 bytes"):
        await client.search_tables("movie")
    assert body.sent < 10_000 + 4 * body.chunk


async def test_declared_size_over_the_cap_is_refused_unread(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "MAX_BYTES", 10_000)
    httpx_mock.add_response(url=constants.SITEMAP_URL, content=b"x" * 20_000)
    with pytest.raises(UpstreamError, match="is 20,000 bytes"):
        await client.search_tables("movie")


async def test_off_site_redirect_is_refused(httpx_mock):
    httpx_mock.add_response(
        url=constants.SITEMAP_URL,
        status_code=302,
        headers={"location": "https://attacker.example/sitemap.xml"},
    )
    with pytest.raises(UpstreamError, match="attacker.example"):
        await client.search_tables("movie")
    assert len(httpx_mock.get_requests()) == 1
