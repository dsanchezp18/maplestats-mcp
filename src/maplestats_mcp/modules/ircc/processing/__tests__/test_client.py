"""Tests for ircc/processing/client.py, shaped on the live files read 2026-11-03."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from maplestats_mcp.modules.ircc.processing import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

_PTIME_EN = {
    "visitor-outside-canada": {
        "AF": "26 days",
        "IN": "31 days",
        "AD": "No processing time available",
        "lastupdated": "October 29, 2026",
    },
    "work": {
        "IN": "10 weeks",
        "CA": "16 weeks",
        "GL": "No processing time available",
        "NG": "Not enough data",
        "lastupdated": "October 29, 2026",
    },
    "refugees_private": {
        "IN": {"sponsor": "28 months", "refugee": "17 months"},
        "lastupdated": "October 29, 2026",
    },
}
_PTIME_FR = {
    "visitor-outside-canada": {
        "IN": "31 jours",
        "AD": "Aucun d&eacute;lai de traitement disponible",
        "lastupdated": "29 octobre 2026",
    },
}
_NON_COUNTRY_EN = {
    "default-update": {"lastupdated": "October 29, 2026"},
    "work_extension": {"work_extension": "123 days"},
    "eta": {"eta": "5 minutes"},
    "citizenship": {"cit_adoption_part1": "Part 1: 4 months", "cit_resumption": "Not enough data"},
    "brand_new_group": {"brand_new_type": "3 weeks"},
}
_NON_COUNTRY_FR = {
    "default-update": {"lastupdated": "29 octobre 2026"},
    "work_extension": {"work_extension": "123 jours"},
    "iec": {"iec_past": "Pas assez de donn&eacute;es"},
}
_FLPT_EN = {
    "default-update": {"flpt_lastupdated": "October 9, 2026", "flpt_interval": "monthly"},
    "total-people": {"cec": "About 53,900 people waiting"},
    "current-flpt": {"cec": "About 6 months", "humanitarian-roc": "More than 10 years"},
    "people-ahead": {"cec-2016/01": "Less than 100 people ahead of you"},
}
_FLPT_FR = {
    "default-update": {"flpt_lastupdated": "9 octobre 2026", "flpt_interval": "mensuelle"},
    "total-people": {"cec": "Environ 53 900 personnes sont en attente"},
    "current-flpt": {"cec": "Environ 6 mois"},
}
_WEEK_EN = {
    "tr-last-updated": "October 24, 2026",
    "total-people": {"WP-EXT": "About 195,900 people waiting"},
    "current-flpt": {"WP-EXT": "11 weeks", "SP-EXT": "6 weeks"},
}
_COUNTRIES_EN = {
    "country-name": {"AF": "Afghanistan", "IN": "India", "AD": "Andorra", "NG": "Nigeria"}
}
_COUNTRIES_FR = {"country-name": {"IN": "Inde", "AD": "Andorre"}}

_FILES = {
    "data-ptime-en": _PTIME_EN,
    "data-ptime-fr": _PTIME_FR,
    "data-ptime-non-country-en": _NON_COUNTRY_EN,
    "data-ptime-non-country-fr": _NON_COUNTRY_FR,
    "flpt-en": _FLPT_EN,
    "flpt-fr": _FLPT_FR,
    "flpt-by-week-en": _WEEK_EN,
    "flpt-by-week-fr": _WEEK_EN,
    "data-country-name-en": _COUNTRIES_EN,
    "data-country-name-fr": _COUNTRIES_FR,
}


def _mock(httpx_mock, overrides=None):
    files = {**_FILES, **(overrides or {})}

    def answer(request):
        import httpx

        name = str(request.url).rsplit("/", 1)[-1].removesuffix(".json")
        body = files[name]
        if isinstance(body, httpx.Response):
            return body
        if isinstance(body, bytes):
            return httpx.Response(200, content=body)
        # The country-name files start with a UTF-8 BOM (live).
        return httpx.Response(200, content=b"\xef\xbb\xbf" + json.dumps(body).encode())

    httpx_mock.add_callback(answer, is_reusable=True)


def test_parse_time_forms():
    about = client.parse_time("About 6 months")
    assert (about.amount, about.unit, about.qualifier, about.status) == (
        6,
        "months",
        "about",
        "available",
    )
    assert client.parse_time("More than 10 years").qualifier == "more_than"
    assert client.parse_time("Environ 26 mois").unit == "months"
    assert client.parse_time("Plus de 10 ans").unit == "years"
    part = client.parse_time("Partie 1 : 4 mois")
    assert (part.amount, part.unit) == (4, "months")
    assert client.parse_time("5 minutes").approx_days == pytest.approx(5 / 1440, abs=1e-4)
    assert client.parse_time("1 week").approx_days == 7
    assert (
        client.parse_time("Aucun d&eacute;lai de traitement disponible").status
        == "no_time_available"
    )
    assert client.parse_time("Pas assez de donn&eacute;es").status == "not_enough_data"
    odd = client.parse_time("Varies")
    assert odd.status == "unparsed" and odd.text == "Varies"


def test_parse_dates_and_people():
    assert client.parse_update_date("October 29, 2026") == date(2026, 10, 29)
    assert client.parse_update_date("9 octobre 2026") == date(2026, 10, 9)
    assert client.parse_update_date("1er août 2026") is None
    assert client.parse_people("About 53,900 people waiting") == 53900
    assert client.parse_people("Environ 53 900 personnes sont en attente") == 53900


async def test_list_application_types(httpx_mock):
    _mock(httpx_mock)
    result = await client.list_application_types()
    ids = [t.type_id for t in result.types]
    assert {"visitor-outside-canada", "work", "work_extension", "cec", "WP-EXT"} <= set(ids)
    work = next(t for t in result.types if t.type_id == "work")
    assert work.by_country and work.basis == "processing_time"
    assert work.last_updated_date == date(2026, 10, 29)
    cec = next(t for t in result.types if t.type_id == "cec")
    assert cec.basis == "forward_looking" and cec.update_cadence == "monthly"
    assert cec.last_updated == "October 9, 2026"
    # A type IRCC adds later is kept, labelled with its own key.
    new = next(t for t in result.types if t.type_id == "brand_new_type")
    assert new.category == "other" and new.label == "brand_new_type"
    assert "not a time series" in result.note
    assert result.provenance.as_of and result.provenance.as_of.date() == date(2026, 10, 29)
    assert result.provenance.licence and "canada.ca" in result.provenance.licence
    only_work = await client.list_application_types("work")
    assert {t.category for t in only_work.types} == {"work"}
    with pytest.raises(InvalidInput, match="category"):
        await client.list_application_types("jobs")


async def test_single_time_types(httpx_mock):
    _mock(httpx_mock)
    inside = await client.get_processing_time("work_extension")
    assert inside.time and inside.time.text == "123 days" and inside.time.approx_days == 123
    assert inside.countries == [] and inside.application_type.last_updated == "October 29, 2026"
    estimate = await client.get_processing_time("wp-ext")
    assert estimate.application_type.type_id == "WP-EXT"
    assert estimate.people_waiting == 195900
    assert estimate.application_type.last_updated_date == date(2026, 10, 24)
    cec = await client.get_processing_time("Canadian Experience Class")
    assert cec.application_type.type_id == "cec" and cec.people_waiting == 53900
    with pytest.raises(InvalidInput, match="one processing time for everyone"):
        await client.get_processing_time("eta", country="IN")


async def test_by_country_types(httpx_mock):
    _mock(httpx_mock)
    every = await client.get_processing_time("work")
    # Longest first; unpublished last; CA and GL named though the name file lacks them.
    assert [c.country_code for c in every.countries][:2] == ["CA", "IN"]
    names = {c.country_code: c.country_name for c in every.countries}
    assert names["CA"] == "Canada" and names["GL"] == "Greenland"
    assert every.time is None and every.returned_count == 4
    india = await client.get_processing_time("visitor-outside-canada", country="india")
    assert [(c.country_code, c.time.text) for c in india.countries] == [("IN", "31 days")]
    by_code = await client.get_processing_time("refugees_private", country="in")
    assert [(c.component, c.time.amount) for c in by_code.countries] == [
        ("sponsor", 28),
        ("refugee", 17),
    ]
    with pytest.raises(NotFound, match="ISO code"):
        await client.get_processing_time("work", country="Atlantis")


async def test_french_files_are_unescaped(httpx_mock):
    _mock(httpx_mock)
    result = await client.get_processing_time(
        "visitor-outside-canada", country="Andorre", lang="fr"
    )
    entry = result.countries[0]
    assert entry.time.text == "Aucun délai de traitement disponible"
    assert entry.time.status == "no_time_available"
    assert result.application_type.label.startswith("Visa de visiteur")
    assert result.application_type.last_updated_date == date(2026, 10, 29)
    assert "série chronologique" in result.note
    iec = await client.get_processing_time("iec_past", lang="fr")
    assert iec.time and iec.time.text == "Pas assez de données"


async def test_type_resolution_errors(httpx_mock):
    _mock(httpx_mock)
    with pytest.raises(InvalidInput, match="several types"):
        await client.get_processing_time("work permit")
    with pytest.raises(NotFound, match="ircc_processing_list_application_types"):
        await client.get_processing_time("no such thing")
    with pytest.raises(InvalidInput, match="must not be empty"):
        await client.get_processing_time(" ")


@pytest.mark.parametrize(
    ("file", "body", "match"),
    [
        ("flpt-en", {"current-flpt": "About 6 months"}, "current-flpt"),
        ("data-ptime-en", ["not", "an", "object"], "application types"),
        ("data-ptime-non-country-en", {"default-update": {"lastupdated": "x"}}, "groups"),
        ("flpt-by-week-en", b"<html>moved</html>", "not JSON"),
    ],
)
async def test_changed_shape_is_a_typed_error(httpx_mock, file, body, match):
    _mock(httpx_mock, {file: body})
    with pytest.raises(UpstreamError, match=match) as raised:
        await client.list_application_types()
    assert "check-processing-times" in str(raised.value)


async def test_http_failures_are_typed(httpx_mock):
    import httpx

    _mock(httpx_mock, {"flpt-en": httpx.Response(404)})
    with pytest.raises(UpstreamError, match="404"):
        await client.list_application_types()


async def test_server_errors_are_unavailable(httpx_mock):
    import httpx

    _mock(httpx_mock, {"data-ptime-en": httpx.Response(503)})
    with pytest.raises(UpstreamUnavailable):
        await client.get_processing_time("work")


async def test_urls_follow_lang(httpx_mock):
    _mock(httpx_mock)
    await client.get_processing_time("cec", lang="fr")
    urls = {str(r.url) for r in httpx_mock.get_requests()}
    assert all(re.search(r"-fr\.json$", u) for u in urls)


@pytest.mark.parametrize(
    ("text", "amount", "unit", "days", "qualifier"),
    [
        # "," and "." were folded to spaces first: 1,234 read as 234 and no decimal matched.
        ("About 1,234 days", 1234, "days", 1234, "about"),
        ("10 000 jours", 10000, "days", 10000, None),
        ("10 000 jours", 10000, "days", 10000, None),
        ("1 234 days", 1234, "days", 1234, None),
        ("1.5 years", 1.5, "years", 547.875, None),
        ("Environ 1,5 an", 1.5, "years", 547.875, "about"),
        # A compound duration was read as its last pair ("6 months"): now summed, and
        # stated in the finest unit named so the amount and unit still read as one time.
        ("1 year 6 months", 18, "months", 547.875, None),
        ("1 an et 6 mois", 18, "months", 547.875, None),
        ("More than 2 weeks, 3 days", 17, "days", 17, "more_than"),
        # A range keeps its upper bound, as before.
        ("3 to 6 months", 6, "months", 182.625, None),
        ("3-6 months", 6, "months", 182.625, None),
        ("De 3 à 6 mois", 6, "months", 182.625, None),
        ("3 months to 6 months", 6, "months", 182.625, None),
        ("Between 3 and 6 months", 6, "months", 182.625, None),
        # business and working days are read as days, like jours ouvrables.
        ("10 business days", 10, "days", 10, None),
        ("10 working days", 10, "days", 10, None),
        ("10 jours ouvrables", 10, "days", 10, None),
        # The part number of a citizenship text is still skipped.
        ("Part 1: 4 months", 4, "months", 121.75, None),
        # A part number is not the first group of a thousands separator.
        ("Part 1 100 days", 100, "days", 100, None),
    ],
)
def test_parse_time_separators_compounds_ranges_and_business_days(
    text, amount, unit, days, qualifier
):
    parsed = client.parse_time(text)
    assert parsed.status == "available"
    assert (parsed.unit, parsed.qualifier) == (unit, qualifier)
    assert parsed.amount == pytest.approx(amount)
    assert parsed.approx_days == pytest.approx(days, abs=1e-3)


async def test_by_country_sort_uses_the_whole_duration(httpx_mock):
    # approx_days feeds the longest-first sort, so a misread amount moves the country.
    times = {
        "work": {
            "AF": "1 year 6 months",
            "IN": "About 1,234 days",
            "CA": "9 months",
            "GL": "10 business days",
            "NG": "5 days",
            "lastupdated": "October 29, 2026",
        }
    }
    _mock(httpx_mock, {"data-ptime-en": times})
    result = await client.get_processing_time("work")
    assert [c.country_code for c in result.countries] == ["IN", "AF", "CA", "GL", "NG"]
