"""Tests for epcor/client.py, shaped around page structures and file
naming quirks confirmed live 2026-09-22 (see the module docstring).
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.epcor import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable

_DAILY_PAGE = """
<table><tr><td></td>
<td><span id="DateLabel1">SEP-15</span></td><td><span id="DateLabel2">SEP-16</span></td></tr>
<tr><td><span id="ZoneLabel">Rossdale</span></td></tr>
<tr><td><span id="HardnessLabel1">178</span></td><td><span id="HardnessLabel2">182</span></td></tr>
<tr><td><span id="phLabel1">7.9</span></td><td><span id="phLabel2">7.8</span></td></tr>
<tr><td><span id="TempLabel1">--</span></td><td><span id="TempLabel2">13.9</span></td></tr>
<tr><td><span id="ChlorineLabel1">2.20</span></td><td><span id="ChlorineLabel2">2.25</span></td></tr>
<tr><td><span id="SodaDoseLabel1">1.17</span></td><td><span id="SodaDoseLabel2">0.000</span></td></tr>
</table>
"""


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def test_infer_label_date_rolls_back_across_new_year():
    assert client.infer_label_date("SEP-15", date(2026, 9, 22)) == date(2026, 9, 15)
    assert client.infer_label_date("DEC-30", date(2027, 1, 2)) == date(2026, 12, 30)
    assert client.infer_label_date("garbage", date(2026, 9, 22)) is None


def test_parse_daily_page_handles_missing_values():
    readings = client.parse_daily_page(_DAILY_PAGE, date(2026, 9, 22))
    assert [r.date_label for r in readings] == ["SEP-15", "SEP-16"]
    assert readings[0].total_hardness == 178
    assert readings[0].temperature is None
    assert readings[1].caustic_soda_dose == 0
    assert readings[0].alkalinity is None


def test_parse_daily_page_without_dates_raises():
    with pytest.raises(UpstreamError):
        client.parse_daily_page("<html>maintenance</html>", date(2026, 9, 22))


async def test_get_daily_water_quality(httpx_mock):
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=Rossdale", text=_DAILY_PAGE)
    result = await client.get_daily_water_quality("rossdale")
    assert result.plant_name == "Rossdale"
    assert result.units["ph"] == "pH"
    assert len(result.readings) == 2


async def test_unknown_plant_raises():
    with pytest.raises(InvalidInput):
        await client.get_daily_water_quality("gold_bar")  # type: ignore[arg-type]


# Trimmed from a live GET of apps.epcor.ca/DailyWaterQuality/Default.aspx?zone=Rossdale
# on 2026-10-03 (3 of 7 days kept, measure rows complete). Shape kept as served: CRLF
# line endings, leading blank lines, no BOM, UTF-8 "°C"/"µS/cm" in row titles, tag
# comments around every value span, and two index-less spans (errorLabel, ZoneLabel)
# that the parser must skip. Days straddle a month end (SEP-30, OCT-01, OCT-02).
_LIVE_ROWS = [
    ("Date", ["SEP-30", "OCT-01", "OCT-02"]),
    ("Hardness", ["174", "173", "173"]),
    ("ph", ["7.7", "7.7", "7.8"]),
    ("Temp", ["11.5", "10.8", "10.5"]),
    ("Chlorine", ["2.26", "2.18", "2.18"]),
    ("Alkalinity", ["112", "113", "111"]),
    ("Conductivity", ["377", "375", "369"]),
    ("SodaDose", ["0.000", "0.000", "0.000"]),
]
_LIVE_PAGE = "\r\n".join(
    [
        "",
        "",
        (
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
            '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
        ),
        '<html xmlns="http://www.w3.org/1999/xhtml" >',
        '<head id="Head1"><title>',
        "\tEPCOR - Daily Water Quality Reports",
        "</title></head>",
        "<body>",
        '    <form method="post" action="./Default.aspx?zone=Rossdale" id="form1">',
        '        <span id="errorLabel"><font color="Red"></font></span>',
        '        <table border="1px" cellspacing="0">',
        '            <tr style="background-color: #d1f2f7">',
        '                <td class="title" width="200">',
        '                    <span id="ZoneLabel">Rossdale</span>',
        "                    Zone <sup>(1)</sup></td>",
        "            </tr>",
        '            <tr><td class="title" width="200">Temperature (°C)</td></tr>',
        '            <tr><td class="title" width="200">Conductivity (µS/cm)</td></tr>',
    ]
    + [
        '                <td width="65">\r\n'
        f"                    <!-- tag={prefix.lower()}{index} -->\r\n"
        f'                    <span id="{prefix}Label{index}">{value}</span>'
        f"<!-- tag=end{prefix.lower()}{index} --></td>"
        for prefix, values in _LIVE_ROWS
        for index, value in enumerate(values, start=1)
    ]
    + ["        </table>", "    </form>", "</body>", "</html>", ""]
)


def test_parse_daily_page_live_shape_across_month_end():
    readings = client.parse_daily_page(_LIVE_PAGE, date(2026, 10, 3))
    assert [r.date for r in readings] == [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
    first = readings[0]
    assert first.total_hardness == 174
    assert first.ph == 7.7
    assert first.temperature == 11.5
    assert first.total_chlorine_residual == 2.26
    assert first.alkalinity == 112
    assert first.conductivity == 377
    # "0.000" is a real zero dose, not a missing reading.
    assert first.caustic_soda_dose == 0.0
    assert readings[2].conductivity == 369


async def test_get_daily_water_quality_live_shape_and_cache(httpx_mock):
    # Served as UTF-8 bytes with the live content type; the second call must come
    # from the hour-long cache, not a second request to EPCOR.
    httpx_mock.add_response(
        url=f"{constants.DAILY_URL}?zone=Rossdale",
        content=_LIVE_PAGE.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    first = await client.get_daily_water_quality("rossdale")
    second = await client.get_daily_water_quality("rossdale")
    assert [r.date_label for r in first.readings] == ["SEP-30", "OCT-01", "OCT-02"]
    assert first.units["conductivity"] == "µS/cm"
    assert first.provenance.cached is False
    assert second.provenance.cached is True
    assert len(httpx_mock.get_requests()) == 1


async def test_els_plant_uses_els_zone(httpx_mock):
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=ELS", text=_DAILY_PAGE)
    result = await client.get_daily_water_quality("els")
    assert result.plant_name == "E.L. Smith"
    assert result.provenance.url.endswith("?zone=ELS")


async def test_upstream_5xx_is_retried_then_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=ELS", status_code=503)
    with pytest.raises(UpstreamUnavailable, match="HTTP 503"):
        await client.get_daily_water_quality("els")
    assert len(httpx_mock.get_requests()) == 3


async def test_rate_limited_429_is_retried_then_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            url=f"{constants.DAILY_URL}?zone=ELS", status_code=429, headers={"Retry-After": "1"}
        )
    with pytest.raises(UpstreamUnavailable, match="HTTP 429"):
        await client.get_daily_water_quality("els")
    assert len(httpx_mock.get_requests()) == 3


async def test_404_is_not_retried_and_becomes_upstream_error(httpx_mock):
    # A moved page is a shape change, not an outage: one request, UpstreamError.
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=ELS", status_code=404)
    with pytest.raises(UpstreamError, match="HTTP 404"):
        await client.get_daily_water_quality("els")
    assert len(httpx_mock.get_requests()) == 1


async def test_timeout_becomes_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable, match="did not respond"):
        await client.get_daily_water_quality("els")


async def test_error_page_without_spans_is_upstream_error_and_not_cached(httpx_mock):
    # An ASP.NET error page answers 200 with HTML but none of the value spans.
    # The failure must not be cached: the next call fetches again and succeeds.
    httpx_mock.add_response(
        url=f"{constants.DAILY_URL}?zone=ELS",
        text="<html><body><h2>Server Error in '/DailyWaterQuality' Application.</h2></body></html>",
    )
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=ELS", text=_DAILY_PAGE)
    with pytest.raises(UpstreamError, match="DateLabel"):
        await client.get_daily_water_quality("els")
    result = await client.get_daily_water_quality("els")
    assert len(result.readings) == 2


async def test_unknown_plant_raises_in_french():
    with pytest.raises(InvalidInput, match="Entrée invalide") as excinfo:
        await client.get_daily_water_quality("gold_bar", lang="fr")  # type: ignore[arg-type]
    assert "plant doit être l'une des valeurs" in str(excinfo.value)


async def test_french_provenance_units_and_licence(httpx_mock):
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=ELS", text=_DAILY_PAGE)
    result = await client.get_daily_water_quality("els", lang="fr")
    assert result.provenance.freshness is not None
    assert "données de surveillance non validées" in result.provenance.freshness
    assert result.provenance.limits is not None
    assert "robinet" in result.provenance.limits
    assert result.units["total_hardness"] == "mg/L en CaCO3"
    assert result.provenance.licence is not None
    assert result.provenance.licence.startswith("Conditions non précisées")


async def test_english_provenance_unchanged(httpx_mock):
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=ELS", text=_DAILY_PAGE)
    result = await client.get_daily_water_quality("els")
    assert result.provenance.freshness == (
        "daily averages, last 7 days; unvalidated monitoring data"
    )
    assert result.provenance.limits == "values leave the treatment plant; tap values can differ"
    assert result.units["total_hardness"] == "mg/L as CaCO3"


async def test_404_in_french(httpx_mock):
    httpx_mock.add_response(url=f"{constants.DAILY_URL}?zone=ELS", status_code=404)
    with pytest.raises(UpstreamError, match="La source amont"):
        await client.get_daily_water_quality("els", lang="fr")
