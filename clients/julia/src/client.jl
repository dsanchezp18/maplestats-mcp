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
`retry_after` is set (seconds) when the hosted server's limit of 60 requests a
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

function call_server_tool(client::Client, name::String, arguments::AbstractDict)
    params = if name in DIRECT_TOOLS
        Dict("name" => name, "arguments" => arguments)
    else
        Dict(
            "name" => "call_tool",
            "arguments" => Dict("name" => name, "arguments" => arguments),
        )
    end
    return decode_result(rpc_request(client, "tools/call", params))
end

as_arguments(kwargs) = Dict{String,Any}(string(k) => v for (k, v) in kwargs)

"""
    search_tools(query; client = default_client()) -> DataFrame

Tools matching a plain-language query, best first. Columns: `name`,
`description`, `input_schema` (JSON text).
"""
function search_tools(query::AbstractString; client::Client=default_client())
    found = call_server_tool(client, "search_tools", Dict("query" => query))
    tools = is_record_list(found) ? found : []
    return DataFrame(;
        name=String[string(get(t, :name, "")) for t in tools],
        description=String[string(get(t, :description, "")) for t in tools],
        input_schema=String[JSON3.write(get(t, :inputSchema, Dict())) for t in tools],
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
    call_tool(tool; client = default_client(), arguments...)

Run a tool and return its result as parsed JSON (provenance included).
"""
function call_tool(tool::AbstractString; client::Client=default_client(), kwargs...)
    return call_server_tool(client, String(tool), as_arguments(kwargs))
end

"""
    get_data(tool; client = default_client(), arguments...) -> DataFrame

Run a tool and return its rows. The rows are the result's largest list of
objects; a series' observations become one row each, carrying the series'
fields. Nested fields become `parent_child` columns and names are cleaned to
snake_case. Values keep their JSON types: dates stay text.

The frame's metadata holds `"citation"` (a vector of strings), `"provenance"`,
`"left_out"` (fields of the result beside the rows), `"tool"` and
`"arguments"`, with style `:note`: read them with `metadata(df, "citation")`.
"""
function get_data(tool::AbstractString; client::Client=default_client(), kwargs...)
    arguments = as_arguments(kwargs)
    raw = call_server_tool(client, String(tool), arguments)
    rows, left = rows_and_left_out(raw)
    frame = rows_to_frame(rows)
    metadata!(frame, "citation", result_citation(raw); style=:note)
    metadata!(frame, "provenance", result_provenance(raw); style=:note)
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
