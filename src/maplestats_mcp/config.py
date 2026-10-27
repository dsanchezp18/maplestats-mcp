"""Environment-variable configuration for hosting.

Namespaced MAPLE_* (not MCP_*) so this server can run on the same host
as another MCP server without an env var collision.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger("maplestats_mcp.config")

# Getters run on hot paths (the cache reads its byte cap on every store), so a
# bad value is reported once, not on every call.
_warned: set[tuple[str, str]] = set()


def _warn_unparsable(name: str, raw: str, default: float) -> None:
    if (name, raw) not in _warned:
        _warned.add((name, raw))
        logger.warning(
            "%s=%r is not a number; ignoring it and using the default %s.", name, raw, default
        )


def _env_int(name: str, default: int) -> int:
    """An integer environment variable; unset or empty gives the default, junk warns."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _warn_unparsable(name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """A numeric environment variable; unset or empty gives the default, junk warns."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _warn_unparsable(name, raw, default)
        return default


def get_host() -> str:
    return os.environ.get("MAPLE_HOST", "127.0.0.1")


def get_port() -> int:
    """The HTTP port. An unparsable value raises: falling back to 8000 would bind
    a port the operator did not ask for while health checks probe the one they set."""
    raw = os.environ.get("MAPLE_PORT", "").strip()
    if not raw:
        return 8000
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"MAPLE_PORT={raw!r} is not a port number; set it to an integer."
        ) from None


_serves_http = False


def mark_serving_http() -> None:
    """Record that this process serves HTTP (`uvicorn maplestats_mcp.asgi:app` sets no variable)."""
    global _serves_http
    _serves_http = True


def get_transport() -> str:
    # Local MCP clients launch the package as a stdio subprocess. Hosted
    # deployments set MAPLE_TRANSPORT=http explicitly in their service config.
    # Anything else raises: a misspelling such as "sdtio" must not start an HTTP
    # server while the MCP client waits on stdin.
    raw = os.environ.get("MAPLE_TRANSPORT", "http" if _serves_http else "stdio").strip().lower()
    if raw not in {"stdio", "http"}:
        raise ValueError(f"MAPLE_TRANSPORT={raw!r} is not supported; use 'stdio' or 'http'.")
    return raw


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
    value = _env_int("MAPLE_MAX_CONCURRENT_REQUESTS", 8)
    return min(256, max(1, value))


def get_rate_limit_requests() -> int:
    value = _env_int("MAPLE_RATE_LIMIT_REQUESTS", 120)
    return min(10_000, max(0, value))


def get_rate_limit_window_seconds() -> float:
    value = _env_float("MAPLE_RATE_LIMIT_WINDOW_SECONDS", 60.0)
    return min(3600.0, max(1.0, value))


def get_cache_max_entries() -> int:
    """Max entries per TTL bucket in shared/cache.py's process-local cache.

    Some cache keys encode an unbounded combination of caller input
    (e.g. WDS's getDataFromVectorsAndLatestNPeriods keys off the full
    list of vector IDs in one request) rather than a small, self-limiting
    resource id — without a cap, a long-running hosted instance's cache
    grows with usage diversity, not with time.
    """
    value = _env_int("MAPLE_CACHE_MAX_ENTRIES", 2000)
    return max(1, value)


def get_cache_max_bytes() -> int:
    """Cap on the estimated memory of shared/cache.py's entries, all buckets together.

    MAPLE_CACHE_MAX_MB, default 128: a quarter of a 512 MB free hosting
    instance, leaving room for the interpreter, parsing and file downloads.
    """
    value = _env_float("MAPLE_CACHE_MAX_MB", 128.0)
    return int(max(1.0, value) * 1024**2)


def get_tool_timeout_seconds() -> float:
    """Longest a single tool call may run before it fails with a clear error.

    Retries in shared/http.py can stack three 60-second attempts; a call
    that never answers leaves some MCP clients waiting on a dead request
    and eventually dropping the connection.
    """
    value = _env_float("MAPLE_TOOL_TIMEOUT_SECONDS", 120.0)
    return min(1800.0, max(5.0, value))


