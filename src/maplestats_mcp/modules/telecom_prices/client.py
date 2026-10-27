"""Client for the CRTC Communications Market Reports workbooks.

Checked live 2026-10-27:

1. The CRTC's 95 open.canada.ca datasets include the year-end plan price
   survey (2016-2025, version 11 of 2026-05-14, although the dataset title
   still says 2016-2022), the retail mobile and retail fixed Internet
   sector tables (2013-2024, titles say 2013-2022) and the quarterly
   current trends (2014 Q1 to 2026 Q1, version 17 of 2026-08-21). None has
   a DataStore. Their "CSV" resources are ZIP archives of one CSV per sheet
   in Windows-1252, which ckan_read_resource refuses; the XLSX resources
   are read here.
2. The files are on applications.crtc.gc.ca, which answers without the
   Cloudflare challenge that blocks crtc.gc.ca (403 "Security Check" on
   every page tried, including the low-cost plan page and the terms). The
   host reset a connection once in five downloads, so downloads are
   retried by the shared reader's caller (cached once read).
3. Resource ids have stayed the same across updates (the price XLSX was
   replaced in place in February and May 2026); a resource that is gone is
   looked up again by format and language in the dataset.
4. The sector workbooks exist in English and French with different tab
   names for figures (MB-F12 and MB-G12); the price and quarterly
   workbooks are bilingual, one file for both languages.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.telecom_prices import constants, parsing
from maplestats_mcp.modules.telecom_prices.schemas import (
    MarketObservation,
    MarketTable,
    MarketTableList,
    MarketTableRef,
    PlanPricePoint,
    PlanPrices,
    QuarterlyTrends,
    TrendObservation,
)
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import french_spacing, normalize_lang
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    raise_localized(exc_cls, en, fr, lang)


def _text(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


# Fetching ---------------------------------------------------------------------


async def _package(workbook: constants.Workbook, lang: str) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        await _LIMITER.acquire()
        try:
            body = await api_get(
                constants.CKAN_PACKAGE_SHOW, params={"id": workbook.dataset_id}, timeout=30.0
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                _raise(
                    NotFound,
                    f"telecom_prices: the CRTC dataset {workbook.dataset_id} is no longer on "
                    "open.canada.ca.",
                    f"telecom_prices : le jeu de données du CRTC {workbook.dataset_id} n'est "
                    "plus sur ouvert.canada.ca.",
                    lang,
                )
            _raise(
                UpstreamError,
                f"telecom_prices: open.canada.ca answered HTTP {exc.response.status_code}.",
                f"telecom_prices : ouvert.canada.ca a répondu HTTP {exc.response.status_code}.",
                lang,
            )
        except httpx.HTTPError as exc:
            _raise(
                UpstreamUnavailable,
                f"telecom_prices: open.canada.ca did not respond ({type(exc).__name__}).",
                f"telecom_prices : ouvert.canada.ca n'a pas répondu ({type(exc).__name__}).",
                lang,
            )
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            _raise(
                UpstreamError,
                "telecom_prices: open.canada.ca returned no dataset record.",
                "telecom_prices : ouvert.canada.ca n'a renvoyé aucune fiche de jeu de données.",
                lang,
            )
        return result

    return await cached_fetch(
        f"telecom_prices:package:{workbook.dataset_id}", constants.PACKAGE_TTL_SECONDS, fetch
    )


def pick_resource(package: dict[str, Any], resource_id: str, lang: str) -> dict[str, Any]:
    """The XLSX resource by id, or else the dataset's XLSX in that language."""
    resources = [r for r in list_or_empty(package, "resources") if isinstance(r, dict)]
    for resource in resources:
        if resource.get("id") == resource_id:
            return resource
    xlsx = [r for r in resources if str(r.get("format") or "").upper() in ("XLSX", "XLS")]
    for resource in xlsx:
        if lang in list_or_empty(resource, "language"):
            return resource
    if xlsx:
        return xlsx[0]
    _raise(
        NotFound,
        "telecom_prices: the CRTC dataset no longer lists an Excel file.",
        "telecom_prices : le jeu de données du CRTC ne contient plus de fichier Excel.",
        lang,
    )


