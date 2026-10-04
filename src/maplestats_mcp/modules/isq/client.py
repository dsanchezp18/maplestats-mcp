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
   BDSO engine, read on demand, one table per request): p_retrn_titre (title), p_retrn_header (JSON column
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

import asyncio
import csv
import html
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.isq import constants
from maplestats_mcp.modules.isq.schemas import IsqSearchResult, IsqTable, IsqTableHit, Value
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import pick
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


async def _get(url: str, params: dict[str, Any] | None = None, lang: str = "en") -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, params=params, timeout=90.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise_localized(
                NotFound, f"isq: {url} does not exist.", f"isq : {url} n'existe pas.", lang
            )
        raise_localized(
            UpstreamError,
            f"isq: {url} returned HTTP {status}.",
            f"isq : {url} a répondu par une erreur HTTP {status}.",
            lang,
        )
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            f"isq: {url} did not respond in time.",
            f"isq : {url} n'a pas répondu à temps.",
            lang,
        )
    if len(response.content) > constants.MAX_BYTES:
        raise_localized(
            UpstreamError,
            f"isq: {url} is larger than expected.",
            f"isq : {url} est plus volumineux que prévu.",
            lang,
        )
    return response.content.decode("utf-8", errors="replace")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


# ------------------------------------------------------------------ search


async def _sitemap(lang: str = "en") -> tuple[list[str], bool]:
    async def fetch() -> list[str]:
        urls = [u for u in _LOC.findall(await _get(constants.SITEMAP_URL, lang=lang))]
        tables = [u for u in urls if constants.TABLE_PATH in u]
        if not tables:
            raise_localized(
                UpstreamError,
                "isq: the sitemap lists no table pages.",
                "isq : le plan du site ne liste aucune page de tableau.",
                lang,
            )
        return tables

    return await cached_fetch("isq:sitemap", constants.SITEMAP_TTL_SECONDS, fetch)


def _hit(url: str) -> IsqTableHit:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    lang = "fr" if "/fr/" in url else "en"
    title = slug.replace("-", " ")
    return IsqTableHit(
        table=slug, title=title[:1].upper() + title[1:], lang=lang, languages=[lang], url=url
    )


async def search_tables(
    query: str, *, lang: str = "en", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> IsqSearchResult:
    """Tables whose slug contains every word of `query` (accents and plurals folded)."""
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise_localized(
            InvalidInput,
            f"isq: limit must be between 1 and {constants.SEARCH_LIMIT_MAX}.",
            f"isq : limit doit être compris entre 1 et {constants.SEARCH_LIMIT_MAX}.",
            lang,
        )
    words = tokenize(query)
    if not words:
        raise_localized(
            InvalidInput,
            "isq: query needs at least one word.",
            "isq : query doit contenir au moins un mot.",
            lang,
        )
    urls, cached = await _sitemap(lang)
    by_slug: dict[str, IsqTableHit] = {}
    for url in urls:
        if lang != "all" and f"/{lang}/" not in url:
            continue
        slug_words = set(tokenize(url.rsplit("/", 1)[-1].replace("-", " ")))
        if not all(w in slug_words for w in words):
            continue
        # Many English pages reuse the French slug (the sitemap lists
        # /fr/ and /en/ .../revenu-disponible-composantes-mrc-ensemble-quebec):
        # one hit per slug, on the French page, listing both languages.
        hit = _hit(url)
        if (seen := by_slug.get(hit.table)) is None:
            by_slug[hit.table] = hit
            continue
        seen.languages = ["en", "fr"]
        if hit.lang == "fr":
            seen.lang, seen.url, seen.title = hit.lang, hit.url, hit.title
    matched = list(by_slug.values())
    shown = matched[:limit]
    titled = await _page_titles(shown) if lang == "fr" else 0
    return IsqSearchResult(
        tables=shown,
        returned_count=min(limit, len(matched)),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.SITEMAP_URL,
            cached=cached,
            schema_name="isq.IsqSearchResult",
            freshness=pick(
                lang,
                "the sitemap is read once a day",
                "le plan du site est lu une fois par jour",
            ),
            coverage=pick(
                lang,
                "matches table page names; about half the tables have an English page",
                "recherche dans les noms des pages de tableaux ; environ la moitié des "
                "tableaux ont aussi une page en anglais",
            ),
            limits=(
                pick(
                    lang,
                    "",
                    f"Titres lus sur la page de chaque tableau pour les {titled} premiers "
                    "résultats ; les suivants sont tirés de l'adresse de la page, sans accents "
                    "(isq_get_table donne le titre exact).",
                )
                if len(shown) > titled
                else None
            )
            or None,
            lang=lang,
        ),
    )


