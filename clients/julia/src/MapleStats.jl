"""
    MapleStats

Client for the MapleStats MCP server: Canadian open data with citations.

```julia
using MapleStats
search_tools("unemployment rate Alberta")
df = get_data("boc_get_observations"; series_names=["FXUSDCAD"], recent=5)
metadata(df, "citation")
```
"""
module MapleStats

using DataFrames: DataFrame, metadata, metadata!
using HTTP: HTTP
using JSON3: JSON3
using Unicode: Unicode

export Client, MapleStatsError
export search_tools, plan_query, call_tool, get_data, reproduce_code, default_client
export metadata

include("tidy.jl")
include("client.jl")

end
