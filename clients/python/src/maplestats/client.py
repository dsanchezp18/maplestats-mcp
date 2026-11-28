"""A small client for the MapleStats MCP endpoint (streamable HTTP, no MCP SDK)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Self

import httpx
import polars as pl

from maplestats._version import __version__
from maplestats.tidy import (
    citations,
    clean_names,
    provenance,
    resolve_shared_notes,
    rows_and_left_out,
)

DEFAULT_URL = "https://mcp.maplestats.danielstats.io/mcp"
PROTOCOL_VERSION = "2025-06-18"

# The hosted server lets a tool call run 230 s; this leaves room for the reply.
DEFAULT_TIMEOUT = 240.0

# The server's own tools, called by name; every other tool goes through call_tool.
_DIRECT_TOOLS = {"search_tools", "plan_query", "call_tool"}


class MapleStatsError(Exception):
    """A tool error, a JSON-RPC error or an HTTP failure, with the server's message."""


class RateLimited(MapleStatsError):
    """HTTP 429: the hosted server allows 120 requests a minute per client."""

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# What a server before 0.6.0 (call_tool) or before 2026-11-09 (search_tools) says of
# `detail`, word for word. Read from the v0.5.0 server called in memory: "Invalid
# input: boc_get_observations: detail is not a parameter of this tool; parameters:
# ..." (the list is the inner tool's, not call_tool's) and, with lang="fr", "detail
# n'est pas un paramètre de cet outil". Nothing looser matches: a current server's
# invalid-arguments error for another argument quotes the tool's parameters, and a
# parameter named "details" or an error saying "unknown" or "unexpected" is not
# this refusal.
_DETAIL_REFUSED = re.compile(
    r"\bdetail (?:is not a parameter of this tool"
    r"|n['’]est pas un param.tre de cet outil)",
    re.IGNORECASE,
)


def _rejects_detail(error: MapleStatsError) -> bool:
    """Whether the server refused `detail` as an argument it does not know.

    A server older than the compact search (before 2026-11-09) does this to
    search_tools, and one older than 0.6.0 (2026-11-18) to call_tool. Both
    answer in full anyway, so the call is repeated once without it. The error
    must say it in the old server's own words (see _DETAIL_REFUSED): any other
    error that mentions "detail" is the tool's own, and repeating the call
    would only hide it.
    """
    return _DETAIL_REFUSED.search(str(error)) is not None


@dataclass
class Result:
    """A tool result as rows, with its source attached."""

    data: pl.DataFrame
    citation: list[str]
    provenance: dict[str, Any]
    left_out: dict[str, Any]
    tool: str
    arguments: dict[str, Any]
    raw: Any = field(repr=False)


