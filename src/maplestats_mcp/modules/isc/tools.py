"""MCP tools for Indigenous Services Canada and CIRNAC publications."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.isc import client
from maplestats_mcp.modules.isc.schemas import (
    FirstNationList,
    FirstNationProfile,
    LongTermAdvisoryList,
    RegisteredPopulation,
    ShortTermAdvisoryList,
)

Lang = Literal["en", "fr"]


@tool
async def isc_search_first_nations(
    query: str = "",
    province: str = "",
    limit: int = 50,
    lang: Lang = "en",
) -> FirstNationList:
    """Find First Nations (bands) by name, band number or province (ISC).

    Use for: looking up a First Nation's band number before reading its
    profile, registered members or advisories; listing the
    First Nations of a region with their ISC region and how many members
    live on and off reserve. `query` matches words of the English or
    French name ("musqueam", "cree") or a band number ("550"); empty lists
    all. `province` is a code (ON, BC...) or a name. Reads ISC's yearly
    Indian Register counts (646 registry groups, at December 31).
    Keywords: First Nations, band number, Indian band, registry group,
    Indigenous communities, First Nations list, reserves, Indian Act,
    Indigenous Services Canada, registered Indians.
    Mots-clés : Premières Nations, numéro de bande, bande indienne,
    groupe du registre, communautés autochtones, liste des Premières
    Nations, réserves, Loi sur les Indiens, Services aux Autochtones
    Canada, Indiens inscrits.
    """
    return await client.search_first_nations(query, province=province, limit=limit, lang=lang)


@tool
async def isc_get_first_nation_profile(band_number: int, lang: Lang = "en") -> FirstNationProfile:
    """A First Nation's profile: name, address, tribal council, reserves, governance.

    Use for: the official name and contact address of a First Nation, its
    affiliated tribal council, its reserves, settlements and villages with
    their area in hectares, its governance (section 10 or 11 membership
    authority, election system such as the First Nations Elections Act or
    a custom code, chief and councillors with their terms) and its
    geographic and environmental indices (remoteness zone, nearest service
    centre). `band_number` comes from isc_search_first_nations (Musqueam is
    550). From CIRNAC's First Nation Profiles, in English or French.
    Keywords: First Nation profile, band profile, chief and council,
    tribal council, reserves, reserve land hectares, band governance,
    election system, custom election code, CIRNAC.
    Mots-clés : profil de Première Nation, profil de bande, chef et
    conseil, conseil tribal, réserves, superficie des réserves,
    administration de la bande, système électoral, code électoral
    coutumier, RCAANC.
    """
    return await client.get_first_nation_profile(band_number, lang=lang)


@tool
async def isc_get_registered_population(
    band_number: int, lang: Lang = "en"
) -> RegisteredPopulation:
    """A First Nation's registered population by sex and residence (Indian Act).

    Use for: how many people are registered with a First Nation under the
    Indian Act, how many live on their own reserve, on other reserves, on
    Crown land or off reserve, men and women, as of the latest month in the
    First Nation Profiles, with the yearly figures since 2023 from ISC's
    open dataset beside them. `band_number` comes from
    isc_search_first_nations. This is the Indian Register, not the census:
    census counts of people living in a community are Statistics Canada's
    (statcan_census_profile_).
    Keywords: registered population, Indian Register, status Indians,
    on-reserve population, off-reserve population, First Nation
    membership, band population, Indian Act registration, ISC.
    Mots-clés : population inscrite, Registre des Indiens, Indiens
    inscrits, population dans les réserves, population hors réserve,
    effectif de la Première Nation, population de la bande, inscription
    en vertu de la Loi sur les Indiens, SAC.
    """
    return await client.get_registered_population(band_number, lang=lang)


@tool
async def isc_list_drinking_water_advisories(
    status: Literal["current", "lifted", "all"] = "current",
    province: str = "",
    community: str = "",
    limit: int = 200,
    lang: Lang = "en",
) -> LongTermAdvisoryList:
    """Long-term drinking water advisories on First Nations public systems (ISC).

    Use for: which First Nations have a long-term drinking water advisory
    in effect (in place more than a year on a public system financially
    supported by ISC), since when, the system, the corrective measure and
    the project phase (feasibility, design, construction), and which were
    lifted since November 2015 and when.
    `status` picks current, lifted or all; `province` is a code or name;
    `community` matches a name or a band number. National counts come back
    with any filter. Short-term advisories: isc_list_short_term_advisories.
    Keywords: drinking water advisory, long-term advisory, boil water
    advisory, do not consume, First Nations, public system, lifted
    advisories, treatment plant, corrective measure.
    Mots-clés : avis concernant la qualité de l'eau potable, avis à long
    terme, avis d'ébullition de l'eau, avis de ne pas consommer, eau
    potable des Premières Nations, réseau d'aqueduc, avis levés, usine
    de traitement de l'eau.
    """
    return await client.list_drinking_water_advisories(
        status, province=province, community=community, limit=limit, lang=lang
    )


@tool
async def isc_list_short_term_advisories(
    province: str = "",
    community: str = "",
    active_only: bool = False,
    lang: Lang = "en",
) -> ShortTermAdvisoryList:
    """Short-term drinking water advisories in First Nations south of 60 (ISC).

    Use for: the boil water, do not consume and do not use advisories that
    ISC lists for First Nations in the Atlantic provinces, Quebec, Ontario,
    Manitoba, Saskatchewan and Alberta, in effect or revoked this month,
    with the system, date set, date revoked and population served.
    `province` is a code, a name or an ISC region ("Atlantic");
    `community` matches the First Nation or community; `active_only` keeps
    those in effect. British Columbia's are published by the First Nations
    Health Authority, not here.
    Keywords: short-term drinking water advisory, boil water advisory,
    do not consume advisory, do not use advisory, First Nations, south of
    60, revoked advisory, ISC.
    Mots-clés : avis à court terme concernant la qualité de l'eau potable,
    avis d'ébullition de l'eau, avis de ne pas boire l'eau, avis de
    non-utilisation, qualité de l'eau des Premières Nations, avis levé,
    eau potable au sud du 60e parallèle, SAC.
    """
    return await client.list_short_term_advisories(
        province=province, community=community, active_only=active_only, lang=lang
    )