def _title(package: dict[str, Any], workbook: constants.Workbook, lang: str) -> str:
    titles = package.get("title_translated") or {}
    found = titles.get(lang) if isinstance(titles, dict) else None
    return str(found or (workbook.title_fr if lang == "fr" else workbook.title_en))


async def _download(url: str, lang: str) -> bytes:
    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=lambda host: host == constants.FILE_HOST,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context="telecom_prices",
            timeout=90.0,
        )

    try:
        downloaded, _ = await file_download.cached_download(
            file_download.cache_key(url), constants.FILE_TTL_SECONDS, fetch
        )
    except UpstreamUnavailable:
        # The file host reset one connection in five on 2026-10-27 and then
        # answered the same URL at once; one more try is cheaper than a failure.
        downloaded, _ = await file_download.cached_download(
            file_download.cache_key(url), constants.FILE_TTL_SECONDS, fetch
        )
    if not downloaded.body.startswith(b"PK"):
        _raise(
            UpstreamError,
            f"telecom_prices: {url} is not an Excel workbook.",
            f"telecom_prices : {url} n'est pas un classeur Excel.",
            lang,
        )
    return downloaded.body


def read_sheets(body: bytes, wanted: Callable[[str], bool]) -> dict[str, list[tuple[Any, ...]]]:
    """The rows of every sheet whose name `wanted` accepts; key "" holds the sheet names."""
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        sheets: dict[str, list[tuple[Any, ...]]] = {"": [tuple(book.sheetnames)]}
        for name in book.sheetnames:
            if wanted(name):
                sheets[name] = [tuple(r) for r in book[name].iter_rows(values_only=True)]
        return sheets
    finally:
        book.close()


async def _workbook(
    workbook: constants.Workbook,
    lang: str,
    wanted: Callable[[str], bool],
    key: str,
) -> tuple[dict[str, list[tuple[Any, ...]]], dict[str, Any], dict[str, Any], bool]:
    package, package_cached = await _package(workbook, lang)
    resource_id = workbook.resource_fr if lang == "fr" else workbook.resource_en
    resource = pick_resource(package, resource_id, lang)
    url = str(resource.get("url") or "")

    async def fetch() -> dict[str, list[tuple[Any, ...]]]:
        body = await _download(url, lang)
        try:
            return await run_parse(read_sheets, body, wanted)
        except UpstreamError:
            raise  # the parse time budget (shared/executor.py) says so itself
        except Exception as exc:  # noqa: BLE001 (openpyxl raises several unrelated types)
            _raise(
                UpstreamError,
                f"telecom_prices: could not read {url} ({type(exc).__name__}).",
                f"telecom_prices : impossible de lire {url} ({type(exc).__name__}).",
                lang,
            )

    sheets, cached = await cached_fetch(
        f"telecom_prices:sheets:{resource.get('id')}:{key}", constants.FILE_TTL_SECONDS, fetch
    )
    return sheets, package, resource, cached and package_cached


def _as_of(released: date | None, resource: dict[str, Any]) -> datetime | None:
    if released is not None:
        return datetime(released.year, released.month, released.day, tzinfo=UTC)
    stamp = str(resource.get("last_modified") or resource.get("created") or "")
    try:
        return datetime.fromisoformat(stamp).replace(tzinfo=UTC) if stamp else None
    except ValueError:
        return None


def _provenance(
    url: str,
    cached: bool,
    schema: str,
    lang: str,
    *,
    as_of: datetime | None,
    freshness: str,
    coverage: str | None = None,
    limits: str | None = None,
) -> Any:
    return make_provenance(
        source=constants.SOURCE,
        url=url,
        cached=cached,
        schema_name=f"telecom_prices.{schema}",
        as_of=as_of,
        freshness=freshness,
        coverage=coverage,
        limits=limits,
        lang=lang,
    )


def _dataset_url(workbook: constants.Workbook, lang: str) -> str:
    return constants.DATASET_PAGE.format(lang=lang, dataset_id=workbook.dataset_id)


