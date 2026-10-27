"""Client for CBSA's Customs Tariff (Departmental Consolidation) in Access format.

Checked live 2026-10-26:

1. Each year has a page, /trade-commerce/tariff-tarif/<year>/menu-eng.html
   (-fra for French), from 2018 (2017 answers 404). The tariff index page
   links only the current year. Each edition is a `section.panel`
   headed "T2026-2 ... Effective date: 2026-09-01" ("Date d'entrée en
   vigueur" in French) with links to the HTML chapters, a PDF and a zip of
   the Microsoft Access database. Some editions are inside HTML comments
   (T2023-2 on the 2023 page): those are not offered.
2. File names vary by year: 01-99-eng.zip, 01-99-1-eng.zip (2018),
   01-99-2023-eng.zip, 01-99-2026-0-eng.zip, so links are read from the
   page, never built.
3. Each zip holds one database: an .mdb in 2018, an .accdb since (25 MB
   for 2026-2), with the schedule in table TPHS; 2021's database also has
   an attachment table, so the table is chosen by name. The French file has
   French descriptions and, since 2023, French column names (TARIF, NPF,
   TÉU ...); 2018's French file kept English names. Rate columns change with
   trade agreements (MUST until 2020, CPTPT from 2019, CPUKT from 2026-2).
4. Rows are headings ('01.01', with the sub-chapter title on the first
   heading of a sub-chapter), subheadings ('0101.2', '0101.21'), tariff
   items ('0101.21.00', which carry the rates) and 10-digit classification
   numbers ('0101.21.00.00', which carry the unit of measure). Rates are
   text: 'Free' / 'En fr.', '6.5 %' / '6,5 %', '35%', specific rates.
   Descriptions longer than 30,000 characters continue in DESC2 (9913.00.00,
   a list of pharmaceutical ingredients); lists inside a description are
   separated by CRLF or a vertical tab (\\x0b).
5. The General Tariff column (GT) of the first 2018 edition is empty on
   every row (checked in the English file); lines without a rate omit it.
6. 5206.41.00.00 appears twice with identical values in 2026-2, so
   identical rows are dropped.

Each edition is read once (accdb.py, about 6 s and 70 MB of memory for
2026-2) into a Parquet file under MAPLE_CBSA_TARIFF_CACHE_DIR; lookups and
searches are DuckDB queries on that file.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import tempfile
import unicodedata
import zipfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Comment

from maplestats_mcp import config
from maplestats_mcp.modules.cbsa_tariff import constants
from maplestats_mcp.modules.cbsa_tariff.accdb import AccessFormatError, AccessTable
from maplestats_mcp.modules.cbsa_tariff.schemas import (
    Level,
    TariffEdition,
    TariffEditions,
    TariffLine,
    TariffLookup,
    TariffRate,
    TariffSearch,
)
from maplestats_mcp.shared import duck
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.capped_io import FileTooLarge, copy_capped
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_TORONTO = ZoneInfo("America/Toronto")
_LABEL = re.compile(r"\bT(\d{4})(?:-(\d{1,2}))?\b")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_EDITION = re.compile(r"^T?(\d{4})(?:-(\d{1,2}))?$", re.IGNORECASE)
_PERCENT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*%$")
_FREE = {"free", "en fr.", "en fr", "en franchise"}
_downloads: dict[str, asyncio.Task[Path]] = {}


def _fr(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


def skeleton(name: str) -> str:
    """A column name's ASCII letters and digits, upper case (see constants.TREATMENTS)."""
    return "".join(c for c in name.upper() if c.isascii() and c.isalnum())


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def level_of(digits: str) -> Level:
    size = len(digits)
    if size == 2:
        return "chapter"
    if size == 4:
        return "heading"
    if size in (5, 6):
        return "subheading"
    if size == 8:
        return "tariff_item"
    if size in (9, 10):
        return "classification"
    return "other"


def percent_of(text: str) -> float | None:
    value = " ".join(text.split())
    if value.casefold() in _FREE:
        return 0.0
    match = _PERCENT.match(value)
    return float(match.group(1).replace(",", ".")) if match else None


# ---------------------------------------------------------------- editions


