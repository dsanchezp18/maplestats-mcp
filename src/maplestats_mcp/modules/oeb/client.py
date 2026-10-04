"""Client for the Ontario Energy Board open data pages and files.

Catalogue: the three English listing pages give each dataset's slug, title,
description and update frequency; each dataset page gives its file types,
"Last updated" date and files (current and archived releases). French titles
come from the French listing, matched through each English page's hreflang
alternate. Files are read whole under a size cap (shared/file_download.py,
https and oeb.ca only, cached in the shared byte budget) and parsed in the
parse pool (records.py).
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from maplestats_mcp.modules.oeb import constants, pages, records
from maplestats_mcp.modules.oeb.schemas import (
    Cell,
    DatasetDetail,
    DatasetList,
    DatasetSummary,
    FieldInfo,
    OebFile,
    QueryResult,
    RateField,
    RatesTable,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import new_client, send_with_retry
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import TokenBucket, get_limiter

_LIMITER = get_limiter(
    constants.SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_client = new_client(timeout=constants.PAGE_TIMEOUT_SECONDS, follow_redirects=False)
_MAX_REDIRECTS = 3
_MAX_HOPS = 2

# Field names (normalized: lower case, letters and digits only) that hold the
# company, as found across the 196 XML files and the workbooks on 2026-10-03:
# Current_Company_Name / Historical_Company_Name in the 2024 RRR files,
# Company_Name, Company, Merged_or_Current, Company_Name__x0028_Merged_or_
# Current_x0029_ in older releases, dist/Dist/comdist in the scorecard, rate
# and complaint files, LICENCE_NAME and APPLICANT1 in the licence and
# application reports, "Company Name" in the rates databases.
_COMPANY_EXACT = frozenset({"dist", "comdist", "licencename", "applicant1", "company"})
_YEAR_EXACT = frozenset({"year", "fiscalyear", "filingyear", "comyear", "rateyear"})


def _lower_first(text: str) -> str:
    """French error details follow "Entrée invalide :", so they start in lower case."""
    return text[:1].lower() + text[1:]


def norm(text: str) -> str:
    """Lower case, accents dropped, letters and digits only."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z0-9.]+", folded) if t]


def is_company_field(name: str) -> bool:
    key = norm(name)
    return "company" in key or key in _COMPANY_EXACT or key.startswith("mergedorcurrent")


def is_year_field(name: str) -> bool:
    return norm(name) in _YEAR_EXACT


def _allowed(host: str) -> bool:
    return host in constants.ALLOWED_HOSTS


def _limiter_for(_host: str) -> TokenBucket:
    return _LIMITER


def request_url(url: str) -> str:
    """Percent-encode the spaces, '&' stays (the server takes both, 2026-10-03)."""
    return quote(url, safe=":/?=&%()',+~;")


