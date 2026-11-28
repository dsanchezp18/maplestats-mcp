# Talk to the MapleStats MCP endpoint over streamable HTTP, without an MCP SDK.
# Design: docs/clients.md in the maplestats-mcp repository.

const DEFAULT_URL = "https://mcp.maplestats.danielstats.io/mcp"
const PROTOCOL_VERSION = "2025-06-18"
const CLIENT_VERSION = "0.1.0"

# The server's own tools, called by name; every other tool goes through call_tool.
const DIRECT_TOOLS = ("search_tools", "plan_query", "call_tool")

"""
    MapleStatsError(message, retry_after)

A tool error, a JSON-RPC error or an HTTP failure, with the server's message.
`retry_after` is set (seconds) when the hosted server's limit of 120 requests a
minute was hit, and `nothing` otherwise.
"""
struct MapleStatsError <: Exception
    message::String
    retry_after::Union{Nothing,Float64}
end
MapleStatsError(message::AbstractString) = MapleStatsError(String(message), nothing)
Base.showerror(io::IO, e::MapleStatsError) = print(io, "MapleStatsError: ", e.message)

"""One HTTP exchange: (status, headers, body) for a POST of `body` to `url`."""
function http_transport(url, headers, body; timeout)
    response = HTTP.post(
        url,
        headers,
        body;
        status_exception=false,
        readtimeout=ceil(Int, timeout),
        retry=false,
    )
    return (
        response.status,
        [lowercase(String(k)) => String(v) for (k, v) in response.headers],
        String(response.body),
    )
end

"""
    Client(; url, token, timeout = 240, transport = http_transport)

One connection to a MapleStats server. `url` defaults to `MAPLESTATS_URL`, else
the hosted server; `token` to `MAPLESTATS_TOKEN` (only a self-hosted server
started with `MAPLE_AUTH_TOKEN` needs one). The hosted server lets a tool call
run 230 s.
"""
mutable struct Client
    url::String
    token::Union{Nothing,String}
    timeout::Float64
    transport::Any
    session::Union{Nothing,String}
    last_id::Int
end

function env_value(name)
    value = get(ENV, name, "")
    return isempty(value) ? nothing : value
end

function Client(; url=nothing, token=nothing, timeout::Real=240, transport=http_transport)
    url = something(url, env_value("MAPLESTATS_URL"), DEFAULT_URL)
    token = something(token, env_value("MAPLESTATS_TOKEN"), Some(nothing))
    return Client(url, token, Float64(timeout), transport, nothing, 0)
end

const DEFAULT_CLIENT = Ref{Union{Nothing,Client}}(nothing)

"""The client the module-level functions use, created on first use."""
function default_client()
    if DEFAULT_CLIENT[] === nothing
        DEFAULT_CLIENT[] = Client()
    end
    return DEFAULT_CLIENT[]
end

function header(headers, name)
    return something((last(p) for p in headers if first(p) == name)..., Some(nothing))
end

function post_message(client::Client, body)
    headers = [
        "content-type" => "application/json",
        "accept" => "application/json, text/event-stream",
        "user-agent" => "maplestats-julia/$(CLIENT_VERSION)",
    ]
    if client.session !== nothing
        push!(headers, "mcp-session-id" => client.session)
        push!(headers, "mcp-protocol-version" => PROTOCOL_VERSION)
    end
    client.token === nothing || push!(headers, "authorization" => "Bearer $(client.token)")

    status, response_headers, text = client.transport(
        client.url, headers, JSON3.write(body); timeout=client.timeout
    )
    if status == 429
        retry = header(response_headers, "retry-after")
        seconds = retry === nothing ? nothing : tryparse(Float64, retry)
        wait = something(retry, "a minute")
        throw(
            MapleStatsError(
                "Rate limited by $(client.url); retry after $(wait) s.", seconds
            ),
        )
    end
    return status, response_headers, text
end

function check_status(client::Client, status, text)
    if status >= 400
        throw(MapleStatsError("HTTP $(status) from $(client.url): $(first(text, 300))"))
    end
end

"""The JSON-RPC response with `request_id` in a JSON or server-sent-events body."""
function parse_message(headers, text, request_id)
    type = something(header(headers, "content-type"), "")
    startswith(type, "application/json") && return JSON3.read(text)
    messages = []
    data = String[]
    for line in [split(text, r"\r?\n"); ""]
        if startswith(line, "data:")
            push!(data, lstrip(line[6:end], ' '))
        elseif isempty(line) && !isempty(data)
            push!(messages, JSON3.read(join(data, "\n")))
            empty!(data)
        end
    end
    for message in messages
        get(message, :id, nothing) == request_id && return message
    end
    throw(MapleStatsError("No response to request $(request_id) in the server's reply."))
