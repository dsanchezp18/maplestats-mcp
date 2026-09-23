"""Environment-variable configuration for hosting.

Namespaced MAPLE_* (not MCP_*) so this server can run on the same host
as another MCP server without an env var collision.
"""

from __future__ import annotations

import os


def get_host() -> str:
    return os.environ.get("MAPLE_HOST", "127.0.0.1")


def get_port() -> int:
    raw = os.environ.get("MAPLE_PORT", "8000")
    try:
        return int(raw)
    except ValueError:
        return 8000


def get_transport() -> str:
    # Local MCP clients launch the package as a stdio subprocess. Hosted
    # deployments set MAPLE_TRANSPORT=http explicitly in their service config.
    raw = os.environ.get("MAPLE_TRANSPORT", "stdio").strip().lower()
    return "stdio" if raw == "stdio" else "http"


def get_auth_token() -> str | None:
    raw = os.environ.get("MAPLE_AUTH_TOKEN", "").strip()
    return raw or None


def get_require_auth() -> bool:
    raw = os.environ.get("MAPLE_REQUIRE_AUTH", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_max_concurrent_requests() -> int:
    raw = os.environ.get("MAPLE_MAX_CONCURRENT_REQUESTS", "8")
    try:
        value = int(raw)
    except ValueError:
        value = 8
    return min(256, max(1, value))


def get_rate_limit_requests() -> int:
    raw = os.environ.get("MAPLE_RATE_LIMIT_REQUESTS", "120")
    try:
        value = int(raw)
    except ValueError:
        value = 120
    return min(10_000, max(0, value))


def get_rate_limit_window_seconds() -> float:
    raw = os.environ.get("MAPLE_RATE_LIMIT_WINDOW_SECONDS", "60")
    try:
        value = float(raw)
    except ValueError:
        value = 60.0
    return min(3600.0, max(1.0, value))


def get_cache_max_entries() -> int:
    """Max entries per TTL bucket in shared/cache.py's process-local cache.

    Some cache keys encode an unbounded combination of caller input
    (e.g. WDS's getDataFromVectorsAndLatestNPeriods keys off the full
    list of vector IDs in one request) rather than a small, self-limiting
    resource id — without a cap, a long-running hosted instance's cache
    grows with usage diversity, not with time.
    """
    raw = os.environ.get("MAPLE_CACHE_MAX_ENTRIES", "2000")
    try:
        value = int(raw)
    except ValueError:
        value = 2000
    return max(1, value)


def get_trust_proxy_headers() -> bool:
    raw = os.environ.get("MAPLE_TRUST_PROXY_HEADERS", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_ssl_certfile() -> str | None:
    raw = os.environ.get("MAPLE_SSL_CERTFILE", "").strip()
    return raw or None


def get_ssl_keyfile() -> str | None:
    raw = os.environ.get("MAPLE_SSL_KEYFILE", "").strip()
    return raw or None
