"""Download and filter published CSV files.

Several sources (CER, GC InfoBase) publish data only as CSV files with
the same quirks, confirmed live 2026-09-23: English files are UTF-8
with a BOM, French files are often Windows-1252, some headers carry
trailing spaces, and a mistyped path can answer HTTP 200 with an HTML
page instead of 404. This module handles those once.
"""

from __future__ import annotations

import csv
import io
import ipaddress
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.fr_typography import call_error
from maplestats_mcp.shared.rate_limiter import TokenBucket

MAX_FILE_BYTES = 40 * 1024 * 1024


def decode(body: bytes) -> str:
    """UTF-8 (BOM allowed), else Windows-1252, else latin-1.

    Windows-1252 leaves five byte values undefined (0x81, 0x8d, 0x8f, 0x90,
    0x9d); latin-1 is the last resort so one stray byte never loses a file
    (the same order as shared/file_tables.decode).
    """
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return body.decode("cp1252")
        except UnicodeDecodeError:
            return body.decode("latin-1")


def check_url(url: str, allowed_hosts: Iterable[str], context: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in set(allowed_hosts):
        raise call_error(
            InvalidInput,
            f"{context}: url must be an https link on {sorted(allowed_hosts)}.",
            f"{context} : url doit être un lien https sur {sorted(allowed_hosts)}.",
        )
    if not parsed.path.lower().endswith(".csv"):
        raise call_error(
            InvalidInput,
            f"{context}: url must point to a .csv file.",
            f"{context} : url doit pointer vers un fichier .csv.",
        )


def _public_host(host: str) -> bool:
    """False for localhost and IP-literal hosts.

    The hop rule when the caller names no allow-list: a redirect is how a
    public link would reach a private network, so it is never followed there.
    """
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return False
    try:
        ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return True
    return False


async def fetch_rows(
    url: str,
    *,
    limiter: TokenBucket,
    ttl: int,
    context: str,
    allowed_hosts: Iterable[str] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Every row of a CSV file as a dict, cached for `ttl` seconds, plus was_cached.

    The file is streamed through shared/file_download.download(): a declared
    Content-Length above MAX_FILE_BYTES is refused without reading the body, a
    body that outgrows the cap is aborted mid-stream, and the URL and every
    redirect hop must be https. open.canada.ca download links answer 302 to a
    signed Azure blob URL and legacy neb-one.gc.ca links answer 301 to
    cer-rec.gc.ca (both confirmed live 2026-09-23); the shared client does not
    follow redirects, so download() follows them one hop at a time.

    `allowed_hosts` is the caller's host allow-list, applied to the URL and to
    every redirect hop (list the redirect targets too). Without it, any https
    host is accepted except localhost and IP addresses.
    """
    hosts = None if allowed_hosts is None else frozenset(allowed_hosts)

    def allow_host(host: str) -> bool:
        return _public_host(host) if hosts is None else host in hosts

    async def fetch() -> list[dict[str, str]]:
        downloaded = await file_download.download(
            url,
            allow_host=allow_host,
            limiter_for=lambda _host: limiter,
            max_bytes=MAX_FILE_BYTES,
            context=context,
            timeout=120.0,
        )
        text = decode(downloaded.body)
        # A mistyped path can answer HTTP 200 with an HTML page; only the start is read.
        if text[:1024].lstrip().lower().startswith(("<!doctype", "<html")):
            raise call_error(
                NotFound,
                f"{context}: {url} returned a web page, not a CSV file.",
                f"{context} : {url} a renvoyé une page Web, pas un fichier CSV.",
            )
        return [
            {(k or "").strip(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text))
        ]

    return await cached_fetch(f"csv:{url}", ttl, fetch)


class Columns:
    """Case-insensitive column lookup with a helpful error."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.names = list(rows[0].keys()) if rows else []
        self._by_lower = {c.lower(): c for c in self.names}

    def get(self, name: str) -> str | None:
        return self._by_lower.get(name.strip().lower())

    def require(self, name: str) -> str:
        match = self.get(name)
        if match is None:
            raise call_error(
                InvalidInput,
                f"Unknown column {name!r}; columns are {self.names}.",
                f"Colonne inconnue {name!r} ; les colonnes sont {self.names}.",
            )
        return match

    def first_of(self, candidates: Iterable[str]) -> str | None:
        return next((c for c in (self.get(n) for n in candidates) if c), None)


def exact_filter(
    rows: list[dict[str, str]], columns: Columns, filters: dict[str, str] | None
) -> list[dict[str, str]]:
    wanted = {columns.require(k): v.strip().lower() for k, v in (filters or {}).items()}
    return [
        r for r in rows if all((r.get(c) or "").strip().lower() == v for c, v in wanted.items())
    ]


def select(
    rows: list[dict[str, str]], columns: Columns, names: list[str] | None
) -> tuple[list[str], list[dict[str, str]]]:
    chosen = [columns.require(n) for n in names] if names else columns.names
    return chosen, [{c: r.get(c) or "" for c in chosen} for r in rows]
