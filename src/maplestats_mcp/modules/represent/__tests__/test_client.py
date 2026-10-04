"""Tests for modules/represent/client.py, shaped on live responses (2026-10-02)."""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.represent import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

BASE = "https://represent.opennorth.ca"
_HTML_404 = "<!DOCTYPE html><html><title>Not Found</title></html>"


def _url(path_and_query: str) -> re.Pattern[str]:
    return re.compile(re.escape(BASE + path_and_query))


def _boundary(set_slug: str, slug: str, name: str, external_id: str | None = None) -> dict:
    return {
        "url": f"/boundaries/{set_slug}/{slug}/",
        "name": name,
        "related": {"boundary_set_url": f"/boundary-sets/{set_slug}/"},
        "boundary_set_name": "Electoral district",
        "external_id": external_id if external_id is not None else "",
    }


def _rep(name: str, set_slug: str, office: str = "MLA", **extra) -> dict:
    return {
        "name": name,
        "district_name": "Edmonton-City Centre",
        "elected_office": office,
        "source_url": "https://example.test/members",
        "first_name": name.split()[0],
        "last_name": name.split()[-1],
        "party_name": "",
        "email": "",
        "url": "",
        "personal_url": "",
        "photo_url": "",
        "gender": "",
        "offices": [{"type": "legislature", "postal": "5th Floor"}],
        "extra": {},
        "representative_set_name": "A set",
        "related": {
            "representative_set_url": f"/representative-sets/{set_slug}/",
            "boundary_url": "/boundaries/x/y/",
        },
        **extra,
    }


