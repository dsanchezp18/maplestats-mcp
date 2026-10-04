"""HTTP client for the Alberta Economic Dashboard data API.

See constants.py for the routes and quirks confirmed live. Table names
are checked against the live table list before use, so a caller-supplied
name can never reach a URL path unvalidated.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, NoReturn
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.ab_economic import constants
from maplestats_mcp.modules.ab_economic.schemas import (
    ColumnInfo,
    Indicator,
    IndicatorList,
    IndicatorSeries,
    PublishedSeries,
    TableData,
    TableFields,
    TableInfo,
    TableList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.limits import fit_to_budget, join_limits, truncation_note
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_PID = re.compile(r"_(\d{8,10})$")
# Column names can hold spaces: 21 of the 147 published series filter on
# columns such as "NAICS Description" (live 2026-10-03), which the API
# accepts URL-encoded.
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")


def _raise_for(exc: httpx.HTTPStatusError, context: str, lang: str = "en") -> NoReturn:
    status = exc.response.status_code
    detail = exc.response.text[:200].strip()
    if status == 404:
        raise_localized(NotFound, f"{context}: not found.", f"{context} : introuvable.", lang)
    if status == 400:
        raise_localized(
            InvalidInput,
            f"{context}: {detail or 'rejected the request'}.",
            f"{context} : {detail or 'requête refusée'}.",
            lang,
        )
    raise_localized(
        UpstreamError,
        f"{context} returned HTTP {status}: {detail}",
        f"{context} a répondu par une erreur HTTP {status} : {detail}",
        lang,
    )


async def _get(path: str, params: dict[str, Any] | None = None, lang: str = "en") -> Any:
    await _LIMITER.acquire()
    context = f"ab_economic:{path.split('?')[0]}"
    try:
        return await api_get(f"{constants.BASE_URL}/{path}", params=params, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        _raise_for(exc, context, lang)
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            f"{context} did not respond in time. Try again shortly.",
            f"{context} n'a pas répondu à temps. Réessayez sous peu.",
            lang,
        )


async def _table_names(lang: str = "en") -> tuple[list[str], bool]:
    async def fetch() -> Any:
        return await _get("api/chart-editor/data-tables", lang=lang)

    raw, cached = await cached_fetch(
        "ab-economic:tables", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
    )
    return [t["tableName"] for t in raw if t.get("tableName")], cached


async def _resolve_table(table: str, lang: str = "en") -> str:
    names, _ = await _table_names(lang)
    by_lower = {n.lower(): n for n in names}
    match = by_lower.get(table.strip().lower())
    if match is None:
        raise_localized(
            NotFound,
            f"No Alberta Economic Dashboard table {table!r}. Use ab_economic_list_tables.",
            f"aucun tableau {table!r} dans le tableau de bord économique de l'Alberta "
            "(Alberta Economic Dashboard). Utilisez ab_economic_list_tables.",
            lang,
        )
    return match


def _pid(table: str) -> str | None:
    found = _PID.search(table)
    return found.group(1) if found else None


async def list_tables(query: str | None = None, lang: str = "en") -> TableList:
    names, cached = await _table_names(lang)
    needle = (query or "").strip().lower()
    matches = [n for n in names if not needle or needle in n.lower() or needle == _pid(n)]
    return TableList(
        tables=[TableInfo(table=n, statcan_pid=_pid(n)) for n in matches],
        total_count=len(matches),
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/api/chart-editor/data-tables",
            cached=cached,
            schema_name="ab_economic.TableList",
            freshness=pick(
                lang,
                "table list cached 24h",
                "liste des tableaux conservée en cache 24 h",
            ),
            coverage=pick(
                lang,
                "",
                "Noms de tableaux, de colonnes et d'indicateurs tels que publiés par le tableau de bord, en anglais seulement.",
            )
            or None,
            lang=lang,
        ),
    )


async def get_table_fields(table: str, lang: str = "en") -> TableFields:
    name = await _resolve_table(table, lang)

    async def fetch_fields() -> Any:
        return await _get(f"api/chart-editor/field-info/{name}", lang=lang)

    async def fetch_info() -> Any:
        return await _get(f"api/chart-editor/indicator-info/{name}", lang=lang)

    fields, cached = await cached_fetch(
        f"ab-economic:fields:{name}", constants.CACHE_TTL_FIELDS_SECONDS, fetch_fields
    )
    info, _ = await cached_fetch(
        f"ab-economic:info:{name}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch_info
    )
    columns = []
    for col in fields:
        values = [str(v) for v in col.get("values") or []]
        columns.append(
            ColumnInfo(
                name=col["columnName"],
                data_type=col.get("dataType") or "unknown",
                distinct_count=len(values),
                values=values[: constants.FIELD_VALUES_MAX],
                values_truncated=len(values) > constants.FIELD_VALUES_MAX,
            )
        )
    info = info if isinstance(info, dict) else {}
    return TableFields(
        table=name,
        # Upstream misspells this key.
        indicator_name=info.get("indicaorName") or info.get("indicatorName"),
        period=info.get("period"),
        columns=columns,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/api/chart-editor/field-info/{name}",
            cached=cached,
            schema_name="ab_economic.TableFields",
            coverage=pick(
                lang,
                "",
                "Noms de tableaux, de colonnes et d'indicateurs tels que publiés par le tableau de bord, en anglais seulement.",
            )
            or None,
            lang=lang,
        ),
    )


def _parse_date(value: str | None, name: str, lang: str = "en") -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise_localized(
            InvalidInput,
            f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}.",
            f"{name} doit être une date ISO (AAAA-MM-JJ) (reçu {value!r}).",
            lang,
        )


def _row_date(row: dict[str, Any]) -> datetime | None:
    raw = row.get("Date")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def get_data(
    table: str,
    filters: dict[str, str] | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> TableData:
    """Rows of one table, filtered upstream by column values.

    Date bounds are inclusive and applied client-side; the most recent
    `limit` matching rows are returned, oldest first.
    """
    if limit < 1 or limit > constants.ROWS_MAX:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {constants.ROWS_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.ROWS_MAX} (reçu {limit}).",
            lang,
        )
    filters = dict(filters or {})
    for column in filters:
        if not _COLUMN.match(column):
            raise_localized(
                InvalidInput,
                f"Filter column {column!r} is not a valid column name.",
                f"la colonne de filtre {column!r} n'est pas un nom de colonne valide.",
                lang,
            )
    start = _parse_date(start_date, "start_date", lang)
    end = _parse_date(end_date, "end_date", lang)
    if start and end and start > end:
        raise_localized(
            InvalidInput,
            f"start_date {start} is after end_date {end}.",
            f"start_date {start} est postérieure à end_date {end}.",
            lang,
        )
    name = await _resolve_table(table, lang)
    params = {"table": name, **filters}

    async def fetch() -> Any:
        return await _get("data", params, lang)

    rows, cached = await cached_fetch(
        f"ab-economic:data:{sorted(params.items())}", constants.CACHE_TTL_DATA_SECONDS, fetch
    )
    if not isinstance(rows, list):
        raise_localized(
            UpstreamError,
            f"ab_economic:data returned {type(rows).__name__}, expected a list.",
            f"ab_economic:data a renvoyé un objet {type(rows).__name__} au lieu d'une liste.",
            lang,
        )

    def in_range(row: dict[str, Any]) -> bool:
        when = _row_date(row)
        if when is None:
            return not (start or end)
        return (not start or when.date() >= start) and (not end or when.date() <= end)

    matching = sorted((r for r in rows if in_range(r)), key=lambda r: str(r.get("Date") or ""))
    # Newest rows first into the byte budget, then back to oldest first.
    kept = fit_to_budget(matching[-limit:][::-1])[::-1]
    dates = [d for r in kept if (d := _row_date(r))]
    return TableData(
        table=name,
        filters=filters,
        rows=kept,
        total_rows=len(matching),
        returned_count=len(kept),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=str(httpx.URL(f"{constants.BASE_URL}/data", params=params)),
            cached=cached,
            schema_name="ab_economic.TableData",
            coverage=pick(
                lang,
                f"{len(kept)} most recent of {len(matching)} matching rows",
                f"les {len(kept)} lignes les plus récentes sur {len(matching)} correspondantes ; "
                "noms de colonnes et valeurs textuelles en anglais, comme à la source",
            ),
            limits=join_limits(
                truncation_note(
                    returned=len(kept),
                    total=len(matching),
                    unit="matching rows",
                    order="latest",
                    how_to_get_more="filter to one series, set start_date/end_date, or raise "
                    f"limit (max {constants.ROWS_MAX}; responses are capped near 200 KB)",
                )
                if lang != "fr"
                else (
                    f"{len(kept)} lignes renvoyées sur {len(matching)}, les plus récentes ; "
                    "pour en obtenir d'autres, filtrez sur une seule série, indiquez "
                    f"start_date/end_date ou augmentez limit (max. {constants.ROWS_MAX} ; "
                    "réponses plafonnées vers 200 Ko)"
                    if len(kept) < len(matching)
                    else None
                ),
                pick(
                    lang,
                    "dates are filtered here, after the upstream returns the filtered table",
                    "les dates sont filtrées ici, après que la source a renvoyé le tableau filtré",
                )
                if start or end
                else None,
            ),
            lang=lang,
        ),
    )


def _slug(name: str) -> str:
    override = constants.SLUG_OVERRIDES.get(name)
    return override or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _page_url(name: str) -> str:
    return constants.INDICATOR_PAGE_URL.format(slug=_slug(name))


def _parse_api_links(html: str) -> list[PublishedSeries]:
    """Every `data?table=...` link on an indicator page, deduplicated."""
    soup = BeautifulSoup(html, "html.parser")
    series: list[PublishedSeries] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        parsed = urlparse(href)
        if parsed.netloc != urlparse(constants.BASE_URL).netloc or parsed.path != "/data":
            continue
        params = dict(parse_qsl(parsed.query))
        table = params.pop("table", None)
        if not table or href in seen:
            continue
        seen.add(href)
        series.append(
            PublishedSeries(
                name=" ".join(link.get_text().split()) or table,
                table=table,
                filters=params,
                api_url=href,
            )
        )
    return series


async def get_indicator_series(indicator: str, lang: str = "en") -> IndicatorSeries:
    """The published API links behind one Key Indicators page."""
    catalogue = await list_indicators(lang)
    wanted = indicator.strip().lower()
    match = next(
        (i for i in catalogue.indicators if wanted in (i.name.lower(), _slug(i.name))),
        None,
    )
    name = match.name if match else indicator.strip()
    url = match.page_url if match else _page_url(name)
    if not name:
        raise_localized(
            InvalidInput,
            "indicator must not be empty.",
            "indicator ne doit pas être vide.",
            lang,
        )

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            try:
                response = await get_raw(url, timeout=60.0)
            except httpx.HTTPStatusError as exc:
                # A renamed page answers 301 to its new address (wells-drilled
                # moved to new-wells-drilled); follow one same-site redirect.
                target = exc.response.headers.get("location", "")
                moved = urljoin(url, target)
                if exc.response.status_code not in (301, 302, 308) or (
                    urlparse(moved).netloc != urlparse(url).netloc
                ):
                    raise
                await _LIMITER.acquire()
                response = await get_raw(moved, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise_localized(
                    NotFound,
                    f"No Alberta Economic Dashboard page for {indicator!r}. "
                    "Use ab_economic_list_indicators.",
                    f"aucune page du tableau de bord économique de l'Alberta pour {indicator!r}. "
                    "Utilisez ab_economic_list_indicators.",
                    lang,
                )
            raise_localized(
                UpstreamError,
                f"ab_economic: {url} returned HTTP {status}.",
                f"ab_economic : {url} a répondu par une erreur HTTP {status}.",
                lang,
            )
        except httpx.HTTPError:
            raise_localized(
                UpstreamUnavailable,
                f"ab_economic: {url} did not respond in time.",
                f"ab_economic : {url} n'a pas répondu à temps.",
                lang,
            )
        return response.text

    html, cached = await cached_fetch(
        f"ab-economic:page:{url}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
    )
    series = _parse_api_links(html)
    note = None
    fallback = constants.TABLE_FALLBACKS.get(name)
    if not series and fallback:
        table, column, values = fallback
        series = [
            PublishedSeries(
                name=f"{name}: {value}",
                table=table,
                filters={column: value},
                api_url=f"{constants.BASE_URL}/data?{urlencode({'table': table, column: value})}",
            )
            for value in values
        ]
        note = pick(
            lang,
            f"The {name!r} page lists no API links; these series come from the data API "
            f"table {table!r} that holds the chart's figures.",
            f"La page {name!r} ne liste aucun lien d'API ; ces séries viennent du tableau "
            f"{table!r} de l'API de données, qui contient les chiffres du graphique.",
        )
    if not series:
        raise_localized(
            NotFound,
            f"The {name!r} page publishes no API links; use ab_economic_list_tables instead.",
            f"la page {name!r} ne publie aucun lien d'API ; utilisez plutôt "
            "ab_economic_list_tables.",
            lang,
        )
    return IndicatorSeries(
        indicator=name,
        page_url=url,
        series=series,
        note=note,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="ab_economic.IndicatorSeries",
            coverage=pick(
                lang,
                "",
                "Noms de tableaux, de colonnes et d'indicateurs tels que publiés par le tableau de bord, en anglais seulement.",
            )
            or None,
            lang=lang,
        ),
    )


async def list_indicators(lang: str = "en") -> IndicatorList:
    async def fetch() -> Any:
        return await _get(f"api/tile-data/dashboard/{constants.KEY_INDICATORS_CODE}", lang=lang)

    body, cached = await cached_fetch(
        "ab-economic:indicators", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
    )
    topics = body.get("data") or []
    indicators = [
        Indicator(
            name=ind["name"],
            topic=topic["name"],
            updated_at=datetime.fromisoformat(ind["updatedAt"]) if ind.get("updatedAt") else None,
            page_url=_page_url(ind["name"]),
        )
        for topic in topics
        for ind in topic.get("indicators") or []
    ]
    return IndicatorList(
        indicators=indicators,
        topics=[t["name"] for t in topics],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.DASHBOARD_URL,
            cached=cached,
            schema_name="ab_economic.IndicatorList",
            freshness=pick(lang, "catalogue cached 24h", "catalogue conservé en cache 24 h"),
            coverage=pick(
                lang,
                "",
                "Noms de tableaux, de colonnes et d'indicateurs tels que publiés par le tableau de bord, en anglais seulement.",
            )
            or None,
            lang=lang,
        ),
    )
