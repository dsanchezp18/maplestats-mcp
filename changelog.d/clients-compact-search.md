### Fixed

- Python, R and Julia clients: `search_tools` (`ms_search_tools` in R) asks the server for `detail="full"`, so its `input_schema` column holds each tool's input schema again instead of `{}` against the compact search. The frame gains an `arguments` column, the one-line signature, filled with `detail="brief"`; the column a response does not carry is null (`NA`, `missing`). Against a server older than the compact search, which rejects `detail`, the clients repeat the search without it. The test fixtures are re-recorded against the hosted server.
