"""Client for StatCan's LODE open databases: catalogue, downloads, schemas, queries."""

from __future__ import annotations

import csv
import io
import json

import httpx

from maplestats_mcp.modules.statcan.lode import constants, files, pages, reader
from maplestats_mcp.modules.statcan.lode.constants import Database
from maplestats_mcp.modules.statcan.lode.schemas import (
    LodeDatabase,
    LodeDatabaseList,
    LodeDescription,
    LodeField,
    LodeFile,
    LodeFileList,
    LodeLayer,
    LodeMemberPreview,
    LodeQueryResult,
    LodeRelease,
    LodeZipListing,
    Scalar,
    ZipEntry,
)
from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SKIP_DATA = (
    "layout", "source", "provider", "metadata", "dictionary", "summary", "description",
    "classification", "readme", "thumbs", "note", "validation",
)  # fmt: skip
_DATA_EXTENSIONS = (".geojson", ".gpkg", ".csv")


def _database(key: str) -> Database:
    db = constants.BY_KEY.get(key.strip().lower())
    if db is None:
        raise InvalidInput(f"Unknown database {key!r}. Keys: {', '.join(constants.BY_KEY)}.")
    return db


async def _page(url: str) -> str:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"statcan_lode: no page at {url}.") from exc
            raise UpstreamError(
                f"statcan_lode: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"statcan_lode: {url} could not be reached.") from exc
        return response.text

    text, _ = await cached_fetch(f"statcan_lode:{url}", constants.CACHE_TTL_SECONDS, fetch)
    return text


def _licence(db: Database, product: pages.ProductPage | None = None) -> tuple[str, str]:
    if db.group == "open_database" or (product and product.licence):
        return constants.OGL, constants.OGL_URL
    return constants.STATCAN_LICENCE, constants.STATCAN_LICENCE_URL


async def list_databases(lang: str = "en") -> LodeDatabaseList:
    landing_url = constants.LANDING_URL[lang]
    landing = pages.parse_landing(await _page(landing_url))
    by_url = {entry.page_url.rstrip("/"): entry for entry in landing}
    databases: list[LodeDatabase] = []
    for db in constants.DATABASES:
        page_url = db.page_en if lang == "en" else db.page_fr
        entry = by_url.get(page_url.rstrip("/"))
        releases: list[LodeRelease] = list(entry.releases) if entry else []
        description = db.description_en if lang == "en" else db.description_fr
        if not entry:
            # Accessibility products and the NAR are not on the landing page;
            # their product page carries the release date.
            product = pages.parse_product(await _page(page_url), page_url)
            if product.release_date:
                label = f"{product.release_date}"
                releases = [LodeRelease(date=product.release_date, version=None, label=label)]
        dates = sorted((r.date for r in releases if r.date), reverse=True)
        licence, licence_url = _licence(db)
        databases.append(
            LodeDatabase(
                key=db.key,
                catalogue_number=db.catalogue_number,
                title=db.title_en if lang == "en" else db.title_fr,
                group=db.group,
                description=description,
                releases=releases,
                latest_release=dates[0] if dates else None,
                formats=list(db.formats),
                licence=licence,
                licence_url=licence_url,
                page_url=page_url,
                queryable=db.queryable,
            )
        )
    return LodeDatabaseList(
        databases=databases,
        landing_url=landing_url,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=landing_url,
            cached=False,
            schema_name="statcan_lode.LodeDatabaseList",
            freshness="StatCan pages, cached 1 day; databases are released occasionally",
            limits="descriptions are summaries; formats are as last verified",
        ),
    )


async def _product(db: Database, lang: str) -> tuple[pages.ProductPage, str]:
    # Download links are language-neutral; the English page is read for
    # them so a French call needs no second set of parsing rules.
    page_url = db.page_en
    return pages.parse_product(await _page(page_url), page_url), page_url


def _file_note(db: Database, fmt: str, url: str) -> tuple[bool, str | None]:
    if not db.queryable:
        return False, "Too large to download here; use statcan_lode_list_zip and preview_member."
    if fmt == "parquet":
        return False, "GeoParquet is not read; the same data ship as GeoPackage or GeoJSON."
    return True, None


