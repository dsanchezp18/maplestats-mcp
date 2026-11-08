"""MCP tools for DFO commercial fisheries landings (open.canada.ca, OGL - Canada)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.dfo_landings import client
from maplestats_mcp.modules.dfo_landings.schemas import Fishery, Landings, LandingsCatalogue

Lang = Literal["en", "fr"]


@tool
async def dfo_landings_list_tables(lang: Lang = "en") -> LandingsCatalogue:
    """List DFO's commercial fisheries landings tables: years available, units and files.

    Two Fisheries and Oceans Canada datasets on open.canada.ca (Open
    Government Licence - Canada): sea fisheries landings 1990-2024 and
    freshwater landings 1990-2019, with each file's year, language and URL.
    Read the rows with dfo_landings_get_landings.
    Use for: which years of Canadian fish landings exist, the source files
    for DFO commercial catch statistics, citing the open data record.
    Keywords: DFO, Fisheries and Oceans Canada, commercial fisheries,
    landings, catch statistics, fish, seafood, open data, years available,
    freshwater fisheries, sea fisheries.
    Mots-clés : MPO, Pêches et Océans Canada, pêches commerciales,
    débarquements, statistiques de capture, poisson, fruits de mer, données
    ouvertes, pêches en eau douce, pêches maritimes.
    """
    return await client.list_tables(lang=lang)


@tool
async def dfo_landings_get_landings(
    fishery: Fishery = "sea",
    year: int | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    region: str | None = None,
    species: str | None = None,
    species_group: str | None = None,
    include_totals: bool = True,
    limit: int = 200,
    lang: Lang = "en",
) -> Landings:
    """Canadian commercial fish landings by year, province, species: quantity (tonnes) and value ($).

    Fisheries and Oceans Canada (DFO) landings as tidy rows. fishery="sea":
    1990-2024 by Atlantic province (NL, PE, NS, NB, QC), BC, the Atlantic
    total and Canada, with species groups (Groundfish, Pelagics, Shellfish,
    Other) and species such as Lobster, Snow crab, Shrimp, Herring, Cod.
    fishery="freshwater": 1990-2019 by province or territory, species such
    as Yellow Pickerel (walleye), Whitefish, Perch (up to 10 years a call).
    Default: the latest year. Filters match part of a name, accents
    optional; region also accepts 'Canada'. lang="fr" reads DFO's French
    files (French species and province names). Licence: Open Government
    Licence - Canada.
    Use for: value of lobster landings in Nova Scotia, Canada's fish catch
    by species, snow crab landed value, freshwater fishery in Manitoba,
    fisheries trends since 1990.
    Keywords: DFO, commercial fisheries, landings, landed value, catch,
    tonnes, lobster, snow crab, shrimp, cod, herring, scallop, salmon,
    walleye, seafood, province, species.
    Mots-clés : MPO, pêches commerciales, débarquements, valeur au
    débarquement, captures, tonnes, homard, crabe des neiges, crevette,
    morue, hareng, pétoncle, doré, produits de la mer, province, espèce.
    """
    return await client.get_landings(
        fishery,
        year,
        start_year,
        end_year,
        region,
        species,
        species_group,
        include_totals,
        limit,
        lang=lang,
    )
