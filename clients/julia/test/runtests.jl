# The client against recorded responses from the hosted server (no network),
# plus one live call when MAPLESTATS_LIVE=1.

using MapleStats
using MapleStats: clean_names
using JSON3
using Test

const FIXTURES = joinpath(@__DIR__, "fixtures")
const SESSION = "test-session"
const REQUESTS = JSON3.read(read(joinpath(FIXTURES, "requests.json"), String))

"""A recorded SSE body, its JSON-RPC id changed to the one the client sent."""
function recorded(name, request_id)
    text = read(joinpath(FIXTURES, "$(name).sse"), String)
    return replace(text, r"\"id\":\d+" => "\"id\":$(request_id)"; count=1)
end

"""Which recording answers a tools/call, matched on tool name and arguments."""
function fixture_for(params)
    tool, arguments = params.name, params.arguments
    if tool == "call_tool"
        tool, arguments = arguments.name, arguments.arguments
    end
    # lang = "en" is the server's default; the recordings leave it out.
    sent = Dict(string(k) => v for (k, v) in pairs(arguments) if !(k == :lang && v == "en"))
    for (name, request) in pairs(REQUESTS)
        recorded_arguments = Dict(string(k) => v for (k, v) in pairs(request.arguments))
        request.tool == tool && recorded_arguments == sent && return string(name)
    end
    return error("No recording for $(tool) $(JSON3.write(arguments))")
end

"""Records what the client sent; answers from fixtures or an override."""
mutable struct FakeServer
    seen::Vector{Any}
    override::Union{Nothing,Function}
end
FakeServer() = FakeServer([], nothing)

const SSE = ["content-type" => "text/event-stream"]
const SEARCH_COLUMNS = ["name", "description", "arguments", "input_schema"]

function (server::FakeServer)(url, headers, body; timeout)
    push!(server.seen, (url=url, headers=Dict(headers), body=JSON3.read(body)))
    if server.override !== nothing
        answer = server.override(JSON3.read(body))
        answer === nothing || return answer
    end
    message = JSON3.read(body)
    if message.method == "initialize"
        return (200, [SSE; "mcp-session-id" => SESSION], recorded("initialize", message.id))
    end
    message.method == "notifications/initialized" && return (202, Pair{String,String}[], "")
    @assert Dict(headers)["mcp-session-id"] == SESSION
    return (200, SSE, recorded(fixture_for(message.params), message.id))
end

methods_sent(server) = [entry.body.method for entry in server.seen]
fake_client(server) = Client(; url="https://test.invalid/mcp", transport=server)
function boc(client; series="FXUSDCAD")
    return call_tool("boc_get_observations"; client, series_names=[series], recent=3)
end

