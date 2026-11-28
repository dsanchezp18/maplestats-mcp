"""The client against recorded responses from the hosted server (no network)."""

from __future__ import annotations

import json

import httpx
import polars as pl
import pytest
from conftest import FakeServer, recorded

from maplestats import Client, MapleStatsError, RateLimited
from maplestats.tidy import resolve_shared_notes, rows_and_left_out


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


# What a server that does not know `detail` says, word for word: the project's own
# validation message, as the v0.5.0 server gave it (a call_tool error names the inner
# tool and lists that tool's parameters), in English and in French.
OLD_SERVER_ERRORS = [
    "detail is not a parameter of this tool; parameters: query",
    (
        "[invalid_input] Invalid input: boc_get_observations: detail is not a "
        "parameter of this tool; parameters: aggregation, lang, recent, series_names "
        "Fix: correct the argument named above."
    ),
    "detail n'est pas un paramètre de cet outil; paramètres : query",
    (
        "[invalid_input] Entrée invalide\xa0: boc_get_observations\xa0: detail "
        "n'est pas un paramètre de cet outil; paramètres\xa0: lang, recent, "
        "series_names Solution\xa0: corrigez l'argument nommé ci-dessus."
    ),
]

# Errors that mention `detail` or an unknown argument without being that refusal: a
# current server's invalid-arguments error quotes a tool's parameters (one is called
# "details"), and the earlier loose wording ("Unexpected argument: detail").
NOT_THE_REFUSAL = [
    (
        "Invalid input: some_tool: kind is not a parameter of this tool; "
        "parameters: details, lang"
    ),
    "Invalid input: some_tool: detail must be one of 'brief' or 'full' (got 'x')",
    "Unexpected argument: detail",
    "Unknown series: detail",
    "No detail found for FXUSDCAD.",
]


def error_reply(request_id: int, text: str) -> httpx.Response:
    reply = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": True},
    }
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"data: {json.dumps(reply)}\n\n",
    )


@pytest.mark.parametrize("message", OLD_SERVER_ERRORS)
def test_search_falls_back_on_a_server_without_detail(
    client: Client, server: FakeServer, message: str
) -> None:
    # A server before the compact search rejects `detail` and answers the full form.
    def old_server(request: httpx.Request) -> httpx.Response | None:
        body = json.loads(request.content)
        if body["method"] != "tools/call":
            return None
        sse = {"content-type": "text/event-stream"}
        if "detail" in body["params"]["arguments"]:
            return error_reply(body["id"], message)
        return httpx.Response(
            200, headers=sse, text=recorded("search_tools", body["id"])
        )

    server.override = old_server
    found = client.search_tools("bank of canada exchange rate")
    assert found.height > 0
    assert json.loads(found["input_schema"][0])["properties"]
    assert "detail" not in server.bodies()[-1]["params"]["arguments"]