async def list_files(database: str, lang: str = "en", sizes: bool = True) -> LodeFileList:
    db = _database(database)
    product, page_url = await _product(db, lang)
    if not product.downloads:
        raise NotFound(f"No ZIP downloads found on {page_url}; StatCan may have moved them.")
    out: list[LodeFile] = []
    for item in product.downloads:
        fmt = pages.file_format(item.url)
        queryable, note = _file_note(db, fmt, item.url)
        size: int | None = None
        modified: str | None = None
        if sizes:
            await _LIMITER.acquire()
            size, modified = await files.head_size(item.url)
        out.append(
            LodeFile(
                label=item.label,
                url=item.url,
                filename=item.url.rsplit("/", 1)[-1],
                format=fmt,
                size_bytes=size,
                last_modified=modified,
                provinces=pages.file_provinces(item.url),
                queryable=queryable,
                note=note,
            )
        )
    licence, licence_url = _licence(db, product)
    return LodeFileList(
        database=db.key,
        title=db.title_en if lang == "en" else db.title_fr,
        page_url=page_url,
        release_date=product.release_date,
        date_modified=product.date_modified,
        licence=licence,
        licence_url=licence_url,
        files=out,
        max_download_bytes=constants.max_download_bytes(),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=page_url,
            cached=False,
            schema_name="statcan_lode.LodeFileList",
            freshness="StatCan product page, cached 1 day; sizes from HEAD requests",
        ),
    )


def _describe_files(listing: list[LodeFile]) -> str:
    return "; ".join(f"{f.filename} ({f.label})" for f in listing[:20])


def choose_files(
    db: Database, listing: list[LodeFile], file: str | None, province: str | None
) -> tuple[list[LodeFile], bool]:
    """The file or files a query reads, and whether `province` picked them."""
    usable = [f for f in listing if f.queryable]
    if not usable:
        raise InvalidInput(f"{db.key} has no file this tool can read; see statcan_lode_list_files.")
    if file:
        needle = file.strip().lower()
        hits = [f for f in usable if needle in f"{f.filename} {f.label}".lower()]
        if not hits:
            raise InvalidInput(f"No file matches {file!r}. Files: {_describe_files(usable)}.")
        if len(hits) > 1 and not province:
            raise InvalidInput(f"{file!r} matches several files: {_describe_files(hits)}.")
        usable = hits
    per_province = any(f.provinces for f in usable)
    if province:
        code = reader.province_code(province)
        hits = [f for f in usable if code in f.provinces]
        if hits:
            return hits, True
        if per_province:
            have = sorted({p for f in usable for p in f.provinces})
            raise InvalidInput(
                f"{db.key} has no file for {code}. Provinces offered: {', '.join(have)}."
            )
    elif per_province and not file:
        raise InvalidInput(
            f"{db.key} is published as one file per province; pass province (e.g. PE) or file. "
            f"Files: {_describe_files(usable)}."
        )
    if db.default_file and not file:
        hits = [f for f in usable if db.default_file in f"{f.filename} {f.label}".lower()]
        if hits:
            return hits[:1], False
    if len(usable) == 1 or file:
        return usable[:1], False
    raise InvalidInput(f"Pass file to pick one of: {_describe_files(usable)}.")


async def _members(url: str) -> tuple[list[remote_zip.ZipMember], int, bool]:
    async def fetch() -> tuple[list[remote_zip.ZipMember], int]:
        await _LIMITER.acquire()
        return await remote_zip.list_members(url)

    (members, total), was_cached = await cached_fetch(
        f"statcan_lode:zip:{url}", constants.CACHE_TTL_SECONDS, fetch
    )
    return members, total, was_cached


def pick_data_member(
    members: list[remote_zip.ZipMember], wanted: str | None = None, strict: bool = False
) -> remote_zip.ZipMember | None:
    """The ZIP's data file: GeoJSON, else GeoPackage, else CSV (the largest).

    A ZIP with several equally good data files (Spatial Access Measures has
    one CSV per measure) is ambiguous: with strict=True that raises and asks
    for `wanted`, a substring of the member's name.
    """
    candidates = [m for m in members if not m.name.endswith("/")]
    for extension in _DATA_EXTENSIONS:
        pool = [
            m
            for m in candidates
            if m.name.lower().endswith(extension)
            and not any(s in m.name.rsplit("/", 1)[-1].lower() for s in _SKIP_DATA)
        ]
        if wanted:
            pool = [m for m in pool if wanted.strip().lower() in m.name.lower()]
        if not pool:
            continue
        if strict and len(pool) > 1 and not wanted:
            listing = ", ".join(f"{m.name} ({m.size / 1e6:.1f} MB)" for m in pool[:30])
            raise InvalidInput(f"The ZIP has several data files; pass member as one of: {listing}")
        return max(pool, key=lambda m: m.size)
    return None


