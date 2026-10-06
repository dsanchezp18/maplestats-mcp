"""Server-wide cap on how long one tool call may run."""

from __future__ import annotations

from typing import Any

import anyio
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from maplestats_mcp.shared.i18n import pick


class ToolTimeoutMiddleware(Middleware):
    """Fail a tool call that runs past `seconds` instead of letting it hang.

    Applied once here rather than as `timeout=` on each of the 350+ @tool
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
        # A cancel scope rather than fail_after: only this deadline setting
        # cancelled_caught, so a TimeoutError the tool raised itself (an
        # upstream wait giving up) is not mistaken for the deadline running out.
        scope = anyio.CancelScope(deadline=anyio.current_time() + self.seconds)
        with scope:
            return await call_next(context)
        inner = arguments.get("arguments") if isinstance(arguments, dict) else None
        used = inner if isinstance(inner, dict) else arguments
        lang = used.get("lang") if isinstance(used, dict) else None
        raise ToolError(
            pick(
                str(lang or "en"),
                f"{name} did not finish within {self.seconds:.0f} s; the upstream source is "
                "slow or unreachable. Try again, or narrow the request.",
                f"{name} ne s'est pas terminé en {self.seconds:.0f} s ; la source amont est "
                "lente ou inaccessible. Réessayez, ou restreignez la requête.",
            )
        )
