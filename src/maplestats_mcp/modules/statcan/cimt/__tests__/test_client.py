from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.cimt import client, constants
from maplestats_mcp.modules.statcan.lang import use_lang
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_REST = constants.BASE_URL
_CODES = constants.CODES_BASE_URL
_EXPORT_REFERER = constants.REFERER_BY_DIRECTION["exports"]
_IMPORT_REFERER = constants.REFERER_BY_DIRECTION["imports"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


# The real files are JavaScript array literals: a byte-order mark, CRLF line
# ends, trailing commas after the last field, accents, and en dashes in the
# French province names (all confirmed live 2026-10-02).
_COUNTRIES = (
    "﻿var countries = [\r\n"
    '{\r\n   "id": 1000,\r\n   "c_start": 197601,\r\n   "c_end": 999912,\r\n'
    '   "c_code": "WW",\r\n   "en": "World total",\r\n   "fr": "Total mondial"\r\n},\r\n'
    '{\r\n   "id": 9,\r\n   "c_start": 196601,\r\n   "c_end": 999912,\r\n'
    '   "c_code": "US",\r\n   "en": "United States of America",\r\n'
    '   "fr": "États-Unis d\'Amérique"\r\n},\r\n'
    '{\r\n   "id": 553,\r\n   "c_start": 198701,\r\n   "c_end": 999912,\r\n'
    '   "c_code": "CN",\r\n   "en": "China",\r\n   "fr": "Chine"\r\n},\r\n'
    '{\r\n   "id": 668,\r\n   "c_start": 199001,\r\n   "c_end": 999912,\r\n'
    '   "c_code": "UM",\r\n   "en": "United States Minor Outlying Islands",\r\n'
    '   "fr": "Îles mineures éloignées des États-Unis"\r\n},\r\n'
    '{\r\n   "id": 887,\r\n   "c_start": 199001,\r\n   "c_end": 999912,\r\n'
    '   "c_code": "VI",\r\n   "en": "Virgin Islands, United States",\r\n'
    '   "fr": "Vierges des États-Unis, îles"\r\n},\r\n'
    '{\r\n   "id": 887,\r\n   "c_start": 199001,\r\n   "c_end": 999912,\r\n'
    '   "c_code": "VI",\r\n   "en": "Virgin Islands, United States",\r\n'
    '   "fr": "Vierges des États-Unis, îles"\r\n},\r\n'
    '{\r\n   "id": 258,\r\n   "c_start": 196601,\r\n   "c_end": 199009,\r\n'
    '   "c_code": "DD",\r\n   "en": "East Germany",\r\n   "fr": "Allemagne de l\'Est"\r\n}\r\n]'
)
_STATES = (
    "﻿var states = [\r\n"
    '     {"id":100, "label_en": "United States", "label_fr": "États-Unis"},\r\n'
    '     {"id":44, "label_en": "Texas", "label_fr": "Texas"},\r\n'
    '     {"id":5, "label_en": "California", "label_fr": "Californie"}\r\n]'
)
_PROVINCES = (
    "﻿provinces = [\r\n"
    '     {"id":24,"en":"Quebec", "fr": "Québec"},\r\n'
    '     {"id":35,"en":"Ontario", "fr": "Ontario"},\r\n'
    '     {"id":48,"en":"Alberta", "fr": "Alberta"},\r\n'
    '     {"id":10,"en":"Newfoundland and Labrador", "fr": "Terre–Neuve–et–Labrador"}\r\n]'
)
_UOM = (
    "var UOM = [\r\n"
    '{\r\n   "id": "MTQ",\r\n   "en": "Volume in cubic metres",\r\n'
    '   "fr": "Volume en mètres cubes",\r\n},\r\n'
    '{\r\n   "id": "NMB",\r\n   "en": "Number",\r\n   "fr": "Nombre",\r\n},\r\n'
    '{\r\n   "id": "KGM",\r\n   "en": "Weight in kilograms",\r\n'
    '   "fr": "Poids en kilogrammes",\r\n}\r\n]'
)
_CHAPTERS = (
    "﻿var chapters = [\r\n"
    '     {"HS":"27","EN":"Mineral fuels, mineral oils","FR":"Combustibles minéraux, huiles"},\r\n'
    '     {"HS":"87","EN":"Vehicles other than railway","FR":"Véhicules automobiles"}\r\n]'
)


def _hs_entry(code: str, unit: str, en: str, fr: str, start: str, end: str) -> str:
    # Trailing comma after the last field, as in the real files.
    return (
        "{\r\n"
        f'   "HS": "{code}",\r\n   "UOM": "{unit}",\r\n   "EN": "{en}",\r\n   "FR": "{fr}",\r\n'
        f'   "C_START": "{start}",\r\n   "C_END": "{end}",\r\n   "U_START": "{start}",\r\n'
        f'   "U_END": "{end}",\r\n}}'
    )


_HS6_EXPORTS = (
    "var HS6 = [\r\n"
    + ",\r\n".join(
        [
            _hs_entry(
                "270900",
                "MTQ",
                "Petroleum oils, crude",
                "Huiles brutes de pétrole",
                "198801",
                "999912",
            ),
            _hs_entry(
                "271000",
                "MTQ",
                "Petroleum oils, other than crude",
                "Huiles de pétrole, autres que brutes",
                "198801",
                "198912",
            ),
            _hs_entry(
                "870323", "NMB", "Passenger cars, 1500-3000 cc", "Voitures", "198801", "999912"
            ),
            _hs_entry(
                "990400", "BLANK", "Goods of US origin returning", "Retour", "198801", "999912"
            ),
        ]
    )
    + "\r\n]"
)
_HS8_EXPORTS = (
    "var HS8 = [\r\n"
    + ",\r\n".join(
        [
            _hs_entry("27090010", "MTQ", "Crude, heavy", "Brut, lourd", "201501", "999912"),
            _hs_entry("27090021", "MTQ", "Condensate", "Condensat", "201501", "999912"),
        ]
    )
    + "\r\n]"
)
_HS10_IMPORTS = (
    "var HS10 = [\r\n"
    + _hs_entry(
        "2709000041", "MTQ", "Condensate, imports", "Condensat, importations", "200201", "999912"
    )
    + "\r\n]"
)
_HS4 = (
    'var HS4 = [\r\n{\r\n   "HS": "2709",\r\n   "EN": "Crude petroleum",\r\n'
    '   "FR": "Pétrole brut",\r\n}\r\n]'
)

_CODE_FILES = {
    "countriesF": _COUNTRIES,
    "states_codr": _STATES,
    "provinces": _PROVINCES,
    "uom": _UOM,
    "chaptersF": _CHAPTERS,
    "hs4F": _HS4,
    "hs6F_X": _HS6_EXPORTS,
    "hs6F": _HS6_EXPORTS,
    "hs8F": _HS8_EXPORTS,
    "hs10F": _HS10_IMPORTS,
}


def _mock_codes(httpx_mock, *, skip: tuple[str, ...] = ()) -> None:
    for name, text in _CODE_FILES.items():
        if name in skip:
            continue
        httpx_mock.add_response(
            url=f"{_CODES}/{name}.js",
            content=text.encode("utf-8"),
            is_reusable=True,
            is_optional=True,
        )


def _mock_periods(httpx_mock, latest: str = "2026-07-01") -> None:
    httpx_mock.add_response(
        url=f"{_REST}/getPeriods",
        json={"start": "1988-01-01", "current": latest},
        is_reusable=True,
        is_optional=True,
        match_headers={"Referer": _EXPORT_REFERER},
    )


def _report_row(**overrides):
    row = {"T": "2025-01-01", "H": "270900", "C": 9, "S": 100, "P": 1, "Q": 21357904.0, "V": 1.3e10}
    return {**row, **overrides}


# --- parsing and periods -----------------------------------------------------


async def test_get_periods_reads_start_and_current(httpx_mock):
    _mock_periods(httpx_mock)
    result = await client.get_periods()
    assert (result.first_period, result.latest_period) == ("1988-01", "2026-07")
    assert result.provenance.as_of is not None
    assert "may change" in (result.provenance.coverage or "")


async def test_request_carries_the_application_referer(httpx_mock):
    # Without this header the real service answers 404 (confirmed live).
    httpx_mock.add_response(
        url=f"{_REST}/getPeriods",
        json={"start": "1988-01-01", "current": "2026-07-01"},
        match_headers={"Referer": _EXPORT_REFERER},
    )
    await client.get_periods()


async def test_missing_referer_404_names_the_api_change_risk(httpx_mock):
    httpx_mock.add_response(url=f"{_REST}/getPeriods", status_code=404)
    with pytest.raises(UpstreamError, match="Referer"):
        await client.get_periods()


async def test_french_periods_provenance_and_errors(httpx_mock):
    use_lang("fr")
    _mock_periods(httpx_mock)
    result = await client.get_periods()
    assert (result.provenance.coverage or "").startswith("API non documentée")
    assert result.provenance.freshness == "mensuel, depuis 1988-01"
    with pytest.raises(InvalidInput, match="hors de la période publiée"):
        await client.get_trade("exports", "2026-07", "2030-01", lang="fr")
    with pytest.raises(InvalidInput, match="level doit être chapter"):
        await client.search_commodities("x", level="hs12", lang="fr")


# --- searching code lists ----------------------------------------------------


async def test_search_commodities_by_words_matches_either_language(httpx_mock):
    _mock_codes(httpx_mock)
    result = await client.search_commodities("pétrole brut", level="hs6")
    assert result.commodities[0].code == "270900"
    assert result.commodities[0].unit == "Volume in cubic metres"


async def test_search_commodities_orders_current_codes_before_retired(httpx_mock):
    _mock_codes(httpx_mock)
    result = await client.search_commodities("petroleum", level="hs6")
    assert [m.code for m in result.commodities] == ["270900", "271000"]
    assert result.commodities[0].valid_to is None
    assert result.commodities[1].valid_to == "1989-12"


async def test_search_commodities_by_code_prefix_and_blank_unit(httpx_mock):
    _mock_codes(httpx_mock)
    result = await client.search_commodities("9904", level="hs6")
    assert result.commodities[0].code == "990400"
    assert result.commodities[0].unit_code is None
    assert result.commodities[0].unit is None


async def test_search_commodities_french_text_and_national_level(httpx_mock):
    _mock_codes(httpx_mock)
    result = await client.search_commodities("2709", level="national", lang="fr")
    assert [m.description for m in result.commodities] == ["Brut, lourd", "Condensat"]
    assert result.commodities[0].unit == "Volume en mètres cubes"


async def test_search_commodities_rejects_bad_level():
    with pytest.raises(InvalidInput):
        await client.search_commodities("x", level="hs12")


async def test_search_partners_countries_dedupe_and_include_world(httpx_mock):
    _mock_codes(httpx_mock)
    everything = await client.search_partners("", limit=100)
    codes = [p.code for p in everything.partners]
    assert codes.count(887) == 1  # repeated in the upstream file
    assert codes[0] == constants.WORLD_ID
    historical = await client.search_partners("east germany")
    assert historical.partners[0].valid_to == "1990-09"


async def test_search_partners_by_iso_code_and_state_and_province(httpx_mock):
    _mock_codes(httpx_mock)
    assert (await client.search_partners("CN")).partners[0].code == 553
    assert (await client.search_partners("texas", kind="us_state")).partners[0].code == 44
    quebec = await client.search_partners("québec", kind="province", lang="fr")
    assert (quebec.partners[0].code, quebec.partners[0].iso_code) == (24, "QC")
    nl = await client.search_partners("terre", kind="province", lang="fr")
    assert nl.partners[0].name == "Terre-Neuve-et-Labrador"  # en dashes normalized


# --- get_trade ---------------------------------------------------------------


async def test_get_trade_builds_the_report_path_and_maps_rows(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/9/100/270900/1/500/0/0/2025-01-01/2025-02-01",
        json={
            "count": 2,
            "trade": [
                _report_row(T="2025-01-01", V=1.0e10),
                _report_row(T="2025-02-01", V=1.1e10, Q=None),
            ],
        },
        match_headers={"Referer": _EXPORT_REFERER},
    )
    result = await client.get_trade("exports", "2025-01", "2025-02", hs_code="270900", partner="US")
    assert [r.period for r in result.rows] == ["2025-01", "2025-02"]
    first = result.rows[0]
    assert first.partner == "United States of America"
    assert first.province == "Canada"
    assert first.us_state is None  # state 100 means "not split by state"
    assert first.hs_description == "Petroleum oils, crude"
    assert first.unit == "Volume in cubic metres"
    assert result.rows[1].quantity is None
    assert result.returned_value_cad == 2.1e10
    assert not result.truncated


async def test_get_trade_flags_truncation_when_count_exceeds_rows(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/1000/100/0/1/1/0/0/2026-07-01/2026-07-01",
        json={"count": 4476, "trade": [_report_row(T="2026-07-01", C=1000)]},
    )
    result = await client.get_trade("exports", "2026-07", "2026-07", limit=1)
    assert result.truncated
    assert result.total_count == 4476
    assert result.returned_count == 1
    assert "arbitrary subset" in (result.provenance.limits or "")


async def test_get_trade_annualized_period_is_the_year(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/9/100/2709/1/500/0/1/2025-01-01/2025-12-01",
        json={"count": 1, "trade": [_report_row(T="2025-01-01", V=1.27e11)]},
    )
    result = await client.get_trade(
        "exports", "2025-01", "2025-12", hs_code="2709", partner="United States", annualize=True
    )
    assert result.rows[0].period == "2025"


async def test_get_trade_province_list_is_sorted_and_canada_wins(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(24,35)/1000/100/87/1/500/0/0/2026-07-01/2026-07-01",
        json={"count": 1, "trade": [_report_row(P=24, C=1000, H="870323")]},
    )
    result = await client.get_trade(
        "exports", "2026-07", "2026-07", hs_code="87", provinces=["ON", "Québec"]
    )
    assert result.rows[0].province == "Quebec"
    # Canada plus a province returns Canada only upstream, so the client sends just (1).
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/1000/100/87/1/500/0/0/2026-07-01/2026-07-01",
        json={"count": 0, "trade": []},
    )
    empty = await client.get_trade(
        "exports", "2026-07", "2026-07", hs_code="87", provinces=["Canada", "ON"]
    )
    assert empty.rows == []


