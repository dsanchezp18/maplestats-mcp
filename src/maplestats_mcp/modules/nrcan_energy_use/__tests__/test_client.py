"""Tests for modules/nrcan_energy_use/client.py, shaped on live 2026-09-23 pages."""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.modules.nrcan_energy_use import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    client._down_until = 0.0
    yield


_REAL_CHECK = client._check_reachable


@pytest.fixture(autouse=True)
def _host_reachable(monkeypatch):
    # The real check opens a TCP socket; tests of it call _REAL_CHECK directly.
    async def reachable(lang: str = "en") -> None:
        return None

    monkeypatch.setattr(client, "_check_reachable", reachable)
    monkeypatch.setattr(client, "_down_until", 0.0)


_MENU = """<html><body><div class="table">
<div class="row"><div class="col-xs-4"><a title="Table 1.1a"
 href="/corporate/statistics/neud/dpa/showTable.cfm?type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1">Table 1.1a</a></div>
<div class="col-xs-8">General characteristics by region</div></div>
<div class="row"><div class="col-xs-4"><a href="/corporate/statistics/neud/dpa/home.cfm">Home</a></div></div>
</div></body></html>"""

_TABLE = """<html><body><h1></h1><h1>Table 1.1a – General Characteristics By Region</h1>
<table>
<tr><th></th><th>Number of households by region</th></tr>
<tr><th>Canada</th><th>Alberta</th></tr>
<tr><th>Number of households</th><td>14,954,936</td><td>A</td><td>1,639,879</td><td>A</td></tr>
<tr><th>Type of dwelling</th></tr>
<tr><th>Mobile home</th><td>171,775</td><td>A</td><td>-</td><td>U</td></tr>
</table>
<small><p><strong>Legend:</strong></p><div class="table"><div class="row">
<div class="col-md-12">The letter beside each estimate classifies its quality as follows: A–Acceptable, U–Too unreliable to be published.</div></div></div></small>
<p><small><strong>Source:</strong><div><i>2019 Survey of Household Energy Use</i></div></small></p>
</body></html>"""

_LIST = """<a href="../../../menus/trends/comprehensive/trends_res_ab.cfm">Alberta</a>
<a href="../../../menus/trends/comprehensive/trends_tran_ca.cfm">Canada</a>"""


async def test_list_products_discovers_comprehensive_menus(httpx_mock):
    httpx_mock.add_response(url=constants.EN_ROOT + constants.COMPREHENSIVE_LIST, text=_LIST)
    result = await client.list_products("fr")
    assert [(m.sector, m.jurisdiction) for m in result.comprehensive] == [
        ("res", "ab"),
        ("tran", "ca"),
    ]
    assert result.comprehensive[0].sector_name == "Résidentiel"
    assert "sheu_2019" in [p.product for p in result.surveys]


async def test_list_tables_parses_menu_and_restores_sector_param(httpx_mock):
    httpx_mock.add_response(url=constants.EN_ROOT + "menus/sheu/2019/tables.cfm", text=_MENU)
    result = await client.list_tables("sheu_2019")
    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.title == "General characteristics by region"
    assert table.table_key == "type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1"


async def test_list_tables_validates_product_and_comprehensive_args():
    with pytest.raises(InvalidInput, match="Unknown product"):
        await client.list_tables("bogus")
    with pytest.raises(InvalidInput, match="sector and jurisdiction"):
        await client.list_tables("comprehensive", "res")
    with pytest.raises(InvalidInput):
        await client.list_tables("comprehensive", "../x", "ab")


async def test_get_table_parses_headers_rows_and_notes_in_french(httpx_mock):
    key = "type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1"
    httpx_mock.add_response(url=f"{constants.FR_ROOT}showTable.cfm?{key}", text=_TABLE)
    table = await client.get_table(key, "fr")
    assert table.title.startswith("Table 1.1a")
    assert table.header_rows == [["", "Number of households by region"], ["Canada", "Alberta"]]
    assert table.rows[0] == ["Number of households", "14,954,936", "A", "1,639,879", "A"]
    assert table.rows[1] == ["Type of dwelling"]
    assert table.notes[0].startswith("The letter beside each estimate")
    assert table.notes[-1] == "Source:2019 Survey of Household Energy Use"


async def test_get_table_rejects_foreign_keys_and_missing_table(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.get_table("type=SH&rn=1&url=http://evil")
    with pytest.raises(InvalidInput):
        await client.get_table("type=SH&rn=1/../x")
    httpx_mock.add_response(text="<html><body>no table</body></html>")
    with pytest.raises(NotFound):
        await client.get_table("type=SH&rn=999")


# oee.nrcan.gc.ca refused or timed out every connection from here on 2026-10-03
# (five polite GETs: ConnectError, then ConnectTimeout), so no new live shape was
# captured; the tests below cover the client's error paths with mocked transports.

_MENU_URL = constants.EN_ROOT + "menus/sheu/2019/tables.cfm"


async def test_upstream_5xx_is_retried_then_upstream_error(httpx_mock):
    # get_raw retries 5xx three times before the client maps the status.
    for _ in range(3):
        httpx_mock.add_response(
            url=_MENU_URL, status_code=503, text="<html>Service Unavailable</html>"
        )
    with pytest.raises(UpstreamError, match="HTTP 503"):
        await client.list_tables("sheu_2019")
    assert len(httpx_mock.get_requests()) == 3


async def test_rate_limited_429_is_retried_and_can_recover(httpx_mock):
    httpx_mock.add_response(url=_MENU_URL, status_code=429, headers={"Retry-After": "0"})
    httpx_mock.add_response(url=_MENU_URL, text=_MENU)
    result = await client.list_tables("sheu_2019")
    assert [t.table_number for t in result.tables] == ["Table 1.1a"]
    assert len(httpx_mock.get_requests()) == 2


async def test_unpublished_menu_404_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_MENU_URL, status_code=404, text="<html>Page not found</html>")
    with pytest.raises(NotFound, match="nothing published"):
        await client.list_tables("sheu_2019")


