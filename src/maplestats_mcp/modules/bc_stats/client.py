"""BC Stats Excel files: listing from the BC catalogue and sheet-by-sheet reading.

Discovery asks the BC CKAN catalogue for the `bc-stats` organization's
datasets (one `package_search` per 100 datasets, through the shared CKAN
action helper, paced in the same bucket as the downloads) and keeps every
resource whose URL ends in `.xlsx`. A file is read only if the catalogue
lists it, so the tool never fetches arbitrary URLs. Sheets keep the agency's
layout; see shared/xlsx_sheets.py.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse

from maplestats_mcp.modules.bc_stats import constants
from maplestats_mcp.modules.bc_stats.schemas import FileData, FileEntry, FileList, SheetInfo
from maplestats_mcp.shared import file_download, xlsx_sheets
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.licences import (
    LICENCES_FR,
    OGL_BC,
    OGL_BC_FR,
    OGL_CANADA,
    STATCAN_LICENCE,
    STATCAN_LICENCE_FR,
)
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

LICENCE_NOTE = {
    "en": "Licence is set per dataset: most BC Stats files are under the Open Government "
    "Licence - British Columbia; tables derived from Statistics Canada carry the "
    "Statistics Canada Open Licence. Check the licence field and attribute the source.",
    "fr": pick(
        "fr",
        "",
        "La licence est propre à chaque jeu de données : la plupart des fichiers de BC "
        "Stats relèvent de la Licence du gouvernement ouvert – Colombie-Britannique ; les "
        "tableaux dérivés de Statistique Canada sont visés par la Licence ouverte de "
        "Statistique Canada. Vérifiez le champ licence et citez la source.",
    ),
}

# The catalogue's update-cycle codes, as French readers expect them.
_UPDATE_CYCLES_FR = {
    "annually": "annuelle",
    "asNeeded": "au besoin",
    "monthly": "mensuelle",
    "quarterly": "trimestrielle",
    "weekly": "hebdomadaire",
    "daily": "quotidienne",
    "irregular": "irrégulière",
}


def _config() -> CkanConfig:
    # Same bucket as the file downloads: the catalogue host is paced at one
    # request per 10 seconds whatever is asked of it.
    return CkanConfig(
        source=constants.RATE_LIMIT_SOURCE,
        base_url=constants.CKAN_PORTAL.base_url,
        rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
        rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
        timeout=constants.CATALOGUE_TIMEOUT_SECONDS,
    )


def _file_licence(entry: FileEntry, lang: str = "en") -> str:
    """The dataset's own licence, with Statistics Canada's attribution for its tables."""
    title = (entry.licence or "").casefold()
    if "statistics canada" in title:
        return pick(
            lang,
            f"{STATCAN_LICENCE} Table compiled by BC Stats from Statistics Canada data.",
            f"{STATCAN_LICENCE_FR} Tableau compilé par BC Stats à partir de données de "
            "Statistique Canada.",
        )
    if "british columbia" in title:
        return pick(lang, OGL_BC, OGL_BC_FR)
    if "open government licence - canada" in title:
        return pick(lang, OGL_CANADA, LICENCES_FR[OGL_CANADA])
    where = f" ({entry.licence_url})" if entry.licence_url else ""
    return pick(
        lang,
        f"{entry.licence or 'no licence stated'}{where}: check these terms before reusing "
        "the file.",
        f"{entry.licence or 'aucune licence précisée'}{where} : vérifiez ces conditions "
        "avant de réutiliser le fichier.",
    )


def _clean(value: Any) -> str | None:
    """A catalogue string; BC writes the literal "null" for missing values."""
    if value is None:
        return None
    text = " ".join(str(value).replace("�", "").split())
    return None if text in ("", "null") else text


def _flag(value: Any) -> bool | None:
    # The catalogue sends booleans and the strings "true"/"false" mixed.
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def parse_packages(packages: list[dict[str, Any]]) -> list[FileEntry]:
    """Every `.xlsx` resource of the given catalogue datasets."""
    files: list[FileEntry] = []
    for package in packages:
        name = str(package.get("name") or package.get("id") or "")
        resources = list_or_empty(package, "resources")
        formats = sorted({str(r["format"]).lower() for r in resources if _clean(r.get("format"))})
        for resource in resources:
            url = str(resource.get("url") or "")
            if not urlparse(url).path.lower().endswith(".xlsx"):
                continue
            size = resource.get("size")
            files.append(
                FileEntry(
                    dataset=name,
                    dataset_title=_clean(package.get("title")) or name,
                    dataset_url=f"{constants.SITE}/dataset/{name}",
                    title=_clean(resource.get("name")) or url.rsplit("/", 1)[-1],
                    url=url,
                    size_bytes=int(size) if isinstance(size, int | float) else None,
                    update_cycle=_clean(resource.get("resource_update_cycle")),
                    modified=_clean(resource.get("last_modified")),
                    licence=_clean(package.get("license_title")),
                    licence_url=_clean(package.get("license_url")),
                    datastore_flag=_flag(resource.get("datastore_active")),
                    dataset_formats=formats,
                )
            )
    return files


async def _catalogue() -> tuple[list[FileEntry], bool]:
    async def fetch() -> list[FileEntry]:
        files: list[FileEntry] = []
        start = 0
        while True:
            result = await action(
                _config(),
                "package_search",
                params={
                    "q": "",
                    "fq": f"organization:{constants.ORGANIZATION}",
                    "rows": constants.PAGE_SIZE,
                    "start": start,
                    "sort": "name asc",
                },
            )
            packages = list_or_empty(result, "results")
            files.extend(parse_packages(packages))
            start += len(packages)
            if not packages or start >= int(result.get("count") or 0):
                return files

    return await cached_fetch("bc_stats:catalogue", constants.CACHE_TTL_LIST_SECONDS, fetch)


async def list_files(
    query: str | None = None,
    dataset: str | None = None,
    limit: int = constants.FILES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileList:
    if not 1 <= limit <= constants.FILES_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"bc_stats: limit must be 1 to {constants.FILES_LIMIT_MAX}.",
            f"bc_stats : limit doit être compris entre 1 et {constants.FILES_LIMIT_MAX}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            "bc_stats: offset must be 0 or more.",
            "bc_stats : offset doit être égal ou supérieur à 0.",
            lang,
        )
    files, cached = await _catalogue()
    if dataset:
        wanted = dataset.casefold()
        files = [
            f
            for f in files
            if wanted in f.dataset.casefold() or wanted in f.dataset_title.casefold()
        ]
    if query:
        words = query.casefold().split()
        files = [
            f
            for f in files
            if all(w in f"{f.title} {f.dataset_title} {f.dataset}".casefold() for w in words)
        ]
    total = len(files)
    return FileList(
        files=files[offset : offset + limit],
        total_files=total,
        truncated=offset + limit < total,
        licence_note=LICENCE_NOTE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=constants.ORGANIZATION_URL,
            cached=cached,
            schema_name="bc_stats.FileList",
            freshness=pick(
                lang,
                "Catalogue metadata, cached for six hours.",
                "Métadonnées du catalogue, conservées en cache six heures.",
            ),
            coverage=pick(
                lang,
                "Excel (.xlsx) resources of the BC Stats organization on the BC data "
                "catalogue; the organization's CSV, PDF and geographic resources are not "
                "listed.",
                "Ressources Excel (.xlsx) de l'organisation BC Stats dans le catalogue de "
                "données de la Colombie-Britannique ; ses ressources CSV, PDF et "
                "géographiques ne sont pas listées.",
            ),
            limits=(
                pick(
                    lang,
                    f"Showing files {offset + 1} to {offset + min(limit, total - offset)} "
                    f"of {total}.",
                    f"Fichiers {offset + 1} à {offset + min(limit, total - offset)} sur {total}.",
                )
                if total > limit
                else None
            ),
            lang=lang,
        ),
    )


def check_file_url(url: str, lang: str = "en") -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != constants.DOMAIN
        or constants.DOWNLOAD_PATH_MARKER not in parsed.path
        or not parsed.path.lower().endswith(".xlsx")
    ):
        raise_localized(
            InvalidInput,
            f"bc_stats: url must be an https .xlsx download link on {constants.DOMAIN} "
            "(see bc_stats_list_files).",
            "bc_stats : url doit être un lien de téléchargement .xlsx en https sur "
            f"{constants.DOMAIN} (voir bc_stats_list_files).",
            lang,
        )


async def _body(url: str, size_hint: int | None, lang: str = "en") -> tuple[bytes, bool]:
    if size_hint and size_hint > constants.MAX_FILE_BYTES:
        raise_localized(
            UpstreamError,
            f"bc_stats: {url} is {size_hint:,} bytes; this tool reads files up to "
            f"{constants.MAX_FILE_BYTES:,}. Download it from the catalogue instead.",
            f"bc_stats : {url} pèse {size_hint:,} octets ; cet outil lit les fichiers d'au "
            f"plus {constants.MAX_FILE_BYTES:,} octets. Téléchargez-le plutôt depuis le "
            "catalogue.".replace(",", " "),
            lang,
        )

    async def fetch() -> file_download.Downloaded:
        # Streamed under the cap: a declared Content-Length above it is refused
        # before the body is read, an undeclared one stops at the cap.
        return await file_download.download(
            url,
            allow_host=lambda host: host == constants.DOMAIN,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context="bc_stats",
            timeout=180.0,
        )

    # The same key ckan_read_resource (portal "bc") uses for this URL, so one
    # copy of the file sits in the shared byte budget.
    downloaded, cached = await file_download.cached_download(
        file_download.cache_key(url), constants.CACHE_TTL_FILE_SECONDS, fetch
    )
    body = downloaded.body
    if body.lstrip()[:5].lower() in (b"<!doc", b"<html"):
        raise_localized(
            NotFound,
            f"bc_stats: {url} returned a web page, not an Excel file.",
            f"bc_stats : {url} a renvoyé une page Web, pas un fichier Excel.",
            lang,
        )
    return body, cached


async def _sheets(url: str, body: bytes, lang: str = "en") -> list[SheetInfo]:
    async def fetch() -> list[SheetInfo]:
        try:
            dims = await run_parse(xlsx_sheets.sheet_dimensions, body)
        # openpyxl raises several unrelated types.
        except Exception as exc:  # noqa: BLE001 (raise_localized re-raises it as UpstreamError)
            raise_localized(
                UpstreamError,
                f"bc_stats: could not read {url}: {exc}",
                f"bc_stats : impossible de lire {url} : {exc}",
                lang,
            )
        return [SheetInfo(name=n, rows=r, columns=c) for n, r, c in dims]

    sheets, _ = await cached_fetch(
        f"bc_stats:sheets:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch
    )
    return sheets


async def _rows(
    url: str, body: bytes, sheet: str, lang: str = "en"
) -> tuple[list[list[str]], bool]:
    async def fetch() -> tuple[list[list[str]], bool]:
        try:
            return await run_parse(
                xlsx_sheets.read_sheet, body, sheet, constants.MAX_ROWS_PER_SHEET
            )
        except InvalidInput:
            raise
        except Exception as exc:  # noqa: BLE001 (raise_localized re-raises it as UpstreamError)
            raise_localized(
                UpstreamError,
                f"bc_stats: could not read {url}: {exc}",
                f"bc_stats : impossible de lire {url} : {exc}",
                lang,
            )

    result, _ = await cached_fetch(
        f"bc_stats:rows:{url}:{sheet}", constants.CACHE_TTL_FILE_SECONDS, fetch
    )
    return result


_NOTES_SHEETS = re.compile(
    r"^(read ?me|notes?|contents|table of contents|index|about|definitions|metadata|"
    r"sources?|footnotes)$"
)


def default_sheet(names: list[str]) -> str:
    """The first sheet that is not a notes page.

    Most BC Stats workbooks open on their table (GDP: 'BC GDP $Current' then
    'BC GDP $2017'; CPI: page1..page5), but the population estimates and
    projections workbook opens on 'READ ME' before 'Table 1' (live file of
    2026-10-01), so a notes-like first sheet is skipped.
    """
    for name in names:
        if not _NOTES_SHEETS.match(" ".join(name.casefold().split())):
            return name
    return names[0]


async def read_file(
    url: str,
    sheet: str | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileData:
    check_file_url(url, lang)
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"bc_stats: limit must be 1 to {constants.ROWS_LIMIT_MAX}.",
            f"bc_stats : limit doit être compris entre 1 et {constants.ROWS_LIMIT_MAX}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            "bc_stats: offset must be 0 or more.",
            "bc_stats : offset doit être égal ou supérieur à 0.",
            lang,
        )
    if header_row is not None and header_row < 1:
        raise_localized(
            InvalidInput,
            "bc_stats: header_row is 1-based (1 or more).",
            "bc_stats : header_row compte à partir de 1 (1 ou plus).",
            lang,
        )

    listed, _ = await _catalogue()
    entry = next((f for f in listed if f.url == url), None)
    if entry is None:
        raise_localized(
            NotFound,
            f"bc_stats: {url} is not an Excel file of the BC Stats organization.",
            f"bc_stats : {url} n'est pas un fichier Excel de l'organisation BC Stats.",
            lang,
        )

    body, cached = await _body(url, entry.size_bytes, lang)
    sheets = await _sheets(url, body, lang)
    if not sheets:
        raise_localized(
            UpstreamError,
            f"bc_stats: {url} has no sheets.",
            f"bc_stats : {url} ne contient aucune feuille.",
            lang,
        )
    if sheet is None:
        chosen = default_sheet([s.name for s in sheets])
    else:
        matches = [s.name for s in sheets if s.name.casefold() == sheet.strip().casefold()]
        if not matches:
            names = [s.name for s in sheets]
            raise_localized(
                InvalidInput,
                f"bc_stats: no sheet {sheet!r}; sheets are {names}.",
                f"bc_stats : aucune feuille {sheet!r} ; les feuilles sont {names}.",
                lang,
            )
        chosen = matches[0]

    rows, capped = await _rows(url, body, chosen, lang)
    # The file's declared size counts trailing blank rows and formatted empty
    # columns (econ_incorporations.xlsx declares 286 x 47 for 284 x 38 of data,
    # seen 2026-10-03); the sheet read reports what it holds, so its counts
    # agree with the header_row bound below.
    width = len(rows[0]) if rows else 0
    sheets = [
        SheetInfo(name=s.name, rows=len(rows), columns=width, counted=True)
        if s.name == chosen
        else s
        for s in sheets
    ]
    if header_row is not None:
        if header_row > len(rows):
            raise_localized(
                InvalidInput,
                f"bc_stats: header_row {header_row} is past the last row with content of "
                f"sheet {chosen!r}, which has only {len(rows)} rows (trailing blank rows "
                "are not counted).",
                f"bc_stats : header_row {header_row} dépasse la dernière ligne remplie de la "
                f"feuille {chosen!r}, qui n'a que {len(rows)} lignes (les lignes vides de la "
                "fin ne sont pas comptées).",
                lang,
            )
        header_index: int | None = header_row - 1
    else:
        header_index = xlsx_sheets.guess_header(rows)
    header = rows[header_index] if header_index is not None else []
    table = rows[header_index + 1 :] if header_index is not None else rows
    table = [r for r in table if any(r)]
    if contains:
        wanted = contains.casefold()
        table = [r for r in table if any(wanted in cell.casefold() for cell in r)]
    total = len(table)
    more = offset + limit < total
    notes = []
    if sheet is None and len(sheets) > 1:
        notes.append(
            pick(
                lang,
                f"no sheet was requested, so {chosen!r} (the first sheet that is not a notes "
                f"page) of {len(sheets)} was read; pass sheet= for another",
                f"aucune feuille demandée : {chosen!r} (la première feuille qui n'est pas une "
                f"page de notes) sur {len(sheets)} a été lue ; passez sheet= pour une autre",
            )
        )
    if capped:
        notes.append(
            pick(
                lang,
                f"the sheet was read only up to {constants.MAX_ROWS_PER_SHEET} rows",
                f"la feuille n'a été lue que jusqu'à {constants.MAX_ROWS_PER_SHEET} lignes",
            )
        )
    if more:
        notes.append(
            pick(
                lang,
                f"showing rows {offset + 1} to {offset + limit} of {total}",
                f"lignes {offset + 1} à {offset + limit} sur {total}",
            )
        )
    cycle = entry.update_cycle
    cycle_fr = _UPDATE_CYCLES_FR.get(cycle or "", cycle or "non précisée")
    return FileData(
        url=url,
        sheets=sheets,
        sheet=chosen,
        header_row=None if header_index is None else header_index + 1,
        header=header,
        rows=table[offset : offset + limit],
        total_rows=total,
        offset=offset,
        truncated=more or capped,
        licence=entry.licence,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="bc_stats.FileData",
            freshness=pick(
                lang,
                f"As published by BC Stats; catalogue update cycle: {cycle or 'not stated'}.",
                f"Tel que publié par BC Stats ; fréquence de mise à jour selon le catalogue : "
                f"{cycle_fr}.",
            ),
            coverage=pick(
                lang,
                f"{entry.title}, sheet {chosen!r} of {len(sheets)}.",
                f"{entry.title}, feuille {chosen!r} sur {len(sheets)}.",
            ),
            limits=pick(lang, "; ", " ; ").join(notes) or None,
            licence=_file_licence(entry, lang),
            lang=lang,
        ),
    )