def _check_limit(limit: int, lang: str) -> None:
    if not 1 <= limit <= constants.ROWS_MAX_LIMIT:
        _raise(
            InvalidInput,
            f"telecom_prices: limit must be 1 to {constants.ROWS_MAX_LIMIT}.",
            f"telecom_prices : limit doit être compris entre 1 et {constants.ROWS_MAX_LIMIT}.",
            lang,
        )


def _check_years(start: int | None, end: int | None, lang: str) -> None:
    if start is not None and end is not None and start > end:
        _raise(
            InvalidInput,
            f"telecom_prices: from_year ({start}) is after to_year ({end}).",
            f"telecom_prices : from_year ({start}) est postérieure à to_year ({end}).",
            lang,
        )


# Plan prices -----------------------------------------------------------------

_GEOGRAPHY_ALIASES = {
    "canada": "Canada",
    "ca": "Canada",
    "national": "Canada",
    "provinces": "Provinces",
    "territories": "Territories",
    "territoires": "Territories",
    "north": "North",
    "nord": "North",
    "south": "South",
    "sud": "South",
}


def _geography(value: str, lang: str) -> str:
    wanted = " ".join(value.split())
    if wanted.upper() in constants.PROVINCES:
        return wanted.upper()
    folded = parsing.text(wanted).casefold()
    if folded in _GEOGRAPHY_ALIASES:
        return _GEOGRAPHY_ALIASES[folded]
    for code, names in constants.PROVINCES.items():
        if folded in (names[0].casefold(), names[1].casefold()):
            return code
    _raise(
        InvalidInput,
        f"telecom_prices: unknown province {value!r}; use a code like ON, 'Canada', "
        "'Provinces', 'Territories', 'North' or 'South'.",
        f"telecom_prices : province inconnue {value!r} ; utilisez un code comme ON, "
        "'Canada', 'Provinces', 'Territories', 'North' ou 'South'.",
        lang,
    )


def plan_key(value: str) -> str:
    """'5GB', '5 Go', '5' and '5 gb' are one plan; 'talk', 'voix' the talk-only plan."""
    folded = parsing.text(value).casefold().replace(",", "")
    if any(word in folded for word in ("talk", "voice", "voix")):
        return "talk"
    digits = "".join(ch for ch in folded if ch.isdigit() or ch in "/.")
    return digits or folded


_METHOD = (
    "Each year the CRTC asks providers for the lowest non-promotional monthly price, before "
    "taxes and fees, that meets each service basket (a minimum data allowance, minutes and "
    "texts for mobile, bring your own device; a speed tier for Internet) in 24 urban centres "
    "and 55 rural communities. Provincial averages are simple averages over communities; the "
    "national average is the mean of the urban and rural averages. Baskets changed: before "
    "2019 the 1 GB plan required 450 minutes and 300 texts, and plans of 10 GB or more were "
    "added from 2019."
)
_METHOD_FR = (
    "Chaque année, le CRTC demande aux fournisseurs le prix mensuel non promotionnel le plus "
    "bas, avant taxes et frais, qui répond à chaque ensemble de services (une quantité "
    "minimale de données, de minutes et de textos pour le mobile, avec votre propre "
    "appareil; une vitesse pour Internet) dans 24 centres urbains et 55 collectivités "
    "rurales. Les moyennes provinciales sont des moyennes simples des collectivités; la "
    "moyenne nationale est la moyenne des moyennes urbaine et rurale. Les ensembles ont "
    "changé : avant 2019, le forfait de 1 Go exigeait 450 minutes et 300 textos, et les "
    "forfaits de 10 Go et plus ont été ajoutés à partir de 2019."
)