def parse_menu(html: str, year: int, lang: str) -> list[TariffEdition]:
    """The editions a year page offers, newest first; commented-out ones are skipped."""
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    editions: list[TariffEdition] = []
    for panel in soup.select("section.panel"):
        heading = panel.find(["h2", "h3"])
        title = " ".join(heading.get_text(" ").split()) if heading else ""
        label, when = _LABEL.search(title), _DATE.search(title)
        links = [str(a.get("href") or "") for a in panel.find_all("a")]
        zips = [h for h in links if h.lower().endswith(".zip")]
        if not label or not when or not zips:
            continue
        edition = label.group(1) + (f"-{label.group(2)}" if label.group(2) else "")
        pdf = next((h for h in links if h.lower().endswith(".pdf")), None)
        page = next((h for h in links if "/html/" in h), None)
        editions.append(
            TariffEdition(
                edition=edition,
                effective_date=date.fromisoformat(when.group(1)),
                year=year,
                access_zip_url=_absolute(zips[0]),
                pdf_url=_absolute(pdf) if pdf else None,
                html_url=_absolute(page) if page else None,
            )
        )
    return sorted(editions, key=lambda e: (e.effective_date, e.edition), reverse=True)


def _absolute(href: str) -> str:
    return href if href.startswith("http") else constants.SITE + "/" + href.lstrip("/")


class _NoYearPage(NotFound):
    """CBSA has no menu page for the year (HTTP 404); never cached."""


async def _year_editions(year: int, lang: str) -> tuple[list[TariffEdition], bool]:
    """A year's editions. A 404 raises _NoYearPage (a NotFound) rather than giving [].

    An empty list read like "this year has no editions", and was cached for
    six hours; the callers decide when a missing page is expected (the
    current year before CBSA posts it) and say so.
    """
    url = constants.MENU_URL.format(year=year, suffix=constants.SUFFIX[lang])

    async def fetch() -> list[TariffEdition]:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=30.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise_localized(
                    _NoYearPage,
                    f"cbsa_tariff: CBSA has no tariff page for {year} ({url} answered 404).",
                    f"cbsa_tariff : l'ASFC n'a pas de page tarifaire pour {year} ({url} a "
                    "répondu 404).",
                    lang,
                )
            raise_localized(
                UpstreamError,
                f"cbsa_tariff: {url} returned HTTP {exc.response.status_code}.",
                f"cbsa_tariff : {url} a renvoyé HTTP {exc.response.status_code}.",
                lang,
            )
        except httpx.HTTPError:
            raise_localized(
                UpstreamUnavailable,
                f"cbsa_tariff: {url} did not respond in time.",
                f"cbsa_tariff : {url} n'a pas répondu à temps.",
                lang,
            )
        return parse_menu(response.text, year, lang)

    return await cached_fetch(f"cbsa_tariff:menu:{year}:{lang}", constants.MENU_TTL_SECONDS, fetch)


def _this_year() -> int:
    return datetime.now(_TORONTO).year


async def list_editions(*, year: int | None = None, lang: str = "en") -> TariffEditions:
    current = _this_year()
    if year is not None and not constants.FIRST_YEAR <= year <= current:
        raise_localized(
            InvalidInput,
            f"cbsa_tariff: year must be {constants.FIRST_YEAR} to {current}; CBSA has no "
            "earlier editions online.",
            f"cbsa_tariff : l'année doit aller de {constants.FIRST_YEAR} à {current} ; l'ASFC "
            "n'a pas d'éditions antérieures en ligne.",
            lang,
        )
    years = [year] if year is not None else [current, current - 1]
    editions: list[TariffEdition] = []
    cached = True
    missing: list[int] = []
    for each in years:
        try:
            found, hit = await _year_editions(each, lang)
        except _NoYearPage:
            # A year asked for is an error; in the default two-year listing the
            # other year's editions are still returned, and the limits name the gap.
            if year is not None:
                raise
            missing.append(each)
            continue
        editions += found
        cached = cached and hit
    url = constants.MENU_URL.format(year=years[0], suffix=constants.SUFFIX[lang])
    return TariffEditions(
        editions=editions,
        years=[y for y in years if y not in missing],
        missing_years=missing,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="cbsa_tariff.TariffEditions",
            freshness=_fr(constants.FRESHNESS, constants.FRESHNESS_FR, lang),
            coverage=_fr(
                f"editions of {', '.join(map(str, years))}; years {constants.FIRST_YEAR} "
                "onward are online (pass `year`)",
                f"éditions de {', '.join(map(str, years))} ; les années à partir de "
                f"{constants.FIRST_YEAR} sont en ligne (paramètre `year`)",
                lang,
            ),
            limits=_fr(
                f"CBSA's tariff page for {' and '.join(map(str, missing))} answered HTTP 404 "
                "(not posted yet, or moved), so those editions are not listed",
                f"la page tarifaire de l'ASFC pour {' et '.join(map(str, missing))} a répondu "
                "HTTP 404 (pas encore publiée, ou déplacée) : ces éditions ne sont pas listées",
                lang,
            )
            if missing
            else None,
            lang=lang,
        ),
    )


