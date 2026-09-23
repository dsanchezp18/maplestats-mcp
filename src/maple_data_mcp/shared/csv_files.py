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
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import httpx

from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import TokenBucket

MAX_FILE_BYTES = 40 * 1024 * 1024


def decode(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp1252")


def check_url(url: str, allowed_hosts: Iterable[str], context: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in set(allowed_hosts):
        raise InvalidInput(f"{context}: url must be an https link on {sorted(allowed_hosts)}.")
    if not parsed.path.lower().endswith(".csv"):
        raise InvalidInput(f"{context}: url must point to a .csv file.")


async def _get_following_redirects(url: str, context: str) -> httpx.Response:
    """GET, following up to 3 https redirects.

    open.canada.ca download links answer 302 to a signed Azure blob URL
    and legacy neb-one.gc.ca links answer 301 to cer-rec.gc.ca (both
    confirmed live 2026-09-23); the shared client does not follow them.
    """
    current = url
    for _ in range(4):
        try:
            return await get_raw(current, timeout=120.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            location = exc.response.headers.get("location")
            if status in (301, 302, 303, 307, 308) and location:
                target = str(exc.response.url.join(location))
                if urlparse(target).scheme != "https":
                    raise UpstreamError(f"{context}: {url} redirected to a non-https URL.") from exc
                current = target
                continue
            if status == 404:
                raise NotFound(f"{context}: no file at {url}.") from exc
            raise UpstreamError(f"{context}: {url} returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"{context}: {url} did not respond in time.") from exc
    raise UpstreamError(f"{context}: {url} redirected too many times.")


async def fetch_rows(
    url: str, *, limiter: TokenBucket, ttl: int, context: str
) -> list[dict[str, str]]:
    """Every row of a CSV file as a dict, cached for `ttl` seconds."""

    async def fetch() -> list[dict[str, str]]:
        await limiter.acquire()
        response = await _get_following_redirects(url, context)
        if len(response.content) > MAX_FILE_BYTES:
            raise UpstreamError(f"{context}: {url} is larger than this tool reads.")
        text = decode(response.content)
        if text.lstrip().lower().startswith(("<!doctype", "<html")):
            raise NotFound(f"{context}: {url} returned a web page, not a CSV file.")
        return [
            {(k or "").strip(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text))
        ]

    rows, _ = await cached_fetch(f"csv:{url}", ttl, fetch)
    return rows


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
            raise InvalidInput(f"Unknown column {name!r}; columns are {self.names}.")
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