def _parse_body(response: httpx.Response, request_id: int) -> dict[str, Any]:
    """The JSON-RPC response in a JSON or server-sent-events body."""
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    messages: list[dict[str, Any]] = []
    data: list[str] = []
    # Not str.splitlines: it also breaks on U+2028, U+0085 and others, which
    # JSON text may hold unescaped; server-sent events end lines at CR or LF only.
    for line in [*re.split(r"\r\n|\r|\n", response.text), ""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif line == "" and data:
            messages.append(json.loads("\n".join(data)))
            data = []
    for message in messages:
        if message.get("id") == request_id:
            return message
    raise MapleStatsError(f"No response to request {request_id} in the server's reply.")


def _decode(result: dict[str, Any]) -> Any:
    """A tools/call result's value: structuredContent, unwrapped, or its text."""
    if result.get("isError"):
        text = " ".join(
            block.get("text", "") for block in result.get("content", []) if block
        )
        raise MapleStatsError(text or "The tool returned an error.")
    structured = result.get("structuredContent")
    wrapped = result.get("_meta", {}).get("fastmcp", {}).get("wrap_result")
    if isinstance(structured, dict) and wrapped and set(structured) == {"result"}:
        return structured["result"]
    if structured is not None:
        return structured
    text = "".join(block.get("text", "") for block in result.get("content", []))
    try:
        return json.loads(text)
    except ValueError:
        return text


class Client:
    """One connection to a MapleStats server.

    url defaults to MAPLESTATS_URL, else the hosted server; token to
    MAPLESTATS_TOKEN (only a self-hosted server started with
    MAPLE_AUTH_TOKEN needs one).
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url or os.environ.get("MAPLESTATS_URL") or DEFAULT_URL
        token = token or os.environ.get("MAPLESTATS_TOKEN")
        headers = {
            "accept": "application/json, text/event-stream",
            "user-agent": f"maplestats-python/{__version__}",
        }
        if token:
            headers["authorization"] = f"Bearer {token}"
        self._http = httpx.Client(timeout=timeout, headers=headers, transport=transport)
        self._session: str | None = None
        self._last_id = 0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # Transport ---------------------------------------------------------------

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        headers = {}
        if self._session:
            headers["mcp-session-id"] = self._session
            headers["mcp-protocol-version"] = PROTOCOL_VERSION
        response = self._http.post(self.url, json=body, headers=headers)
        if response.status_code == 429:
            retry = response.headers.get("retry-after")
            raise RateLimited(
                f"Rate limited by {self.url}; retry after {retry or 'a minute'} s.",
                float(retry) if retry and retry.replace(".", "", 1).isdigit() else None,
            )
        return response

    def _check(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise MapleStatsError(
                f"HTTP {response.status_code} from {self.url}: {response.text[:300]}"
            )

    def _open(self) -> None:
        self._session = None
        self._last_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._last_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "maplestats-python", "version": __version__},
            },
        }
        response = self._post(body)
        self._check(response)
        message = _parse_body(response, self._last_id)
        if "error" in message:
            raise MapleStatsError(message["error"].get("message", "initialize failed"))
        self._session = response.headers.get("mcp-session-id")
        self._check(
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            self._open()
        self._last_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._last_id,
            "method": method,
            "params": params,
        }
        response = self._post(body)
        if response.status_code == 404 and self._session:
            # The server drops idle sessions after 5 minutes: open a new one, once.
            self._open()
            self._last_id += 1
            body["id"] = self._last_id
            response = self._post(body)
        self._check(response)
        message = _parse_body(response, self._last_id)
        if "error" in message:
            raise MapleStatsError(message["error"].get("message", f"{method} failed"))
        return message["result"]

    def _tool(self, name: str, arguments: dict[str, Any], detail: str = "full") -> Any:
        if name in _DIRECT_TOOLS:
            return _decode(
                self._request("tools/call", {"name": name, "arguments": arguments})
            )
        # `detail` is call_tool's own argument, beside `name` and `arguments`.
        # The server's default, "brief", writes a list of six or more rows as
        # CSV text and cuts the provenance; "full" keeps the rows as objects.
        inner: dict[str, Any] = {"name": name, "arguments": arguments, "detail": detail}
        params = {"name": "call_tool", "arguments": inner}
        try:
            return _decode(self._request("tools/call", params))
        except MapleStatsError as error:
            if not _rejects_detail(error):
                raise
        # A server that does not know `detail` answers in full without it.
        del inner["detail"]
        return _decode(self._request("tools/call", params))

    # Public API --------------------------------------------------------------

    def search_tools(self, query: str, detail: str = "full") -> pl.DataFrame:
        """Tools matching a plain-language query, best first.

        Columns: name, description, arguments (the one-line signature) and
        input_schema (JSON text). detail="full" (the default) returns the whole
        description and input_schema, with arguments null; detail="brief"
        returns a one-line description and arguments, with input_schema null.
        """
        try:
            found = self._tool("search_tools", {"query": query, "detail": detail})
        except MapleStatsError as error:
            if not _rejects_detail(error):
                raise
            found = self._tool("search_tools", {"query": query})
        tools = found if isinstance(found, list) else []
        return pl.DataFrame(
            {
                "name": [t.get("name", "") for t in tools],
                "description": [t.get("description", "") for t in tools],
                "arguments": [t.get("arguments") for t in tools],
                "input_schema": [
                    json.dumps(t["inputSchema"]) if "inputSchema" in t else None
                    for t in tools
                ],
            },
            schema={
                "name": pl.String,
                "description": pl.String,
                "arguments": pl.String,
                "input_schema": pl.String,
            },
        )

    def plan_query(self, question: str, lang: str = "en") -> Any:
        """The tools to call, in order, for a question that may span sources."""
        return self._tool("plan_query", {"question": question, "lang": lang})

    def call_tool(
        self, tool: str, /, *, detail: str | None = None, **arguments: Any
    ) -> Any:
        """Run a tool and return its result as decoded JSON (provenance included).

        detail="full" (the default) returns every field, the whole provenance
        and each list of rows as objects. detail="brief" returns the server's
        compact answer: a list of six or more rows is one CSV text block
        ({"format": "csv", "rows": n, "csv": ...}) and the provenance is cut
        to what a citation needs. A server older than 0.6.0 answers in full
        either way. For the server's own tools (search_tools, plan_query) a
        `detail` you pass goes to the tool as one of its arguments.
        """
        if tool in _DIRECT_TOOLS and detail is not None:
            arguments = {**arguments, "detail": detail}
        return self._tool(tool, arguments, detail or "full")

    def get_data(self, tool: str, /, **arguments: Any) -> Result:
        """Run a tool and return its rows as a polars frame, with citation and provenance.

        Always asks the server for detail="full": a brief result writes six or
        more rows as CSV text, which cannot be read as rows.
        """
        raw = self._tool(tool, arguments, "full")
        # Notes the server states once for several items are written back in.
        payload = resolve_shared_notes(raw)
        rows, left_out = rows_and_left_out(payload)
        columns = list(dict.fromkeys(name for row in rows for name in row))
        names = clean_names(columns)
        data = pl.DataFrame(
            {
                new: [row.get(old) for row in rows]
                for old, new in zip(columns, names, strict=True)
            },
            strict=False,
        )
        return Result(
            data=data,
            citation=citations(payload),
            provenance=provenance(payload),
            left_out=left_out,
            tool=tool,
            arguments=arguments,
            raw=raw,
        )

    def reproduce_code(
        self,
        tool: str,
        arguments: dict[str, Any],
        language: str = "python",
        lang: str = "en",
    ) -> Any:
        """A script that fetches the same data straight from the publisher.

        Returns the server's result: scripts (language, code, packages),
        source_url, method and notes.
        """
        return self._tool(
            "reproduce_code",
            {
                "tool_name": tool,
                "arguments": arguments,
                "language": language,
                "lang": lang,
            },
        )