async def test_get_trade_us_state_implies_the_united_states(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/9/44/870323/1/500/0/0/2026-07-01/2026-07-01",
        json={"count": 1, "trade": [_report_row(S=44, H="870323", T="2026-07-01")]},
    )
    result = await client.get_trade(
        "exports", "2026-07", "2026-07", hs_code="870323", us_state="Texas"
    )
    assert result.rows[0].us_state == "Texas"
    assert result.rows[0].us_state_code == 44


async def test_get_trade_imports_use_the_import_referer_and_trade_type(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(48)/1000/100/2709/0/500/1/0/2026-07-01/2026-07-01",
        json={"count": 1, "trade": [_report_row(H="2709000041", P=48, C=1000)]},
        match_headers={"Referer": _IMPORT_REFERER},
    )
    result = await client.get_trade(
        "imports", "2026-07", "2026-07", hs_code="2709", provinces=["AB"], hs_level="national"
    )
    assert result.rows[0].province == "Alberta"
    assert result.rows[0].hs_description == "Condensate, imports"


async def test_get_trade_keeps_the_data_when_the_description_list_is_down(httpx_mock):
    _mock_codes(httpx_mock, skip=("hs6F_X",))
    httpx_mock.add_response(url=f"{_CODES}/hs6F_X.js", status_code=503, is_reusable=True)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/9/100/270900/1/500/0/0/2025-01-01/2025-01-01",
        json={"count": 1, "trade": [_report_row()]},
    )
    result = await client.get_trade("exports", "2025-01", "2025-01", hs_code="270900", partner="US")
    assert result.rows[0].value_cad == 1.3e10
    assert result.rows[0].hs_description is None