async def get_plan_prices(
    service: str = "mobile",
    *,
    plan: str | None = None,
    province: str = "Canada",
    region: str = "national",
    technology: str = "lowest",
    from_year: int | None = None,
    to_year: int | None = None,
    limit: int = constants.ROWS_DEFAULT_LIMIT,
    lang: str = "en",
) -> PlanPrices:
    """Year-end average advertised prices of mobile or Internet plans."""
    lang = normalize_lang(lang)
    _check_limit(limit, lang)
    _check_years(from_year, to_year, lang)
    if service not in constants.PRICE_SHEETS:
        _raise(
            InvalidInput,
            "telecom_prices: service must be 'mobile' or 'internet'.",
            "telecom_prices : service doit être 'mobile' ou 'internet'.",
            lang,
        )
    if region not in ("national", "urban", "rural", "all"):
        _raise(
            InvalidInput,
            "telecom_prices: region must be 'national', 'urban', 'rural' or 'all'.",
            "telecom_prices : region doit être 'national', 'urban', 'rural' ou 'all'.",
            lang,
        )
    tech = technology.strip().lower()
    if service == "mobile" and tech not in ("lowest", "3g", "lte", "5g", "all"):
        _raise(
            InvalidInput,
            "telecom_prices: technology must be 'lowest', '3G', 'LTE', '5G' or 'all'.",
            "telecom_prices : technology doit être 'lowest', '3G', 'LTE', '5G' ou 'all'.",
            lang,
        )
    geography = None if province.strip().lower() == "all" else _geography(province, lang)
    sheet = constants.PRICE_SHEETS[service]
    sheets, _, resource, cached = await _workbook(
        constants.PRICES, lang, lambda n: n in (sheet, "Version"), service
    )
    if sheet not in sheets:
        _raise(
            UpstreamError,
            f"telecom_prices: the price workbook has no {sheet!r} sheet.",
            f"telecom_prices : le classeur des prix n'a pas de feuille {sheet!r}.",
            lang,
        )
    try:
        rows = await run_parse(parsing.parse_prices, sheets[sheet], service)
    except ValueError as exc:
        _raise(
            UpstreamError,
            f"telecom_prices: {exc}.",
            f"telecom_prices : la feuille des prix n'a pas la forme attendue ({exc}).",
            lang,
        )
    version, released = parsing.parse_version(sheets.get("Version", []))
    plans_en = sorted({r.plan_en for r in rows}, key=_plan_order)
    wanted_plan = plan_key(plan) if plan else None
    if wanted_plan and wanted_plan not in {plan_key(p) for p in plans_en}:
        _raise(
            NotFound,
            f"telecom_prices: no {service} plan {plan!r}; plans are {plans_en}.",
            f"telecom_prices : aucun forfait {service} {plan!r} ; les forfaits sont {plans_en}.",
            lang,
        )
    matched = [
        r
        for r in rows
        if (wanted_plan is None or plan_key(r.plan_en) == wanted_plan)
        and (geography is None or r.geography == geography)
        and (region == "all" or r.region == region)
        and (service != "mobile" or tech == "all" or (r.technology or "").lower() == tech)
        and (from_year is None or r.year >= from_year)
        and (to_year is None or r.year <= to_year)
    ]
    matched.sort(key=lambda r: (_plan_order(r.plan_en), r.geography, r.region, r.year))
    points = [
        PlanPricePoint(
            year=r.year,
            plan=r.plan_fr if lang == "fr" else r.plan_en,
            geography=r.geography,
            region=r.region,  # type: ignore[arg-type]
            technology=r.technology,
            average_price=r.value,
            as_published=r.as_published,
        )
        for r in matched[:limit]
    ]
    years = sorted({r.year for r in rows})
    cut = len(matched) - len(points)
    return PlanPrices(
        service=service,  # type: ignore[arg-type]
        dataset=_text(constants.PRICES.title_en, constants.PRICES.title_fr, lang),
        dataset_url=_dataset_url(constants.PRICES, lang),
        version=version,
        released=released,
        points=points,
        returned_count=len(points),
        total_matched=len(matched),
        plans=[(_plan_fr_label(p) if lang == "fr" else p) for p in plans_en],
        years=years,
        method=_text(_METHOD, _METHOD_FR, lang),
        provenance=_provenance(
            str(resource.get("url") or ""),
            cached,
            "PlanPrices",
            lang,
            as_of=_as_of(released, resource),
            freshness=_text(
                "yearly: prices at December 31, published the following spring",
                "annuelle : prix au 31 décembre, publiés le printemps suivant",
                lang,
            ),
            coverage=_text(
                f"{len(rows):,} {service} averages, {years[0]}-{years[-1]}" if years else "no rows",
                f"{len(rows):,} moyennes ({service}), {years[0]}-{years[-1]}"
                if years
                else "aucune ligne",
                lang,
            ),
            limits=join_limits(
                _text(
                    f"first {len(points)} of {len(matched)} matching averages; narrow the "
                    "filters or raise limit",
                    f"{len(points)} premières moyennes sur {len(matched)} ; précisez les "
                    "filtres ou augmentez limit",
                    lang,
                )
                if cut
                else None,
                _text(
                    "Averages of advertised list prices, not what subscribers pay: no "
                    "promotions, bundles or taxes.",
                    "Moyennes de prix annoncés, et non de ce que paient les abonnés : sans "
                    "promotions, offres groupées ni taxes.",
                    lang,
                ),
            ),
        ),
    )


