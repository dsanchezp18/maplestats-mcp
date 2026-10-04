"""Read the Excel and CSV files behind CKAN resources that have no DataStore rows.

Most federal, Ontario and BC datasets are files only: the portal
lists a URL and `datastore_active` is false, so `ckan_datastore_search` has
nothing to query. This module resolves the file itself and reads it as a
table.

The caller never supplies a URL. A resource id goes through `resource_show`
and `package_show` on the portal, the file URL is the one the portal lists
(a relative federal link is resolved against the portal host), and it must
be https on the portal's list of data hosts, again after every redirect.
The download is streamed under a 40 MB cap (shared/file_download.py) and the
real format comes from the file's bytes (shared/file_tables.py), because the
portals' format labels and file names are unreliable: confirmed live
2026-10-02 on every portal read in tests/smoke_test_ckan_files.py.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from maplestats_mcp.modules.ckan import client, constants, licences
from maplestats_mcp.modules.ckan.constants import Portal
from maplestats_mcp.modules.ckan.schemas import (
    FileRows,
    FileSheet,
    FileSource,
    FileStructure,
    SheetSize,
)
from maplestats_mcp.shared import file_download, file_tables
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action, to_bool
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.rate_limiter import TokenBucket, get_limiter

_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TABULAR_FORMATS = frozenset(
    {"csv", "tsv", "xls", "xlsx", "xlsm", "excel", "spreadsheet", "txt", "text", "text/csv"}
)
_TABULAR_SUFFIXES = (".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".txt")
_NOT_TABULAR_FORMATS = frozenset(
    {
        "pdf", "html", "htm", "zip", "gz", "tar", "json", "geojson", "xml", "rdf", "shp", "gpkg",
        "kml", "kmz", "tif", "tiff", "geotif", "jpg", "jpeg", "png", "gif", "doc", "docx", "ppt",
        "pptx", "wms", "wfs", "wmts", "esri rest", "api", "web", "url", "gdb", "ods", "mdb",
        "sqlite", "parquet", "sav", "dta", "sas7bdat", "txt.gz", "csv.gz",
    }
)  # fmt: skip
_DATASTORE_HIDDEN = ("_id", "_full_text")


def host_matcher(portal: Portal) -> Callable[[str], bool]:
    """True for a host that equals an entry of `file_hosts` or matches a `*.suffix` entry."""
    exact = {h for h in portal.file_hosts if not h.startswith("*.")}
    suffixes = tuple(h[1:] for h in portal.file_hosts if h.startswith("*."))

    def allowed(host: str) -> bool:
        lowered = host.lower()
        return lowered in exact or lowered.endswith(suffixes)

    return allowed


def _origin(portal: Portal) -> str:
    parsed = urlparse(portal.base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _buckets(key: str, portal: Portal) -> tuple[CkanConfig, TokenBucket]:
    """The API config (request pacing) and the download bucket for one portal."""
    if portal.shared_bucket:
        rate = 1.0 / portal.download_delay_seconds
        config = CkanConfig(
            source=portal.shared_bucket,
            base_url=portal.base_url,
            rate_limit_per_second=rate,
            rate_limit_capacity=1.0,
            timeout=portal.timeout_seconds,
        )
        return config, get_limiter(portal.shared_bucket, rate=rate, capacity=1.0)
    config = CkanConfig(
        source=f"ckan-resolve-{key}",
        base_url=portal.base_url,
        rate_limit_per_second=1.0 / portal.request_interval_seconds,
        rate_limit_capacity=constants.RESOLVE_BUCKET_CAPACITY,
        timeout=portal.timeout_seconds,
    )
    files = get_limiter(f"ckan-files-{key}", rate=1.0 / portal.download_delay_seconds, capacity=1.0)
    return config, files


def _text(value: Any) -> str | None:
    return client._text(value)


def _file_url(portal: Portal, resource: dict[str, Any], lang: str = "en") -> str:
    raw = (_text(resource.get("url")) or "").strip()
    if not raw:
        raise_localized(
            InvalidInput,
            "ckan_read_resource: this resource has no file URL (it is a record without a "
            "file); see ckan_get_resource.",
            "ckan_read_resource : cette ressource n'a pas d'URL de fichier (c'est une fiche "
            "sans fichier); voir ckan_get_resource.",
            lang,
        )
    url = urljoin(_origin(portal) + "/", raw)
    # Older records list plain-http links (BC's local-government workbooks on
    # www.cscd.gov.bc.ca, 2026-10-02); an allowed host is asked for https
    # instead. Anything else, or a host that does not answer on https, fails.
    parsed = urlparse(url)
    if parsed.scheme == "http" and host_matcher(portal)(parsed.hostname or ""):
        return parsed._replace(scheme="https").geturl()
    return url


def _suffix(url: str) -> str:
    path = unquote(urlparse(url).path).lower()
    return path[path.rfind(".") :] if "." in path.rsplit("/", 1)[-1] else ""


def _check_tabular(declared: str | None, url: str, landing: str | None, lang: str = "en") -> None:
    """Refuse a resource that is plainly not a table before downloading it.

    The file name outranks the portal's label: DFO's NuSEDS "CSV" resource is a
    9.8 MB .zip (confirmed live 2026-10-02), and no byte of it should be fetched.
    """
    fmt = (declared or "").strip().lower().lstrip(".")
    suffix = _suffix(url)
    plain_suffix = suffix.lstrip(".")
    if plain_suffix in _NOT_TABULAR_FORMATS:
        shown = suffix
    elif fmt in _TABULAR_FORMATS or suffix in _TABULAR_SUFFIXES:
        return
    elif fmt in _NOT_TABULAR_FORMATS:
        shown = declared or fmt
    else:
        return
    raise_localized(
        InvalidInput,
        f"ckan_read_resource reads CSV, TSV, XLS and XLSX files; this resource is {shown!r}"
        f" (portal format {declared!r}), which is not parsed"
        + (f" (dataset page: {landing})." if landing else "."),
        f"ckan_read_resource lit les fichiers CSV, TSV, XLS et XLSX ; cette ressource est "
        f"{shown!r} (format indiqué par le portail : {declared!r}), qui n'est pas lu"
        + (f" (page du jeu de données : {landing})." if landing else "."),
        lang,
    )


class _Resolved:
    def __init__(
        self,
        portal_key: str,
        portal: Portal,
        resource: dict[str, Any],
        package: dict[str, Any],
        lang: str,
    ) -> None:
        self.key = portal_key
        self.portal = portal
        self.resource = resource
        self.package = package
        self.lang = lang

    def source(self, url: str) -> FileSource:
        package, resource = self.package, self.resource
        licence_id = _text(package.get("license_id"))
        licence_title = client._translated(package, "license_title", self.lang)
        status = licences.classify(licence_id, licence_title)
        organization = package.get("organization") or {}
        landing = client._dataset_url(self.portal, package, self.lang) if package else None
        title = client._translated(package, "title", self.lang) or package.get("name")
        org_title = client._translated(organization, "title", self.lang) if organization else None
        licence_url = _text(package.get("license_url"))
        shown = licence_title or licence_id or pick(self.lang, "none stated", "aucune indiquée")
        warn = licences.warning(status, shown, licence_url or landing or "", self.lang)
        name = client._translated(resource, "name", self.lang) or _text(resource.get("name"))
        size = client._to_int(resource.get("size"))
        modified = _text(resource.get("last_modified")) or _text(resource.get("metadata_modified"))
        tail = (
            (f", {landing}" if landing else ""),
            (f" ({licence_id})" if licence_id and licence_id != shown else ""),
        )
        citation = pick(
            self.lang,
            f"Source: {org_title or 'publisher not stated'}, "
            f"“{title or 'dataset'}”"
            + tail[0]
            + f". Licence: {shown}"
            + tail[1]
            + (f", modified {modified[:10]}" if modified else "")
            + ".",
            f"Source : {org_title or 'éditeur non indiqué'}, "
            f"« {title or 'jeu de données'} »"
            + tail[0]
            + f". Licence : {shown}"
            + tail[1]
            + (f", modifié le {modified[:10]}" if modified else "")
            + ".",
        )
        return FileSource(
            portal=self.key,
            resource_id=str(resource.get("id") or ""),
            resource_name=name,
            source_url=url,
            declared_format=_text(resource.get("format")),
            size_bytes=size,
            last_modified=modified,
            dataset_id=_text(package.get("id")),
            dataset_title=title,
            landing_page=landing,
            organization=org_title,
            licence_id=licence_id,
            licence_title=licence_title,
            licence_url=licence_url,
            licence_status=status,
            licence_warning=warn,
            citation=citation,
        )

    def limits(self, *notes: str | None) -> str | None:
        parts = [n for n in notes if n]
        if (_text(self.resource.get("url")) or "").lower().startswith("http://"):
            parts.append(
                pick(
                    self.lang,
                    "the portal lists a plain-http link; it was fetched over https",
                    "le portail donne un lien en http simple ; le fichier a été téléchargé en https",
                )
            )
        return "; ".join(parts) or None


async def _resolve(portal_key: str, resource_id: str, lang: str) -> tuple[_Resolved, bool]:
    portal = client._portal(portal_key, lang)
    if portal.file_reader_off_reason:
        raise_localized(
            InvalidInput,
            f"ckan file reader: {portal.file_reader_off_reason}",
            "lecteur de fichiers CKAN : "
            f"{portal.file_reader_off_reason_fr or portal.file_reader_off_reason}",
            lang,
        )
    if not portal.file_hosts:
        raise_localized(
            InvalidInput,
            f"ckan file reader: portal {portal_key!r} has no file hosts configured.",
            f"lecteur de fichiers CKAN : aucun hôte de fichiers n'est configuré pour le "
            f"portail {portal_key!r}.",
            lang,
        )
    rid = resource_id.strip()
    if not _RESOURCE_ID.match(rid):
        raise_localized(
            InvalidInput,
            "ckan_read_resource: resource_id must be a resource id from ckan_get_dataset or "
            "ckan_get_resource (letters, digits, hyphens), not a URL; the file link is "
            "taken from the portal's own record.",
            "ckan_read_resource : resource_id doit être l'identifiant d'une ressource obtenu "
            "avec ckan_get_dataset ou ckan_get_resource (lettres, chiffres, traits d'union), "
            "et non une URL ; le lien du fichier est tiré de la fiche du portail.",
            lang,
        )
    config, _ = _buckets(portal_key, portal)

    async def show_resource() -> Any:
        return await action(config, "resource_show", params={"id": rid}, lang=lang)

    resource, cached_resource = await cached_fetch(
        f"ckan:{portal_key}:files:resource:{rid}",
        constants.CACHE_TTL_RESOURCE_SECONDS,
        show_resource,
    )
    if not isinstance(resource, dict):
        raise_localized(
            UpstreamError,
            f"ckan_read_resource: resource_show for {rid!r} returned no object.",
            f"ckan_read_resource : resource_show n'a renvoyé aucun objet pour {rid!r}.",
            lang,
        )
    package_id = _text(resource.get("package_id"))
    package: dict[str, Any] = {}
    cached_package = True
    if package_id:

        async def show_package() -> Any:
            return await action(config, "package_show", params={"id": package_id}, lang=lang)

        loaded, cached_package = await cached_fetch(
            f"ckan:{portal_key}:files:package:{package_id}",
            constants.CACHE_TTL_PACKAGE_SECONDS,
            show_package,
        )
        package = loaded if isinstance(loaded, dict) else {}
    return _Resolved(portal_key, portal, resource, package, lang), (
        cached_resource and cached_package
    )


async def _fetch_file(resolved: _Resolved, url: str) -> tuple[file_download.Downloaded, bool]:
    portal = resolved.portal
    size = client._to_int(resolved.resource.get("size"))
    if size and size > constants.FILE_MAX_BYTES:
        raise_localized(
            UpstreamError,
            f"ckan_read_resource: the portal lists this file as {size:,} bytes; this reader "
            f"stops at {constants.FILE_MAX_BYTES:,}. Download it from {url}.",
            f"ckan_read_resource : le portail indique que ce fichier fait {size:,} octets; "
            f"ce lecteur s'arrête à {constants.FILE_MAX_BYTES:,}. Téléchargez-le à {url}.",
            resolved.lang,
        )
    _, files_bucket = _buckets(resolved.key, portal)

    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=host_matcher(portal),
            limiter_for=lambda _host: files_bucket,
            max_bytes=constants.FILE_MAX_BYTES,
            context="ckan_read_resource",
        )

    # One key per URL across modules: ab_opendata reads the same open.alberta.ca
    # files, and two keys would hold two copies in the shared byte budget.
    return await file_download.cached_download(
        file_download.cache_key(url), constants.FILE_CACHE_TTL_SECONDS, fetch
    )


def _choose_sheet(
    sizes: list[tuple[str, int, int]], sheet: str | None, fmt: file_tables.FileFormat
) -> tuple[str | None, file_tables.SheetChoice]:
    """The shared sheet policy (shared/file_tables.py), also used by ab_opendata."""
    return file_tables.choose_sheet(sizes, sheet, fmt, "ckan_read_resource")


def _prepare(resolved: _Resolved, declared_check: bool = True) -> str:
    url = _file_url(resolved.portal, resolved.resource, resolved.lang)
    file_download.check_url(url, host_matcher(resolved.portal), "ckan_read_resource")
    if declared_check:
        landing = client._dataset_url(resolved.portal, resolved.package, resolved.lang)
        _check_tabular(
            _text(resolved.resource.get("format")),
            url,
            landing if resolved.package else None,
            resolved.lang,
        )
    return url


def _sniff(body: bytes, resolved: _Resolved, url: str) -> file_tables.FileFormat:
    """The real format, with the file's URL in the error when it is not a table."""
    try:
        return file_tables.detect_format(body, _text(resolved.resource.get("format")))
    except UpstreamError as exc:
        raise_localized(
            UpstreamError,
            f"ckan_read_resource: {url}: {exc}",
            f"ckan_read_resource : le fichier {url} n'a pas pu être lu comme un tableau ({exc})",
            resolved.lang,
        )


