"""Tests for the CFIA client against pages saved live on 2026-09-26.

Each HTML fixture is the <main> element of the live page (which holds the
"Date modified" footer), with scripts removed. reportable_*, status_* and
the per-disease detection pages are otherwise complete. premises_en.html
and premises_fr.html keep 30 of the 662 infected premises rows: the 12
current ones and 18 released rows chosen for their quirks (listed next to
each test), the same premises in both languages.
"""

from __future__ import annotations

import collections
from datetime import date
from pathlib import Path

import pytest

from maplestats_mcp.modules.cfia import client, constants, tools
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable

_HERE = Path(__file__).parent

_DETECTION_FIXTURES = {
    "chronic_wasting_disease": ("cwd_en.html", "cwd_fr.html"),
    "scrapie": ("scrapie_en.html", "scrapie_fr.html"),
    "bovine_tuberculosis": ("btb_en.html", "btb_fr.html"),
    "cysticercosis": ("cysticercosis_en.html", None),
    "bovine_spongiform_encephalopathy": ("bse_en.html", None),
    "trichinellosis": ("trichinellosis_en.html", None),
    "avian_influenza": ("ai_en.html", "ai_fr.html"),
}


def _text(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _mock(httpx_mock, url: str, name: str | None = None, text: str | None = None) -> None:
    httpx_mock.add_response(
        url=url,
        text=text if text is not None else _text(name or ""),
        headers={"content-type": "text/html; charset=UTF-8"},
    )


def _mock_premises(httpx_mock, lang: str = "en") -> None:
    _mock(httpx_mock, constants.HPAI_PREMISES_PAGE["en"], "premises_en.html")
    if lang == "fr":
        _mock(httpx_mock, constants.HPAI_PREMISES_PAGE["fr"], "premises_fr.html")
    _mock(httpx_mock, constants.HPAI_STATUS_PAGE[lang], f"status_{lang}.html")


# --- helpers ---------------------------------------------------------------


def test_disease_names_fold_case_accents_and_apostrophes():
    assert client.match_diseases("CWD") == {"chronic_wasting_disease"}
    assert client.match_diseases("Maladie debilitante chronique") == {"chronic_wasting_disease"}
    assert client.match_diseases("MALADIE DÉBILITANTE CHRONIQUE") == {"chronic_wasting_disease"}
    assert client._fold("Type d’animal infecté") == "type d'animal infecte"
    assert client.match_diseases("Influenza aviaire à déclaration obligatoire") == {
        "avian_influenza"
    }
    assert client.match_diseases("grippe aviaire") == {"avian_influenza"}
    assert client.match_diseases("anémie infectieuse des équidés") == {"equine_infectious_anemia"}
    assert client.match_diseases("bovine") == {
        "bovine_spongiform_encephalopathy",
        "bovine_tuberculosis",
        "cysticercosis",
    }
    assert client.match_diseases("xx") == set()


def test_page_disease_name_variants_share_one_key():
    # Spellings seen on the pages across years and languages.
    assert client.disease_key("Notifiable avian influenza") == "avian_influenza"
    assert client.disease_key("Avian Influenza") == "avian_influenza"
    assert client.disease_key("Influenza aviaire à déclaration obligatoire") == "avian_influenza"
    assert client.disease_key("Tremblante du mouton") == "scrapie"
    assert client.disease_key("Tremblante") == "scrapie"
    assert client.disease_key("Bovine Spongiform Encephalopathy") == (
        "bovine_spongiform_encephalopathy"
    )
    # A disease the CFIA adds later keeps its own key instead of vanishing.
    assert client.disease_key("African swine fever") == "african_swine_fever"


def test_numbers_dates_and_provinces_as_published():
    assert client.parse_int("2,552,000") == 2_552_000
    assert client.parse_int("2\xa0552\xa0000") == 2_552_000
    assert client.parse_int("`0") == 0  # French status page, 2026-09-26
    assert client.parse_int("Under 100") is None
    assert client.parse_day_month("July 6", 2016) == date(2016, 7, 6)
    assert client.parse_day_month("6 Juillet", 2016) == date(2016, 7, 6)
    assert client.parse_day_month("1er juin", 2022) == date(2022, 6, 1)
    assert client.parse_day_month("21 huin", 2019) is None  # French scrapie page typo
    assert client.parse_long_date("September 26, 2026") == date(2026, 9, 26)
    assert client.province_code("Île-Prince-Édouard") == "PE"
    assert client.province_code("ile-du-prince-edouard") == "PE"
    assert client.province_code("sk") == "SK"
    assert client.province_codes_in("Alberta and Saskatchewan") == ["AB", "SK"]
    assert client.province_codes_in("Alberta et Saskatchewan") == ["AB", "SK"]
    assert client.parse_period("2024-02", end=True, lang="en") == date(2024, 2, 29)
    with pytest.raises(InvalidInput):
        client.parse_period("Feb 2024", end=False, lang="en")


def test_every_tool_docstring_is_discoverable_in_both_languages():
    for fn in (tools.cfia_reportable_diseases, tools.cfia_disease_detections):
        doc = fn.__doc__ or ""
        assert "Use for:" in doc and "Keywords:" in doc and "Mots-clés :" in doc
        keywords = doc.split("Keywords:")[1].split("Mots-clés :")[0].split(",")
        mots = doc.split("Mots-clés :")[1].split(",")
        assert len(keywords) >= 8 and len(mots) >= 8
    doc = tools.cfia_avian_influenza.__doc__ or ""
    assert "grippe aviaire" in doc and "IAHP" in doc


# --- federally reportable diseases (yearly totals) ---------------------------


async def test_reportable_diseases_parse_every_year(httpx_mock):
    _mock(httpx_mock, constants.REPORTABLE_PAGE["en"], "reportable_en.html")
    result = await client.get_reportable_diseases()
    assert result.years_available == list(range(2011, 2027))
    assert result.row_count == 69
    assert result.current_as_of == date(2026, 8, 31)
    assert result.provenance.as_of is not None
    assert result.provenance.as_of.date() == date(2026, 9, 10)
    latest = {(r.disease_key, r.count) for r in result.rows if r.year == 2026}
    # "Current as of: 2026-08-31" on the live page.
    assert latest == {
        ("avian_influenza", 19),
        ("chronic_wasting_disease", 7),
        ("equine_infectious_anemia", 7),
    }
    anaplasmosis = next(r for r in result.rows if r.disease_key == "anaplasmosis")
    assert anaplasmosis.disease == "Anaplasmosis"  # table note marker stripped
    assert anaplasmosis.note and "April 1, 2014" in anaplasmosis.note
    ai_2016 = next(r for r in result.rows if r.year == 2016 and r.disease_key == "avian_influenza")
    assert ai_2016.disease == "Notifiable avian influenza"
    assert ai_2016.detections_tool == "cfia_disease_detections"
    ai_2022 = next(r for r in result.rows if r.year == 2022 and r.disease_key == "avian_influenza")
    assert (ai_2022.count, ai_2022.detections_tool) == (279, "cfia_avian_influenza")
    eia = next(r for r in result.rows if r.disease_key == "equine_infectious_anemia")
    assert eia.detections_tool is None


async def test_french_page_has_the_same_counts_under_french_names(httpx_mock):
    _mock(httpx_mock, constants.REPORTABLE_PAGE["en"], "reportable_en.html")
    _mock(httpx_mock, constants.REPORTABLE_PAGE["fr"], "reportable_fr.html")
    english = await client.get_reportable_diseases()
    french = await client.get_reportable_diseases(lang="fr")
    # The French tables list diseases in another order and spell scrapie
    # two ways; keyed rows still line up one for one.
    assert {(r.year, r.disease_key): r.count for r in french.rows} == {
        (r.year, r.disease_key): r.count for r in english.rows
    }
    names = {r.disease for r in french.rows}
    assert {"Maladie débilitante chronique", "Tremblante", "Tremblante du mouton"} <= names
    assert french.current_as_of == date(2026, 8, 31)
    assert french.source_page.endswith("/declaration-obligatoire/au-canada")
    assert french.notes[0].startswith("Les chiffres")


async def test_reportable_filter_and_totals(httpx_mock):
    _mock(httpx_mock, constants.REPORTABLE_PAGE["fr"], "reportable_fr.html")
    scrapie = await client.get_reportable_diseases(
        disease="tremblante", totals_by="disease", lang="fr"
    )
    assert scrapie.diseases == ["scrapie"]
    assert scrapie.totals is not None
    assert [(t.key, t.label, t.total, t.rows) for t in scrapie.totals] == [
        ("scrapie", "Tremblante", 48, 9)
    ]
    cwd = await client.get_reportable_diseases(2022, 2026, "cwd", totals_by="year", lang="fr")
    assert cwd.totals is not None
    assert [(t.key, t.total) for t in cwd.totals] == [
        ("2026", 7),
        ("2025", 9),
        ("2024", 6),
        ("2023", 8),
        ("2022", 6),
    ]


async def test_reportable_rejects_bad_arguments(httpx_mock):
    _mock(httpx_mock, constants.REPORTABLE_PAGE["en"], "reportable_en.html")
    with pytest.raises(InvalidInput):
        await client.get_reportable_diseases(2015, 2012)
    with pytest.raises(InvalidInput, match="2011-2026"):
        await client.get_reportable_diseases(2005, 2008)
    with pytest.raises(InvalidInput, match="unknown disease"):
        await client.get_reportable_diseases(disease="foot and mouth")
    with pytest.raises(InvalidInput):
        await client.get_reportable_diseases(lang="de")


async def test_reportable_layout_change_raises(httpx_mock):
    page = _text("reportable_en.html").replace(">Disease<", ">Illness<", 1)
    _mock(httpx_mock, constants.REPORTABLE_PAGE["en"], text=page)
    with pytest.raises(UpstreamError, match="layout changed"):
        await client.get_reportable_diseases()


async def test_reportable_table_without_year_heading_raises(httpx_mock):
    page = _text("reportable_en.html").replace('<h2 id="a2026">2026</h2>', "<h2>This year</h2>")
    _mock(httpx_mock, constants.REPORTABLE_PAGE["en"], text=page)
    with pytest.raises(UpstreamError, match="year heading"):
        await client.get_reportable_diseases()


async def test_moved_page_is_an_upstream_error(httpx_mock):
    # The site answers 410 Gone for retired URLs (the old yearly pages did).
    httpx_mock.add_response(url=constants.REPORTABLE_PAGE["en"], status_code=410)
    with pytest.raises(UpstreamError, match="moved"):
        await client.get_reportable_diseases()


async def test_server_errors_are_upstream_unavailable(httpx_mock):
    httpx_mock.add_response(url=constants.REPORTABLE_PAGE["en"], status_code=503, is_reusable=True)
    with pytest.raises(UpstreamUnavailable):
        await client.get_reportable_diseases()


# --- per-disease detections --------------------------------------------------


async def test_cwd_detections_count_multi_herd_rows(httpx_mock):
    _mock(httpx_mock, constants.DETECTION_PAGES["chronic_wasting_disease"]["en"], "cwd_en.html")
    result = await client.get_disease_detections("CWD", 2025, 2025, counts_by="month")
    assert result.diseases == ["chronic_wasting_disease"]
    # 7 rows, 9 herds: "Elk (3 herds)" on May 5, as in the yearly table.
    assert (result.row_count, result.herd_count) == (7, 9)
    may = next(r for r in result.rows if r.date_confirmed == date(2025, 5, 5))
    assert (may.animal_type, may.herds, may.province_codes) == ("Elk", 3, ["SK"])
    assert result.counts is not None
    assert result.counts[0].key == "2025-11"
    assert next(c for c in result.counts if c.key == "2025-05").herds == 3
    assert result.last_modified == {"chronic_wasting_disease": date(2026, 9, 10)}
    # The pre-2011 yearly table on the same page is not read as detections.
    assert min(r.year for r in (await client.get_disease_detections("cwd")).rows) == 2011


async def test_detections_add_up_to_the_yearly_totals(httpx_mock):
    _mock(httpx_mock, constants.REPORTABLE_PAGE["en"], "reportable_en.html")
    for key, (english, _) in _DETECTION_FIXTURES.items():
        _mock(httpx_mock, constants.DETECTION_PAGES[key]["en"], english)
    yearly = await client.get_reportable_diseases()
    detections = await client.get_disease_detections()
    assert detections.row_count == 181 and detections.herd_count == 186
    herds = collections.Counter()
    for row in detections.rows:
        herds[(row.disease_key, row.year)] += row.herds
    expected = {
        (r.disease_key, r.year): r.count
        for r in yearly.rows
        if r.disease_key in constants.DETECTION_PAGES
        and not (r.disease_key == "avian_influenza" and r.year >= 2021)
    }
    assert dict(herds) == expected


async def test_french_labels_with_english_dates(httpx_mock):
    for key in ("scrapie", "avian_influenza"):
        english, french = _DETECTION_FIXTURES[key]
        _mock(httpx_mock, constants.DETECTION_PAGES[key]["en"], english)
        _mock(httpx_mock, constants.DETECTION_PAGES[key]["fr"], french)
    scrapie = await client.get_disease_detections("tremblante", 2019, 2019, lang="fr")
    # The French page dates the second 2019 flock "21 huin".
    assert [(r.date_confirmed, r.date_text, r.animal_type) for r in scrapie.rows] == [
        (date(2019, 6, 21), "21 juin", "Mouton"),
        (date(2019, 6, 21), "21 huin", "Mouton"),
    ]
    atypical = await client.get_disease_detections("scrapie", 2012, 2012, lang="fr")
    noted = [r for r in atypical.rows if r.note]
    assert len(noted) == 3 and noted[0].note == "Forme atypique de la tremblante"
    assert noted[0].date_text in {"4 juin", "31 mai", "26 janvier"}
    flu = await client.get_disease_detections("influenza aviaire", 2014, 2014, lang="fr")
    # The French page says "9 décembre" where the English one says December 19.
    first = next(r for r in flu.rows if r.animal_type == "Canards/poulets/oies/dindes")
    assert (first.date_confirmed, first.date_text) == (date(2014, 12, 19), "9 décembre")
    assert first.location == "Colombie-Britannique"
    assert flu.rows[0].disease == "Influenza aviaire"


async def test_french_rows_that_do_not_line_up_keep_english_labels(httpx_mock):
    key = "bovine_tuberculosis"
    _mock(httpx_mock, constants.DETECTION_PAGES[key]["en"], "btb_en.html")
    french = _text("btb_fr.html").replace("<td>2018</td>", "<td>2019</td>", 1)
    _mock(httpx_mock, constants.DETECTION_PAGES[key]["fr"], text=french)
    result = await client.get_disease_detections("tuberculose bovine", lang="fr")
    assert result.rows[0].animal_type == "Dairy Cattle"
    assert any("libellés sont en anglais" in note for note in result.notes)


async def test_detection_filters(httpx_mock):
    key = "bovine_tuberculosis"
    _mock(httpx_mock, constants.DETECTION_PAGES[key]["en"], "btb_en.html")
    _mock(httpx_mock, constants.DETECTION_PAGES[key]["fr"], "btb_fr.html")
    sask = await client.get_disease_detections("bovine tb", province="Saskatchewan")
    # "Alberta and Saskatchewan" (2016) counts for both provinces.
    assert [r.year for r in sask.rows] == [2024, 2023, 2016]
    dairy = await client.get_disease_detections("tb", animal_type="bovins laitiers", lang="fr")
    assert [(r.year, r.animal_type, r.location) for r in dairy.rows] == [
        (2025, "Bovins laitiers", "Manitoba")
    ]


async def test_animal_filter_accepts_either_language(httpx_mock):
    key = "chronic_wasting_disease"
    _mock(httpx_mock, constants.DETECTION_PAGES[key]["en"], "cwd_en.html")
    _mock(httpx_mock, constants.DETECTION_PAGES[key]["fr"], "cwd_fr.html")
    french_term = await client.get_disease_detections("cwd", 2026, 2026, animal_type="wapiti")
    english_term = await client.get_disease_detections("cwd", 2026, 2026, animal_type="elk")
    assert [r.date_confirmed for r in french_term.rows] == [
        r.date_confirmed for r in english_term.rows
    ]
    assert french_term.row_count == 4 and french_term.rows[0].animal_type == "Elk"
    assert not any("anglais" in note for note in french_term.notes)


async def test_bse_rows_carry_the_age(httpx_mock):
    key = "bovine_spongiform_encephalopathy"
    _mock(httpx_mock, constants.DETECTION_PAGES[key]["en"], "bse_en.html")
    result = await client.get_disease_detections("BSE")
    assert result.rows[0].age == "104 months"
    assert result.rows[0].animal_type == "Beef cow (H-type atypical BSE)"


async def test_detections_reject_diseases_without_a_detection_table():
    with pytest.raises(InvalidInput, match="cfia_reportable_diseases"):
        await client.get_disease_detections("equine infectious anemia")
    with pytest.raises(InvalidInput, match="unknown disease"):
        await client.get_disease_detections("rinderpest")
    with pytest.raises(InvalidInput, match="province"):
        await client.get_disease_detections("cwd", province="Atlantis")


async def test_detection_layout_change_raises(httpx_mock):
    page = _text("cwd_en.html").replace("<th>Location</th>", "<th>Region</th>")
    _mock(httpx_mock, constants.DETECTION_PAGES["chronic_wasting_disease"]["en"], text=page)
    with pytest.raises(UpstreamError, match="layout changed"):
        await client.get_disease_detections("cwd")


# --- avian influenza infected premises ---------------------------------------


async def test_current_premises_and_province_counts(httpx_mock):
    _mock_premises(httpx_mock)
    result = await client.get_avian_influenza(status="current")
    assert result.total_matched == 12
    assert [(c.key, c.current, c.released) for c in result.counts] == [
        ("MB", 6, 0),
        ("AB", 3, 0),
        ("SK", 3, 0),
    ]
    newest = result.premises[0]
    assert newest.premises_id == "AB-IP116"
    assert newest.date_detected == date(2026, 9, 26)
    assert newest.location == "County of Vermilion River"
    assert (newest.control_zone, newest.control_zone_order) == ("PCZ-337", "active")
    summary = result.province_summary
    assert summary is not None
    assert (summary.total_current, summary.total_released) == (12, 650)
    assert summary.total_birds_impacted == 17_561_900
    assert summary.birds_as_of == date(2026, 9, 4)
    new_brunswick = next(r for r in summary.rows if r.province_code == "NB")
    assert (new_brunswick.birds_impacted, new_brunswick.birds_impacted_text) == (None, "Under 100")


async def test_premises_row_quirks(httpx_mock):
    _mock_premises(httpx_mock)
    result = await client.get_avian_influenza(limit=1000)
    assert result.total_matched == 30
    by_id = {p.premises_id: p for p in result.premises}
    # The hidden sort digit ("BC-IP<span class=wb-inv>0</span>99") is dropped.
    assert "BC-IP99" in by_id and by_id["BC-IP99"].status == "released"
    # Released marker without <sup>, and with the French label on the English page.
    assert by_id["QC-IP65"].status == "released"
    assert by_id["AB-IP84"].status == "released"
    assert by_id["QC-IP65"].location == "Le Haut-Richelieu Regional County Municipality"
    # Zone and order "N/A".
    assert (by_id["SK-IP67"].control_zone, by_id["SK-IP67"].control_zone_order) == (None, None)
    # Two orders in one cell.
    assert by_id["BC-IP230"].control_zone_order == "revoked"
    assert by_id["BC-IP230"].control_zone_order_text == "Revoked; PCZ-239 Revoked"
    assert by_id["BC-IP239"].control_zone == "PCZ FV4"
    # Low pathogenic premises have no WOAH class.
    lpai = by_id["QC-IP58"]
    assert (lpai.low_pathogenic, lpai.woah_classification) == (True, None)
    assert by_id["NS-IP09"].premises_type == "non_commercial"
    assert by_id["NS-IP09"].premises_type_label == "non-commercial"
    captive = [p for p in result.premises if p.premises_type == "captive_wild"]
    assert len(captive) == 1 and captive[0].woah_classification == "non_poultry"
    newfoundland = by_id["NL-IP02"]
    assert newfoundland.location == "Town of Conception Bay South"
    assert newfoundland.control_zone_order == "released"
    # A trimmed fixture cannot match the province summary; the gap is noted.
    assert any("differ" in note for note in result.notes)


async def test_french_premises_labels_with_english_dates(httpx_mock):
    _mock_premises(httpx_mock, "fr")
    result = await client.get_avian_influenza(limit=1000, lang="fr")
    by_id = {p.premises_id: p for p in result.premises}
    newest = by_id["AB-IP116"]
    # The French page dates it September 25; the English page says 26.
    assert newest.date_detected == date(2026, 9, 26)
    assert newest.location == "le comté de Vermilion River"
    assert (newest.premises_type_label, newest.woah_classification_label) == (
        "commerciale",
        "volailles",
    )
    assert by_id["ON-IP58"].date_detected == date(2025, 2, 21)
    # The French location of AB-IP104 sits inside the <sup> of its note.
    assert by_id["AB-IP104"].location == "le comté de Ponoka"
    assert by_id["BC-IP172"].premises_type == "non_commercial"  # "non- commerciale"
    assert by_id["BC-IP271"].premises_type == "non_commercial"
    assert by_id["ON-IP30"].control_zone_order is None  # "o.s."
    assert by_id["NL-IP01"].control_zone_order_text == "Zone libérée"
    assert by_id["BC-IP230"].control_zone_order_text == "Révoqué; ZCP-239 Révoqué"
    assert by_id["QC-IP58"].woah_classification_label is not None
    assert "IAFP" in by_id["QC-IP58"].woah_classification_label
    assert any("date différente" in note for note in result.notes)
    summary = result.province_summary
    assert summary is not None
    bc = next(r for r in summary.rows if r.province_code == "BC")
    assert (bc.province, bc.current_premises, bc.birds_impacted) == (
        "Colombie-Britannique",
        0,  # published as "`0"
        10_107_000,
    )
    nb = next(r for r in summary.rows if r.province_code == "NB")
    assert nb.birds_impacted_text == "Moins de 100"
    assert result.counts[0].label in {"Manitoba", "Colombie-Britannique"}


async def test_premises_filters(httpx_mock):
    _mock_premises(httpx_mock)
    bc = await client.get_avian_influenza(
        province="Colombie-Britannique",
        date_from="2024-11",
        date_to="2024-11",
        premises_type="commercial",
        counts_by="month",
    )
    assert {p.premises_id for p in bc.premises} == {"BC-IP210"}
    assert [(c.key, c.total) for c in bc.counts] == [("2024-11", 1)]
    capped = await client.get_avian_influenza(limit=5, counts_by="year")
    assert (capped.returned_count, capped.total_matched) == (5, 30)
    assert capped.provenance.limits == "premises capped at 5"
    assert capped.counts[0].key == "2026"


async def test_premises_reject_bad_arguments():
    with pytest.raises(InvalidInput):
        await client.get_avian_influenza(status="active")
    with pytest.raises(InvalidInput):
        await client.get_avian_influenza(province="Atlantis")
    with pytest.raises(InvalidInput):
        await client.get_avian_influenza(date_from="2025-13")
    with pytest.raises(InvalidInput):
        await client.get_avian_influenza(date_from="2025", date_to="2024")
    with pytest.raises(InvalidInput):
        await client.get_avian_influenza(premises_type="backyard")
    with pytest.raises(InvalidInput):
        await client.get_avian_influenza(limit=0)


async def test_status_page_failure_keeps_the_premises(httpx_mock):
    _mock(httpx_mock, constants.HPAI_PREMISES_PAGE["en"], "premises_en.html")
    page = _text("status_en.html").replace(">Province</th>", ">Region</th>")
    _mock(httpx_mock, constants.HPAI_STATUS_PAGE["en"], text=page)
    result = await client.get_avian_influenza()
    assert result.province_summary is None
    assert result.total_matched == 30
    assert any("status-by-province" in note for note in result.notes)


async def test_premises_layout_change_raises(httpx_mock):
    page = _text("premises_en.html").replace("<th>Province</th>", "<th>Region</th>", 1)
    _mock(httpx_mock, constants.HPAI_PREMISES_PAGE["en"], text=page)
    with pytest.raises(UpstreamError, match="layout changed"):
        await client.get_avian_influenza()


async def test_results_are_cached(httpx_mock):
    _mock_premises(httpx_mock)
    first = await client.get_avian_influenza()
    second = await client.get_avian_influenza(status="released")
    assert first.provenance.cached is False and second.provenance.cached is True
    assert second.total_matched == 18