def _plan_order(plan: str) -> tuple[int, float, str]:
    digits = plan_key(plan).split("/")[0]
    try:
        return (1, float(digits), plan)
    except ValueError:
        return (0, 0.0, plan)


def _plan_fr_label(plan_en: str) -> str:
    if plan_en.lower() == "talk plan":
        return "Forfait voix"
    return plan_en.replace(" GB", " Go")


# Sector tables -----------------------------------------------------------------


def _sector(sector: str, lang: str) -> constants.Workbook:
    if sector not in constants.SECTORS:
        _raise(
            InvalidInput,
            "telecom_prices: sector must be 'mobile' or 'internet'.",
            "telecom_prices : sector doit être 'mobile' ou 'internet'.",
            lang,
        )
    return constants.SECTORS[sector]


_SECTOR_FRESHNESS = (
    "yearly: the Communications Market Report for year N comes out late in year N+1",
    (
        "annuelle : le Rapport sur le marché des communications de l'année N paraît à la "
        "fin de l'année N+1"
    ),
)


async def list_market_tables(sector: str = "mobile", *, lang: str = "en") -> MarketTableList:
    lang = normalize_lang(lang)
    workbook = _sector(sector, lang)
    sheets, package, resource, cached = await _workbook(
        workbook, lang, lambda n: n.lower().startswith(("table of contents", "table des")), "toc"
    )
    names = list(sheets[""][0])
    contents = next((rows for name, rows in sheets.items() if name), [])
    tables = parsing.parse_contents(contents, names)
    return MarketTableList(
        sector=sector,  # type: ignore[arg-type]
        dataset=_title(package, workbook, lang),
        dataset_url=_dataset_url(workbook, lang),
        tables=[
            MarketTableRef(table_id=t.table_id, label=t.label, kind=t.kind, title=t.title)  # type: ignore[arg-type]
            for t in tables
        ],
        provenance=_provenance(
            str(resource.get("url") or ""),
            cached,
            "MarketTableList",
            lang,
            as_of=_as_of(None, resource),
            freshness=_text(*_SECTOR_FRESHNESS, lang),
        ),
    )


