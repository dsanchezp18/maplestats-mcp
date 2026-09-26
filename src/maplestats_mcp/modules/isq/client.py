"""Client for statistique.quebec.ca's detailed tables.

Checked live 2026-09-26:

1. sitemap.xml lists every table page as /fr|en/produit/tableau/<slug>
   (7,078 pages, 3,538 in English). Slugs are the titles, so search reads
   them instead of fetching pages. The site's own search uses Google CSE.
2. Each table page embeds its record in __NEXT_DATA__ (props.pageProps.data):
   name, type ('dynamique' or 'statique'), number (`no`, dynamic only),
   update date, subjects, and for static tables the table as HTML (`html`)
   plus an Excel file name (`excel`, served under /<lang>/fichier/).
   /<lang>/produit/tableau/<number> also resolves.
3. Dynamic tables come from /pls/ken/ken411_data_explt_v2.* (the former
   BDSO engine; robots.txt disallows the path, read here on demand only,
   see __init__.py): p_retrn_titre (title), p_retrn_header (JSON column
   tree and the field list), p_retrn_data (the rows as ';'-separated CSV,
   all rows in one response: 26 of 26 sampled tables, up to 1.4 MB),
   p_retrn_note_html (notes and sources) and p_retrn_signe (flag legend).
4. The column tree nests headers ("2025" over a data field and its flag
   field); 'note' leaves hold the flag for the data leaf before them.
   Group fields and layout helpers (tri_coln, gras, saut) are not values.
5. Values are French-formatted ('1 015,1', with a normal, no-break or
   narrow no-break space) and some cells carry HTML (<span data-tri>).
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.isq import constants
from maplestats_mcp.modules.isq.schemas import IsqSearchResult, IsqTable, IsqTableHit, Value
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.search import tokenize

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_LOC = re.compile(r"<loc>([^<]+)</loc>")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_NUMBER = re.compile(r"^-?\d+(,\d+)?$")
_SPACES = re.compile(r"[\s  ]")


async def _get(url: str, params: dict[str, Any] | None = None) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, params=params, timeout=90.0)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise NotFound(f"isq: {url} does not exist.") from exc
        raise UpstreamError(f"isq: {url} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"isq: {url} did not respond in time.") from exc
    if len(response.content) > constants.MAX_BYTES:
        raise UpstreamError(f"isq: {url} is larger than expected.")
    return response.content.decode("utf-8", errors="replace")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


# ------------------------------------------------------------------ search


async def _sitemap() -> tuple[list[str], bool]:
    async def fetch() -> list[str]:
        urls = [u for u in _LOC.findall(await _get(constants.SITEMAP_URL))]
        tables = [u for u in urls if constants.TABLE_PATH in u]
        if not tables:
            raise UpstreamError("isq: the sitemap lists no table pages.")
        return tables

    return await cached_fetch("isq:sitemap", constants.SITEMAP_TTL_SECONDS, fetch)


def _hit(url: str) -> IsqTableHit:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    lang = "fr" if "/fr/" in url else "en"
    title = slug.replace("-", " ")
    return IsqTableHit(table=slug, title=title[:1].upper() + title[1:], lang=lang, url=url)


async def search_tables(
    query: str, *, lang: str = "en", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> IsqSearchResult:
    """Tables whose slug contains every word of `query` (accents and plurals folded)."""
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(f"isq: limit must be between 1 and {constants.SEARCH_LIMIT_MAX}.")
    words = tokenize(query)
    if not words:
        raise InvalidInput("isq: query needs at least one word.")
    urls, cached = await _sitemap()
    matched = []
    for url in urls:
        if lang != "all" and f"/{lang}/" not in url:
            continue
        slug_words = set(tokenize(url.rsplit("/", 1)[-1].replace("-", " ")))
        if all(w in slug_words for w in words):
            matched.append(_hit(url))
    return IsqSearchResult(
        tables=matched[:limit],
        returned_count=min(limit, len(matched)),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.SITEMAP_URL,
            cached=cached,
            schema_name="isq.IsqSearchResult",
            freshness="the sitemap is read once a day",
            coverage="matches table page names; about half the tables have an English page",
        ),
    )


# ------------------------------------------------------------------ tables


@dataclass
class _Column:
    field: str
    label: str
    flag_field: str | None = None


def columns_from_tree(tree: list[dict[str, Any]]) -> list[_Column]:
    """Data columns in display order, labelled by their header path."""
    out: list[_Column] = []

    def walk(nodes: list[dict[str, Any]], path: list[str]) -> None:
        for node in nodes:
            title = _text(str(node.get("title") or ""))
            if node.get("columns"):
                walk(node["columns"], [*path, title] if title else path)
                continue
            name = str(node.get("field") or "")
            if not name or node.get("type") == "interval":
                continue
            if node.get("type") == "note":
                if out:
                    out[-1].flag_field = name
                continue
            label = " / ".join(p for p in [*path, title] if p) or constants.FIELD_LABELS.get(
                name, name
            )
            out.append(_Column(name, label))

    walk(tree, [])
    # Two columns may share a label (e.g. untitled); keep them apart.
    seen: dict[str, int] = {}
    for column in out:
        n = seen.get(column.label, 0)
        seen[column.label] = n + 1
        if n:
            column.label = f"{column.label} ({column.field})"
    return out


def parse_value(cell: str) -> Value:
    text = _text(cell)
    if text == "":
        return None
    compact = _SPACES.sub("", text)
    if _NUMBER.match(compact):
        number = float(compact.replace(",", "."))
        return int(number) if "," not in compact else number
    return text


def parse_rows(
    body: str, columns: list[_Column]
) -> tuple[list[dict[str, Value]], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(body), delimiter=";")
    rows, flags = [], []
    for record in reader:
        row: dict[str, Value] = {}
        flag: dict[str, str] = {}
        for column in columns:
            if column.field in constants.LAYOUT_FIELDS:
                continue
            row[column.label] = parse_value(record.get(column.field) or "")
            if column.flag_field and (mark := _text(record.get(column.flag_field) or "")):
                flag[column.label] = mark
        rows.append(row)
        flags.append(flag)
    return rows, flags


def parse_static(fragment: str) -> list[list[str]]:
    soup = BeautifulSoup(fragment, "html.parser")
    cells = []
    for tr in soup.find_all("tr"):
        texts = [" ".join(td.get_text(" ").split()) for td in tr.find_all(["td", "th"])]
        if any(texts):
            cells.append(texts)
    return cells


def _page_url(table: str, lang: str) -> str:
    table = table.strip()
    if table.startswith("http"):
        if not table.startswith(constants.SITE) or constants.TABLE_PATH not in table:
            raise InvalidInput("isq: table must be a statistique.quebec.ca table page.")
        return table
    if not re.fullmatch(r"[a-z0-9-]+", table):
        raise InvalidInput(f"isq: {table!r} is not a table slug, number or page URL.")
    return f"{constants.SITE}/{lang}{constants.TABLE_PATH}{table}"


async def _page(url: str) -> dict[str, Any]:
    async def fetch() -> dict[str, Any]:
        match = _NEXT_DATA.search(await _get(url))
        data = json.loads(match.group(1))["props"]["pageProps"].get("data") if match else None
        if not data or "type" not in data:
            raise NotFound(f"isq: {url} is not a table page.")
        return data

    data, _ = await cached_fetch(f"isq:page:{url}", constants.TABLE_TTL_SECONDS, fetch)
    return data


async def _dynamic(number: int) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        header = json.loads(await _get(constants.KEN + "p_retrn_header", {"p_id_tabl": number}))
        config = header.get("tableConfig", header)
        source = config.get("dataSource") or {}
        fields = str(source.get("fields") or "").replace(" ", "")
        if not fields:
            raise UpstreamError(f"isq: table {number} has no field list.")
        sort = ",".join(f"{s['field']} {s.get('dir', 'asc')}" for s in source.get("sort") or [])
        params: dict[str, Any] = {"p_id_tabl": number, "p_champs": fields}
        if sort:
            params["p_tri"] = sort
        tree = list(config.get("columns") or [])
        group = (source.get("group") or {}).get("field")
        if group:
            tree.insert(0, {"field": group})
            tree = [n for n in tree if not (n.get("type") == "group" and n.get("field") == group)]
        return {
            "title": _text(await _get(constants.KEN + "p_retrn_titre", {"p_id_tabl": number})),
            "tree": tree,
            "data": await _get(constants.KEN + "p_retrn_data", params),
            "notes": _text(
                await _get(
                    constants.KEN + "p_retrn_note_html", {"p_id_tabl": number, "p_lang": "fr"}
                )
            ),
        }

    return await cached_fetch(f"isq:dynamic:{number}", constants.TABLE_TTL_SECONDS, fetch)


async def _legend() -> dict[str, str]:
    async def fetch() -> dict[str, str]:
        body = await _get(constants.KEN + "p_retrn_signe")
        reader = csv.DictReader(io.StringIO(body), delimiter=";")
        return {
            r["signe"]: r["desc"] for r in reader if r.get("signe") and "TEST" not in r["signe"]
        }

    legend, _ = await cached_fetch("isq:legend", constants.SITEMAP_TTL_SECONDS, fetch)
    return legend


async def get_table(
    table: str,
    *,
    offset: int = 0,
    max_rows: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> IsqTable:
    """One table's metadata and rows, by slug, number or page URL."""
    if max_rows < 1 or max_rows > constants.ROWS_MAX:
        raise InvalidInput(f"isq: max_rows must be between 1 and {constants.ROWS_MAX}.")
    if offset < 0:
        raise InvalidInput("isq: offset must be >= 0.")
    url = _page_url(table, lang)
    try:
        page = await _page(url)
    except NotFound:
        # A slug belongs to one language's page; try the other one.
        other = "en" if lang == "fr" else "fr"
        if table.startswith("http"):
            raise
        url = _page_url(table, other)
        page = await _page(url)
    subjects = [str(s.get("nom")) for s in page.get("sujets") or [] if s.get("nom")]
    common = {
        "url": url,
        "updated": page.get("mise_jour"),
        "subjects": subjects,
    }
    if page.get("type") == "dynamique" and page.get("no"):
        number = int(page["no"])
        loaded, cached = await _dynamic(number)
        columns = [
            c for c in columns_from_tree(loaded["tree"]) if c.field not in constants.LAYOUT_FIELDS
        ]
        rows, flags = parse_rows(loaded["data"], columns)
        shown = slice(offset, offset + max_rows)
        return IsqTable(
            title=loaded["title"] or str(page.get("nom") or ""),
            number=number,
            kind="dynamic",
            columns=[c.label for c in columns],
            rows=rows[shown],
            flags=flags[shown],
            returned_count=len(rows[shown]),
            total_rows=len(rows),
            notes=loaded["notes"] or None,
            flag_legend=await _legend(),
            provenance=_provenance(constants.KEN + f"p_retrn_data?p_id_tabl={number}", cached),
            **common,
        )
    cells = parse_static(str(page.get("html") or ""))
    excel = page.get("excel")
    return IsqTable(
        title=str(page.get("nom") or ""),
        kind="static",
        cells=cells[offset : offset + max_rows],
        returned_count=len(cells[offset : offset + max_rows]),
        total_rows=len(cells),
        # The Excel copy is served under the language of the page it came from.
        excel_url=(
            f"{constants.SITE}/{'fr' if '/fr/' in url else 'en'}/fichier/{excel}" if excel else None
        ),
        provenance=_provenance(url, False),
        **common,
    )


def _provenance(url: str, cached: bool) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name="isq.IsqTable",
        freshness="as published by ISQ; each table states its update date",
        limits="labels are mostly French; flags are ISQ's conventional signs",
    )
