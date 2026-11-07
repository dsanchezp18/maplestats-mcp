"""A fake MapleStats server that answers from the recorded responses in fixtures/."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from maplestats import Client

FIXTURES = Path(__file__).parent / "fixtures"
SESSION = "test-session"
REQUESTS: dict[str, dict[str, Any]] = json.loads(
    (FIXTURES / "requests.json").read_text(encoding="utf-8")
)


def recorded(name: str, request_id: int) -> str:
    """A recorded SSE body, its JSON-RPC id changed to the one the client sent."""
    text = (FIXTURES / f"{name}.sse").read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith("data:"):
            message = json.loads(line[5:])
            message["id"] = request_id
            line = "data: " + json.dumps(message)
        lines.append(line)
    return "\n".join(lines) + "\n\n"


def fixture_for(params: dict[str, Any]) -> str:
    """Which recording answers a tools/call, matched on tool name and arguments."""
    tool, arguments = params["name"], params["arguments"]
    if tool == "call_tool":
        tool, arguments = arguments["name"], arguments["arguments"]
    # lang="en" is the server's default; the recordings leave it out.
    arguments = {k: v for k, v in arguments.items() if (k, v) != ("lang", "en")}
    for name, request in REQUESTS.items():
        if request["tool"] == tool and request["arguments"] == arguments:
            return name
    raise AssertionError(f"No recording for {tool} {arguments}")


class FakeServer:
    """Records what the client sent; answers from fixtures or an override."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self.override: Callable[[httpx.Request], httpx.Response | None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.override and (response := self.override(request)) is not None:
            return response
        body = json.loads(request.content)
        sse = {"content-type": "text/event-stream"}
        if body["method"] == "initialize":
            headers = {**sse, "mcp-session-id": SESSION}
            return httpx.Response(
                200, headers=headers, text=recorded("initialize", body["id"])
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        assert request.headers.get("mcp-session-id") == SESSION
        name = fixture_for(body["params"])
        return httpx.Response(200, headers=sse, text=recorded(name, body["id"]))

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.seen]


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def client(server: FakeServer) -> Client:
    return Client(url="https://test.invalid/mcp", transport=httpx.MockTransport(server))