def _validate_paging(
    limit: int, offset: int, header_row: int | None, header_rows: int, lang: str = "en"
) -> None:
    if not 1 <= limit <= constants.FILE_ROWS_MAX:
        raise_localized(
            InvalidInput,
            f"ckan_read_resource: limit must be 1 to {constants.FILE_ROWS_MAX}.",
            f"ckan_read_resource : limit doit être entre 1 et {constants.FILE_ROWS_MAX}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            "ckan_read_resource: offset must be 0 or more.",
            "ckan_read_resource : offset doit être 0 ou plus.",
            lang,
        )
    if header_row is not None and header_row < 1:
        raise_localized(
            InvalidInput,
            "ckan_read_resource: header_row is 1-based (1 or more).",
            "ckan_read_resource : header_row commence à 1 (1 ou plus).",
            lang,
        )
    if not 1 <= header_rows <= 5:
        raise_localized(
            InvalidInput,
            "ckan_read_resource: header_rows must be 1 to 5.",
            "ckan_read_resource : header_rows doit être entre 1 et 5.",
            lang,
        )


async def describe_resource(
    portal: str, resource_id: str, sheet: str | None = None, lang: str = "en"
) -> FileStructure:
    resolved, api_cached = await _resolve(portal, resource_id, lang)
    url = _prepare(resolved)
    downloaded, cached = await _fetch_file(resolved, url)
    body = downloaded.body
    fmt = _sniff(body, resolved, url)
    sizes = await run_parse(file_tables.sheet_sizes, body, fmt)
    only = _choose_sheet(sizes, sheet, fmt)[0] if sheet is not None else None
    total, summaries = await run_parse(file_tables.describe, body, fmt, only)
    source = resolved.source(url)
    datastore = resolved.resource.get("datastore_active")
    shown = 1 if only else total
    return FileStructure(
        source=source,
        format=fmt,
        file_bytes=len(body),
        datastore_active=None if datastore is None else to_bool(datastore),
        sheets=[
            FileSheet(
                name=s.name,
                rows=s.rows,
                columns=s.columns,
                header_row=s.header_row,
                header_row_candidates=s.header_candidates,
                column_names=s.column_names,
                preview=s.preview,
            )
            for s in summaries
        ],
        total_sheets=total,
        truncated=len(summaries) < shown,
        provenance=make_provenance(
            source=f"ckan-{portal}",
            url=url,
            cached=cached and api_cached,
            schema_name="ckan.FileStructure",
            freshness=_file_freshness(source, lang),
            coverage=source.licence_warning or source.citation,
            limits=resolved.limits(
                pick(
                    lang,
                    f"described the first {file_tables.MAX_DESCRIBED_SHEETS} of {total} sheets",
                    f"seules les {file_tables.MAX_DESCRIBED_SHEETS} premières feuilles sur "
                    f"{total} sont décrites",
                )
                if len(summaries) < shown
                else None
            ),
            licence=_licence_line(source, lang),
            lang=lang,
        ),
    )


