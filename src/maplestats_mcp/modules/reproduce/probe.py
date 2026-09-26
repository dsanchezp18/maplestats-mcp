"""Turn the upstream requests a tool made into a Spec.

reproduce_code runs the tool once while shared/http.py records every
request (URL with all query parameters, POST body, Accept header). The
data request is the last successful one; when a tool paged through the
same endpoint, the first page is used and a note says so. The request is
then fetched once more to confirm what comes back and where the rows sit,
so a script never reads a whole JSON response as a single row.

Checked live 2026-09-25 across the tools in tests/test_reproduce.py:
metadata calls come first (ECCC queryables, DFO station list, Alberta's
table list), so "last successful request" is the data request.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any
from urllib.parse import parse_qsl, unquote_plus, urlparse

import httpx

from maplestats_mcp.modules.reproduce.spec import Spec
from maplestats_mcp.shared.http import RecordedRequest, new_client

_MAX_PROBE_BYTES = 30 * 1024 * 1024
_client = new_client(timeout=120.0, follow_redirects=True)
_SESSION_FIELDS = ("__VIEWSTATE", "__RequestVerificationToken", "__EVENTVALIDATION")


def _path(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def choose(
    requests: list[RecordedRequest], provenance_url: str = ""
) -> tuple[RecordedRequest | None, int]:
    """The data request and how many requests hit the same endpoint.

    The endpoint the result names as its source wins: a search tool that
    then looks up each hit (cer_list_datasets) or checks files with HEAD
    (canadabuys_list_bulk_files) still reproduces the search. Otherwise
    the last successful GET or POST is the data request.
    """
    ok = [
        r
        for r in requests
        if r.status is not None and 200 <= r.status < 300 and r.method in ("GET", "POST")
    ]
    if not ok:
        return None, 0
    named = [r for r in ok if provenance_url and _path(r.url) == _path(provenance_url)]
    target = named[-1] if named else ok[-1]
    # A named web page that the tool mined for an API call (Alberta's
    # dashboard pages hold the data endpoint) loses to that data request.
    data = [r for r in ok if "html" not in r.response_type.lower()]
    if "html" in target.response_type.lower() and data:
        target = data[-1]
    same = [r for r in ok if _path(r.url) == _path(target.url) and r.method == target.method]
    return same[0], len(same)


def _file_name(url: str, extension: str) -> str:
    name = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or "download"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60]
    return name if "." in name else f"{name}.{extension}"


def find_records(payload: Any) -> dict[str, Any]:
    """Where the rows sit in a JSON payload, as Spec field values."""
    if isinstance(payload, list):
        dicts = [item for item in payload if isinstance(item, dict)]
        if dicts and len(dicts) == len(payload):
            inner = dicts[0].get("object")
            # WDS: [{"status": ..., "object": {...}}], one object per request item.
            if isinstance(inner, dict):
                for key, value in inner.items():
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        return {"records_path": ["object", key], "each_item": True}
                return {"record_field": "object"}
            return {}
        return {"unreadable": "a JSON array of non-objects"}
    if not isinstance(payload, dict):
        return {"unreadable": "a JSON value that is not an object or array"}
    features = payload.get("features")
    if isinstance(features, list) and features and isinstance(features[0], dict):
        # ArcGIS REST puts fields under "attributes", GeoJSON under "properties".
        for key in ("attributes", "properties"):
            if isinstance(features[0].get(key), dict):
                return {"records_path": ["features"], "record_field": key}
    best: tuple[int, list[str]] | None = None
    frontier: list[tuple[list[str], Any]] = [([], payload)]
    for _ in range(3):
        next_frontier: list[tuple[list[str], Any]] = []
        for path, node in frontier:
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                    if best is None or len(value) > best[0]:
                        best = (len(value), [*path, key])
                elif isinstance(value, dict):
                    next_frontier.append(([*path, key], value))
        frontier = next_frontier
    if best is not None:
        return {"records_path": best[1]}
    return {"single_object": True}


def _delimiter(sample: str) -> str:
    header = sample.lstrip("﻿").splitlines()[0] if sample.strip() else ""
    counts = {d: header.count(d) for d in (",", "|", "\t", ";")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def _request_fields(request: RecordedRequest) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if request.accept and request.accept != "*/*":
        fields["headers"] = {"Accept": request.accept}
    if request.method == "POST" and request.body:
        if "json" in request.content_type:
            fields["post_json"] = json.loads(request.body)
        else:
            fields["post_form"] = dict(parse_qsl(request.body.decode("utf-8", "replace")))
    return fields


async def _fetch(request: RecordedRequest) -> tuple[str, bytes, bool]:
    """Content type, up to _MAX_PROBE_BYTES of body, and whether it was cut short."""
    headers = {"Accept": request.accept} if request.accept else {}
    if request.body:
        headers["Content-Type"] = request.content_type
    chunks: list[bytes] = []
    size = 0
    truncated = False
    async with _client.stream(
        request.method, request.url, content=request.body or None, headers=headers
    ) as response:
        response.raise_for_status()
        kind = response.headers.get("content-type", "")
        async for chunk in response.aiter_bytes(1 << 16):
            chunks.append(chunk)
            size += len(chunk)
            if size > _MAX_PROBE_BYTES:
                truncated = True
                break
    return kind, b"".join(chunks), truncated


def _html_tables(text: str) -> int:
    return len(re.findall(r"<table\b", text, flags=re.IGNORECASE))


async def spec_from_request(request: RecordedRequest, pages: int) -> Spec:
    fields = _request_fields(request)
    session = [f for f in _SESSION_FIELDS if f in (fields.get("post_form") or {})]
    method = "exact: the request the tool made, recorded while it ran"
    if session:
        return Spec(
            kind="none",
            url=request.url,
            file_name="",
            method=method,
            notes=[
                (
                    "This source answers only inside a browser session (the request carries "
                    f"{', '.join(session)} tokens from an earlier page), so a script cannot "
                    "replay it. Cite the URL and retrieval date, or keep the tool's output as "
                    "the raw input."
                )
            ],
        )
    notes = []
    if pages > 1:
        notes.append(
            f"The tool paged through {pages} requests to this endpoint; the script fetches "
            "the first page. Raise its limit or add an offset loop for every row."
        )
    try:
        content_type, body, truncated = await _fetch(request)
    except httpx.HTTPError as exc:
        return Spec(
            kind="none",
            url=request.url,
            file_name="",
            method=method,
            notes=[f"Replaying the request failed ({exc!r}); the source may need a session."],
        )
    lower = content_type.lower()
    path = urlparse(request.url).path.lower()
    base = {"url": request.url, "method": method, "notes": notes, **fields}
    if "json" in lower or (body[:1] in (b"{", b"[") and "html" not in lower):
        try:
            payload = json.loads(body)
        except ValueError:
            return Spec(kind="file", file_name=_file_name(request.url, "json"), **base)
        if isinstance(payload, str):
            notes.append("The source returns JSON encoded twice; decode the text once more.")
            return Spec(kind="file", file_name=_file_name(request.url, "json"), **base)
        located = find_records(payload)
        if "unreadable" in located:
            notes.append(f"The response is {located.pop('unreadable')}; read it by hand.")
            return Spec(kind="file", file_name=_file_name(request.url, "json"), **base)
        if "/valet/observations/" in request.url:
            located["source"] = "valet"
        return Spec(kind="json", file_name=_file_name(request.url, "json"), **base, **located)
    if path.endswith(".zip") or "zip" in lower:
        return Spec(kind="zip", file_name=_file_name(request.url, "zip"), **base)
    if path.endswith((".xlsx", ".xls")) or "spreadsheet" in lower or "excel" in lower:
        return Spec(kind="xlsx", file_name=_file_name(request.url, "xlsx"), **base)
    if "protobuf" in lower or "protocol-buffer" in lower or path.endswith(".pb"):
        notes.append(
            "GTFS-Realtime protocol buffers: decode with gtfs-realtime-bindings (Python) or "
            "RProtoBuf and the GTFS-RT .proto (R)."
        )
        return Spec(kind="file", file_name=_file_name(request.url, "pb"), **base)
    text = body.decode("utf-8", "replace")
    head = text.lstrip()[:300].lower()
    if head.startswith("<?xml") or "xml" in lower:
        if "<rss" in head or "<feed" in head:
            return Spec(kind="feed", file_name=_file_name(request.url, "xml"), **base)
        notes.append("XML (such as SDMX-ML): read it with xml2 in R or lxml in Python.")
        return Spec(kind="file", file_name=_file_name(request.url, "xml"), **base)
    if "html" in lower or head.startswith(("<!doctype", "<html")):
        count = _html_tables(text)
        if count:
            index = _largest_table(text)
            if count > 1:
                notes.append(
                    f"The page has {count} tables; the script reads the largest (number "
                    f"{index + 1}). Change the index for another."
                )
            return Spec(
                kind="html_table",
                file_name=_file_name(request.url, "html"),
                html_table_index=index,
                **base,
            )
        notes.append(
            "This is a web page the tool parses, not a data table, so a download does not "
            "reproduce the result. Cite the URL and retrieval date, or keep the tool's "
            "output as the raw input."
        )
        return Spec(kind="none", file_name="", **base)
    delimiter = _delimiter(text[:5000])
    sample = list(csv.reader(io.StringIO(text[:5000]), delimiter=delimiter))
    if truncated or (sample and len(sample[0]) > 1):
        header_prefix = "#" if text.lstrip("﻿").startswith("#") else ""
        return Spec(
            kind="csv",
            file_name=_file_name(request.url, "csv"),
            delimiter=delimiter,
            header_prefix=header_prefix,
            **base,
        )
    notes.append("Fixed-width or free text: read it with read_fwf (R) or by column positions.")
    return Spec(kind="file", file_name=_file_name(request.url, "txt"), **base)


def _largest_table(text: str) -> int:
    tables = re.findall(r"<table\b.*?</table>", text, flags=re.IGNORECASE | re.DOTALL)
    rows = [len(re.findall(r"<tr\b", t, flags=re.IGNORECASE)) for t in tables]
    return rows.index(max(rows)) if rows else 0


def unsent_arguments(arguments: dict[str, Any], request: RecordedRequest) -> list[str]:
    """Arguments whose values never reached the source, so the tool applied them."""
    ignored = {"lang", "limit", "offset", "page", "max_return", "include_geometry"}
    sent = unquote_plus(request.url).lower() + request.body.decode("utf-8", "replace").lower()
    unsent = []
    for key, value in arguments.items():
        if key in ignored or value in (None, "", [], {}):
            continue
        values = (
            value.values()
            if isinstance(value, dict)
            else (value if isinstance(value, list) else [value])
        )
        if any(str(v).lower() not in sent for v in values):
            unsent.append(f"{key}={value!r}")
    return unsent
