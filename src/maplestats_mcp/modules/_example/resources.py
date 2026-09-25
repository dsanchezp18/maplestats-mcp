"""Template resources.py. All three patterns below are zero-parameter —
any parameter makes FastMCP treat the function as a ResourceTemplate
instead of a FunctionResource."""

from __future__ import annotations

from fastmcp.resources import resource


@resource("data://example/status")
def example_status() -> str:
    """A small piece of live-ish data exposed as a resource rather than a tool."""
    return "template module, not registered live"


@resource("docs://example/overview")
def example_overview_doc() -> str:
    """Static documentation exposed as a resource."""
    return "This is the template module every new source copies."


@resource("template://example/greeting")
def example_greeting_template() -> str:
    """A resource whose content could be swapped per-deployment via config."""
    return "Hello from the example module template."
