"""Client for AER statistical reports (ST1 well licences, ST3 production
volumes). See the module docstring for the two opposite redirect
behaviors this relies on (static.aer.ca bypass for ST1 .TXT files,
real HTTP 303 for ST3 .xlsx/ST1 .zip files).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, NoReturn
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.aer import constants, st98
from maplestats_mcp.modules.aer.schemas import (
    ProductionVolumesLink,
    St98Edition,
    St98Observation,
    St98Series,
    St98Table,
    St98TableInfo,
    St98TableList,
    WellLicenceArchiveLink,
    WellLicenceDailyReport,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import new_client, send_with_retry
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# follow_redirects=True: needed for the real HTTP 303s on ST3 .xlsx and
# ST1 .zip links (see module docstring) -- the ST1 .TXT files instead
# bypass www.aer.ca entirely rather than relying on this.
_client = new_client(http2=False, follow_redirects=True)

_DATE_LINE_RE = re.compile(r"DATE:\s+(\d{1,2}\s+\w+\s+\d{4})")

# AER publishes its ST1/ST3 reports in English only, so a French call gets
# the text as is plus this note rather than a silent English answer.
_ENGLISH_ONLY_FR = french_spacing(
    "Les rapports de l'AER n'existent qu'en anglais ; ils sont reproduits tels quels."
)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English text unchanged; French goes through the typed-error template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


async def _head(url: str, context: str, lang: str) -> httpx.Response:
    """HEAD a file: 200 means it is there, 404 or 410 that it is not.

    Checked live 2026-10-27: a published ZIP or XLSX answers 200 and an
    unpublished month 404. Anything else (403, a 429 or 5xx that outlasted the
    retries, a network failure) says nothing about the file, so it raises,
    and cached_fetch does not keep it, rather than read as "no file here".
    """
    await _LIMITER.acquire()
    try:
        response = await send_with_retry(_client, "HEAD", url, headers=constants.HEAD_HEADERS)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        _raise(
            UpstreamUnavailable,
            f"aer:{context}: {url} answered HTTP {status}; try again shortly.",
            f"aer:{context} : {url} a répondu HTTP {status} ; réessayez sous peu.",
            lang,
        )
    except httpx.HTTPError:
        _raise(
            UpstreamUnavailable,
            f"aer:{context} did not respond in time.",
            f"aer:{context} n'a pas répondu à temps.",
            lang,
        )
    if response.status_code not in (200, 404, 410):
        _raise(
            UpstreamError,
            f"aer:{context}: {url} answered HTTP {response.status_code}, so whether the file "
            "exists is unknown.",
            f"aer:{context} : {url} a répondu HTTP {response.status_code} ; on ne peut donc "
            "pas savoir si le fichier existe.",
            lang,
        )
    return response


def _join_notes(*notes: str | None) -> str | None:
    return " ".join(n for n in notes if n) or None


def _parse_report_date(raw_text: str) -> date | None:
    match = _DATE_LINE_RE.search(raw_text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %B %Y").replace(tzinfo=UTC).date()
    except ValueError:
        return None


def _expected_date(day_key: str, today: date) -> date:
    """The most recent date (today or earlier) falling on that weekday."""
    target = list(constants.DAY_CODES).index(day_key)  # sunday = 0
    today_index = (today.weekday() + 1) % 7
    return today - timedelta(days=(today_index - target) % 7)


async def get_well_licences_daily(
    day: str | None = None, *, lang: str = "en"
) -> WellLicenceDailyReport:
    """Fetch AER's ST1 "Well Licences Issued - Daily List" for one weekday.
    `day` is a weekday name (e.g. "monday"); defaults to yesterday in
    America/Edmonton time, AER's own reporting timezone: a day's file is
    posted around midnight after it ends, so before then "today" still
    holds last week's list (live 2026-10-03, a Saturday: the default
    returned the 2026-09-26 list). Each weekday file is overwritten
    weekly; when it still holds an older list than the latest date with
    that weekday, `note` says so. Returns raw report text -- see the
    module docstring for why this stays a text report rather than a
    structured parse (each licence record spans 5 fixed-width lines with
    no stable column boundaries confirmed safe to split on)."""
    today = datetime.now(ZoneInfo(constants.TIMEZONE)).date()
    if day is None:
        day = (today - timedelta(days=1)).strftime("%A").lower()
    day_key = day.strip().lower()
    if day_key not in constants.DAY_CODES:
        _raise(
            InvalidInput,
            f"day must be one of {sorted(constants.DAY_CODES)}, got {day!r}.",
            f"day doit être l'un de {sorted(constants.DAY_CODES)} (jours de la semaine en "
            f"anglais), reçu {day!r}.",
            lang,
        )
    expected = _expected_date(day_key, today)
    day_code = constants.DAY_CODES[day_key]
    url = constants.WELL_LICENCE_DAILY_URL.format(day_code=day_code)

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            # Retries 429/5xx with backoff like every other source; a status
            # that is not retryable (a 404 for a file AER moved or has not
            # posted) comes back as a response and is typed below.
            response = await send_with_retry(_client, "GET", url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                _raise(
                    NotFound,
                    f"aer: no daily well-licence file at {url} (HTTP 404); the file may have "
                    "moved.",
                    f"aer : aucun fichier quotidien des permis de puits à {url} (HTTP 404) ; "
                    "le fichier a peut-être été déplacé.",
                    lang,
                )
            _raise(
                UpstreamError,
                f"aer: {url} returned HTTP {status}.",
                f"aer : {url} a répondu HTTP {status}.",
                lang,
            )
        except httpx.HTTPError:
            _raise(
                UpstreamUnavailable,
                "aer:get_well_licences_daily did not respond in time.",
                "aer:get_well_licences_daily n'a pas répondu à temps.",
                lang,
            )
        return response.text

    cache_key = f"aer:well-licences-daily:{day_key}"
    raw_text, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DAILY_SECONDS, fetch)
    report_date = _parse_report_date(raw_text)
    note = None
    if report_date is not None and report_date < expected:
        note = (
            f"This is the {report_date.isoformat()} list: the {day_key} list for "
            f"{expected.isoformat()} is not posted yet (files appear around midnight "
            "Alberta time after the day ends)."
            if lang != "fr"
            else french_spacing(
                f"Voici la liste du {report_date.isoformat()} : celle du "
                f"{expected.isoformat()} ({day_key}) n'est pas encore publiée (les fichiers "
                "paraissent vers minuit, heure de l'Alberta, après la fin de la journée)."
            )
        )
    if lang == "fr":
        note = _join_notes(note, _ENGLISH_ONLY_FR)

    return WellLicenceDailyReport(
        day=day_key,
        report_date=report_date,
        expected_date=expected,
        note=note,
        raw_text=raw_text,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.WellLicenceDailyReport",
            as_of=(
                datetime.combine(report_date, time(), tzinfo=ZoneInfo(constants.TIMEZONE))
                if report_date
                else None
            ),
            freshness=(
                "posted nightly by 12:00am MT; each weekday's file is overwritten weekly"
                if lang != "fr"
                else french_spacing(
                    "publié chaque nuit avant minuit (heure des Rocheuses) ; le fichier de "
                    "chaque jour de la semaine est remplacé chaque semaine"
                )
            ),
            lang=lang,
        ),
    )


def _archive_url(year: int, month: int | None, lang: str = "en") -> str:
    if month is not None:
        if not (1 <= month <= 12):
            _raise(
                InvalidInput,
                f"month must be between 1 and 12, got {month}.",
                f"month doit être compris entre 1 et 12, reçu {month}.",
                lang,
            )
        return constants.WELL_LICENCE_MONTHLY_ZIP_URL.format(year=year, month=month)
    if year >= constants.WELL_LICENCE_YEARLY_URL_PATH_BOUNDARY_YEAR:
        return constants.WELL_LICENCE_YEARLY_ZIP_URL_NEW.format(year=year)
    return constants.WELL_LICENCE_YEARLY_ZIP_URL_OLD.format(year=year)


async def get_well_licence_archive_link(
    year: int, month: int | None = None, *, lang: str = "en"
) -> WellLicenceArchiveLink:
    """Resolve (and confirm existence of) an AER ST1 well-licence archive
    ZIP. Pass `month` (1-12) for one month of the *current* year (AER
    only publishes monthly ZIPs for the year in progress); omit it for
    a full prior year's ZIP. Discovery-only -- these are large
    fixed-width archives, not parsed here."""
    today = datetime.now(ZoneInfo(constants.TIMEZONE)).date()
    first = constants.WELL_LICENCE_FIRST_YEAR
    if not first <= year <= today.year:
        _raise(
            InvalidInput,
            f"year must be between {first} and {today.year} "
            f"(AER's ST1 archive starts in {first}), got {year}.",
            f"year doit être compris entre {first} et {today.year} "
            f"(l'archive ST1 de l'AER commence en {first}), reçu {year}.",
            lang,
        )
    url = _archive_url(year, month, lang)
    if month is not None and (year, month) > (today.year, today.month):
        _raise(
            InvalidInput,
            f"{year}-{month:02d} has not happened yet; nothing is published.",
            f"{year}-{month:02d} n'est pas encore arrivé ; rien n'est publié.",
            lang,
        )

    async def fetch() -> httpx.Response:
        return await _head(url, "get_well_licence_archive_link", lang)

    cache_key = f"aer:well-licence-archive:{year}:{month}"
    response, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LINK_SECONDS, fetch)
    exists = response.status_code == 200
    size_raw = response.headers.get("content-length")
    size_bytes = int(size_raw) if exists and size_raw is not None and size_raw.isdigit() else None
    note = None
    if not exists:
        recent = month is not None and (year, month) >= (today.year, today.month - 1)
        if lang == "fr":
            note = french_spacing(
                "Pas encore publié : l'AER met en ligne le ZIP de chaque mois après la fin du mois."
                if recent
                else "L'AER n'a aucun fichier à cette adresse."
            )
        else:
            note = (
                "Not published yet: AER posts each month's ZIP after the month ends."
                if recent
                else "AER has no file at this address."
            )
    if lang == "fr":
        note = _join_notes(note, _ENGLISH_ONLY_FR)

    return WellLicenceArchiveLink(
        year=year,
        month=month,
        url=url,
        exists=exists,
        size_bytes=size_bytes,
        note=note,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.WellLicenceArchiveLink",
            lang=lang,
        ),
    )


async def get_production_volumes_link(product: str, *, lang: str = "en") -> ProductionVolumesLink:
    """Resolve (and confirm existence of) AER's ST3 current-month
    production-volume/price XLSX for one product. `product` is one of
    "butane", "ethane", "gas", "ngl", "oil", "propane", "sulphur",
    "oil_prices". Discovery-only -- this project has no pinned
    XLSX-parsing dependency, so the file itself is not parsed here."""
    product_key = product.strip().lower()
    if product_key not in constants.PRODUCTION_PRODUCTS:
        _raise(
            InvalidInput,
            f"product must be one of {sorted(constants.PRODUCTION_PRODUCTS)}, got {product!r}.",
            f"product doit être l'un de {sorted(constants.PRODUCTION_PRODUCTS)}, reçu {product!r}.",
            lang,
        )
    product_path = constants.PRODUCTION_PRODUCTS[product_key]
    url = constants.PRODUCTION_VOLUMES_URL.format(product_path=product_path)

    async def fetch() -> httpx.Response:
        return await _head(url, "get_production_volumes_link", lang)

    cache_key = f"aer:production-volumes:{product_key}"
    response, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LINK_SECONDS, fetch)
    exists = response.status_code == 200
    size_raw = response.headers.get("content-length")
    size_bytes = int(size_raw) if exists and size_raw is not None and size_raw.isdigit() else None

    return ProductionVolumesLink(
        product=product_key,
        url=url,
        exists=exists,
        size_bytes=size_bytes,
        last_modified=response.headers.get("last-modified"),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.ProductionVolumesLink",
            freshness=(
                "ST3 is released monthly, one month in arrears"
                if lang != "fr"
                else "ST3 est publié chaque mois, avec un mois de décalage"
            ),
            limits=_ENGLISH_ONLY_FR if lang == "fr" else None,
            lang=lang,
        ),
    )


# --- ST98 Alberta Energy Outlook ---------------------------------------------

_ST98_LINK = re.compile(r'href="([^"]*executive[-_]summary[-_]data\.xlsx)"', re.IGNORECASE)
_ST98_LINK_YEAR = re.compile(r"st98[-_]?(20\d\d)", re.IGNORECASE)
_ST98_PATH_YEAR = re.compile(r"/(20\d\d)/")
_ST98_TABLE_ID = re.compile(r"^(fig(?:ure)?|tab(?:le)?)[\s_.-]*(\d+)$", re.IGNORECASE)
_ST98_MAX_PAGE_BYTES = 2 * 1024 * 1024


def _aer_host(host: str) -> bool:
    return host in (constants.WWW_DOMAIN, constants.STATIC_DOMAIN)


async def _st98_download(url: str, max_bytes: int) -> file_download.Downloaded:
    """GET an aer.ca file under a size cap; www.aer.ca answers 301 to static.aer.ca."""
    return await file_download.download(
        url,
        allow_host=_aer_host,
        limiter_for=lambda _host: _LIMITER,
        max_bytes=max_bytes,
        context="aer",
        timeout=60.0,
    )


def st98_editions_from_page(html: str) -> dict[int, str]:
    """Edition year -> workbook URL for every executive-summary workbook the page links."""
    found: dict[int, str] = {}
    for href in _ST98_LINK.findall(html):
        url = urljoin(constants.ST98_PAGE_URL, href)
        name = url.rsplit("/", 1)[-1]
        match = _ST98_LINK_YEAR.search(name) or _ST98_PATH_YEAR.search(url)
        if match:
            found.setdefault(int(match.group(1)), url)
    return found


async def _st98_editions() -> tuple[list[St98Edition], bool]:
    """(editions newest first, read from the live page).

    The page is read so a new edition shows up without a release of this
    server; the editions recorded in constants (all checked live) fill in
    when the page does not answer or drops an older link.
    """

    async def load() -> dict[int, str]:
        page = await _st98_download(constants.ST98_PAGE_URL, _ST98_MAX_PAGE_BYTES)
        return st98_editions_from_page(page.body.decode("utf-8", errors="replace"))

    try:
        linked, _ = await cached_fetch("aer:st98:page", constants.CACHE_TTL_ST98_SECONDS, load)
    except (NotFound, UpstreamError, UpstreamUnavailable):
        linked = {}
    years = sorted(set(constants.ST98_WORKBOOKS) | set(linked), reverse=True)
    editions = [
        St98Edition(
            edition=year,
            workbook_url=linked.get(year) or constants.ST98_WORKBOOKS[year],
            report_url=constants.ST98_REPORTS.get(year),
        )
        for year in years
    ]
    return editions, bool(linked)


def _pick_edition(editions: list[St98Edition], edition: int | None, lang: str) -> St98Edition:
    if edition is None:
        return editions[0]
    for item in editions:
        if item.edition == edition:
            return item
    known = sorted(e.edition for e in editions)
    _raise(
        NotFound,
        f"aer: no ST98 executive-summary workbook for {edition}; editions are {known} "
        "(earlier editions publish their data as ZIP archives only).",
        f"aer : aucun classeur de sommaire ST98 pour {edition} ; les éditions sont {known} "
        "(les éditions antérieures ne publient leurs données qu'en archives ZIP).",
        lang,
    )


async def _st98_blocks(chosen: St98Edition, lang: str) -> tuple[list[st98.ParsedBlock], bool]:
    async def load() -> list[st98.ParsedBlock]:
        response = await _st98_download(chosen.workbook_url, constants.ST98_MAX_WORKBOOK_BYTES)
        if not response.body.startswith(b"PK"):
            _raise(
                UpstreamError,
                f"aer: {chosen.workbook_url} is not an Excel workbook.",
                f"aer : {chosen.workbook_url} n'est pas un classeur Excel.",
                lang,
            )
        blocks = await run_parse(st98.parse_workbook, response.body)
        if not any(b.kind == "figure" for b in blocks):
            _raise(
                UpstreamError,
                f"aer: no figure data read from the ST98 {chosen.edition} workbook; its layout "
                "changed.",
                f"aer : aucune donnée de figure lue dans le classeur ST98 {chosen.edition} ; sa "
                "structure a changé.",
                lang,
            )
        return blocks

    key = f"aer:st98:{chosen.edition}:{chosen.workbook_url}"
    return await cached_fetch(key, constants.CACHE_TTL_ST98_SECONDS, load)


def _st98_title(block: st98.ParsedBlock, edition: int, lang: str) -> str:
    titles = constants.ST98_TITLES.get(edition, {})
    if block.table_id in titles:
        en, fr = titles[block.table_id]
        return french_spacing(fr) if lang == "fr" else en
    # Tables carry their title in the heading: "Table 1 Resources, reserves, ..."
    title = re.sub(r"^\s*(Figure|Table)\s+\d+\s*", "", block.heading).strip()
    return title or block.heading


def _st98_provenance(
    url: str, cached: bool, schema: str, lang: str, coverage: str | None = None
) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"aer.{schema}",
        freshness=(
            "one edition a year (around June): history to the year before, forecast for the "
            "next ten years"
            if lang != "fr"
            else french_spacing(
                "une édition par année (vers juin) : historique jusqu'à l'année précédente, "
                "prévisions pour les dix années suivantes"
            )
        ),
        coverage=coverage,
        limits=_ENGLISH_ONLY_FR if lang == "fr" else None,
        lang=lang,
    )


def _st98_info(block: st98.ParsedBlock, edition: int, lang: str) -> St98TableInfo:
    years = [r.year for r in block.rows if r.year is not None]
    return St98TableInfo(
        table=block.table_id,
        title=_st98_title(block, edition, lang),
        heading=block.heading,
        sheet=block.sheet,
        series=[St98Series(series=s.label, unit=s.unit) for s in block.series],
        rows=len(block.rows),
        first_year=min(years) if years else None,
        last_year=max(years) if years else None,
        has_forecast=any(y >= edition for y in years),
    )


async def list_st98_tables(
    edition: int | None = None, *, query: str = "", lang: str = "en"
) -> St98TableList:
    """The ST98 editions, and the figures and tables of one edition matching `query`."""
    editions, live = await _st98_editions()
    chosen = _pick_edition(editions, edition, lang)
    blocks, cached = await _st98_blocks(chosen, lang)
    words = query.casefold().split()
    infos = [_st98_info(b, chosen.edition, lang) for b in blocks]
    found = [
        info
        for info in infos
        if all(
            w
            in " ".join(
                [info.table, info.title, info.heading, *(s.series for s in info.series)]
            ).casefold()
            for w in words
        )
    ]
    coverage = None
    if not live:
        coverage = (
            "The ST98 page did not answer; editions are the ones MapleStats recorded."
            if lang != "fr"
            else french_spacing(
                "La page ST98 n'a pas répondu ; les éditions sont celles que MapleStats a relevées."
            )
        )
    return St98TableList(
        editions=editions,
        edition=chosen.edition,
        forecast_from=chosen.edition,
        tables=found,
        total_matched=len(found),
        provenance=_st98_provenance(chosen.workbook_url, cached, "St98TableList", lang, coverage),
    )


def _st98_table_id(table: str, lang: str) -> str:
    match = _ST98_TABLE_ID.match(table.strip())
    if match is None:
        _raise(
            InvalidInput,
            f"aer: table must look like 'figure_8' or 'table_1', got {table!r}.",
            f"aer : table doit ressembler à 'figure_8' ou 'table_1', reçu {table!r}.",
            lang,
        )
    kind = "figure" if match.group(1).lower().startswith("fig") else "table"
    return f"{kind}_{int(match.group(2))}"


async def get_st98_table(
    table: str,
    *,
    edition: int | None = None,
    series: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    forecast: bool | None = None,
    lang: str = "en",
) -> St98Table:
    """One ST98 figure or table as tidy observations, history and forecast flagged."""
    table_id = _st98_table_id(table, lang)
    if start_year is not None and end_year is not None and start_year > end_year:
        _raise(
            InvalidInput,
            f"aer: start_year {start_year} is after end_year {end_year}.",
            f"aer : start_year {start_year} est postérieur à end_year {end_year}.",
            lang,
        )
    editions, _ = await _st98_editions()
    chosen = _pick_edition(editions, edition, lang)
    blocks, cached = await _st98_blocks(chosen, lang)
    block = next((b for b in blocks if b.table_id == table_id), None)
    if block is None:
        ids = ", ".join(b.table_id for b in blocks)
        _raise(
            NotFound,
            f"aer: no {table_id} in the ST98 {chosen.edition} workbook; it has {ids} (see "
            "aer_st98_list_tables).",
            f"aer : aucun {table_id} dans le classeur ST98 {chosen.edition} ; il contient {ids} "
            "(voir aer_st98_list_tables).",
            lang,
        )
    wanted = [
        i
        for i, s in enumerate(block.series)
        if not series or series.casefold() in s.label.casefold()
    ]
    if not wanted:
        labels = "; ".join(s.label for s in block.series)
        _raise(
            NotFound,
            f"aer: no series matching {series!r} in {table_id}; its series are: {labels}.",
            f"aer : aucune série correspondant à {series!r} dans {table_id} ; ses séries sont : "
            f"{labels}.",
            lang,
        )
    estimated = block.estimated_years()
    observations: list[St98Observation] = []
    for row in block.rows:
        if row.year is None and (start_year is not None or end_year is not None):
            continue
        if row.year is not None:
            if start_year is not None and row.year < start_year:
                continue
            if end_year is not None and row.year > end_year:
                continue
        is_forecast = None if row.year is None else row.year >= chosen.edition
        if forecast is not None and is_forecast is not forecast:
            continue
        for i in wanted:
            if row.values[i] is None and row.markers[i] is None:
                continue
            observations.append(
                St98Observation(
                    series=block.series[i].label,
                    category=row.label if row.is_item else None,
                    year=row.year,
                    period=row.period,
                    row_label=row.label,
                    value=row.values[i],
                    unit=block.series[i].unit,
                    marker=row.markers[i],
                    forecast=is_forecast,
                    estimated=row.year in estimated,
                    edition=chosen.edition,
                )
            )
    return St98Table(
        edition=chosen,
        table=table_id,
        title=_st98_title(block, chosen.edition, lang),
        heading=block.heading,
        forecast_from=chosen.edition,
        series=[
            St98Series(series=block.series[i].label, unit=block.series[i].unit) for i in wanted
        ],
        observations=observations,
        total_observations=len(observations),
        notes=block.notes,
        provenance=_st98_provenance(chosen.workbook_url, cached, "St98Table", lang),
    )
