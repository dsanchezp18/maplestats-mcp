from __future__ import annotations

import json
from datetime import date

import pytest

from maplestats_mcp.modules.ircc import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _round(
    draw_number: str,
    draw_date: str,
    draw_name: str,
    draw_text2: str,
    draw_size: str,
    draw_crs: str,
    draw_cutoff: str = "",
    href_prefix: str = "/content/canadasite",
) -> dict[str, str]:
    href = (
        f"{href_prefix}/en/immigration-refugees-citizenship/corporate/mandate/"
        f"policies-operational-instructions-agreements/ministerial-instructions/"
        f"express-entry-rounds/invitations.html?q={draw_number}"
    )
    return {
        "drawNumber": draw_number,
        "drawNumberURL": f"<a href='{href}'>{draw_number}</a>",
        "drawDate": draw_date,
        "drawDateFull": draw_date,
        "drawName": draw_name,
        "drawSize": draw_size,
        "drawCRS": draw_crs,
        "mitext": "",
        "DrawText1": "",
        "drawText2": draw_text2,
        "drawDateTime": "",
        "drawCutOff": draw_cutoff,
        "drawDistributionAsOn": "September 13, 2026",
        **{f"dd{i}": "0" for i in range(1, 19)},
        "dd1": "574",
        "dd2": "1,000",
        "dd3": "1,574",
        "dd9": "0",
        "dd15": "0",
        "dd16": "0",
        "dd17": "0",
        "dd18": "1,574",
    }


_EN_FEED = {
    "classes": "wb-tables",
    "rounds": [
        _round(
            "444",
            "2026-09-16",
            "Senior managers with Canadian Work Experience, 2026-Version 1",
            "Canadian Experience Class",
            "250",
            "389",
            draw_cutoff="September 01, 2026 at 23:05:13 UTC",
        ),
        _round(
            "1",
            "2015-01-31",
            "No Program Specified",
            "Federal Skilled Worker, Canadian Experience Class",
            "779",
            "886",
            href_prefix="",
        ),
    ],
}


async def test_list_rounds_parses_and_orders_newest_first(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=_EN_FEED)
    result = await client.list_express_entry_rounds()
    assert result.total_matching == 2
    assert [r.draw_number for r in result.rounds] == ["444", "1"]
    first = result.rounds[0]
    assert first.invitations_issued == 250
    assert first.crs_cutoff == 389
    assert first.crs_distribution.band_601_1200 == 574
    assert first.crs_distribution.band_501_600 == 1000
    assert first.crs_distribution.total == 1574
    assert first.eligibility_cutoff == "September 01, 2026 at 23:05:13 UTC"
    assert first.details_url == (
        "https://www.canada.ca/en/immigration-refugees-citizenship/corporate/mandate/"
        "policies-operational-instructions-agreements/ministerial-instructions/"
        "express-entry-rounds/invitations.html?q=444"
    )
    second = result.rounds[1]
    assert second.eligibility_cutoff is None
    assert second.details_url.endswith("invitations.html?q=1")


async def test_list_rounds_filters_by_program(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=_EN_FEED)
    result = await client.list_express_entry_rounds(program="canadian experience class")
    assert result.total_matching == 2  # matches both draw_name and drawText2 across rounds


async def test_list_rounds_filters_by_since(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=_EN_FEED)
    result = await client.list_express_entry_rounds(since=date(2020, 1, 1))
    assert result.total_matching == 1
    assert result.rounds[0].draw_number == "444"


async def test_list_rounds_respects_limit(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=_EN_FEED)
    result = await client.list_express_entry_rounds(limit=1)
    assert result.returned_count == 1
    assert result.total_matching == 2


async def test_get_round_by_draw_number(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=_EN_FEED)
    detail = await client.get_express_entry_round("1")
    assert detail.round.draw_number == "1"
    assert detail.round.invitations_issued == 779


async def test_get_round_accepts_lettered_draw_numbers(httpx_mock):
    # Confirmed live 2026-09-18: 2018-05-30 has two rounds published as
    # "91a" and "91b" instead of separate sequential numbers.
    lettered_feed = {
        "classes": "wb-tables",
        "rounds": [
            _round("91b", "2018-05-30", "Provincial Nominee Program", "PNP", "500", "758"),
            _round("91a", "2018-05-30", "Federal Skilled Trades", "FST", "700", "199"),
        ],
    }
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=lettered_feed)
    detail = await client.get_express_entry_round("91a")
    assert detail.round.draw_name == "Federal Skilled Trades"


async def test_get_round_not_found(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=_EN_FEED)
    with pytest.raises(NotFound):
        await client.get_express_entry_round("9999")


async def test_get_latest_round_returns_first_entry(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, json=_EN_FEED)
    detail = await client.get_latest_express_entry_round()
    assert detail.round.draw_number == "444"


async def test_french_feed_decoded_as_cp1252_not_utf8(httpx_mock):
    # The French feed's bytes are Windows-1252 despite a bare
    # "application/json" content type (no charset) -- encode a French
    # program name with cp1252 to simulate the real upstream response and
    # confirm the client decodes it correctly rather than mangling it as
    # UTF-8 (see client.py's module docstring for how this was confirmed
    # against the live feed).
    fr_round = _round(
        "444",
        "2026-09-16",
        "Cadres supérieurs, 2026-version 1",
        "Programme des travailleurs qualifiés (fédéral)",
        "250",
        "389",
    )
    body = json.dumps({"classes": "wb-tables", "rounds": [fr_round]}, ensure_ascii=False)
    httpx_mock.add_response(
        url=constants.BASE_URL_FR,
        content=body.encode("cp1252"),
        headers={"content-type": "application/json"},
    )
    result = await client.list_express_entry_rounds(lang="fr")
    assert result.rounds[0].draw_name == "Cadres supérieurs, 2026-version 1"
    assert result.rounds[0].program == "Programme des travailleurs qualifiés (fédéral)"


async def test_french_feed_uses_space_thousands_separator(httpx_mock):
    fr_round = _round("444", "2026-09-16", "General", "General", "1 200", "389")
    body = json.dumps({"classes": "wb-tables", "rounds": [fr_round]}, ensure_ascii=False)
    httpx_mock.add_response(
        url=constants.BASE_URL_FR,
        content=body.encode("cp1252"),
        headers={"content-type": "application/json"},
    )
    result = await client.list_express_entry_rounds(lang="fr")
    assert result.rounds[0].invitations_issued == 1200


async def test_invalid_inputs_are_typed():
    with pytest.raises(InvalidInput):
        await client.list_express_entry_rounds(limit=0)
    with pytest.raises(InvalidInput):
        await client.list_express_entry_rounds(limit=constants.ROUNDS_LIMIT_MAX + 1)
    with pytest.raises(InvalidInput):
        await client.get_express_entry_round(" ")


async def test_malformed_feed_is_typed_upstream_error(httpx_mock):
    httpx_mock.add_response(url=constants.BASE_URL_EN, text="not json")
    with pytest.raises(UpstreamError):
        await client.list_express_entry_rounds()