async def _get_html(url: str, lang: str) -> str:
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        await _LIMITER.acquire()
        try:
            response = await send_with_retry(
                _client, "GET", request_url(current), timeout=constants.PAGE_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as exc:
            raise_localized(
                UpstreamUnavailable,
                f"www.oeb.ca did not answer for {current} ({type(exc).__name__}).",
                f"www.oeb.ca n'a pas répondu pour {current} ({type(exc).__name__}).",
                lang,
            )
        if response.status_code in (301, 302, 303, 307, 308):
            target = urljoin(current, response.headers.get("location", ""))
            if not _allowed(urlparse(target).hostname or ""):
                raise_localized(
                    UpstreamError,
                    f"{current} redirected off www.oeb.ca, to {target}.",
                    f"{current} redirige hors de www.oeb.ca, vers {target}.",
                    lang,
                )
            current = target
            continue
        if response.status_code == 404:
            raise_localized(
                NotFound,
                f"No OEB page at {current}.",
                f"aucune page de la CEO à {current}.",
                lang,
            )
        if response.status_code >= 400:
            raise_localized(
                UpstreamError,
                f"{current} returned HTTP {response.status_code}.",
                f"{current} a renvoyé le code HTTP {response.status_code}.",
                lang,
            )
        return response.text
    raise_localized(
        UpstreamError,
        f"{url} redirected more than {_MAX_REDIRECTS} times.",
        f"{url} a redirigé plus de {_MAX_REDIRECTS} fois.",
        lang,
    )


async def _listing_rows(lang: str) -> list[pages.ListingRow]:
    """Every row of the English (or French) listing, following the pager."""
    base = constants.LISTING_URL if lang == "en" else constants.LISTING_URL_FR
    prefix = "/open-data/" if lang == "en" else "/fr/donnees-ouvertes/"

    async def fetch() -> list[pages.ListingRow]:
        rows: list[pages.ListingRow] = []
        for page_number in range(constants.MAX_LISTING_PAGES):
            html = await _get_html(f"{base}?page={page_number}", lang)
            page_rows, has_next = pages.parse_listing(html, prefix=prefix)
            rows.extend(page_rows)
            if not has_next:
                return rows
        return rows

    rows, _ = await cached_fetch(f"oeb:listing:{lang}", constants.CATALOGUE_TTL_SECONDS, fetch)
    if not rows:
        raise_localized(
            UpstreamError,
            f"The OEB open data listing at {base} showed no datasets.",
            f"la liste des données ouvertes de la CEO à {base} n'affichait aucun jeu de données.",
            lang,
        )
    return rows


async def _yearbook_page(lang: str) -> pages.DatasetPage:
    async def fetch() -> list[pages.PageFile]:
        return pages.parse_yearbook_links(await _get_html(f"{constants.LISTING_URL}?page=0", lang))

    files, _ = await cached_fetch("oeb:yearbook", constants.CATALOGUE_TTL_SECONDS, fetch)
    return pages.DatasetPage(
        slug=constants.YEARBOOK_SLUG,
        title=constants.YEARBOOK_TITLE,
        description=constants.YEARBOOK_DESCRIPTION,
        file_types=["XLSX"],
        update_frequency=None,
        last_updated=None,
        fr_path=None,
        files=files,
    )


async def _dataset_page(slug: str, lang: str) -> pages.DatasetPage:
    if slug == constants.YEARBOOK_SLUG:
        return await _yearbook_page(lang)

    async def fetch() -> pages.DatasetPage:
        url = constants.DATASET_URL.format(slug=slug)
        page = pages.parse_dataset_page(await _get_html(url, lang), slug)
        # Two pages link only to another oeb.ca page that lists the files
        # (distribution rates databases, intervenor cost awards).
        if not page.files:
            for hop in page.hops[:_MAX_HOPS]:
                page.files.extend(pages.parse_hop_page(await _get_html(hop, lang), hop))
        return page

    page, _ = await cached_fetch(f"oeb:page:{slug}", constants.CATALOGUE_TTL_SECONDS, fetch)
    return page


def _files(page: pages.DatasetPage) -> list[OebFile]:
    return [
        OebFile(
            index=i,
            name=f.name,
            caption=f.caption,
            release=f.release,
            format=f.format,  # type: ignore[arg-type]
            readable=f.format in ("xml", "xlsx"),
            url=f.url,
        )
        for i, f in enumerate(page.files, start=1)
    ]


def _note(files: list[OebFile], lang: str) -> str | None:
    if any(f.readable for f in files):
        return None
    if any(f.format == "zip" for f in files):
        return pick(
            lang,
            "Map files (KMZ inside zip archives) for GIS software, not tables: the rows are "
            "not read here. Download them from the page.",
            "Fichiers cartographiques (KMZ dans des archives zip) pour logiciels SIG, et non "
            "des tableaux : les lignes ne sont pas lues ici. Téléchargez-les depuis la page.",
        )
    return pick(
        lang,
        "The page links no XML or Excel file that can be read.",
        "La page ne renvoie à aucun fichier XML ou Excel lisible.",
    )


def _summary(
    page: pages.DatasetPage,
    row: pages.ListingRow | None,
    fr_rows: dict[str, pages.ListingRow],
    lang: str,
) -> DatasetSummary:
    files = _files(page)
    title = row.title if row else page.title
    description = page.description or (row.description if row else "")
    frequency = page.update_frequency or (row.update_frequency if row else None)
    if lang == "fr":
        if page.slug == constants.YEARBOOK_SLUG:
            title, description = constants.YEARBOOK_TITLE_FR, constants.YEARBOOK_DESCRIPTION_FR
        elif page.fr_path and page.fr_path in fr_rows:
            fr = fr_rows[page.fr_path]
            title, description = fr.title, fr.description or description
            frequency = fr.update_frequency or frequency
    page_url = (
        constants.LISTING_URL
        if page.slug == constants.YEARBOOK_SLUG
        else constants.DATASET_URL.format(slug=page.slug)
    )
    return DatasetSummary(
        slug=page.slug,
        title=title,
        description=description,
        update_frequency=frequency,
        last_updated=page.last_updated,
        file_types=page.file_types,
        current_files=sum(1 for f in files if f.release == "current"),
        archived_files=sum(1 for f in files if f.release != "current"),
        readable=any(f.readable for f in files),
        note=_note(files, lang),
        page_url=page_url,
    )


async def _fr_rows(lang: str) -> dict[str, pages.ListingRow]:
    if lang != "fr":
        return {}
    return {row.path: row for row in await _listing_rows("fr")}


def _provenance(
    url: str,
    schema: str,
    lang: str,
    *,
    cached: bool,
    freshness: str | None = None,
    limits: str | None = None,
    coverage: str | None = None,
    as_of: Any = None,
) -> Provenance:
    as_of_dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) if as_of else None
    return make_provenance(
        source=constants.SOURCE,
        url=url,
        cached=cached,
        schema_name=f"oeb.{schema}",
        as_of=as_of_dt,
        freshness=freshness,
        coverage=coverage,
        limits=limits,
        licence=pick(lang, constants.LICENCE, constants.LICENCE_FR),
        lang=lang,
    )


