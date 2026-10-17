"""Entrypoint: `maplestats-mcp` or `python -m maplestats_mcp`.

Transport picked from MAPLE_TRANSPORT (default "stdio"). stdio bypasses
the ASGI security layer entirely — it's a local-process transport with
no network exposure to protect. `--version` prints the version and exits
without starting a server.
"""

from __future__ import annotations

import argparse
import logging

from maplestats_mcp import __version__, config

logging.basicConfig(level=logging.INFO)
# httpx and httpcore log every upstream request at INFO, URL and query string
# included, which would print what people search for. Keep them to warnings.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger("maplestats_mcp")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="maplestats-mcp",
        description="MapleStats MCP server. The transport comes from MAPLE_TRANSPORT.",
    )
    # The bare version, so a bug report can paste it as it is.
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)

    transport = config.get_transport()

    if transport == "stdio":
        from maplestats_mcp.server import mcp

        logger.info("Starting MapleStats MCP v%s (stdio)", __version__)
        mcp.run(transport="stdio")
        return

    import uvicorn

    from maplestats_mcp.asgi import app

    host = config.get_host()
    port = config.get_port()
    certfile = config.get_ssl_certfile()
    keyfile = config.get_ssl_keyfile()

    # The MAPLE_REQUIRE_AUTH refusal and the external-bind warning live in
    # build_asgi_app(), which the import above has already run, so that
    # `uvicorn maplestats_mcp.asgi:app` enforces them too.
    if bool(certfile) != bool(keyfile):
        raise RuntimeError("MAPLE_SSL_CERTFILE and MAPLE_SSL_KEYFILE must both be set, or neither.")

    scheme = "https" if certfile else "http"
    logger.info("Starting MapleStats MCP v%s on %s:%d", __version__, host, port)
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