async def resolve_edition(edition: str, lang: str) -> TariffEdition:
    """'latest', an edition ('2026-2', 'T2026', '2026-0') or a date (the edition then in force)."""
    wanted = edition.strip() or "latest"
    current = _this_year()
    on_date: date | None = None
    label: tuple[str, str] | None = None
    if wanted.casefold() in ("latest", "current", "dernière", "derniere"):
        on_date = datetime.now(_TORONTO).date()
    elif match := _EDITION.match(wanted):
        label = (match.group(1), match.group(2) or "0")
    else:
        try:
            on_date = date.fromisoformat(wanted)
        except ValueError:
            raise_localized(
                InvalidInput,
                f"cbsa_tariff: edition {edition!r} is not 'latest', an edition such as "
                "'2026-2', or a date YYYY-MM-DD.",
                f"cbsa_tariff : l'édition {edition!r} n'est ni 'latest', ni une édition comme "
                "'2026-2', ni une date AAAA-MM-JJ.",
                lang,
            )
    if label is not None:
        year = int(label[0])
        if constants.FIRST_YEAR <= year <= current:
            # A missing year page propagates as NotFound naming the page.
            for item in (await _year_editions(year, lang))[0]:
                parts = item.edition.split("-")
                if (parts[0], parts[1] if len(parts) > 1 else "0") == label:
                    return item
        raise_localized(
            NotFound,
            f"cbsa_tariff: no edition {edition!r}; cbsa_tariff_list_editions lists them.",
            f"cbsa_tariff : aucune édition {edition!r} ; cbsa_tariff_list_editions les énumère.",
            lang,
        )
    assert on_date is not None
    for year in range(min(on_date.year, current), constants.FIRST_YEAR - 1, -1):
        try:
            year_editions = (await _year_editions(year, lang))[0]
        except _NoYearPage:
            # The current year's page may not be posted yet, and then the edition
            # in force is genuinely last year's; any other missing year is an error.
            if year != current:
                raise
            continue
        in_force = [e for e in year_editions if e.effective_date <= on_date]
        if in_force:
            return in_force[0]
    raise_localized(
        NotFound,
        f"cbsa_tariff: no edition in force on {on_date}; the earliest online is from "
        f"{constants.FIRST_YEAR}.",
        f"cbsa_tariff : aucune édition en vigueur le {on_date} ; la plus ancienne en ligne "
        f"date de {constants.FIRST_YEAR}.",
        lang,
    )


