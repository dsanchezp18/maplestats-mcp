# Test fixtures

The Python client's tests run against responses recorded from the hosted server,
stored in `fixtures/` (server-sent events, one file per call), so they need no
network. `fixtures/requests.json` lists the tool and arguments of each case.

Some fixtures are synthetic. These were built offline on 2026-11-26, not
recorded: `boc.sse`, `wds.sse`, `boc_long.sse`, `wds_long.sse`,
`boc_long_brief.sse`, `wds_long_brief.sse`, `wds_two.sse`. The server's own
`call_tool`, response budget and `shape()` (`shared/brief.py`) ran in memory over
models filled by hand, so their structure is what the server sends. `boc.sse` and
`wds.sse` keep the values recorded earlier; every value past those, and all of
`wds_two.sse` (two series, their values and their notes), is illustrative. The
tests that use them check how the client reads that structure, not what the data
say. The other fixtures (`initialize`, `search_tools`, `search_brief`,
`search_none`, `plan_query`, `reproduce`, `tool_error`) are recordings.

To replace all of them with live recordings, run from the repository root:

```bash
uv run python clients/record_fixtures.py
```

It calls the hosted server (`MAPLESTATS_URL` changes the address) and rewrites the
fixtures of all three clients. Run each client's tests afterwards: a test that
asserts a value the synthetic fixtures held (a row count, a series name or a
note) may need updating. The cases and the history of the synthetic ones are
described at the top of `record_fixtures.py`.
