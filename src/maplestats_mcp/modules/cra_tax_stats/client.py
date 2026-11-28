"""Read CRA's T1 Final Basic Tables and FSA tables, one edition at a time, the same way.

Every edition is a CKAN package on open.canada.ca (package ids in constants.py).
The package is read with the shared CKAN client (shared/ckan.action) and its CSV
resources are matched by file name, because neither the resource names nor the
resource language tags can be trusted: in the 2024 T1 edition the French Nova
Scotia resource links to the English file, and the 2021 edition's "CSV" Table 2
for Alberta and Quebec are PDFs (package_show, 2026-11-19). Files are streamed
through shared/file_download (https, www.canada.ca only, under the shared CSV
cap) and kept in its byte cache; canada.ca sometimes drops a connection
mid-answer (RemoteProtocolError), which the shared retries absorb.

What differs between editions, all read live on 2026-11-19 and handled here:

- Header wording. 2018-2021: bilingual "Grand total/Total global #" and
  "... $ (000)"; 2022-2023: "Total (Number / Nombre)", "(Thousands of Dollars /
  Milliers de dollars)"; 2024: English-only "(Number)", "(Thousands of
  Dollars)" or "(Thousands of $)", with the French in a separate file.
- Units. Table 1 is in millions of dollars ("(000,000)") to 2021 and in
  thousands from 2022; Tables 2-5 are in thousands throughout. FSA amounts are
  whole dollars to 2020 and thousands in 2021 (constants.FSA_THOUSANDS_FROM).
  Every amount comes back in thousands of dollars with the published unit.
- Count rows. "Number of taxable returns" has a blank amount cell to 2021 and
  a 0 from 2022; that 0 is not an amount and is dropped.
- Table 3 changed in 2022 from line items by source of income to returns and
  amounts by source and province (the old layout has an Item column).
- The 2021 FSA files start with a line holding a single quote and a blank line
  before the header; the 2017-2020 files end with rows of empty cells.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, NoReturn

from maplestats_mcp.modules.cra_tax_stats import constants
from maplestats_mcp.modules.cra_tax_stats.schemas import (
    FsaRow,
    FsaSeries,
    FsaTable,
    Measure,
    Series,
    T1Row,
    T1Series,
    T1Table,
    TaxCatalogue,
    TaxEdition,
    TaxTableFile,
)
from maplestats_mcp.shared import csv_files, file_download
from maplestats_mcp.shared.arg_checks import check_range
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_CKAN = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.CKAN_BASE_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    timeout=60.0,
)
_FILES = get_limiter(
    f"{constants.RATE_LIMIT_SOURCE}-files",
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# T1 file names: table1.csv, table2_ac.csv, tbl2_nl.csv, tbl1_ac_en.csv. No area
# means all of Canada (table1.csv, table5.csv); "ac" is CRA's own code for it.
_T1_FILE = re.compile(
    r"^(?:tbl|table)(?P<table>[1-5])(?:_(?P<area>[a-z]{2}))?(?:_(?P<lang>en|fr))?\.csv$"
)
# FSA national files only (every FSA in Canada, with its province code):
# tbl1a-en.csv, tbl2-en.csv. The per-province files repeat the same rows.
_FSA_FILE = re.compile(r"^tbl(?P<table>1[a-e]|2)-en\.csv$")

Unit = Literal["number", "thousands of dollars", "millions of dollars"]


def _fail(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    raise_localized(exc_cls, en, fr, lang)


def _editions(series: Series) -> dict[int, str]:
    return constants.T1_EDITIONS if series == "t1_final" else constants.FSA_EDITIONS


def _check_year(series: Series, tax_year: int, lang: str) -> str:
    editions = _editions(series)
    if tax_year not in editions:
        years = ", ".join(str(y) for y in editions)
        _fail(
            InvalidInput,
            f"cra_tax_stats: tax_year {tax_year} is not covered for {series}; covered: {years}.",
            f"cra_tax_stats : l'année d'imposition {tax_year} n'est pas couverte pour {series}; "
            f"années couvertes : {years}.",
            lang,
        )
    return editions[tax_year]


def _page(dataset_id: str, lang: str) -> str:
    return constants.DATASET_PAGE["fr" if lang == "fr" else "en"].format(id=dataset_id)


def _title(package: dict[str, Any], lang: str) -> str:
    titles = package.get("title_translated") or {}
    if isinstance(titles, dict):
        found = titles.get("fr" if lang == "fr" else "en") or titles.get("en")
        if found:
            return " ".join(str(found).split())
    return " ".join(str(package.get("title") or "").split())


async def _package(series: Series, tax_year: int, lang: str) -> tuple[dict[str, Any], bool]:
    dataset_id = _check_year(series, tax_year, lang)

    async def fetch() -> Any:
        return await action(_CKAN, "package_show", params={"id": dataset_id}, lang=lang)

    package, cached = await cached_fetch(
        f"cra-tax-stats:package:{dataset_id}", constants.PACKAGE_TTL_SECONDS, fetch
    )
    if not isinstance(package, dict):
        _fail(
            UpstreamError,
            f"cra_tax_stats: package_show for {dataset_id} returned no object.",
            f"cra_tax_stats : package_show n'a renvoyé aucun objet pour {dataset_id}.",
            lang,
        )
    return package, cached


def _resource_name(resource: dict[str, Any], lang: str) -> str | None:
    names = resource.get("name_translated") or {}
    name = names.get("fr" if lang == "fr" else "en") if isinstance(names, dict) else None
    text = name or resource.get("name")
    return " ".join(str(text).split()) if text else None


def table_files(series: Series, package: dict[str, Any], lang: str = "en") -> list[TaxTableFile]:
    """The CSV files of one edition this module reads, matched by file name."""
    found: dict[tuple[str, str], TaxTableFile] = {}
    for resource in list_or_empty(package, "resources"):
        url = str(resource.get("url") or "").strip()
        if not url.lower().startswith(f"https://{constants.FILE_HOST}/"):
            continue
        name = url.rsplit("/", 1)[-1].lower()
        if series == "t1_final":
            match = _T1_FILE.match(name)
            if not match or match["lang"] == "fr":
                continue
            area = match["area"] or "ac"
            key = (match["table"], "ca" if area == "ac" else area)
        else:
            match = _FSA_FILE.match(name)
            if not match:
                continue
            key = (match["table"], "ca")
        if key[1] not in constants.AREAS or key in found:
            continue
        found[key] = TaxTableFile(
            table=key[0],
            area=key[1],
            title=_resource_name(resource, lang),
            url=url,
            resource_id=str(resource.get("id") or ""),
        )
    order = list(constants.AREAS)
    return sorted(found.values(), key=lambda f: (f.table, order.index(f.area)))


def _provenance(
    url: str,
    cached: bool,
    schema: str,
    lang: str,
    *,
    coverage: str,
    limits: str | None = None,
) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"cra_tax_stats.{schema}",
        freshness=pick(
            lang,
            "One edition per tax year; CRA adds a tax year about two years after it ends and "
            "rarely revises a published edition. Cached up to 24 hours.",
            "Une édition par année d'imposition; l'ARC ajoute une année environ deux ans après "
            "sa fin et révise rarement une édition publiée. Mis en cache jusqu'à 24 heures.",
        ),
        coverage=coverage,
        limits=limits,
        lang=lang,
    )


def _citation(package: dict[str, Any], dataset_id: str, lang: str) -> str:
    template = constants.CITATION_FR if lang == "fr" else constants.CITATION
    return template.format(title=_title(package, lang), page=_page(dataset_id, lang))


def _table_titles(series: Series, lang: str) -> dict[str, str]:
    i = 1 if lang == "fr" else 0
    if series == "t1_final":
        return {str(k): v[i] for k, v in constants.T1_TABLES.items()}
    return {k: v[i] for k, v in constants.FSA_TABLES.items()}


async def list_tables(
    series: Series = "t1_final", tax_year: int | None = None, lang: str = "en"
) -> TaxCatalogue:
    """The covered editions, and with `tax_year` the CSV files resolved in that edition."""
    editions = [
        TaxEdition(tax_year=year, dataset_id=pid, landing_page=_page(pid, lang))
        for year, pid in sorted(_editions(series).items())
    ]
    titles = _table_titles(series, lang)
    if tax_year is None:
        return TaxCatalogue(
            series=series,
            tax_year=None,
            editions=editions,
            tables=[],
            table_titles=titles,
            provenance=_provenance(
                constants.CKAN_BASE_URL + "package_show",
                True,
                "TaxCatalogue",
                lang,
                coverage=pick(
                    lang,
                    f"Editions checked live 2026-11-19: {editions[0].tax_year}-"
                    f"{editions[-1].tax_year}. Pass tax_year to list one edition's files.",
                    f"Éditions vérifiées en direct le 2026-11-19 : {editions[0].tax_year}-"
                    f"{editions[-1].tax_year}. Passez tax_year pour la liste des fichiers d'une "
                    "édition.",
                ),
            ),
        )
    package, cached = await _package(series, tax_year, lang)
    dataset_id = _editions(series)[tax_year]
    return TaxCatalogue(
        series=series,
        tax_year=tax_year,
        editions=editions,
        tables=table_files(series, package, lang),
        table_titles=titles,
        provenance=_provenance(
            _page(dataset_id, lang),
            cached,
            "TaxCatalogue",
            lang,
            coverage=_citation(package, dataset_id, lang),
        ),
    )


async def _find_file(
    series: Series, tax_year: int, table: str, area: str, lang: str
) -> tuple[TaxTableFile, dict[str, Any], bool]:
    package, cached = await _package(series, tax_year, lang)
    files = table_files(series, package, lang)
    for f in files:
        if f.table == table and f.area == area:
            return f, package, cached
    shown = ", ".join(sorted({f"{f.table}/{f.area}" for f in files})) or "none"
    _fail(
        NotFound,
        f"cra_tax_stats: the {tax_year} edition has no readable CSV for table {table}, area "
        f"{area!r} (tables/areas there: {shown}). The package may list it as a PDF or link "
        f"another file; see {_page(_editions(series)[tax_year], 'en')}.",
        f"cra_tax_stats : l'édition {tax_year} n'a aucun CSV lisible pour le tableau {table}, "
        f"région {area!r} (tableaux/régions offerts : {shown}). La fiche le donne peut-être en "
        f"PDF ou renvoie à un autre fichier; voir {_page(_editions(series)[tax_year], 'fr')}.",
        lang,
    )


def _is_web_page(text: str) -> bool:
    return text[:1024].lstrip().lower().startswith(("<!doctype", "<html"))


def _web_page_error(url: str, lang: str) -> NoReturn:
    _fail(
        UpstreamError,
        f"cra_tax_stats: {url} returned a web page, not a CSV file.",
        f"cra_tax_stats : {url} a renvoyé une page Web, pas un fichier CSV.",
        lang,
    )


async def _download(url: str, lang: str = "en") -> tuple[bytes, bool]:
    async def fetch() -> file_download.Downloaded:
        downloaded = await file_download.download(
            url,
            allow_host=lambda host: host == constants.FILE_HOST,
            limiter_for=lambda _host: _FILES,
            max_bytes=constants.MAX_FILE_BYTES,
            context="cra_tax_stats",
            timeout=120.0,
        )
        # Checked inside the function the cache calls, so a web page is never stored:
        # canada.ca answers an outage or a moved file with an HTML page and HTTP 200,
        # which used to sit in the byte cache for 24 hours (under the key every module
        # reading this URL shares) and read as NotFound, so get_t1_series and
        # get_fsa_series listed the year as missing instead of failing.
        if _is_web_page(csv_files.decode(downloaded.body[:2048])):
            _web_page_error(url, lang)
        return downloaded

    downloaded, cached = await file_download.cached_download(
        file_download.cache_key(url), constants.FILE_TTL_SECONDS, fetch
    )
    return downloaded.body, cached


# ------------------------------------------------------------------ parsing


def _rows(body: bytes, url: str, lang: str = "en") -> tuple[list[str], list[list[str]]]:
    """The header and data rows, skipping the lines before the header.

    The header is the first line with three or more non-empty cells: the 2021
    FSA files open with a line holding one quote and a blank line.
    """
    text = csv_files.decode(body)
    if _is_web_page(text):
        _web_page_error(url, lang)
    try:
        lines = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise UpstreamError(f"cra_tax_stats: {url} is not well-formed CSV ({exc}).") from exc
    for i, line in enumerate(lines):
        if sum(1 for cell in line if cell.strip()) >= 3:
            return [" ".join(c.split()) for c in line], lines[i + 1 :]
    raise UpstreamError(f"cra_tax_stats: {url} has no header row.")


def _number(cell: str) -> float | None:
    text = cell.strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# Unit markers at the end of a value column's header, in every wording seen.
_END_MARKERS: tuple[tuple[re.Pattern[str], Measure, Unit], ...] = (
    (re.compile(r"\s*\(number(?:\s*/\s*nombre)?\)$", re.IGNORECASE), "number", "number"),
    (
        re.compile(
            r"\s*\(thousands of (?:dollars|\$)(?:\s*/\s*milliers de dollars)?\)$", re.IGNORECASE
        ),
        "amount",
        "thousands of dollars",
    ),
    (re.compile(r"\s*\$\s*\(000\)$"), "amount", "thousands of dollars"),
    (re.compile(r"\s*#$"), "number", "number"),
)
# Table 1's units sit inside the English half: "Total income assessed (000,000)/...".
_INNER_MARKERS: tuple[tuple[re.Pattern[str], Measure, Unit], ...] = (
    (re.compile(r"\s*\(000,000\)", re.IGNORECASE), "amount", "millions of dollars"),
    (
        re.compile(r"\s*\(thousands of (?:dollars|\$)\)", re.IGNORECASE),
        "amount",
        "thousands of dollars",
    ),
)


def _english(label: str) -> str:
    """The English half of a bilingual label ("Employment/Emploi", "Ontario / Ontario").

    The one English label with a slash of its own, "Proprietorships/Partnerships"
    (Table 3, 2018-2021), keeps it.
    """
    text = " ".join(label.split())
    if " / " in text:
        text = text.split(" / ", 1)[0]
    elif "/" in text:
        parts = text.split("/")
        text = "/".join(parts[:2]) if parts[0].strip().lower() == "proprietorships" else parts[0]
    text = text.strip().rstrip("#").strip()
    return re.sub(r"^grand total\b", "Total", text, flags=re.IGNORECASE)


def _value_column(header: str) -> tuple[str, Measure, Unit] | None:
    """(label, measure, published unit) of a value column, or None when it is not one."""
    text = " ".join(header.split())
    for pattern, measure, unit in _END_MARKERS:
        if pattern.search(text):
            return _english(pattern.sub("", text)), measure, unit
    english = _english(text)
    for pattern, measure, unit in _INNER_MARKERS:
        if pattern.search(english):
            return " ".join(pattern.sub("", english).split()), measure, unit
    if english.lower().startswith("number of"):
        return english, "number", "number"
    return None


_COUNT_ITEM = re.compile(r"^(?:total )?number of\b", re.IGNORECASE)
_NON_TAXABLE = re.compile(r"^non[\s-]*taxable", re.IGNORECASE)


@dataclass
class _Layout:
    item: int | None = None
    item_fr: int | None = None
    item_number: int | None = None
    row_label: int | None = None
    return_type: int | None = None


def parse_t1(body: bytes, tax_year: int, url: str = "", lang: str = "en") -> list[T1Row]:
    """Every value of one T1 table file as long rows, amounts in thousands of dollars."""
    header, lines = _rows(body, url, lang)
    layout = _Layout()
    values: list[tuple[int, str, Measure, Unit]] = []
    for i, name in enumerate(header):
        key = name.lower()
        if key in ("#", "number"):
            layout.item_number = i
        elif key == "item":
            layout.item = i
        elif key == "poste":
            layout.item_fr = i
        elif key in ("province or territory", "prov_e"):
            layout.row_label = i
        elif key.startswith("return"):
            layout.return_type = i
        elif not key or key.startswith("tax year") or key in ("province ou territoire", "prov_f"):
            continue
        else:
            parsed = _value_column(name)
            if parsed is not None:
                values.append((i, *parsed))
    by_item = layout.item is not None
    if not by_item and layout.row_label is None:
        raise UpstreamError(
            f"cra_tax_stats: {url} has neither an Item nor a province column; header {header}."
        )
    out: list[T1Row] = []
    for line in lines:

        def cell(i: int | None, line: list[str] = line) -> str:
            return " ".join(line[i].split()) if i is not None and i < len(line) else ""

        label = cell(layout.item if by_item else layout.row_label)
        if not label:
            continue
        number = cell(layout.item_number)
        return_type = None
        if layout.return_type is not None:
            # "Non taxable returns" to 2021, "Non-taxable returns" from 2022.
            return_type = _NON_TAXABLE.sub("Non-taxable", _english(cell(layout.return_type)))
        for i, column, measure, unit in values:
            value = _number(line[i]) if i < len(line) else None
            if value is None:
                continue
            item = label if by_item else column
            if measure == "amount" and _COUNT_ITEM.match(item):
                continue  # the 0 or blank beside a count row is not an amount
            out.append(
                T1Row(
                    tax_year=tax_year,
                    item=item,
                    item_fr=(cell(layout.item_fr) or None) if by_item else None,
                    item_number=int(number) if number.isdigit() else None,
                    group=column if by_item else _english(label),
                    return_type=return_type or None,
                    measure=measure,
                    value=value * 1000 if unit == "millions of dollars" else value,
                    unit="number" if measure == "number" else "thousands of dollars",
                    published_unit=unit,
                )
            )
    return out


def parse_fsa(body: bytes, tax_year: int, url: str = "", lang: str = "en") -> list[FsaRow]:
    """Every value of one national FSA table as long rows, amounts in thousands of dollars."""
    header, lines = _rows(body, url, lang)
    lowered = [h.lower() for h in header]
    try:
        prov_i = lowered.index("prov/terr")
        fsa_i = lowered.index("fsa")
    except ValueError as exc:
        raise UpstreamError(f"cra_tax_stats: {url} has no Prov/Terr and FSA columns.") from exc
    thousands = tax_year >= constants.FSA_THOUSANDS_FROM
    columns: list[tuple[int, str, Measure]] = []
    for i, name in enumerate(header):
        if i in (prov_i, fsa_i) or not name:
            continue
        key = name.lower()
        # Table 1e pairs "X Income #" with "X Income $"; Tables 1a-1d and 2 have
        # "Total" (returns) and "Total income"/"Net income"/"Taxable income".
        if key.endswith(" $") or (key.endswith("income") and not key.endswith(" #")):
            columns.append((i, name.removesuffix(" $").strip(), "amount"))
        else:
            columns.append((i, name.removesuffix(" #").strip(), "number"))
    out: list[FsaRow] = []
    for line in lines:
        if len(line) <= fsa_i:
            continue
        prov = line[prov_i].strip()
        fsa = line[fsa_i].strip()
        if not fsa:
            continue
        province = "ca" if prov.lower() == "canada" else constants.PROVINCE_CODES.get(prov)
        if province is None:
            continue
        for i, item, measure in columns:
            value = _number(line[i]) if i < len(line) else None
            if value is None:
                continue
            published: Literal["number", "dollars", "thousands of dollars"] = (
                "number"
                if measure == "number"
                else "thousands of dollars"
                if thousands
                else "dollars"
            )
            out.append(
                FsaRow(
                    tax_year=tax_year,
                    fsa=fsa.upper() if fsa.lower() != "total" else "Total",
                    province=province,
                    item=item,
                    measure=measure,
                    value=value / 1000 if published == "dollars" else value,
                    unit="number" if measure == "number" else "thousands of dollars",
                    published_unit=published,
                )
            )
    return out


async def _t1_rows(
    tax_year: int, table: int, area: str, lang: str
) -> tuple[list[T1Row], TaxTableFile, dict[str, Any], bool]:
    found, package, api_cached = await _find_file("t1_final", tax_year, str(table), area, lang)

    async def fetch() -> list[T1Row]:
        body, _ = await _download(found.url, lang)
        return await run_parse(parse_t1, body, tax_year, found.url, lang)

    rows, cached = await cached_fetch(
        f"cra-tax-stats:t1:{found.url}", constants.FILE_TTL_SECONDS, fetch
    )
    return rows, found, package, cached and api_cached


async def _fsa_rows(
    tax_year: int, table: str, lang: str
) -> tuple[list[FsaRow], TaxTableFile, dict[str, Any], bool]:
    found, package, api_cached = await _find_file("fsa", tax_year, table, "ca", lang)

    async def fetch() -> list[FsaRow]:
        body, _ = await _download(found.url, lang)
        return await run_parse(parse_fsa, body, tax_year, found.url, lang)

    rows, cached = await cached_fetch(
        f"cra-tax-stats:fsa:{found.url}", constants.FILE_TTL_SECONDS, fetch
    )
    return rows, found, package, cached and api_cached


# ------------------------------------------------------------------ queries


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _check_paging(limit: int, offset: int, lang: str) -> None:
    if not 1 <= limit <= constants.ROWS_MAX:
        _fail(
            InvalidInput,
            f"cra_tax_stats: limit must be 1 to {constants.ROWS_MAX}.",
            f"cra_tax_stats : limit doit être entre 1 et {constants.ROWS_MAX}.",
            lang,
        )
    if offset < 0:
        _fail(
            InvalidInput,
            "cra_tax_stats: offset must be 0 or more.",
            "cra_tax_stats : offset doit être 0 ou plus.",
            lang,
        )


def _check_table(table: int, lang: str) -> None:
    if table not in constants.T1_TABLES:
        _fail(
            InvalidInput,
            f"cra_tax_stats: table must be 1 to 5, not {table}.",
            f"cra_tax_stats : table doit être entre 1 et 5, et non {table}.",
            lang,
        )


def _check_area(area: str, lang: str) -> str:
    code = area.strip().lower()
    code = "ca" if code in ("ac", "canada") else code
    if code not in constants.AREAS:
        shown = ", ".join(constants.AREAS)
        _fail(
            InvalidInput,
            f"cra_tax_stats: area {area!r} is not known; use one of {shown}.",
            f"cra_tax_stats : la région {area!r} est inconnue; utilisez {shown}.",
            lang,
        )
    return code


def _units_note(rows: Iterable[T1Row | FsaRow], lang: str) -> str | None:
    published = sorted({r.published_unit for r in rows if r.measure == "amount"})
    converted = [u for u in published if u != "thousands of dollars"]
    if not converted:
        return None
    return pick(
        lang,
        f"amounts published in {', '.join(converted)} were converted to thousands of dollars "
        "(published_unit gives each row's own unit; no precision is added)",
        f"les montants publiés en {', '.join(converted)} ont été convertis en milliers de "
        "dollars (published_unit donne l'unité de chaque ligne; aucune précision n'est ajoutée)",
    )


def _join(*notes: str | None) -> str | None:
    kept = [n for n in notes if n]
    return "; ".join(kept) if kept else None


async def get_t1_table(
    tax_year: int,
    table: int = 1,
    area: str = "ca",
    item: str | None = None,
    group: str | None = None,
    measure: Measure | None = None,
    limit: int = constants.ROWS_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> T1Table:
    """One T1 Final Basic Table for one tax year and area, as long rows."""
    _check_table(table, lang)
    _check_paging(limit, offset, lang)
    code = _check_area(area, lang)
    rows, found, package, cached = await _t1_rows(tax_year, table, code, lang)
    wanted_item = _norm(item) if item else None
    wanted_group = _norm(group) if group else None
    matched = [
        r
        for r in rows
        if (wanted_item is None or wanted_item in _norm(r.item) or str(r.item_number) == item)
        and (wanted_group is None or wanted_group in _norm(r.group))
        and (measure is None or r.measure == measure)
    ]
    page = matched[offset : offset + limit]
    more = offset + len(page) < len(matched)
    dataset_id = constants.T1_EDITIONS[tax_year]
    i = 1 if lang == "fr" else 0
    return T1Table(
        tax_year=tax_year,
        table=table,
        area=code,
        title=constants.T1_TABLES[table][i],
        source_url=found.url,
        rows=page,
        total_rows=len(matched),
        offset=offset,
        truncated=more,
        provenance=_provenance(
            found.url,
            cached,
            "T1Table",
            lang,
            coverage=pick(
                lang,
                f"Table {table}, {constants.AREAS[code][0]}, tax year {tax_year}. ",
                f"Tableau {table}, {constants.AREAS[code][1]}, année d'imposition {tax_year}. ",
            )
            + _citation(package, dataset_id, lang),
            limits=_join(
                _units_note(page, lang),
                pick(
                    lang,
                    f"showing rows {offset + 1} to {offset + len(page)} of {len(matched)}",
                    f"lignes {offset + 1} à {offset + len(page)} sur {len(matched)}",
                )
                if more
                else None,
                pick(
                    lang,
                    "labels are in English as published; item_fr gives CRA's French line item "
                    "where the file has one (not in the English-only 2024 files)",
                    "les libellés sont en anglais, tels que publiés; item_fr donne le poste en "
                    "français lorsque le fichier l'indique (pas dans les fichiers 2024, en "
                    "anglais seulement)",
                )
                if lang == "fr"
                else None,
            ),
        ),
    )


def _years(
    editions: dict[int, str], from_year: int | None, to_year: int | None, lang: str
) -> list[int]:
    check_range(from_year, to_year, "from_year", "to_year")
    years = [
        y
        for y in sorted(editions)
        if (from_year is None or y >= from_year) and (to_year is None or y <= to_year)
    ]
    if not years:
        _fail(
            InvalidInput,
            f"cra_tax_stats: no edition between {from_year} and {to_year}; covered: "
            f"{min(editions)}-{max(editions)}.",
            f"cra_tax_stats : aucune édition entre {from_year} et {to_year}; années couvertes : "
            f"{min(editions)}-{max(editions)}.",
            lang,
        )
    return years


async def get_t1_series(
    table: int,
    item: str,
    group: str | None = None,
    area: str = "ca",
    return_type: str | None = "All returns",
    measure: Measure | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    lang: str = "en",
) -> T1Series:
    """One line item of a T1 table across every covered edition.

    `item` and `group` match the whole label (case and spacing ignored), because
    a substring would mix items across years ("Total income" is in "Total income
    assessed"), and never the line-item number, which shifts between editions
    (Total tax payable is item 100 in 2018 and 106 in 2024). Without `group`, the
    all-groups column ("Total") or row ("Canada") is used.
    """
    _check_table(table, lang)
    code = _check_area(area, lang)
    years = _years(constants.T1_EDITIONS, from_year, to_year, lang)
    wanted_item = _norm(item)
    wanted_groups = {_norm(group)} if group else {"total", "canada"}
    wanted_return = _norm(return_type) if return_type else None
    found_rows: list[T1Row] = []
    missing: list[int] = []
    sources: list[str] = []
    all_cached = True
    for year in years:
        try:
            rows, found, _, cached = await _t1_rows(year, table, code, lang)
        except NotFound:
            missing.append(year)
            continue
        all_cached = all_cached and cached
        hits = [
            r
            for r in rows
            if _norm(r.item) == wanted_item
            and _norm(r.group) in wanted_groups
            and (
                r.return_type is None
                or wanted_return is None
                or _norm(r.return_type) == wanted_return
            )
            and (measure is None or r.measure == measure)
        ]
        if hits:
            found_rows.extend(hits)
            sources.append(found.url)
        else:
            missing.append(year)
    if not found_rows:
        _fail(
            NotFound,
            f"cra_tax_stats: no row of table {table} ({code}) has item {item!r} and group "
            f"{group or 'Total'!r} in {years[0]}-{years[-1]}. Use cra_tax_stats_get_t1_table "
            "to see the labels of one edition.",
            f"cra_tax_stats : aucune ligne du tableau {table} ({code}) n'a le poste {item!r} et "
            f"le groupe {group or 'Total'!r} en {years[0]}-{years[-1]}. Utilisez "
            "cra_tax_stats_get_t1_table pour voir les libellés d'une édition.",
            lang,
        )
    i = 1 if lang == "fr" else 0
    return T1Series(
        table=table,
        area=code,
        item=found_rows[0].item,
        group=found_rows[0].group,
        rows=found_rows,
        years_read=[y for y in years if y not in missing],
        missing_years=missing,
        sources=sources,
        provenance=_provenance(
            sources[-1],
            all_cached,
            "T1Series",
            lang,
            coverage=pick(
                lang,
                f"Table {table} ({constants.T1_TABLES[table][0]}), {constants.AREAS[code][0]}, "
                f"one file per tax year. Source: Canada Revenue Agency, Individual Income Tax "
                "Return Statistics (T1 Final Statistics). Contains information licensed under "
                "the Open Government Licence - Canada.",
                f"Tableau {table} ({constants.T1_TABLES[table][i]}), {constants.AREAS[code][1]}, "
                "un fichier par année d'imposition. Source : Agence du revenu du Canada, "
                "Statistiques sur les déclarations de revenus des particuliers (Statistiques "
                "finales T1). Contient des renseignements autorisés sous la Licence du "
                "gouvernement ouvert - Canada.",
            ),
            limits=_join(
                _units_note(found_rows, lang),
                pick(
                    lang,
                    f"no matching row in {', '.join(map(str, missing))}",
                    f"aucune ligne correspondante en {', '.join(map(str, missing))}",
                )
                if missing
                else None,
                pick(
                    lang,
                    "Table 3 changed layout in 2022 (line items by source to 2021, sources by "
                    "province from 2022), so its labels differ across that break",
                    "le tableau 3 a changé de présentation en 2022 (postes par source jusqu'en "
                    "2021, sources par province depuis 2022), ses libellés diffèrent donc de "
                    "part et d'autre",
                )
                if table == 3
                else None,
            ),
        ),
    )


def _check_fsa_table(table: str, lang: str) -> str:
    code = table.strip().lower()
    if code not in constants.FSA_TABLES:
        shown = ", ".join(constants.FSA_TABLES)
        _fail(
            InvalidInput,
            f"cra_tax_stats: FSA table must be one of {shown}, not {table!r}.",
            f"cra_tax_stats : le tableau RTA doit être l'un de {shown}, et non {table!r}.",
            lang,
        )
    return code


def _fsa_code(value: str, lang: str) -> str:
    code = value.strip().upper()
    if code.lower() == "total":
        return "Total"
    if not re.fullmatch(r"[A-Z]\d[A-Z]", code):
        _fail(
            InvalidInput,
            f"cra_tax_stats: {value!r} is not a forward sortation area (letter, digit, letter, "
            "e.g. T5K).",
            f"cra_tax_stats : {value!r} n'est pas une région de tri d'acheminement (lettre, "
            "chiffre, lettre, p. ex. T5K).",
            lang,
        )
    return code


def _province(value: str, lang: str) -> str:
    code = value.strip().lower()
    code = constants.PROVINCE_CODES.get(code, code)
    if code not in constants.AREAS or code in ("nr",):
        shown = ", ".join(c for c in constants.AREAS if c != "nr")
        _fail(
            InvalidInput,
            f"cra_tax_stats: province {value!r} is not known; use one of {shown}.",
            f"cra_tax_stats : la province {value!r} est inconnue; utilisez {shown}.",
            lang,
        )
    return code


async def get_fsa_table(
    tax_year: int,
    table: str = "1a",
    fsa: list[str] | None = None,
    province: str | None = None,
    item: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> FsaTable:
    """One FSA table for one tax year, filtered to FSAs or a province."""
    code = _check_fsa_table(table, lang)
    _check_paging(limit, offset, lang)
    if fsa and len(fsa) > constants.FSA_LIST_MAX:
        _fail(
            InvalidInput,
            f"cra_tax_stats: at most {constants.FSA_LIST_MAX} FSAs per call.",
            f"cra_tax_stats : au plus {constants.FSA_LIST_MAX} RTA par appel.",
            lang,
        )
    wanted_fsa = {_fsa_code(f, lang) for f in fsa} if fsa else None
    wanted_prov = _province(province, lang) if province else None
    rows, found, package, cached = await _fsa_rows(tax_year, code, lang)
    wanted_item = _norm(item) if item else None
    matched = [
        r
        for r in rows
        if (wanted_fsa is None or r.fsa in wanted_fsa)
        and (wanted_prov is None or r.province == wanted_prov)
        and (wanted_item is None or wanted_item in _norm(r.item))
    ]
    page = matched[offset : offset + limit]
    more = offset + len(page) < len(matched)
    dataset_id = constants.FSA_EDITIONS[tax_year]
    i = 1 if lang == "fr" else 0
    return FsaTable(
        tax_year=tax_year,
        table=code,
        title=constants.FSA_TABLES[code][i],
        source_url=found.url,
        rows=page,
        total_rows=len(matched),
        offset=offset,
        truncated=more,
        provenance=_provenance(
            found.url,
            cached,
            "FsaTable",
            lang,
            coverage=_citation(package, dataset_id, lang),
            limits=_join(
                _units_note(page, lang),
                pick(
                    lang,
                    f"showing rows {offset + 1} to {offset + len(page)} of {len(matched)}",
                    f"lignes {offset + 1} à {offset + len(page)} sur {len(matched)}",
                )
                if more
                else None,
                pick(
                    lang,
                    "an FSA is a postal area, not a census geography; its boundaries can change "
                    "between years",
                    "une RTA est une zone postale, pas une région géographique du recensement; "
                    "ses limites peuvent changer d'une année à l'autre",
                ),
            ),
        ),
    )


async def get_fsa_series(
    fsa: str,
    table: str = "1a",
    item: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    lang: str = "en",
) -> FsaSeries:
    """One FSA's values in one FSA table across every covered edition."""
    code = _check_fsa_table(table, lang)
    wanted = _fsa_code(fsa, lang)
    if wanted == "Total":
        _fail(
            InvalidInput,
            "cra_tax_stats: give one FSA (e.g. T5K); province totals are in "
            "cra_tax_stats_get_fsa_table with fsa=['Total'] and a province.",
            "cra_tax_stats : donnez une RTA (p. ex. T5K); les totaux provinciaux sont dans "
            "cra_tax_stats_get_fsa_table avec fsa=['Total'] et une province.",
            lang,
        )
    years = _years(constants.FSA_EDITIONS, from_year, to_year, lang)
    wanted_item = _norm(item) if item else None
    out: list[FsaRow] = []
    missing: list[int] = []
    sources: list[str] = []
    all_cached = True
    for year in years:
        try:
            rows, found, _, cached = await _fsa_rows(year, code, lang)
        except NotFound:
            missing.append(year)
            continue
        all_cached = all_cached and cached
        hits = [
            r
            for r in rows
            if r.fsa == wanted and (wanted_item is None or _norm(r.item) == wanted_item)
        ]
        if hits:
            out.extend(hits)
            sources.append(found.url)
        else:
            missing.append(year)
    if not out:
        _fail(
            NotFound,
            f"cra_tax_stats: FSA {wanted} has no row in table {code}"
            + (f" for item {item!r}" if item else "")
            + f" in {years[0]}-{years[-1]}.",
            f"cra_tax_stats : la RTA {wanted} n'a aucune ligne dans le tableau {code}"
            + (f" pour le poste {item!r}" if item else "")
            + f" en {years[0]}-{years[-1]}.",
            lang,
        )
    return FsaSeries(
        fsa=wanted,
        table=code,
        item=item,
        rows=out,
        years_read=[y for y in years if y not in missing],
        missing_years=missing,
        sources=sources,
        provenance=_provenance(
            sources[-1],
            all_cached,
            "FsaSeries",
            lang,
            coverage=pick(
                lang,
                "Source: Canada Revenue Agency, Individual Tax Statistics by Forward Sortation "
                "Area, one edition per tax year. Contains information licensed under the Open "
                "Government Licence - Canada.",
                "Source : Agence du revenu du Canada, Statistiques sur l'impôt des particuliers "
                "par région de tri d'acheminement, une édition par année d'imposition. Contient "
                "des renseignements autorisés sous la Licence du gouvernement ouvert - Canada.",
            ),
            limits=_join(
                _units_note(out, lang),
                pick(
                    lang,
                    f"no row for this FSA in {', '.join(map(str, missing))}",
                    f"aucune ligne pour cette RTA en {', '.join(map(str, missing))}",
                )
                if missing
                else None,
                pick(
                    lang,
                    "FSA boundaries can change between years, so a change in an FSA's figures "
                    "can reflect a boundary change",
                    "les limites des RTA peuvent changer d'une année à l'autre; une variation "
                    "peut donc venir d'un changement de limites",
                ),
            ),
        ),
    )