def _set_detail(
    name: str, updated: str | None, licence: str | None = "https://licence.test"
) -> dict:
    return {
        "related": {"boundaries_url": "/boundaries/x/"},
        "name_plural": name,
        "name_singular": name,
        "authority": "Someone",
        "domain": "Alberta",
        "source_url": "https://source.test",
        "notes": "",
        "licence_url": licence,
        "last_updated": updated,
        "extent": [0, 0, 1, 1],
        "extra": {},
        "start_date": None,
        "end_date": None,
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


async def test_postcode_handles_absent_concordance_and_old_sets(httpx_mock):
    # Live T5J0N3: boundaries_concordance empty and representatives_concordance
    # key absent altogether (not null).
    httpx_mock.add_response(
        url=_url("/postcodes/T5J0N3/"),
        json={
            "code": "T5J0N3",
            "city": "EDMONTON",
            "province": "AB",
            "centroid": {"type": "Point", "coordinates": [-113.490305, 53.541236]},
            "boundaries_concordance": [],
            "boundaries_centroid": [
                _boundary(
                    "alberta-electoral-districts-2017",
                    "edmonton-city-centre",
                    "Edmonton-City Centre",
                    "29",
                ),
                _boundary(
                    "federal-electoral-districts-2003-representation-order",
                    "48012",
                    "Edmonton Centre",
                    "48012",
                ),
            ],
            "representatives_centroid": [
                _rep("David Shepherd", "alberta-legislature"),
                _rep("Andrew Knack", "edmonton-city-council", office="Mayor"),
            ],
        },
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/alberta-electoral-districts-2017/"),
        json=_set_detail(
            "Alberta electoral districts (2017)", "2018-03-01", "https://open.alberta.ca/licence"
        ),
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/federal-electoral-districts-2003-representation-order/"),
        json=_set_detail("Federal electoral districts (2003)", "2017-08-23"),
    )
    result = await client.lookup_postcode("t5j 0n3")
    assert result.postcode == "T5J0N3"
    assert result.centroid_latitude == pytest.approx(53.541236)
    assert result.centroid_longitude == pytest.approx(-113.490305)
    assert [b.matched_by for b in result.boundaries] == ["centroid", "centroid"]
    assert result.boundaries[0].external_id == "29"
    assert [r.level for r in result.representatives] == ["provincial", "municipal"]
    assert result.representatives[0].party_name is None  # "" read as absent
    assert result.representatives[0].offices[0].postal == "5th Floor"
    by_slug = {s.slug: s for s in result.boundary_sets}
    assert (
        by_slug["alberta-electoral-districts-2017"].licence_url == "https://open.alberta.ca/licence"
    )
    assert by_slug["federal-electoral-districts-2003-representation-order"].possibly_stale is True
    assert str(result.oldest_boundary_update) == "2017-08-23"
    assert any("more than 5 years" in n for n in result.notes)
    assert any("No federal representative matched" in n for n in result.notes)
    assert "60 requests per minute" in (result.provenance.limits or "")
    assert "unverified" in (result.provenance.limits or "")


async def test_postcode_with_sets_filter_drops_representative_keys(httpx_mock):
    # Live: ?sets=... removes both representatives_* keys from the response.
    httpx_mock.add_response(
        url=_url("/postcodes/H3B4W8/?sets=federal-electoral-districts"),
        json={
            "code": "H3B4W8",
            "city": "MONTREAL",
            "province": "QC",
            "centroid": {"type": "Point", "coordinates": [-73.571571, 45.497394]},
            "boundaries_concordance": [
                _boundary("federal-electoral-districts", "24054", "Ville-Marie", "24054")
            ],
            "boundaries_centroid": [],
        },
    )
    result = await client.lookup_postcode(
        "H3B 4W8", sets="federal-electoral-districts", include_set_details=False
    )
    assert result.representatives == []
    assert result.boundaries[0].matched_by == "concordance"
    assert result.boundary_sets == []
    assert "include_set_details" in (result.provenance.coverage or "")


async def test_postcode_unknown_is_not_found_and_bad_format_invalid(httpx_mock):
    httpx_mock.add_response(
        url=_url("/postcodes/Z9Z9Z9/"),
        status_code=404,
        text=_HTML_404,
        headers={"content-type": "text/html"},
    )
    with pytest.raises(NotFound, match="Z9Z9Z9"):
        await client.lookup_postcode("Z9Z9Z9")
    with pytest.raises(InvalidInput):
        await client.lookup_postcode("12345")
    with pytest.raises(InvalidInput):
        await client.lookup_postcode("T5J0N3", sets="Bad Slug!")


async def test_french_errors(httpx_mock):
    httpx_mock.add_response(
        url=_url("/postcodes/Z9Z9Z9/"),
        status_code=404,
        text=_HTML_404,
        headers={"content-type": "text/html"},
    )
    with pytest.raises(NotFound, match=r"^Aucune correspondance trouvée\xa0: represent\xa0: le"):
        await client.lookup_postcode("Z9Z9Z9", lang="fr")
    with pytest.raises(InvalidInput, match="postcode doit avoir la forme"):
        await client.lookup_postcode("12345", lang="fr")
    with pytest.raises(InvalidInput, match="latitude doit être entre"):
        await client.lookup_point(200, 0, lang="fr")
    with pytest.raises(InvalidInput, match="donnez au moins"):
        await client.search_representatives(lang="fr")
    with pytest.raises(InvalidInput, match=r"^represent: offset must be 0 or more\.$"):
        await client.search_representatives(name="x", offset=-1)


async def test_point_lookup_reports_totals_and_empty_outside_canada(httpx_mock):
    httpx_mock.add_response(
        url=_url("/boundaries/?contains=0.0%2C0.0&limit=100"),
        json={"objects": [], "meta": {"total_count": 0, "next": None}},
    )
    httpx_mock.add_response(
        url=_url("/representatives/?point=0.0%2C0.0&limit=100"),
        json={"objects": [], "meta": {"total_count": 0, "next": None}},
    )
    result = await client.lookup_point(0.0, 0.0)
    assert result.boundaries == []
    assert result.representatives == []
    assert any("No boundary matched" in n for n in result.notes)
    with pytest.raises(InvalidInput):
        await client.lookup_point(95.0, 0.0)
    with pytest.raises(InvalidInput):
        await client.lookup_point(float("nan"), 0.0)


async def test_point_lookup_with_details(httpx_mock):
    httpx_mock.add_response(
        url=_url("/boundaries/?contains=45.524%2C-73.596&limit=100"),
        json={
            "objects": [
                _boundary(
                    "federal-electoral-districts-2023-representation-order",
                    "24053",
                    "Outremont",
                    "24053",
                )
            ],
            "meta": {"total_count": 1, "next": None},
        },
    )
    httpx_mock.add_response(
        url=_url("/representatives/?point=45.524%2C-73.596&limit=100"),
        json={
            "objects": [_rep("Rachel Bendayan", "house-of-commons", office="MP")],
            "meta": {"total_count": 1, "next": None},
        },
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/federal-electoral-districts-2023-representation-order/"),
        json=_set_detail(
            "Federal electoral districts (2023)",
            "2024-05-01",
            "https://open.canada.ca/en/open-government-licence-canada",
        ),
    )
    result = await client.lookup_point(45.524, -73.596)
    assert result.representatives[0].level == "federal"
    assert (result.boundary_sets[0].licence_url or "").endswith("open-government-licence-canada")
    assert result.boundary_sets[0].detail_loaded is True
    assert result.boundaries[0].matched_by == "point"


async def test_point_bad_request_maps_to_invalid_input(httpx_mock):
    # Live: a malformed point answers 400 with plain text.
    httpx_mock.add_response(
        url=_url("/boundaries/?contains=1.0%2C2.0&limit=100"),
        status_code=400,
        text="Invalid latitude,longitude",
    )
    with pytest.raises(InvalidInput, match="rejected"):
        await client.lookup_point(1.0, 2.0)


async def test_rate_limit_503_is_unavailable(httpx_mock):
    httpx_mock.add_response(url=_url("/postcodes/T5J0N3/"), status_code=503, is_reusable=True)
    with pytest.raises(UpstreamUnavailable, match="60"):
        await client.lookup_postcode("T5J0N3")


async def test_search_requires_a_filter():
    with pytest.raises(InvalidInput, match="at least one"):
        await client.search_representatives()
    with pytest.raises(InvalidInput):
        await client.search_representatives(name="x", limit=0)


async def test_search_plain_uses_upstream_paging(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representatives/?name__icontains=bendayan&limit=2&offset=0"),
        json={
            "objects": [_rep("Rachel Bendayan", "house-of-commons", office="MP")],
            "meta": {"total_count": 1, "next": None},
        },
    )
    result = await client.search_representatives(name="bendayan", limit=2)
    assert result.total_count == 1
    assert result.has_more is False
    assert result.representatives[0].level == "federal"


async def test_search_unknown_set_is_not_found(httpx_mock):
    # Live: /representatives/nosuchset/ answers 200 with an empty list, so the
    # set itself is checked first.
    httpx_mock.add_response(
        url=_url("/representative-sets/nosuchset/"), status_code=404, text=_HTML_404
    )
    with pytest.raises(NotFound):
        await client.search_representatives(representative_set="nosuchset", name="a")


async def test_search_level_conflict_with_set():
    with pytest.raises(InvalidInput, match="not federal"):
        await client.search_representatives(
            level="federal", representative_set="alberta-legislature"
        )


async def test_search_provincial_merges_legislatures(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representative-sets/?limit=1000"),
        json={
            "objects": [
                {
                    "name": "Legislative Assembly of Alberta",
                    "url": "/representative-sets/alberta-legislature/",
                    "data_url": "https://x",
                    "related": {
                        "boundary_set_url": "/boundary-sets/alberta-electoral-districts-2017/"
                    },
                },
                {
                    "name": "Assemblée nationale du Québec",
                    "url": "/representative-sets/quebec-assemblee-nationale/",
                    "data_url": "https://y",
                    "related": {},
                },
                {
                    "name": "Edmonton City Council",
                    "url": "/representative-sets/edmonton-city-council/",
                    "data_url": "https://z",
                    "related": {},
                },
            ],
            "meta": {"total_count": 3, "next": None},
        },
    )
    httpx_mock.add_response(
        url=_url("/representatives/alberta-legislature/?party_name__icontains=new&limit=1000"),
        json={
            "objects": [_rep("David Shepherd", "alberta-legislature")],
            "meta": {"total_count": 1},
        },
    )
    httpx_mock.add_response(
        url=_url(
            "/representatives/quebec-assemblee-nationale/?party_name__icontains=new&limit=1000"
        ),
        json={"objects": [], "meta": {"total_count": 0}},
    )
    result = await client.search_representatives(party="new", level="provincial", limit=5)
    assert [r.name for r in result.representatives] == ["David Shepherd"]
    assert result.total_count == 1


async def test_search_municipal_drops_federal_and_provincial_rows(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representatives/?elected_office__icontains=m&limit=1000&offset=0"),
        json={
            "objects": [
                _rep("Rachel Bendayan", "house-of-commons", office="MP"),
                _rep("David Shepherd", "alberta-legislature"),
                _rep("Andrew Knack", "edmonton-city-council", office="Mayor"),
            ],
            "meta": {"total_count": 3, "next": None},
        },
    )
    result = await client.search_representatives(office="m", level="municipal")
    assert [r.name for r in result.representatives] == ["Andrew Knack"]


async def test_list_boundary_sets_loads_details_the_list_lacks(httpx_mock):
    # Live: the list rows carry only name/domain/urls; licence_url and
    # last_updated exist on the detail endpoint alone.
    httpx_mock.add_response(
        url=_url("/boundary-sets/?limit=2&offset=0&name__icontains=ward"),
        json={
            "objects": [
                {
                    "url": "/boundary-sets/calgary-wards/",
                    "related": {},
                    "name": "Calgary wards",
                    "domain": "Calgary, AB",
                },
                {
                    "url": "/boundary-sets/toronto-wards-2018/",
                    "related": {},
                    "name": "Toronto wards",
                    "domain": "Toronto, ON",
                },
            ],
            "meta": {"total_count": 94, "next": "/boundary-sets/?limit=2&offset=2"},
        },
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/calgary-wards/"), json=_set_detail("Calgary wards", "2021-09-01")
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/toronto-wards-2018/"),
        json=_set_detail("Toronto wards", None, licence=None),
    )
    result = await client.list_boundary_sets(name="ward", limit=2)
    assert result.total_count == 94
    assert result.has_more is True
    assert result.sets[0].licence_url == "https://licence.test"
    assert result.sets[1].last_updated is None
    assert result.sets[0].name == "Calgary wards"
    assert str(result.oldest_last_updated) == "2021-09-01"


async def test_list_boundary_sets_without_details_flags_it(httpx_mock):
    httpx_mock.add_response(
        url=_url("/boundary-sets/?limit=1&offset=0"),
        json={
            "objects": [
                {
                    "url": "/boundary-sets/acton-vale-districts/",
                    "related": {},
                    "name": "Acton Vale districts",
                    "domain": "Acton Vale, QC",
                }
            ],
            "meta": {"total_count": 524, "next": "/boundary-sets/?limit=1&offset=1"},
        },
    )
    result = await client.list_boundary_sets(limit=1, with_details=False)
    assert result.sets[0].detail_loaded is False
    assert result.sets[0].licence_url is None
    assert result.notes


async def test_list_representative_sets_classifies_levels(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representative-sets/?limit=1000"),
        json={
            "objects": [
                {
                    "name": "House of Commons",
                    "url": "/representative-sets/house-of-commons/",
                    "data_url": "",
                    "related": {},
                },
                {
                    "name": "Legislative Assembly of Ontario",
                    "url": "/representative-sets/ontario-legislature/",
                    "data_url": "",
                    "related": {},
                },
                {
                    "name": "Toronto City Council",
                    "url": "/representative-sets/toronto-city-council/",
                    "data_url": "",
                    "related": {"boundary_set_url": "/boundary-sets/toronto-wards-2018/"},
                },
            ],
            "meta": {"total_count": 3, "next": None},
        },
    )
    result = await client.list_representative_sets()
    assert [s.level for s in result.sets] == ["federal", "municipal", "provincial"]
    assert result.sets[1].boundary_set == "toronto-wards-2018"


def test_level_of():
    assert client.level_of("house-of-commons") == "federal"
    assert client.level_of("nova-scotia-legislature") == "provincial"
    assert client.level_of("quebec-assemblee-nationale") == "provincial"
    assert client.level_of("conseil-municipal-de-laval") == "municipal"
    assert client.level_of(None) is None


async def test_lang_must_be_en_or_fr():
    with pytest.raises(InvalidInput, match="lang"):
        await client.lookup_postcode("T5J0N3", lang="es")  # type: ignore[arg-type]


# Live 2026-10-03, K2J6B6 with sets=federal-electoral-districts: the response
# keeps code, city, province, centroid and both boundaries_* keys but no
# representatives_* key, because that slug is the superseded 2013 order.
_K2J6B6_OLD_ORDER = {
    "code": "K2J6B6",
    "city": "NEPEAN",
    "province": "ON",
    "centroid": {"type": "Point", "coordinates": [-75.750606, 45.274051]},
    "boundaries_concordance": [],
    "boundaries_centroid": [
        {
            "url": "/boundaries/federal-electoral-districts/35064/",
            "name": "Nepean",
            "related": {"boundary_set_url": "/boundary-sets/federal-electoral-districts/"},
            "boundary_set_name": "Federal electoral district",
            "external_id": "35064",
        }
    ],
}
_FED_2013_DETAIL = {
    "related": {"boundaries_url": "/boundaries/federal-electoral-districts/"},
    "name_plural": "Federal electoral districts",
    "name_singular": "Federal electoral district",
    "authority": "Her Majesty the Queen in Right of Canada",
    "domain": "Canada",
    "source_url": "https://open.canada.ca/data/en/dataset/5f1c2e06-405a-4357-9566-872e69ee2ade",
    "notes": "",
    "licence_url": "https://open.canada.ca/en/open-government-licence-canada",
    "last_updated": "2017-08-23",
    "extent": [-141.0, 41.6, -52.5, 89.9],
    "extra": {"division_id": "ocd-division/country:ca"},
    "start_date": None,
    "end_date": None,
}


async def test_old_federal_order_is_flagged_superseded_and_empty_reps_explained(httpx_mock):
    httpx_mock.add_response(
        url=_url("/postcodes/K2J6B6/?sets=federal-electoral-districts"), json=_K2J6B6_OLD_ORDER
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/federal-electoral-districts/"), json=_FED_2013_DETAIL
    )
    result = await client.lookup_postcode("K2J6B6", sets="federal-electoral-districts")
    assert result.representatives == []
    [info] = result.boundary_sets
    assert info.superseded_by == "federal-electoral-districts-2023-representation-order"
    # The 2017 date is explained as a superseded order, not reported as stale.
    assert not any("more than 5 years" in n for n in result.notes)
    assert any("Superseded" in n and "2013 order" in n for n in result.notes)
    assert any("Drop sets" in n for n in result.notes)
    assert any("federal-electoral-districts (no year) is the 2013 order" in n for n in result.notes)


async def test_postcode_notes_follow_lang_fr(httpx_mock):
    httpx_mock.add_response(
        url=_url("/postcodes/K2J6B6/?sets=federal-electoral-districts"), json=_K2J6B6_OLD_ORDER
    )
    httpx_mock.add_response(
        url=_url("/boundary-sets/federal-electoral-districts/"), json=_FED_2013_DETAIL
    )
    result = await client.lookup_postcode("K2J6B6", sets="federal-electoral-districts", lang="fr")
    assert any("ordonnance de 2013" in n for n in result.notes)
    assert any("Retirer sets" in n for n in result.notes)
    assert not any("order)" in n or "Drop sets" in n for n in result.notes)


def _party_rep(name: str, set_slug: str, party: str) -> dict:
    return _rep(name, set_slug, party_name=party)


async def test_party_alias_ndp_matches_provincial_long_names_locally(httpx_mock):
    # Live party_name values (2026-10-03): Alberta "Alberta New Democratic
    # Party", Quebec none; "NDP" alone matched 0 provincial members before.
    httpx_mock.add_response(
        url=_url("/representative-sets/?limit=1000"),
        json={
            "objects": [
                {
                    "name": "Legislative Assembly of Alberta",
                    "url": "/representative-sets/alberta-legislature/",
                    "data_url": "https://x",
                    "related": {},
                },
                {
                    "name": "Assemblée nationale du Québec",
                    "url": "/representative-sets/quebec-assemblee-nationale/",
                    "data_url": "https://y",
                    "related": {},
                },
            ],
            "meta": {"total_count": 2, "next": None},
        },
    )
    # No party_name__icontains upstream: the alias is matched here.
    httpx_mock.add_response(
        url=re.compile(re.escape(BASE + "/representatives/alberta-legislature/?limit=1000") + "$"),
        json={
            "objects": [
                _party_rep("David Shepherd", "alberta-legislature", "Alberta New Democratic Party"),
                _party_rep("Danielle Smith", "alberta-legislature", "United Conservative Party"),
            ],
            "meta": {"total_count": 2},
        },
    )
    httpx_mock.add_response(
        url=re.compile(
            re.escape(BASE + "/representatives/quebec-assemblee-nationale/?limit=1000") + "$"
        ),
        json={
            "objects": [
                _party_rep(
                    "François Legault", "quebec-assemblee-nationale", "Coalition avenir Québec"
                )
            ],
            "meta": {"total_count": 1},
        },
    )
    result = await client.search_representatives(party="N.D.P.", level="provincial")
    assert [r.name for r in result.representatives] == ["David Shepherd"]
    assert result.total_count == 1
    assert any("NDP, New Democratic" in n for n in result.notes)
    assert any("Saskatchewan" in n for n in result.notes)


async def test_party_alias_without_level_merges_one_query_per_form(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representatives/?party_name__icontains=NDP&limit=1000"),
        json={
            "objects": [_party_rep("Leah Gazan", "house-of-commons", "NDP")],
            "meta": {"total_count": 1, "next": None},
        },
    )
    httpx_mock.add_response(
        url=_url("/representatives/?party_name__icontains=New+Democratic&limit=1000"),
        json={
            "objects": [
                _party_rep("David Shepherd", "alberta-legislature", "Alberta New Democratic Party")
            ],
            "meta": {"total_count": 1, "next": None},
        },
    )
    result = await client.search_representatives(party="npd", lang="fr")
    assert [r.name for r in result.representatives] == ["Leah Gazan", "David Shepherd"]
    assert result.total_count == 2
    # French notes carry no-break spaces inside the guillemets.
    assert any("«\xa0npd\xa0»" in n for n in result.notes)
    assert (result.provenance.coverage or "").startswith("les fiches d'élus sont extraites")
    assert (result.provenance.licence or "").startswith("L'API Represent d'Open North")


async def test_single_form_alias_goes_upstream(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representatives/?party_name__icontains=Coalition+avenir+Qu"),
        json={
            "objects": [
                _party_rep(
                    "François Legault", "quebec-assemblee-nationale", "Coalition avenir Québec"
                )
            ],
            "meta": {"total_count": 1, "next": None},
        },
    )
    result = await client.search_representatives(party="caq")
    assert result.total_count == 1


async def test_search_no_match_and_level_notes_follow_lang(httpx_mock):
    httpx_mock.add_response(
        url=_url("/representatives/?name__icontains=zzzqqq&limit=20&offset=0"),
        json={"objects": [], "meta": {"total_count": 0, "next": None}},
    )
    result = await client.search_representatives(name="zzzqqq", lang="fr")
    assert result.notes == [
        "Aucun élu ne correspond. La recherche porte sur une sous-chaîne, sans égard à la casse."
    ]


def test_limiter_has_no_burst_above_60_a_minute():
    assert client.constants.RATE_LIMIT_CAPACITY == 1.0
    assert client.constants.RATE_LIMIT_PER_SECOND * 60 <= client.constants.RATE_LIMIT_PER_MINUTE
