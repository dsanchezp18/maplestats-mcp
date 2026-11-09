"""docs_list_resources and docs_read_resource: the docs:// pages as tools."""

from __future__ import annotations

from typing import Literal

from fastmcp import Context
from fastmcp.tools import tool

from maplestats_mcp.modules.docs import client
from maplestats_mcp.modules.docs.schemas import DocsPageList, DocsPageText

Lang = Literal["en", "fr"]


@tool
async def docs_read_resource(uri: str, ctx: Context, lang: Lang = "en") -> DocsPageText:
    """Read one of this server's docs:// pages as text, e.g.
    docs://cmhc/gotchas, docs://cmhc/rms-methodology, docs://statcan/addressing
    or docs://catalogue.

    Use for: opening a docs:// page a tool description or result tells you
    to read, when your client does not offer MCP resources. With
    lang="fr" an English page that has a French version returns that
    version. docs_list_resources lists every page.
    Keywords: docs, documentation, read resource, gotchas, methodology,
    guide, help page, catalogue, reference, known quirks, how to use.
    Mots-clés : documentation, lire une ressource, pièges, méthodologie,
    guide, page d'aide, catalogue, référence, particularités, mode d'emploi.
    """
    return await client.read_page(ctx.fastmcp, uri, lang)


@tool
async def docs_list_resources(ctx: Context, lang: Lang = "en") -> DocsPageList:
    """List this server's docs:// pages, each with a one-line description
    (the French versions with lang="fr").

    Use for: finding the documentation page for a source (gotchas,
    well-known series or categories, survey methodology, addressing
    rules, the module catalogue) before reading it with
    docs_read_resource, when your client does not offer MCP resources.
    Keywords: docs, documentation, list resources, pages, gotchas,
    methodology, guide, help, catalogue, reference.
    Mots-clés : documentation, liste des ressources, pages, pièges,
    méthodologie, guide, aide, catalogue, référence, mode d'emploi.
    """
    return await client.list_pages(ctx.fastmcp, lang)
