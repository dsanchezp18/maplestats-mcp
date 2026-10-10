"""Keep tool arguments and exception text out of FastMCP's error logs."""

from __future__ import annotations

import logging

_TOOL_FAILURE_PREFIXES = ("Error calling tool", "Invalid arguments for tool")


class PrivateToolLogs(logging.Filter):
    """Clients receive the detailed error; logs keep only its exception type.

    FastMCP logs a traceback before our middleware can catch a failure.
    Validation summaries and exception messages can both contain arguments,
    so remove them at the logger, including its cached traceback text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Other warnings on this logger (startup, configuration) stay as written.
        if str(record.msg).startswith(_TOOL_FAILURE_PREFIXES):
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
    logger = logging.getLogger("fastmcp.server.server")
    if not any(isinstance(f, PrivateToolLogs) for f in logger.filters):
        logger.addFilter(PrivateToolLogs())