async def list_datasets(query: str | None = None, *, lang: str = "en") -> DatasetList:
    rows = await _listing_rows("en")
    fr_rows = await _fr_rows(lang)
    page_list = await asyncio.gather(*(_dataset_page(r.slug, lang) for r in rows))
    yearbook = await _yearbook_page(lang)
    summaries = [_summary(p, r, fr_rows, lang) for p, r in zip(page_list, rows, strict=True)]
    summaries.append(_summary(yearbook, None, fr_rows, lang))
    if query and query.strip():
        wanted = _tokens(query)
        english = {r.slug: f"{r.title} {r.description}" for r in rows}

        def hit(s: DatasetSummary) -> bool:
            text = " ".join(
                _tokens(f"{s.slug} {s.title} {s.description} {english.get(s.slug, '')}")
            )
            return all(token in text for token in wanted)

        summaries = [s for s in summaries if hit(s)]
    return DatasetList(
        query=query,
        total=len(summaries),
        datasets=summaries,
        provenance=_provenance(
            constants.LISTING_URL,
            "DatasetList",
            lang,
            cached=False,
            coverage=pick(
                lang,
                "Every dataset page on the OEB open data page, plus the 2021 yearbook workbooks "
                "linked from it.",
                "Toutes les pages de jeux de données de la page des données ouvertes de la CEO, "
                "plus les classeurs de l'annuaire 2021 qui y sont liés.",
            ),
        ),
    )


