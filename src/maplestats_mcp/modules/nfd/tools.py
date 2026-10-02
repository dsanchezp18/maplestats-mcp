"""MCP tools for the National Forestry Database (CCFM / Canadian Forest Service).

`lang` picks the label language of the answer ("fr": French jurisdiction and
category names, units and quality-code meanings). Filters accept the English
or the French spelling, ignoring case and accents.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.nfd import client, constants
from maplestats_mcp.modules.nfd.schemas import (
    NfdCommentsResult,
    NfdQueryResult,
    NfdTableDescription,
    NfdTableList,
)

Lang = Literal["en", "fr"]
Filter = str | list[str] | None


@tool
async def nfd_list_tables(section: str | None = None, lang: Lang = "en") -> NfdTableList:
    """List the National Forestry Database tables (forest fires, harvest, wood supply, pests).

    Use for: the first step before nfd_describe_table or nfd_query_table:
    the 25 tables of the Canadian Council of Forest Ministers' National
    Forestry Database with their number, topic and title, and links to the
    CSV, Excel, data dictionary and comments files. Topics: Wood Supply
    (2), Forest Fires (3.1.1 number of fires and 3.2.1 area burned by
    cause, month and fire size class; 3.3 property losses), Forest Insects
    (4), Harvest (5.1 volume, 5.2 area), Regeneration (6.1 to 6.6: site
    preparation, scarification, seeding, planting, stand tending), Revenues
    (7) and Pest Control (8.1 insecticides, 8.2 herbicides). `section`
    keeps tables whose topic or title contains the text, e.g. 'fires' or
    'planted'. `lang="fr"` gives French titles.
    Keywords: National Forestry Database, NFD, CCFM, forest statistics,
    forest fires, area burned, timber harvest, wood supply, reforestation,
    insect defoliation, pesticide use, forestry tables, Canadian Forest
    Service.
    Mots-clés : Base nationale de données forestières, BNDF, CCMF,
    statistiques forestières, incendies de forêt, superficie brûlée,
    récolte de bois, approvisionnement en bois, reboisement, défoliation
    par les insectes, pesticides, Service canadien des forêts.
    """
    return await client.list_tables(section, lang=lang)


@tool
async def nfd_describe_table(table_id: str, lang: Lang = "en") -> NfdTableDescription:
    """Describe one National Forestry Database table: columns, units, jurisdictions and quality codes.

    Use for: the step before nfd_query_table. Gives the table's data
    dictionary (title, source agency, last update), the unit of the value,
    the years each province or territory covers, every category column
    (`dimensions`, e.g. cause, month, tenure, species group, treatment,
    product) with its values, the data-quality codes in use (a actual,
    E and e estimated, p preliminary, r revised, u and U not available, n
    not applicable, s too small) and checked quirks of that file. `table_id`
    is the number from nfd_list_tables, e.g. '3.2.1' (area burned by
    cause), '5.1' (roundwood volume harvested), '6.4' (seedlings planted),
    '7' (timber revenues). `lang="fr"` gives French labels.
    Keywords: NFD table description, forest fire cause classes, tenure,
    species group, data dictionary, data qualifier, hectares burned,
    harvest categories, forestry data codebook, jurisdictions covered.
    Mots-clés : description de tableau, dictionnaire de données,
    qualificatifs de données, origine des incendies, groupe d'espèces,
    tenure, hectares brûlés, catégories de récolte, juridictions,
    Base nationale de données forestières.
    """
    return await client.describe_table(table_id, lang=lang)


@tool
async def nfd_query_table(
    table_id: str,
    province: Filter = None,
    year_from: int | None = None,
    year_to: int | None = None,
    filters: dict[str, Filter] | None = None,
    group_by: list[str] | None = None,
    drop_missing: bool = False,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> NfdQueryResult:
    """Get National Forestry Database rows: wildfire, harvest, planting, insects, revenues by province.

    Use for: area burned and number of wildfires by cause (human or
    natural), month or fire size class; timber harvested (cubic metres) by
    category, species group and tenure; area harvested by method; wood
    supply; seedlings planted and area planted, seeded, scarified or
    tended; insect defoliation by species; timber revenues; insecticide and
    herbicide use, by province or territory and year (1940 to 2025 by
    table; 1990 on for fires). `province` is a code or name ('BC',
    'Alberta', 'Colombie-Britannique'); `filters` maps a column from
    nfd_describe_table to a value or list, e.g. {'cause': 'Natural cause'}
    or {'tenure': ['Provincial land', 'Private land']}. `group_by` (e.g.
    ['year'], ['jurisdiction'], ['year', 'cause']) sums values over the
    other columns; without it rows come as published, with null for a
    missing figure and its quality code, never 0. Rows are in year order;
    past `limit` the latest rows are dropped. Every row carries its unit.
    `lang="fr"` gives French labels.
    Keywords: wildfire area burned by province, number of fires by cause,
    forest fires Canada, timber harvest volume, roundwood harvested,
    seedlings planted, insect defoliation, mountain pine beetle, forest
    revenues, herbicide use, National Forestry Database, hectares.
    Mots-clés : superficie brûlée par province, nombre d'incendies par
    origine, incendies de forêt au Canada, volume de bois récolté, bois
    rond, semis plantés, défoliation par les insectes, dendroctone du pin,
    revenus forestiers, herbicides, Base nationale de données
    forestières, hectares.
    """
    return await client.query_table(
        table_id,
        province=province,
        year_from=year_from,
        year_to=year_to,
        filters=filters,
        group_by=group_by,
        drop_missing=drop_missing,
        limit=limit,
        lang=lang,
    )


@tool
async def nfd_table_comments(
    table_id: str,
    province: Filter = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 50,
    lang: Lang = "en",
) -> NfdCommentsResult:
    """Read the agencies' comments and footnotes for a National Forestry Database table.

    Use for: how a province or territory compiled a series: definition
    changes, years carried forward, methods, what a footnote letter on a
    label means ('*b'), e.g. why a harvest or wood supply figure changed.
    Comments come per jurisdiction and year; identical text is merged with
    the years it applies to. Six fire tables (3.1.1 to 3.2.3) have none.
    `province` takes a code or name; `lang="fr"` reads the French sheet.
    Keywords: forestry data comments, footnotes, methodology notes, data
    notes by province, allowable annual cut, definitions, series break,
    National Forestry Database, harvest methods, data caveats.
    Mots-clés : commentaires sur les données, renvois, notes
    méthodologiques, notes par province, possibilité annuelle de coupe,
    définitions, rupture de série, Base nationale de données
    forestières, méthodes de récolte, limites des données.
    """
    return await client.table_comments(
        table_id,
        province=province,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        lang=lang,
    )