def _format_of(member: remote_zip.ZipMember) -> str:
    return member.name.rsplit(".", 1)[-1].lower()


async def query(
    database: str,
    *,
    file: str | None = None,
    member: str | None = None,
    province: str | None = None,
    csd: str | None = None,
    type: str | None = None,
    name: str | None = None,
    bbox: list[float] | None = None,
    filters: dict[str, str] | None = None,
    layer: str | None = None,
    limit: int = constants.RECORDS_DEFAULT,
    lang: str = "en",
) -> LodeQueryResult:
    db = _database(database)
    if not db.queryable:
        raise InvalidInput(
            f"{db.key} is too large to download here. Use statcan_lode_list_zip to see its "
            "files and statcan_lode_preview_member to read rows by HTTP range."
        )
    if limit < 0 or limit > constants.RECORDS_MAX:
        raise InvalidInput(f"limit must be between 0 and {constants.RECORDS_MAX}, got {limit}.")
    box: tuple[float, float, float, float] | None = None
    if bbox is not None:
        if len(bbox) != 4:
            raise InvalidInput("bbox needs four numbers: west, south, east, north.")
        box = (bbox[0], bbox[1], bbox[2], bbox[3])
    listing = (await list_files(db.key, lang, sizes=False)).files
    chosen, by_province = choose_files(db, listing, file, province)
    spec = reader.QuerySpec(
        province=None if by_province else province,
        csd=csd,
        type=type,
        name=name,
        bbox=box,
        filters=filters or {},
        limit=limit,
        layer=layer,
    )
    cap = constants.max_download_bytes()
    plan: list[tuple[LodeFile, remote_zip.ZipMember, int]] = []
    to_download = 0
    for item in chosen:
        members, total, _ = await _members(files.check_url(item.url))
        picked = pick_data_member(members, member, strict=True)
        if picked is None:
            raise NotFound(f"No GeoJSON, GeoPackage or CSV data file inside {item.filename}.")
        if picked.size > constants.MAX_MEMBER_BYTES:
            raise InvalidInput(
                f"{picked.name} unpacks to {picked.size / 1e6:,.0f} MB, over the "
                f"{constants.MAX_MEMBER_BYTES / 1e6:,.0f} MB limit."
            )
        if files.cached(item.url, picked.name) is None:
            to_download += total
        plan.append((item, picked, total))
    if to_download > cap:
        raise InvalidInput(
            f"This query needs {to_download / 1e6:,.0f} MB of downloads, over the per-call cap of "
            f"{cap / 1e6:,.0f} MB (MAPLE_LODE_MAX_DOWNLOAD_MB; 0 turns downloads off). "
            "Pick a smaller file, or a province for per-province databases."
        )
    records: list[dict[str, Scalar]] = []
    total_matched = 0
    lower = False
    notes: list[str] = []
    columns: list[str] = []
    downloaded = False
    outcome_layer: str | None = None
    outcome_crs: str | None = None
    for item, data_file, _ in plan:
        path, fresh = await files.local_member(item.url, data_file.name)
        downloaded = downloaded or fresh
        remaining = replace_limit(spec, limit - len(records))
        kind = _format_of(data_file)
        runner = {
            "geojson": reader.query_geojson,
            "gpkg": reader.query_gpkg,
            "csv": reader.query_csv,
        }[kind]
        outcome = await run_in_pool(runner, path, remaining)
        records.extend(outcome.records)
        total_matched += outcome.total
        lower = lower or outcome.lower_bound
        notes.extend(outcome.notes)
        columns = columns or outcome.columns
        outcome_layer = outcome_layer or outcome.layer
        outcome_crs = outcome_crs or outcome.crs
    first_item, first_member, _ = plan[0]
    if len(plan) > 1:
        notes.append(f"Read {len(plan)} files: {', '.join(i.filename for i, _, _ in plan)}.")
    notes.append('StatCan prints ".." for not available; it is returned as null.')
    return LodeQueryResult(
        database=db.key,
        file_url=first_item.url,
        data_member=first_member.name,
        format=_format_of(first_member),
        layer=outcome_layer,
        crs=outcome_crs,
        filters=spec.described() | ({"province": province} if province else {}),
        total_matched=total_matched,
        total_is_lower_bound=lower,
        returned=len(records),
        truncated=len(records) < total_matched,
        columns=columns,
        records=records,
        downloaded=downloaded,
        archive_bytes=sum(t for _, _, t in plan),
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=first_item.url,
            cached=not downloaded,
            schema_name="statcan_lode.LodeQueryResult",
            freshness="read from the unpacked ZIP; downloaded once, then cached on disk",
            limits=f"at most {limit} records returned; downloads capped at {cap / 1e6:,.0f} MB",
        ),
    )


