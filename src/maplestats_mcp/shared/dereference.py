"""Inline `$ref`s in tool schemas once per schema, not once per request.

fastmcp's DereferenceRefsMiddleware (on by default) rewrites every tool's
input and output schema on each `tools/list`. The BM25 search transform
lists every tool to answer `search_tools` and again to resolve `call_tool`,
so each of those calls dereferenced all ~520 schemas: 0.48 s of CPU per
call, 95% of its time, measured with cProfile on 2026-10-03. The schemas
do not change after startup, so the result is kept per schema object.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import mcp_types as mt
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.middleware.dereference import DereferenceRefsMiddleware
from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext
from fastmcp.tools.base import Tool
from fastmcp.utilities.json_schema import dereference_refs

# More schemas than this means they are being rebuilt per request, so
# caching gains nothing; start over rather than grow without bound.
_MAX_ENTRIES = 8192


class CachedDereferenceMiddleware(DereferenceRefsMiddleware):
    """DereferenceRefsMiddleware with each schema's result remembered.

    Keyed by the schema dict's identity, and the entry keeps that dict
    alive, so an id is never reused for a different schema while cached.
    Tool copies made by transforms share their schema dicts (pydantic's
    model_copy is shallow), so they hit the same entries.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cache: dict[int, tuple[dict[str, Any], dict[str, Any] | None]] = {}

    def _resolved(self, schema: dict[str, Any]) -> dict[str, Any] | None:
        """The dereferenced schema, or None when it has no $ref to inline."""
        entry = self._cache.get(id(schema))
        if entry is not None and entry[0] is schema:
            return entry[1]
        resolved = dereference_refs(schema) if _needs_dereference(schema) else None
        if len(self._cache) >= _MAX_ENTRIES:
            self._cache.clear()
        self._cache[id(schema)] = (schema, resolved)
        return resolved

    def _tool(self, tool: Tool) -> Tool:
        updates: dict[str, object] = {}
        parameters = self._resolved(tool.parameters)
        if parameters is not None:
            updates["parameters"] = parameters
        if tool.output_schema is not None:
            output = self._resolved(tool.output_schema)
            if output is not None:
                updates["output_schema"] = output
        return tool.model_copy(update=updates) if updates else tool

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        return [self._tool(tool) for tool in tools]

    async def on_list_resource_templates(
        self,
        context: MiddlewareContext[mt.ListResourceTemplatesRequest],
        call_next: CallNext[mt.ListResourceTemplatesRequest, Sequence[ResourceTemplate]],
    ) -> Sequence[ResourceTemplate]:
        templates = await call_next(context)
        result = []
        for template in templates:
            parameters = self._resolved(template.parameters)
            if parameters is not None:
                template = template.model_copy(update={"parameters": parameters})
            result.append(template)
        return result


def _needs_dereference(schema: dict[str, Any]) -> bool:
    return "$defs" in schema or _has_ref(schema)


def _has_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_has_ref(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_ref(v) for v in value)
    return False