async def _page_titles(hits: list[IsqTableHit]) -> int:
    """Replace the slug titles of the first hits by their page titles (with accents).

    The sitemap has no titles, and a slug drops accents and punctuation
    ("Indicateurs mensuels emploi et taux de chomage par region
    administrative" for "Indicateurs mensuels : emploi et taux de chômage
    par région administrative"). Each page's __NEXT_DATA__ carries its title
    (`nom`, checked live 2026-10-04); pages are cached like get_table's, and a
    page that fails keeps its slug title. Returns how many hits were read.
    """
    first = hits[: constants.SEARCH_TITLES_MAX]

    async def title(hit: IsqTableHit) -> None:
        try:
            page = await _page(hit.url)
        except (NotFound, UpstreamError, UpstreamUnavailable):
            return
        if page.get("nom"):
            hit.title = _text(str(page["nom"]))

    await asyncio.gather(*(title(hit) for hit in first))
    return len(first)


# ------------------------------------------------------------------ tables


@dataclass
class _Column:
    field: str
    label: str
    flag_field: str | None = None
    # Field whose per-row text titles this column's header (e.g. lbl_2024 =
    # "2024ᵖ"); a trailing superscript there is the cell's flag.
    mark_field: str | None = None


def split_mark(text: str) -> tuple[str, str]:
    """'2024ᵖ' -> ('2024', 'p'): ISQ writes the flag as a superscript letter."""
    text = _text(text)
    end = len(text)
    while end and unicodedata.category(text[end - 1]) == "Lm":
        end -= 1
    return text[:end].strip(), unicodedata.normalize("NFKC", text[end:])


def header_values(body: str) -> dict[str, str]:
    """First non-empty value of every field, to resolve titleField headers."""
    found: dict[str, str] = {}
    for record in csv.DictReader(io.StringIO(body), delimiter=";"):
        for key, value in record.items():
            if key and key not in found and value and value.strip():
                found[key] = value
    return found


def columns_from_tree(
    tree: list[dict[str, Any]], values: dict[str, str] | None = None
) -> list[_Column]:
    """Data columns in display order, labelled by their header path.

    A header can name a field instead of carrying a title ("titleField"):
    table 4948 (checked live 2026-10-03) titles each year group with
    lbl_<year> ("2024ᵖ") and each value leaf with mesr, the row's unit
    ("$/hab" or "M$"). The year comes from `values` (first non-empty cell
    of each field); the unit field becomes a column of its own, since two
    rows that differ only by unit are otherwise indistinguishable.
    """
    values = values or {}
    out: list[_Column] = []
    fields_out: set[str] = set()

    def walk(nodes: list[dict[str, Any]], path: list[str], mark: str | None) -> None:
        for node in nodes:
            title = _text(str(node.get("title") or ""))
            title_field = str(node.get("titleField") or "")
            if node.get("columns"):
                child_mark = mark
                if title_field and not title:
                    title = split_mark(values.get(title_field, ""))[0] or title_field
                    child_mark = title_field
                walk(node["columns"], [*path, title] if title else path, child_mark)
                continue
            name = str(node.get("field") or "")
            if not name or node.get("type") == "interval":
                continue
            if node.get("type") == "note":
                if out:
                    out[-1].flag_field = name
                continue
            if title_field and not title and title_field not in fields_out:
                label = constants.FIELD_LABELS.get(title_field, title_field)
                # The unit lands right before the first value column it titles.
                out.append(_Column(title_field, label))
                fields_out.add(title_field)
            label = " / ".join(p for p in [*path, title] if p) or constants.FIELD_LABELS.get(
                name, name
            )
            out.append(_Column(name, label, mark_field=mark))
            fields_out.add(name)

    walk(tree, [], None)
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
            row[column.label] = value = parse_value(record.get(column.field) or "")
            mark = _text(record.get(column.flag_field) or "") if column.flag_field else ""
            if not mark and column.mark_field and value is not None:
                # No sign: the flag is the header's superscript ("2024ᵖ").
                mark = split_mark(record.get(column.mark_field) or "")[1]
            if mark:
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
            raise_localized(
                InvalidInput,
                "isq: table must be a statistique.quebec.ca table page.",
                "isq : table doit être une page de tableau de statistique.quebec.ca.",
                lang,
            )
        return table
    if not re.fullmatch(r"[a-z0-9-]+", table):
        raise_localized(
            InvalidInput,
            f"isq: {table!r} is not a table slug, number or page URL.",
            f"isq : {table!r} n'est ni un identifiant de tableau, ni un numéro, ni l'adresse "
            "d'une page.",
            lang,
        )
    return f"{constants.SITE}/{lang}{constants.TABLE_PATH}{table}"


