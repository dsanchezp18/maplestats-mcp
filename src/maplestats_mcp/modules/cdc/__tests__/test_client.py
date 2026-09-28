"""Tests for the CDC client against real payloads saved 2026-09-26.

The HTML fixtures are the <main> element of the live pages (support
prices node 720 in both languages, milk classes node 717 in both
languages, the total quota index node 653 and the 2017, 2018, 2019,
2023 and 2026 year pages); pricing_history_2026.csv is the live file
unchanged; market_sample.csv is 26 real rows of CDC_CCL.csv with its
header and byte order mark.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from maplestats_mcp.modules.cdc import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent


def _text(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def _bytes(name: str) -> bytes:
    return (_HERE / name).read_bytes()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch):
    def set_today(value: date) -> None:
        monkeypatch.setattr(client, "_today", lambda: value)

    set_today(date(2026, 9, 26))
    return set_today


def _csv_url(year: int) -> str:
    return constants.COMPONENT_PRICES_URL.format(year=year)


_NOT_FOUND_PAGE = b"<!DOCTYPE html><html><body>Page not found</body></html>"


# --- helpers ---------------------------------------------------------------


def test_class_codes_normalize_both_ways():
    assert client.normalize_class("Class 3(d)") == "3D"
    assert client.normalize_class(" 5 (a) ") == "5A"
    assert client.normalize_class("1(a) 1") == "1A1"
    assert client.normalize_class("Classe 5B/C/D") == "5B/C/D"
    assert client.class_label("4M") == "4(m)"


def test_month_names_english_french_and_abbreviations():
    assert client.month_number("Sept.") == 9
    assert client.month_number("Mars") == 3  # on the English 2019 quota page
    assert client.month_number("févr.") == 2
    assert client.month_number("juin") == 6 and client.month_number("juillet") == 7
    assert client.month_number("Caption") is None


# --- component prices ------------------------------------------------------


def test_component_rows_are_sorted_and_zeros_become_none():
    raw = [
        {
            "Milk Class": "4A",
            "Effective Date": "2026-09-01 00:00:00",
            "Butterfat($/kg)": "11.6418",
            "Proteins($/kg)": "0",
            "Other solids($/kg)": "0",
        },
        {
            "Milk Class": "4M",
            "Effective Date": "2025-02-01 00:00:00",
            "Butterfat($/kg)": "",
            "Proteins($/kg)": "3.3503",
            "Other solids($/kg)": "3.3503",
        },
    ]
    rows = client.parse_component_rows(raw)
    assert [r.effective_date for r in rows] == [date(2025, 2, 1), date(2026, 9, 1)]
    assert rows[0].milk_class == "4(m)" and rows[0].butterfat_per_kg is None
    assert rows[1].protein_per_kg is None and rows[1].butterfat_per_kg == 11.6418


def test_component_rows_accept_french_price_headers():
    # The live 2026 file briefly had these mixed headers (2026-09-28).
    raw = [
        {
            "Classe de lait": "5C",
            "Effective Date": "2026-01-01 00:00:00",
            "M.G.($/kg)": "6.8538",
            "Protéine($/kg)": "2.4098",
            "Autres solides($/kg)": "2.4098",
        }
    ]
    rows = client.parse_component_rows(raw)
    assert rows[0].butterfat_per_kg == 6.8538 and rows[0].protein_per_kg == 2.4098


def test_component_columns_changed_is_an_upstream_error():
    with pytest.raises(UpstreamError):
        client.parse_component_rows([{"Class": "5A", "Date": "2026-01-01"}])


async def test_component_prices_default_to_the_current_year(httpx_mock, today):
    httpx_mock.add_response(
        url=_csv_url(2026),
        content=_bytes("pricing_history_2026.csv"),
        headers={"content-type": "text/csv"},
    )
    result = await client.get_component_prices()
    assert (result.year_from, result.year_to) == (2026, 2026)
    assert result.row_count == 66
    october = [r for r in result.rows if r.effective_date == date(2026, 10, 1)]
    five_a = next(r for r in october if r.milk_class_code == "5A")
    # Matches the live "Component Pricing" page for October 2026.
    assert (five_a.butterfat_per_kg, five_a.protein_per_kg, five_a.other_solids_per_kg) == (
        4.6287,
        8.6652,
        1.2415,
    )
    # Not yet announced: December has only the fixed 3(d) and 4(a) butterfat.
    december = [r for r in result.rows if r.effective_date == date(2026, 12, 1)]
    assert {r.milk_class_code for r in december} == {"3D", "4A", "4M"}
    four_m = next(r for r in december if r.milk_class_code == "4M")
    assert (four_m.butterfat_per_kg, four_m.protein_per_kg) == (None, None)
    assert result.provenance.url == _csv_url(2026)


async def test_component_prices_filter_one_class(httpx_mock, today):
    httpx_mock.add_response(url=_csv_url(2026), content=_bytes("pricing_history_2026.csv"))
    result = await client.get_component_prices(2026, 2026, milk_class="3(d)")
    assert result.milk_class == "3(d)" and result.row_count == 12
    assert all(r.protein_per_kg == 10.1476 for r in result.rows[1:])


async def test_component_prices_in_january_fall_back_to_last_year(httpx_mock, today):
    today(date(2027, 1, 3))
    httpx_mock.add_response(url=_csv_url(2027), status_code=404, content=_NOT_FOUND_PAGE)
    httpx_mock.add_response(url=_csv_url(2026), content=_bytes("pricing_history_2026.csv"))
    result = await client.get_component_prices(lang="fr")
    assert (result.year_from, result.year_to) == (2026, 2026)
    assert "Pas encore de fichier pour 2027." in result.notes


async def test_component_prices_skip_a_next_year_without_a_file(httpx_mock, today):
    httpx_mock.add_response(url=_csv_url(2026), content=_bytes("pricing_history_2026.csv"))
    httpx_mock.add_response(url=_csv_url(2027), status_code=404, content=_NOT_FOUND_PAGE)
    result = await client.get_component_prices(2026, 2027)
    assert result.year_to == 2026 and "No 2027 file yet." in result.notes


async def test_component_prices_missing_past_year_is_not_found(httpx_mock, today):
    httpx_mock.add_response(url=_csv_url(2010), status_code=404, content=_NOT_FOUND_PAGE)
    with pytest.raises(NotFound):
        await client.get_component_prices(2010, 2010)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"year_from": 2001}, "2002"),
        ({"year_from": 2026, "year_to": 2025}, "after"),
        ({"year_to": 2030}, "2026"),
        ({"milk_class": "2(a)"}, "milk_class"),
    ],
)
async def test_component_prices_reject_bad_arguments(today, kwargs, message):
    with pytest.raises(InvalidInput, match=message):
        await client.get_component_prices(**kwargs)


# --- butter support price --------------------------------------------------


def test_support_prices_labels_and_dates():
    rows = client.parse_support_prices(_text("support_en.html"))
    assert len(rows) == 18
    assert rows[0].effective_label == "2026" and rows[0].effective_date == date(2026, 2, 1)
    assert rows[0].butter_per_kg == 10.5662
    by_label = {r.effective_label: r for r in rows}
    assert by_label["2024 (May)"].effective_date == date(2024, 5, 1)
    assert by_label["2022 (Sept.)"].effective_date == date(2022, 9, 1)
    assert by_label["2010"].butter_per_kg == 7.1024


def test_french_support_page_decimal_commas_give_the_same_numbers():
    english = client.parse_support_prices(_text("support_en.html"))
    french = client.parse_support_prices(_text("support_fr.html"))
    assert [r.butter_per_kg for r in french] == [r.butter_per_kg for r in english]
    assert french[3].effective_label == "2023 (fév.)"
    assert french[3].effective_date == date(2023, 2, 1)


async def test_support_prices_read_the_english_page_in_both_languages(httpx_mock):
    httpx_mock.add_response(url=constants.SUPPORT_PRICES_PAGE["en"], text=_text("support_en.html"))
    httpx_mock.add_response(url=constants.SUPPORT_PRICES_PAGE["fr"], text=_text("support_fr.html"))
    result = await client.get_butter_support_prices(lang="fr")
    assert result.source_page == constants.SUPPORT_PRICES_PAGE["fr"]
    assert result.provenance.url == constants.SUPPORT_PRICES_PAGE["en"]
    assert result.notes[0].startswith("La CCL")
    # Labels come from the French page; values and dates stay the English ones.
    by_date = {r.effective_date: r for r in result.rows}
    assert by_date[date(2024, 5, 1)].effective_label == "2024 (mai)"
    assert by_date[date(2023, 2, 1)].effective_label == "2023 (fév.)"
    assert by_date[date(2023, 2, 1)].butter_per_kg == 10.218
    english = await client.get_butter_support_prices()  # both pages cached
    assert english.rows[2].effective_label == "2024 (May)"


async def test_support_prices_keep_english_labels_when_french_rows_differ(httpx_mock):
    httpx_mock.add_response(url=constants.SUPPORT_PRICES_PAGE["en"], text=_text("support_en.html"))
    shifted = _text("support_fr.html").replace("10, 5662", "10, 9999", 1)
    httpx_mock.add_response(url=constants.SUPPORT_PRICES_PAGE["fr"], text=shifted)
    result = await client.get_butter_support_prices(lang="fr")
    assert result.rows[2].effective_label == "2024 (May)"
    assert result.rows[0].butter_per_kg == 10.5662


# --- national quota --------------------------------------------------------

_QUOTA_PAGES = {
    2017: "https://cdc-ccl.ca/en/node/667",
    2018: "https://cdc-ccl.ca/en/node/668",
    2019: "https://cdc-ccl.ca/en/node/669",
    2023: "https://cdc-ccl.ca/en/2023-national-milk-production-target",
    2026: "https://cdc-ccl.ca/en/2026-national-milk-production-target",
}


def test_quota_index_lists_every_year():
    years = client.parse_quota_index(
        _text("quota_index_en.html"), constants.NATIONAL_QUOTA_INDEX["en"]
    )
    assert sorted(years) == list(range(2017, 2027))
    for year, url in _QUOTA_PAGES.items():
        assert years[year] == url


def test_quota_page_layouts():
    y2026 = client.parse_quota_page(_text("quota_2026.html"), 2026)
    # Months after July are still blank on the page and are left out.
    assert [r.period for r in y2026][-1] == "2026-07" and len(y2026) == 7
    assert y2026[0].total_quota_kg_butterfat == 34_391_869

    y2023 = {r.period: r for r in client.parse_quota_page(_text("quota_2023.html"), 2023)}
    assert y2023["2023-03"].total_quota_kg_butterfat is None
    assert y2023["2023-03"].published_value == "34,889,4085"
    assert y2023["2023-04"].total_quota_kg_butterfat == 32_255_543

    y2019 = {r.period: r for r in client.parse_quota_page(_text("quota_2019.html"), 2019)}
    assert len(y2019) == 12 and y2019["2019-03"].total_quota_kg_butterfat == 32_576_696

    y2018 = {r.period: r for r in client.parse_quota_page(_text("quota_2018.html"), 2018)}
    assert len(y2018) == 11 and "2018-12" not in y2018
    assert y2018["2018-07"].change_from_year_ago_pct == -0.10
    assert y2018["2018-08"].change_from_year_ago_pct is None

    y2017 = client.parse_quota_page(_text("quota_2017.html"), 2017)
    assert y2017[-1].period == "2017-12" and y2017[-1].change_from_year_ago_pct == 4.67


async def test_national_quota_range_with_notes(httpx_mock):
    httpx_mock.add_response(
        url=constants.NATIONAL_QUOTA_INDEX["en"], text=_text("quota_index_en.html")
    )
    for year in (2017, 2018, 2019):
        httpx_mock.add_response(url=_QUOTA_PAGES[year], text=_text(f"quota_{year}.html"))
    result = await client.get_national_quota(2017, 2019)
    assert result.row_count == 35
    assert [r.period for r in result.rows][:2] == ["2017-01", "2017-02"]
    assert any("2018-12" in note for note in result.notes)
    assert any("before August 2018" in note for note in result.notes)
    assert result.provenance.url == constants.NATIONAL_QUOTA_INDEX["en"]


async def test_national_quota_defaults_to_latest_year_and_flags_bad_figures(httpx_mock):
    httpx_mock.add_response(
        url=constants.NATIONAL_QUOTA_INDEX["en"], text=_text("quota_index_en.html")
    )
    httpx_mock.add_response(url=_QUOTA_PAGES[2026], text=_text("quota_2026.html"))
    latest = await client.get_national_quota()
    assert (latest.year_from, latest.row_count) == (2026, 7)
    assert len(latest.notes) == 1  # a partial latest year is not a gap

    httpx_mock.add_response(url=_QUOTA_PAGES[2023], text=_text("quota_2023.html"))
    # The French index links each year's French page (checked live 2026-09-26).
    french_2023 = (
        "https://cdc-ccl.ca/fr/cible-nationale-production-laitiere-au-canada-pour-annee-2023"
    )
    httpx_mock.add_response(
        url=constants.NATIONAL_QUOTA_INDEX["fr"],
        text=f'<main><a href="{french_2023[len("https://cdc-ccl.ca") :]}">2023</a></main>',
    )
    y2023 = await client.get_national_quota(2023, 2023, lang="fr")
    assert any("2023-03" in note for note in y2023.notes)
    assert y2023.source_pages == [french_2023] and y2023.provenance.url == french_2023
    assert y2023.rows[3].total_quota_kg_butterfat == 32_255_543


async def test_national_quota_years_not_published(httpx_mock):
    httpx_mock.add_response(
        url=constants.NATIONAL_QUOTA_INDEX["en"], text=_text("quota_index_en.html")
    )
    with pytest.raises(NotFound, match="2017-2026"):
        await client.get_national_quota(2015, 2017)


# --- milk classes ----------------------------------------------------------


def test_milk_classes_handle_rowspan_and_footnotes():
    classes = client.parse_milk_classes(_text("classes_en.html"))
    assert len(classes) == 31
    four_a = next(c for c in classes if c.milk_class == "4(a)")
    assert four_a.products[0] == "Butter and butteroil." and len(four_a.products) == 6
    cheddar = next(c for c in classes if c.milk_class == "3(b) 2")
    assert "Footnote" not in " ".join(cheddar.products)
    assert {c.class_group for c in classes} == {"1", "2", "3", "4", "5"}


async def test_milk_classes_french_and_filter(httpx_mock):
    httpx_mock.add_response(url=constants.MILK_CLASSES_PAGE["fr"], text=_text("classes_fr.html"))
    result = await client.get_milk_classes("3c", lang="fr")
    assert result.classes[0].milk_class == "3(c) 1"
    assert result.classes[0].products == ["Féta."] and result.class_count == 6


async def test_milk_classes_unknown_filter(httpx_mock):
    httpx_mock.add_response(url=constants.MILK_CLASSES_PAGE["en"], text=_text("classes_en.html"))
    with pytest.raises(NotFound):
        await client.get_milk_classes("9(z)")


# --- market data -----------------------------------------------------------


def _market(httpx_mock, content: bytes | None = None) -> None:
    httpx_mock.add_response(
        url=constants.MARKET_DATA_URL,
        content=content if content is not None else _bytes("market_sample.csv"),
        headers={"content-type": "text/csv"},
    )


async def test_market_production_by_province(httpx_mock):
    _market(httpx_mock)
    result = await client.query_market_data("production", province="on")
    assert result.total_matched == 3
    assert [r.period_end for r in result.rows] == [
        date(2026, 7, 31),
        date(2026, 6, 30),
        date(2026, 5, 31),
    ]
    assert result.rows[0].value == 274_871_871 and result.rows[0].unit == "L"
    assert result.latest_date == date(2026, 7, 31)


async def test_market_sales_class_segment_and_dates(httpx_mock):
    _market(httpx_mock)
    result = await client.query_market_data(
        "sales_p10", milk_class="4(a)", segment="butterfat_revenue", date_from="2026-07"
    )
    assert result.total_matched == 1
    row = result.rows[0]
    assert (row.milk_class, row.milk_subclass, row.unit) == ("Class 4", "Class 4A", "$")
    assert row.value == 43_629_900.27


async def test_market_class_prefix_and_limit(httpx_mock):
    _market(httpx_mock)
    result = await client.query_market_data("sales_p10", milk_class="3b", limit=1)
    assert result.total_matched == 2 and result.returned_count == 1
    assert result.provenance.limits == "newest 1 rows returned"


async def test_market_regions_in_french(httpx_mock):
    _market(httpx_mock)
    result = await client.query_market_data("sales_by_region", region="Ouest", lang="fr")
    assert result.total_matched == 2
    assert {r.region for r in result.rows} == {"Ouest"}
    assert {r.milk_subclass for r in result.rows} == {"Classe 1A", "Classe 3B/C"}
    assert result.rows[0].segment == "Revenu de matière grasse ($)"
    assert result.notes[0].startswith("P10")
    assert result.dictionary_url.endswith("CCLDictionnaireFr.html")


async def test_market_farms(httpx_mock):
    _market(httpx_mock)
    result = await client.query_market_data("farms", province="QC")
    assert [r.value for r in result.rows] == [4134.0, 4250.0]
    assert result.rows[0].unit == "count" and result.rows[0].period_end == date(2025, 8, 1)


async def test_market_dataset_renamed_upstream(httpx_mock):
    sample = _bytes("market_sample.csv").decode("utf-8-sig")
    header, *lines = sample.splitlines()
    only_production = "\n".join([header, *[line for line in lines if "Total Production" in line]])
    _market(httpx_mock, only_production.encode("utf-8"))
    with pytest.raises(UpstreamError, match="farms"):
        await client.query_market_data("farms")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"province": "XX"}, "province"),
        ({"region": "North"}, "region"),
        ({"date_from": "July 2026"}, "YYYY"),
        ({"limit": 0}, "limit"),
    ],
)
async def test_market_rejects_bad_arguments(kwargs, message):
    # Arguments are checked before the 4 MB file is downloaded.
    with pytest.raises(InvalidInput, match=message):
        await client.query_market_data("production", **kwargs)


def test_catalogue_is_bilingual():
    english = client.catalogue("en")
    french = client.catalogue("fr")
    assert [d.tool for d in english.datasets] == [d.tool for d in french.datasets]
    assert all(d.tool.startswith("cdc_") for d in english.datasets)
    egg = next(r for r in french.related_sources if r.name == "Producteurs d'œufs du Canada")
    assert egg.status == "blocked_terms" and "permission" in egg.detail
    assert egg.alternative and egg.alternative.startswith("tableaux wds_")
    assert [r.url for r in english.related_sources][:8] == [r.url for r in french.related_sources][
        :8
    ]
    assert "Egg Farmers of Canada" in {r.name for r in english.related_sources}
    assert "Dairy Farmers of Ontario" in {r.name for r in french.related_sources}
    with pytest.raises(InvalidInput):
        client.catalogue("es")