@pytest.mark.parametrize("message", OLD_SERVER_ERRORS)
def test_data_calls_fall_back_on_a_server_without_detail(
    client: Client, server: FakeServer, message: str
) -> None:
    # A server before 0.6.0 does not know call_tool's `detail`; it answers in full.
    def old_server(request: httpx.Request) -> httpx.Response | None:
        body = json.loads(request.content)
        if body["method"] == "tools/call" and "detail" in body["params"]["arguments"]:
            return error_reply(body["id"], message)
        return None

    server.override = old_server
    result = client.get_data(
        "boc_get_observations", series_names=["FXUSDCAD"], recent=3
    )
    assert result.data.height == 3
    calls = [b["params"] for b in server.bodies() if b["method"] == "tools/call"]
    assert len(calls) == 2
    assert calls[0]["arguments"]["detail"] == "full"
    assert calls[1]["name"] == "call_tool"
    assert "detail" not in calls[1]["arguments"]
    assert calls[1]["arguments"]["arguments"] == {
        "series_names": ["FXUSDCAD"],
        "recent": 3,
    }
    # The raw call falls back the same way.
    raw = client.call_tool("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    assert raw["provenance"]["source"] == "boc"


@pytest.mark.parametrize("message", NOT_THE_REFUSAL)
def test_an_error_that_only_mentions_detail_is_not_repeated(
    client: Client, server: FakeServer, message: str
) -> None:
    # The tool's own error, not a refusal of the argument: one call, and it raises.
    server.override = lambda request: (
        error_reply(json.loads(request.content)["id"], message)
        if json.loads(request.content)["method"] == "tools/call"
        else None
    )
    with pytest.raises(MapleStatsError):
        client.call_tool("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    with pytest.raises(MapleStatsError):
        client.get_data("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    calls = [b for b in server.bodies() if b["method"] == "tools/call"]
    assert len(calls) == 2  # one per call above, none repeated


@pytest.mark.parametrize("message", NOT_THE_REFUSAL)
def test_a_search_error_that_only_mentions_detail_is_not_repeated(
    client: Client, server: FakeServer, message: str
) -> None:
    server.override = lambda request: (
        error_reply(json.loads(request.content)["id"], message)
        if json.loads(request.content)["method"] == "tools/call"
        else None
    )
    with pytest.raises(MapleStatsError):
        client.search_tools("bank of canada exchange rate")
    calls = [b for b in server.bodies() if b["method"] == "tools/call"]
    assert len(calls) == 1


def test_the_repeat_without_detail_is_made_once(
    client: Client, server: FakeServer
) -> None:
    # A server that refuses `detail` and then fails the repeat too: two calls, then
    # the error reaches the caller.
    server.override = lambda request: (
        error_reply(json.loads(request.content)["id"], OLD_SERVER_ERRORS[0])
        if json.loads(request.content)["method"] == "tools/call"
        else None
    )
    with pytest.raises(MapleStatsError, match="detail is not a parameter"):
        client.get_data("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    calls = [b["params"] for b in server.bodies() if b["method"] == "tools/call"]
    assert len(calls) == 2
    assert "detail" in calls[0]["arguments"] and "detail" not in calls[1]["arguments"]


def test_the_raw_call_passes_detail_to_the_servers_own_tools(
    client: Client, server: FakeServer
) -> None:
    # search_tools takes `detail` itself, so it goes in its arguments, as given.
    client.call_tool(
        "search_tools", query="bank of canada exchange rate", detail="full"
    )
    call = server.bodies()[2]["params"]
    assert call["name"] == "search_tools"
    assert call["arguments"] == {
        "query": "bank of canada exchange rate",
        "detail": "full",
    }
    # Without one, nothing is added.
    client.call_tool("plan_query", question="Unemployment rate in Alberta")
    assert server.bodies()[3]["params"]["arguments"] == {
        "question": "Unemployment rate in Alberta"
    }


def test_plan_query_has_no_detail_and_the_server_says_so(
    client: Client, server: FakeServer
) -> None:
    server.override = lambda request: (
        error_reply(
            json.loads(request.content)["id"],
            "detail is not a parameter of this tool; parameters: question, lang",
        )
        if json.loads(request.content)["method"] == "tools/call"
        else None
    )
    with pytest.raises(MapleStatsError, match="detail is not a parameter"):
        client.call_tool(
            "plan_query", question="Unemployment rate in Alberta", detail="full"
        )
    sent = [b["params"] for b in server.bodies() if b["method"] == "tools/call"]
    assert sent == [
        {
            "name": "plan_query",
            "arguments": {
                "question": "Unemployment rate in Alberta",
                "detail": "full",
            },
        }
    ]


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
    # A full result carries every field: non_numeric is null on every row here.
    assert result.data.columns == ["ref_date", "values_fxusdcad", "non_numeric"]
    assert result.data.height == 3
    assert result.data["values_fxusdcad"].dtype == pl.Float64
    assert result.provenance["source"] == "boc"
    assert result.citation[0].startswith("Source: boc. https://www.bankofcanada.ca/")
    assert result.left_out == {"series": "[object]", "transformed": None}
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


def test_data_tools_are_called_with_full_detail(
    client: Client, server: FakeServer
) -> None:
    client.call_tool("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    client.get_data("boc_get_observations", series_names=["FXUSDCAD"], recent=3)
    calls = [b["params"] for b in server.bodies() if b["method"] == "tools/call"]
    assert len(calls) == 2
    for call in calls:
        # `detail` is call_tool's own argument, beside `name` and `arguments`.
        assert call["name"] == "call_tool"
        assert call["arguments"]["detail"] == "full"
        assert call["arguments"]["arguments"] == {
            "series_names": ["FXUSDCAD"],
            "recent": 3,
        }


def test_call_tool_can_ask_for_the_brief_answer(
    client: Client, server: FakeServer
) -> None:
    client.call_tool(
        "boc_get_observations", detail="brief", series_names=["FXUSDCAD"], recent=3
    )
    call = server.bodies()[2]["params"]["arguments"]
    assert call["detail"] == "brief"
    assert call["arguments"] == {"series_names": ["FXUSDCAD"], "recent": 3}


def test_a_brief_call_returns_the_rows_as_csv_text(client: Client) -> None:
    # What the server's default answer holds for twelve rows, and what get_data
    # would be unable to read as rows.
    raw = client.call_tool(
        "wds_get_data_from_vectors",
        detail="brief",
        vector_ids=[2062815],
        latest_n=12,
    )
    block = raw["series"][0]["observations"]
    assert block["format"] == "csv"
    assert block["rows"] == 12
    assert block["csv"].startswith("ref_period,value\n2025-11-01,")
    assert "queried_at" not in raw["provenance"]


WDS_LONG_COLUMNS = [
    "product_id",
    "coordinate",
    "vector_id",
    "context_citation",
    "context_table_id",
    "context_table_title",
    "context_table_url",
    "context_series_title",
    "context_unit",
    "context_scale",
    "context_frequency",
    "context_geography",
    "context_members",
    "context_table_release_time",
    "context_first_period",
    "context_last_period",
    "context_notes",
    "transformed",
    "ref_period",
    "value",
    "decimals",
    "scalar_factor_code",
    "scale_multiplier",
    "symbol_code",
    "status_code",
    "security_level_code",
    "release_time",
    "symbol",
    "status",
    "security_level",
]


def test_a_long_statcan_result_becomes_one_row_per_observation(
    client: Client, server: FakeServer
) -> None:
    # Twelve observations: the server's brief result would hold them as CSV text.
    result = client.get_data(
        "wds_get_data_from_vectors", vector_ids=[2062815], latest_n=12
    )
    call = server.bodies()[2]["params"]["arguments"]
    assert call["detail"] == "full"
    assert call["arguments"] == {"vector_ids": [2062815], "latest_n": 12}
    frame = result.data
    assert frame.shape == (12, 30)
    assert frame.columns == WDS_LONG_COLUMNS
    assert frame["ref_period"].to_list()[::11] == ["2025-11-01", "2026-10-01"]
    assert frame["value"].dtype == pl.Float64
    assert frame["value"].null_count() == 0
    assert frame["vector_id"].unique().to_list() == [2062815]
    assert frame["context_unit"].unique().to_list() == ["Percent"]
    assert result.citation == [frame["context_citation"][0]]
    assert "Table 14-10-0287-01" in result.citation[0]
    # A full result keeps the whole provenance, caveats and query time included.
    assert result.provenance["source"] == "statcan-wds"
    assert result.provenance["queried_at"]
    assert len(result.provenance["caveats"]) == 2
    assert result.left_out == {"failed": "[list]"}


def test_a_long_bank_of_canada_result_becomes_one_row_per_date(
    client: Client, server: FakeServer
) -> None:
    result = client.get_data(
        "boc_get_observations", series_names=["FXUSDCAD"], recent=12
    )
    assert server.bodies()[2]["params"]["arguments"]["detail"] == "full"
    frame = result.data
    assert frame.shape == (12, 3)
    assert frame.columns == ["ref_date", "values_fxusdcad", "non_numeric"]
    assert frame["ref_date"].n_unique() == 12
    assert frame["values_fxusdcad"].dtype == pl.Float64
    assert frame["values_fxusdcad"].null_count() == 0
    assert result.provenance["source"] == "boc"
    assert result.provenance["caveats"][0].startswith("Indicative rate")
    assert result.citation[0].startswith("Source: boc. https://www.bankofcanada.ca/")
    assert result.left_out == {"series": "[object]", "transformed": None}


SCALE_NOTE = (
    "Values are in thousands: multiply value by scale_multiplier for the full figure."
)
LATEST_NOTE = "The latest period is preliminary and may be revised."


def test_notes_the_server_states_once_are_written_back_into_the_rows(
    client: Client,
) -> None:
    # wds_two was shaped by the server's own shape(): the note both series share
    # is in a top-level `shared_notes` list and each series holds a reference.
    args = {"vector_ids": [2062810, 2062811], "latest_n": 3}
    raw = client.call_tool("wds_get_data_from_vectors", **args)
    assert raw["shared_notes"] == [SCALE_NOTE]
    assert raw["series"][0]["context"]["notes"][0] == "shared_notes[0]"

    result = client.get_data("wds_get_data_from_vectors", **args)
    frame = result.data
    assert frame.shape[0] == 6
    assert frame["vector_id"].to_list() == [2062810] * 3 + [2062811] * 3
    assert (
        frame["context_notes"].to_list()
        == [f"{SCALE_NOTE}; {LATEST_NOTE}"] * 3 + [SCALE_NOTE] * 3
    )
    assert not any("shared_notes" in str(cell) for row in frame.rows() for cell in row)
    assert "shared_notes" not in result.left_out
    assert result.left_out == {"failed": "[list]"}
    assert result.citation == [
        frame["context_citation"][0],
        frame["context_citation"][3],
    ]


def test_references_are_resolved_wherever_they_stand() -> None:
    # A wrapped list result: shared_notes sits beside "result" (shape() output).
    wrapped = {
        "result": [
            {"name": "alpha", "notes": ["shared_notes[0]", "Kept."]},
            {"name": "beta", "notes": ["shared_notes[0]"], "note": "shared_notes[9]"},
        ],
        "shared_notes": ["A note long enough to be shared across items of the list."],
    }
    resolved = resolve_shared_notes(wrapped)
    assert resolved == {
        "result": [
            {
                "name": "alpha",
                "notes": [
                    "A note long enough to be shared across items of the list.",
                    "Kept.",
                ],
            },
            {
                "name": "beta",
                "notes": ["A note long enough to be shared across items of the list."],
                # An index past the list is left as it came.
                "note": "shared_notes[9]",
            },
        ]
    }
    rows, left_out = rows_and_left_out(resolved)
    assert [row["notes"] for row in rows][1] == (
        "A note long enough to be shared across items of the list."
    )
    assert left_out == {}
    # Without shared_notes the payload is returned as it is.
    plain = {"series": [{"notes": ["shared_notes[0]"]}]}
    assert resolve_shared_notes(plain) is plain


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