async def _resolve(dataset: str, lang: str) -> tuple[pages.DatasetPage, pages.ListingRow | None]:
    key = dataset.strip().strip("/").rsplit("/", 1)[-1]
    if not key:
        raise_localized(
            InvalidInput, "dataset must not be empty.", "dataset ne doit pas être vide.", lang
        )
    rows = await _listing_rows("en")
    by_slug = {r.slug: r for r in rows}
    if key == constants.YEARBOOK_SLUG or norm(key) in ("yearbook", "yearbook2021"):
        return await _yearbook_page(lang), None
    if key in by_slug:
        return await _dataset_page(key, lang), by_slug[key]
    wanted = _tokens(key.replace("-", " "))
    fr_rows = await _listing_rows("fr") if lang == "fr" else []
    candidates = [
        r for r in rows if all(t in " ".join(_tokens(f"{r.slug} {r.title}")) for t in wanted)
    ]
    if not candidates and fr_rows:
        fr_hits = [r for r in fr_rows if all(t in " ".join(_tokens(r.title)) for t in wanted)]
        if fr_hits:
            pages_fr = await asyncio.gather(*(_dataset_page(r.slug, lang) for r in rows))
            paths = {r.path for r in fr_hits}
            candidates = [r for r, p in zip(rows, pages_fr, strict=True) if p.fr_path in paths]
    exact = [r for r in candidates if norm(r.title) == norm(key)]
    if len(exact) == 1 or len(candidates) == 1:
        row = (exact or candidates)[0]
        return await _dataset_page(row.slug, lang), row
    if not candidates:
        raise_localized(
            NotFound,
            f"No OEB open data dataset matches {dataset!r}. Call oeb_list_datasets for slugs.",
            f"aucun jeu de données ouvertes de la CEO ne correspond à {dataset!r}. Appelez "
            "oeb_list_datasets pour les identifiants.",
            lang,
        )
    names = ", ".join(r.slug for r in candidates[:8])
    raise_localized(
        InvalidInput,
        f"{dataset!r} matches {len(candidates)} datasets; pass one slug: {names}.",
        f"{dataset!r} correspond à {len(candidates)} jeux de données; donnez un "
        f"identifiant : {names}.",
        lang,
    )


def _select_file(files: list[OebFile], file: str | None, release: str | None, lang: str) -> OebFile:
    pool = files
    if release and release.strip().lower() not in ("", "all"):
        wanted = release.strip().lower()
        pool = [f for f in files if f.release == wanted or f.release.startswith(wanted)]
        if not pool:
            releases = sorted({f.release for f in files})
            raise_localized(
                InvalidInput,
                f"No release {release!r}; releases are {releases}.",
                f"aucune publication {release!r}; publications : {releases}.",
                lang,
            )
    if file is None or not str(file).strip():
        current = [f for f in pool if f.readable and f.release == "current"] or [
            f for f in pool if f.readable
        ]
        if not current:
            raise_localized(
                InvalidInput,
                _note(files, "en") or "No readable file.",
                _lower_first(_note(files, "fr") or "aucun fichier lisible."),
                lang,
            )
        return current[0]
    text = str(file).strip()
    # A small number is a position in the list; a year ("2025") is matched
    # against file names like the rates databases' "2025 Annual Rates Database".
    if text.isdigit() and int(text) <= len(files):
        return files[int(text) - 1]
    wanted = norm(text)
    matches = [f for f in pool if wanted in norm(f"{f.name} {f.caption or ''}")]
    if not matches:
        raise_localized(
            InvalidInput,
            f"No file matches {file!r}; call oeb_describe_dataset for the file list.",
            f"aucun fichier ne correspond à {file!r}; appelez oeb_describe_dataset pour la "
            "liste des fichiers.",
            lang,
        )
    current = [f for f in matches if f.release == "current"]
    return (current or matches)[0]


