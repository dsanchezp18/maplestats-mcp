"""Open Alberta files: dataset discovery through CKAN and file reading.

Discovery calls the portal's CKAN Action API (`package_search`,
`package_show`) through the shared CKAN helper; a file is read only when
its dataset lists it, so the tool never fetches arbitrary URLs. API calls
and downloads share one bucket of one request per 10 seconds. Sheet and
CSV parsing lives in tables.py.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from maplestats_mcp.modules.ab_opendata import constants
from maplestats_mcp.modules.ab_opendata.schemas import (
    DatasetDetail,
    DatasetEntry,
    DatasetList,
    OrganizationCount,
    OrganizationList,
    ResourceEntry,
    ResourceRows,
    ResourceStructure,
    SheetInfo,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared import file_tables as tables
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action, excerpt
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.i18n import french_spacing, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.licences import OGL_ALBERTA
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]
FormatName = Literal["xlsx", "xls", "csv"]
SortName = Literal["relevance", "modified", "title"]

_CONFIG = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.API_BASE,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    timeout=60.0,
)
_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_DOWNLOAD = re.compile(constants.DOWNLOAD_PATH_PATTERN)
_SLUG = re.compile(r"^[a-z0-9_-]+$")
_DATASET_NAME = re.compile(r"^[a-z0-9_-]{2,100}$")

LICENCE_NOTE = {
    "en": "Almost every Open Alberta dataset is under the Open Government Licence - Alberta: "
    "a worldwide, royalty-free, perpetual, non-exclusive licence to use the information, "
    "including for commercial purposes, with the attribution 'Contains information "
    "licensed under the Open Government Licence – Alberta.' A dataset whose ogl_alberta "
    "is false is under other terms: its own licence, or by default the alberta.ca terms "
    "of use (non-commercial); check licence_note before reusing it.",
    "fr": "Presque tous les jeux de données d'Open Alberta relèvent de la Licence du "
    "gouvernement ouvert – Alberta : licence mondiale, libre de redevances, perpétuelle et "
    "non exclusive d'utilisation de l'information, y compris à des fins commerciales, avec "
    "la mention « Contains information licensed under the Open Government Licence – "
    "Alberta. » Un jeu dont ogl_alberta est faux relève d'autres conditions : sa propre "
    "licence ou, par défaut, les conditions d'utilisation d'alberta.ca (usage non "
    "commercial) ; lire licence_note avant toute réutilisation.",
}
OTHER_LICENCE_NOTE = {
    "en": "NOT under the Open Government Licence - Alberta (licence: {licence}). Other terms "
    "apply: the dataset's own licence or, by default, the alberta.ca terms of use, which "
    "are non-commercial. Do not assume commercial reuse is allowed; check {url}.",
    "fr": "N'est PAS sous la Licence du gouvernement ouvert – Alberta (licence : {licence}). "
    "D'autres conditions s'appliquent : la licence propre au jeu ou, par défaut, les "
    "conditions d'utilisation d'alberta.ca, qui sont non commerciales. Ne pas supposer que "
    "la réutilisation commerciale est permise ; vérifier {url}.",
}
NO_LICENCE = {"en": "none stated", "fr": "aucune indiquée"}
# French notes get their no-break spaces once, here.
LICENCE_NOTE["fr"] = french_spacing(LICENCE_NOTE["fr"])
OTHER_LICENCE_NOTE["fr"] = french_spacing(OTHER_LICENCE_NOTE["fr"])


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    # Titles carry U+FFFD where an en dash was lost upstream; notes carry literal &nbsp;.
    text = str(value).replace("�", "").replace("&nbsp;", " ").replace("\xa0", " ")
    text = " ".join(text.split())
    return None if text in ("", "null") else text


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        return _clean(value[0]) if value else None
    return _clean(value)


def parse_download_url(url: str, lang: str = "en") -> tuple[str, str]:
    """(dataset id, resource id) of an open.alberta.ca download link, or InvalidInput."""
    parsed = urlparse(url)
    match = _DOWNLOAD.match(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != constants.DOMAIN or match is None:
        raise_localized(
            InvalidInput,
            f"ab_opendata: url must be an https download link on {constants.DOMAIN} "
            "(/dataset/<id>/resource/<id>/download/<file>); see ab_opendata_search_datasets.",
            f"ab_opendata : url doit être un lien de téléchargement https sur {constants.DOMAIN} "
            "(/dataset/<id>/resource/<id>/download/<fichier>) ; voir "
            "ab_opendata_search_datasets.",
            lang,
        )
    assert match is not None
    return match["dataset"], match["resource"]


def _readable(url: str, fmt: str | None) -> bool:
    parsed = urlparse(url)
    return (
        (fmt or "").lower() in constants.FORMATS
        and parsed.scheme == "https"
        and parsed.hostname == constants.DOMAIN
        and _DOWNLOAD.match(parsed.path) is not None
    )


def _resource(raw: dict[str, Any]) -> ResourceEntry:
    url = str(raw.get("url") or "")
    size = raw.get("size")
    fmt = _clean(raw.get("format"))
    return ResourceEntry(
        id=str(raw.get("id") or ""),
        name=_clean(raw.get("name")) or unquote(url.rsplit("/", 1)[-1]),
        format=fmt,
        size_bytes=int(size) if isinstance(size, int | float) and size else None,
        modified=_clean(raw.get("last_modified") or raw.get("metadata_modified")),
        url=url,
        readable=_readable(url, fmt),
        description=excerpt(_clean(raw.get("description")) or "", 200) or None,
    )


def parse_dataset(package: dict[str, Any], lang: Lang = "en") -> DatasetEntry:
    name = str(package.get("name") or package.get("id") or "")
    organization = package.get("organization") or {}
    licence_id = _clean(package.get("license_id"))
    ogl = licence_id == constants.OGL_LICENCE_ID
    licence = _clean(package.get("license_title"))
    url = constants.DATASET_URL.format(name=name)
    resources = [_resource(r) for r in list_or_empty(package, "resources")]
    resources.sort(key=lambda r: not r.readable)
    other = sorted({(r.format or "unknown").lower() for r in resources if not r.readable})
    return DatasetEntry(
        name=name,
        title=_clean(package.get("title")) or name,
        dataset_url=url,
        organization=_clean(organization.get("name")),
        organization_title=_clean(organization.get("title")),
        licence_id=licence_id,
        licence=licence,
        licence_url=_clean(package.get("license_url")),
        ogl_alberta=ogl,
        licence_note=None
        if ogl
        else OTHER_LICENCE_NOTE[lang].format(
            licence=licence or licence_id or NO_LICENCE[lang], url=url
        ),
        date_modified=_clean(package.get("date_modified"))
        or (_clean(package.get("metadata_modified")) or "")[:10]
        or None,
        update_frequency=_clean(package.get("updatefrequency")),
        time_coverage_from=_clean(package.get("time_coverage_from")),
        time_coverage_to=_clean(package.get("time_coverage_to")),
        topics=[t for t in (_clean(x) for x in list_or_empty(package, "topic")) if t],
        summary=excerpt(_clean(package.get("notes")) or "", constants.NOTES_EXCERPT_CHARS) or None,
        resources=resources,
        other_formats=other,
    )


async def _api(method: str, params: dict[str, Any]) -> tuple[Any, bool]:
    key = f"ab_opendata:{method}:{json.dumps(params, sort_keys=True)}"

    async def fetch() -> Any:
        return await action(_CONFIG, method, params=params)

    return await cached_fetch(key, constants.CACHE_TTL_API_SECONDS, fetch)


def _format_filter(fmt: str | None, lang: str = "en") -> str:
    if fmt is None:
        return "(res_format:XLSX OR res_format:XLS OR res_format:CSV)"
    if fmt not in constants.FORMATS:
        raise_localized(
            InvalidInput,
            f"ab_opendata: format must be one of {list(constants.FORMATS)}.",
            f"ab_opendata : format doit valoir l'une des valeurs {list(constants.FORMATS)}.",
            lang,
        )
    return f"res_format:{fmt.upper()}"


def _facet_organizations(result: Any) -> list[OrganizationCount]:
    facets = (result.get("search_facets") or {}).get("organization") or {}
    return [
        OrganizationCount(
            name=str(i.get("name")),
            title=_clean(i.get("display_name")) or str(i.get("name")),
            datasets=int(i.get("count") or 0),
        )
        for i in list_or_empty(facets, "items")
    ]


async def _search(
    query: str | None,
    organization: str | None,
    fmt: str | None,
    ogl_only: bool,
    sort: str,
    rows: int,
    start: int,
    lang: str = "en",
) -> tuple[Any, bool]:
    filters = ["type:opendata", _format_filter(fmt, lang)]
    if organization:
        slug = organization.strip().lower()
        if not _SLUG.match(slug):
            raise_localized(
                InvalidInput,
                "ab_opendata: organization is a slug such as 'health' or "
                "'treasuryboardandfinance' (see ab_opendata_list_organizations).",
                "ab_opendata : organization est un identifiant comme « health » ou "
                "« treasuryboardandfinance » (voir ab_opendata_list_organizations).",
                lang,
            )
        filters.append(f"organization:{slug}")
    if ogl_only:
        filters.append(f"license_id:{constants.OGL_LICENCE_ID}")
    order = {"relevance": None, "modified": "metadata_modified desc", "title": "title_string asc"}
    if sort not in order:
        raise_localized(
            InvalidInput,
            f"ab_opendata: sort must be one of {list(order)}.",
            f"ab_opendata : sort doit valoir l'une des valeurs {list(order)}.",
            lang,
        )
    params: dict[str, Any] = {
        "q": (query or "").strip(),
        "fq": " AND ".join(filters),
        "rows": rows,
    }
    # Confirmed live 2026-10-02: the portal answers HTTP 520 when `facet.field`
    # is sent together with `sort` or with `start` (even 0). So organization counts
    # come only with the default order on the first page.
    if order[sort]:
        params["sort"] = order[sort]
    if start:
        params["start"] = start
    if not order[sort] and not start:
        params["facet.field"] = json.dumps(["organization"])
        params["facet.limit"] = constants.ORGANIZATIONS_FACET_LIMIT
    return await _api("package_search", params)


async def search_datasets(
    query: str | None = None,
    organization: str | None = None,
    format: str | None = None,
    ogl_alberta_only: bool = False,
    sort: SortName = "relevance",
    limit: int = constants.DATASETS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetList:
    if not 1 <= limit <= constants.DATASETS_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"ab_opendata: limit must be 1 to {constants.DATASETS_LIMIT_MAX}.",
            f"ab_opendata : limit doit être compris entre 1 et {constants.DATASETS_LIMIT_MAX}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            "ab_opendata: offset must be 0 or more.",
            "ab_opendata : offset doit être égal ou supérieur à 0.",
            lang,
        )
    result, cached = await _search(
        query, organization, format, ogl_alberta_only, sort, limit, offset, lang
    )
    datasets = [parse_dataset(p, lang) for p in list_or_empty(result, "results")]
    total = int(result.get("count") or 0)
    return DatasetList(
        datasets=datasets,
        total_datasets=total,
        offset=offset,
        truncated=offset + len(datasets) < total,
        organizations=_facet_organizations(result),
        licence_note=LICENCE_NOTE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=f"{constants.SITE}/dataset",
            cached=cached,
            schema_name="ab_opendata.DatasetList",
            freshness=_CATALOGUE_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Open datasets (type opendata) with at least one Excel or CSV resource; "
                "publications, maps and datasets with only PDFs or links are not listed here "
                "(use ckan_ with portal=ab).",
                "Jeux de données ouverts (type opendata) qui ont au moins une ressource Excel ou "
                "CSV ; les publications, les cartes et les jeux qui n'ont que des PDF ou des "
                "liens n'y figurent pas (utilisez ckan_ avec portal=ab). Titres et descriptions "
                "en anglais, comme sur le portail.",
            ),
            limits=(
                pick(
                    lang,
                    f"Showing datasets {offset + 1} to {offset + len(datasets)} of {total}.",
                    f"Jeux de données {offset + 1} à {offset + len(datasets)} sur {total}.",
                )
                if offset + len(datasets) < total or offset
                else None
            ),
            lang=lang,
        ),
    )


async def list_organizations(format: str | None = None, lang: Lang = "en") -> OrganizationList:
    result, cached = await _search(None, None, format, False, "relevance", 1, 0, lang)
    organizations = _facet_organizations(result)
    return OrganizationList(
        organizations=organizations,
        total_datasets=int(result.get("count") or 0),
        licence_note=LICENCE_NOTE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=f"{constants.SITE}/organization",
            cached=cached,
            schema_name="ab_opendata.OrganizationList",
            freshness=_CATALOGUE_FRESHNESS[lang],
            coverage=pick(
                lang,
                "Counts datasets with an Excel or CSV resource only.",
                "Ne compte que les jeux de données qui ont une ressource Excel ou CSV.",
            ),
            lang=lang,
        ),
    )


def _dataset_id(dataset: str, lang: str = "en") -> str:
    text = dataset.strip()
    if not text:
        raise_localized(
            InvalidInput,
            "ab_opendata: dataset must not be empty.",
            "ab_opendata : dataset ne doit pas être vide.",
            lang,
        )
    parsed = urlparse(text)
    if parsed.hostname == constants.DOMAIN:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "dataset":
            return parts[1]
        raise_localized(
            InvalidInput,
            f"ab_opendata: {text!r} is not a dataset page on {constants.DOMAIN}.",
            f"ab_opendata : {text!r} n'est pas une page de jeu de données sur {constants.DOMAIN}.",
            lang,
        )
    return text


async def _package(dataset_id: str, lang: str = "en") -> tuple[dict[str, Any], bool]:
    missing = NotFound(
        pick(
            lang,
            f"ab_opendata: no dataset {dataset_id!r} on {constants.DOMAIN}.",
            f"Aucune correspondance trouvée : ab_opendata : aucun jeu de données {dataset_id!r} "
            f"sur {constants.DOMAIN}.",
        )
    )
    # Every API call waits its turn in the 10-second bucket, so a name CKAN
    # could never hold (its names and ids are 2-100 of a-z, 0-9, - and _)
    # is refused without asking, and an unknown one is remembered a while.
    lowered = dataset_id.lower()
    if not _DATASET_NAME.match(lowered):
        raise missing

    async def lookup() -> tuple[Any, bool] | None:
        try:
            return await _api("package_show", {"id": lowered})
        except NotFound:
            return None

    found, probe_cached = await cached_fetch(
        f"ab_opendata:package_lookup:{lowered}", constants.CACHE_TTL_MISSING_SECONDS, lookup
    )
    if found is None:
        raise missing
    package, cached = found
    if not isinstance(package, dict):
        raise_localized(
            UpstreamError,
            f"ab_opendata: package_show for {dataset_id!r} returned no object.",
            f"ab_opendata : package_show pour {dataset_id!r} n'a renvoyé aucun objet.",
            lang,
        )
    return package, cached or probe_cached


async def get_dataset(dataset: str, lang: Lang = "en") -> DatasetDetail:
    package, cached = await _package(_dataset_id(dataset, lang), lang)
    entry = parse_dataset(package, lang)
    return DatasetDetail(
        dataset=entry,
        licence_note=LICENCE_NOTE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=entry.dataset_url,
            cached=cached,
            schema_name="ab_opendata.DatasetDetail",
            freshness=pick(
                lang,
                f"Update frequency: {entry.update_frequency or 'not stated'}; "
                f"modified {entry.date_modified or 'date not stated'}.",
                f"Fréquence de mise à jour : {entry.update_frequency or 'non précisée'} ; "
                f"modifié le {entry.date_modified or 'date non précisée'}.",
            ),
            coverage=pick(
                lang,
                "Every resource of the dataset; only .xlsx, .xls and .csv files hosted "
                "on open.alberta.ca are readable with ab_opendata_read_resource.",
                "Toutes les ressources du jeu de données ; seuls les fichiers .xlsx, .xls et "
                ".csv hébergés sur open.alberta.ca se lisent avec ab_opendata_read_resource. "
                "Titres et descriptions en anglais, comme sur le portail.",
            ),
            licence=_dataset_licence(entry, lang),
            lang=lang,
        ),
    )


async def _context(url: str, lang: Lang) -> tuple[DatasetEntry, ResourceEntry]:
    dataset_id, resource_id = parse_download_url(url, lang)
    package, _ = await _package(dataset_id, lang)
    entry = parse_dataset(package, lang)
    resource = next((r for r in entry.resources if r.id == resource_id), None)
    if resource is None:
        raise_localized(
            NotFound,
            f"ab_opendata: resource {resource_id} is not listed in dataset {entry.name!r}.",
            f"ab_opendata : la ressource {resource_id} ne figure pas dans le jeu de données "
            f"{entry.name!r}.",
            lang,
        )
    if not resource.readable:
        raise_localized(
            InvalidInput,
            f"ab_opendata: resource {resource.name!r} (format {resource.format}) is not an "
            "Excel or CSV file this module reads.",
            f"ab_opendata : la ressource {resource.name!r} (format {resource.format}) n'est pas "
            "un fichier Excel ou CSV que ce module lit.",
            lang,
        )
    return entry, resource


_CATALOGUE_FRESHNESS = {
    "en": "Catalogue metadata, cached for six hours.",
    "fr": "Métadonnées du catalogue, conservées en cache six heures.",
}


def _allow_host(host: str) -> bool:
    return host == constants.DOMAIN


async def _body(url: str, size_hint: int | None, lang: str = "en") -> tuple[bytes, bool]:
    if size_hint and size_hint > constants.MAX_FILE_BYTES:
        raise_localized(
            UpstreamError,
            f"ab_opendata: {url} is larger than this tool reads.",
            f"ab_opendata : {url} dépasse la taille que cet outil peut lire.",
            lang,
        )

    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=_allow_host,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context="ab_opendata",
        )

    # The same key as ckan_read_resource (portal="ab") uses for this URL, so one
    # copy of the file sits in the shared byte budget.
    downloaded, cached = await file_download.cached_download(
        file_download.cache_key(url), constants.CACHE_TTL_FILE_SECONDS, fetch
    )
    return downloaded.body, cached


def _choose_sheet(
    sizes: list[tuple[str, int, int]], sheet: str | None, fmt: tables.FileFormat
) -> tuple[str | None, tables.SheetChoice]:
    """The sheet policy shared with ckan_read_resource (shared/file_tables.py)."""
    return tables.choose_sheet(sizes, sheet, fmt, "ab_opendata")


def _attribution(entry: DatasetEntry) -> str | None:
    return constants.OGL_ATTRIBUTION if entry.ogl_alberta else None


def _freshness(entry: DatasetEntry, resource: ResourceEntry, lang: str = "en") -> str:
    return pick(
        lang,
        f"As published by the data owner; dataset update frequency: "
        f"{entry.update_frequency or 'not stated'}; file modified "
        f"{(resource.modified or 'date not stated')[:10]}.",
        f"Tel que publié par le propriétaire des données ; fréquence de mise à jour du jeu : "
        f"{entry.update_frequency or 'non précisée'} ; fichier modifié le "
        f"{(resource.modified or 'date non précisée')[:10]}.",
    )


async def describe_resource(
    url: str, sheet: str | None = None, lang: Lang = "en"
) -> ResourceStructure:
    entry, resource = await _context(url, lang)
    body, cached = await _body(url, resource.size_bytes, lang)
    fmt = tables.detect_format(body, resource.format)
    sizes = await run_parse(tables.sheet_sizes, body, fmt)
    only = _choose_sheet(sizes, sheet, fmt)[0] if sheet is not None else None
    total, summaries = await run_parse(tables.describe, body, fmt, only)
    attribution = _attribution(entry)
    return ResourceStructure(
        url=url,
        format=fmt,
        resource_name=resource.name,
        dataset=entry.name,
        dataset_title=entry.title,
        # The declared width counts formatted empty columns: the Income Support
        # workbook declares 14 columns for 5 named ones (live 2026-10-03). Rows
        # are trimmed of trailing blanks when read, so the width is the one
        # read_resource uses: one column per name.
        sheets=[
            SheetInfo(
                name=s.name,
                rows=s.rows,
                columns=len(s.column_names) if s.column_names else s.columns,
                header_row=s.header_row,
                column_names=s.column_names,
                preview=s.preview,
            )
            for s in summaries
        ],
        total_sheets=total,
        truncated=len(summaries) < (1 if only else total),
        licence=entry.licence,
        ogl_alberta=entry.ogl_alberta,
        attribution=attribution,
        licence_note=entry.licence_note,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="ab_opendata.ResourceStructure",
            freshness=_freshness(entry, resource, lang),
            limits=(
                pick(
                    lang,
                    f"Described the first {tables.MAX_DESCRIBED_SHEETS} of {total} sheets.",
                    f"Description des {tables.MAX_DESCRIBED_SHEETS} premières feuilles sur {total}.",
                )
                if total > tables.MAX_DESCRIBED_SHEETS and not only
                else None
            ),
            licence=_dataset_licence(entry, lang),
            lang=lang,
        ),
    )


def _dataset_licence(entry: DatasetEntry, lang: str = "en") -> str:
    """OGL - Alberta for most datasets; otherwise the dataset's own terms and the warning."""
    if entry.ogl_alberta:
        return OGL_ALBERTA
    named = (
        entry.licence
        or entry.licence_id
        or pick(lang, "no licence stated", "aucune licence indiquée")
    )
    where = f" ({entry.licence_url})" if entry.licence_url else ""
    return f"{named}{where}. {entry.licence_note or ''}".strip()


