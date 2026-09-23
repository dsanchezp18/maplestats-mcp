"""HTTP client for NRCan's National Energy Use Database (OEE) pages.

Menus and tables are server-rendered HTML with no JSON alternative, so
both are parsed with BeautifulSoup. A table is addressed by a
`table_key`: the whitelisted `showTable.cfm` query string, which works
unchanged against the English and French roots.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from maple_data_mcp.modules.nrcan_energy_use import constants
from maple_data_mcp.modules.nrcan_energy_use.schemas import (
    ComprehensiveMenu,
    EnergyTable,
    Product,
    ProductList,
    TableList,
    TableRef,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_VALUE = re.compile(r"^[A-Za-z0-9]{1,12}$")
_MENU = re.compile(r"trends_([a-z]+)_([a-z]+)\.cfm")


async def _html(url: str, ttl: int) -> tuple[str, bool]:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"nrcan_energy_use: nothing published at {url}.") from exc
            raise UpstreamError(
                f"nrcan_energy_use: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"nrcan_energy_use: {url} did not respond in time.") from exc
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
    index = 1 if lang == "fr" else 0
    html, cached = await _html(
        constants.EN_ROOT + constants.COMPREHENSIVE_LIST, constants.CACHE_TTL_MENU_SECONDS
    )
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
        surveys=[Product(product=k, name=v[index]) for k, v in constants.SURVEYS.items()],
        comprehensive=menus,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.EN_ROOT + constants.COMPREHENSIVE_LIST,
            cached=cached,
            schema_name="nrcan_energy_use.ProductList",
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
    product: str, sector: str | None = None, jurisdiction: str | None = None
) -> TableList:
    if product == "comprehensive":
        if not sector or not jurisdiction:
            raise InvalidInput(
                "product='comprehensive' needs sector and jurisdiction "
                "(see nrcan_energy_use_list_products)."
            )
        if not (_VALUE.match(sector) and _VALUE.match(jurisdiction)):
            raise InvalidInput("sector and jurisdiction must be short codes such as 'res', 'ab'.")
        path = constants.COMPREHENSIVE_MENU.format(sector=sector, jurisdiction=jurisdiction)
    elif product in constants.SURVEYS:
        path = constants.SURVEYS[product][2]
    else:
        raise InvalidInput(
            f"Unknown product {product!r}; use 'comprehensive' or one of "
            f"{sorted(constants.SURVEYS)}."
        )
    url = constants.EN_ROOT + path
    html, cached = await _html(url, constants.CACHE_TTL_MENU_SECONDS)
    tables = _parse_menu(html)
    if not tables:
        raise NotFound(f"No tables listed at {url}.")
    return TableList(
        product=product,
        tables=tables,
        menu_url=url,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="nrcan_energy_use.TableList",
        ),
    )


def _validated_key(table_key: str) -> str:
    params = dict(parse_qsl(table_key.lstrip("?")))
    unknown = set(params) - set(constants.TABLE_PARAMS)
    if unknown or "type" not in params or "rn" not in params:
        raise InvalidInput(
            "table_key must be a key from nrcan_energy_use_list_tables, "
            "e.g. 'type=SH&sector=aaa&juris=ca&year=2019&rn=1&page=1'."
        )
    if not all(_VALUE.match(v) for v in params.values()):
        raise InvalidInput("table_key values must be short letter/number codes.")
    return urlencode({k: params[k] for k in constants.TABLE_PARAMS if k in params})


def _cells(row: Tag) -> list[str]:
    return [_clean(c.get_text()) for c in row.find_all(["th", "td"], recursive=False)]


def _parse_table(html: str) -> tuple[str, list[list[str]], list[list[str]], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not isinstance(table, Tag):
        raise NotFound("nrcan_energy_use: the page has no data table.")
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
    key = _validated_key(table_key)
    root = constants.FR_ROOT if lang == "fr" else constants.EN_ROOT
    url = f"{root}showTable.cfm?{key}"
    html, cached = await _html(url, constants.CACHE_TTL_TABLE_SECONDS)
    title, header_rows, rows, notes = _parse_table(html)
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
        ),
    )
