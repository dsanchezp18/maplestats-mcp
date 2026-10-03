"""MCP tools for StatCan's extra .Stat Suite SDMX spaces.

Two spaces beyond the main table service (sdmx_get_data): `ccei`, the Canadian
Centre for Energy Information (ECCC greenhouse-gas inventory and projections, air
pollutants, NRCan energy efficiency, plus StatCan table mirrors) and `stcshared`,
the shared space (rural, CITH internal trade, QOL, PCEIP, MEA, ISC drinking-water
advisories). Data is SDMX-CSV 2.0, structures SDMX-JSON 1.0.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.sdmx_spaces import client
from maplestats_mcp.modules.statcan.sdmx_spaces.schemas import (
    SpaceData,
    SpaceFlowList,
    SpaceSearch,
    SpaceStructure,
)

Lang = Literal["en", "fr"]
Space = Literal["ccei", "stcshared"]
Tenant = Literal["ccei", "rural", "cith", "pceip"]


@tool
async def sdmx_space_list_flows(
    space: Space = "ccei",
    query: str = "",
    agency: str = "",
    limit: int = 50,
    offset: int = 0,
    lang: Lang = "en",
) -> SpaceFlowList:
    """List the dataflows of one of Statistics Canada's extra SDMX spaces:
    `ccei` (Canadian Centre for Energy Information, 245 flows) or
    `stcshared` (shared space, 238 flows), filtered by words and agency.

    Use for: finding a dataflow id in the energy information space (ECCC
    greenhouse gas inventory and projections, air pollutants, black carbon,
    NRCan energy efficiency indicators) or the shared space (CITH internal
    trade, quality of life, rural, PCEIP education and employment, MEA, ISC
    advisories). `query` needs every word in the id,
    name or description; `agency` is e.g. CCEI, STC, CA1.CCEI, CITH, QOL,
    PCEIP, RURAL, MEA. Returns `flow` (agency,id,version) to pass to
    sdmx_space_get_structure and sdmx_space_get_data. Unlike
    sdmx_space_search it sees every flow, including QOL and MEA. Every flow
    is annotated NonProductionDataflow; provenance.licence carries the
    Statistics Canada Open Licence note and the partner-department caveat.
    The main table service is sdmx_get_data.
    Keywords: statcan, sdmx, ccei, energy information, greenhouse gas,
    dataflows, stcshared, CITH, internal trade, ISC advisories,
    ECCC, NRCan.
    Mots-clés : statcan, sdmx, ccie, information sur l'énergie, gaz à effet
    de serre, flux de données, commerce intérieur, avis sur l'eau potable,
    qualité de vie, ECCC, RNCan.
    """
    return await client.list_flows(
        space, query=query, agency=agency, limit=limit, offset=offset, lang=lang
    )


@tool
async def sdmx_space_search(
    query: str,
    space: Space = "ccei",
    tenant: Tenant | None = None,
    filters: dict[str, list[str]] | None = None,
    limit: int = 10,
    offset: int = 0,
    lang: Lang = "en",
) -> SpaceSearch:
    """Full-text and facet search over the dataflows of Statistics Canada's
    CCEI (energy) and shared SDMX spaces, using the sdmx-sfs search service.

    Use for: finding a dataflow by topic words, such as greenhouse gas
    emissions by province, GHG projections, air pollutants, black carbon,
    energy efficiency, electricity, internal trade or rural indicators.
    Hits give `flow` (agency,id,version), the
    dimension names and last update; `facets` lists topic, geography and
    frequency values with a `filter_value` to pass back in `filters`
    (for example {"Frequency": ["0|Annual#A#"]}). `tenant` narrows the shared
    space to rural, cith or pceip. Only indexed flows are searched (122 of 245
    in ccei; none of QOL or MEA in stcshared): use sdmx_space_list_flows for
    the rest. limit + offset is capped at 50.
    Keywords: statcan, sdmx, search, ccei, energy, greenhouse gas, emissions,
    air pollutants, black carbon, energy efficiency, facets, dataflows.
    Mots-clés : statcan, sdmx, recherche, ccie, énergie, gaz à effet de
    serre, émissions, polluants atmosphériques, carbone noir, efficacité
    énergétique, facettes, flux de données.
    """
    return await client.search_flows(
        space, query, tenant=tenant, filters=filters, limit=limit, offset=offset, lang=lang
    )


@tool
async def sdmx_space_get_structure(
    flow: str,
    space: Space = "ccei",
    dimension: str = "",
    code_query: str = "",
    limit: int = 100,
    offset: int = 0,
    lang: Lang = "en",
) -> SpaceStructure:
    """Browse one dataflow of the CCEI or shared SDMX space: its dimensions in
    key order, the codes that have data, the period range and the size.

    Use for: building a key for sdmx_space_get_data. `flow` is a dataflow id
    (GHG_IPCC_TABLE), agency,id (CCEI,GHG_IPCC_TABLE) or agency,id,version.
    `key_order` lists the dimensions as the dot-separated key expects them.
    Each dimension's codes are only those with data (codelist_size is the
    whole codelist) and are paged by `limit`/`offset`; `dimension` returns
    one dimension and `code_query` keeps codes whose name contains the text
    (for example Alberta, or CO2). Also gives start_period, end_period and
    the observation count. Flagged non_production for every flow so far.
    Keywords: statcan, sdmx, structure, dimensions, codes, codelist, key,
    ccei, energy information, dataflow, availability.
    Mots-clés : statcan, sdmx, structure, dimensions, codes, liste de codes,
    clé, ccie, information sur l'énergie, flux de données, disponibilité.
    """
    return await client.get_structure(
        space,
        flow,
        dimension=dimension,
        code_query=code_query,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def sdmx_space_get_data(
    flow: str,
    key: str,
    space: Space = "ccei",
    start_period: str | None = None,
    end_period: str | None = None,
    last_n_observations: int | None = None,
    max_rows: int = 1000,
    lang: Lang = "en",
) -> SpaceData:
    """Get observations from a dataflow of the CCEI (energy) or shared SDMX
    space, as series with their attributes (SDMX-CSV 2.0).

    Use for: ECCC National Inventory greenhouse gas emissions by province and
    IPCC category, GHG projections, air pollutants, NRCan energy efficiency
    indicators, ISC long-term advisories, CITH internal trade.
    `key` has one segment per dimension in `key_order` order (see
    sdmx_space_get_structure), '+' for several codes, empty for a wildcard:
    A.CA_AB.0.CO2EQ. A whole large flow ("all", or only wildcards) is
    refused because the service times out; filter at least one dimension.
    With no period argument the LATEST 12 observations per series are
    returned; `last_n_observations` changes that, `start_period`/`end_period`
    (2020, 2020-03, 2020-Q1) give a range. Caps: 500 rows per series (newest
    kept), 200 series, `max_rows` (default 1000, max 5000) in total;
    provenance.limits records any cut. Flows are NonProduction annotated.
    Keywords: statcan, sdmx, data, observations, ccei, greenhouse gas,
    emissions, projections, air pollutants, ISC advisories,
    internal trade.
    Mots-clés : statcan, sdmx, données, observations, ccie, gaz à effet de
    serre, émissions, projections, polluants atmosphériques, avis sur l'eau
    potable, commerce intérieur.
    """
    return await client.get_data(
        space,
        flow,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n_observations=last_n_observations,
        max_rows=max_rows,
        lang=lang,
    )
