"""MCP tools for Open North's Represent API (elected officials and districts)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.represent import client, constants
from maplestats_mcp.modules.represent.schemas import (
    BoundarySetList,
    Level,
    PointLookup,
    PostcodeLookup,
    RepresentativeSearchResult,
    RepresentativeSetList,
)


@tool
async def represent_lookup_postcode(
    postcode: str,
    sets: str | None = None,
    include_set_details: bool = True,
    lang: Literal["en", "fr"] = "en",
) -> PostcodeLookup:
    """Find the MP, MLA and mayor or councillors for a Canadian postal code.

    Use for: who represents a postal code (e.g. T5J0N3, H3B 4W8), and which
    federal, provincial and municipal electoral districts it falls in, with
    each district set's licence and last-updated date. A postal code can
    match several districts (see notes); for exact results use
    represent_lookup_point. sets optionally limits districts to
    comma-separated boundary set slugs (e.g.
    federal-electoral-districts-2023-representation-order, the current
    federal map; federal-electoral-districts with no year is the old 2013
    order). With sets, only representatives of the current sets come back.
    Source is Open North (unofficial, 60 requests a minute); representative
    data is scraped from official sites, its licence is unverified and some
    records are stale. Complements the ourcommons_ tools.
    Keywords: postal code, postcode, elected officials, representative, MP,
    MLA, mayor, councillor, riding, electoral district, ward, who is my MP.
    Mots-clés : code postal, élus, représentant, député, maire, conseiller,
    circonscription, district électoral, quartier, qui est mon député.
    """
    return await client.lookup_postcode(
        postcode, sets=sets, include_set_details=include_set_details, lang=lang
    )


@tool
async def represent_lookup_point(
    latitude: float,
    longitude: float,
    include_set_details: bool = True,
    lang: Literal["en", "fr"] = "en",
) -> PointLookup:
    """Find the representatives and electoral districts at a latitude and longitude.

    Use for: the exact riding, ward and representatives of a location (e.g.
    latitude 45.524, longitude -73.596), when a postal code is too coarse
    or a geocoded address is at hand. A point falls in exactly one district
    per boundary set. Each set's licence and last-updated date are
    included. Source is Open North (unofficial, 60 requests a minute);
    representative data is scraped and its licence is unverified.
    Keywords: latitude, longitude, coordinates, point lookup, riding, ward,
    electoral district, boundary, elected officials, MP, MLA, mayor,
    geocode.
    Mots-clés : latitude, longitude, coordonnées, recherche par point,
    circonscription, quartier, district électoral, limites, élus, député,
    maire, géocodage.
    """
    return await client.lookup_point(
        latitude, longitude, include_set_details=include_set_details, lang=lang
    )


@tool
async def represent_search_representatives(
    name: str | None = None,
    office: str | None = None,
    district: str | None = None,
    party: str | None = None,
    level: Level | None = None,
    representative_set: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: Literal["en", "fr"] = "en",
) -> RepresentativeSearchResult:
    """Search about 3,800 Canadian elected officials by name, office, district, party or level.

    Use for: finding a representative by name (substring, e.g. "Carney"),
    all mayors (office "Mayor"), all MLAs of a party, councillors of a
    district or city, or every federal or provincial member. level is
    federal, provincial or municipal; representative_set is a set slug
    from represent_list_representative_sets (e.g. toronto-city-council).
    party is a substring of the party name; common abbreviations and
    French or English names also work (NDP/NPD, UCP, CAQ, PLQ, PQ, QS, BQ,
    PC, Green/Vert, Liberal/Libéral).
    Each record shows contact details, offices and the official page it was
    scraped from (source_url); records are unverified and some sets are
    stale. Source is Open North (unofficial). Complements ourcommons_.
    Keywords: search representatives, elected officials, MP, MLA, mayor,
    councillor, party, politician, contact, email, constituency office,
    municipal council.
    Mots-clés : chercher élus, représentants, député, maire, conseiller,
    parti, politicien, courriel, bureau de circonscription, conseil
    municipal, assemblée nationale.
    """
    return await client.search_representatives(
        name=name,
        office=office,
        district=district,
        party=party,
        level=level,
        representative_set=representative_set,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def represent_list_boundary_sets(
    domain: str | None = None,
    name: str | None = None,
    with_details: bool = True,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: Literal["en", "fr"] = "en",
) -> BoundarySetList:
    """List electoral boundary sets with their licence and last-updated date.

    Use for: finding which boundary sets exist (524: federal and provincial
    electoral districts, municipal wards, census divisions and
    subdivisions), judging how stale one is (last_updated, possibly_stale)
    and reading its licence_url before reuse. Filter by domain (Canada, a
    province, or a city such as "Toronto") or by name (e.g. "ward"). With
    with_details true, up to 25 sets per call are fetched individually
    because the list itself carries no licence or date; page with offset.
    Source is Open North (unofficial); licences differ per set.
    Keywords: boundary sets, electoral districts, wards, ridings, licence,
    last updated, stale, shapefile source, census subdivisions, open
    government licence.
    Mots-clés : ensembles de limites, circonscriptions, quartiers,
    licence, dernière mise à jour, périmé, source géographique,
    subdivisions de recensement, licence du gouvernement ouvert.
    """
    return await client.list_boundary_sets(
        domain=domain,
        name=name,
        with_details=with_details,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def represent_list_representative_sets(
    level: Level | None = None,
    lang: Literal["en", "fr"] = "en",
) -> RepresentativeSetList:
    """List the 121 sets of representatives (House of Commons, legislatures, city councils).

    Use for: finding the slug of a legislature or council to pass to
    represent_search_representatives (representative_set), and checking
    which cities and provinces are covered at all. level is federal,
    provincial or municipal. Coverage is partial: only some municipal
    councils are included, and sets carry no update date. Source is Open
    North (unofficial).
    Keywords: representative sets, legislature, city council, House of
    Commons, coverage, which cities, municipal council list, assembly,
    provincial legislature.
    Mots-clés : ensembles d'élus, assemblée législative, conseil
    municipal, Chambre des communes, couverture, quelles villes, liste des
    conseils, assemblée nationale.
    """
    return await client.list_representative_sets(level=level, lang=lang)
