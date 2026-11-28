# The client against recorded responses from the hosted server (no network),
# plus one live call when MAPLESTATS_LIVE=1.

using MapleStats
using MapleStats: clean_names, resolve_shared_notes, rows_and_left_out
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

"""
The recording that answers a tools/call, as the real server would choose it.

A call_tool without detail = "full" gets the server's brief result, where a list of
six or more rows is CSV text; the long recordings have a _brief twin for that. Every
other recording is the same whatever `detail` says.
"""
function answer_for(params)
    name = fixture_for(params)
    asked_full =
        params.name != "call_tool" || get(params.arguments, :detail, nothing) == "full"
    brief = "$(name)_brief"
    return !asked_full && isfile(joinpath(FIXTURES, "$(brief).sse")) ? brief : name
end

"""Records what the client sent; answers from fixtures or an override."""
mutable struct FakeServer
    seen::Vector{Any}
    override::Union{Nothing,Function}
end
FakeServer() = FakeServer([], nothing)

const SSE = ["content-type" => "text/event-stream"]
const SEARCH_COLUMNS = ["name", "description", "arguments", "input_schema"]
const SCALE_NOTE = "Values are in thousands: multiply value by scale_multiplier for the full figure."
const LATEST_NOTE = "The latest period is preliminary and may be revised."
const WDS_LONG_COLUMNS = [
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
    return (200, SSE, recorded(answer_for(message.params), message.id))
end

"""A tool error as the server sends it: an isError result in one event."""
function error_reply(id, text)
    block = Dict("type" => "text", "text" => text)
    result = Dict("content" => [block], "isError" => true)
    reply = Dict("jsonrpc" => "2.0", "id" => id, "result" => result)
    return (200, SSE, "data: $(JSON3.write(reply))\n\n")
end

# What a server that does not know `detail` says, word for word: the project's own
# validation message, as the v0.5.0 server gave it (a call_tool error names the inner
# tool and lists that tool's parameters), in English and in French.
const OLD_SERVER_ERRORS = [
    "detail is not a parameter of this tool; parameters: query",
    string(
        "[invalid_input] Invalid input: boc_get_observations: detail is not a ",
        "parameter of this tool; parameters: aggregation, lang, recent, series_names ",
        "Fix: correct the argument named above.",
    ),
    "detail n'est pas un paramètre de cet outil; paramètres : query",
    string(
        "[invalid_input] Entrée invalide\u00a0: boc_get_observations\u00a0: detail ",
        "n'est pas un paramètre de cet outil; paramètres\u00a0: lang, recent, ",
        "series_names Solution\u00a0: corrigez l'argument nommé ci-dessus.",
    ),
]

# Errors that mention `detail` or an unknown argument without being that refusal: a
# current server's invalid-arguments error quotes a tool's parameters (one is called
# "details"), and the earlier loose wording ("Unexpected argument: detail").
const NOT_THE_REFUSAL = [
    string(
        "Invalid input: some_tool: kind is not a parameter of this tool; ",
        "parameters: details, lang",
    ),
    "Invalid input: some_tool: detail must be one of 'brief' or 'full' (got 'x')",
    "Unexpected argument: detail",
    "Unknown series: detail",
    "No detail found for FXUSDCAD.",
]

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

    for refusal in OLD_SERVER_ERRORS
        @testset "search falls back on a server without detail: $(refusal)" begin
            # A server before the compact search rejects `detail` and answers the full
            # form.
            server = FakeServer()
            server.override = function (message)
                message.method == "tools/call" || return nothing
                if haskey(message.params.arguments, :detail)
                    return error_reply(message.id, refusal)
                end
                return (200, SSE, recorded("search_tools", message.id))
            end
            found = search_tools("bank of canada exchange rate"; client=fake_client(server))
            @test size(found, 1) > 0
            @test !ismissing(found.input_schema[1])
            @test !haskey(server.seen[end].body.params.arguments, :detail)
        end

        @testset "data calls fall back on a server without detail: $(refusal)" begin
            # A server before 0.6.0 does not know call_tool's `detail`; it answers in
            # full.
            server = FakeServer()
            server.override = function (message)
                message.method == "tools/call" || return nothing
                if haskey(message.params.arguments, :detail)
                    return error_reply(message.id, refusal)
                end
                return nothing
            end
            client = fake_client(server)
            df = get_data(
                "boc_get_observations"; client, series_names=["FXUSDCAD"], recent=3
            )
            @test size(df, 1) == 3
            calls = [e.body.params for e in server.seen if e.body.method == "tools/call"]
            @test length(calls) == 2
            @test calls[1].arguments.detail == "full"
            @test calls[2].name == "call_tool"
            @test !haskey(calls[2].arguments, :detail)
            @test calls[2].arguments.arguments.recent == 3
            # The raw call falls back the same way.
            @test boc(client).provenance.source == "boc"
        end
    end

    for message in NOT_THE_REFUSAL
        @testset "a detail-only error is not repeated: $(message)" begin
            # The tool's own error, not a refusal of the argument: one call each for
            # the raw call, the data call and the search, and each throws.
            server = FakeServer()
            server.override = function (request)
                request.method == "tools/call" || return nothing
                return error_reply(request.id, message)
            end
            client = fake_client(server)
            attempts = [
                () -> boc(client),
                () -> get_data(
                    "boc_get_observations"; client, series_names=["FXUSDCAD"], recent=3
                ),
                () -> search_tools("bank of canada exchange rate"; client),
            ]
            for attempt in attempts
                error = try
                    attempt()
                    nothing
                catch caught
                    caught
                end
                @test error isa MapleStatsError
            end
            @test count(==("tools/call"), methods_sent(server)) == 3
        end
    end

    @testset "the repeat without detail is made once" begin
        # A server that refuses `detail` and then fails the repeat too: two calls, then
        # the error reaches the caller.
        server = FakeServer()
        server.override = function (request)
            request.method == "tools/call" || return nothing
            return error_reply(request.id, OLD_SERVER_ERRORS[1])
        end
        error = try
            get_data(
                "boc_get_observations";
                client=fake_client(server),
                series_names=["FXUSDCAD"],
                recent=3,
            )
            nothing
        catch caught
            caught
        end
        @test error isa MapleStatsError
        @test occursin("detail is not a parameter", error.message)
        calls = [e.body.params for e in server.seen if e.body.method == "tools/call"]
        @test length(calls) == 2
        @test haskey(calls[1].arguments, :detail)
        @test !haskey(calls[2].arguments, :detail)
    end

    @testset "the raw call passes detail to the server's own tools" begin
        server = FakeServer()
        client = fake_client(server)
        # search_tools takes `detail` itself, so it goes in its arguments, as given.
        call_tool(
            "search_tools"; query="bank of canada exchange rate", detail="full", client
        )
        call = server.seen[3].body.params
        @test call.name == "search_tools"
        @test Dict(string(k) => v for (k, v) in pairs(call.arguments)) ==
            Dict("query" => "bank of canada exchange rate", "detail" => "full")
        # Without one, nothing is added.
        call_tool("plan_query"; question="Unemployment rate in Alberta", client)
        sent = server.seen[4].body.params.arguments
        @test Dict(string(k) => v for (k, v) in pairs(sent)) ==
            Dict("question" => "Unemployment rate in Alberta")
    end

    @testset "plan_query has no detail and the server says so" begin
        server = FakeServer()
        server.override = function (message)
            message.method == "tools/call" || return nothing
            text = "detail is not a parameter of this tool; parameters: question, lang"
            return error_reply(message.id, text)
        end
        error = try
            call_tool(
                "plan_query";
                question="Unemployment rate in Alberta",
                detail="full",
                client=fake_client(server),
            )
            nothing
        catch caught
            caught
        end
        @test error isa MapleStatsError
        @test occursin("detail is not a parameter", error.message)
        calls = [e.body.params for e in server.seen if e.body.method == "tools/call"]
        @test length(calls) == 1
        @test calls[1].name == "plan_query"
        @test calls[1].arguments.detail == "full"
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
        # A full result carries every field: non_numeric is null on every row here.
        @test names(df) == ["ref_date", "values_fxusdcad", "non_numeric"]
        @test size(df, 1) == 3
        @test eltype(df.values_fxusdcad) == Float64
        @test metadata(df, "provenance").source == "boc"
        @test startswith(
            only(metadata(df, "citation")), "Source: boc. https://www.bankofcanada.ca/"
        )
        @test metadata(df, "left_out") ==
            Dict("series" => "[object]", "transformed" => nothing)
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

    @testset "data tools are called with full detail" begin
        server = FakeServer()
        client = fake_client(server)
        boc(client)
        get_data("boc_get_observations"; client, series_names=["FXUSDCAD"], recent=3)
        calls = [e.body.params for e in server.seen if e.body.method == "tools/call"]
        @test length(calls) == 2
        for call in calls
            # `detail` is call_tool's own argument, beside `name` and `arguments`.
            @test call.name == "call_tool"
            @test call.arguments.detail == "full"
            @test call.arguments.arguments.recent == 3
            @test !haskey(call.arguments.arguments, :detail)
        end
    end

    @testset "call_tool can ask for the brief answer" begin
        server = FakeServer()
        call_tool(
            "boc_get_observations";
            detail="brief",
            client=fake_client(server),
            series_names=["FXUSDCAD"],
            recent=3,
        )
        call = server.seen[3].body.params.arguments
        @test call.detail == "brief"
        @test call.arguments.recent == 3
        @test !haskey(call.arguments, :detail)
    end

    @testset "a brief call returns the rows as csv text" begin
        # What the server's default answer holds for twelve rows, and what get_data
        # would be unable to read as rows.
        raw = call_tool(
            "wds_get_data_from_vectors";
            detail="brief",
            client=fake_client(FakeServer()),
            vector_ids=[2062815],
            latest_n=12,
        )
        block = raw.series[1].observations
        @test block.format == "csv"
        @test block.rows == 12
        @test startswith(block.csv, "ref_period,value\n2025-11-01,")
        @test !haskey(raw.provenance, :queried_at)
    end

    @testset "a long StatCan result becomes one row per observation" begin
        server = FakeServer()
        df = get_data(
            "wds_get_data_from_vectors";
            client=fake_client(server),
            vector_ids=[2062815],
            latest_n=12,
        )
        call = server.seen[3].body.params.arguments
        @test call.detail == "full"
        @test call.arguments.latest_n == 12
        @test size(df) == (12, 30)
        @test names(df) == WDS_LONG_COLUMNS
        @test df.ref_period[[1, 12]] == ["2025-11-01", "2026-10-01"]
        @test eltype(df.value) == Float64
        @test unique(df.vector_id) == [2062815]
        @test unique(df.context_unit) == ["Percent"]
        @test metadata(df, "citation") == [df.context_citation[1]]
        @test occursin("Table 14-10-0287-01", only(metadata(df, "citation")))
        # A full result keeps the whole provenance, caveats and query time included.
        provenance = metadata(df, "provenance")
        @test provenance.source == "statcan-wds"
        @test haskey(provenance, :queried_at)
        @test length(provenance.caveats) == 2
        @test metadata(df, "left_out") == Dict("failed" => "[list]")
    end

    @testset "a long Bank of Canada result becomes one row per date" begin
        server = FakeServer()
        df = get_data(
            "boc_get_observations";
            client=fake_client(server),
            series_names=["FXUSDCAD"],
            recent=12,
        )
        @test server.seen[3].body.params.arguments.detail == "full"
        @test size(df) == (12, 3)
        @test names(df) == ["ref_date", "values_fxusdcad", "non_numeric"]
        @test length(unique(df.ref_date)) == 12
        @test eltype(df.values_fxusdcad) == Float64
        provenance = metadata(df, "provenance")
        @test provenance.source == "boc"
        @test startswith(provenance.caveats[1], "Indicative rate")
        @test startswith(
            only(metadata(df, "citation")), "Source: boc. https://www.bankofcanada.ca/"
        )
        @test metadata(df, "left_out") ==
            Dict("series" => "[object]", "transformed" => nothing)
    end

    @testset "notes the server states once are written back into the rows" begin
        server = FakeServer()
        client = fake_client(server)
        # wds_two was shaped by the server's own shape(): the note both series share is
        # in a top-level `shared_notes` list and each series holds a reference.
        raw = call_tool(
            "wds_get_data_from_vectors"; client, vector_ids=[2062810, 2062811], latest_n=3
        )
        @test collect(raw.shared_notes) == [SCALE_NOTE]
        @test raw.series[1].context.notes[1] == "shared_notes[0]"

        df = get_data(
            "wds_get_data_from_vectors"; client, vector_ids=[2062810, 2062811], latest_n=3
        )
        @test size(df, 1) == 6
        @test df.vector_id == [fill(2062810, 3); fill(2062811, 3)]
        @test df.context_notes ==
            [fill("$(SCALE_NOTE); $(LATEST_NOTE)", 3); fill(SCALE_NOTE, 3)]
        cells = [string(cell) for column in eachcol(df) for cell in column]
        @test !any(occursin("shared_notes", cell) for cell in cells)
        @test metadata(df, "left_out") == Dict("failed" => "[list]")
        @test metadata(df, "citation") == [df.context_citation[1], df.context_citation[4]]
    end

    @testset "references are resolved wherever they stand" begin
        # A wrapped list result: shared_notes sits beside "result" (shape() output).
        shared = "A note long enough to be shared across items of the list."
        wrapped = JSON3.read(
            """{"result":[{"name":"alpha","notes":["shared_notes[0]","Kept."]},""" *
            """{"name":"beta","notes":["shared_notes[0]"],"note":"shared_notes[9]"}],""" *
            """"shared_notes":["$(shared)"]}""",
        )
        resolved = resolve_shared_notes(wrapped)
        @test collect(keys(resolved)) == [:result]
        alpha, beta = resolved.result
        @test collect(alpha.notes) == [shared, "Kept."]
        @test collect(beta.notes) == [shared]
        # An index past the list is left as it came.
        @test beta.note == "shared_notes[9]"
        rows, left = rows_and_left_out(resolved)
        @test last(rows[2][2]) == shared
        @test isempty(left)
        # Without shared_notes the payload is returned as it is.
        plain = JSON3.read("""{"series":[{"notes":["shared_notes[0]"]}]}""")
        @test resolve_shared_notes(plain) === plain
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