async def test_connection_failures_become_upstream_unavailable(httpx_mock):
    # The failure seen live on 2026-10-03: the host drops or never accepts the connection.
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("timed out"), url=_MENU_URL)
    with pytest.raises(UpstreamUnavailable):
        await client.list_tables("sheu_2019")
    assert len(httpx_mock.get_requests()) == 3
    # The next call fails at once, without another request.
    with pytest.raises(UpstreamUnavailable, match="could not be reached"):
        await client.get_table("type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1")
    assert len(httpx_mock.get_requests()) == 3
    # The survey list still answers, with the menus left out and the reason given.
    products = await client.list_products()
    assert len(products.surveys) == 11 and products.comprehensive == []
    assert "not loaded" in (products.provenance.limits or "")


async def test_menu_page_without_table_links_is_not_found(httpx_mock):
    # A maintenance or redesigned page answers 200 with no showTable.cfm links; an
    # empty TableList would read as "this survey has no tables".
    httpx_mock.add_response(
        url=_MENU_URL,
        text='<html><body><h1>Maintenance</h1><a href="/home.cfm">Home</a></body></html>',
    )
    with pytest.raises(NotFound, match="No tables listed"):
        await client.list_tables("sheu_2019")


async def test_get_table_normalises_key_order_and_serves_repeat_from_cache(httpx_mock):
    canonical = "type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1"
    httpx_mock.add_response(url=f"{constants.EN_ROOT}showTable.cfm?{canonical}", text=_TABLE)
    first = await client.get_table("?page=1&rn=1&year=2019&juris=ca&sector=aaa&type=SH")
    second = await client.get_table(canonical)
    assert first.table_key == second.table_key == canonical
    assert first.provenance.cached is False
    assert second.provenance.cached is True
    assert len(httpx_mock.get_requests()) == 1


async def test_unreachable_host_fails_fast_and_is_remembered(monkeypatch):
    # Live 2026-10-03: TCP connects to oee.nrcan.gc.ca:443 time out; each tool
    # used to wait about 67 s (60 s read timeout plus retries) before failing.
    calls = 0

    async def never_connects(host: str, port: int):
        nonlocal calls
        calls += 1
        raise TimeoutError

    monkeypatch.setattr(client.asyncio, "open_connection", never_connects)
    with pytest.raises(UpstreamUnavailable, match="did not accept a connection"):
        await _REAL_CHECK()
    with pytest.raises(UpstreamUnavailable, match="not accepting connections"):
        await _REAL_CHECK()
    assert calls == 1
    with pytest.raises(UpstreamUnavailable, match="n'accepte pas les connexions"):
        await _REAL_CHECK("fr")


async def test_french_errors_and_down_note(monkeypatch):
    with pytest.raises(InvalidInput, match="^Entrée invalide : produit inconnu"):
        await client.list_tables("nothing", lang="fr")
    with pytest.raises(InvalidInput, match="table_key doit être une clé"):
        await client.get_table("x=1", lang="fr")

    async def down(lang: str = "en") -> None:
        raise UpstreamUnavailable("nrcan_energy_use : site injoignable")

    monkeypatch.setattr(client, "_check_reachable", down)
    result = await client.list_products("fr")
    assert result.note is not None and result.note.startswith("Le menu des tableaux complets")
    assert (result.provenance.limits or "").startswith("Menus de la base de données complète")


async def test_list_products_keeps_the_static_surveys_when_the_site_is_down(monkeypatch):
    async def down(lang: str = "en") -> None:
        raise UpstreamUnavailable("nrcan_energy_use: host down")

    monkeypatch.setattr(client, "_check_reachable", down)
    result = await client.list_products()
    assert len(result.surveys) == len(constants.SURVEYS)
    assert result.comprehensive == []
    assert result.note is not None and "comprehensive" in result.note


