"""The server keeps what people ask out of its own logs."""

from __future__ import annotations

import logging

import pytest


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


# FastMCP logs each failure from the module that handles it: tool calls and
# resource reads from server.server, a failed prompt render from
# prompts.function_prompt. A logger's filter only sees records logged on that
# logger itself, so each one needs the scrubbing filter.
_FASTMCP_LOGGERS = ("fastmcp.server.server", "fastmcp.prompts.function_prompt")


@pytest.fixture
def fastmcp_logs(caplog):
    """Capture FastMCP's own loggers, which stop propagating to the root logger."""
    from maplestats_mcp.shared.private_logs import configure_private_logs

    configure_private_logs()
    loggers = [logging.getLogger(name) for name in _FASTMCP_LOGGERS]
    for logger in loggers:
        logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING)
    yield caplog
    for logger in loggers:
        logger.removeHandler(caplog.handler)


def test_the_scrubbing_filter_sits_on_each_logger_fastmcp_reports_failures_from():
    from maplestats_mcp.shared.private_logs import PrivateToolLogs, configure_private_logs

    configure_private_logs()
    configure_private_logs()
    for name in _FASTMCP_LOGGERS:
        filters = logging.getLogger(name).filters
        assert sum(isinstance(f, PrivateToolLogs) for f in filters) == 1, name


async def test_a_failing_prompt_render_keeps_arguments_and_exception_text_out_of_logs(
    fastmcp_logs,
):
    from fastmcp import Client, FastMCP

    server = FastMCP("t")

    @server.prompt
    def failing_prompt(topic: str) -> str:
        raise RuntimeError("private_exception_marker")

    async with Client(server) as client:
        with pytest.raises(Exception, match="failing_prompt"):
            await client.get_prompt("failing_prompt", {"topic": "private_argument_marker"})
    assert "private" not in fastmcp_logs.text
    assert "RuntimeError" in fastmcp_logs.text


async def test_a_failing_resource_read_keeps_the_uri_and_exception_text_out_of_logs(
    fastmcp_logs,
):
    from fastmcp import Client, FastMCP

    server = FastMCP("t")

    @server.resource("docs://private_uri_marker")
    def failing_resource() -> str:
        raise RuntimeError("private_exception_marker")

    async with Client(server) as client:
        with pytest.raises(Exception, match="resource"):
            await client.read_resource("docs://private_uri_marker")
    assert "private" not in fastmcp_logs.text
    assert "RuntimeError" in fastmcp_logs.text


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
