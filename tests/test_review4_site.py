"""Fourth review of the website generator: the home page's demo, the places inscribed in
the square, French month abbreviations and the Toronto page's trimmed-response comments.

The checks that need the whole site built (the demo's JSON on the French page, the chart
labels) are at the end of tests/test_site.py, which builds it once.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest

from tests.test_site import ALLOWED_NAMES, ENGLISH_MARKERS, _FrenchText, site

NBSP, NNBSP = " ", " "
ENGLISH_MONTHS = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November"
    r"|December)\b"
)


def _demo(lang: str) -> list[dict[str, str]]:
    """The demo's examples as the browser reads them: the JSON in the script element."""
    markup = site.chat_demo_context(lang)["chat_demo"]
    payload = re.search(r'data-ask-examples="">(.*?)</script>', markup, re.DOTALL)
    assert payload
    return json.loads(payload.group(1))


# --------------------------------------------------------------------------
# The home page's demo, in French.
# --------------------------------------------------------------------------


def test_the_french_demo_spaces_its_punctuation_and_its_units():
    for example in _demo("fr"):
        for key in ("user", "html", "code", "cite"):
            text = re.sub(r"<[^>]+>", "", example[key])
            assert not re.search(r" [:;?!%$»]|« |\d%", text), (key, text)
    by_tool = {example["tool"]: example for example in _demo("fr")}
    beef = by_tool["wds_get_data_from_cube_coord"]
    assert beef["user"].endswith(f"{NNBSP}?")
    assert f"{NBSP}$" in beef["html"]
    assert re.search(rf"\d{NBSP}\$", beef["code"])
    cards = by_tool["fcac_search_credit_cards"]
    assert re.search(rf"\d{NNBSP}%", cards["html"])
    assert re.search(rf"\d{NNBSP}%", cards["code"])
    assert f"{NBSP}:" in cards["html"]


def test_the_french_demo_marks_the_english_draw_name_and_quotes_it_in_french():
    draw = {e["tool"]: e for e in _demo("fr")}["ircc_get_latest_express_entry_round"]
    recorded = {c["name"]: c["response"] for c in site.load_case("prompts")["calls"]}
    name = recorded["ircc_get_latest_express_entry_round"]["round"]["draw_name"]
    quoted = "«" + NBSP + '<span lang="en">' + name + "</span>" + NBSP + "»"
    assert quoted in draw["html"]
    # The English page has no markup around it.
    english = {e["tool"]: e for e in _demo("en")}["ircc_get_latest_express_entry_round"]
    assert 'lang="en"' not in english["html"]


def test_the_french_demo_names_the_outlook_month_in_french():
    budget = {e["tool"]: e for e in _demo("fr")}["pbo_get_publication"]
    assert "perspectives de juin 2026" in budget["html"]
    assert re.search(rf"\d{NBSP}G\$", budget["html"])  # the unit never wraps off its figure
    for example in _demo("fr"):
        assert not ENGLISH_MONTHS.search(" ".join(example.values())), example["tool"]
    assert (
        "In its June 2026 outlook"
        in {e["tool"]: e for e in _demo("en")}["pbo_get_publication"]["html"]
    )


@pytest.mark.parametrize(("month", "phrase"), [("April", "d'avril"), ("June", "de juin")])
def test_the_outlook_month_takes_de_or_d_before_a_vowel(monkeypatch, month, phrase):
    real = site.load_case

    def fake(key: str) -> dict[str, Any]:
        case = copy.deepcopy(real(key))
        if key == "prompts":
            for call in case["calls"]:
                if call["name"] == "pbo_get_publication":
                    title = call["response"]["publication"]["title"]
                    call["response"]["publication"]["title"] = title.replace("June", month)
        return case

    monkeypatch.setattr(site, "load_case", fake)
    html = {e["tool"]: e for e in _demo("fr")}["pbo_get_publication"]["html"]
    assert f"perspectives {phrase} 2026" in html


@pytest.mark.parametrize("years", [1, 6])
def test_the_demo_names_the_fiscal_year_of_the_capture_not_a_fixed_one(monkeypatch, years):
    """A capture taken `years` later reads its own year, and does not stop the build
    when the table no longer has 2026-2027."""
    real = site.load_case

    def later(key: str) -> dict[str, Any]:
        case = copy.deepcopy(real(key))
        if key == "prompts":
            case["captured"] = f"{int(case['captured'][:4]) + years}{case['captured'][4:]}"
            for call in case["calls"]:
                if call["name"] == "pbo_get_publication":
                    for row in call["response"]["tables"][0]["rows"]:
                        start, end = row["sdg7j"].split("-")
                        row["sdg7j"] = f"{int(start) + years}-{int(end) + years}"
        return case

    monkeypatch.setattr(site, "load_case", later)
    year = f"{2026 + years}-{2027 + years}"
    for lang in ("en", "fr"):
        budget = {e["tool"]: e for e in _demo(lang)}["pbo_get_publication"]
        assert f"{year}" in budget["html"], lang
        # The question carries the year, so it stays true after the year has passed.
        assert year in budget["user"], lang
        assert "this year" not in budget["user"] and "cette année" not in budget["user"]
        # The rows beside the answer are that year and its neighbours.
        assert [line.split("  ")[0] for line in budget["code"].split("\n")] == [
            f"{2025 + years}-{2026 + years}",
            year,
            f"{2027 + years}-{2028 + years}",
        ]


