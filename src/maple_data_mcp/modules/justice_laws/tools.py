"""MCP tools for consolidated federal Acts and regulations (Justice Laws Website)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.justice_laws import client, constants
from maple_data_mcp.modules.justice_laws.schemas import (
    DocumentKind,
    LawOutline,
    LawSearchResult,
    LawSection,
)

Lang = Literal["en", "fr"]


@tool
async def justice_laws_search(
    query: str,
    kind: DocumentKind | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> LawSearchResult:
    """Search Canada's consolidated federal Acts and regulations by title or citation.

    Use for: finding the id of a statute or regulation, e.g.
    "access to information", "Criminal Code", "C-46", or "SOR/2007-151".
    Every word must appear in the title or citation; set `kind` to "act"
    or "regulation" to narrow. `lang="fr"` searches and returns French
    titles (e.g. "Code criminel").
    Keywords: federal law, statute, Act, regulation, legislation,
    Justice Laws, consolidated, SOR, Criminal Code, Parliament.
    Mots-clés : loi fédérale, loi, règlement, législation, lois
    codifiées, DORS, Code criminel, Justice Canada, texte de loi.
    """
    return await client.search(query, kind=kind, limit=limit, lang=lang)


@tool
async def justice_laws_get_outline(law_id: str, offset: int = 0, lang: Lang = "en") -> LawOutline:
    """Get a federal Act's or regulation's outline: sections, headings, and amendment dates.

    Use for: listing section numbers with their marginal notes and the
    heading they fall under, plus the long title and last-amended date,
    before reading a section with justice_laws_get_section. `law_id` is
    a citation from justice_laws_search (English or French form).
    Outlines return 400 sections at a time; when `truncated`, call again
    with `offset` (the Criminal Code has ~1,700 sections).
    Keywords: statute outline, table of contents, sections, headings,
    marginal notes, last amended, federal Act, regulation.
    Mots-clés : plan de la loi, table des matières, articles,
    intertitres, notes marginales, dernière modification, règlement.
    """
    return await client.get_outline(law_id, lang, offset)


@tool
async def justice_laws_get_section(law_id: str, section: str, lang: Lang = "en") -> LawSection:
    """Get the current consolidated text of one section of a federal Act or regulation.

    Use for: quoting or checking what a provision says now, e.g.
    law_id="A-1", section="4" (Access to Information Act, right of
    access). Subsections and paragraphs keep their labels. The Justice
    Laws Website remains the authoritative version.
    Keywords: section text, provision, statute, legal text, current
    law, clause, subsection, federal Act, regulation, wording.
    Mots-clés : texte de l'article, disposition, loi, texte juridique,
    droit en vigueur, paragraphe, alinéa, règlement, libellé.
    """
    return await client.get_section(law_id, section, lang)