async def read_resource(
    url: str,
    sheet: str | None = None,
    columns: list[str] | None = None,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ResourceRows:
    parse_download_url(url, lang)
    checks = [
        (
            not 1 <= limit <= constants.ROWS_LIMIT_MAX,
            f"ab_opendata: limit must be 1 to {constants.ROWS_LIMIT_MAX}.",
            f"ab_opendata : limit doit être compris entre 1 et {constants.ROWS_LIMIT_MAX}.",
        ),
        (
            offset < 0,
            "ab_opendata: offset must be 0 or more.",
            "ab_opendata : offset doit être égal ou supérieur à 0.",
        ),
        (
            header_row is not None and header_row < 1,
            "ab_opendata: header_row is 1-based (1 or more).",
            "ab_opendata : header_row compte à partir de 1 (1 ou plus).",
        ),
        (
            not 1 <= header_rows <= 5,
            "ab_opendata: header_rows must be 1 to 5.",
            "ab_opendata : header_rows doit être compris entre 1 et 5.",
        ),
    ]
    for failed, en, fr in checks:
        if failed:
            raise_localized(InvalidInput, en, fr, lang)

    entry, resource = await _context(url, lang)
    body, cached = await _body(url, resource.size_bytes, lang)
    fmt = tables.detect_format(body, resource.format)
    sizes = await run_parse(tables.sheet_sizes, body, fmt)
    names = [n for n, _, _ in sizes]
    if not names:
        raise_localized(
            UpstreamError,
            f"ab_opendata: {url} has no sheets.",
            f"ab_opendata : {url} ne contient aucune feuille.",
            lang,
        )
    chosen, how = _choose_sheet(sizes, sheet, fmt)
    attribution = _attribution(entry)
    if chosen is None:
        return ResourceRows(
            url=url,
            format=fmt,
            resource_name=resource.name,
            dataset=entry.name,
            dataset_title=entry.title,
            sheets=names,
            sheet=None,
            sheet_chosen_by="none",
            header_row=None,
            all_columns=[],
            columns=[],
            rows=[],
            total_rows=0,
            offset=offset,
            truncated=False,
            licence=entry.licence,
            ogl_alberta=entry.ogl_alberta,
            attribution=attribution,
            licence_note=entry.licence_note,
            provenance=make_provenance(
                source=constants.PROVENANCE_SOURCE,
                url=url,
                cached=cached,
                schema_name="ab_opendata.ResourceRows",
                freshness=_freshness(entry, resource, lang),
                limits=pick(
                    lang,
                    f"the workbook has {len(names)} sheets of similar size and none was "
                    "requested, so no rows were read: pick one from `sheets` and pass it as "
                    "`sheet` (ab_opendata_describe_resource shows each sheet's header).",
                    f"le classeur a {len(names)} feuilles de taille semblable et aucune n'a été "
                    "demandée : aucune ligne n'a été lue. Choisissez-en une dans `sheets` et "
                    "passez-la dans `sheet` (ab_opendata_describe_resource montre l'en-tête de "
                    "chaque feuille).",
                ),
                licence=_dataset_licence(entry, lang),
                lang=lang,
            ),
        )
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
    more = offset + limit < result.total_rows
    notes = []
    if how == "largest":
        notes.append(
            pick(
                lang,
                f"the workbook has {len(names)} sheets and none was requested, so the largest "
                f"({chosen!r}) was read; pass sheet= for another",
                f"le classeur a {len(names)} feuilles et aucune n'a été demandée : la plus "
                f"grande ({chosen!r}) a été lue ; passez sheet= pour une autre",
            )
        )
    if result.capped:
        notes.append(
            pick(
                lang,
                f"the file was scanned only up to {tables.MAX_SCAN_ROWS} rows",
                f"le fichier n'a été parcouru que jusqu'à {tables.MAX_SCAN_ROWS} lignes",
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
    attribution = _attribution(entry)
    return ResourceRows(
        url=url,
        format=fmt,
        resource_name=resource.name,
        dataset=entry.name,
        dataset_title=entry.title,
        sheets=names,
        sheet=chosen,
        sheet_chosen_by=how,
        header_row=result.header_row,
        all_columns=result.all_columns,
        columns=result.columns,
        rows=result.rows,
        total_rows=result.total_rows,
        offset=offset,
        truncated=more or result.capped,
        licence=entry.licence,
        ogl_alberta=entry.ogl_alberta,
        attribution=attribution,
        licence_note=entry.licence_note,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="ab_opendata.ResourceRows",
            freshness=_freshness(entry, resource, lang),
            coverage=pick(
                lang,
                f"{entry.title}: {resource.name}, sheet {chosen!r} of {len(names)}.",
                f"{entry.title} : {resource.name}, feuille {chosen!r} sur {len(names)}.",
            ),
            limits=pick(lang, "; ", " ; ").join(notes) or None,
            licence=_dataset_licence(entry, lang),
            lang=lang,
        ),
    )