async def test_get_trade_future_month_is_rejected_before_any_report_call(httpx_mock):
    # The service answers HTTP 500 for a month it has not published (confirmed live).
    _mock_periods(httpx_mock)
    with pytest.raises(InvalidInput, match="outside the published range"):
        await client.get_trade("exports", "2026-07", "2030-01")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"hs_code": "270900100"}, "digits"),
        ({"hs_code": "2"}, "digits"),
        ({"hs_code": "27x0"}, "digits only"),
        ({"hs_code": "27090010"}, "hs_level"),
        ({"hs_code": "2709001000", "hs_level": "national"}, "does not match"),
        ({"hs_level": "hs4"}, "hs_level"),
        ({"limit": 0}, "limit"),
        ({"limit": 5001}, "limit"),
    ],
)
async def test_get_trade_rejects_bad_arguments(kwargs, message):
    with pytest.raises(InvalidInput, match=message):
        await client.get_trade("exports", "2026-06", "2026-07", **kwargs)


async def test_get_trade_rejects_bad_period_order_and_format():
    with pytest.raises(InvalidInput, match="after"):
        await client.get_trade("exports", "2026-07", "2026-06")
    with pytest.raises(InvalidInput, match="YYYY-MM"):
        await client.get_trade("exports", "July 2026", "2026-07")
    with pytest.raises(InvalidInput, match="direction"):
        await client.get_trade("trade", "2026-06", "2026-07")


