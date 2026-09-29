"""The server keeps what people ask out of its own logs."""

from __future__ import annotations

import logging


def test_http_client_logs_stay_quiet() -> None:
    """httpx logs each upstream URL, with its query string, at INFO; the entrypoint mutes that."""
    import maplestats_mcp.__main__  # noqa: F401  (importing it configures logging)

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name
