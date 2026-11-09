"""A stdio MCP relay to a hosted MapleStats server that asks for full results.

The maplestats_full arm: the CLI talks to this relay over stdio, and the relay forwards
every JSON-RPC message to the hosted server over streamable HTTP, setting
`"detail": "full"` on every call_tool request so that no answer depends on the model
choosing it. Each call_tool request is logged (tool name and the detail sent) to the file
named by MAPLE_RELAY_LOG, so a run can show that every call carried it.

usage: python -m tests.maple_test.relay_full <url>
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import UTC, datetime
from typing import Any

import httpx

URL = sys.argv[1] if len(sys.argv) > 1 else "https://mcp.maplestats.danielstats.io/mcp"
LOG = os.environ.get("MAPLE_RELAY_LOG")
TRACE = os.environ.get("MAPLE_RELAY_TRACE")  # every message in and out, for debugging
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

client = httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0))
out_lock = threading.Lock()
session: dict[str, str] = {}


def trace(direction: str, text: str) -> None:
    if TRACE:
        with open(TRACE, "a", encoding="utf-8") as fh:
            fh.write(f"{direction} {text[:300]}\n")


def emit(message: Any) -> None:
    trace("OUT", json.dumps(message))
    with out_lock:
        sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def log(entry: dict[str, Any]) -> None:
    if LOG:
        entry["at"] = datetime.now(UTC).isoformat(timespec="seconds")
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def full(message: dict[str, Any]) -> dict[str, Any]:
    """Set detail='full' on a call_tool request; leave every other message as it is."""
    params = message.get("params") or {}
    if message.get("method") == "tools/call" and params.get("name") == "call_tool":
        arguments = params.setdefault("arguments", {})
        arguments["detail"] = "full"
        log({"tool": arguments.get("name"), "detail": arguments["detail"]})
    return message


def forward(message: dict[str, Any]) -> None:
    headers = dict(HEADERS)
    initialize = message.get("method") == "initialize"
    if "id" in session and not initialize:
        headers["Mcp-Session-Id"] = session["id"]
    try:
        with client.stream("POST", URL, json=full(message), headers=headers) as response:
            # The session is the one a successful initialize opens, nothing else.
            if initialize and response.is_success and response.headers.get("mcp-session-id"):
                session["id"] = response.headers["mcp-session-id"]
            kind = response.headers.get("content-type", "")
            if response.status_code == 202 or "id" not in message:
                return
            if response.status_code >= 400:
                body = response.read().decode("utf-8", "replace")[:500]
                raise RuntimeError(f"HTTP {response.status_code}: {body}")
            if "text/event-stream" in kind:
                data: list[str] = []
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].strip())
                    elif not line and data:
                        emit(json.loads("\n".join(data)))
                        data = []
                if data:
                    emit(json.loads("\n".join(data)))
            else:
                emit(json.loads(response.read()))
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:  # an error, not a hang
        if "id" in message:
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32000, "message": str(exc)},
                }
            )


def main() -> None:
    # UTF-8 both ways: Windows defaults to cp1252, which cannot write characters such as
    # "≤" in some tool descriptions, so those results failed (2026-11-09, CKAN searches).
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        trace("IN", line.strip())
        message = json.loads(line)
        # The CLI first probes for a newer protocol's server/discover; answering "method
        # not found" here makes it fall back to initialize, as it does with the server.
        if message.get("method") == "server/discover":
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
            continue
        # initialize sets the session id, so it is forwarded before anything else is sent;
        # notifications go in order too. Requests run in parallel, as the CLI may send several.
        if message.get("method") == "initialize" or "id" not in message:
            forward(message)
        else:
            threading.Thread(target=forward, args=(message,), daemon=True).start()


if __name__ == "__main__":
    main()
