"""Environment-variable configuration for hosting.

Namespaced MAPLE_* (not MCP_*) so this server can run on the same host
as another MCP server without an env var collision.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


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


def get_usage_stats_enabled() -> bool:
    """Whether tool calls are counted (names and outcomes only) and /stats is served."""
    raw = os.environ.get("MAPLE_USAGE_STATS", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


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


def get_cache_max_bytes() -> int:
    """Cap on the estimated memory of shared/cache.py's entries, all buckets together.

    MAPLE_CACHE_MAX_MB, default 128: a quarter of a 512 MB free hosting
    instance, leaving room for the interpreter, parsing and file downloads.
    """
    raw = os.environ.get("MAPLE_CACHE_MAX_MB", "128")
    try:
        value = float(raw)
    except ValueError:
        value = 128.0
    return int(max(1.0, value) * 1024**2)


def get_tool_timeout_seconds() -> float:
    """Longest a single tool call may run before it fails with a clear error.

    Retries in shared/http.py can stack three 60-second attempts; a call
    that never answers leaves some MCP clients waiting on a dead request
    and eventually dropping the connection.
    """
    raw = os.environ.get("MAPLE_TOOL_TIMEOUT_SECONDS", "120")
    try:
        value = float(raw)
    except ValueError:
        value = 120.0
    return min(1800.0, max(5.0, value))


def get_parse_workers() -> int:
    """Threads in shared/executor.py's file-parsing pool.

    Kept small: parsing is CPU-bound and the free hosting tier has a
    fraction of one CPU, so more threads only add memory.
    """
    raw = os.environ.get("MAPLE_PARSE_WORKERS", "4")
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return min(32, max(1, value))


def get_parse_timeout_seconds() -> float:
    """Wall-clock budget for one file parse, including the wait for a worker."""
    raw = os.environ.get("MAPLE_PARSE_TIMEOUT_SECONDS", "60")
    try:
        value = float(raw)
    except ValueError:
        value = 60.0
    return min(1800.0, max(1.0, value))


def get_pumf_cache_dir() -> Path:
    """Where PUMF data files are downloaded and extracted for tabulation.

    Defaults to the system temp folder. A hosted deployment should point it
    at a persistent volume, or every restart re-downloads the files (the
    Census 2021 individuals ZIP alone is 182 MB).
    """
    raw = os.environ.get("MAPLE_PUMF_CACHE_DIR", "").strip()
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "maplestats-mcp" / "pumf"


def get_pumf_tabulate_enabled() -> bool:
    """Whether statcan_pumf_tabulate is offered.

    A small hosted instance sets MAPLE_PUMF_TABULATE=0: the tool downloads
    whole PUMF ZIPs (30 to 534 MB) into a disk that free hosts lose on every
    restart. Search, ZIP listings and codebooks need no disk and stay on.
    """
    raw = os.environ.get("MAPLE_PUMF_TABULATE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def get_pumf_cache_max_bytes() -> int:
    """Cap on the PUMF cache; the least recently used files are removed past it."""
    raw = os.environ.get("MAPLE_PUMF_CACHE_MAX_GB", "5")
    try:
        value = float(raw)
    except ValueError:
        value = 5.0
    return int(max(0.5, value) * 1024**3)


def get_delta_max_scan_bytes() -> int:
    """Compressed bytes one statcan_delta_read_table call may stream.

    Measured 2026-10-03 from a home connection: about 2.5 MB/s per range
    request and 5 to 7 MB/s with two or three in flight, so 400 MB fits the
    scan's time ceiling. A host with a faster link can raise it.
    """
    raw = os.environ.get("MAPLE_DELTA_MAX_SCAN_MB", "400")
    try:
        value = float(raw)
    except ValueError:
        value = 400.0
    return int(min(4096.0, max(1.0, value)) * 1024 * 1024)


def get_delta_max_scan_seconds() -> float:
    """Seconds one Delta scan may run, kept 30 s under the tool timeout."""
    raw = os.environ.get("MAPLE_DELTA_MAX_SCAN_SECONDS", "75")
    try:
        value = float(raw)
    except ValueError:
        value = 75.0
    # Never above the tool timeout minus 30 s, even when that leaves less than
    # the 5 s floor (a tool timeout set near its own minimum).
    return min(max(5.0, value), max(1.0, get_tool_timeout_seconds() - 30.0))


def get_delta_index_dir() -> Path | None:
    """Where Delta File scan indexes (resume points) are saved; None keeps them in memory.

    Defaults to the system temp folder; "off" disables the disk copy.
    """
    raw = os.environ.get("MAPLE_DELTA_INDEX_DIR", "").strip()
    if raw.lower() in {"0", "off", "false", "no"}:
        return None
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "maplestats-mcp" / "delta"


def get_ip_horizons_cache_dir() -> Path:
    """Where CIPO IP Horizons patent tables are kept as Parquet for queries.

    Files are fetched only when a patent lookup or search needs them. A
    hosted deployment should point this at a persistent volume, or every
    restart downloads them again (the patent IPC table alone is 740 MB).
    """
    raw = os.environ.get("MAPLE_IP_HORIZONS_CACHE_DIR", "").strip()
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "maplestats-mcp" / "ip_horizons"


def get_ip_horizons_cache_max_bytes() -> int:
    """Cap on the IP Horizons cache; the least recently used files are removed past it."""
    raw = os.environ.get("MAPLE_IP_HORIZONS_CACHE_MAX_GB", "3")
    try:
        value = float(raw)
    except ValueError:
        value = 3.0
    return int(max(0.5, value) * 1024**3)


DEFAULT_ALLOWED_ORIGINS = (
    "https://dsanchezp18.github.io",
    "http://localhost:*",
    "https://localhost:*",
    "http://127.0.0.1:*",
    "https://127.0.0.1:*",
    "http://[::1]:*",
    "https://[::1]:*",
)


def get_allowed_origins() -> tuple[str, ...]:
    """Browser origins allowed to call /mcp (CORS and Origin validation).

    MAPLE_ALLOWED_ORIGINS is a comma-separated list that replaces the
    defaults: the project website plus localhost on any port. Entries may
    use a port wildcard (`http://localhost:*`), a subdomain wildcard
    (`https://*.office.com`, needed for an Office add-in task pane), or
    `*` for any origin. Requests that send no Origin header (desktop
    clients, scripts) are allowed whatever this says.
    """
    raw = os.environ.get("MAPLE_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS
    return tuple(entry.strip() for entry in raw.split(",") if entry.strip())


def get_trust_proxy_headers() -> bool:
    raw = os.environ.get("MAPLE_TRUST_PROXY_HEADERS", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_trusted_proxy_hops() -> int:
    """How many trusted reverse proxies append to X-Forwarded-For (MAPLE_TRUSTED_PROXY_HOPS, default 1)."""
    raw = os.environ.get("MAPLE_TRUSTED_PROXY_HOPS", "1")
    try:
        value = int(raw)
    except ValueError:
        value = 1
    return min(10, max(1, value))


def get_ssl_certfile() -> str | None:
    raw = os.environ.get("MAPLE_SSL_CERTFILE", "").strip()
    return raw or None


def get_ssl_keyfile() -> str | None:
    raw = os.environ.get("MAPLE_SSL_KEYFILE", "").strip()
    return raw or None