def replace_limit(spec: reader.QuerySpec, limit: int) -> reader.QuerySpec:
    return reader.QuerySpec(
        province=spec.province,
        csd=spec.csd,
        type=spec.type,
        name=spec.name,
        bbox=spec.bbox,
        filters=spec.filters,
        limit=max(0, limit),
        layer=spec.layer,
    )


# --- describe -----------------------------------------------------------


def _is_dictionary(name: str) -> bool:
    base = name.rsplit("/", 1)[-1].lower()
    if not base.endswith(".csv") or base.startswith(("data_sources", "validation")):
        return False
    return "layout" in base or base.endswith("column_descriptions.csv")


def parse_dictionary(text: str) -> list[LodeField]:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if len(rows) < 2:
        return []
    header = [h.strip().lower() for h in rows[0]]
    desc = next((i for i, h in enumerate(header) if "desc" in h), None)
    kind = next((i for i, h in enumerate(header) if "type" in h and i != 0), None)
    out: list[LodeField] = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        out.append(
            LodeField(
                name=row[0].strip(),
                description=row[desc].strip() if desc is not None and desc < len(row) else None,
                type=row[kind].strip() if kind is not None and kind < len(row) else None,
            )
        )
    return out


def _geojson_sample(chunks: list[bytes]) -> list[LodeField]:
    text = b"".join(chunks).decode("utf-8", errors="ignore")
    # The file's "crs" member also has a "properties" key, so look after "features".
    start = text.find('"properties"', max(text.find('"features"'), 0))
    if start < 0:
        return []
    brace = text.find("{", start)
    try:
        props, _ = json.JSONDecoder().raw_decode(text[brace:])
    except ValueError:
        return []
    return [LodeField(name=k, example=reader.tidy(v)) for k, v in props.items()]


def _csv_sample(chunks: list[bytes]) -> list[LodeField]:
    header, rows = files.read_rows(chunks, False, {}, 1)
    row = rows[0] if rows else {}
    return [LodeField(name=h, example=row.get(h)) for h in header if h]


def merge_fields(*groups: list[LodeField]) -> list[LodeField]:
    merged: dict[str, LodeField] = {}
    for group in groups:
        for item in group:
            key = item.name.lower()
            current = merged.get(key)
            if current is None:
                merged[key] = item.model_copy()
                continue
            for attr in ("type", "description", "example"):
                if getattr(current, attr) is None and getattr(item, attr) is not None:
                    setattr(current, attr, getattr(item, attr))
    return list(merged.values())


