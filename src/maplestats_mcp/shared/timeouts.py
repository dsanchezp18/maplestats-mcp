"""Server-wide cap on how long one tool call may run."""

from __future__ import annotations

from typing import Any

import anyio
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext


class ToolTimeoutMiddleware(Middleware):
    """Fail a tool call that runs past `seconds` instead of letting it hang.

    Applied once here rather than as `timeout=` on each of 160+ @tool
    decorators. The error names the tool so the client can retry or narrow
    the request.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        params = context.message
        name = getattr(params, "name", "tool")
        arguments = getattr(params, "arguments", None) or {}
        # The call_tool meta-tool wraps the real tool; name that one.
        if name == "call_tool" and isinstance(arguments, dict):
            name = arguments.get("name", name)
        try:
            with anyio.fail_after(self.seconds):
                return await call_next(context)
        except TimeoutError as exc:
            raise ToolError(
                f"{name} did not finish within {self.seconds:.0f} s; the upstream source is "
                "slow or unreachable. Try again, or narrow the request."
            ) from exc
