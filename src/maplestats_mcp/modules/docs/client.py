"""List and read the server's docs:// resources for a tool call.

The server is passed in (the tool's Context gives it), so these read exactly
what a client's resources/read would: the same providers, lazy module loading
included. Only docs:// pages are served; no other resource scheme is
registered live, and this tool is not a general resource proxy.
"""

from __future__ import annotations

import re

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError

from maplestats_mcp.modules.docs.schemas import DocsPage, DocsPageList, DocsPageText
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.models import Provenance

SCHEME = "docs://"

# An English page's description names its French twin as "French version:
# docs://..." (tests/test_bilingual_docs.py keeps the twins in step).
_FRENCH_TWIN = re.compile(r"French version:\s*(docs://[a-z0-9/_-]+)")


def _provenance(uri: str, schema: str, lang: str) -> Provenance:
    return make_provenance(
        source="maplestats-docs",
        url=uri,
        cached=False,
        schema_name=schema,
        lang=lang,
    )


async def _pages(server: FastMCP) -> list[DocsPage]:
    resources = await server.list_resources()
    pages = {
        str(r.uri): DocsPage(uri=str(r.uri), description=(r.description or "").strip() or None)
        for r in resources
        if str(r.uri).startswith(SCHEME)
    }
    return [pages[uri] for uri in sorted(pages)]


def _twin(page: DocsPage) -> str | None:
    match = _FRENCH_TWIN.search(page.description or "")
    return match.group(1) if match else None


async def list_pages(server: FastMCP, lang: str = "en") -> DocsPageList:
    """Pages in the call's language: an English page is replaced by its French twin."""
    pages = await _pages(server)
    twins = {twin for page in pages if (twin := _twin(page))}
    if lang == "fr":
        uris = {page.uri for page in pages}
        pages = [page for page in pages if (_twin(page) or "") not in uris]
    else:
        pages = [page for page in pages if page.uri not in twins]
    return DocsPageList(
        pages=pages,
        total_count=len(pages),
        provenance=_provenance("docs://", "docs.DocsPageList", lang),
    )


async def read_page(server: FastMCP, uri: str, lang: str = "en") -> DocsPageText:
    uri = uri.strip()
    if not uri.startswith(SCHEME):
        raise_typed(
            InvalidInput,
            f"uri must start with {SCHEME} (got {uri!r}); docs_list_resources lists the pages."
            if lang != "fr"
            else f"l'uri doit commencer par {SCHEME} (reçu {uri!r}) ; "
            "docs_list_resources énumère les pages.",
            lang,
        )
    pages = {page.uri: page for page in await _pages(server)}
    if uri not in pages:
        nearby = sorted(u for u in pages if u.split("/")[2:3] == uri.split("/")[2:3])
        hint = ", ".join(nearby) if nearby else "docs_list_resources"
        raise_typed(
            NotFound,
            f"no page {uri!r}; try {hint}."
            if lang != "fr"
            else f"aucune page {uri!r} ; essayez {hint}.",
            lang,
        )
    twin = _twin(pages[uri])
    if lang == "fr" and twin is not None and twin in pages:
        uri = twin
    try:
        result = await server.read_resource(uri)
    except NotFoundError:
        raise_typed(NotFound, f"no page {uri!r}.", lang)
    text = "".join(
        c.content if isinstance(c.content, str) else c.content.decode("utf-8", "replace")
        for c in result.contents
    )
    return DocsPageText(
        uri=uri,
        text=text,
        provenance=_provenance(uri, "docs.DocsPageText", lang),
    )