async def describe(database: str, file: str | None = None, lang: str = "en") -> LodeDescription:
    db = _database(database)
    product, _page_url = await _product(db, lang)
    listing = (await list_files(db.key, lang, sizes=False)).files
    try:
        chosen, _ = choose_files(db, listing, file, None)
    except InvalidInput:
        if file:
            raise
        # Same schema across a database's files: use the smallest-looking one.
        usable = [f for f in listing if f.queryable] or listing
        chosen = [next((f for f in usable if set(f.provinces) & {"YT", "PE", "NT"}), usable[0])]
    item = chosen[0]
    members, total, _ = await _members(files.check_url(item.url))
    entries = [
        ZipEntry(name=m.name, size_bytes=m.size) for m in members if not m.name.endswith("/")
    ]
    data = pick_data_member(members)
    notes: list[str] = []
    sources: list[str] = []
    dictionary: list[LodeField] = []
    for member in members:
        if _is_dictionary(member.name) and member.size < 2_000_000:
            await _LIMITER.acquire()
            raw = await remote_zip.read_member(item.url, member)
            text = raw.decode("utf-8-sig", errors="replace")
            dictionary = parse_dictionary(text)
            if dictionary:
                sources.append(f"dictionary file {member.name}")
                break
    sample: list[LodeField] = []
    layers: list[LodeLayer] = []
    if data is not None:
        kind = _format_of(data)
        if kind in ("csv", "geojson"):
            await _LIMITER.acquire()
            chunks, _, _ = await files.stream_member(item.url, data, 256 * 1024)
            sample = _csv_sample(chunks) if kind == "csv" else _geojson_sample(chunks)
            if sample:
                sources.append(f"first record of {data.name}")
        else:
            local = files.cached(item.url, data.name)
            if local is None and total <= constants.DESCRIBE_DOWNLOAD_BYTES:
                local, _ = await files.local_member(item.url, data.name)
            if local is not None:
                layers = await run_in_pool(reader.gpkg_layers, local)
                sample, _ = await run_in_pool(reader.gpkg_schema, local, None)
                sources.append(f"GeoPackage schema of {data.name}")
            else:
                notes.append(
                    f"{data.name} is a GeoPackage in a {total / 1e6:,.0f} MB archive; its schema "
                    "is read only after statcan_lode_query downloads it. Fields below come from "
                    "the product page."
                )
    page_fields = [LodeField(name=n, description=d) for n, d in product.fields]
    if page_fields:
        sources.append("product page variable list")
    fields = merge_fields(sample, dictionary, page_fields)
    if not fields:
        notes.append("No field list found; see the metadata PDF in the ZIP.")
    return LodeDescription(
        database=db.key,
        title=db.title_en if lang == "en" else db.title_fr,
        file_url=item.url,
        data_member=data.name if data else None,
        format=_format_of(data) if data else None,
        members=entries,
        layers=layers,
        fields=fields,
        field_sources=sources,
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=item.url,
            cached=False,
            schema_name="statcan_lode.LodeDescription",
            limits="read by HTTP range; a GeoPackage is downloaded only when under "
            f"{constants.DESCRIBE_DOWNLOAD_BYTES / 1e6:,.0f} MB",
        ),
    )


# --- zip listing and member preview ---------------------------------------


async def list_zip(url: str) -> LodeZipListing:
    members, total, was_cached = await _members(files.check_url(url))
    return LodeZipListing(
        url=url,
        archive_bytes=total,
        entries=[
            ZipEntry(name=m.name, size_bytes=m.size) for m in members if not m.name.endswith("/")
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_lode.LodeZipListing",
            limits="read with HTTP range requests; the archive itself was not downloaded",
        ),
    )


async def preview_member(
    url: str,
    member: str,
    *,
    match: dict[str, str] | None = None,
    rows: int = 10,
    scan_mb: float = constants.PREVIEW_SCAN_DEFAULT_MB,
) -> LodeMemberPreview:
    if rows < 1 or rows > constants.PREVIEW_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.PREVIEW_ROWS_MAX}, got {rows}.")
    if scan_mb <= 0 or scan_mb > constants.PREVIEW_SCAN_MAX_MB:
        raise InvalidInput(f"scan_mb must be between 0 and {constants.PREVIEW_SCAN_MAX_MB}.")
    members, _, _ = await _members(files.check_url(url))
    wanted = member.strip().lower()
    hits = [m for m in members if m.name.lower() == wanted or m.name.lower().endswith("/" + wanted)]
    if not hits:
        raise NotFound(f"No file {member!r} in the ZIP; see statcan_lode_list_zip.")
    target = hits[0]
    if not target.name.lower().endswith((".csv", ".txt")):
        raise InvalidInput(f"{target.name} is not a text table; only CSV members can be previewed.")
    await _LIMITER.acquire()
    chunks, read, complete = await files.stream_member(url, target, int(scan_mb * 1_000_000))
    columns, found = files.read_rows(chunks, complete, match or {}, rows)
    notes: list[str] = []
    if not complete:
        notes.append(
            f"Read the first {read / 1e6:,.1f} MB (compressed) of {target.compressed_size / 1e6:,.0f} MB; "
            "rows beyond that were not scanned. Raise scan_mb to look further."
        )
    if match and not found:
        notes.append("No row matched in the part scanned.")
    return LodeMemberPreview(
        url=url,
        member=target.name,
        member_bytes=target.size,
        columns=columns,
        rows=found,
        rows_returned=len(found),
        match=match or {},
        compressed_bytes_read=read,
        scan_complete=complete,
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="statcan_lode.LodeMemberPreview",
            limits=f"scanned at most {scan_mb:g} MB of compressed data by HTTP range",
        ),
    )
