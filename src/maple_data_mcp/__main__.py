"""Entrypoint: `uv run maple-data-mcp` or `python -m maple_data_mcp`.

Transport picked from MAPLE_TRANSPORT (default "http"). stdio bypasses
the ASGI security layer entirely — it's a local-process transport with
no network exposure to protect.
"""

from __future__ import annotations

import logging

from maple_data_mcp import __version__, config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("maple_data_mcp")


def main() -> None:
    transport = config.get_transport()

    if transport == "stdio":
        from maple_data_mcp.server import mcp

        logger.info("Starting MapleData MCP v%s (stdio)", __version__)
        mcp.run(transport="stdio")
        return

    import uvicorn

    from maple_data_mcp.asgi import app

    host = config.get_host()
    port = config.get_port()
    auth_token = config.get_auth_token()
    certfile = config.get_ssl_certfile()
    keyfile = config.get_ssl_keyfile()
    loopback = host in {"127.0.0.1", "localhost", "::1"}

    if config.get_require_auth() and not auth_token:
        raise RuntimeError("MAPLE_REQUIRE_AUTH is set but MAPLE_AUTH_TOKEN is empty.")
    if not loopback and not auth_token:
        logger.warning(
            "MCP HTTP endpoint is bound externally without MAPLE_AUTH_TOKEN; "
            "set a token before exposing it beyond a trusted network."
        )
    if bool(certfile) != bool(keyfile):
        raise RuntimeError("MAPLE_SSL_CERTFILE and MAPLE_SSL_KEYFILE must both be set, or neither.")

    scheme = "https" if certfile else "http"
    logger.info(
        "Starting MapleData MCP v%s on %s:%d (profile=%s)",
        __version__,
        host,
        port,
        config.get_profile(),
    )
    logger.info("MCP endpoint: %s://%s:%d/mcp", scheme, host, port)
    logger.info("Health check: %s://%s:%d/health", scheme, host, port)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )


if __name__ == "__main__":
    main()
