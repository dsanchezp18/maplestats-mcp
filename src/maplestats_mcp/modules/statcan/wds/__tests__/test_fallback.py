"""The WDS fallback: a blocked www150 answered from another official source, labelled.

Everything is mocked at the HTTP layer, shaped like what the sources answered on
2026-11-17 (see each route's module docstring for the checks against recorded WDS
histories): www150's Cloudflare challenge, the CCEI SDMX space (flow list, structure with
references=all, SDMX-CSV 2.0 with the VECTOR attribute written both "v65201210" and
"65201210"), the Bank of Canada's Valet CPI group and observations (newest first), and the
Alberta Economic Dashboard's table list and rows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.sdmx_spaces import constants as space_constants
from maplestats_mcp.modules.statcan.wds import constants, fallback_book, tools
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared import substitution
from maplestats_mcp.shared.breaker import BREAKER, CircuitOpen
from maplestats_mcp.shared.errors import (
    CloudflareChallenge,
    InvalidInput,
    NotFound,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.usage import STATS

WWW150 = "www150.statcan.gc.ca"
# The lead of the fallback's own "Fix:". A challenge error carries a "Fix:" of its own
# as well (shared/blocked_hosts.py: do not retry, and what still works), so "Fix:" alone
# no longer says whether the fallback spoke.
FALLBACK_FIX = "found no other source for this request"
ANY_WDS = re.compile(r"https://www150\.statcan\.gc\.ca/.*")
CCEI = space_constants.SPACES["ccei"].base_url
LIST_URL = f"{CCEI}/dataflow/all/all/latest"
SHARED_LIST_URL = f"{space_constants.SPACES['stcshared'].base_url}/dataflow/all/all/latest"
STRUCT_URL = f"{CCEI}/dataflow/CA1.CCEI/DF_36100434/2.0?references=all"
INDEX_URL = f"{CCEI}/data/CA1.CCEI,DF_36100434,2.0/all?lastNObservations=1"
GDP_KEY = "M.CA.S.C-2017._T"
VALET = "https://www.bankofcanada.ca/valet"
VALET_FR = "https://www.banqueducanada.ca/valet"
ALBERTA = "https://api.economicdata.alberta.ca"
FIXTURES = Path(__file__).parent / "fixtures"


def _fn(t):
    return getattr(t, "fn", t)


@pytest.fixture(autouse=True)
def _fresh_state():
    STATS.fallbacks.clear()
    fallback_book.reset()
    yield
    STATS.fallbacks.clear()
    fallback_book.reset()


# ------------------------------------------------------------------ the block


def _block(httpx_mock, cloudflare_challenge) -> None:
    """Every www150 request is answered with the Cloudflare challenge."""
    httpx_mock.add_response(
        url=ANY_WDS, method=None, is_reusable=True, is_optional=True, **cloudflare_challenge
    )


def _open_breaker() -> None:
    for _ in range(config.get_breaker_failures()):
        BREAKER.record_failure(f"{WWW150}/wds", "server_error")


# ------------------------------------------------------------------ CCEI mocks


def _flow(agency: str, flow_id: str, version: str, name: str) -> dict:
    return {
        "id": flow_id,
        "version": version,
        "agencyID": agency,
        "name": name,
        "names": {"en": name},
        "annotations": [{"type": "NonProductionDataflow", "text": "true"}],
    }


FLOWS = {
    "data": {
        "dataflows": [
            _flow("STC", "DF_36100434", "1.0", "GDP (reference only)"),
            _flow("CA1.CCEI", "DF_36100434", "2.0", "Gross domestic product, monthly"),
            _flow("CA1.CCEI", "DF_17100009", "2.0", "Population estimates, quarterly"),
        ]
    }
}


def _lists(httpx_mock) -> None:
    """The flow lists of both spaces: CCEI first, then the shared space for a table not in it."""
    httpx_mock.add_response(url=LIST_URL, json=FLOWS, is_reusable=True, is_optional=True)
    httpx_mock.add_response(
        url=SHARED_LIST_URL, json=SHARED_FLOWS, is_reusable=True, is_optional=True
    )


SHARED_FLOWS = {
    "data": {"dataflows": [_flow("CA1.QOL", "DF_11100090", "1.0", "Poverty and low income")]}
}


def _codes(*pairs: tuple[str, str]) -> list[dict]:
    return [{"id": c, "name": n, "names": {"en": n}} for c, n in pairs]


def _dim(dim_id: str, position: int, codelist: str) -> dict:
    return {
        "id": dim_id,
        "position": position,
        "type": "Dimension",
        "conceptIdentity": f"urn:sdmx:org.sdmx.infomodel.conceptscheme.Concept=CA1:CS(1.0).{dim_id}",
        "localRepresentation": {
            "enumeration": f"urn:sdmx:org.sdmx.infomodel.codelist.Codelist=CA1:{codelist}(1.0)"
        },
    }


GDP_STRUCTURE = {
    "data": {
        "dataflows": [
            {
                **_flow("CA1.CCEI", "DF_36100434", "2.0", "Gross domestic product, monthly"),
                "description": (
                    "GDP at basic prices.<br/><br/><strong>Release date:</strong> 2026-10-30"
                    "<br/><br/><strong>How to cite:</strong>"
                ),
                "structure": "urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure="
                "CA1.CCEI:DSD_36100434(2.0)",
            }
        ],
        "dataStructures": [
            {
                "id": "DSD_36100434",
                "version": "2.0",
                "agencyID": "CA1.CCEI",
                "dataStructureComponents": {
                    "attributeList": {"attributes": [{"id": "UNIT_MEASURE"}, {"id": "VECTOR"}]},
                    "dimensionList": {
                        "dimensions": [
                            _dim("FREQ", 0, "CL_FREQ"),
                            _dim("REF_AREA", 1, "CL_AREA"),
                            _dim("ADJUSTMENT", 2, "CL_ADJ"),
                            _dim("PRICES", 3, "CL_PRICES"),
                            _dim("INDUSTRY", 4, "CL_NAICS"),
                        ],
                        "timeDimensions": [{"id": "TIME_PERIOD", "position": 5}],
                    },
                },
            }
        ],
        "conceptSchemes": [
            {
                "id": "CS",
                "version": "1.0",
                "agencyID": "CA1",
                "concepts": [
                    {"id": "FREQ", "name": "Frequency"},
                    {"id": "REF_AREA", "name": "Reference area"},
                    {"id": "ADJUSTMENT", "name": "Adjustment"},
                    {"id": "PRICES", "name": "Prices"},
                    {"id": "INDUSTRY", "name": "Industry"},
                ],
            }
        ],
        "codelists": [
            {
                "id": "CL_FREQ",
                "version": "1.0",
                "agencyID": "CA1",
                "codes": _codes(("M", "Monthly")),
            },
            {
                "id": "CL_AREA",
                "version": "1.0",
                "agencyID": "CA1",
                "codes": _codes(("CA", "Canada")),
            },
            {
                "id": "CL_ADJ",
                "version": "1.0",
                "agencyID": "CA1",
                "codes": _codes(("S", "Seasonally adjusted data, not calendar adjusted")),
            },
            {
                "id": "CL_PRICES",
                "version": "1.0",
                "agencyID": "CA1",
                "codes": _codes(("C-2017", "Chained (2017) dollars")),
            },
            {
                "id": "CL_NAICS",
                "version": "1.0",
                "agencyID": "CA1",
                "codes": _codes(("_T", "All industries"), ("621", "Ambulatory health care")),
            },
        ],
        "contentConstraints": [],
    }
}

CSV_HEADER = (
    "STRUCTURE,STRUCTURE_ID,ACTION,FREQ,REF_AREA,ADJUSTMENT,PRICES,INDUSTRY,TIME_PERIOD,"
    "OBS_VALUE,UNIT_MEASURE,OBS_STATUS,CONFID,QUALITY,UNIT_MULT,DECIMALS,"
    "MEASURE_TYPE_ENERGY,DGUID,VECTOR"
)


def _row(
    industry: str, period: str, value: str, vector: str, status: str = "A", quality: str = ""
) -> str:
    return (
        f"DATAFLOW,CA1.CCEI:DF_36100434(2.0),I,M,CA,S,C-2017,{industry},{period},{value},CAD,"
        f"{status},,{quality},6,0,NUMBER,2021A000011124,{vector}"
    )


def _csv(*rows: str) -> str:
    return "\n".join([CSV_HEADER, *rows]) + "\n"


# The index read: one observation per series, the vector written both ways.
INDEX_CSV = _csv(
    _row("_T", "2026-08", "2371635", "65201210"),
    _row("621", "2026-08", "73324", "v65201731"),
)
GDP_CSV = _csv(
    _row("_T", "2026-06", "2371177", "65201210"),
    _row("_T", "2026-07", "2371788", "65201210", status="P"),
    _row("_T", "2026-08", "2371635", "65201210", quality="E"),
)


def _ccei(httpx_mock, *, data_csv: str = GDP_CSV, key: str = GDP_KEY, n: int = 3) -> None:
    _lists(httpx_mock)
    httpx_mock.add_response(url=INDEX_URL, text=INDEX_CSV, is_reusable=True, is_optional=True)
    httpx_mock.add_response(url=STRUCT_URL, json=GDP_STRUCTURE, is_reusable=True, is_optional=True)
    httpx_mock.add_response(
        url=f"{CCEI}/data/CA1.CCEI,DF_36100434,2.0/{key}?lastNObservations={n}",
        text=data_csv,
        is_reusable=True,
        is_optional=True,
    )


# ------------------------------------------------------------------ Valet mocks


def _valet_group(host: str = VALET) -> dict:
    return {
        "groupDetail": {
            "name": "CPI_MONTHLY",
            "label": "Consumer Price Index",
            "description": "The monthly CPI group.",
            "groupSeries": {
                "V41690973": {"label": "Total CPI", "link": "x"},
                "V41690914": {"label": "Total CPI (seasonally adjusted)", "link": "x"},
                "CPI_TRIM": {"label": "CPI-trim", "link": "x"},
            },
        }
    }


def _valet_obs(name: str, label: str, values: dict[str, str]) -> dict:
    return {
        "seriesDetail": {
            name: {
                "label": label,
                "description": f"{label}.",
                "dimension": {"key": "d", "name": "Date"},
                "metadata": {"unit": "Index (2002=100)", "frequency": "Monthly"},
            }
        },
        # Newest first, as Valet answers.
        "observations": [{"d": d, name: {"v": v}} for d, v in sorted(values.items(), reverse=True)],
    }


def _valet(httpx_mock, *, host: str = VALET, n: int = 3) -> None:
    httpx_mock.add_response(
        url=f"{host}/groups/CPI_MONTHLY/json",
        json=_valet_group(),
        is_optional=True,
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=f"{host}/observations/V41690973/json?recent={n}",
        json=_valet_obs(
            "V41690973",
            "Total CPI",
            {"2026-08-01": "169.8", "2026-09-01": "170.0", "2026-10-01": "170.4"},
        ),
        is_optional=True,
    )
    httpx_mock.add_response(
        url=f"{host}/observations/V41690914/json?recent={n}",
        json=_valet_obs(
            "V41690914",
            "Total CPI (seasonally adjusted)",
            {"2026-08-01": "169.4", "2026-09-01": "170.0", "2026-10-01": "170.3"},
        ),
        is_optional=True,
    )


# ------------------------------------------------------------------ Alberta mocks

AB_TABLES = [
    {"tableName": "UnemploymentRates_14100287"},
    {"tableName": "EmploymentRate_14100287"},
    {"tableName": "Employment_14100287"},
    {"tableName": "CPI_18100004"},
]


def _alberta(httpx_mock, *, rows: list[dict] | None = None) -> None:
    httpx_mock.add_response(
        url=f"{ALBERTA}/api/chart-editor/data-tables",
        json=AB_TABLES,
        is_reusable=True,
        is_optional=True,
    )
    rows = rows or [
        {"Date": f"2026-{m:02d}-01T00:00:00", "GeoName": "Canada", "Value": v}
        for m, v in ((8, 6.4), (9, 6.5), (10, 6.7))
    ]
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(ALBERTA)}/data\?.*"),
        json=rows,
        is_reusable=True,
        is_optional=True,
    )


def _others(httpx_mock) -> None:
    """What a call reaching Valet and the Alberta dashboard also asks CCEI and Valet for."""
    _lists(httpx_mock)
    httpx_mock.add_response(
        url=f"{VALET}/groups/CPI_MONTHLY/json",
        json=_valet_group(),
        is_reusable=True,
        is_optional=True,
    )


# ------------------------------------------------------------------ the triggers


async def test_cloudflare_challenge_answers_from_ccei_and_says_so(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _ccei(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3)
    # The same output model as the primary, in the same order and units as WDS.
    assert [(o.ref_period.isoformat(), o.value) for o in result.series[0].observations] == [
        ("2026-06-01", 2371177.0),
        ("2026-07-01", 2371788.0),
        ("2026-08-01", 2371635.0),
    ]
    series = result.series[0]
    assert (series.product_id, series.coordinate, series.vector_id) == (
        36100434,
        "1.1.1.1.0.0.0.0.0.0",
        65201210,
    )
    assert series.observations[0].scale_multiplier == 10**6
    # The flags CCEI sends, as WDS words them: preliminary and use with caution.
    assert (
        series.observations[1].symbol == "preliminary" and series.observations[1].symbol_code == 1
    )
    assert (
        series.observations[2].status == "use with caution"
        and series.observations[2].status_code == 7
    )
    ctx = series.context
    assert ctx is not None
    assert ctx.table_id == "36-10-0434-01"
    assert ctx.citation is not None and "Vector v65201210. Released 2026-10-30." in ctx.citation
    assert ctx.series_title == (
        "Canada;Seasonally adjusted data, not calendar adjusted;Chained (2017) dollars;All industries"
    )
    assert ctx.scale == "millions" and ctx.last_period.isoformat() == "2026-08-01"  # type: ignore[union-attr]
    # Never silent: source, marker and caveats name the substitute and the reason.
    prov = result.provenance
    assert prov.substituted_for == "wds"
    assert prov.source == "statcan-sdmx-spaces"
    assert prov.url.startswith(f"{CCEI}/data/CA1.CCEI,DF_36100434,2.0/{GDP_KEY}")
    assert len(prov.caveats) == 1
    caveat = prov.caveats[0]
    assert "Web Data Service" in caveat and "blocked by a Cloudflare bot challenge" in caveat
    assert "CCEI SDMX space (api.statcan.gc.ca)" in caveat and "NonProductionDataflow" in caveat
    assert "Newest period: 2026-08-01" in caveat
    assert prov.licence is not None and "Statistics Canada Open Licence" in prov.licence
    assert STATS.fallbacks == {"ccei": 1}


async def test_an_open_breaker_alone_is_not_a_challenge(httpx_mock):
    # The breaker opens on timeouts and 5xx answers, not on a challenge: StatCan has not
    # said it is challenging the Web Data Service, so no substitute is read, even though
    # ones would answer.
    _open_breaker()
    _ccei(httpx_mock)
    calls = (
        lambda: _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3),
        lambda: _fn(tools.wds_get_data_from_cube_coord)(product_id=36100434, coordinate="1.1.1.1"),
        lambda: _fn(tools.wds_get_series_info)(vector_id=65201210),
        lambda: _fn(tools.wds_get_cube_metadata)(product_id=36100434),
    )
    for call in calls:
        with pytest.raises(CircuitOpen) as caught:
            await call()
        assert "Fix:" not in str(caught.value)
    assert httpx_mock.get_requests() == []
    assert STATS.fallbacks == {}


async def test_french_call_gets_french_caveat_and_labels(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _ccei(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(
        vector_ids=[65201210], latest_n=3, lang="fr"
    )
    caveat = result.provenance.caveats[0].replace(" ", " ")
    assert "Le Service de données Web de Statistique Canada" in caveat
    assert "bloqué par un défi anti-robot Cloudflare" in caveat
    assert "l'espace SDMX du CCIE de Statistique Canada (api.statcan.gc.ca)" in caveat
    assert "Période la plus récente : 2026-08-01" in caveat
    assert result.provenance.substituted_for == "wds" and result.provenance.lang == "fr"
    ctx = result.series[0].context
    assert ctx is not None and ctx.citation is not None
    assert ctx.citation.startswith("Statistique Canada. Tableau 36-10-0434-01")
    assert ctx.frequency == "Mensuelle" and ctx.scale == "millions"
    assert result.series[0].observations[1].symbol == "provisoire"
    assert result.series[0].observations[2].status == "à utiliser avec prudence"


async def test_substituted_cube_coord_and_series_info(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _ccei(httpx_mock, n=2)
    one = await _fn(tools.wds_get_data_from_cube_coord)(
        product_id="36-10-0434-01", coordinate="1.1.1.1", latest_n=2
    )
    assert one.series is None and one.vector_id == 65201210
    assert one.context is not None and one.context.table_id == "36-10-0434-01"
    assert one.provenance.substituted_for == "wds" and one.failed == []
    info = await _fn(tools.wds_get_series_info)(vector_id=65201210)
    assert (info.product_id, info.coordinate, info.vector_id) == (
        36100434,
        "1.1.1.1.0.0.0.0.0.0",
        65201210,
    )
    assert info.scalar_factor_code == 6 and info.frequency_code == 6
    assert (
        info.provenance.substituted_for == "wds" and info.provenance.source == "statcan-sdmx-spaces"
    )
    by_coord = await _fn(tools.wds_get_series_info)(product_id=36100434, coordinate="1.1.1.1")
    assert by_coord.vector_id == 65201210


async def test_a_series_whose_vector_is_spelled_differently_in_some_rows_is_still_served(
    httpx_mock, cloudflare_challenge
):
    # 36-10-0222's Alberta GDP wrote its VECTOR "v62788314" in some rows and left it out of
    # others (live 2026-11-18), which moves the attribute off the series onto the rows.
    _block(httpx_mock, cloudflare_challenge)
    mixed = _csv(
        _row("_T", "2026-06", "2371177", "65201210"),
        _row("_T", "2026-07", "2371788", "v65201210"),
        _row("_T", "2026-08", "2371635", ""),
    )
    _ccei(httpx_mock, data_csv=mixed)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3)
    assert [o.value for o in result.series[0].observations] == [2371177.0, 2371788.0, 2371635.0]


async def test_a_key_that_returns_another_vector_is_refused(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _ccei(httpx_mock, data_csv=_csv(_row("_T", "2026-08", "5", "777")))
    _others(httpx_mock)
    with pytest.raises(CloudflareChallenge, match="substitute sources failed"):
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3)
    assert STATS.fallbacks == {}


# ------------------------------------------------------------------ the other routes


async def test_cpi_vector_comes_from_valet_oldest_first(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _valet(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[41690973], latest_n=3)
    series = result.series[0]
    assert [(o.ref_period.isoformat(), o.value) for o in series.observations] == [
        ("2026-08-01", 169.8),
        ("2026-09-01", 170.0),
        ("2026-10-01", 170.4),
    ]
    assert (series.product_id, series.coordinate) == (18100004, "2.2.0.0.0.0.0.0.0.0")
    assert series.observations[-1].decimals == 1
    prov = result.provenance
    assert (prov.source, prov.substituted_for) == ("boc", "wds")
    assert "Valet API" in prov.caveats[0] and "Newest period: 2026-10-01" in prov.caveats[0]
    assert "Bank's terms of use" in prov.caveats[0]
    assert prov.licence is not None and "Bank of Canada" in prov.licence
    assert STATS.fallbacks == {"boc": 1}


async def test_valet_vector_without_a_known_table_is_served_with_the_gap_stated(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _valet(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[41690914], latest_n=3)
    series = result.series[0]
    assert (series.product_id, series.coordinate) == (0, "")
    assert series.context is not None and series.context.table_id == ""
    assert any("product_id is 0" in note for note in series.context.notes)
    assert series.observations[-1].value == 170.3


async def test_valet_citation_without_a_known_table_invents_no_table_number(
    httpx_mock, cloudflare_challenge
):
    """Vector 41690914 is not in the recorded book, so its table is unknown. The citation
    read "Table 00-00-0000-01", a number that does not exist; it now cites the Valet series
    that was read, and the StatCan vector it carries."""
    _block(httpx_mock, cloudflare_challenge)
    _valet(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[41690914], latest_n=3)
    cite = result.series[0].context.citation
    assert "00-00-0000" not in cite
    assert "Table" not in cite
    assert "Bank of Canada" in cite and "V41690914" in cite and "v41690914" in cite


async def test_valet_citation_without_a_known_table_in_french(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _others(httpx_mock)
    _valet(httpx_mock, host=VALET_FR)
    result = await _fn(tools.wds_get_data_from_vectors)(
        vector_ids=[41690914], latest_n=3, lang="fr"
    )
    cite = result.series[0].context.citation
    assert "00-00-0000" not in cite
    assert "Tableau" not in cite
    assert "Banque du Canada" in cite and "V41690914" in cite and "v41690914" in cite


async def test_valet_citation_with_a_known_table_is_unchanged(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _valet(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[41690973], latest_n=3)
    assert result.series[0].context.citation == (
        "Statistics Canada. Table 18-10-0004-01. Vector v41690973."
    )


async def test_valet_cpi_by_coordinate_in_french_uses_the_french_host(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _others(httpx_mock)
    _valet(httpx_mock, host=VALET_FR, n=2)
    result = await _fn(tools.wds_get_data_from_cube_coord)(
        product_id=18100004, coordinate="2.2", latest_n=2, lang="fr"
    )
    assert result.provenance.url.startswith(VALET_FR)
    assert result.observations[-1].value == 170.4
    assert "l'API Valet de la Banque du Canada" in result.provenance.caveats[0]


async def test_lfs_vector_comes_from_the_alberta_dashboard_with_filters(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _others(httpx_mock)
    _alberta(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[2062815], latest_n=3)
    series = result.series[0]
    assert [o.value for o in series.observations] == [6.4, 6.5, 6.7]
    assert (series.product_id, series.coordinate) == (14100287, "1.7.1.1.1.1.0.0.0.0")
    assert series.context is not None and series.context.unit == "Percent"
    assert any("seasonally adjusted" in n for n in series.context.notes)
    prov = result.provenance
    assert (prov.source, prov.substituted_for) == ("ab-economic", "wds")
    # Always filtered by column: GeoName, Sex and Age are all in the request.
    sent = [r.url for r in httpx_mock.get_requests() if r.url.path == "/data"]
    assert sent and dict(sent[0].params) == {
        "table": "UnemploymentRates_14100287",
        "GeoName": "Canada",
        "Sex": "Both sexes",
        "Age": "15 years and over",
    }
    assert STATS.fallbacks == {"ab_economic": 1}


async def test_several_coordinates_come_back_as_series_with_the_rest_in_failed(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _others(httpx_mock)
    _alberta(httpx_mock)
    result = await _fn(tools.wds_get_data_from_cube_coord)(
        product_id=14100287,
        coordinates=["10.7.1.1.1.1", "1.7.1.1.1.1", "3.7.1.1.1.1"],
        latest_n=3,
    )
    assert result.series is not None and result.observations == []
    assert [s.coordinate for s in result.series] == [
        "10.7.1.1.1.1.0.0.0.0",
        "1.7.1.1.1.1.0.0.0.0",
    ]
    assert [f.coordinate for f in result.failed] == ["3.7.1.1.1.1.0.0.0.0"]
    assert "cannot be matched to a series" in result.failed[0].reason
    assert "1 coordinate(s) returned no data" in (result.provenance.limits or "")


async def test_ccei_comes_before_valet_and_alberta(httpx_mock, cloudflare_challenge):
    # Vectors from three routes in one call keep their own sources; CCEI is tried first.
    _block(httpx_mock, cloudflare_challenge)
    _ccei(httpx_mock, n=2)
    _valet(httpx_mock, n=2)
    _alberta(httpx_mock)
    result = await _fn(tools.wds_get_data_from_vectors)(
        vector_ids=[2062815, 41690973, 65201210, 4242], latest_n=2
    )
    assert [s.vector_id for s in result.series] == [2062815, 41690973, 65201210]
    assert set(result.provenance.source.split("+")) == {
        "statcan-sdmx-spaces",
        "boc",
        "ab-economic",
    }
    assert len(result.provenance.caveats) == 3
    assert [f.vector_id for f in result.failed] == [4242]
    assert STATS.fallbacks == {"ccei": 1, "boc": 1, "ab_economic": 1}


async def test_a_vector_learned_from_wds_is_routed_when_wds_is_blocked(
    httpx_mock, cloudflare_challenge
):
    # 65201731 is in no seed: the process learned its table while WDS answered.
    fallback_book.learn(36100434, "1.1.1.1.4.0.0.0.0.0", 65201731)
    _block(httpx_mock, cloudflare_challenge)
    _ccei(
        httpx_mock,
        key="M.CA.S.C-2017.621",
        data_csv=_csv(_row("621", "2026-08", "73324", "v65201731")),
        n=1,
    )
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201731], latest_n=1)
    assert result.series[0].coordinate == "1.1.1.1.4.0.0.0.0.0"
    assert result.series[0].observations[0].value == 73324.0
    assert result.series[0].context is not None
    assert result.series[0].context.series_title is not None
    assert result.series[0].context.series_title.endswith("Ambulatory health care")


# ------------------------------------------------------------------ nothing to substitute


async def test_unplaced_vector_raises_its_own_error_with_what_works(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _valet(httpx_mock)
    with pytest.raises(CloudflareChallenge) as caught:
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[12345678], latest_n=3)
    text = str(caught.value)
    assert "Cloudflare bot challenge" in text  # the original message, unchanged
    assert "Fix: " in text and "no other source MapleStats reads carries this vector" in text
    assert "plan_query" in text
    assert STATS.fallbacks == {}


async def test_unmapped_coordinate_of_a_table_names_the_copies_that_exist(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _ccei(httpx_mock)
    _alberta(httpx_mock)
    with pytest.raises(CloudflareChallenge) as caught:
        await _fn(tools.wds_get_data_from_cube_coord)(
            product_id=36100434, coordinate="1.2.1.1", latest_n=2
        )
    text = str(caught.value)
    assert "Cloudflare bot challenge" in text and "Fix: " in text
    assert (
        "DF_36100434" in text and "sdmx_space_get_structure(flow='CA1.CCEI,DF_36100434,2.0'" in text
    )


async def test_alberta_copies_are_named_for_a_table_with_no_decoder(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _alberta(httpx_mock)
    with pytest.raises(UpstreamUnavailable, match="UnemploymentRates_14100287"):
        await _fn(tools.wds_get_data_from_cube_coord)(
            product_id=14100287, coordinate="1.1.1.1.1.1", latest_n=2
        )


async def test_cube_metadata_says_plainly_it_cannot_and_names_the_copy(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _alberta(httpx_mock)
    with pytest.raises(CloudflareChallenge) as caught:
        await _fn(tools.wds_get_cube_metadata)(product_id=36100434)
    text = str(caught.value)
    assert "member ids a coordinate is built from) is carried by no other source" in text
    assert "DF_36100434" in text
    assert "Solution" not in text


async def test_cube_metadata_in_french_gets_a_french_fix(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _alberta(httpx_mock)
    with pytest.raises(CloudflareChallenge) as caught:
        await _fn(tools.wds_get_cube_metadata)(product_id=17100009, lang="fr")
    text = str(caught.value).replace(" ", " ")
    assert "Solution : Les métadonnées de tableau du SDW" in text
    assert "DF_17100009" in text


async def test_a_transform_is_not_substituted(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _alberta(httpx_mock)
    with pytest.raises(CloudflareChallenge, match="published levels only"):
        await _fn(tools.wds_get_data_from_vectors)(
            vector_ids=[41690973], latest_n=3, transform="yoy_pct_change"
        )
    with pytest.raises(CloudflareChallenge, match="published levels only"):
        await _fn(tools.wds_get_data_from_cube_coord)(
            product_id=18100004, coordinate="2.2", latest_n=3, frequency="annual"
        )


async def test_a_substitute_that_is_down_too_is_reported(httpx_mock, cloudflare_challenge):
    _block(httpx_mock, cloudflare_challenge)
    httpx_mock.add_response(url=LIST_URL, status_code=503, is_reusable=True)
    httpx_mock.add_response(
        url=f"{VALET}/groups/CPI_MONTHLY/json", status_code=503, is_reusable=True
    )
    with pytest.raises(CloudflareChallenge, match="substitute sources failed"):
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3)
    assert STATS.fallbacks == {}


# ------------------------------------------------------------------ the switch


@pytest.mark.parametrize("value", ["0", "off", "false", "no"])
async def test_switch_off_leaves_the_original_error(
    httpx_mock, monkeypatch, value, cloudflare_challenge
):
    monkeypatch.setenv("MAPLE_STATCAN_FALLBACK", value)
    _block(httpx_mock, cloudflare_challenge)
    for call in (
        _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3),
        _fn(tools.wds_get_data_from_cube_coord)(product_id=36100434, coordinate="1.1.1.1"),
        _fn(tools.wds_get_series_info)(vector_id=65201210),
        _fn(tools.wds_get_cube_metadata)(product_id=36100434),
    ):
        with pytest.raises(CloudflareChallenge) as caught:
            await call
        assert FALLBACK_FIX not in str(caught.value)
    # Only www150 was asked, and nothing was read from any substitute.
    assert {r.url.host for r in httpx_mock.get_requests()} <= {WWW150}
    assert STATS.fallbacks == {}


async def test_switch_off_with_a_cloudflare_challenge(
    httpx_mock, cloudflare_challenge, monkeypatch
):
    monkeypatch.setenv("MAPLE_STATCAN_FALLBACK", "0")
    _block(httpx_mock, cloudflare_challenge)
    with pytest.raises(CloudflareChallenge) as caught:
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3)
    assert FALLBACK_FIX not in str(caught.value)
    assert {r.url.host for r in httpx_mock.get_requests()} == {WWW150}


# ------------------------------------------------------------------ what is not substituted


def _wds_error(status: int, message: str = "") -> dict:
    return {"status_code": status, "json": {"message": message} if message else {}}


@pytest.mark.parametrize(
    ("status", "error"),
    [(406, InvalidInput), (404, NotFound), (409, ValueError)],
)
async def test_an_ordinary_wds_answer_is_never_substituted(httpx_mock, status, error):
    httpx_mock.add_response(
        url=ANY_WDS, method=None, is_reusable=True, is_optional=True, **_wds_error(status, "No")
    )
    with pytest.raises(error):
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3)
    assert {r.url.host for r in httpx_mock.get_requests()} <= {WWW150}


async def test_a_server_error_is_not_a_block(httpx_mock):
    # Three attempts, all 503: UpstreamUnavailable, but not a paused host or a challenge.
    httpx_mock.add_response(
        url=ANY_WDS, method=None, status_code=503, is_reusable=True, is_optional=True
    )
    with pytest.raises(UpstreamUnavailable) as caught:
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=3)
    assert not isinstance(caught.value, CloudflareChallenge)
    assert STATS.fallbacks == {}
    assert {r.url.host for r in httpx_mock.get_requests()} == {WWW150}


async def test_bad_input_is_refused_before_any_substitute_is_tried(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    with pytest.raises(InvalidInput):
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[0], latest_n=3)
    with pytest.raises(InvalidInput):
        await _fn(tools.wds_get_data_from_cube_coord)(product_id=36100434, coordinate="a.b")
    with pytest.raises(InvalidInput):
        await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=0)
    # WDS was asked (the call's own prefetch), and nothing was read from a substitute.
    assert {r.url.host for r in httpx_mock.get_requests()} <= {WWW150}


# ------------------------------------------------------------------ caps


async def test_a_long_ccei_history_keeps_its_row_cap_and_says_so(httpx_mock, cloudflare_challenge):
    # 600 monthly rows come back; the CCEI client keeps the newest 500 per series.
    rows = [
        _row("_T", f"{1980 + i // 12}-{i % 12 + 1:02d}", str(1000 + i), "65201210")
        for i in range(600)
    ]
    _block(httpx_mock, cloudflare_challenge)
    _ccei(httpx_mock, data_csv=_csv(*rows), n=600)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[65201210], latest_n=600)
    assert len(result.series[0].observations) == space_constants.MAX_ROWS == 500
    assert result.series[0].observations[-1].value == 1599.0
    assert "newest 500 rows kept per series" in (result.provenance.limits or "")


async def test_a_long_alberta_history_is_cut_to_latest_n_and_noted(
    httpx_mock, cloudflare_challenge
):
    rows = [
        {
            "Date": f"{1980 + i // 12}-{i % 12 + 1:02d}-01T00:00:00",
            "GeoName": "Canada",
            "Value": 5.0 + i / 100,
        }
        for i in range(610)
    ]
    _block(httpx_mock, cloudflare_challenge)
    _others(httpx_mock)
    _alberta(httpx_mock, rows=rows)
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=[2062815], latest_n=12)
    assert len(result.series[0].observations) == 12
    assert result.series[0].observations[-1].value == pytest.approx(5.0 + 609 / 100)
    assert "most recent 12 of 610 matching rows" in (result.provenance.limits or "")


async def test_the_fallback_answers_at_most_twenty_series_and_says_which_it_left(
    httpx_mock, cloudflare_challenge
):
    _block(httpx_mock, cloudflare_challenge)
    _lists(httpx_mock)
    _valet(httpx_mock, n=1)
    asked = [41690973] + list(range(900_000, 900_024))
    result = await _fn(tools.wds_get_data_from_vectors)(vector_ids=asked, latest_n=1)
    assert [s.vector_id for s in result.series] == [41690973]
    over = [f for f in result.failed if "at most 20 series" in f.reason]
    assert [f.vector_id for f in over] == asked[20:]
    assert len(result.failed) == len(asked) - 1


# ------------------------------------------------------------------ the healthy path


def _wds_mocks(httpx_mock) -> None:
    fixture = json.loads((FIXTURES / "cube_coord_batch.json").read_text(encoding="utf-8"))
    envelopes = {
        "2.2.0.0.0.0.0.0.0.0": fixture["series_canada"],
        "14.2.0.0.0.0.0.0.0.0": fixture["series_ontario"],
    }

    def data(request: httpx.Request) -> httpx.Response:
        answer = []
        for pair in json.loads(request.content):
            copy = json.loads(json.dumps(envelopes[pair["coordinate"]]))
            points = copy["object"]["vectorDataPoint"]
            copy["object"]["vectorDataPoint"] = points[-pair["latestN"] :]
            answer.append(copy)
        return httpx.Response(200, json=answer)

    httpx_mock.add_callback(
        data, url=f"{constants.BASE_URL}getDataFromCubePidCoordAndLatestNPeriods", is_reusable=True
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCubeMetadata",
        json=[{"status": "SUCCESS", "object": fixture["cube_metadata"]}],
        is_reusable=True,
        is_optional=True,
    )

    def info(request: httpx.Request) -> httpx.Response:
        by_vector = {e["object"]["vectorId"]: e["object"] for e in envelopes.values()}
        answer = []
        for item in json.loads(request.content):
            obj = by_vector[item["vectorId"]]
            answer.append(
                {
                    "status": "SUCCESS",
                    "object": {
                        "responseStatusCode": 0,
                        "productId": obj["productId"],
                        "coordinate": obj["coordinate"],
                        "vectorId": obj["vectorId"],
                        "frequencyCode": 6,
                        "scalarFactorCode": 0,
                        "decimals": 1,
                        "memberUomCode": 17,
                        "SeriesTitleEn": "Consumer Price Index; All-items",
                    },
                }
            )
        return httpx.Response(200, json=answer)

    httpx_mock.add_callback(
        info, url=f"{constants.BASE_URL}getSeriesInfoFromVector", is_reusable=True, is_optional=True
    )


def _stable(result) -> dict:
    dumped = result.model_dump(mode="json")
    dumped["provenance"].pop("queried_at")
    return dumped


async def test_healthy_wds_answer_is_untouched_and_reads_only_wds(httpx_mock, monkeypatch):
    _wds_mocks(httpx_mock)
    on = await _fn(tools.wds_get_data_from_cube_coord)(
        product_id=18100004, coordinate="2.2", latest_n=2
    )
    requests_on = [r.url.host for r in httpx_mock.get_requests()]
    cache_module._caches.clear()
    monkeypatch.setenv("MAPLE_STATCAN_FALLBACK", "0")
    off = await _fn(tools.wds_get_data_from_cube_coord)(
        product_id=18100004, coordinate="2.2", latest_n=2
    )
    # Same output with the switch on or off, no marker, no caveat, WDS the only host read.
    assert _stable(on) == _stable(off)
    assert on.provenance.substituted_for is None and on.provenance.source == "statcan-wds"
    assert not on.provenance.caveats or all(
        "Web Data Service" not in c for c in on.provenance.caveats
    )
    assert set(requests_on) == {WWW150}
    assert STATS.fallbacks == {}
    # The series it served is remembered for later (fallback_book).
    assert fallback_book.locate_vector(41690973) is not None


async def test_what_wds_serves_is_learned_for_a_later_block(httpx_mock):
    _wds_mocks(httpx_mock)
    assert fallback_book.locate_vector(41691783) is None  # Ontario CPI: in no seed
    await _fn(tools.wds_get_data_from_cube_coord)(
        product_id=18100004, coordinates=["2.2", "14.2"], latest_n=1
    )
    learned = fallback_book.locate_vector(41691783)
    assert learned == fallback_book.Located(18100004, "14.2.0.0.0.0.0.0.0.0")
    assert fallback_book.locate_coordinate(18100004, "14.2.0.0.0.0.0.0.0.0") == 41691783


def test_only_the_challenge_triggers_a_fallback():
    assert substitution.is_blocked(CloudflareChallenge("x"))
    assert not substitution.is_blocked(CircuitOpen("paused"))
    assert not substitution.is_blocked(UpstreamUnavailable("a timeout"))
    assert not substitution.is_blocked(InvalidInput("bad"))
