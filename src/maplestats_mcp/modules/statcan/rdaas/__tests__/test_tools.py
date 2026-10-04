"""Argument-routing tests for the merged RDaaS tools."""

from __future__ import annotations

from maplestats_mcp.modules.statcan.rdaas import client, tools


async def test_search_filters_routes_by_kind(monkeypatch):
    monkeypatch.setattr(client, "get_classification_search_filters", _ret("class"))
    monkeypatch.setattr(client, "get_concordance_search_filters", _ret("conc"))
    fn = getattr(tools.rdaas_get_search_filters, "fn", tools.rdaas_get_search_filters)
    assert await fn(kind="classification") == "class"
    assert await fn(kind="concordance") == "conc"


def _ret(value):
    async def f(lang="en"):
        return value

    return f