def test_the_demo_year_is_the_fiscal_year_that_holds_the_capture_date(monkeypatch):
    # The federal fiscal year runs from 1 April: a capture in March belongs to the year
    # that began the April before.
    real = site.load_case

    def march(key: str) -> dict[str, Any]:
        case = copy.deepcopy(real(key))
        if key == "prompts":
            case["captured"] = "2027-03-31"
        return case

    monkeypatch.setattr(site, "load_case", march)
    assert "for 2026-2027." in {e["tool"]: e for e in _demo("en")}["pbo_get_publication"]["html"]


def test_the_french_demo_has_no_unmarked_english():
    for example in _demo("fr"):
        parser = _FrenchText()
        parser.feed(f'<html lang="fr">{example["html"]}</html>')
        chunks = [*parser.chunks, example["user"], example["cite"]]
        for chunk in chunks:
            assert not ENGLISH_MARKERS.search(ALLOWED_NAMES.sub("", chunk)), chunk


# --------------------------------------------------------------------------
# The places inscribed in the square.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("portal", "city"),
    [
        ("Open Data Kingston", "Kingston"),
        ("Open Kelowna", "Kelowna"),
        ("City of Nanaimo GIS Open Data Portal", "Nanaimo"),
        ("City of Calgary: building permits and community populations", "Calgary"),
        ("City of Toronto open data", "Toronto"),
        ("Halifax Regional Municipality (HRM) Open Data", "Halifax"),
        ("Sturgeon County Atlas", "Sturgeon"),
        ("City of Niagara Falls Open Data", "Niagara Falls"),
        ("Niagara Region Open Data", "Niagara"),
        ("City of Red Deer ArcGIS Hub", "Red Deer"),
    ],
)
def test_a_portal_name_gives_the_place_it_serves(portal: str, city: str):
    assert site._city(portal) == city


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_the_square_lists_real_place_names_once_each(lang: str):
    names = site.square_places(lang)
    assert len(names) == len(set(names))
    for junk in ("Transit schedules", "BC Transit real-time", "Data Kingston", "Nanaimo GIS"):
        assert junk not in names
    # A service, an agency or a conservation authority is not a place.
    agency = re.compile(r"Transit|Police|Conservation|Authority|EPCOR|Board")
    assert not [name for name in names if agency.search(name)]
    # A city whose name holds another's stays: Niagara Falls beside Niagara.
    for city in ("Kingston", "Nanaimo", "Niagara", "Niagara Falls", "Waterloo", "Vancouver"):
        assert city in names, city


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_the_square_lists_each_province_then_its_cities_in_a_fixed_order(lang: str):
    index = 1 if lang == "en" else 2
    provinces = [site.PLACES[code][index] for code in site.SQUARE_ORDER]
    names = site.square_places(lang)
    headings = [name for name in names if name in provinces]
    assert headings == [p for p in provinces if p in names]  # west to east, then north
    block: list[str] = []
    for name in [*names, None]:
        if name is None or name in provinces:
            assert block == sorted(block, key=lambda n: (site.alphabetical(n), n))
            block = []
        else:
            block.append(name)


def test_french_names_of_montreal_and_quebec_stay_french():
    names = site.square_places("fr")
    assert "Montréal" in names and "Montreal" not in names


# --------------------------------------------------------------------------
# French month abbreviations.
# --------------------------------------------------------------------------


def test_month_abbreviations():
    days = [f"2026-{month:02d}-01" for month in range(1, 13)]
    assert [site.month_abbr(day, "en") for day in days] == [
        *("Jan", "Feb", "Mar", "Apr", "May", "Jun"),
        *("Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    ]
    assert [site.month_abbr(day, "fr") for day in days] == [
        *("janv.", "févr.", "mars", "avr.", "mai", "juin"),
        *("juill.", "août", "sept.", "oct.", "nov.", "déc."),
    ]


# --------------------------------------------------------------------------
# The Toronto page's "+N autres" comments.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "english", "french"),
    [(1, "1 more", "1 autre"), (2, "2 more", "2 autres"), (7, "7 more", "7 autres")],
)
def test_a_trimmed_list_says_how_many_more_in_each_language(count: int, english: str, french: str):
    assert site._more_items(count, "en") == site._MORE + english
    assert site._more_items(count, "fr") == site._MORE + french


def test_the_toronto_page_pluralises_its_other_items(monkeypatch):
    import asyncio

    modules = asyncio.run(site.collect_modules())
    case, calls = site._toronto_calls()
    calls = copy.deepcopy(calls)
    for call in calls:
        response = call["response"]
        if call["name"] == "ckan_search_datasets" and call["arguments"].get("query"):
            response["returned_count"] = 4
        if call["name"] == "ckan_get_dataset_documents":
            response["data_dictionary"] += response["data_dictionary"][:2]
            response["documents"] += response["documents"][:2]
    monkeypatch.setattr(site, "_toronto_calls", lambda: (case, calls))
    french = "\n".join(site.toronto_context(modules, "fr").values())
    assert len(re.findall(r"// 3 autres</span>", french)) == 3
    assert not re.search(r"// (?:[2-9]|\d\d+) autre</span>", french)
    english = "\n".join(site.toronto_context(modules, "en").values())
    assert len(re.findall(r"// 3 more</span>", english)) == 3