def get_breaker_enabled() -> bool:
    """Whether shared/breaker.py stops calling an upstream host after repeated failures.

    MAPLE_BREAKER=0 turns it off: every request is sent, however often its
    host failed just before.
    """
    raw = os.environ.get("MAPLE_BREAKER", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def get_breaker_failures() -> int:
    """Failures in a row, within the window, that open a host's breaker (MAPLE_BREAKER_FAILURES)."""
    value = _env_int("MAPLE_BREAKER_FAILURES", 5)
    return min(100, max(1, value))


def get_breaker_window_seconds() -> float:
    """How recent those failures must be (MAPLE_BREAKER_WINDOW_SECONDS, default 300).

    A call to a host that times out takes about 95 s (three 30 s attempts and
    their backoff) and counts once, so a shorter window would rarely see five
    of them from one caller.
    """
    value = _env_float("MAPLE_BREAKER_WINDOW_SECONDS", 300.0)
    return min(3600.0, max(1.0, value))


def get_breaker_cooldown_seconds() -> float:
    """How long an open breaker refuses requests before one probe is let through.

    MAPLE_BREAKER_COOLDOWN_SECONDS, default 60: long enough to spare callers
    the full timeout while a host is down, short enough that a host which
    comes back is used again within a minute.
    """
    value = _env_float("MAPLE_BREAKER_COOLDOWN_SECONDS", 60.0)
    return min(3600.0, max(1.0, value))


def get_parse_workers() -> int:
    """Threads in shared/executor.py's file-parsing pool.

    Kept small: parsing is CPU-bound and the free hosting tier has a
    fraction of one CPU, so more threads only add memory.
    """
    value = _env_int("MAPLE_PARSE_WORKERS", 4)
    return min(32, max(1, value))


def get_parse_timeout_seconds() -> float:
    """Wall-clock budget for one file parse, including the wait for a worker."""
    value = _env_float("MAPLE_PARSE_TIMEOUT_SECONDS", 60.0)
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
    value = _env_float("MAPLE_PUMF_CACHE_MAX_GB", 5.0)
    return int(max(0.5, value) * 1024**3)


def get_delta_max_scan_bytes() -> int:
    """Compressed bytes one statcan_delta_read_table call may stream.

    Measured 2026-10-03 from a home connection: about 2.5 MB/s per range
    request and 5 to 7 MB/s with two or three in flight, so 400 MB fits the
    scan's time ceiling. A host with a faster link can raise it.
    """
    value = _env_float("MAPLE_DELTA_MAX_SCAN_MB", 400.0)
    return int(min(4096.0, max(1.0, value)) * 1024 * 1024)


def get_delta_max_scan_seconds() -> float:
    """Seconds one Delta scan may run, kept 30 s under the tool timeout."""
    value = _env_float("MAPLE_DELTA_MAX_SCAN_SECONDS", 75.0)
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


def get_duckdb_memory_limit() -> str | None:
    """DuckDB's memory limit for queries over downloaded files, e.g. "256MB"; None sets none.

    Beyond the limit DuckDB spills to the temporary folder instead of growing: a
    small hosted instance sets it, a laptop leaves it unset.
    """
    raw = os.environ.get("MAPLE_DUCKDB_MEMORY_LIMIT", "").strip()
    return raw or None


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
    value = _env_float("MAPLE_IP_HORIZONS_CACHE_MAX_GB", 3.0)
    return int(max(0.5, value) * 1024**3)


def get_lode_cache_dir() -> Path:
    """Where StatCan open-database (LODE) archives are unpacked.

    A hosted deployment should point it at a persistent volume, or every
    restart downloads them again.
    """
    raw = os.environ.get("MAPLE_LODE_CACHE_DIR", "").strip()
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "maplestats-mcp" / "lode"


def get_lode_cache_max_bytes() -> int:
    """Cap on the LODE cache (MAPLE_LODE_CACHE_MAX_GB, default 3); least recently used files go first."""
    value = _env_float("MAPLE_LODE_CACHE_MAX_GB", 3.0)
    return int(max(0.5, value) * 1024**3)


def get_cbsa_tariff_cache_dir() -> Path:
    """Where Customs Tariff editions are kept as Parquet (a few MB each).

    Each edition is read from CBSA's Access file once; a hosted deployment
    should point this at a persistent volume, or every restart reads them
    again (about 6 s and 70 MB of memory per edition).
    """
    raw = os.environ.get("MAPLE_CBSA_TARIFF_CACHE_DIR", "").strip()
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "maplestats-mcp" / "cbsa_tariff"


def get_on_fir_cache_dir() -> Path:
    """Where Ontario Financial Information Return years are kept as Parquet.

    Each year is about 10 MB to download and 3 MB as Parquet. A hosted
    deployment should point this at a persistent volume, or every restart
    downloads them again.
    """
    raw = os.environ.get("MAPLE_ON_FIR_CACHE_DIR", "").strip()
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "maplestats-mcp" / "on_fir"


def get_on_fir_cache_max_bytes() -> int:
    """Cap on the FIR cache (MAPLE_ON_FIR_CACHE_MAX_MB, default 500); least recently used years go first."""
    value = _env_float("MAPLE_ON_FIR_CACHE_MAX_MB", 500.0)
    return int(max(50.0, value) * 1024**2)


def get_lode_max_download_bytes(default_mb: float) -> int:
    """Largest LODE archive one call may download (MAPLE_LODE_MAX_DOWNLOAD_MB; 0 turns downloads off)."""
    value = _env_float("MAPLE_LODE_MAX_DOWNLOAD_MB", float(default_mb))
    return int(max(0.0, value) * 1_000_000)


DEFAULT_ALLOWED_ORIGINS = (
    "https://maplestats.danielstats.io",
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


def get_client_ip_header() -> str | None:
    """Header the outermost proxy sets to the client's own address, e.g. "CF-Connecting-IP".

    Used for the per-client rate limit when MAPLE_TRUST_PROXY_HEADERS is on. Set it only
    when every request passes through that proxy; unset by default.
    """
    raw = os.environ.get("MAPLE_CLIENT_IP_HEADER", "").strip()
    if not raw:
        return None
    if not re.fullmatch(r"[A-Za-z0-9-]+", raw):
        raise ValueError(f"MAPLE_CLIENT_IP_HEADER={raw!r} is not a header name.")
    return raw


def get_trusted_proxy_hops() -> int:
    """How many trusted reverse proxies append to X-Forwarded-For (MAPLE_TRUSTED_PROXY_HOPS, default 1)."""
    value = _env_int("MAPLE_TRUSTED_PROXY_HOPS", 1)
    return min(10, max(1, value))


def get_ssl_certfile() -> str | None:
    raw = os.environ.get("MAPLE_SSL_CERTFILE", "").strip()
    return raw or None


def get_ssl_keyfile() -> str | None:
    raw = os.environ.get("MAPLE_SSL_KEYFILE", "").strip()
    return raw or None