async def _download(file: OebFile, lang: str) -> tuple[bytes, bool]:
    if not file.readable:
        raise_localized(
            InvalidInput,
            f"{file.name} is a {file.format} file whose rows are not read here; download it "
            f"from {file.url}.",
            f"{file.name} est un fichier {file.format} dont les lignes ne sont pas lues ici; "
            f"téléchargez-le à {file.url}.",
            lang,
        )
    url = request_url(file.url)
    max_bytes = constants.MAX_FILE_BYTES if file.format == "xml" else constants.MAX_XLSX_BYTES

    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=_allowed,
            limiter_for=_limiter_for,
            max_bytes=max_bytes,
            context="oeb",
            timeout=constants.FILE_TIMEOUT_SECONDS,
        )

    got, cached = await file_download.cached_download(
        file_download.cache_key(url), constants.FILE_TTL_SECONDS, fetch
    )
    body = got.body
    if file.format == "xlsx" and not body.startswith(b"PK"):
        raise_localized(
            UpstreamError,
            f"{file.url} is not an Excel workbook (got {body[:20]!r}).",
            f"{file.url} n'est pas un classeur Excel (reçu {body[:20]!r}).",
            lang,
        )
    if file.format == "xml" and not body.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
        raise_localized(
            UpstreamError,
            f"{file.url} is not XML (got {body[:20]!r}).",
            f"{file.url} n'est pas un fichier XML (reçu {body[:20]!r}).",
            lang,
        )
    return body, cached


def _rows(body: bytes, fmt: str, sheet: str | None) -> Iterator[dict[str, Cell]]:
    if fmt == "xml":
        return (record for _, record in records.xml_records(body))
    return records.xlsx_records(body, sheet or "")


async def _sheet_for(
    body: bytes, fmt: str, sheet: str | None, lang: str
) -> tuple[str | None, list[str]]:
    if fmt != "xlsx":
        return None, []
    names = await run_parse(records.xlsx_sheets, body)
    if sheet is None:
        return names[0], names
    for name in names:
        if norm(name) == norm(sheet):
            return name, names
    raise_localized(
        InvalidInput,
        f"No sheet {sheet!r}; sheets are {names}.",
        f"aucune feuille {sheet!r}; feuilles : {names}.",
        lang,
    )


def _describe_scan(body: bytes, fmt: str, sheet: str | None) -> dict[str, Any]:
    count = 0
    stats: dict[str, list[Any]] = {}
    years: set[str] = set()
    companies: set[str] = set()
    for record in _rows(body, fmt, sheet):
        count += 1
        for name, value in record.items():
            entry = stats.setdefault(name, [0, True, []])
            if value is None:
                continue
            entry[0] += 1
            if isinstance(value, str):
                entry[1] = False
            text = str(value)
            if len(entry[2]) < constants.MAX_EXAMPLES and text not in entry[2]:
                entry[2].append(text[:120])
            if is_year_field(name):
                years.add(_year_text(value))
            elif is_company_field(name) and isinstance(value, str):
                companies.add(value)
    return {"count": count, "stats": stats, "years": years, "companies": companies}


def _year_text(value: Cell) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


async def describe_dataset(
    dataset: str,
    file: str | None = None,
    release: str | None = None,
    sheet: str | None = None,
    *,
    lang: str = "en",
) -> DatasetDetail:
    page, row = await _resolve(dataset, lang)
    summary = _summary(page, row, await _fr_rows(lang), lang)
    files = _files(page)
    selected: OebFile | None = None
    detail: dict[str, Any] = {}
    cached = False
    sheet_name: str | None = None
    sheet_names: list[str] = []
    if summary.readable:
        selected = _select_file(files, file, release, lang)
        body, cached = await _download(selected, lang)
        sheet_name, sheet_names = await _sheet_for(body, selected.format, sheet, lang)
        detail = await run_parse(_describe_scan, body, selected.format, sheet_name)
    stats: dict[str, list[Any]] = detail.get("stats", {})
    companies = sorted(detail.get("companies", set()))
    return DatasetDetail(
        dataset=summary,
        files=files,
        selected_file=selected,
        sheet=sheet_name,
        sheets=sheet_names,
        record_count=detail.get("count"),
        fields=[
            FieldInfo(name=name, filled=s[0], numeric=bool(s[0]) and s[1], examples=s[2])
            for name, s in stats.items()
        ],
        years=sorted(detail.get("years", set())),
        distributor_count=len(companies) if selected else None,
        distributors=companies[: constants.MAX_LISTED_DISTRIBUTORS],
        provenance=_provenance(
            selected.url if selected else summary.page_url,
            "DatasetDetail",
            lang,
            cached=cached,
            freshness=summary.update_frequency,
            as_of=summary.last_updated,
            limits=pick(
                lang,
                f"Distributor names capped at {constants.MAX_LISTED_DISTRIBUTORS}; "
                f"{constants.MAX_EXAMPLES} example values per field.",
                f"Noms de distributeurs limités à {constants.MAX_LISTED_DISTRIBUTORS}; "
                f"{constants.MAX_EXAMPLES} exemples de valeurs par champ.",
            ),
        ),
    )


