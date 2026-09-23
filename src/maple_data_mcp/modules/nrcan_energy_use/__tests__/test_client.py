"""Tests for modules/nrcan_energy_use/client.py, shaped on live 2026-09-23 pages."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.nrcan_energy_use import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


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
