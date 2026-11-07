# Turn a tool result into rows, the way the server's reproduce_workbook does.
# A port of rows_and_left_out() in
# src/maplestats_mcp/modules/reproduce/workbook.py; keep the two in step.
# JSON objects are AbstractDicts (JSON3.Object keeps their key order), arrays
# AbstractVectors and null `nothing`. A flattened record is a vector of
# name => value pairs, so its column order is the result's own.

const Record = Vector{Pair{String,Any}}

is_object(x) = x isa AbstractDict
is_record_list(x) = x isa AbstractVector && !isempty(x) && all(is_object, x)

entries(node::AbstractDict) = Pair{String,Any}[string(k) => v for (k, v) in pairs(node)]
entries(node::Record) = node
without_provenance(node) = filter(p -> first(p) != "provenance", entries(node))

"""Every list of objects in the payload, three levels deep, provenance aside."""
function record_lists(payload)
    found = Any[]
    frontier = Any[payload]
    for _ in 1:4
        next_frontier = Any[]
        for node in frontier
            if is_record_list(node)
                push!(found, node)
            elseif is_object(node)
                append!(next_frontier, last.(without_provenance(node)))
            end
        end
        frontier = next_frontier
    end
    return found
end

scalar_text(v) = v === nothing ? "" : string(v)

"""Nested objects become dotted names; lists become text."""
function flatten_record(record, prefix::String="")
    flat = Record()
    for (key, value) in without_provenance(record)
        name = prefix * key
        if is_object(value)
            append!(flat, flatten_record(value, name * "."))
        elseif value isa AbstractVector
            scalar = !any(v -> v isa AbstractDict || v isa AbstractVector, value)
            text = scalar ? join(scalar_text.(value), "; ") : JSON3.write(value)
            push!(flat, name => text)
        else
            push!(flat, name => value)
        end
    end
    return flat
end

function holds(node, best)
    node === best && return true
    is_object(node) || return false
    return any(p -> holds(last(p), best), without_provenance(node))
end

"""The result's fields outside the rows, by dotted name."""
function left_out(node, best, prefix::String="")
    left = Record()
    is_object(node) || return left
    for (key, value) in without_provenance(node)
        value === best && continue
        name = prefix * key
        if is_object(value) && holds(value, best)
            append!(left, left_out(value, best, name * "."))
        elseif is_object(value)
            push!(left, name => "[object]")
        elseif value isa AbstractVector
            push!(left, name => "[list]")
        else
            push!(left, name => value)
        end
    end
    return left
end

"""Pairs of `inner` replace same-named pairs of `outer` in place; new ones follow."""
function update_record(outer::Record, inner::Record)
    merged = copy(outer)
    for (name, value) in inner
        at = findfirst(p -> first(p) == name, merged)
        if at === nothing
            push!(merged, name => value)
        else
            merged[at] = name => value
        end
    end
    return merged
end

"""FastMCP wraps a list result under "result"."""
function unwrap_result(payload)
    is_object(payload) || return payload
    inner = get_key(payload, "result")
    return inner isa AbstractVector ? inner : payload
end

"""
    rows_and_left_out(payload) -> (rows, left_out)

The table a result holds (its largest list of objects) and what it leaves out.
When each object holds its own list of objects (a series and its
observations), every inner object is one row carrying the outer fields.
"""
function rows_and_left_out(payload)
    payload = unwrap_result(payload)
    lists = record_lists(payload)
    if isempty(lists)
        is_object(payload) || return (Record[], Record())
        single = without_provenance(payload)
        isempty(single) && return (Record[], Record())
        return ([flatten_record(single)], Record())
    end
    best = lists[argmax(length.(lists))]
    left = left_out(payload, best)
    first_row = entries(best[1])
    child_keys = [k for (k, v) in first_row if is_record_list(v)]
    isempty(child_keys) && return ([flatten_record(row) for row in best], left)

    sizes = [
        sum(length(something(get_key(row, k), [])) for row in best) for k in child_keys
    ]
    key = child_keys[argmax(sizes)]
    rows = Record[]
    for parent in best
        outer = flatten_record(filter(p -> first(p) != key, entries(parent)))
        children = something(get_key(parent, key), [])
        append!(rows, [update_record(outer, flatten_record(child)) for child in children])
    end
    return (rows, left)
end

function get_key(node::AbstractDict, key::String)
    for (k, v) in pairs(node)
        string(k) == key && return v
    end
    return nothing
end

"""snake_case, ASCII only, as janitor::clean_names does."""
function clean_name(name::AbstractString)
    plain = filter(isascii, Unicode.normalize(String(name); stripmark=true, compat=true))
    split = replace(plain, r"([a-z0-9])([A-Z])" => s"\1_\2")
    cleaned = strip(replace(lowercase(split), r"[^0-9a-z]+" => "_"), '_')
    return isempty(cleaned) ? "x" : String(cleaned)
end

"""clean_name for each, with names that clean alike numbered from 2."""
function clean_names(names::AbstractVector{<:AbstractString})
    taken = Set{String}()
    out = String[]
    for name in clean_name.(names)
        candidate, suffix = name, 2
        while candidate in taken
            candidate = "$(name)_$(suffix)"
            suffix += 1
        end
        push!(taken, candidate)
        push!(out, candidate)
    end
    return out
end

"""Flat records as a DataFrame: one column per name in first-seen order."""
function rows_to_frame(rows::Vector{Record})
    columns = unique(first(p) for row in rows for p in row)
    frame = DataFrame()
    for (column, name) in zip(columns, clean_names(columns))
        values = map(rows) do row
            at = findfirst(p -> first(p) == column, row)
            value = at === nothing ? missing : last(row[at])
            value === nothing ? missing : value
        end
        frame[!, name] = identity.(values)
    end
    return frame
end

"""The result's provenance, or its first item's for a list result."""
function result_provenance(payload)
    payload = unwrap_result(payload)
    if is_record_list(payload)
        payload = payload[1]
    end
    is_object(payload) || return Dict{String,Any}()
    found = get_key(payload, "provenance")
    return is_object(found) ? found : Dict{String,Any}()
end

function find_citations!(found::Vector{String}, node)
    if is_object(node)
        value = get_key(node, "citation")
        value isa AbstractString && !(value in found) && push!(found, String(value))
        foreach(p -> find_citations!(found, last(p)), entries(node))
    elseif node isa AbstractVector
        foreach(child -> find_citations!(found, child), node)
    end
    return found
end

"""Each distinct citation in the result, else one built from provenance."""
function result_citation(payload)
    found = find_citations!(String[], payload)
    isempty(found) || return found
    source = result_provenance(payload)
    isempty(source) && return String[]
    parts = ["Source: $(something(get_key(source, "source"), "unknown"))."]
    url = get_key(source, "url")
    url === nothing || push!(parts, string(url))
    queried = get_key(source, "queried_at")
    queried === nothing || push!(parts, "(queried $(queried))")
    return [join(parts, " ")]
end
