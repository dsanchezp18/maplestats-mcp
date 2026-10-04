"""ECCC Data Catalogue file tree: folder listings, a folder index, file reading.

Listings come from `api/path_contents`, files from `api/file` (a 302 to a
signed blob URL on the same host); see constants.py for what was verified
live. Sheet and CSV parsing is the shared `file_tables` reader. The NPRI and
GHGRP lookups parse their published CSVs directly, locating each column by
its bilingual header text so a reordered file still reads correctly and a
renamed column fails loudly instead of returning wrong numbers.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal, NoReturn
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from maplestats_mcp.modules.eccc_datamart import constants
from maplestats_mcp.modules.eccc_datamart.schemas import (
    CatalogueEntry,
    DocumentationFile,
    EntryKind,
    FileRows,
    FileStructure,
    FolderListing,
    GhgrpRecord,
    GhgrpResult,
    NpriRecord,
    NpriResult,
    SearchHit,
    SearchResults,
    SheetInfo,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared import file_tables as tables
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import check_deadline, run_parse
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]
Order = Literal["file", "largest"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_DOC = re.compile(constants.DOC_PATTERN)
_NPRI_FILE = re.compile(constants.NPRI_FILE_PATTERN)
_GHGRP_FILE = re.compile(constants.GHGRP_FILE_PATTERN)
_SIZE = re.compile(r"^\s*([\d.]+)\s*([KMGT]?i?B)\s*$", re.IGNORECASE)
_UNITS = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}

CTX = "eccc_datamart"

PROVINCES: dict[str, tuple[str, str]] = {
    "AB": ("Alberta", "Alberta"),
    "BC": ("British Columbia", "Colombie-Britannique"),
    "MB": ("Manitoba", "Manitoba"),
    "NB": ("New Brunswick", "Nouveau-Brunswick"),
    "NL": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador"),
    "NS": ("Nova Scotia", "Nouvelle-Écosse"),
    "NT": ("Northwest Territories", "Territoires du Nord-Ouest"),
    "NU": ("Nunavut", "Nunavut"),
    "ON": ("Ontario", "Ontario"),
    "PE": ("Prince Edward Island", "Île-du-Prince-Édouard"),
    "QC": ("Quebec", "Québec"),
    "SK": ("Saskatchewan", "Saskatchewan"),
    "YT": ("Yukon", "Yukon"),
}

NOTES = {
    "npri_years": {
        "en": "Single-year facility tables exist for {years}. Earlier years (1993 onward) are "
        "only in the all-years bulk files ({bulk}: the releases file is about 375 MB) and a "
        "175 MB zipped database, which are larger than this reader opens; download them "
        "from the catalogue.",
        "fr": "Les tableaux annuels par installation existent pour {years}. Les années "
        "antérieures (depuis 1993) ne figurent que dans les fichiers en vrac toutes années "
        "({bulk} : le fichier des rejets fait environ 375 Mo) et une base de données ZIP de "
        "175 Mo, trop volumineux pour ce lecteur ; les télécharger depuis le catalogue.",
    },
    "npri_units": {
        "en": "Quantities are in the row's units (tonnes, kg, grams, or g TEQ for dioxins "
        "and furans); compare rows only within one substance.",
        "fr": "Les quantités sont dans les unités de la ligne (tonnes, kg, grammes ou g ÉQT "
        "pour les dioxines et furannes) ; ne comparer que des lignes d'une même substance.",
    },
    "npri_largest": {
        "en": "order=largest ranks by grand total converted to tonnes (kg and grams "
        "converted; g TEQ rows last).",
        "fr": "order=largest classe selon le total général converti en tonnes (kg et "
        "grammes convertis ; lignes en g ÉQT à la fin).",
    },
    "ghgrp_gwp": {
        "en": "CO2e uses the global warming potentials of the IPCC Fifth Assessment Report "
        "over the whole series. From 2022, CO2 from biomass combustion is reported but "
        "excluded from total_co2e. Facilities report above a threshold (10 kt CO2e from "
        "2017, 50 kt before), so counts jump in 2017.",
        "fr": "Les éq. CO2 utilisent les potentiels de réchauffement planétaire du cinquième "
        "rapport d'évaluation du GIEC pour toute la série. Depuis 2022, le CO2 issu de la "
        "combustion de biomasse est déclaré mais exclu de total_co2e. Les installations "
        "déclarent au-delà d'un seuil (10 kt éq. CO2 depuis 2017, 50 kt avant), d'où la "
        "hausse du nombre d'installations en 2017.",
    },
    "ghgrp_contacts": {
        "en": "The file also lists each facility's public contact (name, telephone, email); "
        "those columns are left out here. eccc_datamart_read_file returns the file as "
        "published.",
        "fr": "Le fichier donne aussi le responsable des renseignements au public de chaque "
        "installation (nom, téléphone, courriel) ; ces colonnes sont omises ici. "
        "eccc_datamart_read_file renvoie le fichier tel que publié.",
    },
}


def _note(key: str, lang: Lang, **kwargs: Any) -> str:
    text = NOTES[key][lang].format(**kwargs)
    return french_spacing(text) if lang == "fr" else text


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str = "en") -> NoReturn:
    """English as before; French in the typed template ("Entrée invalide : ...")."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _pick(en: str | None, fr: str | None, lang: Lang) -> str | None:
    if lang != "fr":
        return en
    return french_spacing(fr) if fr else fr


def _attribution(lang: Lang) -> str:
    return constants.OGL_ATTRIBUTION_FR if lang == "fr" else constants.OGL_ATTRIBUTION


def _licence(lang: Lang) -> str:
    return french_spacing(constants.LICENCE_TEXT_FR) if lang == "fr" else constants.LICENCE_TEXT


def _undocumented(lang: Lang) -> str:
    return (
        french_spacing(constants.UNDOCUMENTED_NOTE_FR)
        if lang == "fr"
        else constants.UNDOCUMENTED_NOTE
    )


# --- paths and listings -----------------------------------------------------------


