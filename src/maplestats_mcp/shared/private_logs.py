"""Keep tool arguments and exception text out of FastMCP's error logs."""

from __future__ import annotations

import logging

# Every FastMCP message on this logger that carries a failed call's arguments:
# tools, resource reads (the URI) and prompt renders.
_CALL_FAILURE_PREFIXES = (
    "Error calling tool",
    "Invalid arguments for tool",
    "Error reading resource",
    "Error rendering prompt",
)

_FASTMCP_LOGGERS = ("fastmcp.server.server", "fastmcp.prompts.function_prompt")


class PrivateToolLogs(logging.Filter):
    """Clients receive the detailed error; logs keep only its exception type.

    FastMCP logs a traceback before our middleware can catch a failure.
    Validation summaries and exception messages can both contain arguments,
    so remove them at the logger, including its cached traceback text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Other warnings on this logger (startup, configuration) stay as written.
        if str(record.msg).startswith(_CALL_FAILURE_PREFIXES):
            kind = (
                record.exc_info[0].__name__
                if record.exc_info and record.exc_info[0]
                else "validation or dispatch"
            )
            record.msg = "MCP tool call failed (%s)"
            record.args = (kind,)
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def configure_private_logs() -> None:
    """Apply to in-process, stdio and hosted servers, once per logger."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # A logger's filters only see records logged on that logger itself, never
    # ones that propagate up from a child, so a filter on "fastmcp" would catch
    # nothing. Name each module FastMCP 4.1 logs a failed call from: tool calls
    # and resource reads from server.server, prompt renders (arguments in the
    # traceback frames) from prompts.function_prompt.
    for name in _FASTMCP_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, PrivateToolLogs) for f in logger.filters):
            logger.addFilter(PrivateToolLogs())