def _file_freshness(source: FileSource, lang: str) -> str:
    hours = constants.FILE_CACHE_TTL_SECONDS // 3600
    if source.last_modified:
        return pick(
            lang,
            f"File modified {source.last_modified[:10]}; cached up to {hours} hours.",
            f"Fichier modifié le {source.last_modified[:10]}; mis en cache jusqu'à {hours} heures.",
        )
    return pick(
        lang,
        f"File modified date not stated; cached up to {hours} hours.",
        f"Date de modification du fichier non indiquée ; mis en cache jusqu'à {hours} heures.",
    )


def _licence_line(source: FileSource, lang: str = "en") -> str:
    shown = (
        source.licence_title or source.licence_id or pick(lang, "none stated", "aucune indiquée")
    )
    base = f"{shown} ({source.licence_id})" if source.licence_id else shown
    return f"{base}. {source.licence_warning}" if source.licence_warning else base


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


async def _read_datastore(
    resolved: _Resolved,
    columns: list[str] | None,
    filters: dict[str, str] | None,
    contains: str | None,
    limit: int,
    offset: int,
) -> FileRows | None:
    """Rows from the portal's DataStore, or None when it answers 404 (use the file)."""
    try:
        result = await client.datastore_search(
            resolved.key,
            str(resolved.resource.get("id")),
            filters=filters,
            query=contains,
            fields=",".join(columns) if columns else None,
            limit=limit,
            offset=offset,
            lang=resolved.lang,
        )
    except NotFound:
        # Confirmed live: some resources keep datastore_active true after the table
        # was dropped, and datastore_search then answers 404; the file still reads.
        return None
    names = [f.id for f in result.fields if f.id not in _DATASTORE_HIDDEN]
    lang = resolved.lang
    source = resolved.source(_file_url(resolved.portal, resolved.resource, lang))
    more = offset + result.returned_count < result.total_count
    return FileRows(
        source=source,
        read_via="datastore",
        format="datastore",
        sheets=[],
        sheet=None,
        sheet_chosen_by="datastore",
        header_row=None,
        all_columns=names,
        columns=names,
        rows=[{n: _cell(r.get(n)) for n in names} for r in result.records],
        total_rows=result.total_count,
        offset=offset,
        truncated=more,
        provenance=make_provenance(
            source=f"ckan-{resolved.key}",
            url=result.provenance.url,
            cached=result.provenance.cached,
            schema_name="ckan.FileRows",
            freshness=pick(
                lang,
                "DataStore rows; the portal's DataStore may differ from its file.",
                "Lignes du DataStore ; le DataStore du portail peut différer de son fichier.",
            ),
            coverage=source.licence_warning or source.citation,
            limits=resolved.limits(
                pick(
                    lang,
                    "DataStore rows (sheet, header_row and header_rows do not apply; filters are "
                    "case-sensitive exact matches, and `contains` is the DataStore's full-text "
                    "search on whole words, not the file reader's substring match)",
                    "lignes du DataStore (sheet, header_row et header_rows ne s'appliquent pas ; "
                    "les filtres sont des correspondances exactes sensibles à la casse, et "
                    "`contains` est la recherche plein texte du DataStore sur des mots entiers, "
                    "et non la recherche de sous-chaîne du lecteur de fichiers)",
                ),
                pick(
                    lang,
                    f"showing rows {offset + 1} to {offset + result.returned_count} of "
                    f"{result.total_count}",
                    f"lignes {offset + 1} à {offset + result.returned_count} sur "
                    f"{result.total_count}",
                )
                if more
                else None,
            ),
            licence=_licence_line(source, lang),
            lang=lang,
        ),
    )