def normalize_path(raw: str, lang: Lang = "en") -> str:
    """'/a/b' from a path, a catalogue page URL or a file link; InvalidInput otherwise."""
    text = (raw or "").strip()
    if text.lower().startswith(("http://", "https://")):
        parsed = urlparse(text)
        if parsed.hostname != constants.DOMAIN:
            _raise(
                InvalidInput,
                f"{CTX}: only {constants.DOMAIN} paths are read; got {parsed.hostname!r}.",
                f"{CTX} : seuls les chemins de {constants.DOMAIN} sont lus ; "
                f"reçu {parsed.hostname!r}.",
                lang,
            )
        if parsed.path.startswith("/api/"):
            text = (parse_qs(parsed.query).get("path") or [""])[0]
        elif parsed.path.startswith("/data"):
            text = unquote(parsed.path[len("/data") :])
        elif parsed.path.startswith("/public/"):
            text = unquote(parsed.path[len("/public") :])
        else:
            text = unquote(parsed.path)
    parts = [p for p in text.replace("\\", "/").split("/") if p]
    if any(p in (".", "..") for p in parts):
        _raise(
            InvalidInput,
            f"{CTX}: a path cannot contain '.' or '..' segments.",
            f"{CTX} : un chemin ne peut pas contenir de segments '.' ou '..'.",
            lang,
        )
    return "/" + "/".join(parts)


def file_url(path: str) -> str:
    return f"{constants.FILE_URL}?path={quote(path, safe='/')}"


def browse_url(path: str, lang: Lang) -> str:
    return constants.BROWSE_URL.format(path="" if path == "/" else quote(path), lang=lang)


def _size_parts(text: str | None) -> tuple[float, int] | None:
    """(number, unit in bytes) of a listing size such as '36 MiB'."""
    match = _SIZE.match(text or "")
    if not match:
        return None
    unit = match[2].lower()
    unit = {"kb": "kib", "mb": "mib", "gb": "gib", "tb": "tib"}.get(unit, unit)
    factor = _UNITS.get(unit)
    return (float(match[1]), factor) if factor else None


def size_bytes(text: str | None) -> int | None:
    """Approximate bytes of a listing size (the catalogue rounds to whole units)."""
    parts = _size_parts(text)
    return int(parts[0] * parts[1]) if parts else None


def _surely_too_big(text: str | None) -> bool:
    """True when even the low end of a rounded size is above the reading cap."""
    parts = _size_parts(text)
    return bool(parts) and (parts[0] - 0.5) * parts[1] > constants.MAX_FILE_BYTES


