"""Saskatchewan Bureau of Statistics: the files of its products and their Excel tables.

The Bureau publishes through the Publications Centre, whose JSON API lists every
file issued under a product. This module reads the eight products the Bureau's
pages link, lists their files, and reads the Excel ones sheet by sheet with the
shared reader (shared/file_tables.py), as published text.

publications.saskatchewan.ca sends its certificate without the DigiCert Global G2
TLS RSA SHA256 2020 CA1 intermediate (checked with openssl s_client on
2026-11-24). Browsers and Windows curl fetch it themselves from the certificate's
CA Issuers link; Python does not, so the public intermediate is bundled next to
this file and trusted on top of certifi's roots, as ised/ip_horizons does for
opic-cipo.ca.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any, Literal, NoReturn

import certifi
import httpx

from maplestats_mcp.modules.sk_stats import constants
from maplestats_mcp.modules.sk_stats.schemas import (
    FileEntry,
    FileKind,
    FileList,
    FileRows,
    ProductInfo,
    SheetSize,
)
from maplestats_mcp.shared import file_tables as tables
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import decode_json, new_client, stream_capped
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]
Product = Literal[
    "economic_accounts",
    "economic_review",
    "monthly_review",
    "labour_force",
    "cpi",
    "fact_sheets",
    "census",
    "demography",
]
KindChoice = Literal["data_table", "document", "any"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_TLS = ssl.create_default_context(cafile=certifi.where())
_TLS.load_verify_locations(Path(__file__).with_name(constants.INTERMEDIATE_PEM))
_CLIENT = new_client(timeout=120.0, verify=_TLS)


def _fail(cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    raise_localized(cls, f"sk_stats: {en}", f"sk_stats : {fr}", lang)


async def _get(url: str, max_bytes: int, lang: Lang) -> httpx.Response:
    """The whole answer from the Publications Centre, read under `max_bytes`."""
    await _LIMITER.acquire()
    try:
        response = await stream_capped(_CLIENT, url, timeout=120.0, max_bytes=max_bytes)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _fail(
            UpstreamError,
            f"{url} returned HTTP {exc.response.status_code}.",
            f"{url} a répondu par une erreur HTTP {exc.response.status_code}.",
            lang,
        )
    except httpx.HTTPError:
        _fail(
            UpstreamUnavailable,
            f"{url} did not respond in time. Try again shortly.",
            f"{url} n'a pas répondu à temps. Réessayez sous peu.",
            lang,
        )
    return response


def _products(lang: Lang) -> list[ProductInfo]:
    return [
        ProductInfo(
            product=slug,
            product_id=pid,
            title=pick(lang, en, fr),
            page_url=constants.PRODUCT_PAGE_URL.format(product=pid),
        )
        for slug, (pid, en, fr) in constants.PRODUCTS.items()
    ]


async def _product(slug: str, lang: Lang) -> tuple[dict[str, Any], bool]:
    pid = constants.PRODUCTS[slug][0]
    url = constants.PRODUCT_API.format(product=pid)

    async def fetch() -> dict[str, Any]:
        payload = decode_json(await _get(url, constants.MAX_LIST_BYTES, lang), url=url)
        if not isinstance(payload, dict) or not isinstance(payload.get("productFormats"), list):
            _fail(
                UpstreamError,
                f"{url} has no productFormats list; the API may have changed.",
                f"{url} n'a pas de liste productFormats ; l'API a peut-être changé.",
                lang,
            )
        return payload

    return await cached_fetch(f"sk_stats:product:{pid}", constants.CACHE_TTL_LIST_SECONDS, fetch)


def _kind(file_type: str) -> FileKind:
    text = file_type.strip().lower()
    if "excel" in text:
        return "data_table"
    return "document" if text == "pdf" else "other"


def entries(slug: str, payload: dict[str, Any]) -> list[FileEntry]:
    """The product's downloadable files still on offer, newest first."""
    pid = constants.PRODUCTS[slug][0]
    files: list[FileEntry] = []
    for item in payload.get("productFormats") or []:
        if item.get("inactiveTimestamp") or item.get("productFormatMediumType") != "DIGITAL":
            continue
        fid = item.get("productFormatId")
        if not isinstance(fid, int):
            continue
        file_type = str(item.get("productFormatType") or "").strip()
        posted = str(item.get("activeTimestamp") or "")[:10] or None
        files.append(
            FileEntry(
                product=slug,
                format_id=fid,
                title=" ".join(str(item.get("description") or "").split()) or str(fid),
                kind=_kind(file_type),
                format=file_type,
                published=item.get("formatPublicationDate") or posted,
                pages=item.get("pageCount") or None,
                url=constants.DOWNLOAD_URL.format(product=pid, format=fid),
            )
        )
    return sorted(files, key=lambda f: (f.published or "", f.format_id), reverse=True)


