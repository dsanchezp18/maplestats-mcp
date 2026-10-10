"""MCP tools for the CRA registered charities lookup."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cra_charities import client
from maplestats_mcp.modules.cra_charities.schemas import (
    CharityDetail,
    CharityDirectors,
    CharitySearchResult,
)

Lang = Literal["en", "fr"]


@tool
async def cra_charities_search(
    query: str = "",
    province: str = "",
    designation: str = "",
    limit: int = 20,
    offset: int = 0,
    lang: Lang = "en",
) -> CharitySearchResult:
    """Search Canada's registered charities (CRA T3010 annual list) by name words, city,
    province code (ON, QC...) and designation (A public foundation, B private foundation,
    C charitable organization). A business number as the query is an exact lookup.

    Use for: finding a charity by name, listing charities in a city or province, checking
    whether an organization appears on the latest CRA list of charities, getting its
    business number. Words match any text field, so "food bank toronto" works. The list is
    the latest annual file, not CRA's live registry.
    Keywords: charity, registered charity, charities list, CRA, T3010, business number,
    nonprofit, foundation, charitable organization, donee, registration number, RR0001.
    Mots-clés : organisme de bienfaisance, organisme enregistré, liste des organismes de
    bienfaisance, ARC, T3010, numéro d'entreprise, OSBL, fondation, donataire reconnu,
    numéro d'enregistrement, recherche par nom.
    """
    return await client.search_charities(query, province, designation, limit, offset, lang)


@tool
async def cra_charities_get_charity(business_number: str, lang: Lang = "en") -> CharityDetail:
    """One registered charity by business number (9 digits or 119219814RR0001): legal name,
    address, designation, category codes, latest fiscal period end and declared programs.

    Use for: verifying a charity from its business number, getting its address and type
    (foundation or charitable organization), seeing when its latest return period ended.
    Keywords: charity lookup, business number, BN, registration number, CRA charity,
    designation, foundation, fiscal period end, charitable programs, T3010, verify charity.
    Mots-clés : fiche d'un organisme de bienfaisance, numéro d'entreprise, NE, numéro
    d'enregistrement, ARC, désignation, fondation, fin d'exercice, programmes de
    bienfaisance, T3010, vérifier un organisme.
    """
    return await client.get_charity(business_number, lang)


@tool
async def cra_charities_get_directors(business_number: str, lang: Lang = "en") -> CharityDirectors:
    """Directors and officers a charity reported on its latest T3010 return, by business
    number: names, positions, arm's-length status and start and end dates.

    Use for: seeing who sits on a charity's board, officers' positions and tenure, whether
    a person is a director of a given charity (published open data, per CRA return).
    Keywords: charity directors, officers, board, trustees, T3010, CRA, business number,
    governance, position, arm's length, charity board members.
    Mots-clés : administrateurs d'un organisme de bienfaisance, dirigeants, conseil
    d'administration, fiduciaires, T3010, ARC, numéro d'entreprise, gouvernance, poste,
    lien de dépendance, membres du conseil.
    """
    return await client.get_directors(business_number, lang)
