"""CachedDereferenceMiddleware sends the schemas fastmcp's own middleware would, once."""

from __future__ import annotations

from fastmcp import Client, FastMCP
from fastmcp.server.middleware.dereference import DereferenceRefsMiddleware, _dereference_tool
from pydantic import BaseModel

from maplestats_mcp.shared import dereference
from maplestats_mcp.shared.dereference import CachedDereferenceMiddleware


class Place(BaseModel):
    name: str
    province: str | None = None


class Answer(BaseModel):
    places: list[Place]


def _server() -> FastMCP:
    server = FastMCP("t", dereference_schemas=False)
    server.add_middleware(CachedDereferenceMiddleware())

    @server.tool
    async def find_places(where: Place, limit: int = 5) -> Answer:
        return Answer(places=[where] * limit)

    @server.tool
    async def plain(text: str) -> str:
        return text

    return server


async def test_schemas_match_fastmcps_and_are_dereferenced_once(monkeypatch):
    server = _server()
    calls: list[dict] = []
    real = dereference.dereference_refs

    def counting(schema: dict) -> dict:
        calls.append(schema)
        return real(schema)

    monkeypatch.setattr(dereference, "dereference_refs", counting)
    async with Client(server) as client:
        first = {t.name: t for t in await client.list_tools()}
        second = {t.name: t for t in await client.list_tools()}

    stock = {t.name: _dereference_tool(t) for t in await server.list_tools(run_middleware=False)}
    for name, tool in stock.items():
        assert first[name].input_schema == tool.parameters, name
        assert first[name].output_schema == tool.output_schema, name
        assert second[name].input_schema == tool.parameters, name
    assert "$defs" not in first["find_places"].input_schema
    # find_places's input and output schemas carry $defs; plain's need nothing.
    assert len(calls) == 2


async def test_tools_still_run_through_it():
    async with Client(_server()) as client:
        result = await client.call_tool("find_places", {"where": {"name": "Banff"}, "limit": 2})
    assert result.structured_content == {
        "places": [{"name": "Banff", "province": None}, {"name": "Banff", "province": None}]
    }


def test_the_server_uses_it_instead_of_the_stock_middleware():
    from maplestats_mcp.server import mcp

    kinds = [type(m) for m in mcp.middleware]
    assert kinds.count(CachedDereferenceMiddleware) == 1
    assert DereferenceRefsMiddleware not in kinds