def _company_match(record: dict[str, Cell], tokens: list[str]) -> str | None:
    for name, value in record.items():
        if isinstance(value, str) and is_company_field(name):
            text = " ".join(_tokens(value))
            if all(token in text for token in tokens):
                return value
    return None


def _year_match(record: dict[str, Cell], year: int) -> bool | None:
    """True/False when the record has a year field, None when it has none."""
    found = False
    for name, value in record.items():
        if is_year_field(name):
            found = True
            if value is not None and _year_text(value).startswith(str(year)):
                return True
        elif "effectivedate" in norm(name) and isinstance(value, str):
            found = True
            if value.startswith(str(year)):
                return True
    return False if found else None


def _query_scan(
    body: bytes,
    fmt: str,
    sheet: str | None,
    distributor: str | None,
    year: int | None,
    where: dict[str, str],
    fields: list[str],
    max_rows: int,
) -> dict[str, Any]:
    tokens = _tokens(distributor) if distributor else []
    where_norm = {norm(k): norm(v) for k, v in where.items()}
    field_norms = [norm(f) for f in fields if norm(f)]
    seen_columns: list[str] = []
    seen_set: set[str] = set()
    matched_where: set[str] = set()
    matched_fields: set[str] = set()
    has_year_field = False
    has_company_field = False
    total = 0
    out: list[dict[str, Cell]] = []
    names: Counter[str] = Counter()
    for record in _rows(body, fmt, sheet):
        for name in record:
            if name not in seen_set:
                seen_set.add(name)
                seen_columns.append(name)
        if tokens:
            company = _company_match(record, tokens)
            if any(is_company_field(n) for n in record):
                has_company_field = True
            if company is None:
                continue
        else:
            company = None
        if year is not None:
            ok = _year_match(record, year)
            if ok is not None:
                has_year_field = True
            if not ok:
                continue
        keep = True
        for key, value in where_norm.items():
            hit = False
            for name, cell in record.items():
                if key == norm(name) or key in norm(name):
                    matched_where.add(key)
                    if cell is not None and norm(str(cell)) == value:
                        hit = True
            if not hit:
                keep = False
                break
        if not keep:
            continue
        total += 1
        if company:
            names[company] += 1
        if len(out) < max_rows:
            out.append(record)
    for column in seen_columns:
        for f in field_norms:
            if f == norm(column) or f in norm(column):
                matched_fields.add(f)
    return {
        "rows": out,
        "total": total,
        "columns": seen_columns,
        "names": [n for n, _ in names.most_common(20)],
        "unknown_where": [k for k in where if norm(k) not in matched_where],
        "unknown_fields": [f for f in fields if norm(f) and norm(f) not in matched_fields],
        "has_year_field": has_year_field or year is None,
        "has_company_field": has_company_field or not tokens,
    }


