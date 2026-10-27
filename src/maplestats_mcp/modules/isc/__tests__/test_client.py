"""Tests on pages and files trimmed from ISC and CIRNAC's live responses (2026-10-26)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from maplestats_mcp.modules.isc import client, constants, tools
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


def _page(body: str) -> str:
    return f'<html><body><main property="mainContentOfPage">{body}</main></body></html>'


def _span(element_id: str, text: str) -> str:
    return f'<span id="plcMain_{element_id}" class="text">{text}</span>'


_MAIN_143 = _page(
    _span("lblBandName", "Official Name")
    + _span("txtBandName", "Attawapiskat")
    + _span("txtPhoneticSpelling", "a-ta-wah-pi-skat")
    + _span("txtBandNumber", "143")
    + _span("txtAddress", "PO BOX 248, ATTAWAPISKAT, ON")
    + _span("txtPostalCode", "P0L 1A0")
    + _span("txtPhone", "(705) 997-2375")
    + _span("txtFax", "(705) 997-2422")
    + '<input type="submit" name="ctl00$plcMain$btnReserves" value="Reserves" />'
    + _span("lblTCTitle", "Tribal Council affiliated with this First Nation")
    + '<a id="plcMain_hlTCNumber" href="TCMain.aspx?TC_NUMBER=1079&amp;lang=eng">1079</a>'
    + '<a id="plcMain_hlTCName" href="TCMain.aspx?TC_NUMBER=1079&amp;lang=eng">'
    "MUSHKEGOWUK COUNCIL</a>"
)
# Musqueam has a web site and no tribal council.
_MAIN_550 = _page(
    _span("txtBandName", "Musqueam")
    + _span("txtAddress", "6735 SALISH DRIVE, VANCOUVER, BC")
    + '<a id="plcMain_anchor1" href="https://www.musqueam.bc.ca/">Musqueam</a>'
)
_RESERVES_FR = _page(
    _span("txtBandName", "Attawapiskat")
    + '<table class="table" id="plcMain_dgReservesList"><tr><th scope="col">Numéro</th>'
    '<th scope="col">Nom</th><th>Emplacement</th><th>Hectares</th></tr><tr><td>'
    '<a id="plcMain_dgReservesList_hlRVNumber_0" href="RVDetail.aspx?RESERVE_NUMBER=06259">'
    "06259</a></td><td><a>ATTAWAPISKAT 91</a></td><td>165 KM W/O OF/DE JAMES BAY BOTH "
    "BANKS OF EKWAN RIVER</td><td>27040,10</td></tr><tr><td><a>06260</a></td><td>"
    "<a>ATTAWAPISKAT 91A</a></td><td>LEFT BANK OF ATTAWAPISKAT RIVER</td><td>1563</td></tr>"
    "</table>"
)
_GOVERNANCE = _page(
    _span("txtBandName", "Attawapiskat")
    + _span("txtAuthority", "Section 11 Band")
    + _span("txtElection", "Custom Electoral System")
    + _span("txtQuorum", "Please contact the First Nation for the quorum information.")
    + '<table id="plcMain_dgOfficialsList"><tr><th>Title</th><th>Surname</th>'
    "<th>Given Name</th><th>Appointment Date</th><th>Expiry Date</th></tr>"
    "<tr><td>Chief</td><td>KOOSTACHIN-METATAWABIN</td><td>JUDY (SYLVIA)</td>"
    "<td>08/30/2025</td><td>08/29/2028</td></tr></table>"
)
_GEOGRAPHY = _page(
    _span("txtBandName", "Musqueam")
    + _span("txtRegion", "BRITISH COLUMBIA")
    + _span("txtZone", "1")
    + _span("txtZoneDesc", "First Nation is located within 50 Km of the nearest service centre")
    + _span("txtSubZone", "")
    + _span("lblColon2", "Not applicable for this zone")
    + _span("txtEnvironmentalIndex", "B")
    + _span("txtCity", "Vancouver")
    + _span("txtCityCenter", "Vancouver")
    + '<a id="plcMain_lbReserve" href="#">MUSQUEAM 2</a>'
)


def _population(fr: bool = False) -> str:
    male, female = (
        ("Hommes inscrits", "Femmes inscrites")
        if fr
        else ("Registered Males", "Registered Females")
    )
    rows = ""
    values = {
        "OnReserve": ("On Own Reserve", 329, 334),
        "OnOtherReserves": ("On Other Reserves", 62, 61),
        "OnOwnCrownLand": ("On Own Crown Land", 0, 0),
        "OnOtherCrownLand": ("On Other Band Crown Land", 0, 0),
        "OnNoBandCrownLand": ("On No Band Crown Land", 0, 1),
        "OffReserve": ("Off Reserve", 339, 400),
    }
    for suffix, (label, men, women) in values.items():
        rows += (
            f"<tr><td>{_span(f'lblMales{suffix}', f'{male} {label}')}</td>"
            f"<td>{_span(f'txtMales{suffix}', str(men))}</td></tr>"
            f"<tr><td>{_span(f'lblFemales{suffix}', f'{female} {label}')}</td>"
            f"<td>{_span(f'txtFemales{suffix}', str(women))}</td></tr>"
        )
    total = "1\xa0526" if fr else "1,526"
    return _page(
        _span("txtBandName", "Musqueam")
        + _span("txtExtractDate", "septembre, 2026" if fr else "September, 2026")
        + f"<table>{rows}<tr><th>{_span('txtTotalPopulation', total)}</th></tr></table>"
    )


# cp1252, as the live file is; "NA" where no district applies.
_REGPOP_CSV = (
    "year,registry_group_number,registry_group_name EN,registry_group_name FR,region EN,"
    "Region FR,prov_terr EN,prov_terr FR,district EN,district FR,"
    "pop_on_reserve_crown_land_men,pop_on_reserve_crown_land_women,"
    "pop_on_reserve_crown_land_total,pop_off_reserve_men,pop_off_reserve_women,"
    "pop_off_reserve_total,pop_total_men,pop_total_women,pop_total_total\n"
    "2023,1,Abegweit,Abegweit,Atlantic,Atlantique,Prince Edward Island,"
    "Île-du-Prince-Édouard,NA,NA,117,115,232,78,98,176,195,213,408\n"
    "2023,550,Musqueam,Musqueam,British Columbia,Colombie-Britannique,British Columbia,"
    "Colombie-Britannique,NA,NA,403,405,808,319,364,683,722,769,1491\n"
    "2024,1,Abegweit,Abegweit,Atlantic,Atlantique,Prince Edward Island,"
    "Île-du-Prince-Édouard,NA,NA,118,116,234,80,99,179,198,215,413\n"
    "2024,550,Musqueam,Musqueam,British Columbia,Colombie-Britannique,British Columbia,"
    "Colombie-Britannique,NA,NA,396,399,795,321,380,701,717,779,1496\n"
    "2024,633,Oujé-Bougoumou Cree Nation,Oujé-Bougoumou Cree Nation,Quebec,Québec,Quebec,"
    "Québec,Quebec District,District du Québec,700,710,1410,150,160,310,850,870,1720\n"
).encode("cp1252")
_CSV_URL = (
    f"https://open.canada.ca/data/dataset/{constants.REGPOP_DATASET}/resource/"
    f"7a2b6d7b-e94a-4fa6-bd8e-f9c6f7798439/download/{constants.REGPOP_DATASET}.csv"
)
_BLOB_URL = (
    "https://opencanada.blob.core.windows.net/opengovprod/resources/"
    "7a2b6d7b/regpop.csv?se=2026-10-27&sig=x"
)


def _mock_regpop(httpx_mock) -> None:
    httpx_mock.add_response(
        url=constants.REGPOP_PACKAGE,
        json={
            "result": {
                "resources": [
                    {"format": "HTML", "url": "https://www.sac-isc.gc.ca/eng/1736535095412"},
                    {"format": "CSV", "url": _CSV_URL},
                ]
            }
        },
    )
    httpx_mock.add_response(url=_CSV_URL, status_code=302, headers={"location": _BLOB_URL})
    httpx_mock.add_response(url=_BLOB_URL, content=_REGPOP_CSV)


def _fnp(httpx_mock, page: str, band: int, html: str, lang: str = "en") -> None:
    httpx_mock.add_response(url=client.fnp_url(page, band, lang), text=html)


# --- search -------------------------------------------------------------------


async def test_search_reads_latest_year_and_folds_accents(httpx_mock):
    _mock_regpop(httpx_mock)
    result = await client.search_first_nations("ouje")
    assert result.year == 2024
    assert [f.band_number for f in result.first_nations] == [633]
    found = result.first_nations[0]
    assert found.province_code == "QC" and found.district == "Quebec District"
    assert found.registered_population == 1720 and found.on_reserve == 1410
    assert result.provenance.licence and "Open Government Licence" in result.provenance.licence


async def test_search_by_number_province_and_french(httpx_mock):
    _mock_regpop(httpx_mock)
    assert [f.name for f in (await client.search_first_nations("550")).first_nations] == [
        "Musqueam"
    ]
    island = await client.search_first_nations("", province="Île-du-Prince-Édouard", lang="fr")
    assert island.total_matched == 1
    assert island.first_nations[0].province == "Île-du-Prince-Édouard"
    assert island.first_nations[0].region == "Atlantique"
    assert island.first_nations[0].registered_population == 413
    everything = await client.search_first_nations("", limit=2)
    assert everything.total_matched == 3 and everything.returned_count == 2
    assert everything.provenance.limits == "First 2 of 3 matches."


async def test_search_rejects_unknown_province():
    with pytest.raises(InvalidInput, match="unknown province"):
        await client.search_first_nations("", province="Atlantis")


def test_csv_without_the_number_column_is_an_upstream_error():
    with pytest.raises(UpstreamError):
        client.parse_regpop_csv("year,name\n2024,Musqueam\n")


# --- profile ------------------------------------------------------------------


async def test_profile_reads_all_four_pages(httpx_mock):
    _fnp(httpx_mock, "main", 143, _MAIN_143, "fr")
    _fnp(httpx_mock, "reserves", 143, _RESERVES_FR, "fr")
    _fnp(httpx_mock, "governance", 143, _GOVERNANCE, "fr")
    _fnp(httpx_mock, "geography", 143, _GEOGRAPHY, "fr")
    profile = await client.get_first_nation_profile(143, lang="fr")
    assert profile.name == "Attawapiskat" and profile.phonetic_spelling == "a-ta-wah-pi-skat"
    assert profile.tribal_council is not None
    assert (profile.tribal_council.number, profile.tribal_council.name) == (
        1079,
        "MUSHKEGOWUK COUNCIL",
    )
    # French pages write hectares with a decimal comma.
    assert [(r.number, r.hectares) for r in profile.reserves] == [
        ("06259", 27040.1),
        ("06260", 1563.0),
    ]
    assert profile.total_reserve_hectares == 28603.1
    chief = profile.governance.officials[0]
    assert chief.title == "Chief" and chief.appointment_date == date(2025, 8, 30)
    assert profile.governance.council_quorum.startswith("Please contact")  # type: ignore[union-attr]
    assert profile.geography.sub_zone is None
    assert profile.geography.sub_zone_description == "Not applicable for this zone"
    assert profile.geography.most_populated_site == "MUSQUEAM 2"
    assert profile.profile_url.endswith("BAND_NUMBER=143&lang=fra")
    assert profile.provenance.licence and "gouvernement du Canada" in profile.provenance.licence


def test_main_page_with_a_web_site_and_no_council():
    from bs4 import BeautifulSoup

    main = client.parse_main(BeautifulSoup(_MAIN_550, "html.parser"))
    assert main["website"] == "https://www.musqueam.bc.ca/"
    assert main["tribal_council"] is None and main["phone"] is None


async def test_unknown_band_redirects_to_an_error_page(httpx_mock):
    httpx_mock.add_response(
        url=client.fnp_url("main", 99999, "en"),
        status_code=302,
        headers={"location": "http://www.ainc-inac.gc.ca/error/404.html"},
    )
    with pytest.raises(NotFound, match="redirects to an error page"):
        await client.get_first_nation_profile(99999)


async def test_page_without_a_name_is_a_layout_change(httpx_mock):
    _fnp(httpx_mock, "main", 550, _page("<p>Maintenance</p>"))
    with pytest.raises(UpstreamError, match="layout"):
        await client.get_first_nation_profile(550)


async def test_band_number_must_be_positive():
    with pytest.raises(InvalidInput):
        await client.get_first_nation_profile(0)


# --- registered population ----------------------------------------------------


async def test_population_monthly_and_yearly(httpx_mock):
    _fnp(httpx_mock, "population", 550, _population())
    _mock_regpop(httpx_mock)
    result = await client.get_registered_population(550)
    assert result.as_of == "September, 2026" and result.as_of_month == "2026-09"
    own = result.by_residence[0]
    assert (own.residence, own.label, own.men, own.women, own.total) == (
        "own_reserve",
        "On Own Reserve",
        329,
        334,
        663,
    )
    assert result.total == 1526 and result.men == 730 and result.women == 796
    assert [(a.year, a.total, a.on_reserve) for a in result.annual] == [
        (2023, 1491, 808),
        (2024, 1496, 795),
    ]
    assert result.annual_source == _CSV_URL
    assert result.provenance.licence and "Yearly figures" in result.provenance.licence


async def test_population_in_french_reads_no_break_space_totals(httpx_mock):
    _fnp(httpx_mock, "population", 550, _population(fr=True), "fr")
    _mock_regpop(httpx_mock)
    result = await client.get_registered_population(550, lang="fr")
    assert result.total == 1526 and result.as_of_month == "2026-09"
    assert result.by_residence[-1].label == "Off Reserve"
    assert "31 décembre" in result.notes[0]


def test_a_missing_sex_is_not_read_as_zero():
    from bs4 import BeautifulSoup

    # The off-reserve women's figure is blank: that residence has no total, and the
    # all-residence women's sum is unknown rather than short by 400.
    html = _population().replace(
        '<span id="plcMain_txtFemalesOffReserve" class="text">400</span>',
        '<span id="plcMain_txtFemalesOffReserve" class="text"></span>',
    )
    result = client.parse_population(BeautifulSoup(html, "html.parser"))
    off = result["by_residence"][-1]
    assert (off.men, off.women, off.total) == (339, None, None)
    assert result["men"] == 730 and result["women"] is None
    assert result["total"] == 1526


def test_to_int_reads_whole_numbers_only():
    assert client._to_int("1,526") == 1526
    assert client._to_int("1\xa0526") == 1526
    assert client._to_int("-3") == -3
    assert client._to_int("12.5") is None
    assert client._to_int("") is None


# --- long-term advisories -----------------------------------------------------

_LTDWA_PAGE = (
    '<html><body><main><div id="map"></div></main><script>\n'
    '\t\twindow["App_config"] = {\n\t\t"LANG": "EN",\n'
    '\t\t"LinkAjaxSource": "/DAM/DAM-ISC-SAC/DAM-WTR/STAGING/texte-text/'
    'lTDWA_map_data_1572010201618_eng.txt",\n\t\t"IconeVertPale": "/x.png"\n\t\t};\n'
    "</script></body></html>"
)
_MAP_URL = (
    "https://www.sac-isc.gc.ca/DAM/DAM-ISC-SAC/DAM-WTR/STAGING/texte-text/"
    "lTDWA_map_data_1572010201618_eng.txt"
)


def _lifted() -> dict:
    return {
        "AdvisoryID": "1711",
        "Region": "ATLANTIC",
        "CategoryID": 4,
        "WaterSystemName": "Morell Public Water System ",
        "CommunityNum": "001",
        "CommunityName": "Abegweit",
        "AdvisoryType": "Boil water advisory",
        "DateSet": "2009-04-29",
        "DateLTDWASet": "2010-04-29",
        "DateExpected": "2015-11-17",
        "PopulatioEstimated": "0 to 100 people",
        "CorrectiveMeasure": "New water treatment system\r\n",
        "LongPhase": "Complete",
        "Lattitude": 46.35793,
        "Longitude": -62.90262,
        "RecommendedEPHO": "No",
        "RecommendedEPHOIND": 0,
        "LongPhaseCode": "5",
    }


def _current() -> dict:
    return {
        "AdvisoryID": "1664",
        "Region": "ONTARIO",
        "CategoryID": 2,
        "WaterSystemName": "Neskantaga Public Water System ",
        "CommunityNum": "239",
        "CommunityName": "Neskantaga First Nation",
        "AdvisoryType": "Boil water advisory",
        "DateSet": "1995-02-01",
        "DateLTDWASet": "1996-02-01",
        "DateExpected": "",
        "PopulatioEstimated": "101 to 500 people",
        "CorrectiveMeasure": "Upgrade and expansion of existing treatment plant",
        "LongPhase": "Construction",
        "Lattitude": 52.20458,
        "Longitude": -88.01144,
        "RecommendedEPHO": "Yes",
        "RecommendedEPHOIND": 1,
        "LongPhaseCode": "4",
    }


_MAP = {
    "data": [
        {
            "CommunityNum": "001",
            "CommunityName": "Abegweit",
            "Region": "ATLANTIC",
            "Province": "Prince\xa0Edward Island",
            "ProvinceAcronym": "PE",
            "DataBiim": [],
            "LTDWACurrent": [],
            "LTDWALifted": [_lifted()],
        },
        {
            "CommunityNum": "239",
            "CommunityName": "Neskantaga First Nation",
            "Region": "ONTARIO",
            "Province": "Ontario",
            "ProvinceAcronym": "ON",
            "DataBiim": [],
            "LTDWACurrent": [_current()],
            "LTDWALifted": [],
        },
        {
            "CommunityNum": "1059",
            "CommunityName": "Daylu Dena Council",
            "Province": "",
            "ProvinceAcronym": "",
            "LTDWACurrent": None,
            "LTDWALifted": [],
        },
    ],
    "Ressources": [{"Key": "AdvisoryDate", "Value": "Date Advisory Set"}],
    "GenerateDate": "2026-10-20",
}


def _mock_map(httpx_mock, payload: dict | None = None) -> None:
    httpx_mock.add_response(url=constants.LTDWA_PAGE.format(lang="eng"), text=_LTDWA_PAGE)
    httpx_mock.add_response(url=_MAP_URL, text=json.dumps(payload or _MAP))


async def test_current_advisories_and_national_counts(httpx_mock):
    _mock_map(httpx_mock)
    result = await client.list_drinking_water_advisories()
    assert result.generated == date(2026, 10, 20)
    assert (result.current_count, result.lifted_count, result.communities_with_current) == (
        1,
        1,
        1,
    )
    assert result.data_url == _MAP_URL
    [advisory] = result.advisories
    assert advisory.band_number == 239 and advisory.kind == "boil_water"
    assert advisory.water_system == "Neskantaga Public Water System"
    assert advisory.date_lifted is None and advisory.recommended_to_lift is True
    assert result.provenance.as_of is not None


async def test_lifted_advisory_takes_its_lift_date_from_date_expected(httpx_mock):
    _mock_map(httpx_mock)
    result = await client.list_drinking_water_advisories("lifted", province="PE")
    [advisory] = result.advisories
    assert advisory.date_lifted == date(2015, 11, 17)
    assert advisory.province == "Prince Edward Island"
    assert advisory.corrective_measure == "New water treatment system"
    everything = await client.list_drinking_water_advisories("all", community="1")
    assert [a.community for a in everything.advisories] == ["Abegweit"]


async def test_map_file_name_is_read_from_the_page(httpx_mock):
    httpx_mock.add_response(
        url=constants.LTDWA_PAGE.format(lang="eng"), text="<html><main></main></html>"
    )
    with pytest.raises(UpstreamError, match="LinkAjaxSource"):
        await client.list_drinking_water_advisories()


def test_map_source_must_stay_on_the_isc_host():
    page = '"LinkAjaxSource": "https://evil.example/data.txt"'
    assert client.find_map_source(page, constants.LTDWA_PAGE.format(lang="eng")) is None
    assert client.find_map_source(_LTDWA_PAGE, constants.LTDWA_PAGE) == _MAP_URL


def test_map_without_data_is_an_upstream_error():
    with pytest.raises(UpstreamError):
        client.parse_map({"GenerateDate": "2026-10-20"})


# --- short-term advisories ----------------------------------------------------


def _table(rows: str) -> str:
    return (
        '<table class="wb-tables table"><thead><tr><th scope="col">First Nation<br></th>'
        "<th>Community</th><th>System name</th><th>Type of advisory</th><th>Date set</th>"
        "<th>Date revoked</th><th>Population</th><th>Infrastructure</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


_STDWA = _page(
    "<p>As of <span class='nowrap'>October 25, 2026</span>, there were 39&nbsp;short-term "
    "drinking water advisories in place in First Nations communities south of 60, "
    "excluding those in the British Columbia region.</p>"
    "<h3>Legend</h3><dl><dt>BWA:</dt><dd>boil water advisory</dd></dl>"
    '<section id="atla"><header><h3 class="mrgn-tp-sm">Atlantic</h3></header><div>'
    + _table(
        "<tr><td>Miawpukek</td><td>Conne River</td><td>Saint Anne's School Semi-Public Water "
        "System</td><td>DNC</td><td>2026/01/21</td><td>None</td><td>Unknown</td>"
        "<td>Yes</td></tr>"
        "<tr><td>Mushuau Innu First Nation</td><td>Natuashish</td><td>Natuashish Public "
        "Water System</td><td>BWA</td><td>2026/09/26</td><td>2026/10/01</td>"
        "<td>501-1000 people</td><td>Yes </td></tr>"
    )
    + "</div></section>"
    # The page keeps an "all lifted" variant of each region in a comment.
    + "<!-- <section><h3>Quebec</h3><table><tr><td>x</td></tr></table></section> -->"
    + '<section id="ont"><header><h3 class="mrgn-tp-sm">Ontario</h3></header><div>'
    + _table(
        "<tr><td>Biigtigong Nishnaabeg</td><td>Pic River</td><td>Pic River Public Water "
        "System</td><td>DWA</td><td>2026/10/24</td><td>None</td><td>101-500 people</td>"
        "<td>No</td></tr>"
    )
    + "</div></section>"
)


async def test_short_term_tables_by_region(httpx_mock):
    httpx_mock.add_response(url=constants.STDWA_PAGE.format(lang="eng"), text=_STDWA)
    result = await client.list_short_term_advisories()
    assert result.as_of == date(2026, 10, 25) and result.in_effect_count == 39
    assert [a.region for a in result.advisories] == ["ATLANTIC", "ATLANTIC", "ONTARIO"]
    first, revoked, ontario = result.advisories
    assert first.kind == "do_not_consume" and first.active and first.date_revoked is None
    assert revoked.date_revoked == date(2026, 10, 1) and not revoked.active
    assert revoked.isc_supported is True
    # "DWA" is not in the page's legend.
    assert ontario.code == "DWA" and ontario.kind == "other" and ontario.isc_supported is False
    nova_scotia = await client.list_short_term_advisories(province="NS", active_only=True)
    assert [a.first_nation for a in nova_scotia.advisories] == ["Miawpukek"]
    by_name = await client.list_short_term_advisories(community="pic river")
    assert by_name.total_matched == 1


def test_short_term_french_sentence():
    found, count = client.parse_as_of(
        "En date du 25 octobre 2026 , 39\xa0avis à court terme concernant la qualité de "
        "l'eau potable sont en vigueur"
    )
    assert found == date(2026, 10, 25) and count == 39


async def test_short_term_refuses_british_columbia():
    with pytest.raises(InvalidInput, match="First Nations Health Authority"):
        await client.list_short_term_advisories(province="BC")


# --- tools --------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [
        tools.isc_search_first_nations,
        tools.isc_get_first_nation_profile,
        tools.isc_get_registered_population,
        tools.isc_list_drinking_water_advisories,
        tools.isc_list_short_term_advisories,
    ],
)
def test_docstrings_are_bilingual(fn):
    doc = fn.__doc__ or ""
    assert "Use for:" in doc
    keywords = doc.split("Keywords:")[1].split("Mots-clés :")[0]
    assert len([k for k in keywords.split(",") if k.strip()]) >= 8
    mots = doc.split("Mots-clés :")[1]
    assert len([k for k in mots.split(",") if k.strip()]) >= 8


async def test_french_error_messages():
    with pytest.raises(InvalidInput) as error:
        await tools.isc_get_registered_population(0, lang="fr")
    assert "doit être un nombre positif" in str(error.value)