async def test_partner_resolution_errors(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    with pytest.raises(NotFound):
        await client.get_trade("exports", "2026-06", "2026-07", partner="Atlantis")
    with pytest.raises(InvalidInput, match="ambiguous"):
        await client.get_trade("exports", "2026-06", "2026-07", partner="united st")
    with pytest.raises(InvalidInput, match="United States as partner"):
        await client.get_trade("exports", "2026-06", "2026-07", partner="China", us_state="Texas")


async def test_upstream_406_becomes_invalid_input(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/1000/100/27/1/500/0/0/2026-07-01/2026-07-01", status_code=406
    )
    with pytest.raises(InvalidInput, match="406"):
        await client.get_trade("exports", "2026-07", "2026-07", hs_code="27")


async def test_upstream_500_is_retried_then_raised(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getReport/(1)/1000/100/27/1/500/0/0/2026-07-01/2026-07-01",
        status_code=500,
        is_reusable=True,
    )
    with pytest.raises(UpstreamError, match="500"):
        await client.get_trade("exports", "2026-07", "2026-07", hs_code="27")


# --- rankings, breakdown and series -----------------------------------------


async def test_get_top_partners_ranks_countries_with_shares(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getTopPartners/2026-07-01/1/1000/100/0/0/0",
        json={"total": 100.0, "trade": [{"C": 9, "V": 67.0}, {"C": 553, "V": 5.0}]},
    )
    result = await client.get_top_partners("exports")
    assert result.period == "2026-07"
    assert [p.name for p in result.partners] == ["United States of America", "China"]
    assert result.partners[0].share_of_total == pytest.approx(0.67)
    assert result.total_value_cad == 100.0


async def test_get_top_partners_us_state_view_uses_state_mode(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getTopPartners/2026-06-01/35/9/100/27/1/1",
        json={"total": 10.0, "trade": [{"C": 44, "V": 5.0}]},
        match_headers={"Referer": _IMPORT_REFERER},
    )
    result = await client.get_top_partners(
        "imports", period="2026-06", hs_chapter="27", province="Ontario", view="us_state"
    )
    assert result.partners[0].name == "Texas"
    assert result.province == "Ontario"
    assert result.hs_chapter == "27"


async def test_get_top_partners_rejects_bad_chapter_and_view():
    with pytest.raises(InvalidInput, match="chapter"):
        await client.get_top_partners("exports", hs_chapter="2709")
    with pytest.raises(InvalidInput, match="view"):
        await client.get_top_partners("exports", view="province")


async def test_get_top_commodities_names_from_the_hs6_list(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getTopCommodities/2026-07-01/48/9/100/0/1/0",
        json={"trade": [{"H": "270900", "V": 11.0}, {"H": "999999", "V": 1.0}]},
    )
    result = await client.get_top_commodities("exports", province="AB", partner="US")
    assert result.commodities[0].name == "Petroleum oils, crude"
    assert result.commodities[1].name == "999999"  # not in the list: the code stands in
    assert result.partner == "United States of America"


async def test_get_province_breakdown_reports_reexports_separately(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getProvinces/2026-07-01/553/100/12/0",
        json={
            "domestic": 90.0,
            "reexports": 10.0,
            "trade": [{"P": 48, "V": 60.0}, {"P": 35, "V": 40.0}],
        },
    )
    result = await client.get_province_breakdown("exports", partner="China", hs_chapter="12")
    assert [p.name for p in result.provinces] == ["Alberta", "Ontario"]
    assert result.provinces[0].share_of_total == pytest.approx(0.6)
    assert result.reexport_value_cad == 10.0


async def test_get_series_chapter_uses_the_chapter_chart(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getChapterChart/2026-07-01/1/9/100/27/0",
        json={"chart": [{"T": "2026-06-01", "V": 2.0}, {"T": "2026-05-01", "V": 1.0}]},
    )
    result = await client.get_series("exports", "27", partner="US")
    assert [p.period for p in result.points] == ["2026-05", "2026-06"]
    assert {p.measure for p in result.points} == {"value"}
    assert result.unit is None


async def test_get_series_commodity_labels_the_estimate_flags(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getCommodityChart/2026-07-01/1/1000/100/270900/0",
        json={
            "chart": [
                {"R": "2026-07-01", "V": 14.0, "E": 1},
                {"R": "2026-07-01", "V": 0.2, "E": 2},
                {"R": "2026-07-01", "V": 20.0, "E": 3},
                {"R": "2026-07-01", "V": 1.0, "E": 4},
            ]
        },
    )
    result = await client.get_series("exports", "270900")
    by_measure = {p.measure: p.value for p in result.points}
    assert by_measure == {
        "domestic_value": 14.0,
        "reexport_value": 0.2,
        "domestic_quantity": 20.0,
        "reexport_quantity": 1.0,
    }
    assert result.unit == "Volume in cubic metres"


async def test_get_series_imports_flags_are_value_then_quantity(httpx_mock):
    _mock_codes(httpx_mock)
    _mock_periods(httpx_mock)
    httpx_mock.add_response(
        url=f"{_REST}/getCommodityChart/2026-07-01/1/1000/100/270900/1",
        json={
            "chart": [{"R": "2026-07-01", "V": 5.0, "E": 1}, {"R": "2026-07-01", "V": 2.0, "E": 2}]
        },
        match_headers={"Referer": _IMPORT_REFERER},
    )
    result = await client.get_series("imports", "270900")
    assert {p.measure for p in result.points} == {"value", "quantity"}


async def test_get_series_rejects_four_digit_code():
    with pytest.raises(InvalidInput, match="4-digit"):
        await client.get_series("exports", "2709")


async def test_lists_are_fetched_once_and_cached(httpx_mock):
    _mock_codes(httpx_mock)
    await client.search_partners("china")
    await client.search_partners("china")
    countries_requests = [
        r for r in httpx_mock.get_requests() if r.url.path.endswith("countriesF.js")
    ]
    assert len(countries_requests) == 1


async def test_empty_code_list_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=f"{_CODES}/countriesF.js", text="<html>moved</html>")
    with pytest.raises(UpstreamError, match="format may have changed"):
        await client.search_partners("china")


async def test_search_partners_puts_an_exact_code_before_name_matches(httpx_mock):
    _mock_codes(httpx_mock)
    # "AB" is inside "Newfoundland and Labrador" too; the province code must come first.
    result = await client.search_partners("AB", kind="province")
    assert result.partners[0].code == 48
    assert result.total_matched > 1