def _columns(all_columns: list[str], fields: list[str]) -> list[str]:
    if not fields:
        return all_columns
    keys = [norm(f) for f in fields if norm(f)]
    ids = [c for c in all_columns if is_company_field(c) or is_year_field(c)]
    picked = [c for c in all_columns if any(k == norm(c) or k in norm(c) for k in keys)]
    return ids + [c for c in picked if c not in ids]


async def query_dataset(
    dataset: str,
    file: str | None = None,
    release: str | None = None,
    distributor: str | None = None,
    year: int | None = None,
    fields: list[str] | None = None,
    where: dict[str, str] | None = None,
    sheet: str | None = None,
    max_rows: int = constants.DEFAULT_MAX_ROWS,
    *,
    lang: str = "en",
) -> QueryResult:
    if not 1 <= max_rows <= constants.MAX_ROWS:
        raise_localized(
            InvalidInput,
            f"max_rows must be between 1 and {constants.MAX_ROWS}.",
            f"max_rows doit être entre 1 et {constants.MAX_ROWS}.",
            lang,
        )
    page, row = await _resolve(dataset, lang)
    summary = _summary(page, row, await _fr_rows(lang), lang)
    files = _files(page)
    selected = _select_file(files, file, release, lang)
    body, cached = await _download(selected, lang)
    sheet_name, _ = await _sheet_for(body, selected.format, sheet, lang)
    wanted_fields = [f for f in (fields or []) if f.strip()]
    scan = await run_parse(
        _query_scan,
        body,
        selected.format,
        sheet_name,
        distributor.strip() if distributor and distributor.strip() else None,
        year,
        where or {},
        wanted_fields,
        max_rows,
    )
    columns: list[str] = scan["columns"]
    # Each problem in English and French, so the error reads whole in either language.
    problems: list[tuple[str, str]] = []
    if scan["unknown_where"] or scan["unknown_fields"]:
        unknown = scan["unknown_where"] + scan["unknown_fields"]
        problems.append(
            (f"No column matches {unknown}.", f"Aucune colonne ne correspond à {unknown}.")
        )
    if not scan["has_company_field"]:
        problems.append(
            ("This file has no company column.", "Ce fichier n'a pas de colonne d'entreprise.")
        )
    if not scan["has_year_field"]:
        problems.append(("This file has no year column.", "Ce fichier n'a pas de colonne d'année."))
    if problems:
        raise_localized(
            InvalidInput,
            " ".join(en for en, _ in problems) + f" Columns: {columns}.",
            _lower_first(" ".join(fr for _, fr in problems)) + f" Colonnes : {columns}.",
            lang,
        )
    shown = _columns(columns, wanted_fields)
    rows = [{c: record.get(c) for c in shown} for record in scan["rows"]]
    return QueryResult(
        dataset=summary.slug,
        title=summary.title,
        file=selected,
        sheet=sheet_name,
        columns=shown,
        rows=rows,
        total_matched=scan["total"],
        returned=len(rows),
        truncated=scan["total"] > len(rows),
        matched_distributors=scan["names"],
        provenance=_provenance(
            selected.url,
            "QueryResult",
            lang,
            cached=cached,
            freshness=summary.update_frequency,
            as_of=summary.last_updated,
            limits=pick(
                lang,
                f"First {max_rows} matching rows. Blank values the distributors left were "
                "published as zeros in many RRR files (as the dataset pages state).",
                f"Les {max_rows} premières lignes correspondantes. Dans de nombreux fichiers "
                "RRR, les valeurs laissées vides par les distributeurs sont publiées comme des "
                "zéros (selon les pages des jeux de données).",
            ),
        ),
    )


def _keys_scan(body: bytes) -> dict[str, tuple[str | None, str | None]]:
    sheet = records.xlsx_sheets(body)[0]
    keys: dict[str, tuple[str | None, str | None]] = {}
    for record in records.xlsx_records(body, sheet):
        values = list(record.values())
        tag = str(values[0] or "").strip().strip("<>/ ")
        if not tag:
            continue
        description = str(values[1]) if len(values) > 1 and values[1] is not None else None
        unit = str(values[2]) if len(values) > 2 and values[2] is not None else None
        keys[records.label(tag)] = (description, unit)
    return keys