async def get_market_table(
    table: str,
    sector: str = "mobile",
    *,
    series: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    lang: str = "en",
) -> MarketTable:
    lang = normalize_lang(lang)
    _check_years(from_year, to_year, lang)
    workbook = _sector(sector, lang)
    if not table.strip():
        _raise(
            InvalidInput,
            "telecom_prices: table must name a tab such as 'MB-S3' "
            "(see telecom_list_market_tables).",
            "telecom_prices : table doit nommer un onglet comme 'MB-S3' "
            "(voir telecom_list_market_tables).",
            lang,
        )
    aliases = parsing.sheet_aliases(table)
    sheets, package, resource, cached = await _workbook(
        workbook, lang, lambda n: n.upper() in aliases, "table:" + aliases[0]
    )
    found = next((name for name in sheets if name and name.upper() in aliases), None)
    if found is None:
        tabs = [n for n in sheets[""][0] if parsing.is_table_sheet(n)]
        _raise(
            NotFound,
            f"telecom_prices: no tab {table!r} in the {sector} workbook; tabs are {tabs}.",
            f"telecom_prices : aucun onglet {table!r} dans le classeur {sector} ; les onglets "
            f"sont {tabs}.",
            lang,
        )
    parsed = await run_parse(parsing.parse_table, sheets[found])
    if not parsed.observations:
        _raise(
            NotFound,
            f"telecom_prices: tab {found!r} has no table of years to read.",
            f"telecom_prices : l'onglet {found!r} ne contient aucun tableau par année.",
            lang,
        )
    words = parsing.text(series).casefold().split() if series else []
    kept = [
        o
        for o in parsed.observations
        if all(w in f"{o.block or ''} {o.series}".casefold() for w in words)
        and (from_year is None or o.year >= from_year)
        and (to_year is None or o.year <= to_year)
    ]
    mobile_only = any(o.mobile_phone_only for o in kept)
    return MarketTable(
        sector=sector,  # type: ignore[arg-type]
        table_id=found,
        label=parsed.label,
        title=parsed.title,
        dataset=_title(package, workbook, lang),
        dataset_url=_dataset_url(workbook, lang),
        observations=[MarketObservation(**o.__dict__) for o in kept],
        series=list(dict.fromkeys(o.series for o in parsed.observations)),
        notes=parsed.notes,
        derived_columns_left_out=parsed.derived_columns,
        provenance=_provenance(
            str(resource.get("url") or ""),
            cached,
            "MarketTable",
            lang,
            as_of=_as_of(None, resource),
            freshness=_text(*_SECTOR_FRESHNESS, lang),
            coverage=_text(
                f"{len(kept)} of {len(parsed.observations)} values in tab {found}",
                f"{len(kept)} valeurs sur {len(parsed.observations)} dans l'onglet {found}",
                lang,
            ),
            limits=join_limits(
                _text(
                    "Years marked mobile_phone_only (2020 on) count mobile phone services "
                    "only and do not compare with earlier years.",
                    "Les années marquées mobile_phone_only (2020 et après) ne comptent que "
                    "les services de téléphonie mobile et ne se comparent pas aux années "
                    "antérieures.",
                    lang,
                )
                if mobile_only
                else None,
                _text(
                    "Shares are stored as fractions in most tabs (0.283 is 28.3%).",
                    "Les parts sont le plus souvent des fractions (0,283 vaut 28,3 %).",
                    lang,
                )
                if any(o.value is not None and 0 < abs(o.value) < 1 for o in kept)
                else None,
            ),
        ),
    )


# Quarterly trends -----------------------------------------------------------------


_MARKETS = {"combined": "Combined", "residential": "Residential", "business": "Business"}


