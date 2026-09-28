"""Argument-routing tests for the merged WDS tools."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.wds import client, tools
from maplestats_mcp.shared.errors import InvalidInput


def _fn(t):
    return getattr(t, "fn", t)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"vector_id": 1, "product_id": 2, "coordinate": "1.1"},
        {"product_id": 2},
        {"coordinate": "1"},
    ],
)
async def test_vector_or_coord_rejects_bad_combos(kwargs):
    with pytest.raises(InvalidInput):
        await _fn(tools.wds_get_series_info)(**kwargs)
    with pytest.raises(InvalidInput):
        await _fn(tools.wds_get_changed_series_data)(**kwargs)


async def test_series_info_routes(monkeypatch):
    calls = []

    async def by_vec(v):
        calls.append(("vec", v))

    async def by_coord(p, c):
        calls.append(("coord", p, c))

    monkeypatch.setattr(client, "get_series_info_from_vector", by_vec)
    monkeypatch.setattr(client, "get_series_info_from_cube_pid_coord", by_coord)
    await _fn(tools.wds_get_series_info)(vector_id=5)
    await _fn(tools.wds_get_series_info)(product_id=7, coordinate="1.2")
    assert calls == [("vec", 5), ("coord", 7, "1.2")]


async def test_full_table_download_routes(monkeypatch):
    calls = []

    async def csv(p, lang):
        calls.append(("csv", p, lang))

    async def sdmx(p):
        calls.append(("sdmx", p))

    monkeypatch.setattr(client, "get_full_table_download_csv", csv)
    monkeypatch.setattr(client, "get_full_table_download_sdmx", sdmx)
    await _fn(tools.wds_get_full_table_download)(product_id=1, lang="fr")
    await _fn(tools.wds_get_full_table_download)(product_id=2, format="sdmx")
    assert calls == [("csv", 1, "fr"), ("sdmx", 2)]


async def test_search_cubes_rejects_lite_false_with_query():
    with pytest.raises(InvalidInput):
        await _fn(tools.wds_search_cubes)(query="cpi", lite=False)