end

function next_id!(client::Client)
    client.last_id += 1
    return client.last_id
end

function open_session!(client::Client)
    client.session = nothing
    id = next_id!(client)
    body = Dict(
        "jsonrpc" => "2.0",
        "id" => id,
        "method" => "initialize",
        "params" => Dict(
            "protocolVersion" => PROTOCOL_VERSION,
            "capabilities" => Dict{String,Any}(),
            "clientInfo" =>
                Dict("name" => "maplestats-julia", "version" => CLIENT_VERSION),
        ),
    )
    status, headers, text = post_message(client, body)
    check_status(client, status, text)
    message = parse_message(headers, text, id)
    if haskey(message, :error)
        throw(MapleStatsError(string(get(message.error, :message, "initialize failed"))))
    end
    client.session = header(headers, "mcp-session-id")
    initialized = Dict("jsonrpc" => "2.0", "method" => "notifications/initialized")
    status, _, text = post_message(client, initialized)
    check_status(client, status, text)
    return client
end

function rpc_request(client::Client, method::String, params)
    client.session === nothing && open_session!(client)
    body = Dict{String,Any}(
        "jsonrpc" => "2.0", "id" => next_id!(client), "method" => method, "params" => params
    )
    status, headers, text = post_message(client, body)
    if status == 404 && client.session !== nothing
        # The server drops idle sessions after 5 minutes: open a new one, once.
        open_session!(client)
        body["id"] = next_id!(client)
        status, headers, text = post_message(client, body)
    end
    check_status(client, status, text)
    message = parse_message(headers, text, body["id"])
    if haskey(message, :error)
        throw(MapleStatsError(string(get(message.error, :message, "$(method) failed"))))
    end
    return message.result
end

"""A tools/call result's value: structuredContent, unwrapped, or its text."""
function decode_result(result)
    blocks = get(result, :content, [])
    text = join((string(get(block, :text, "")) for block in blocks), " ")
    if get(result, :isError, false) == true
        throw(MapleStatsError(isempty(text) ? "The tool returned an error." : text))
    end
    structured = get(result, :structuredContent, nothing)
    meta = get(result, :_meta, Dict())
    wrapped = get(get(meta, :fastmcp, Dict()), :wrap_result, false) == true
    if wrapped && is_object(structured) && collect(keys(structured)) == [:result]
        return structured.result
    end
    structured === nothing || return structured
    try
        return JSON3.read(text)
    catch
        return text
    end
end

# What a server before 0.6.0 (call_tool) or before 2026-11-09 (search_tools) says of
# `detail`, word for word. Read from the v0.5.0 server called in memory: "Invalid
# input: boc_get_observations: detail is not a parameter of this tool; parameters: ..."
# (the list is the inner tool's, not call_tool's) and, with lang = "fr", "detail n'est
# pas un paramètre de cet outil". Nothing looser matches: a current server's
# invalid-arguments error for another argument quotes the tool's parameters, and a
# parameter named "details" or an error saying "unknown" or "unexpected" is not this
# refusal.
const DETAIL_REFUSED = r"\bdetail (?:is not a parameter of this tool|n['\x{2019}]est pas un param.tre de cet outil)"i

"""
Whether the server refused `detail` as an argument it does not know. A server older
than the compact search (before 2026-11-09) does this to search_tools, and one older
than 0.6.0 (2026-11-18) to call_tool. Both answer in full anyway, so the call is
repeated once without it. The error must say it in the old server's own words (see
`DETAIL_REFUSED`): any other error that mentions "detail" is the tool's own, and
repeating the call would only hide it.
"""
function rejects_detail(err)
    err isa MapleStatsError || return false
    return occursin(DETAIL_REFUSED, err.message)
end

# `detail` is call_tool's own argument, beside `name` and `arguments`. The server's
# default, "brief", writes a list of six or more rows as CSV text and cuts the
# provenance; "full" keeps the rows as objects. For the server's own tools
# (search_tools, plan_query) a `detail` that was given travels inside the arguments,
# where the tool reads it.
function call_server_tool(
    client::Client,
    name::String,
    arguments::AbstractDict;
    detail::Union{Nothing,AbstractString}=nothing,
)
    if name in DIRECT_TOOLS
        sent = detail === nothing ? arguments : merge(arguments, Dict("detail" => detail))
        params = Dict("name" => name, "arguments" => sent)
        return decode_result(rpc_request(client, "tools/call", params))
    end
    inner = Dict(
        "name" => name, "arguments" => arguments, "detail" => something(detail, "full")
    )
    params = Dict("name" => "call_tool", "arguments" => inner)
    try
        return decode_result(rpc_request(client, "tools/call", params))
    catch err
        rejects_detail(err) || rethrow()
    end
    # A server that does not know `detail` answers in full without it.
    delete!(inner, "detail")
    return decode_result(rpc_request(client, "tools/call", params))