def _rates_scan(
    body: bytes, fmt: str, sheet: str | None, distributor: str | None, max_rows: int
) -> dict[str, Any]:
    tokens = _tokens(distributor) if distributor else []
    columns: list[str] = []
    out: list[dict[str, Cell]] = []
    total = 0
    for record in _rows(body, fmt, sheet):
        for name in record:
            if name not in columns:
                columns.append(name)
        if tokens:
            dist = record.get("Dist")
            if not isinstance(dist, str) or not all(t in " ".join(_tokens(dist)) for t in tokens):
                continue
        total += 1
        if len(out) < max_rows:
            out.append(record)
    return {"columns": columns, "rows": out, "total": total}


async def get_rates(
    table: str,
    distributor: str | None = None,
    max_rows: int = 200,
    *,
    lang: str = "en",
) -> RatesTable:
    spec = constants.RATE_TABLES.get(table)
    if spec is None:
        raise_localized(
            InvalidInput,
            f"table must be one of {sorted(constants.RATE_TABLES)}.",
            f"table doit être l'une de {sorted(constants.RATE_TABLES)}.",
            lang,
        )
    if not 1 <= max_rows <= constants.MAX_ROWS:
        raise_localized(
            InvalidInput,
            f"max_rows must be between 1 and {constants.MAX_ROWS}.",
            f"max_rows doit être entre 1 et {constants.MAX_ROWS}.",
            lang,
        )
    is_xml = spec["url"].endswith(".xml")
    if distributor and not is_xml:
        raise_localized(
            InvalidInput,
            "The Regulated Price Plan tables are province-wide; drop distributor.",
            "les grilles tarifaires réglementées valent pour toute la province; retirez "
            "distributor.",
            lang,
        )
    data_file = OebFile(
        index=1,
        name=pages.file_name(spec["url"]),
        release="current",
        format="xml" if is_xml else "xlsx",
        readable=True,
        url=spec["url"],
    )
    body, cached = await _download(data_file, lang)
    keys: dict[str, tuple[str | None, str | None]] = {}
    if "keys" in spec:
        keys_file = data_file.model_copy(
            update={"name": pages.file_name(spec["keys"]), "format": "xlsx", "url": spec["keys"]}
        )
        keys_body, _ = await _download(keys_file, lang)
        keys = await run_parse(_keys_scan, keys_body)
    scan = await run_parse(
        _rates_scan,
        body,
        data_file.format,
        spec.get("sheet"),
        distributor.strip() if distributor and distributor.strip() else None,
        max_rows,
    )
    if distributor and not scan["total"]:
        raise_localized(
            NotFound,
            f"No distributor in {table} matches {distributor!r}.",
            f"aucun distributeur de {table} ne correspond à {distributor!r}.",
            lang,
        )
    fields = [
        RateField(
            name=c, description=keys.get(c, (None, None))[0], unit=keys.get(c, (None, None))[1]
        )
        for c in scan["columns"]
    ]
    rows = [{c: r.get(c) for c in scan["columns"]} for r in scan["rows"]]
    return RatesTable(
        table=table,
        title=spec["title_fr"] if lang == "fr" else spec["title"],
        fields=fields,
        rows=rows,
        total_matched=scan["total"],
        returned=len(rows),
        truncated=scan["total"] > len(rows),
        provenance=_provenance(
            spec["url"],
            "RatesTable",
            lang,
            cached=cached,
            freshness=pick(
                lang,
                "Electricity rates monthly, natural gas quarterly, RPP prices as needed.",
                "Électricité chaque mois, gaz naturel chaque trimestre, prix de la grille au "
                "besoin.",
            ),
            limits=pick(lang, f"First {max_rows} rows.", f"Les {max_rows} premières lignes."),
        ),
    )