def _check_paging(limit: int, offset: int, top: int, lang: Lang) -> None:
    if not 1 <= limit <= top:
        _fail(
            InvalidInput,
            f"limit must be 1 to {top}.",
            f"limit doit être entre 1 et {top}.",
            lang,
        )
    if offset < 0:
        _fail(InvalidInput, "offset must be 0 or more.", "offset doit être 0 ou plus.", lang)


def _provenance(
    url: str, cached: bool, schema: str, coverage: str, limits: str | None, lang: Lang
) -> Provenance:
    return make_provenance(
        source=constants.PROVENANCE_SOURCE,
        url=url,
        cached=cached,
        schema_name=schema,
        freshness=pick(
            lang,
            "As published by the Saskatchewan Bureau of Statistics; file lists cached two "
            "hours, files six.",
            "Tel que publié par le Bureau de la statistique de la Saskatchewan ; listes de "
            "fichiers en cache deux heures, fichiers six heures.",
        ),
        coverage=coverage,
        limits=limits,
        lang=lang,
    )


async def list_files(
    product: Product | None = None,
    query: str | None = None,
    kind: KindChoice = "data_table",
    limit: int = constants.FILES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileList:
    _check_paging(limit, offset, constants.FILES_LIMIT_MAX, lang)
    if product is not None and product not in constants.PRODUCTS:
        _fail(
            InvalidInput,
            f"product must be one of {sorted(constants.PRODUCTS)}.",
            f"product doit être l'un de {sorted(constants.PRODUCTS)}.",
            lang,
        )
    slugs = [product] if product else list(constants.PRODUCTS)
    files: list[FileEntry] = []
    cached = True
    for slug in slugs:
        payload, hit = await _product(slug, lang)
        cached = cached and hit
        files.extend(entries(slug, payload))
    if kind != "any":
        files = [f for f in files if f.kind == kind]
    if query:
        words = query.casefold().split()
        files = [
            f
            for f in files
            if all(w in f"{f.title} {f.product} {f.published or ''}".casefold() for w in words)
        ]
    files.sort(key=lambda f: (f.published or "", f.format_id), reverse=True)
    total = len(files)
    page = files[offset : offset + limit]
    more = offset + len(page) < total
    pid = constants.PRODUCTS[product][0] if product else None
    provenance = _provenance(
        constants.PRODUCT_PAGE_URL.format(product=pid) if pid else constants.BUREAU_URL,
        cached,
        "sk_stats.FileList",
        pick(
            lang,
            f"Files of {len(slugs)} Bureau product(s) in the Publications Centre, newest first.",
            f"Fichiers de {len(slugs)} produit(s) du Bureau au Centre des publications, du plus "
            "récent au plus ancien. Titres en anglais seulement.",
        ),
        pick(
            lang,
            f"files {offset + 1} to {offset + len(page)} of {total}; pass offset="
            f"{offset + len(page)} for more",
            f"fichiers {offset + 1} à {offset + len(page)} sur {total} ; passez offset="
            f"{offset + len(page)} pour la suite",
        )
        if more
        else None,
        lang,
    )
    return FileList(
        products=_products(lang),
        files=page,
        total_files=total,
        offset=offset,
        truncated=more,
        licence=provenance.licence or "",
        provenance=provenance,
    )


async def _find(format_id: int, lang: Lang) -> FileEntry:
    for slug in constants.PRODUCTS:
        payload, _ = await _product(slug, lang)
        for entry in entries(slug, payload):
            if entry.format_id == format_id:
                return entry
    _fail(
        NotFound,
        f"no file {format_id} among the Bureau's products (see sk_stats_list_files).",
        f"aucun fichier {format_id} parmi les produits du Bureau (voir sk_stats_list_files).",
        lang,
    )


def _workbook_format(body: bytes, url: str, lang: Lang) -> tables.FileFormat:
    try:
        fmt = tables.detect_format(body, None)
    except UpstreamError as exc:
        _fail(
            UpstreamError,
            f"{url}: {exc}",
            f"{url} n'est pas un classeur Excel lisible ({exc})",
            lang,
        )
    if fmt == "csv":
        _fail(
            UpstreamError,
            f"{url} did not return an Excel workbook.",
            f"{url} n'a pas renvoyé de classeur Excel.",
            lang,
        )
    return fmt


async def _download(url: str, lang: Lang) -> tuple[bytes, tables.FileFormat, bool]:
    async def fetch() -> tuple[bytes, tables.FileFormat]:
        body = (await _get(url, constants.MAX_FILE_BYTES, lang)).content
        # Sniffed before it is cached: a web page in place of the file (an outage
        # or error page served with HTTP 200) was stored, then rejected on every
        # call for the whole cache window, after the site had recovered.
        return body, _workbook_format(body, url, lang)

    (body, fmt), cached = await cached_fetch(
        f"sk_stats:file:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch
    )
    return body, fmt, cached


async def read_file(
    format_id: int,
    sheet: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileRows:
    _check_paging(limit, offset, constants.ROWS_LIMIT_MAX, lang)
    if header_row is not None and header_row < 1:
        _fail(
            InvalidInput,
            "header_row is 1-based (1 or more).",
            "header_row compte à partir de 1 (1 ou plus).",
            lang,
        )
    if not 1 <= header_rows <= constants.HEADER_ROWS_MAX:
        _fail(
            InvalidInput,
            f"header_rows must be 1 to {constants.HEADER_ROWS_MAX}.",
            f"header_rows doit être entre 1 et {constants.HEADER_ROWS_MAX}.",
            lang,
        )
    entry = await _find(format_id, lang)
    if entry.kind != "data_table":
        _fail(
            InvalidInput,
            f"file {format_id} ({entry.title}) is a {entry.format or 'non-Excel'} file; only "
            f"Excel files are read. Its link: {entry.url}",
            f"le fichier {format_id} ({entry.title}) est de type {entry.format or 'autre'} ; "
            f"seuls les fichiers Excel sont lus. Son lien : {entry.url}",
            lang,
        )
    body, fmt, cached = await _download(entry.url, lang)
    sizes = await run_parse(tables.sheet_sizes, body, fmt)
    if not sizes:
        _fail(
            UpstreamError,
            f"{entry.url} has no sheets.",
            f"{entry.url} ne contient aucune feuille.",
            lang,
        )
    chosen, how = tables.choose_sheet(sizes, sheet, fmt, "sk_stats")
    sheet_sizes = [SheetSize(name=n, rows=r, columns=c) for n, r, c in sizes]

    def provenance(limits: list[str], coverage: str) -> Provenance:
        return _provenance(
            entry.url,
            cached,
            "sk_stats.FileRows",
            coverage,
            pick(lang, "; ", " ; ").join(limits) or None,
            lang,
        )

    if chosen is None:
        prov = provenance(
            [
                pick(
                    lang,
                    f"the workbook has {len(sizes)} sheets of similar size and none was "
                    "requested, so no rows were read: pick one from `sheets` and pass it as "
                    "`sheet`",
                    f"le classeur compte {len(sizes)} feuilles de taille semblable et aucune "
                    "n'a été demandée, donc aucune ligne n'a été lue : choisissez-en une dans "
                    "`sheets` et passez-la dans `sheet`",
                )
            ],
            pick(
                lang,
                f"Sheet list of {entry.title}, a {len(sizes)}-sheet workbook.",
                f"Liste des feuilles de {entry.title}, un classeur de {len(sizes)} feuilles.",
            ),
        )
        return FileRows(
            format_id=format_id,
            title=entry.title,
            url=entry.url,
            format=fmt,
            sheets=sheet_sizes,
            sheet=None,
            sheet_chosen_by="none",
            header_row=None,
            header_row_candidates=[],
            all_columns=[],
            columns=[],
            rows=[],
            total_rows=0,
            offset=offset,
            truncated=False,
            licence=prov.licence or "",
            provenance=prov,
        )

    _, summaries = await run_parse(tables.describe, body, fmt, chosen)
    result = await run_parse(
        tables.scan,
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
    candidates = summaries[0].header_candidates if summaries else []
    more = offset + limit < result.total_rows
    notes: list[str] = []
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
                f"the sheet was scanned only up to {tables.MAX_SCAN_ROWS} rows",
                f"la feuille n'a été parcourue que jusqu'à {tables.MAX_SCAN_ROWS} lignes",
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
    prov = provenance(
        notes,
        pick(
            lang,
            f"{entry.title} (published {entry.published}), sheet {chosen!r} of {len(sizes)}, "
            "layout as published (title rows, years across columns, notes at the bottom).",
            f"{entry.title} (publié le {entry.published}), feuille {chosen!r} sur {len(sizes)}, "
            "mise en page telle que publiée (lignes de titre, années en colonnes, notes en "
            "bas). Contenu en anglais seulement.",
        ),
    )
    return FileRows(
        format_id=format_id,
        title=entry.title,
        url=entry.url,
        format=fmt,
        sheets=sheet_sizes,
        sheet=chosen,
        sheet_chosen_by=how,
        header_row=result.header_row,
        header_row_candidates=[c for c in candidates if c != result.header_row],
        all_columns=result.all_columns,
        columns=result.columns,
        rows=result.rows,
        total_rows=result.total_rows,
        offset=offset,
        truncated=more or result.capped,
        licence=prov.licence or "",
        provenance=prov,
    )
