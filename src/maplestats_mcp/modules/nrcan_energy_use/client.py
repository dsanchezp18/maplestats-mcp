"""HTTP client for NRCan's National Energy Use Database (OEE) pages.

Menus and tables are server-rendered HTML with no JSON alternative, so
both are parsed with BeautifulSoup. A table is addressed by a
`table_key`: the whitelisted `showTable.cfm` query string, which works
unchanged against the English and French roots.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import NoReturn
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.nrcan_energy_use import constants
from maplestats_mcp.modules.nrcan_energy_use.schemas import (
    ComprehensiveMenu,
    EnergyTable,
    Product,
    ProductList,
    TableList,
    TableRef,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import ERROR_KEYS, french_spacing, t
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_VALUE = re.compile(r"^[A-Za-z0-9]{1,12}$")
_MENU = re.compile(r"trends_([a-z]+)_([a-z]+)\.cfm")


# Monotonic time until which the host is treated as down. When the host
# cannot be reached, a request used to spend about 67 s in connection
# retries; after one failed connect or request, calls fail at once for a
# few minutes.
_down_until = 0.0


def _error(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> ValueError:
    """The error to raise: English as before, French in the typed template."""
    if lang == "fr":
        return exc_cls(t(ERROR_KEYS[exc_cls.__name__], "fr", detail=fr))
    return exc_cls(en)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _pick(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


def _unreachable(url: str, lang: str = "en") -> ValueError:
    return _error(
        UpstreamUnavailable,
        f"nrcan_energy_use: oee.nrcan.gc.ca could not be reached ({url}); retry in a few "
        "minutes. The survey list (nrcan_energy_use_list_products) does not need the host.",
        f"nrcan_energy_use : oee.nrcan.gc.ca est injoignable ({url}) ; réessayez dans "
        "quelques minutes. La liste des enquêtes (nrcan_energy_use_list_products) n'a pas "
        "besoin du site.",
        lang,
    )


async def _check_reachable(lang: str = "en") -> None:
    """Fail fast when the host does not accept a TCP connection."""
    global _down_until
    if time.monotonic() < _down_until:
        _raise(
            UpstreamUnavailable,
            f"nrcan_energy_use: {constants.HOST} is not accepting connections; try again later.",
            f"nrcan_energy_use : {constants.HOST} n'accepte pas les connexions ; réessayez "
            "plus tard.",
            lang,
        )
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(constants.HOST, 443), constants.CONNECT_TIMEOUT_SECONDS
        )
    except (TimeoutError, OSError) as exc:
        _down_until = time.monotonic() + constants.DOWN_RETRY_SECONDS
        raise _error(
            UpstreamUnavailable,
            f"nrcan_energy_use: {constants.HOST} did not accept a connection within "
            f"{constants.CONNECT_TIMEOUT_SECONDS:g} s; try again later.",
            f"nrcan_energy_use : {constants.HOST} n'a pas accepté de connexion en "
            f"{constants.CONNECT_TIMEOUT_SECONDS:g} s ; réessayez plus tard.",
            lang,
        ) from exc
    writer.close()


async def _html(url: str, ttl: int, lang: str = "en") -> tuple[str, bool]:
    async def fetch() -> str:
        global _down_until
        if time.monotonic() < _down_until:
            raise _unreachable(url, lang)
        await _check_reachable(lang)
        await _LIMITER.acquire()
        try:
            # The whole retry chain gets one budget, so an unreachable host
            # fails in seconds rather than after every retry has timed out.
            response = await asyncio.wait_for(
                get_raw(url, timeout=constants.REQUEST_TIMEOUT_SECONDS),
                constants.REQUEST_BUDGET_SECONDS,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise _error(
                    NotFound,
                    f"nrcan_energy_use: nothing published at {url}.",
                    f"nrcan_energy_use : rien n'est publié à {url}.",
                    lang,
                ) from exc
            raise _error(
                UpstreamError,
                f"nrcan_energy_use: {url} returned HTTP {status}.",
                f"nrcan_energy_use : {url} a renvoyé HTTP {status}.",
                lang,
            ) from exc
        except (httpx.HTTPError, TimeoutError) as exc:
            _down_until = time.monotonic() + constants.DOWN_RETRY_SECONDS
            raise _unreachable(url, lang) from exc
        return response.text

    return await cached_fetch(f"nrcan-energy-use:{url}", ttl, fetch)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _href(tag: Tag) -> str:
    # html.parser decodes "&sect" in "&sector=" to "§"; restore it.
    return str(tag.get("href") or "").replace("§", "&sect")


def _table_key(href: str) -> str | None:
    parsed = urlparse(href)
    if not parsed.path.endswith("showTable.cfm"):
        return None
    params = {k: v for k, v in parse_qsl(parsed.query) if k in constants.TABLE_PARAMS}
    return urlencode(params) if "type" in params and "rn" in params else None


async def list_products(lang: str = "en") -> ProductList:
    """The 11 survey products (static) and the comprehensive-database menus (live).

    The survey list never needs the host; when it is unreachable the
    comprehensive menus are left empty and limits says so, instead of the
    whole call failing.
    """
    index = 1 if lang == "fr" else 0
    surveys = [Product(product=k, name=v[index]) for k, v in constants.SURVEYS.items()]
    unreachable: str | None = None
    try:
        html, cached = await _html(
            constants.EN_ROOT + constants.COMPREHENSIVE_LIST, constants.CACHE_TTL_MENU_SECONDS, lang
        )
    except UpstreamUnavailable as exc:
        html, cached, unreachable = "", False, str(exc)
    pairs = sorted(set(_MENU.findall(html)))
    menus = [
        ComprehensiveMenu(
            sector=sector,
            sector_name=constants.SECTORS.get(sector, (sector, sector))[index],
            jurisdiction=juris,
            jurisdiction_name=constants.JURISDICTIONS.get(juris, (juris, juris))[index],
        )
        for sector, juris in pairs
    ]
    return ProductList(
        surveys=surveys,
        comprehensive=menus,
        # The survey products are fixed; only the comprehensive menu is read live.
        note=(
            _pick(
                f"The comprehensive tables menu could not be read ({unreachable}); the survey "
                "products are listed, but their tables need the site to answer.",
                f"Le menu des tableaux complets n'a pas pu être lu ({unreachable}) ; les "
                "enquêtes sont listées, mais leurs tableaux exigent que le site réponde.",
                lang,
            )
            if unreachable
            else None
        ),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.EN_ROOT + constants.COMPREHENSIVE_LIST,
            cached=cached,
            schema_name="nrcan_energy_use.ProductList",
            limits=(
                _pick(
                    f"Comprehensive-database menus not loaded: {unreachable} The survey list "
                    "comes from this server's own catalogue.",
                    f"Menus de la base de données complète non chargés : {unreachable} La liste "
                    "des enquêtes vient du catalogue de ce serveur.",
                    lang,
                )
                if unreachable
                else None
            ),
            lang=lang,
        ),
    )


def _parse_menu(html: str) -> list[TableRef]:
    soup = BeautifulSoup(html, "html.parser")
    tables: list[TableRef] = []
    for link in soup.find_all("a", href=True):
        key = _table_key(_href(link))
        if key is None:
            continue
        number = _clean(link.get_text()).rstrip(":")
        cell = link.find_parent("div")
        sibling = cell.find_next_sibling("div") if cell else None
        title = _clean(sibling.get_text()) if sibling else ""
        tables.append(TableRef(table_number=number, title=title or number, table_key=key))
    return tables


async def list_tables(
    product: str, sector: str | None = None, jurisdiction: str | None = None, lang: str = "en"
) -> TableList:
    if product == "comprehensive":
        if not sector or not jurisdiction:
            _raise(
                InvalidInput,
                "product='comprehensive' needs sector and jurisdiction "
                "(see nrcan_energy_use_list_products).",
                "product='comprehensive' exige sector et jurisdiction "
                "(voir nrcan_energy_use_list_products).",
                lang,
            )
        if not (_VALUE.match(sector) and _VALUE.match(jurisdiction)):
            _raise(
                InvalidInput,
                "sector and jurisdiction must be short codes such as 'res', 'ab'.",
                "sector et jurisdiction doivent être des codes courts comme 'res', 'ab'.",
                lang,
            )
        path = constants.COMPREHENSIVE_MENU.format(sector=sector, jurisdiction=jurisdiction)
    elif product in constants.SURVEYS:
        path = constants.SURVEYS[product][2]
    else:
        _raise(
            InvalidInput,
            f"Unknown product {product!r}; use 'comprehensive' or one of "
            f"{sorted(constants.SURVEYS)}.",
            f"produit inconnu {product!r} ; utilisez 'comprehensive' ou l'un de "
            f"{sorted(constants.SURVEYS)}.",
            lang,
        )
    url = constants.EN_ROOT + path
    html, cached = await _html(url, constants.CACHE_TTL_MENU_SECONDS, lang)
    tables = _parse_menu(html)
    if not tables:
        _raise(
            NotFound,
            f"No tables listed at {url}.",
            f"aucun tableau listé à {url}.",
            lang,
        )
    return TableList(
        product=product,
        tables=tables,
        menu_url=url,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="nrcan_energy_use.TableList",
            # The menus are read from the English site; each table's own French
            # version comes from nrcan_energy_use_get_table with lang="fr".
            limits=_pick(
                "",
                "Les titres des tableaux viennent du menu anglais de RNCan ; "
                "nrcan_energy_use_get_table avec lang='fr' renvoie chaque tableau en français.",
                lang,
            )
            or None,
            lang=lang,
        ),
    )


def _validated_key(table_key: str, lang: str = "en") -> str:
    params = dict(parse_qsl(table_key.lstrip("?")))
    unknown = set(params) - set(constants.TABLE_PARAMS)
    if unknown or "type" not in params or "rn" not in params:
        _raise(
            InvalidInput,
            "table_key must be a key from nrcan_energy_use_list_tables, "
            "e.g. 'type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1'.",
            "table_key doit être une clé donnée par nrcan_energy_use_list_tables, "
            "p. ex. 'type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1'.",
            lang,
        )
    if not all(_VALUE.match(v) for v in params.values()):
        _raise(
            InvalidInput,
            "table_key values must be short letter/number codes.",
            "les valeurs de table_key doivent être des codes courts de lettres et de chiffres.",
            lang,
        )
    return urlencode({k: params[k] for k in constants.TABLE_PARAMS if k in params})


def _cells(row: Tag) -> list[str]:
    return [_clean(c.get_text()) for c in row.find_all(["th", "td"], recursive=False)]


def _parse_table(
    html: str, lang: str = "en"
) -> tuple[str, list[list[str]], list[list[str]], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not isinstance(table, Tag):
        _raise(
            NotFound,
            "nrcan_energy_use: the page has no data table.",
            "nrcan_energy_use : la page n'a aucun tableau de données.",
            lang,
        )
    headings = [_clean(h.get_text()) for h in soup.find_all("h1")]
    caption = table.find("caption")
    title = next((h for h in headings if h), "") or (_clean(caption.get_text()) if caption else "")
    header_rows: list[list[str]] = []
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = _cells(tr)
        if not any(cells):
            continue
        if not rows and not tr.find("td"):
            header_rows.append(cells)
        else:
            rows.append(cells)
    notes: list[str] = []
    for el in table.find_all_next(["p", "dd", "div"], limit=80):
        if el.name == "div" and "col-md-12" not in (el.get("class") or []):
            continue
        text = _clean(el.get_text())
        if text.endswith(":") or "Return to footnote" in text:
            continue
        if text and not any(text in note for note in notes):
            notes.append(text)
        if text.startswith(("Source:", "Source :")):
            break
    return title, header_rows, rows, notes


async def get_table(table_key: str, lang: str = "en") -> EnergyTable:
    key = _validated_key(table_key, lang)
    root = constants.FR_ROOT if lang == "fr" else constants.EN_ROOT
    url = f"{root}showTable.cfm?{key}"
    html, cached = await _html(url, constants.CACHE_TTL_TABLE_SECONDS, lang)
    title, header_rows, rows, notes = _parse_table(html, lang)
    return EnergyTable(
        table_key=key,
        title=title,
        header_rows=header_rows,
        rows=rows,
        notes=notes,
        source_url=url,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="nrcan_energy_use.EnergyTable",
            lang=lang,
        ),
    )
