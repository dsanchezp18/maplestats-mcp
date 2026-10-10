"""The server keeps what people ask out of its own logs."""

from __future__ import annotations

import logging


def test_http_client_logs_stay_quiet() -> None:
    """httpx logs each upstream URL, with its query string, at INFO; the entrypoint mutes that."""
    import maplestats_mcp.__main__  # noqa: F401  (importing it configures logging)

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


async def test_tool_errors_keep_arguments_in_client_response_only(caplog):
    from fastmcp import Client

    from maplestats_mcp.server import mcp

    marker = "private_argument_marker"
    # FastMCP stops this logger propagating once its logging is configured, so
    # attach the capture handler to the logger itself to make the test order-proof.
    tool_logger = logging.getLogger("fastmcp.server.server")
    tool_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger="fastmcp.server.server")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "call_tool",
            {"name": "wds_get_cube_metadata", "arguments": {"product_id": marker}},
            raise_on_error=False,
        )
        unknown = await client.call_tool(
            "call_tool", {"name": marker, "arguments": {}}, raise_on_error=False
        )
        invalid = await client.call_tool(
            "call_tool",
            {"name": "boc_get_observations", "arguments": {"series_names": marker}},
            raise_on_error=False,
        )
    assert result.is_error and marker in str(result.content)
    assert unknown.is_error and invalid.is_error
    tool_logger.removeHandler(caplog.handler)
    assert marker not in caplog.text
    assert "MCP tool call failed" in caplog.text


def test_unexpected_exception_text_is_not_logged(caplog):
    from maplestats_mcp.shared.private_logs import configure_private_logs

    configure_private_logs()
    logger = logging.getLogger("fastmcp.server.server")
    with caplog.at_level(logging.ERROR, logger=logger.name):
        try:
            raise RuntimeError("private_exception_marker")
        except RuntimeError:
            logger.exception("Error calling tool 'private_tool_marker'")
    assert "private" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_unrelated_warnings_are_not_relabelled():
    from maplestats_mcp.shared.private_logs import PrivateToolLogs

    record = logging.LogRecord("x", logging.WARNING, "f", 1, "Server is unnamed", None, None)
    PrivateToolLogs().filter(record)
    assert record.getMessage() == "Server is unnamed"
