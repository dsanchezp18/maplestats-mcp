"""HTTP client for the Justice Laws Website XML service.

The ~5 MB index is parsed once into a compact list and cached. Document
XML is parsed with defusedxml. Section text is flattened into one line
per structural unit (subsection, paragraph, ...) prefixed with its
label, which keeps the statute's numbering readable without markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree

from maple_data_mcp.modules.justice_laws import constants
from maple_data_mcp.modules.justice_laws.schemas import (
    LawOutline,
    LawSearchResult,
    LawSection,
    LawSummary,
    SectionHeading,
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
_STRUCTURE = {
    "Subsection",
    "Paragraph",
    "Subparagraph",
    "Clause",
    "Subclause",
    "Definition",
    "ContinuedSectionSubsection",
    "ContinuedParagraph",
    "ContinuedSubparagraph",
    "ContinuedClause",
}


@dataclass(frozen=True)
class _Entry:
    uid: str
    kind: str
    lang: str
    title: str
    official_number: str | None
    current_to: date | None
    toc_url: str
    xml_url: str
    record_id: str | None
    other_id: str | None


async def _fetch(url: str) -> bytes:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=90.0)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise NotFound(f"justice_laws: nothing published at {url}.") from exc
        raise UpstreamError(
            f"justice_laws: {url} returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"justice_laws: {url} did not respond in time.") from exc
    return response.content


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _https(url: str) -> str:
    return url.replace("http://", "https://", 1)


def _parse_index(body: bytes) -> list[_Entry]:
    root = ElementTree.fromstring(body)
    entries: list[_Entry] = []
    for kind, tag in (("act", "Acts/Act"), ("regulation", "Regulations/Regulation")):
        for el in root.findall(tag):
            uid = (el.findtext("UniqueId") or "").strip()
            if not uid:
                continue
            entries.append(
                _Entry(
                    uid=uid,
                    kind=kind,
                    lang="fr" if el.findtext("Language") == "fra" else "en",
                    title=(el.findtext("Title") or uid).strip(),
                    official_number=el.findtext("OfficialNumber"),
                    current_to=_parse_date(el.findtext("CurrentToDate")),
                    toc_url=_https(el.findtext("LinkToHTMLToC") or ""),
                    xml_url=_https(el.findtext("LinkToXML") or ""),
                    record_id=el.get("id"),
                    other_id=el.get("olid"),
                )
            )
    return entries


async def _index() -> tuple[list[_Entry], bool]:
    async def fetch() -> list[_Entry]:
        return _parse_index(await _fetch(constants.INDEX_URL))

    return await cached_fetch("justice-laws:index", constants.CACHE_TTL_INDEX_SECONDS, fetch)


def _normalize(identifier: str) -> str:
    return re.sub(r"\s+", "", identifier).replace("/", "-").upper()


def _summary(entry: _Entry) -> LawSummary:
    return LawSummary(
        id=entry.uid,
        kind="act" if entry.kind == "act" else "regulation",
        title=entry.title,
        official_number=entry.official_number,
        current_to=entry.current_to,
        url=entry.toc_url,
    )


async def _resolve(identifier: str, lang: str) -> _Entry:
    """Find a document in the requested language from an id in either language."""
    key = _normalize(identifier)
    if not key:
        raise InvalidInput("law_id must not be empty.")
    entries, _ = await _index()
    found = next((e for e in entries if _normalize(e.uid) == key), None)
    if found is None:
        raise NotFound(f"No Act or regulation {identifier!r}. Use justice_laws_search.")
    if found.lang == lang:
        return found
    if found.kind == "act":
        twin = next((e for e in entries if e.uid == found.uid and e.lang == lang), None)
    else:
        twin = next((e for e in entries if e.record_id == found.other_id), None)
    return twin or found


async def search(
    query: str,
    *,
    kind: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: str = "en",
) -> LawSearchResult:
    """Match every word of `query` against titles and citations."""
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    words = [w for w in query.lower().split() if w]
    if not words:
        raise InvalidInput("query must not be empty.")
    entries, cached = await _index()
    normalized_query = _normalize(query)
    matches = [
        e
        for e in entries
        if e.lang == lang
        and (kind is None or e.kind == kind)
        and (
            _normalize(e.uid) == normalized_query
            or all(w in f"{e.title} {e.uid} {e.official_number or ''}".lower() for w in words)
        )
    ]

    # Exact citation hits first, then Acts before regulations, then shorter titles.
    matches.sort(
        key=lambda e: (_normalize(e.uid) != normalized_query, e.kind != "act", len(e.title))
    )
    return LawSearchResult(
        laws=[_summary(e) for e in matches[:limit]],
        total_matches=len(matches),
        returned_count=min(limit, len(matches)),
        query=query,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.INDEX_URL,
            cached=cached,
            schema_name="justice_laws.LawSearchResult",
            freshness="index cached 24h; each law states its own current-to date",
        ),
    )


async def _document(entry: _Entry) -> tuple[Element, bool]:
    async def fetch() -> bytes:
        return await _fetch(entry.xml_url)

    body, cached = await cached_fetch(
        f"justice-laws:doc:{entry.xml_url}", constants.CACHE_TTL_DOCUMENT_SECONDS, fetch
    )
    try:
        return ElementTree.fromstring(body), cached
    except ElementTree.ParseError as exc:
        raise UpstreamError(f"justice_laws: {entry.xml_url} is not valid XML.") from exc


def _lims(el: Element, name: str) -> str | None:
    return el.get(f"{constants.LIMS_NS}{name}")


def _text(el: Element | None) -> str | None:
    if el is None:
        return None
    joined = " ".join("".join(el.itertext()).split())
    return joined or None


def _body_sections(root: Element) -> list[tuple[Element, str | None]]:
    """Body sections in order, each with its nearest preceding heading."""
    body = root.find("Body")
    if body is None:
        return []
    out: list[tuple[Element, str | None]] = []
    heading: str | None = None
    for el in body.iter():
        if el.tag == "Heading":
            heading = _text(el.find("TitleText")) or heading
        elif el.tag == "Section":
            out.append((el, heading))
    return out


async def get_outline(law_id: str, lang: str = "en", offset: int = 0) -> LawOutline:
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    entry = await _resolve(law_id, lang)
    root, cached = await _document(entry)
    sections = _body_sections(root)
    headings = [
        SectionHeading(
            label=el.findtext("Label") or "",
            marginal_note=_text(el.find("MarginalNote")),
            heading=heading,
            last_amended=_parse_date(_lims(el, "lastAmendedDate")),
        )
        for el, heading in sections
    ]
    identification = root.find("Identification")
    return LawOutline(
        law=_summary(entry),
        long_title=_text(identification.find("LongTitle")) if identification is not None else None,
        last_amended=_parse_date(_lims(root, "lastAmendedDate")),
        in_force=None if root.get("in-force") is None else root.get("in-force") == "yes",
        section_count=len(headings),
        offset=offset,
        sections=headings[offset : offset + constants.OUTLINE_SECTIONS_MAX],
        truncated=len(headings) > offset + constants.OUTLINE_SECTIONS_MAX,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=entry.xml_url,
            cached=cached,
            schema_name="justice_laws.LawOutline",
        ),
    )


def _lines(el: Element, depth: int = 0) -> list[str]:
    parts = [el.findtext("Label") or ""]
    parts += [_text(t) or "" for t in el.findall("Text")]
    own = " ".join(p for p in parts if p)
    lines = [("  " * depth) + own] if own else []
    for child in el:
        if child.tag in _STRUCTURE:
            lines += _lines(child, depth + 1)
    return lines


def _section_url(entry: _Entry, label: str) -> str:
    stem = "art" if entry.lang == "fr" else "section"
    return entry.toc_url.replace("index.html", f"{stem}-{label}.html")


async def get_section(law_id: str, section: str, lang: str = "en") -> LawSection:
    label = section.strip()
    if not label:
        raise InvalidInput("section must not be empty.")
    entry = await _resolve(law_id, lang)
    root, cached = await _document(entry)
    found: Any = next((el for el, _ in _body_sections(root) if el.findtext("Label") == label), None)
    if found is None:
        raise NotFound(
            f"{entry.uid} has no section {label!r}. Use justice_laws_get_outline for labels."
        )
    text = "\n".join(_lines(found))
    truncated = len(text) > constants.SECTION_TEXT_MAX
    return LawSection(
        law=_summary(entry),
        label=label,
        marginal_note=_text(found.find("MarginalNote")),
        last_amended=_parse_date(_lims(found, "lastAmendedDate")),
        text=text[: constants.SECTION_TEXT_MAX],
        truncated=truncated,
        url=_section_url(entry, label),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=entry.xml_url,
            cached=cached,
            schema_name="justice_laws.LawSection",
            limits="unofficial consolidation; the Justice Laws Website version is authoritative",
        ),
    )