@testset "MapleStats client" begin
    @testset "one session; tools go through call_tool" begin
        server = FakeServer()
        client = fake_client(server)
        boc(client)
        boc(client)
        @test methods_sent(server) ==
            ["initialize", "notifications/initialized", "tools/call", "tools/call"]
        call = server.seen[3].body.params
        @test call.name == "call_tool"
        @test call.arguments.name == "boc_get_observations"
        @test server.seen[3].headers["mcp-protocol-version"] == "2025-06-18"
        @test startswith(server.seen[1].headers["user-agent"], "maplestats-julia/")
    end

    @testset "search_tools returns a DataFrame" begin
        server = FakeServer()
        found = search_tools("bank of canada exchange rate"; client=fake_client(server))
        @test names(found) == SEARCH_COLUMNS
        @test size(found, 1) > 0
        @test any(startswith.(found.name, "boc_"))
        @test !isempty(JSON3.read(found.input_schema[1]).properties)
        @test all(ismissing, found.arguments)
        call = server.seen[3].body.params
        @test call.name == "search_tools"
        @test call.arguments.detail == "full"
    end

    @testset "a brief search keeps the argument signature" begin
        found = search_tools(
            "bank of canada exchange rate"; detail="brief", client=fake_client(FakeServer())
        )
        @test names(found) == SEARCH_COLUMNS
        @test size(found, 1) > 0
        @test startswith(found.arguments[1], "{")
        @test all(ismissing, found.input_schema)
    end

    @testset "search falls back on a server without detail" begin
        # A server before the compact search rejects `detail` and answers the full form.
        server = FakeServer()
        server.override = function (message)
            message.method == "tools/call" || return nothing
            if haskey(message.params.arguments, :detail)
                block = Dict("type" => "text", "text" => "Unexpected argument: detail")
                result = Dict("content" => [block], "isError" => true)
                reply = Dict("jsonrpc" => "2.0", "id" => message.id, "result" => result)
                return (200, SSE, "data: $(JSON3.write(reply))\n\n")
            end
            return (200, SSE, recorded("search_tools", message.id))
        end
        found = search_tools("bank of canada exchange rate"; client=fake_client(server))
        @test size(found, 1) > 0
        @test !ismissing(found.input_schema[1])
        @test !haskey(server.seen[end].body.params.arguments, :detail)
    end

    @testset "a search with no match is an empty DataFrame" begin
        found = search_tools("zzqx"; client=fake_client(FakeServer()))
        @test size(found, 1) == 0
        @test names(found) == SEARCH_COLUMNS
    end

    @testset "plan_query is called directly" begin
        server = FakeServer()
        plan = plan_query("Unemployment rate in Alberta"; client=fake_client(server))
        @test !isempty(plan.topics[1].steps)
        @test server.seen[3].body.params.name == "plan_query"
    end

    @testset "get_data tidies Bank of Canada observations" begin
        df = get_data(
            "boc_get_observations";
            client=fake_client(FakeServer()),
            series_names=["FXUSDCAD"],
            recent=3,
        )
        @test names(df) == ["ref_date", "values_fxusdcad"]
        @test size(df, 1) == 3
        @test eltype(df.values_fxusdcad) == Float64
        @test metadata(df, "provenance").source == "boc"
        @test startswith(
            only(metadata(df, "citation")), "Source: boc. https://www.bankofcanada.ca/"
        )
        @test metadata(df, "left_out")["series"] == "[object]"
        @test metadata(df, "tool") == "boc_get_observations"
    end

    @testset "get_data unnests a series' observations" begin
        df = get_data(
            "wds_get_data_from_vectors";
            client=fake_client(FakeServer()),
            vector_ids=[2062815],
            latest_n=3,
        )
        @test size(df, 1) == 3
        @test issubset(["vector_id", "ref_period", "value", "context_citation"], names(df))
        @test unique(df.vector_id) == [2062815]
        @test metadata(df, "citation") == [df.context_citation[1]]
        @test occursin("Table 14-10-0287-01", only(metadata(df, "citation")))
    end

    @testset "a tool error raises with the server's message" begin
        error = try
            boc(fake_client(FakeServer()); series="NOPE_XX")
            nothing
        catch caught
            caught
        end
        @test error isa MapleStatsError
        @test occursin("Series NOPE_XX not found", error.message)
    end

    @testset "reproduce_code returns the scripts" begin
        code = reproduce_code(
            "boc_get_observations",
            Dict("series_names" => ["FXUSDCAD"], "recent" => 3);
            language="python",
            client=fake_client(FakeServer()),
        )
        @test code.scripts[1].language == "python"
        @test occursin("polars", code.scripts[1].code)
    end

    @testset "an expired session is reopened once" begin
        server = FakeServer()
        client = fake_client(server)
        boc(client)
        expired = Ref(false)
        server.override = function (message)
            if message.method == "tools/call" && !expired[]
                expired[] = true
                return (404, Pair{String,String}[], "Session not found")
            end
            return nothing
        end
        boc(client)
        sent = methods_sent(server)
        @test count(==("initialize"), sent) == 2
        @test last(sent) == "tools/call"
    end

    @testset "a rate limit raises with retry_after" begin
        server = FakeServer()
        server.override = _ -> (429, ["retry-after" => "12"], "Too many requests")
        error = try
            search_tools("anything"; client=fake_client(server))
            nothing
        catch caught
            caught
        end
        @test error isa MapleStatsError
        @test error.retry_after == 12.0
    end

    @testset "an HTTP error raises" begin
        server = FakeServer()
        server.override = _ -> (503, Pair{String,String}[], "")
        @test_throws MapleStatsError search_tools("anything"; client=fake_client(server))
    end

    @testset "url and token come from the environment" begin
        server = FakeServer()
        withenv(
            "MAPLESTATS_URL" => "https://self.hosted/mcp", "MAPLESTATS_TOKEN" => "secret"
        ) do
            search_tools("bank of canada exchange rate"; client=Client(; transport=server))
        end
        @test server.seen[1].url == "https://self.hosted/mcp"
        @test server.seen[1].headers["authorization"] == "Bearer secret"
    end

    @testset "names are cleaned as janitor does" begin
        @test clean_names([
            "context.citation", "values.FXUSDCAD", "refPer", "Année", "a.b", "a_b"
        ]) == ["context_citation", "values_fxusdcad", "ref_per", "annee", "a_b", "a_b_2"]
    end

    if get(ENV, "MAPLESTATS_LIVE", "") == "1"
        @testset "live: search and get_data against the hosted server" begin
            client = Client()
            found = search_tools("bank of canada exchange rate"; client)
            @test any(startswith.(found.name, "boc_"))
            df = get_data(
                "boc_get_observations"; client, series_names=["FXUSDCAD"], recent=2
            )
            @test size(df, 1) == 2
            @test "values_fxusdcad" in names(df)
            @test metadata(df, "provenance").source == "boc"
        end
    end
end