async def _page(url: str, lang: str = "en") -> dict[str, Any]:
    async def fetch() -> dict[str, Any]:
        match = _NEXT_DATA.search(await _get(url, lang=lang))
        data = json.loads(match.group(1))["props"]["pageProps"].get("data") if match else None
        if not data or "type" not in data:
            raise_localized(
                NotFound,
                f"isq: {url} is not a table page.",
                f"isq : {url} n'est pas une page de tableau.",
                lang,
            )
        return data

    data, _ = await cached_fetch(f"isq:page:{url}", constants.TABLE_TTL_SECONDS, fetch)
    return data


async def _dynamic(number: int, lang: str = "en") -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        header = json.loads(
            await _get(constants.KEN + "p_retrn_header", {"p_id_tabl": number}, lang)
        )
        config = header.get("tableConfig", header)
        source = config.get("dataSource") or {}
        fields = str(source.get("fields") or "").replace(" ", "")
        if not fields:
            raise_localized(
                UpstreamError,
                f"isq: table {number} has no field list.",
                f"isq : le tableau {number} n'a pas de liste de champs.",
                lang,
            )
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
            "title": _text(
                await _get(constants.KEN + "p_retrn_titre", {"p_id_tabl": number}, lang)
            ),
            "tree": tree,
            "data": await _get(constants.KEN + "p_retrn_data", params, lang),
            # The engine is French only: p_lang=en returned the same French
            # notes on 7 of 7 tables with an English page, and p_retrn_titre
            # or p_retrn_header with p_lang answer 404 (checked 2026-10-03).
            "notes": _text(
                await _get(
                    constants.KEN + "p_retrn_note_html",
                    {"p_id_tabl": number, "p_lang": "fr"},
                    lang,
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
        raise_localized(
            InvalidInput,
            f"isq: max_rows must be between 1 and {constants.ROWS_MAX}.",
            f"isq : max_rows doit être compris entre 1 et {constants.ROWS_MAX}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            "isq: offset must be >= 0.",
            "isq : offset doit être égal ou supérieur à 0.",
            lang,
        )
    url = _page_url(table, lang)
    try:
        page = await _page(url, lang)
    except NotFound:
        # A slug belongs to one language's page; try the other one.
        other = "en" if lang == "fr" else "fr"
        if table.startswith("http"):
            raise
        url = _page_url(table, other)
        page = await _page(url, lang)
    subjects = [str(s.get("nom")) for s in page.get("sujets") or [] if s.get("nom")]
    common = {
        "url": url,
        "updated": page.get("mise_jour"),
        "subjects": subjects,
    }
    if page.get("type") == "dynamique" and page.get("no"):
        number = int(page["no"])
        loaded, cached = await _dynamic(number, lang)
        tree_columns = columns_from_tree(loaded["tree"], header_values(loaded["data"]))
        columns = [c for c in tree_columns if c.field not in constants.LAYOUT_FIELDS]
        rows, flags = parse_rows(loaded["data"], columns)
        shown = slice(offset, offset + max_rows)
        # The engine's title is French; an English page carries its own title.
        english = lang == "en" and "/en/" in url and page.get("nom")
        return IsqTable(
            title=str(page["nom"]) if english else loaded["title"] or str(page.get("nom") or ""),
            number=number,
            kind="dynamic",
            columns=[c.label for c in columns],
            rows=rows[shown],
            flags=flags[shown],
            returned_count=len(rows[shown]),
            total_rows=len(rows),
            notes=loaded["notes"] or None,
            flag_legend=await _legend(),
            provenance=_provenance(
                constants.KEN + f"p_retrn_data?p_id_tabl={number}", cached, lang
            ),
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
        provenance=_provenance(url, False, lang),
        **common,
    )


def _provenance(url: str, cached: bool, lang: str = "en") -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name="isq.IsqTable",
        freshness=pick(
            lang,
            "as published by ISQ; each table states its update date",
            "tel que publié par l'ISQ ; chaque tableau indique sa date de mise à jour",
        ),
        limits=pick(
            lang,
            "ISQ's data engine is French only: column labels, units, notes and"
            " sources stay French with lang='en' (only the title follows an"
            " English page); flags are ISQ's conventional signs",
            "Les étiquettes de colonnes, unités, notes et sources sont celles de l'ISQ, en "
            "français ; les signes sont les signes conventionnels de l'ISQ",
        ),
        lang=lang,
    )