end

as_arguments(kwargs) = Dict{String,Any}(string(k) => v for (k, v) in kwargs)

"""
    search_tools(query; detail = "full", client = default_client()) -> DataFrame

Tools matching a plain-language query, best first. Columns: `name`,
`description`, `arguments` (the one-line signature) and `input_schema` (JSON
text). `detail = "full"` (the default) returns the whole description and
`input_schema`, with `arguments` missing; `detail = "brief"` returns a
one-line description and `arguments`, with `input_schema` missing.
"""
function search_tools(
    query::AbstractString; detail::AbstractString="full", client::Client=default_client()
)
    found = try
        call_server_tool(client, "search_tools", Dict("query" => query, "detail" => detail))
    catch err
        rejects_detail(err) || rethrow()
        call_server_tool(client, "search_tools", Dict("query" => query))
    end
    tools = is_record_list(found) ? found : []
    return DataFrame(;
        name=String[string(get(t, :name, "")) for t in tools],
        description=String[string(get(t, :description, "")) for t in tools],
        arguments=Union{String,Missing}[
            haskey(t, :arguments) ? string(t.arguments) : missing for t in tools
        ],
        input_schema=Union{String,Missing}[
            haskey(t, :inputSchema) ? JSON3.write(t.inputSchema) : missing for t in tools
        ],
    )
end

"""
    plan_query(question; lang = "en", client = default_client())

The tools to call, in order, for a question that may span sources.
"""
function plan_query(question::AbstractString; lang="en", client::Client=default_client())
    return call_server_tool(
        client, "plan_query", Dict("question" => question, "lang" => lang)
    )
end

"""
    call_tool(tool; detail = nothing, client = default_client(), arguments...)

Run a tool and return its result as parsed JSON (provenance included).
`detail = "full"` (what `nothing` means) returns every field, the whole provenance and
each list of rows as objects. `detail = "brief"` returns the server's compact
answer: a list of six or more rows is one CSV text block (`format`, `rows`,
`csv`) and the provenance is cut to what a citation needs. A server older than
0.6.0 answers in full either way. For the server's own tools (`search_tools`,
`plan_query`) a `detail` you pass goes to the tool as one of its arguments.
"""
function call_tool(
    tool::AbstractString;
    detail::Union{Nothing,AbstractString}=nothing,
    client::Client=default_client(),
    kwargs...,
)
    return call_server_tool(client, String(tool), as_arguments(kwargs); detail)
end

"""
    get_data(tool; client = default_client(), arguments...) -> DataFrame

Run a tool and return its rows. The rows are the result's largest list of
objects; a series' observations become one row each, carrying the series'
fields. Nested fields become `parent_child` columns and names are cleaned to
snake_case. Values keep their JSON types: dates stay text. The server is always
asked for `detail = "full"`: a brief result writes six or more rows as CSV text,
which cannot be read as rows, so the frame has every field the server sends.

The frame's metadata holds `"citation"` (a vector of strings), `"provenance"`,
`"left_out"` (fields of the result beside the rows), `"tool"` and
`"arguments"`, with style `:note`: read them with `metadata(df, "citation")`.
"""
function get_data(tool::AbstractString; client::Client=default_client(), kwargs...)
    arguments = as_arguments(kwargs)
    # Notes the server states once for several items are written back in.
    payload = resolve_shared_notes(call_server_tool(client, String(tool), arguments))
    rows, left = rows_and_left_out(payload)
    frame = rows_to_frame(rows)
    metadata!(frame, "citation", result_citation(payload); style=:note)
    metadata!(frame, "provenance", result_provenance(payload); style=:note)
    metadata!(frame, "left_out", Dict(left); style=:note)
    metadata!(frame, "tool", String(tool); style=:note)
    metadata!(frame, "arguments", arguments; style=:note)
    return frame
end

"""
    reproduce_code(tool, arguments; language = "julia", lang = "en", client = default_client())

A script that fetches the same data straight from the publisher. Returns the
server's result: `scripts` (language, code, packages), `source_url`, `method`
and `notes`.
"""
function reproduce_code(
    tool::AbstractString,
    arguments::AbstractDict;
    language="julia",
    lang="en",
    client::Client=default_client(),
)
    return call_server_tool(
        client,
        "reproduce_code",
        Dict(
            "tool_name" => tool,
            "arguments" => arguments,
            "language" => language,
            "lang" => lang,
        ),
    )
end