def _sheet_sizes(
    sizes: list[tuple[str, int, int]], fmt: file_tables.FileFormat, width: int
) -> list[SheetSize]:
    """Declared sheet sizes; a CSV declares none, so only its column count is known."""
    if fmt == "csv":
        return [SheetSize(name=name, rows=None, columns=width) for name, _, _ in sizes]
    return [SheetSize(name=n, rows=r, columns=c) for n, r, c in sizes]


def _sheet_list(
    resolved: _Resolved,
    url: str,
    sizes: list[tuple[str, int, int]],
    fmt: file_tables.FileFormat,
    cached: bool,
    offset: int,
) -> FileRows:
    """No rows: the workbook has several comparable sheets and none was requested."""
    lang = resolved.lang
    source = resolved.source(url)
    return FileRows(
        source=source,
        read_via="file",
        format=fmt,
        sheets=[SheetSize(name=n, rows=r, columns=c) for n, r, c in sizes],
        sheet=None,
        sheet_chosen_by="none",
        header_row=None,
        all_columns=[],
        columns=[],
        rows=[],
        total_rows=0,
        offset=offset,
        truncated=False,
        provenance=make_provenance(
            source=f"ckan-{resolved.key}",
            url=url,
            cached=cached,
            schema_name="ckan.FileRows",
            freshness=pick(
                lang,
                f"File modified {(source.last_modified or 'date not stated')[:10]}.",
                f"Fichier modifié le {source.last_modified[:10]}."
                if source.last_modified
                else "Date de modification du fichier non indiquée.",
            ),
            coverage=source.licence_warning or source.citation,
            limits=resolved.limits(
                pick(
                    lang,
                    f"the workbook has {len(sizes)} sheets of similar size and none was "
                    "requested, so no rows were read: pick one from `sheets` and pass it as "
                    "`sheet` (ckan_describe_resource shows each sheet's header and a preview)",
                    f"le classeur compte {len(sizes)} feuilles de taille semblable et aucune "
                    "n'a été demandée, donc aucune ligne n'a été lue : choisissez-en une dans "
                    "`sheets` et passez-la dans `sheet` (ckan_describe_resource montre l'en-tête "
                    "et un aperçu de chaque feuille)",
                )
            ),
            licence=_licence_line(source, lang),
            lang=lang,
        ),
    )