# ------------------------------------------------------------------ store


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x0b", "\n").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def _column_index(names: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    """(field -> column index, treatment code -> column index) for one database."""
    by_skeleton = {skeleton(n): i for i, n in enumerate(names)}
    fields = {
        key: by_skeleton[skeleton(alias)]
        for key, aliases in constants.FIELDS.items()
        for alias in aliases
        if skeleton(alias) in by_skeleton
    }
    rates = {
        code: by_skeleton[skeleton(alias)]
        for code, aliases, _, _ in constants.TREATMENTS
        for alias in aliases
        if skeleton(alias) in by_skeleton
    }
    return fields, rates


def database_rows(path: Path) -> list[dict[str, Any]]:
    """The schedule's rows from one Access file, normalized for the Parquet copy."""
    table = AccessTable(path, constants.TABLE)
    names = [c.name for c in table.columns]
    fields, rates = _column_index(names)
    if "tariff" not in fields or "MFN" not in rates:
        raise AccessFormatError(f"{path.name}: no TARIFF or MFN column among {names}.")
    out: list[dict[str, Any]] = []
    for row in table.rows():

        def field(key: str, row: list[Any] = row) -> Any:
            return row[fields[key]] if key in fields else None

        tariff = _clean(field("tariff"))
        if not tariff:
            continue
        tariff = "".join(tariff.split())
        description = "".join(
            str(field(k)) for k in ("desc1", "desc2", "desc3") if field(k) not in (None, "")
        )
        effective = field("effective_date")
        uom = _clean(field("uom"))
        out.append(
            {
                "tariff": tariff,
                "digits": re.sub(r"\D", "", tariff),
                "description": _clean(description) or "",
                "sub_chapter": _clean(field("sub_chapter")),
                "uom": None if uom in (None, "-") else uom,
                "footnote": _clean(field("footnote")),
                "effective_date": effective.date().isoformat()
                if isinstance(effective, datetime)
                else None,
                "changed": bool(field("change")),
                "rates": json.dumps(
                    {
                        code: text
                        for code, index in rates.items()
                        if (text := _clean(row[index])) is not None
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return out


def write_parquet(rows: list[dict[str, Any]], target: Path) -> None:
    """Write the rows as Parquet through a JSON-lines file (multi-line text stays intact)."""
    lines = target.with_suffix(".jsonl.part")
    part = target.with_suffix(".parquet.part")
    try:
        with lines.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        source = str(lines).replace("'", "''")
        sink = str(part).replace("'", "''")
        columns = (
            "{'tariff': 'VARCHAR', 'digits': 'VARCHAR', 'description': 'VARCHAR', "
            "'sub_chapter': 'VARCHAR', 'uom': 'VARCHAR', 'footnote': 'VARCHAR', "
            "'effective_date': 'DATE', 'changed': 'BOOLEAN', 'rates': 'VARCHAR'}"
        )
        with duck.connect() as connection:
            connection.execute(
                f"COPY (SELECT DISTINCT * FROM read_json('{source}', format='newline_delimited', "
                f"columns={columns}) ORDER BY digits, tariff) "
                f"TO '{sink}' (FORMAT parquet, COMPRESSION zstd)"
            )
        part.replace(target)
    finally:
        lines.unlink(missing_ok=True)
        part.unlink(missing_ok=True)


def _enforce_cache_cap(root: Path, keep: Path) -> None:
    files = sorted(root.glob("*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[constants.MAX_CACHED_EDITIONS :]:
        if path != keep:
            path.unlink(missing_ok=True)


def convert_zip(body: bytes, target: Path, url: str) -> None:
    """Unpack the database in a zip body and write its schedule to `target` as Parquet."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as scratch:
        database = Path(scratch) / "tariff.accdb"
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                member = next(
                    (n for n in archive.namelist() if n.lower().endswith((".accdb", ".mdb"))),
                    None,
                )
                if member is None:
                    raise UpstreamError(f"cbsa_tariff: {url} holds no Access database.")
                with archive.open(member) as source, database.open("wb") as sink:
                    copy_capped(source, sink, constants.MAX_DATABASE_BYTES, member)
        except zipfile.BadZipFile as exc:
            raise UpstreamError(f"cbsa_tariff: {url} is not a readable zip: {exc}") from exc
        try:
            rows = database_rows(database)
        except AccessFormatError as exc:
            raise UpstreamError(f"cbsa_tariff: {url}: {exc}") from exc
        if not rows:
            raise UpstreamError(f"cbsa_tariff: {url} has no tariff lines.")
        write_parquet(rows, target)
    _enforce_cache_cap(target.parent, target)


async def _download_and_convert(edition: TariffEdition, target: Path, lang: str) -> Path:
    url = edition.access_zip_url
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=120.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 410):
            raise_localized(
                NotFound,
                f"cbsa_tariff: {url} is no longer published (HTTP {status}).",
                f"cbsa_tariff : {url} n'est plus publié (HTTP {status}).",
                lang,
            )
        raise_localized(
            UpstreamError,
            f"cbsa_tariff: {url} returned HTTP {status}.",
            f"cbsa_tariff : {url} a renvoyé HTTP {status}.",
            lang,
        )
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            f"cbsa_tariff: {url} did not respond in time.",
            f"cbsa_tariff : {url} n'a pas répondu à temps.",
            lang,
        )
    if len(response.content) > constants.MAX_ZIP_BYTES:
        raise_localized(
            UpstreamError,
            f"cbsa_tariff: {url} is much larger than expected; it changed.",
            f"cbsa_tariff : {url} est beaucoup plus volumineux que prévu ; il a changé.",
            lang,
        )
    try:
        await run_in_pool(convert_zip, response.content, target, url)
    except FileTooLarge:
        raise
    except UpstreamError as exc:
        raise_localized(UpstreamError, str(exc), str(exc), lang)
    return target


async def local_table(edition: TariffEdition, lang: str) -> tuple[Path, bool]:
    """(the edition's Parquet copy, whether it was already on disk)."""
    # The zip URL names the edition and language, so a new edition is a new key.
    key = hashlib.sha1(edition.access_zip_url.encode()).hexdigest()[:12]
    target = config.get_cbsa_tariff_cache_dir() / f"{edition.edition}-{lang}-{key}.parquet"
    if target.exists():
        target.touch()
        return target, True
    task = _downloads.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_download_and_convert(edition, target, lang))
        _downloads[key] = task
    return await asyncio.shield(task), False


# ---------------------------------------------------------------- queries


def _line(row: dict[str, Any], lang: str, limit: int | None) -> TariffLine:
    names = {code: (en, fr) for code, _, en, fr in constants.TREATMENTS}
    found: dict[str, str] = json.loads(row["rates"] or "{}")
    rates = [
        TariffRate(
            code=code,
            name=names[code][1] if lang == "fr" else names[code][0],
            text=found[code],
            percent=percent_of(found[code]),
        )
        for code in names
        if code in found
    ]
    description = row["description"] or ""
    cut = limit is not None and len(description) > limit
    effective = row["effective_date"]
    return TariffLine(
        tariff=row["tariff"],
        digits=row["digits"],
        level=level_of(row["digits"]),
        description=description[:limit].rstrip() + " ..." if cut else description,
        description_truncated=cut,
        sub_chapter=row["sub_chapter"],
        unit_of_measure=row["uom"],
        footnote=row["footnote"],
        effective_date=effective if isinstance(effective, date) else None,
        changed_in_edition=bool(row["changed"]),
        mfn=found.get("MFN"),
        general=found.get("GT"),
        rates=rates,
    )


def _query(path: Path, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with duck.connect() as connection:
        cursor = connection.execute(sql.replace("{table}", "read_parquet(?)"), [str(path), *params])
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]


def _provenance(
    edition: TariffEdition, cached: bool, schema: str, lang: str, limits: str | None = None
) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=edition.access_zip_url,
        cached=cached,
        schema_name=schema,
        as_of=datetime.combine(edition.effective_date, time()),
        freshness=_fr(constants.FRESHNESS, constants.FRESHNESS_FR, lang),
        coverage=_fr(constants.COVERAGE, constants.COVERAGE_FR, lang),
        limits=limits,
        lang=lang,
    )


async def lookup(tariff: str, *, edition: str = "latest", lang: str = "en") -> TariffLookup:
    digits = re.sub(r"[\s.\-]", "", tariff)
    if not digits.isdigit() or not 2 <= len(digits) <= 10:
        raise_localized(
            InvalidInput,
            f"cbsa_tariff: {tariff!r} is not a tariff number: give 2 to 10 digits, dots "
            "allowed ('8703.80', '0401.10.10', '8703800000'). To find one by words, use "
            "cbsa_tariff_search.",
            f"cbsa_tariff : {tariff!r} n'est pas un numéro tarifaire : donnez de 2 à 10 "
            "chiffres, points permis ('8703.80', '0401.10.10', '8703800000'). Pour en trouver "
            "un par mots, utilisez cbsa_tariff_search.",
            lang,
        )
    chosen = await resolve_edition(edition, lang)
    path, cached = await local_table(chosen, lang)
    rows = await run_in_pool(
        _query,
        path,
        "SELECT * FROM {table} WHERE digits = ? OR (starts_with(?, digits) AND length(digits) < ?) "
        "OR (starts_with(digits, ?) AND length(digits) > ?) ORDER BY digits, tariff",
        [digits, digits, len(digits), digits, len(digits)],
    )
    item = next((r for r in rows if r["digits"] == digits), None)
    ancestors = [r for r in rows if len(r["digits"]) < len(digits)]
    children = [r for r in rows if len(r["digits"]) > len(digits)]
    note = None
    if item is None and not children:
        if not ancestors:
            raise_localized(
                NotFound,
                f"cbsa_tariff: no tariff line {tariff!r} in edition {chosen.edition}; "
                "cbsa_tariff_search finds lines by words or chapter.",
                f"cbsa_tariff : aucune ligne tarifaire {tariff!r} dans l'édition "
                f"{chosen.edition} ; cbsa_tariff_search trouve des lignes par mots ou chapitre.",
                lang,
            )
        note = _fr(
            f"{tariff} is not a line of edition {chosen.edition}; its nearest headings are shown.",
            f"{tariff} n'est pas une ligne de l'édition {chosen.edition} ; ses positions les "
            "plus proches sont affichées.",
            lang,
        )
    shown = children[: constants.CHILDREN_LIMIT]
    limits = None
    if len(children) > len(shown):
        limits = _fr(
            f"first {len(shown)} of {len(children)} lines under {tariff}; ask for a longer "
            "number to narrow",
            f"{len(shown)} premières lignes sur {len(children)} sous {tariff} ; donnez un "
            "numéro plus long pour restreindre",
            lang,
        )
    return TariffLookup(
        edition=chosen,
        query=tariff,
        item=_line(item, lang, None) if item else None,
        ancestors=[_line(r, lang, constants.SNIPPET_CHARS) for r in ancestors],
        children=[_line(r, lang, constants.SNIPPET_CHARS) for r in shown],
        total_children=len(children),
        note=note,
        provenance=_provenance(chosen, cached, "cbsa_tariff.TariffLookup", lang, limits),
    )


async def search(
    query: str = "",
    *,
    chapter: str = "",
    edition: str = "latest",
    limit: int = 25,
    lang: str = "en",
) -> TariffSearch:
    words = fold(query).split()
    chapter_digits = re.sub(r"\D", "", chapter)
    if chapter.strip() and not 1 <= len(chapter_digits) <= 2:
        raise_localized(
            InvalidInput,
            f"cbsa_tariff: chapter {chapter!r} must be 1 to 99.",
            f"cbsa_tariff : le chapitre {chapter!r} doit aller de 1 à 99.",
            lang,
        )
    if not words and not chapter_digits:
        raise_localized(
            InvalidInput,
            "cbsa_tariff: give words to search for, a chapter, or both.",
            "cbsa_tariff : donnez des mots à chercher, un chapitre, ou les deux.",
            lang,
        )
    if not 1 <= limit <= constants.SEARCH_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"cbsa_tariff: limit must be 1 to {constants.SEARCH_LIMIT_MAX}.",
            f"cbsa_tariff : limit doit aller de 1 à {constants.SEARCH_LIMIT_MAX}.",
            lang,
        )
    chosen = await resolve_edition(edition, lang)
    path, cached = await local_table(chosen, lang)
    where: list[str] = []
    params: list[Any] = []
    if chapter_digits:
        where.append("starts_with(digits, ?)")
        params.append(chapter_digits.zfill(2))
    for word in words:
        if word.replace(".", "").isdigit():
            where.append("starts_with(digits, ?)")
            params.append(word.replace(".", ""))
        else:
            where.append("strip_accents(lower(description)) LIKE ?")
            params.append(f"%{word}%")
    rows = await run_in_pool(
        _query,
        path,
        "SELECT *, count(*) OVER () AS n FROM {table} WHERE "
        + " AND ".join(where)
        + " ORDER BY digits, tariff LIMIT ?",
        [*params, limit],
    )
    total = int(rows[0]["n"]) if rows else 0
    limits = None
    if total > len(rows):
        limits = _fr(
            f"first {len(rows)} of {total} matches; add words, a chapter or a higher limit",
            f"{len(rows)} premiers résultats sur {total} ; ajoutez des mots, un chapitre ou "
            "augmentez limit",
            lang,
        )
    return TariffSearch(
        edition=chosen,
        query=query,
        chapter=chapter_digits.zfill(2) if chapter_digits else None,
        lines=[_line(r, lang, constants.SNIPPET_CHARS) for r in rows],
        total_matches=total,
        returned_count=len(rows),
        provenance=_provenance(chosen, cached, "cbsa_tariff.TariffSearch", lang, limits),
    )