# Comprehensive Energy Use Database, recorded live 2026-11-07 (trimmed): the
# tables now run to 2023, and the menu links carry year=2023. Page 0 shows
# 2000 and 2018-2023; page=1 holds 2000-2017. The h1 is empty, so the title
# comes from the caption, written with <br /> lines and a footnote <sup>.
_COMPREHENSIVE_MENU = """<div class="table">
       	<div class="row mrgn-bttm-md">
           	<div class="col-xs-4 col-sm-2 col-md-2"><a title="Table 1" href="/corporate/statistics/neud/dpa/showTable.cfm?type=CP&sector=res&juris=ab&year=2023&rn=1&page=0">Table 1:</a></div>
			<div class="col-xs-8 col-sm-9 col-md-10">Secondary Energy Use and <abbr title="Greenhouse Gas">GHG</abbr> Emissions by Energy Source</div>
		</div>
		<div class="row mrgn-bttm-md">
			<div class="col-xs-4 col-sm-2 col-md-2"><a title="Table 2" href="/corporate/statistics/neud/dpa/showTable.cfm?type=CP&sector=res&juris=ab&year=2023&rn=2&page=0">Table 2:</a></div>
			<div class="col-xs-8 col-sm-9 col-md-10">Households, Floor Space and Energy Use</div>
		</div></div>"""

_COMPREHENSIVE_KEY = "type=CP&sector=res&juris=ab&year=2023&rn=1&page=0"

_COMPREHENSIVE_TABLE = """<html><body><h1 id="wb-cont" property="name">
	
</h1>
<table id="statdata" class="table table-hover table-bordered table-striped"><caption class="text-left">Residential Sector<br />Alberta<sup><a title="Footnote 1" href="#footnotes">1</a></sup><br />Table 1: Secondary Energy Use and <abbr title="Greenhouse Gas">GHG</abbr> Emissions by Energy Source</caption>
<tr><th class="un_normalize_header">&nbsp;</th>
<th class="toprow_header align-middle text-center" scope="col">2000</th>
<th id="topspacer" scope="col">&nbsp;</th>
<th scope="col">2018</th>
<th scope="col">2019</th>
<th scope="col">2020</th>
<th scope="col">2021</th>
<th scope="col">2022</th>
<th scope="col">2023</th>
</tr>
<tr><th class="singlerow" scope="row">Total Energy Use (<abbr title="Petajoule">PJ</abbr>)</th>
<td class="highlightdata data"><strong>191.3</strong></td>
<td class="spacer">&nbsp;</td>
<td class="highlightdata text-right data"><strong>217.5</strong></td>
<td class="shadowhighlight text-right data"><strong>217.7</strong></td>
<td class="highlightdata text-right data"><strong>215.3</strong></td>
<td class="shadowhighlight text-right data"><strong>205.9</strong></td>
<td class="highlightdata text-right data"><strong>215.9</strong></td>
<td class="shadowhighlight text-right data"><strong>203.5</strong></td>
</tr>
<tr><th class="rowgroup" scope="rowgroup" colspan="9"><br /><em>Energy Use by Energy Source (<abbr title="Petajoule">PJ</abbr>)</em></th></tr>
<tr><th class="row" scope="row">Electricity</th>
<td class="data">25.6</td>
<td class="spacer">&nbsp;</td>
<td class="data">36.8</td>
<td class="shadow data">39.5</td>
<td class="data">41.5</td>
<td class="shadow data">42.0</td>
<td class="data">41.0</td>
<td class="shadow data">40.6</td>
</tr>
</table>
<p><small><a id="footnotes"></a><strong>Footnotes:</strong><br />
<div class="mrgn&minus;bttm&minus;md">1) Data on <abbr title="Greenhouse Gas">GHG</abbr> emissions are presented <span class="underline">excluding</span> <abbr title="Greenhouse Gas">GHG</abbr> emissions related to electricity production only.</div></small></p>
</body></html>"""


async def test_comprehensive_menu_lists_2023_tables(httpx_mock):
    httpx_mock.add_response(
        url=constants.EN_ROOT + "menus/trends/comprehensive/trends_res_ab.cfm",
        text=_COMPREHENSIVE_MENU,
    )
    result = await client.list_tables("comprehensive", "res", "ab")
    assert [t.table_key for t in result.tables] == [
        _COMPREHENSIVE_KEY,
        "type=CP&sector=res&juris=ab&year=2023&rn=2&page=0",
    ]
    assert result.tables[0].title == "Secondary Energy Use and GHG Emissions by Energy Source"


async def test_comprehensive_table_returns_2023_with_a_readable_title(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.EN_ROOT}showTable.cfm?{_COMPREHENSIVE_KEY}", text=_COMPREHENSIVE_TABLE
    )
    table = await client.get_table(_COMPREHENSIVE_KEY)
    assert table.title == (
        "Residential Sector - Alberta - Table 1: Secondary Energy Use and GHG Emissions by "
        "Energy Source"
    )
    assert table.header_rows[0][-1] == "2023"
    assert table.rows[0][0] == "Total Energy Use (PJ)"
    assert table.rows[0][-1] == "203.5"
    assert table.rows[-1][-1] == "40.6"


async def test_a_reset_connection_fails_fast_as_upstream_unavailable(httpx_mock):
    # Live 2026-11-07: the TCP connect succeeds but the server resets the TLS
    # handshake now and then ("Recv failure: Connection was reset").
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectError("connection reset"), url=_MENU_URL)
    with pytest.raises(UpstreamUnavailable, match="could not be reached"):
        await client.list_tables("sheu_2019")
