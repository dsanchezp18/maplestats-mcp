# ============================================================
# Record MCP responses for the client test suites
# Author: Daniel Sanchez
# Purpose: Call the hosted MapleStats server once per test case and save
#          each raw response body (server-sent events), so the Python, R
#          and Julia client tests run without network access.
# Inputs:  The hosted server (MAPLESTATS_URL overrides the address)
# Outputs: fixtures/*.sse and fixtures/requests.json in every client's test
#          folder that exists
# ============================================================

# %% 0. Setup
import json
import os
from pathlib import Path

import httpx

CLIENTS = Path(__file__).parent
URL = os.environ.get("MAPLESTATS_URL", "https://mcp.maplestats.danielstats.io/mcp")
PROTOCOL = "2025-06-18"
FIXTURE_DIRS = [
    CLIENTS / "python" / "tests" / "fixtures",
    CLIENTS / "r" / "tests" / "testthat" / "fixtures",
    CLIENTS / "julia" / "test" / "fixtures",
]

# Each case is one tools/call: the fixture name, the tool the server runs,
# and its arguments. Tools other than search_tools and plan_query go through
# the call_tool proxy, as the clients send them.
CASES = [
    ("search_tools", "search_tools", {"query": "bank of canada exchange rate"}),
    ("search_none", "search_tools", {"query": "zzqx"}),
    ("plan_query", "plan_query", {"question": "Unemployment rate in Alberta"}),
    ("boc", "boc_get_observations", {"series_names": ["FXUSDCAD"], "recent": 3}),
    ("wds", "wds_get_data_from_vectors", {"vector_ids": [2062815], "latest_n": 3}),
    ("tool_error", "boc_get_observations", {"series_names": ["NOPE_XX"], "recent": 3}),
    (
        "reproduce",
        "reproduce_code",
        {
            "tool_name": "boc_get_observations",
            "arguments": {"series_names": ["FXUSDCAD"], "recent": 3},
            "language": "python",
        },
    ),
]
DIRECT = {"search_tools", "plan_query"}


def post(client: httpx.Client, body: dict, session: str | None) -> httpx.Response:
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if session:
        headers["mcp-session-id"] = session
        headers["mcp-protocol-version"] = PROTOCOL
    response = client.post(URL, headers=headers, json=body)
    response.raise_for_status()
    return response


# %% 1. Open a session
http = httpx.Client(timeout=240, headers={"user-agent": "maplestats-fixture-recorder"})
initialize = post(
    http,
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "maplestats-fixture-recorder", "version": "0"},
        },
    },
    None,
)
session = initialize.headers["mcp-session-id"]
post(http, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
bodies = {"initialize": initialize.text}
requests = {}

# %% 2. Record each case
for number, (fixture, tool, arguments) in enumerate(CASES, start=2):
    if tool in DIRECT:
        params = {"name": tool, "arguments": arguments}
    else:
        params = {"name": "call_tool", "arguments": {"name": tool, "arguments": arguments}}
    body = {"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": params}
    bodies[fixture] = post(http, body, session).text
    requests[fixture] = {"tool": tool, "arguments": arguments}

# %% 3. Write fixtures
for folder in FIXTURE_DIRS:
    if not folder.parent.exists():
        continue
    folder.mkdir(exist_ok=True)
    for fixture, text in bodies.items():
        (folder / f"{fixture}.sse").write_text(text, encoding="utf-8", newline="\n")
    manifest = json.dumps(requests, indent=2, ensure_ascii=False) + "\n"
    (folder / "requests.json").write_text(manifest, encoding="utf-8", newline="\n")