def _suffix(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def _kind(name: str, is_folder: bool, catalogue_id: str | None) -> EntryKind:
    if is_folder:
        return "folder"
    suffix = _suffix(name)
    if name == ".dir_metadata.json" or (catalogue_id and name == f"{catalogue_id}.xml"):
        return "documentation"
    if _DOC.search(name) and suffix in (*constants.READABLE_SUFFIXES, ".docx", ".pdf", ".xml"):
        return "documentation"
    if suffix in constants.READABLE_SUFFIXES:
        return "table"
    if suffix in constants.ARCHIVE_SUFFIXES:
        return "archive"
    return "other"


def _title(display: Any, lang: Lang) -> str | None:
    if not isinstance(display, dict):
        return None
    value = display.get(lang) or display.get("fr" if lang == "en" else "en")
    text = " ".join(str(value).split()) if value else ""
    return text or None


def parse_entry(raw: dict[str, Any], catalogue_id: str | None, lang: Lang) -> CatalogueEntry:
    name = str(raw.get("name") or "")
    path = "/" + str(raw.get("path") or name).lstrip("/")
    is_folder = bool(raw.get("is_directory"))
    size = None if is_folder else (raw.get("content_length") or None)
    kind = _kind(name, is_folder, catalogue_id)
    readable = kind in ("table", "documentation") and _suffix(name) in (constants.READABLE_SUFFIXES)
    return CatalogueEntry(
        name=name,
        path=path,
        kind=kind,
        title=_title(raw.get("display_name"), lang),
        size=size,
        size_bytes=size_bytes(size),
        modified=raw.get("last_modified") or None,
        readable=readable and not _surely_too_big(size),
        file_url=None if is_folder else file_url(path),
    )


async def _listing(path: str, lang: Lang = "en") -> tuple[dict[str, Any], bool]:
    key = f"{CTX}:listing:{path}"

    async def fetch() -> dict[str, Any]:
        await _LIMITER.acquire()
        try:
            data = await api_get(constants.LISTING_URL, params={"path": path}, timeout=30.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                _raise(
                    NotFound,
                    f"{CTX}: no folder or file {path!r} in the ECCC Data Catalogue "
                    "(eccc_datamart_browse lists what exists).",
                    f"{CTX} : aucun dossier ni fichier {path!r} dans le catalogue de données "
                    "d'ECCC (eccc_datamart_browse liste ce qui existe).",
                    lang,
                )
            _raise(
                UpstreamError,
                f"{CTX}: the catalogue answered HTTP {status} for {path!r}.",
                f"{CTX} : le catalogue a répondu HTTP {status} pour {path!r}.",
                lang,
            )
        except httpx.HTTPError as exc:
            _raise(
                UpstreamUnavailable,
                f"{CTX}: the catalogue did not respond for {path!r} ({type(exc).__name__}).",
                f"{CTX} : le catalogue n'a pas répondu pour {path!r} ({type(exc).__name__}).",
                lang,
            )
        if not isinstance(data, dict) or "path_contents" not in data:
            _raise(
                UpstreamError,
                f"{CTX}: unexpected listing shape for {path!r}.",
                f"{CTX} : forme de liste inattendue pour {path!r}.",
                lang,
            )
        return data

    return await cached_fetch(key, constants.CACHE_TTL_LISTING_SECONDS, fetch)


def _is_file_listing(path: str, data: dict[str, Any]) -> bool:
    # A file path answers with the file itself as the only entry.
    contents = list_or_empty(data, "path_contents")
    return (
        len(contents) == 1
        and not contents[0].get("is_directory")
        and "/" + str(contents[0].get("path") or "").lstrip("/") == path
    )


def _catalogue_url(catalogue_id: str | None, lang: Lang) -> str | None:
    return constants.CATALOGUE_URL.format(lang=lang, id=catalogue_id) if catalogue_id else None


async def browse(
    path: str = "/",
    limit: int = constants.ENTRIES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FolderListing:
    _check_limit(limit, constants.ENTRIES_LIMIT_MAX, lang)
    _check_offset(offset, lang)
    folder = normalize_path(path, lang)
    data, cached = await _listing(folder, lang)
    if _is_file_listing(folder, data):
        _raise(
            InvalidInput,
            f"{CTX}: {folder!r} is a file, not a folder; use eccc_datamart_describe_file or "
            "eccc_datamart_read_file.",
            f"{CTX} : {folder!r} est un fichier, pas un dossier ; utilisez "
            "eccc_datamart_describe_file ou eccc_datamart_read_file.",
            lang,
        )
    catalogue_id = data.get("path_catalogue_id") or None
    entries = [parse_entry(e, catalogue_id, lang) for e in list_or_empty(data, "path_contents")]
    entries.sort(key=lambda e: (e.kind != "folder", e.name.casefold()))
    page = entries[offset : offset + limit]
    title = await _folder_title(folder, lang)
    folders = sum(1 for e in entries if e.kind == "folder")
    return FolderListing(
        path=folder,
        parent=data.get("path_parent"),
        title=title,
        catalogue_id=catalogue_id,
        catalogue_url=_catalogue_url(catalogue_id, lang),
        browse_url=browse_url(folder, lang),
        folders=folders,
        files=len(entries) - folders,
        entries=page,
        total_entries=len(entries),
        offset=offset,
        truncated=offset + len(page) < len(entries),
        attribution=_attribution(lang),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=f"{constants.LISTING_URL}?path={quote(folder, safe='/')}",
            cached=cached,
            schema_name="eccc_datamart.FolderListing",
            freshness=_pick(
                "Listing cached for six hours; modified dates are the catalogue's.",
                "Liste mise en cache six heures ; les dates de modification sont celles du "
                "catalogue.",
                lang,
            ),
            coverage=_undocumented(lang),
            limits=(
                _pick(
                    f"Showing entries {offset + 1} to {offset + len(page)} of {len(entries)}.",
                    f"Entrées {offset + 1} à {offset + len(page)} sur {len(entries)}.",
                    lang,
                )
                if offset or offset + len(page) < len(entries)
                else None
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def _folder_title(path: str, lang: Lang) -> str | None:
    """The display name the parent listing gives `path` (None at the root or if absent)."""
    if path == "/":
        return None
    parent = path.rsplit("/", 1)[0] or "/"
    try:
        data, _ = await _listing(parent)
    except (NotFound, UpstreamError):
        return None
    for raw in list_or_empty(data, "path_contents"):
        if "/" + str(raw.get("path") or "").lstrip("/") == path:
            return _title(raw.get("display_name"), lang)
    return None


# --- folder index and search --------------------------------------------------------


@dataclass
class IndexedFolder:
    path: str
    depth: int
    title_en: str | None
    title_fr: str | None


def fold(text: str) -> str:
    """Lower case without accents, punctuation as spaces."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


async def _build_index() -> tuple[list[IndexedFolder], list[str]]:
    found: list[IndexedFolder] = []
    skipped: list[str] = []
    semaphore = asyncio.Semaphore(constants.INDEX_CONCURRENCY)

    async def visit(path: str, depth: int) -> None:
        async with semaphore:
            try:
                data, _ = await _listing(path)
            except (NotFound, UpstreamError) as exc:
                if path == "/":
                    raise
                skipped.append(f"{path} ({type(exc).__name__})")
                return
        children = []
        for raw in list_or_empty(data, "path_contents"):
            if not raw.get("is_directory"):
                continue
            child = "/" + str(raw.get("path") or raw.get("name") or "").lstrip("/")
            display = raw.get("display_name") or {}
            found.append(
                IndexedFolder(
                    path=child,
                    depth=depth + 1,
                    title_en=_title({"en": display.get("en")}, "en"),
                    title_fr=_title({"fr": display.get("fr")}, "fr"),
                )
            )
            if depth + 1 < constants.INDEX_DEPTH:
                children.append(visit(child, depth + 1))
        await asyncio.gather(*children)

    await visit("/", 0)
    found.sort(key=lambda f: f.path)
    return found, sorted(skipped)


async def _index() -> tuple[tuple[list[IndexedFolder], list[str]], bool]:
    return await cached_fetch(f"{CTX}:index", constants.CACHE_TTL_INDEX_SECONDS, _build_index)


def score_folder(folder: IndexedFolder, terms: list[str], phrase: str) -> float:
    titles = " ".join(t for t in (folder.title_en, folder.title_fr) if t)
    haystack = fold(f"{folder.path.rsplit('/', 1)[-1]} {titles}")
    words = haystack.split()
    matched = sum(1 for term in terms if any(w.startswith(term) for w in words))
    if matched == 0:
        return 0.0
    score = matched / len(terms)
    if len(terms) > 1 and phrase in haystack:
        score += 0.5
    # Dataset folders (depth 3) are what people look for; topic folders rarely are.
    return round(score + 0.05 * folder.depth, 3)


async def search(
    query: str,
    topic: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SearchResults:
    terms = fold(query or "").split()
    if not terms:
        _raise(
            InvalidInput,
            f"{CTX}: query must contain at least one word.",
            f"{CTX} : query doit contenir au moins un mot.",
            lang,
        )
    _check_limit(limit, constants.SEARCH_LIMIT_MAX, lang)
    (folders, skipped), cached = await _index()
    topics = sorted({f.path.split("/")[1] for f in folders})
    wanted_topic = topic.strip().strip("/").lower() if topic else None
    if wanted_topic and wanted_topic not in topics:
        _raise(
            InvalidInput,
            f"{CTX}: topic must be one of {topics}.",
            f"{CTX} : topic doit être l'un de {topics} (noms de dossiers du catalogue, en "
            "anglais).",
            lang,
        )
    phrase = " ".join(terms)
    scored = []
    for folder in folders:
        if wanted_topic and folder.path.split("/")[1] != wanted_topic:
            continue
        score = score_folder(folder, terms, phrase)
        if score:
            scored.append((score, folder))
    scored.sort(key=lambda s: (-s[0], s[1].path))
    hits = []
    for score, folder in scored[:limit]:
        own = folder.title_en if lang == "en" else folder.title_fr
        other = folder.title_fr if lang == "en" else folder.title_en
        hits.append(
            SearchHit(
                path=folder.path,
                title=own or other or folder.path.rsplit("/", 1)[-1],
                other_title=other if own else None,
                topic=folder.path.split("/")[1],
                depth=folder.depth,
                score=score,
                browse_url=browse_url(folder.path, lang),
            )
        )
    return SearchResults(
        query=query,
        hits=hits,
        total_hits=len(scored),
        indexed_folders=len(folders),
        index_depth=constants.INDEX_DEPTH,
        skipped_folders=skipped,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=constants.LISTING_URL,
            cached=cached,
            schema_name="eccc_datamart.SearchResults",
            freshness=_pick(
                "Folder index rebuilt at most once a day (about 60 listings).",
                "Index des dossiers reconstruit au plus une fois par jour (environ 60 listes).",
                lang,
            ),
            coverage=_pick(
                f"Folder names and bilingual titles down to {constants.INDEX_DEPTH} "
                "levels (topic / function / dataset); files and deeper folders (year folders, "
                "sub-datasets) are reached with eccc_datamart_browse. "
                + constants.UNDOCUMENTED_NOTE,
                f"Noms de dossiers et titres bilingues sur {constants.INDEX_DEPTH} niveaux "
                "(thème / fonction / jeu de données) ; les fichiers et les dossiers plus "
                "profonds (dossiers annuels, sous-jeux de données) s'atteignent avec "
                "eccc_datamart_browse. " + constants.UNDOCUMENTED_NOTE_FR,
                lang,
            ),
            limits=_pick(
                f"Showing {len(hits)} of {len(scored)} matching folders.",
                f"{len(hits)} des {len(scored)} dossiers correspondants sont affichés.",
                lang,
            )
            if len(scored) > len(hits)
            else None,
            licence=_licence(lang),
            lang=lang,
        ),
    )


# --- files ----------------------------------------------------------------------------


@dataclass
class FileContext:
    path: str
    entry: CatalogueEntry
    siblings: list[CatalogueEntry]
    catalogue_id: str | None
    folder: str


async def _file_context(path: str, lang: Lang) -> FileContext:
    target = normalize_path(path, lang)
    if target == "/":
        _raise(
            InvalidInput,
            f"{CTX}: path must name a file.",
            f"{CTX} : path doit désigner un fichier.",
            lang,
        )
    folder = target.rsplit("/", 1)[0] or "/"
    data, _ = await _listing(folder, lang)
    catalogue_id = data.get("path_catalogue_id") or None
    siblings = [parse_entry(e, catalogue_id, lang) for e in list_or_empty(data, "path_contents")]
    entry = next((e for e in siblings if e.path == target), None)
    if entry is None:
        _raise(
            NotFound,
            f"{CTX}: no file {target!r}; eccc_datamart_browse with path={folder!r} lists "
            "the folder.",
            f"{CTX} : aucun fichier {target!r} ; eccc_datamart_browse avec path={folder!r} "
            "liste le dossier.",
            lang,
        )
    if entry.kind == "folder":
        _raise(
            InvalidInput,
            f"{CTX}: {target!r} is a folder; use eccc_datamart_browse.",
            f"{CTX} : {target!r} est un dossier ; utilisez eccc_datamart_browse.",
            lang,
        )
    return FileContext(target, entry, siblings, catalogue_id, folder)


def _check_readable(entry: CatalogueEntry, lang: Lang = "en") -> None:
    url = entry.file_url
    if entry.kind == "archive":
        _raise(
            InvalidInput,
            f"{CTX}: {entry.name} is a ZIP or other archive ({entry.size}); this reader does "
            f"not open archives. Download it from {url}.",
            f"{CTX} : {entry.name} est une archive ZIP ou autre ({entry.size}) ; ce lecteur "
            f"n'ouvre pas les archives. Téléchargez-la depuis {url}.",
            lang,
        )
    if _suffix(entry.name) not in constants.READABLE_SUFFIXES:
        _raise(
            InvalidInput,
            f"{CTX}: {entry.name} is not a CSV, TSV, TXT or Excel table, so it is not read "
            f"here. Download it from {url}.",
            f"{CTX} : {entry.name} n'est pas un tableau CSV, TSV, TXT ou Excel ; il n'est "
            f"donc pas lu ici. Téléchargez-le depuis {url}.",
            lang,
        )
    if _surely_too_big(entry.size):
        cap = constants.MAX_FILE_BYTES // (1024 * 1024)
        _raise(
            InvalidInput,
            f"{CTX}: {entry.name} is {entry.size}, above this reader's "
            f"{cap} MB cap. Download it from {url}.",
            f"{CTX} : {entry.name} fait {entry.size}, au-delà du plafond de {cap} Mo de ce "
            f"lecteur. Téléchargez-le depuis {url}.",
            lang,
        )


def _allow_host(host: str) -> bool:
    return host == constants.DOMAIN


async def _body(path: str) -> tuple[file_download.Downloaded, bool]:
    url = file_url(path)

    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=_allow_host,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context=CTX,
        )

    return await file_download.cached_download(
        file_download.cache_key(url), constants.CACHE_TTL_FILE_SECONDS, fetch
    )


def _excerpt(body: bytes) -> str:
    text = tables.decode(body)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return joined[: constants.DOC_EXCERPT_CHARS]


async def _documentation(ctx: FileContext) -> list[DocumentationFile]:
    docs: list[DocumentationFile] = []
    excerpts = 0
    for entry in ctx.siblings:
        if entry.kind != "documentation" or entry.name == ".dir_metadata.json":
            continue
        excerpt = None
        small = (entry.size_bytes or 0) <= constants.DOC_EXCERPT_MAX_BYTES
        if (
            _suffix(entry.name) in (".csv", ".txt")
            and small
            and excerpts < constants.DOC_EXCERPTS_MAX
        ):
            downloaded, _ = await _body(entry.path)
            excerpt = _excerpt(downloaded.body)
            excerpts += 1
        docs.append(
            DocumentationFile(
                name=entry.name,
                path=entry.path,
                size=entry.size,
                file_url=entry.file_url or file_url(entry.path),
                excerpt=excerpt,
            )
        )
    return docs


def _freshness(entry: CatalogueEntry, lang: Lang = "en") -> str:
    if lang == "fr":
        return french_spacing(
            f"Tel que publié par ECCC ; fichier modifié le {entry.modified or 'date non indiquée'}."
        )
    return f"As published by ECCC; file modified {entry.modified or 'date not stated'}."


async def describe_file(path: str, sheet: str | None = None, lang: Lang = "en") -> FileStructure:
    ctx = await _file_context(path, lang)
    _check_readable(ctx.entry, lang)
    downloaded, cached = await _body(ctx.path)
    fmt = tables.detect_format(downloaded.body, _suffix(ctx.entry.name).lstrip("."))
    sizes = await run_parse(tables.sheet_sizes, downloaded.body, fmt)
    only = tables.choose_sheet(sizes, sheet, fmt, CTX)[0] if sheet is not None else None
    if fmt == "csv":
        only = None
    total, summaries = await run_parse(tables.describe, downloaded.body, fmt, only)
    docs = await _documentation(ctx)
    return FileStructure(
        path=ctx.path,
        file_url=file_url(ctx.path),
        format=fmt,
        size=ctx.entry.size,
        modified=ctx.entry.modified,
        folder_title=await _folder_title(ctx.folder, lang),
        catalogue_url=_catalogue_url(ctx.catalogue_id, lang),
        sheets=[
            SheetInfo(
                name=s.name,
                rows=s.rows,
                columns=s.columns,
                header_row=s.header_row,
                column_names=s.column_names,
                preview=s.preview,
            )
            for s in summaries
        ],
        total_sheets=total,
        truncated=len(summaries) < (1 if only else total),
        documentation=docs,
        attribution=_attribution(lang),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=file_url(ctx.path),
            cached=cached,
            schema_name="eccc_datamart.FileStructure",
            freshness=_freshness(ctx.entry, lang),
            coverage=_undocumented(lang),
            limits=(
                _pick(
                    f"Described the first {tables.MAX_DESCRIBED_SHEETS} of {total} sheets.",
                    f"Les {tables.MAX_DESCRIBED_SHEETS} premières feuilles sur {total} sont "
                    "décrites.",
                    lang,
                )
                if total > tables.MAX_DESCRIBED_SHEETS and not only
                else None
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )


async def read_file(
    path: str,
    sheet: str | None = None,
    columns: list[str] | None = None,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileRows:
    _validate_page(limit, offset, lang)
    if header_row is not None and header_row < 1:
        _raise(
            InvalidInput,
            f"{CTX}: header_row is 1-based (1 or more).",
            f"{CTX} : header_row commence à 1 (1 ou plus).",
            lang,
        )
    if not 1 <= header_rows <= 5:
        _raise(
            InvalidInput,
            f"{CTX}: header_rows must be 1 to 5.",
            f"{CTX} : header_rows doit être compris entre 1 et 5.",
            lang,
        )
    ctx = await _file_context(path, lang)
    _check_readable(ctx.entry, lang)
    downloaded, cached = await _body(ctx.path)
    fmt = tables.detect_format(downloaded.body, _suffix(ctx.entry.name).lstrip("."))
    sizes = await run_parse(tables.sheet_sizes, downloaded.body, fmt)
    names = [n for n, _, _ in sizes]
    if not names:
        _raise(
            UpstreamError,
            f"{CTX}: {ctx.path} has no sheets.",
            f"{CTX} : {ctx.path} n'a aucune feuille.",
            lang,
        )
    chosen, how = tables.choose_sheet(sizes, sheet, fmt, CTX)

    def provenance(limits: str | None):
        return make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=file_url(ctx.path),
            cached=cached,
            schema_name="eccc_datamart.FileRows",
            freshness=_freshness(ctx.entry, lang),
            coverage=_undocumented(lang),
            limits=limits,
            licence=_licence(lang),
            lang=lang,
        )

    if chosen is None:
        return FileRows(
            path=ctx.path,
            file_url=file_url(ctx.path),
            format=fmt,
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
            attribution=_attribution(lang),
            provenance=provenance(
                _pick(
                    f"the workbook has {len(names)} sheets of similar size and none was "
                    "requested, so no rows were read: pass one of `sheets` as `sheet`.",
                    f"le classeur compte {len(names)} feuilles de taille semblable et aucune "
                    "n'a été demandée ; aucune ligne n'a donc été lue : passez l'une des "
                    "`sheets` comme `sheet`.",
                    lang,
                )
            ),
        )
    result = await run_parse(
        tables.scan,
        downloaded.body,
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
    notes: list[str] = []
    if how == "largest":
        notes.append(
            f"no sheet was requested, so the largest ({chosen!r}) was read"
            if lang != "fr"
            else f"aucune feuille demandée : la plus grande ({chosen!r}) a été lue"
        )
    if result.capped:
        notes.append(
            f"the file was scanned only up to {tables.MAX_SCAN_ROWS} rows"
            if lang != "fr"
            else f"le fichier n'a été parcouru que jusqu'à {tables.MAX_SCAN_ROWS} lignes"
        )
    if more:
        last = offset + len(result.rows)
        notes.append(
            f"showing rows {offset + 1} to {last} of {result.total_rows}"
            if lang != "fr"
            else f"lignes {offset + 1} à {last} sur {result.total_rows}"
        )
    return FileRows(
        path=ctx.path,
        file_url=file_url(ctx.path),
        format=fmt,
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
        attribution=_attribution(lang),
        provenance=provenance(
            (french_spacing(" ; ".join(notes)) if lang == "fr" else "; ".join(notes)) or None
        ),
    )


# --- NPRI and GHGRP lookups --------------------------------------------------------


def province_code(value: str | None, lang: Lang = "en") -> str | None:
    if value is None or not value.strip():
        return None
    wanted = fold(value)
    for code, (en, fr) in PROVINCES.items():
        if wanted in (code.lower(), fold(en), fold(fr)):
            return code
    _raise(
        InvalidInput,
        f"{CTX}: unknown province {value!r}; use a two-letter code such as AB or QC, or a name.",
        f"{CTX} : province inconnue {value!r} ; utilisez un code à deux lettres comme AB ou "
        "QC, ou un nom.",
        lang,
    )


def _rows(body: bytes) -> Iterator[list[str]]:
    for index, row in enumerate(csv.reader(io.StringIO(tables.decode(body)))):
        if index % 500 == 0:
            check_deadline()
        yield row


def locate(
    header: list[str], rules: dict[str, str], name: str, lang: Lang = "en"
) -> dict[str, int]:
    """Column index per field; a rule is a substring of the bilingual header text."""
    folded = [" ".join(h.split()).casefold() for h in header]
    found: dict[str, int] = {}
    for field, needle in rules.items():
        index = next((i for i, h in enumerate(folded) if needle in h), None)
        if index is None:
            _raise(
                UpstreamError,
                f"{CTX}: the {name} file has no column matching {needle!r}; its layout "
                "changed. eccc_datamart_describe_file shows the current columns.",
                f"{CTX} : le fichier {name} n'a aucune colonne correspondant à {needle!r} ; "
                "sa structure a changé. eccc_datamart_describe_file montre les colonnes "
                "actuelles.",
                lang,
            )
        found[field] = index
    return found


def _number(text: str) -> float | None:
    value = text.strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _text(text: str) -> str | None:
    value = " ".join(text.split())
    return value or None


NPRI_COLUMNS = {
    "year": "/ year",
    "npri_id": "npri id",
    "company": "company name",
    "facility": "facility name",
    "city": "/ city",
    "province": "province / province",
    "latitude": "/ latitude",
    "longitude": "/ longitude",
    "naics": "naics 6 code",
    "naics_en": "naics 6 sector name (english)",
    "naics_fr": "naics 6 sector name (french)",
    "cas": "cas number",
    "substance_en": "substance name (english)",
    "substance_fr": "substance name (french)",
    "units": "/ units",
    "air": "air emissions - total",
    "water": "water releases - total",
    "land": "land releases - total",
    "road_dust": "road dust emissions",
    "total_releases": "total releases including road dust",
    "on_site": "on-site disposal - total on-site",
    "off_site": "off-site disposal - total off-site",
    "treatment": "transfers for treatment - total",
    "recycling": "transfers for recycling - total",
    "grand_total": "grand total",
}

GHGRP_COLUMNS = {
    "ghgrp_id": "ghgrp id",
    "year": "reference year",
    "facility": "facility name",
    "city": "facility city",
    "province": "facility province",
    "latitude": "latitude",
    "longitude": "longitude",
    "npri_id": "facility npri id",
    "naics": "facility naics code /",
    "naics_en": "english facility naics",
    "naics_fr": "french facility naics",
    "company": "reporting company legal name",
    "trade_name": "reporting company trade name",
    "co2": "co2 (tonnes)",
    "ch4": "ch4 (tonnes co2e",
    "n2o": "n2o (tonnes co2e",
    "hfc": "hfc total",
    "pfc": "pfc total",
    "sf6": "sf6 (tonnes co2e",
    "total": "total emissions",
    "biomass": "co2 from biomass",
}

_TONNES = {"tonnes": 1.0, "kg": 0.001, "grams": 1e-6}


def _contains(cell: str, needle: str | None) -> bool:
    return needle is None or needle in fold(cell)


def _prepare(value: str | None) -> str | None:
    return fold(value) if value and value.strip() else None


def _cell(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def scan_npri(
    body: bytes,
    *,
    lang: Lang,
    facility: str | None,
    company: str | None,
    province: str | None,
    substance: str | None,
    naics: str | None,
    npri_id: str | None,
    order: Order,
    offset: int,
    limit: int,
) -> tuple[list[NpriRecord], int, int]:
    rows = _rows(body)
    header = next(rows, None)
    if not header:
        _raise(
            UpstreamError,
            f"{CTX}: the NPRI file is empty.",
            f"{CTX} : le fichier de l'INRP est vide.",
            lang,
        )
    col = locate(header, NPRI_COLUMNS, "NPRI", lang)
    want_facility, want_company = _prepare(facility), _prepare(company)
    want_substance = _prepare(substance)
    cas = substance.strip() if substance else None
    matched: list[list[str]] = []
    for row in rows:
        if not any(row):
            continue
        if province and _cell(row, col["province"]).strip().upper() != province:
            continue
        if npri_id and _cell(row, col["npri_id"]).strip() != npri_id:
            continue
        if naics and not _cell(row, col["naics"]).strip().startswith(naics):
            continue
        if not _contains(_cell(row, col["facility"]), want_facility):
            continue
        if not _contains(_cell(row, col["company"]), want_company):
            continue
        if want_substance and not (
            _cell(row, col["cas"]).strip() == cas
            or want_substance in fold(_cell(row, col["substance_en"]))
            or want_substance in fold(_cell(row, col["substance_fr"]))
        ):
            continue
        matched.append(row)
    if order == "largest":

        def tonnes(row: list[str]) -> float:
            factor = _TONNES.get(_cell(row, col["units"]).strip().lower())
            total = _number(_cell(row, col["grand_total"])) or 0.0
            return total * factor if factor is not None else float("-inf")

        matched.sort(key=tonnes, reverse=True)
    facilities = len({_cell(r, col["npri_id"]) for r in matched})
    page = matched[offset : offset + limit]
    suffix = "en" if lang == "en" else "fr"
    records = [
        NpriRecord(
            year=int(_number(_cell(r, col["year"])) or 0),
            npri_id=_cell(r, col["npri_id"]).strip(),
            company=_text(_cell(r, col["company"])) or "",
            facility=_text(_cell(r, col["facility"])) or "",
            city=_text(_cell(r, col["city"])),
            province=_text(_cell(r, col["province"])),
            latitude=_number(_cell(r, col["latitude"])),
            longitude=_number(_cell(r, col["longitude"])),
            naics=_text(_cell(r, col["naics"])),
            naics_name=_text(_cell(r, col[f"naics_{suffix}"])),
            cas_number=_text(_cell(r, col["cas"])),
            substance=_text(_cell(r, col[f"substance_{suffix}"])) or "",
            units=_text(_cell(r, col["units"])) or "",
            air=_number(_cell(r, col["air"])),
            water=_number(_cell(r, col["water"])),
            land=_number(_cell(r, col["land"])),
            road_dust=_number(_cell(r, col["road_dust"])),
            total_releases=_number(_cell(r, col["total_releases"])),
            on_site_disposal=_number(_cell(r, col["on_site"])),
            off_site_disposal=_number(_cell(r, col["off_site"])),
            treatment_transfers=_number(_cell(r, col["treatment"])),
            recycling_transfers=_number(_cell(r, col["recycling"])),
            grand_total=_number(_cell(r, col["grand_total"])),
        )
        for r in page
    ]
    return records, len(matched), facilities


def _check_limit(limit: int, maximum: int, lang: Lang = "en") -> None:
    if not 1 <= limit <= maximum:
        _raise(
            InvalidInput,
            f"{CTX}: limit must be 1 to {maximum}.",
            f"{CTX} : limit doit être compris entre 1 et {maximum}.",
            lang,
        )


def _check_offset(offset: int, lang: Lang = "en") -> None:
    if offset < 0:
        _raise(
            InvalidInput,
            f"{CTX}: offset must be 0 or more.",
            f"{CTX} : offset doit être 0 ou plus.",
            lang,
        )


def _validate_page(limit: int, offset: int, lang: Lang = "en") -> None:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    _check_offset(offset, lang)


def _digits(value: str | None, field: str, lang: Lang = "en") -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if not text.isdigit():
        _raise(
            InvalidInput,
            f"{CTX}: {field} must be digits; got {value!r}.",
            f"{CTX} : {field} ne doit contenir que des chiffres ; reçu {value!r}.",
            lang,
        )
    return text


async def npri_facilities(
    year: int | None = None,
    facility: str | None = None,
    company: str | None = None,
    province: str | None = None,
    substance: str | None = None,
    naics: str | None = None,
    npri_id: str | None = None,
    order: Order = "file",
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> NpriResult:
    _validate_page(limit, offset, lang)
    code = province_code(province, lang)
    naics_code = _digits(naics, "naics", lang)
    facility_id = _digits(npri_id, "npri_id", lang)
    data, _ = await _listing(constants.NPRI_FOLDER, lang)
    files: dict[int, CatalogueEntry] = {}
    for raw in list_or_empty(data, "path_contents"):
        match = _NPRI_FILE.match(str(raw.get("name") or ""))
        if match:
            files[int(match["year"])] = parse_entry(raw, None, lang)
    if not files:
        _raise(
            UpstreamError,
            f"{CTX}: no NPRI single-year CSV found in {constants.NPRI_FOLDER}.",
            f"{CTX} : aucun CSV annuel de l'INRP dans {constants.NPRI_FOLDER}.",
            lang,
        )
    years = sorted(files)
    chosen_year = year if year is not None else years[-1]
    years_note = _note(
        "npri_years", lang, years=f"{years[0]}-{years[-1]}", bulk=constants.NPRI_BULK_FOLDER
    )
    if chosen_year not in files:
        _raise(
            InvalidInput,
            f"{CTX}: no NPRI single-year table for {chosen_year}. {years_note}",
            f"{CTX} : aucun tableau annuel de l'INRP pour {chosen_year}. {years_note}",
            lang,
        )
    entry = files[chosen_year]
    downloaded, cached = await _body(entry.path)
    records, total, facilities = await run_parse(
        scan_npri,
        downloaded.body,
        lang=lang,
        facility=facility,
        company=company,
        province=code,
        substance=substance,
        naics=naics_code,
        npri_id=facility_id,
        order=order,
        offset=offset,
        limit=limit,
    )
    notes = [_note("npri_units", lang), years_note]
    if order == "largest":
        notes.insert(0, _note("npri_largest", lang))
    more = offset + len(records) < total
    return NpriResult(
        year=chosen_year,
        available_years=years,
        file_path=entry.path,
        file_url=file_url(entry.path),
        records=records,
        total_records=total,
        facilities=facilities,
        offset=offset,
        truncated=more,
        notes=notes,
        attribution=_attribution(lang),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=file_url(entry.path),
            cached=cached,
            schema_name="eccc_datamart.NpriResult",
            freshness=_pick(
                f"NPRI single-year table, file modified {entry.modified}; ECCC "
                "revises past years when facilities correct reports.",
                f"Tableau annuel de l'INRP, fichier modifié le {entry.modified} ; ECCC révise "
                "les années passées quand les installations corrigent leurs déclarations.",
                lang,
            ),
            coverage=_pick(
                "One row per facility and substance reported to the National Pollutant "
                "Release Inventory. " + constants.UNDOCUMENTED_NOTE,
                "Une ligne par installation et par substance déclarée à l'Inventaire national "
                "des rejets de polluants. " + constants.UNDOCUMENTED_NOTE_FR,
                lang,
            ),
            limits=_pick(
                f"Showing records {offset + 1} to {offset + len(records)} of {total}.",
                f"Enregistrements {offset + 1} à {offset + len(records)} sur {total}.",
                lang,
            )
            if more or offset
            else None,
            licence=_licence(lang),
            lang=lang,
        ),
    )


def scan_ghgrp(
    body: bytes,
    *,
    lang: Lang,
    years: tuple[int, int] | None,
    facility: str | None,
    company: str | None,
    province: str | None,
    naics: str | None,
    ghgrp_id: str | None,
    npri_id: str | None,
    order: Order,
    offset: int,
    limit: int,
) -> tuple[list[GhgrpRecord], int, int, float, list[int]]:
    rows = _rows(body)
    header = next(rows, None)
    if not header:
        _raise(
            UpstreamError,
            f"{CTX}: the GHGRP file is empty.",
            f"{CTX} : le fichier du PDGES est vide.",
            lang,
        )
    col = locate(header, GHGRP_COLUMNS, "GHGRP", lang)
    want_facility, want_company = _prepare(facility), _prepare(company)
    province_name = fold(PROVINCES[province][0]) if province else None
    all_years: set[int] = set()
    matched: list[list[str]] = []
    for row in rows:
        if not any(row):
            continue
        year = _number(_cell(row, col["year"]))
        if year is None:
            continue
        all_years.add(int(year))
        if years and not years[0] <= year <= years[1]:
            continue
        if province_name and fold(_cell(row, col["province"])) != province_name:
            continue
        if ghgrp_id and _cell(row, col["ghgrp_id"]).strip().upper() != ghgrp_id:
            continue
        if npri_id and _cell(row, col["npri_id"]).strip() != npri_id:
            continue
        if naics and not _cell(row, col["naics"]).strip().startswith(naics):
            continue
        if not _contains(_cell(row, col["facility"]), want_facility):
            continue
        if want_company and not (
            _contains(_cell(row, col["company"]), want_company)
            or _contains(_cell(row, col["trade_name"]), want_company)
        ):
            continue
        matched.append(row)
    if order == "largest":
        matched.sort(key=lambda r: _number(_cell(r, col["total"])) or 0.0, reverse=True)
    facilities = len({_cell(r, col["ghgrp_id"]) for r in matched})
    total_sum = sum(_number(_cell(r, col["total"])) or 0.0 for r in matched)
    suffix = "en" if lang == "en" else "fr"
    records = []
    for r in matched[offset : offset + limit]:
        npri = _cell(r, col["npri_id"]).strip()
        records.append(
            GhgrpRecord(
                ghgrp_id=_cell(r, col["ghgrp_id"]).strip(),
                year=int(_number(_cell(r, col["year"])) or 0),
                facility=_text(_cell(r, col["facility"])) or "",
                city=_text(_cell(r, col["city"])),
                province=_text(_cell(r, col["province"])),
                latitude=_number(_cell(r, col["latitude"])),
                longitude=_number(_cell(r, col["longitude"])),
                npri_id=None if npri in ("", "0") else npri,
                naics=_text(_cell(r, col["naics"])),
                naics_name=_text(_cell(r, col[f"naics_{suffix}"])),
                company=_text(_cell(r, col["company"])),
                company_trade_name=_text(_cell(r, col["trade_name"])),
                co2_tonnes=_number(_cell(r, col["co2"])),
                ch4_co2e=_number(_cell(r, col["ch4"])),
                n2o_co2e=_number(_cell(r, col["n2o"])),
                hfc_co2e=_number(_cell(r, col["hfc"])),
                pfc_co2e=_number(_cell(r, col["pfc"])),
                sf6_co2e=_number(_cell(r, col["sf6"])),
                total_co2e=_number(_cell(r, col["total"])),
                co2_biomass_tonnes=_number(_cell(r, col["biomass"])),
            )
        )
    return records, len(matched), facilities, round(total_sum, 3), sorted(all_years)


async def ghgrp_facilities(
    year: int | None = None,
    year_to: int | None = None,
    facility: str | None = None,
    company: str | None = None,
    province: str | None = None,
    naics: str | None = None,
    ghgrp_id: str | None = None,
    npri_id: str | None = None,
    order: Order = "file",
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> GhgrpResult:
    _validate_page(limit, offset, lang)
    if year_to is not None and year is None:
        _raise(
            InvalidInput,
            f"{CTX}: year_to needs year (the start of the range).",
            f"{CTX} : year_to exige year (le début de la période).",
            lang,
        )
    span = None if year is None else (year, year_to if year_to is not None else year)
    if span and span[1] < span[0]:
        _raise(
            InvalidInput,
            f"{CTX}: year_to must not be before year.",
            f"{CTX} : year_to ne doit pas précéder year.",
            lang,
        )
    code = province_code(province, lang)
    gid = ghgrp_id.strip().upper() if ghgrp_id and ghgrp_id.strip() else None
    data, _ = await _listing(constants.GHGRP_FOLDER, lang)
    entry = next(
        (
            parse_entry(raw, None, lang)
            for raw in list_or_empty(data, "path_contents")
            if _GHGRP_FILE.match(str(raw.get("name") or ""))
        ),
        None,
    )
    if entry is None:
        _raise(
            UpstreamError,
            f"{CTX}: no GHGRP emissions CSV found in {constants.GHGRP_FOLDER}.",
            f"{CTX} : aucun CSV des émissions du PDGES dans {constants.GHGRP_FOLDER}.",
            lang,
        )
    downloaded, cached = await _body(entry.path)
    records, total, facilities, total_sum, years = await run_parse(
        scan_ghgrp,
        downloaded.body,
        lang=lang,
        years=span,
        facility=facility,
        company=company,
        province=code,
        naics=_digits(naics, "naics", lang),
        ghgrp_id=gid,
        npri_id=_digits(npri_id, "npri_id", lang),
        order=order,
        offset=offset,
        limit=limit,
    )
    if span and years and (span[1] < years[0] or span[0] > years[-1]):
        _raise(
            InvalidInput,
            f"{CTX}: the GHGRP file covers {years[0]}-{years[-1]}; got {span[0]}-{span[1]}.",
            f"{CTX} : le fichier du PDGES couvre {years[0]}-{years[-1]} ; période demandée : "
            f"{span[0]}-{span[1]}.",
            lang,
        )
    more = offset + len(records) < total
    return GhgrpResult(
        years=years,
        file_path=entry.path,
        file_url=file_url(entry.path),
        file_modified=entry.modified,
        records=records,
        total_records=total,
        facilities=facilities,
        total_co2e_sum=total_sum,
        offset=offset,
        truncated=more,
        notes=[_note("ghgrp_gwp", lang), _note("ghgrp_contacts", lang)],
        attribution=_attribution(lang),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=file_url(entry.path),
            cached=cached,
            schema_name="eccc_datamart.GhgrpResult",
            freshness=_pick(
                f"Greenhouse Gas Reporting Program facility file, modified "
                f"{entry.modified}; updated once a year with the new reference year and "
                "revisions to past years.",
                f"Fichier des installations du Programme de déclaration des gaz à effet de "
                f"serre, modifié le {entry.modified} ; mis à jour une fois par an avec la "
                "nouvelle année de référence et les révisions des années passées.",
                lang,
            ),
            coverage=_pick(
                "One row per facility and reference year, emissions by gas. "
                + constants.UNDOCUMENTED_NOTE,
                "Une ligne par installation et par année de référence, émissions par gaz. "
                + constants.UNDOCUMENTED_NOTE_FR,
                lang,
            ),
            limits=_pick(
                f"Showing records {offset + 1} to {offset + len(records)} of {total}.",
                f"Enregistrements {offset + 1} à {offset + len(records)} sur {total}.",
                lang,
            )
            if more or offset
            else None,
            licence=_licence(lang),
            lang=lang,
        ),
    )