async def get_quarterly_trends(
    service: str = "mobile",
    *,
    metric: str | None = None,
    market: str = "all",
    measure: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    limit: int = constants.ROWS_DEFAULT_LIMIT,
    lang: str = "en",
) -> QuarterlyTrends:
    lang = normalize_lang(lang)
    _check_limit(limit, lang)
    _check_years(from_year, to_year, lang)
    if service not in constants.TREND_SHEETS:
        _raise(
            InvalidInput,
            "telecom_prices: service must be 'mobile', 'internet', 'wireline' or "
            "'tv_distribution'.",
            "telecom_prices : service doit être 'mobile', 'internet', 'wireline' ou "
            "'tv_distribution'.",
            lang,
        )
    if market not in (*_MARKETS, "all"):
        _raise(
            InvalidInput,
            "telecom_prices: market must be 'combined', 'residential', 'business' or 'all'.",
            "telecom_prices : market doit être 'combined', 'residential', 'business' ou 'all'.",
            lang,
        )
    sheet = constants.TREND_SHEETS[service]
    sheets, _, resource, cached = await _workbook(
        constants.TRENDS, lang, lambda n: n in (sheet, "Version"), "trends:" + service
    )
    if sheet not in sheets:
        _raise(
            UpstreamError,
            f"telecom_prices: the quarterly workbook has no {sheet!r} sheet.",
            f"telecom_prices : le classeur trimestriel n'a pas de feuille {sheet!r}.",
            lang,
        )
    try:
        rows = await run_parse(parsing.parse_trends, sheets[sheet])
    except ValueError as exc:
        _raise(
            UpstreamError,
            f"telecom_prices: {exc}.",
            f"telecom_prices : la feuille trimestrielle n'a pas la forme attendue ({exc}).",
            lang,
        )
    version, released = parsing.parse_version(sheets.get("Version", []))
    metric_words = parsing.text(metric).casefold().split() if metric else []
    measure_words = parsing.text(measure).casefold().split() if measure else []

    def has(words: list[str], *texts: str | None) -> bool:
        joined = " ".join(t or "" for t in texts).casefold()
        return all(w in joined for w in words)

    matched = [
        r
        for r in rows
        if has(metric_words, r.metric_en, r.metric_fr, r.subcategory_en, r.subcategory_fr)
        and has(measure_words, r.measure_en, r.measure_fr)
        and (market == "all" or r.market_en is None or r.market_en == _MARKETS[market])
        and (from_year is None or r.year >= from_year)
        and (to_year is None or r.year <= to_year)
    ]
    observations = [
        TrendObservation(
            period=f"{r.year}-Q{r.quarter}",
            year=r.year,
            quarter=r.quarter,
            market=r.market_fr if lang == "fr" else r.market_en,
            metric=r.metric_fr if lang == "fr" else r.metric_en,
            subcategory=r.subcategory_fr if lang == "fr" else r.subcategory_en,
            measure=r.measure_fr if lang == "fr" else r.measure_en,
            value=r.value,
        )
        for r in matched[:limit]
    ]
    metrics = sorted({(r.metric_fr if lang == "fr" else r.metric_en) for r in rows})
    quarters = sorted({(r.year, r.quarter) for r in rows})
    cut = len(matched) - len(observations)
    return QuarterlyTrends(
        service=service,  # type: ignore[arg-type]
        dataset=_text(constants.TRENDS.title_en, constants.TRENDS.title_fr, lang),
        dataset_url=_dataset_url(constants.TRENDS, lang),
        version=version,
        released=released,
        observations=observations,
        returned_count=len(observations),
        total_matched=len(matched),
        metrics=metrics,
        provenance=_provenance(
            str(resource.get("url") or ""),
            cached,
            "QuarterlyTrends",
            lang,
            as_of=_as_of(released, resource),
            freshness=_text(
                "quarterly, about five months after the quarter ends; past quarters are revised",
                "trimestrielle, environ cinq mois après la fin du trimestre; les trimestres "
                "passés sont révisés",
                lang,
            ),
            coverage=_text(
                f"{quarters[0][0]}-Q{quarters[0][1]} to {quarters[-1][0]}-Q{quarters[-1][1]}"
                if quarters
                else "no rows",
                f"{quarters[0][0]}-T{quarters[0][1]} à {quarters[-1][0]}-T{quarters[-1][1]}"
                if quarters
                else "aucune ligne",
                lang,
            ),
            limits=join_limits(
                _text(
                    f"first {len(observations)} of {len(matched)} matching values; narrow "
                    "metric, market or years, or raise limit",
                    f"{len(observations)} premières valeurs sur {len(matched)} ; précisez "
                    "metric, market ou les années, ou augmentez limit",
                    lang,
                )
                if cut
                else None,
                # Stated in the dataset's own description on open.canada.ca.
                _text(
                    "The quarterly survey (with Statistics Canada) covers the entities with "
                    "the top 90% of revenues, so totals run below the annual sector tables "
                    "(telecom_get_market_table).",
                    "L'enquête trimestrielle (avec Statistique Canada) couvre les entités qui "
                    "font 90 % des revenus : les totaux sont inférieurs à ceux des tableaux "
                    "annuels (telecom_get_market_table).",
                    lang,
                ),
            ),
        ),
    )
