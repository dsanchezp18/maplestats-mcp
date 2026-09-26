"""Client for the Government of Canada Recalls and Safety Alerts site.

Search and counts run over the site's daily open-data dump (one JSON
file per language, see constants.py); a single recall's full details
come from its page. Checked live 2026-09-26:

1. The dump holds 34,131 notices (1991 onward) from Health Canada, CFIA
   and Transport Canada, 14,444 of them archived. The site's own search
   shows only non-archived notices: its total (19,690) and its per-year
   facet counts match the dump's non-archived rows grouped by
   "Last updated" year, so that is the site's date too. The dump has no
   recall date or first-published date; those are only on the page.
2. Quirks: 22,000+ titles carry leading/trailing spaces; "Product" is
   null on 18,762 rows; "Last updated" is null on 2,717 (all Transport
   Canada); "What you should do" is empty on over 90% of rows and
   otherwise HTML flattened to text, with `&nbsp;` entities and
   paragraphs run together ("table.Consult"), so search leaves it out
   and recalls_get reads the page's own text instead; some titles carry zero-width spaces; "Recall class" is "" or "--"
   when there is none, and can be a range ("Type I - Type II"). A few
   URLs point to the other language's page (377 in the French file).
3. Pages come in two layouts. Current pages use Drupal fields whose
   class names (field--name-field-product, -issue-type, -category,
   -hazard-type, -recall-date, -cfia-id, ...) are the same in both
   languages; notices migrated from the old site put a <dl> header and
   free HTML inside div.recall-alert-body. A page untranslated into
   French is served at /fr/ with English text.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from maplestats_mcp.modules.recalls import constants
from maplestats_mcp.modules.recalls.schemas import (
    LabelValue,
    RecallCount,
    RecallCountsResult,
    RecallDetail,
    RecallSearchResult,
    RecallSection,
    RecallSummary,
    RecallTable,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import decode_json, get_raw, is_retryable, new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
# /{lang}/node/{nid} answers with a 302 to the page's slug, so pages need
# a client that follows redirects; the shared one does not.
_pages = new_client(timeout=30.0, follow_redirects=True)

_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
_TC_NUMBER = re.compile(r" - (\d{6,8})\s*(?:-|$)")
_BLOCK_TAGS = frozenset(
    {"p", "li", "div", "tr", "h2", "h3", "h4", "h5", "dt", "dd", "ul", "ol", "table", "details"}
)
_FREQUENCY = "daily; the dump is regenerated around 02:20 UTC"


@dataclass(frozen=True, slots=True)
class _Record:
    nid: int
    title: str
    url: str
    organization: str
    agency: str
    product_types: tuple[str, ...]
    product: str | None
    issue: str | None
    category: str | None
    recall_class: str | None
    last_updated: date | None
    archived: bool
    tc_recall_number: str | None
    haystack: str


@dataclass(frozen=True, slots=True)
class _Dump:
    records: tuple[_Record, ...]
    url: str
    as_of: datetime | None


# ---------------------------------------------------------------- text helpers


def _fold(text: str) -> str:
    """Lowercase without accents, so 'bœuf' matches 'boeuf' and 'Santé' 'sante'."""
    text = text.replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).translate(_INVISIBLE).replace("\xa0", " ")
    text = " ".join(text.split())
    return text or None


def _clean_class(value: Any) -> str | None:
    text = _clean(value)
    return None if text in (None, "--") else text


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _product_types(organization: str, category: str | None) -> tuple[str, ...]:
    types: set[str] = set()
    fixed = constants.ORGANIZATION_TYPE.get(organization)
    if fixed:
        types.add(fixed)
    leaves = {leaf.strip() for leaf in (category or "").split(" - ")}
    if leaves & constants.FOOD_LEAVES:
        types.add("food")
    if leaves & constants.CONSUMER_LEAVES:
        types.add("consumer_product")
    if leaves & constants.HEALTH_LEAVES:
        types.add("health_product")
    if not types and constants.ORGANIZATION_AGENCY.get(organization) == "health_canada":
        # Health Canada communications-branch advisories on household
        # items, electronics and the like: consumer products on the site.
        types.add("consumer_product")
    return tuple(t for t in constants.PRODUCT_TYPES if t in types)


def _record(row: dict[str, Any], keys: dict[str, str]) -> _Record | None:
    nid = str(row.get("NID") or "").strip()
    if not nid.isdigit():
        return None
    organization = _clean(row.get("Organization")) or ""
    title = _clean(row.get(keys["title"])) or ""
    product = _clean(row.get(keys["product"]))
    issue = _clean(row.get(keys["issue"]))
    category = _clean(row.get(keys["category"]))
    agency = constants.ORGANIZATION_AGENCY.get(organization, "other")
    tc_number = None
    if agency == "transport_canada":
        match = _TC_NUMBER.search(title)
        tc_number = match.group(1) if match else None
    return _Record(
        nid=int(nid),
        title=title,
        url=str(row.get("URL") or ""),
        organization=organization,
        agency=agency,
        product_types=_product_types(organization, category),
        product=product,
        issue=issue,
        category=category,
        recall_class=_clean_class(row.get(keys["recall_class"])),
        last_updated=_parse_date(row.get(keys["last_updated"])),
        archived=str(row.get(keys["archived"]) or "0").strip() == "1",
        tc_recall_number=tc_number,
        haystack=_fold(" ".join(filter(None, (title, product, issue, category, organization)))),
    )


def _sort_key(record: _Record) -> tuple[date, int]:
    return (record.last_updated or date.min, record.nid)


# ---------------------------------------------------------------- dump


def _check_lang(lang: str) -> str:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be 'en' or 'fr', got {lang!r}.")
    return lang


async def _load_dump(lang: str) -> tuple[_Dump, bool]:
    url = constants.DUMP_URLS[lang]

    async def fetch() -> _Dump:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=constants.DUMP_TIMEOUT_SECONDS)
            rows = decode_json(response, url)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"recalls: open-data file returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.DecodingError as exc:
            raise UpstreamError("recalls: open-data file is not valid JSON.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable("recalls: open-data file could not be downloaded.") from exc
        if not isinstance(rows, list) or not rows:
            raise UpstreamError("recalls: open-data file is not a non-empty JSON list.")
        keys = constants.KEYS[lang]
        if not isinstance(rows[0], dict) or keys["title"] not in rows[0]:
            raise UpstreamError(
                f"recalls: open-data rows no longer carry {keys['title']!r}; the format changed."
            )
        records = [r for r in (_record(row, keys) for row in rows if isinstance(row, dict)) if r]
        records.sort(key=_sort_key, reverse=True)
        as_of = None
        modified = response.headers.get("last-modified")
        if modified:
            try:
                as_of = parsedate_to_datetime(modified)
            except (TypeError, ValueError):
                as_of = None
        return _Dump(records=tuple(records), url=url, as_of=as_of)

    return await cached_fetch(f"recalls:dump:{lang}", constants.DUMP_CACHE_TTL_SECONDS, fetch)


def _date_arg(value: str | None, name: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise InvalidInput(f"{name} must be YYYY-MM-DD, got {value!r}.") from exc


def _class_parts(value: str) -> set[str]:
    return {" ".join(_fold(p).replace("classe", "class").split()) for p in value.split(" - ")}


def _filter(
    records: Iterable[_Record],
    *,
    query: str | None,
    agency: str | None,
    product_type: str | None,
    category: str | None,
    recall_class: str | None,
    updated_from: str | None,
    updated_to: str | None,
    include_archived: bool,
) -> list[_Record]:
    if agency is not None and agency not in constants.AGENCIES:
        raise InvalidInput(f"agency must be one of {', '.join(constants.AGENCIES)}.")
    if product_type is not None and product_type not in constants.PRODUCT_TYPES:
        raise InvalidInput(f"product_type must be one of {', '.join(constants.PRODUCT_TYPES)}.")
    start = _date_arg(updated_from, "updated_from")
    end = _date_arg(updated_to, "updated_to")
    if start and end and start > end:
        raise InvalidInput(f"updated_from {start} is after updated_to {end}.")
    words = re.findall(r"\w+", _fold(query or ""))
    category_folded = _fold(category.strip()) if category and category.strip() else None
    wanted_class = _class_parts(recall_class) if recall_class and recall_class.strip() else None

    matched = []
    for record in records:
        if record.archived and not include_archived:
            continue
        if agency and record.agency != agency:
            continue
        if product_type and product_type not in record.product_types:
            continue
        if (start or end) and record.last_updated is None:
            continue
        if start and record.last_updated and record.last_updated < start:
            continue
        if end and record.last_updated and record.last_updated > end:
            continue
        if category_folded and category_folded not in _fold(record.category or ""):
            continue
        if wanted_class and not (
            record.recall_class and wanted_class <= _class_parts(record.recall_class)
        ):
            continue
        if words and not all(word in record.haystack for word in words):
            continue
        matched.append(record)
    return matched


def _coverage(include_archived: bool) -> str:
    if include_archived:
        return "includes archived notices"
    return "archived notices excluded, as on the site's own search; pass include_archived=True"


def _summary(record: _Record) -> RecallSummary:
    return RecallSummary(
        recall_id=record.nid,
        title=record.title,
        product=record.product,
        issue=record.issue,
        category=record.category,
        recall_class=record.recall_class,
        organization=record.organization,
        agency=record.agency,
        product_types=list(record.product_types),
        last_updated=record.last_updated,
        archived=record.archived,
        tc_recall_number=record.tc_recall_number,
        url=record.url,
    )


async def search(
    query: str | None = None,
    *,
    agency: str | None = None,
    product_type: str | None = None,
    category: str | None = None,
    recall_class: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    include_archived: bool = False,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> RecallSearchResult:
    lang = _check_lang(lang)
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    dump, cached = await _load_dump(lang)
    matched = _filter(
        dump.records,
        query=query,
        agency=agency,
        product_type=product_type,
        category=category,
        recall_class=recall_class,
        updated_from=updated_from,
        updated_to=updated_to,
        include_archived=include_archived,
    )
    page = matched[offset : offset + limit]
    return RecallSearchResult(
        recalls=[_summary(r) for r in page],
        total_matched=len(matched),
        returned_count=len(page),
        offset=offset,
        limit=limit,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=dump.url,
            cached=cached,
            schema_name="recalls.RecallSearchResult",
            as_of=dump.as_of,
            freshness=_FREQUENCY,
            coverage=_coverage(include_archived),
            limits=(
                "newest 'last updated' first; dates filter on last updated (the dump has no "
                "recall date); notices with no date sort last and drop out of date filters"
            ),
        ),
    )


def _group_keys(record: _Record, group_by: str) -> list[str]:
    if group_by == "year":
        return [str(record.last_updated.year) if record.last_updated else "unknown"]
    if group_by == "product_type":
        return list(record.product_types) or ["unknown"]
    if group_by == "archived":
        return ["archived" if record.archived else "current"]
    value = getattr(record, group_by)
    return [value or "(none)"]


GROUP_BY = ("year", "agency", "product_type", "organization", "category", "issue", "recall_class")


async def summarize(
    group_by: str,
    query: str | None = None,
    *,
    agency: str | None = None,
    product_type: str | None = None,
    category: str | None = None,
    recall_class: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    include_archived: bool = True,
    top: int = constants.GROUPS_DEFAULT,
    lang: str = "en",
) -> RecallCountsResult:
    lang = _check_lang(lang)
    if group_by not in GROUP_BY:
        raise InvalidInput(f"group_by must be one of {', '.join(GROUP_BY)}, got {group_by!r}.")
    if top < 1 or top > constants.GROUPS_MAX:
        raise InvalidInput(f"top must be between 1 and {constants.GROUPS_MAX}, got {top}.")
    dump, cached = await _load_dump(lang)
    matched = _filter(
        dump.records,
        query=query,
        agency=agency,
        product_type=product_type,
        category=category,
        recall_class=recall_class,
        updated_from=updated_from,
        updated_to=updated_to,
        include_archived=include_archived,
    )
    counts: Counter[str] = Counter()
    for record in matched:
        counts.update(_group_keys(record, group_by))
    if group_by == "year":
        ordered = sorted(counts.items(), key=lambda kv: (kv[0] == "unknown", kv[0]))
    else:
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    groups = [RecallCount(key=k, count=v) for k, v in ordered[:top]]
    limits = "year is the 'last updated' year, which the site's own date facet also uses"
    if group_by == "product_type":
        limits = "a notice can have several product types, so counts can sum past total_matched"
    if len(ordered) > top:
        limits += f"; first {top} of {len(ordered)} groups"
    return RecallCountsResult(
        group_by=group_by,
        total_matched=len(matched),
        groups=groups,
        groups_total=len(ordered),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=dump.url,
            cached=cached,
            schema_name="recalls.RecallCountsResult",
            as_of=dump.as_of,
            freshness=_FREQUENCY,
            coverage=_coverage(include_archived),
            limits=limits,
        ),
    )


# ---------------------------------------------------------------- recall page


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _get_page(url: str) -> httpx.Response:
    response = await _pages.get(url)
    response.raise_for_status()
    return response


async def _fetch_page(nid: int, lang: str) -> tuple[tuple[str, str], bool]:
    url = constants.NODE_URL.format(lang=lang, nid=nid)

    async def fetch() -> tuple[str, str]:
        await _LIMITER.acquire()
        try:
            response = await _get_page(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"No recall or alert with id {nid}.") from exc
            raise UpstreamError(
                f"recalls: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"recalls: {url} could not be reached.") from exc
        return str(response.url), response.text

    return await cached_fetch(f"recalls:page:{lang}:{nid}", constants.PAGE_CACHE_TTL_SECONDS, fetch)


def _text(element: Tag | None) -> str:
    """Element text with block breaks kept and inline links left inline."""
    if element is None:
        return ""
    parts: list[str] = []
    for node in element.descendants:
        if isinstance(node, Comment):
            continue
        if isinstance(node, NavigableString):
            if node.parent is not None and node.parent.name in ("script", "style"):
                continue
            # Newlines in the HTML source are only whitespace; line breaks
            # come from <br> and block elements below.
            parts.append(re.sub(r"\s+", " ", str(node)))
        elif isinstance(node, Tag) and (node.name == "br" or node.name in _BLOCK_TAGS):
            parts.append("\n")
    lines = (_clean(line) for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def _cap(text: str) -> str:
    if len(text) <= constants.TEXT_MAX_CHARS:
        return text
    return text[: constants.TEXT_MAX_CHARS].rstrip() + " [...]"


def _items(root: Tag, name: str) -> list[str]:
    values: list[str] = []
    for element in root.select(f".field--name-{name}"):
        classes = element.get("class") or []
        items = [element] if "field--item" in classes else element.select(".field--item")
        for item in items:
            text = _text(item)
            if text and text not in values:
                values.append(text)
    return values


def _first(root: Tag, name: str) -> str | None:
    values = _items(root, name)
    return values[0] if values else None


def _time(element: Tag | None) -> date | None:
    if element is None:
        return None
    stamp = element if element.name == "time" else element.find("time")
    if not isinstance(stamp, Tag):
        return None
    return _parse_date(stamp.get("datetime") or stamp.get_text(strip=True))


def _table(table: Tag) -> RecallTable:
    rows = table.find_all("tr")
    header = table.select("thead th")
    body = rows
    if not header and rows and rows[0].find("th") and not rows[0].find("td"):
        header = rows[0].find_all("th")
        body = rows[1:]
    columns = [_text(th).replace("\n", " ") for th in header]
    data = []
    for tr in body:
        cells = tr.find_all("td")
        if cells:
            data.append([_text(td).replace("\n", "; ") for td in cells])
    truncated = len(data) > constants.TABLE_ROWS_MAX
    return RecallTable(columns=columns, rows=data[: constants.TABLE_ROWS_MAX], truncated=truncated)


def _agency(*names: str | None) -> str | None:
    for name in names:
        if name:
            key = (_clean(name) or "").casefold().replace("\u2019", "'")
            agency = constants.PUBLISHER_AGENCY.get(key)
            if agency:
                return agency
    return None


def _parse_current(main: Tag) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "product": _first(main, "field-product"),
        "issue": _items(main, "field-issue-type"),
        "category": _items(main, "field-category"),
        "recall_class": " - ".join(_items(main, "field-hazard-type")) or None,
        "what_to_do": _first(main, "field-action"),
        "audience": _items(main, "field-who-this-is-for"),
        "distribution": _items(main, "field-distribution-region"),
        "companies": _first(main, "field-companies"),
        "published_by": _first(main, "field-organization"),
        "brands": _items(main, "field-brand-ref"),
        "recall_date": _time(main.select_one(".field--name-field-recall-date")),
        "last_updated": _time(main.select_one(".field--name-field-last-updated")),
        "alert_type": _first(main, "field-recall-type"),
    }
    changed = main.select_one(".views-label-changed")
    fields["first_published"] = _time(changed.parent) if changed and changed.parent else None
    for wrapper in main.select(".field--name-node-id"):
        value = _text(wrapper.select_one(".field--item"))
        if re.fullmatch(r"RA-\d+", value):
            fields["identification_number"] = value
    reference = main.select_one(".field--name-field-cfia-id")
    if reference is not None:
        value = _first(reference, "field-cfia-id") or _text(reference)
        holder = reference.find_parent(class_="field--label-inline")
        label = holder.find(class_="field--label") if holder else None
        if value:
            fields["agency_reference"] = LabelValue(
                label=_text(label).replace("\n", " ") or "ID", value=value
            )
    tables: list[RecallTable] = []
    sections: list[RecallSection] = []
    for section in main.select("section.ar-section"):
        classes = section.get("class") or []
        if "ar-summary" in classes or "ar-additional-info" in classes:
            continue
        heading = section.find("h2")
        for table in section.find_all("table"):
            tables.append(_table(table))
            table.decompose()
        if heading is not None:
            title = _text(heading)
            heading.decompose()
        else:
            title = ""
        text = _text(section)
        if text:
            sections.append(RecallSection(heading=title, text=_cap(text)))
    background = main.select_one(".field--name-field-background")
    if background is not None:
        details = background.find_parent("details")
        summary = details.find("summary") if details else None
        text = _text(background)
        if text:
            sections.append(RecallSection(heading=_text(summary) or "Background", text=_cap(text)))
    fields["tables"] = tables
    fields["sections"] = sections
    return fields


def _parse_legacy(body: Tag) -> dict[str, Any]:
    details: list[LabelValue] = []
    for dl in body.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            label = _text(dt).replace("\n", " ").rstrip(" :")
            value = _text(dd).replace("\n", ", ") if isinstance(dd, Tag) else ""
            if label and value:
                details.append(LabelValue(label=label, value=value))
    tables = [_table(t) for t in body.find_all("table")]
    for table in body.find_all("table"):
        table.decompose()
    ident = next(
        (d.value for d in details if re.fullmatch(r"RA-\d+", d.value)),
        None,
    )
    # Header labels seen live: "Source of recall" / "Source" and
    # "Hazard classification" / "Classification du risque".
    source = next((d.value for d in details if _fold(d.label).startswith("source")), None)
    hazard = next(
        (
            d.value
            for d in details
            if _fold(d.label).startswith(("hazard classification", "classification du risque"))
        ),
        None,
    )
    return {
        "details": details,
        "tables": tables,
        "identification_number": ident,
        "published_by": source,
        "recall_class": hazard,
        "legacy_text": _cap(_text(body)) or None,
    }


def parse_page(page_html: str, nid: int, url: str, lang: str) -> dict[str, Any]:
    soup = BeautifulSoup(page_html, "html.parser")
    main = soup.find("main")
    if not isinstance(main, Tag):
        raise UpstreamError(f"recalls: page for {nid} has no <main> element.")
    heading = main.select_one("h1#wb-cont") or main.find("h1")
    nav = main.select_one("#wb-cont-nav")
    archived = main.select_one("#block-archived, section#archived") is not None
    legacy_body = main.select_one(".recall-alert-body")
    if main.select_one("section.ar-section") is not None:
        fields = _parse_current(main)
        layout = "current"
    elif legacy_body is not None:
        fields = _parse_legacy(legacy_body)
        layout = "legacy"
    else:
        raise NotFound(f"Node {nid} is not a recall or safety alert page.")
    fields.setdefault("alert_type", None)
    fields["alert_type"] = fields["alert_type"] or (_text(nav) or None)
    fields.update(
        recall_id=nid,
        url=url,
        lang=lang,
        layout=layout,
        title=_text(heading).replace("\n", " "),
        archived=archived,
    )
    fields["agency"] = _agency(fields.get("published_by"))
    return fields


async def get_recall(recall_id: int | str, lang: str = "en") -> RecallDetail:
    lang = _check_lang(lang)
    text = str(recall_id).strip()
    if text.upper().startswith("RA-"):
        raise InvalidInput(
            f"{text!r} is an identification number, not a recall_id; recall_id is the NID "
            "from recalls_search (for current pages it is the digits after 'RA-')."
        )
    if not text.isdigit():
        raise InvalidInput(f"recall_id must be the numeric NID from recalls_search, got {text!r}.")
    nid = int(text)
    (url, page_html), cached = await _fetch_page(nid, lang)
    fields = parse_page(page_html, nid, url, lang)
    return RecallDetail(
        **fields,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="recalls.RecallDetail",
            as_of=(
                datetime.combine(fields["last_updated"], datetime.min.time())
                if fields.get("last_updated")
                else None
            ),
            limits=(
                f"section text capped at {constants.TEXT_MAX_CHARS} characters, tables at "
                f"{constants.TABLE_ROWS_MAX} rows"
            ),
        ),
    )