async def read_resource(
    portal: str,
    resource_id: str,
    sheet: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    columns: list[str] | None = None,
    limit: int = constants.FILE_ROWS_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> FileRows:
    _validate_paging(limit, offset, header_row, header_rows, lang)
    resolved, api_cached = await _resolve(portal, resource_id, lang)
    datastore_active = to_bool(resolved.resource.get("datastore_active"))
    if datastore_active and resolved.portal.has_datastore:
        rows = await _read_datastore(resolved, columns, filters, contains, limit, offset)
        if rows is not None:
            return rows
    url = _prepare(resolved)
    downloaded, cached = await _fetch_file(resolved, url)
    body = downloaded.body
    fmt = _sniff(body, resolved, url)
    sizes = await run_parse(file_tables.sheet_sizes, body, fmt)
    if not sizes:
        raise_localized(
            UpstreamError,
            f"ckan_read_resource: {url} has no sheets.",
            f"ckan_read_resource : {url} n'a aucune feuille.",
            lang,
        )
    chosen, how = _choose_sheet(sizes, sheet, fmt)
    if chosen is None:
        return _sheet_list(resolved, url, sizes, fmt, cached and api_cached, offset)
    result = await run_parse(
        file_tables.scan,
        body,
        fmt,
        chosen,
        header_row=header_row,
        header_rows=header_rows,
        columns=columns,
        filters=filters,
        contains=contains,
        offset=offset,
        limit=limit,
    )
    more = offset + limit < result.total_rows
    source = resolved.source(url)
    notes: list[str | None] = []
    if how == "largest":
        notes.append(
            pick(
                lang,
                f"the workbook has {len(sizes)} sheets and none was requested, so the largest "
                f"({chosen!r}) was read; pass sheet= for another",
                f"le classeur compte {len(sizes)} feuilles et aucune n'a été demandée, donc la "
                f"plus grande ({chosen!r}) a été lue ; passez sheet= pour une autre",
            )
        )
    if result.capped:
        notes.append(
            pick(
                lang,
                f"the file was scanned only up to {file_tables.MAX_SCAN_ROWS} rows",
                f"le fichier n'a été parcouru que jusqu'à {file_tables.MAX_SCAN_ROWS} lignes",
            )
        )
    if more:
        notes.append(
            pick(
                lang,
                f"showing rows {offset + 1} to {offset + len(result.rows)} of {result.total_rows}",
                f"lignes {offset + 1} à {offset + len(result.rows)} sur {result.total_rows}",
            )
        )
    if datastore_active and resolved.portal.has_datastore:
        notes.append(
            pick(
                lang,
                "the DataStore answered 404 for this resource, so the file was read",
                "le DataStore a répondu 404 pour cette ressource, donc le fichier a été lu",
            )
        )
    return FileRows(
        source=source,
        read_via="file",
        format=fmt,
        sheets=_sheet_sizes(sizes, fmt, len(result.all_columns)),
        sheet=chosen,
        sheet_chosen_by=how,
        header_row=result.header_row,
        all_columns=result.all_columns,
        columns=result.columns,
        rows=result.rows,
        total_rows=result.total_rows,
        offset=offset,
        truncated=more or result.capped,
        provenance=make_provenance(
            source=f"ckan-{portal}",
            url=url,
            cached=cached and api_cached,
            schema_name="ckan.FileRows",
            freshness=_file_freshness(source, lang),
            coverage=pick(
                lang,
                f"{source.dataset_title or 'dataset'}: {source.resource_name or resource_id}, "
                f"sheet {chosen!r} of {len(sizes)}. ",
                f"{source.dataset_title or 'jeu de données'} : "
                f"{source.resource_name or resource_id}, feuille {chosen!r} sur {len(sizes)}. ",
            )
            + (source.licence_warning or source.citation),
            limits=resolved.limits(*notes),
            licence=_licence_line(source, lang),
            lang=lang,
        ),
    )
