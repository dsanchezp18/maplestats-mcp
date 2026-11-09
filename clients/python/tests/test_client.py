"""The client against recorded responses from the hosted server (no network)."""

from __future__ import annotations

import json

import httpx
import polars as pl
import pytest
from conftest import FakeServer, recorded

from maplestats import Client, MapleStatsError, RateLimited


def test_opens_one_session_and_proxies_through_call_tool(
    client: Client, server: FakeServer
) -> None:
    client.call_tool("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    client.call_tool("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    methods = [b["method"] for b in server.bodies()]
    assert methods == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/call",
    ]
    call = server.bodies()[2]["params"]
    assert call["name"] == "call_tool"
    assert call["arguments"]["name"] == "boc_get_observations"
    assert server.seen[2].headers["mcp-protocol-version"] == "2025-06-18"
    assert server.seen[0].headers["user-agent"].startswith("maplestats-python/")


SEARCH_COLUMNS = ["name", "description", "arguments", "input_schema"]


def test_search_tools_returns_a_frame(client: Client, server: FakeServer) -> None:
    found = client.search_tools("bank of canada exchange rate")
    assert found.columns == SEARCH_COLUMNS
    assert found.height > 0
    assert found["name"].str.starts_with("boc_").any()
    assert json.loads(found["input_schema"][0])["properties"]
    assert found["arguments"].is_null().all()
    call = server.bodies()[2]["params"]
    assert call["name"] == "search_tools"
    assert call["arguments"]["detail"] == "full"


def test_brief_search_keeps_the_signature(client: Client, server: FakeServer) -> None:
    found = client.search_tools("bank of canada exchange rate", detail="brief")
    assert found.columns == SEARCH_COLUMNS
    assert found.height > 0
    assert found["arguments"][0].startswith("{")
    assert found["input_schema"].is_null().all()


def test_search_falls_back_on_a_server_without_detail(
    client: Client, server: FakeServer
) -> None:
    # A server before the compact search rejects `detail` and answers the full form.
    def old_server(request: httpx.Request) -> httpx.Response | None:
        body = json.loads(request.content)
        if body["method"] != "tools/call":
            return None
        sse = {"content-type": "text/event-stream"}
        if "detail" in body["params"]["arguments"]:
            error = {
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [
                        {"type": "text", "text": "Unexpected argument: detail"}
                    ],
                    "isError": True,
                },
            }
            return httpx.Response(
                200, headers=sse, text=f"data: {json.dumps(error)}\n\n"
            )
        return httpx.Response(
            200, headers=sse, text=recorded("search_tools", body["id"])
        )

    server.override = old_server
    found = client.search_tools("bank of canada exchange rate")
    assert found.height > 0
    assert json.loads(found["input_schema"][0])["properties"]
    assert "detail" not in server.bodies()[-1]["params"]["arguments"]


def test_search_with_no_match_is_an_empty_frame(client: Client) -> None:
    found = client.search_tools("zzqx")
    assert found.height == 0
    assert found.columns == SEARCH_COLUMNS


def test_plan_query_is_called_directly(client: Client, server: FakeServer) -> None:
    plan = client.plan_query("Unemployment rate in Alberta")
    assert plan["topics"][0]["steps"]
    assert server.bodies()[2]["params"]["name"] == "plan_query"


def test_get_data_tidies_boc_observations(client: Client) -> None:
    result = client.get_data(
        "boc_get_observations", series_names=["FXUSDCAD"], recent=3
    )
    assert result.data.columns == ["ref_date", "values_fxusdcad"]
    assert result.data.height == 3
    assert result.data["values_fxusdcad"].dtype == pl.Float64
    assert result.provenance["source"] == "boc"
    assert result.citation[0].startswith("Source: boc. https://www.bankofcanada.ca/")
    assert result.left_out["series"] == "[object]"
    assert result.tool == "boc_get_observations"
    assert result.arguments == {"series_names": ["FXUSDCAD"], "recent": 3}


def test_get_data_unnests_series_observations(client: Client) -> None:
    result = client.get_data(
        "wds_get_data_from_vectors", vector_ids=[2062815], latest_n=3
    )
    frame = result.data
    assert frame.height == 3
    assert {"vector_id", "ref_period", "value", "context_citation"} <= set(
        frame.columns
    )
    assert frame["vector_id"].unique().to_list() == [2062815]
    assert result.citation == [frame["context_citation"][0]]
    assert "Table 14-10-0287-01" in result.citation[0]
    assert result.provenance["source"] == "statcan-wds"


def test_tool_error_raises_with_the_server_message(client: Client) -> None:
    with pytest.raises(MapleStatsError, match="Series NOPE_XX not found"):
        client.call_tool("boc_get_observations", series_names=["NOPE_XX"], recent=3)


def test_reproduce_code_returns_scripts(client: Client) -> None:
    code = client.reproduce_code(
        "boc_get_observations", {"series_names": ["FXUSDCAD"], "recent": 3}
    )
    assert code["scripts"][0]["language"] == "python"
    assert "polars" in code["scripts"][0]["code"]


def test_expired_session_is_reopened_once(client: Client, server: FakeServer) -> None:
    client.call_tool("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    expired = {"done": False}

    def drop_session(request: httpx.Request) -> httpx.Response | None:
        body = json.loads(request.content)
        if body["method"] == "tools/call" and not expired["done"]:
            expired["done"] = True
            return httpx.Response(404, text="Session not found")
        return None

    server.override = drop_session
    client.call_tool("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    methods = [b["method"] for b in server.bodies()]
    assert methods.count("initialize") == 2
    assert methods[-1] == "tools/call"


def test_rate_limit_raises_with_retry_after(client: Client, server: FakeServer) -> None:
    server.override = lambda request: httpx.Response(
        429, headers={"retry-after": "12"}, text="Too many requests"
    )
    with pytest.raises(RateLimited) as caught:
        client.search_tools("anything")
    assert caught.value.retry_after == 12.0


def test_http_error_raises(client: Client, server: FakeServer) -> None:
    server.override = lambda request: httpx.Response(503, text="busy")
    with pytest.raises(MapleStatsError, match="HTTP 503"):
        client.search_tools("anything")


def test_json_rpc_error_raises(client: Client, server: FakeServer) -> None:
    client.search_tools("bank of canada exchange rate")

    def rpc_error(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        error = {"jsonrpc": "2.0", "id": body["id"], "error": {"message": "Bad call"}}
        return httpx.Response(200, json=error)

    server.override = rpc_error
    with pytest.raises(MapleStatsError, match="Bad call"):
        client.search_tools("anything")


def test_token_and_url_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, server: FakeServer
) -> None:
    monkeypatch.setenv("MAPLESTATS_URL", "https://self.hosted/mcp")
    monkeypatch.setenv("MAPLESTATS_TOKEN", "secret")
    local = Client(transport=httpx.MockTransport(server))
    local.search_tools("bank of canada exchange rate")
    assert str(server.seen[0].url) == "https://self.hosted/mcp"
    assert server.seen[0].headers["authorization"] == "Bearer secret"


def test_recorded_helper_keeps_crlf_bodies_readable() -> None:
    assert recorded("boc", 7).count("data: ") == 1
