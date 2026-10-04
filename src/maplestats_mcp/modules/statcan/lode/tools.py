"""MCP tools for StatCan's LODE open databases and accessibility products."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.lang import use_lang
from maplestats_mcp.modules.statcan.lode import client, constants
from maplestats_mcp.modules.statcan.lode.schemas import (
    LodeDatabaseList,
    LodeDescription,
    LodeFileList,
    LodeMemberPreview,
    LodeQueryResult,
    LodeZipListing,
)


@tool
async def statcan_lode_list_databases(lang: Literal["en", "fr"] = "en") -> LodeDatabaseList:
    """List the LODE open databases with versions and licences.

    Use for: which open facility, building and address datasets exist
    (healthcare ODHF, sports ODSRF, buildings ODB, schools ODEF, cultural
    ODCAF, addresses ODA) plus remoteness, proximity and the National
    Address Register. Returns keys for the other LODE tools.
    Keywords: open database, LODE, healthcare facilities, hospitals, building
    footprints, schools, recreation facilities, remoteness, proximity.
    Mots-clés : base de données ouvertes, ECDO, établissements de santé,
    hôpitaux, empreintes d'immeubles, écoles, installations sportives,
    éloignement, proximité.
    """
    use_lang(lang)
    return await client.list_databases(lang)


@tool
async def statcan_lode_list_files(
    database: str, sizes: bool = True, lang: Literal["en", "fr"] = "en"
) -> LodeFileList:
    """List a LODE database's ZIP downloads with sizes, formats and provinces.

    Use for: download links, sizes and formats of one database key (odhf,
    odsrf, odb, odef, odcaf, oda, odi, pmd, remoteness, sam, nar), which file
    covers which province, and which can be queried. Sizes come from HEAD
    requests paced at 2 seconds each; sizes=false skips them.
    Keywords: download links, ZIP, file size, GeoJSON, GeoPackage, CSV,
    GeoParquet, provinces, open licence, release date.
    Mots-clés : liens de téléchargement, fichier ZIP, taille du fichier,
    GeoJSON, GeoPackage, CSV, provinces, licence ouverte, date de diffusion.
    """
    use_lang(lang)
    return await client.list_files(database, lang, sizes)


@tool
async def statcan_lode_describe(
    database: str, file: str | None = None, lang: Literal["en", "fr"] = "en"
) -> LodeDescription:
    """Show a LODE database's fields, types, descriptions and ZIP contents.

    Use for: which columns a database has before querying: the record
    layout in the ZIP, a first-record sample, the GeoPackage schema (read
    when the archive is under 60 MB) and the product page's variable list.
    Keywords: data dictionary, record layout, fields, columns, variables,
    schema, GeoPackage layers, facility type.
    Mots-clés : dictionnaire de données, disposition des enregistrements,
    champs, colonnes, variables, schéma, couches GeoPackage, type
    d'installation.
    """
    use_lang(lang)
    return await client.describe(database, file, lang)


@tool
async def statcan_lode_query(
    database: str,
    province: str | None = None,
    csd: str | None = None,
    type: str | None = None,
    name: str | None = None,
    bbox: list[float] | None = None,
    filters: dict[str, str] | None = None,
    file: str | None = None,
    member: str | None = None,
    layer: str | None = None,
    limit: int = constants.RECORDS_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> LodeQueryResult:
    """Query a LODE open database by province, place, type, name or bounding box.

    Use for: hospitals in Alberta (odhf, province AB, type Hospital), arenas
    in a city (odsrf), buildings in a bbox west,south,east,north (odb with
    province PE), schools (odef), museums (odcaf), addresses (oda), a
    community's remoteness (remoteness) or proximity (pmd). province takes AB,
    Alberta or 48; csd a name or 7-digit code; type exact, name substring,
    ignoring case and accents; filters match any column. Returns up to
    limit (max 500) records with WGS 84 coordinates, the total matched and
    the file read. First call downloads the ZIP to a disk cache (cap 300 MB,
    MAPLE_LODE_MAX_DOWNLOAD_MB); retry if it times out. odb and oda need
    province; file picks a ZIP, member a data file inside it.
    Keywords: query open database, hospitals, clinics, pharmacies, schools,
    arenas, museums, building footprints, bounding box, census subdivision,
    facilities by type, remoteness, ODHF, ODSRF, ODB.
    Mots-clés : interroger base de données ouvertes, hôpitaux, cliniques,
    pharmacies, écoles, arénas, musées, empreintes d'immeubles, boîte
    englobante, subdivision de recensement, installations par type.
    """
    use_lang(lang)
    return await client.query(
        database,
        file=file,
        member=member,
        province=province,
        csd=csd,
        type=type,
        name=name,
        bbox=bbox,
        filters=filters,
        layer=layer,
        limit=limit,
        lang=lang,
    )


@tool
async def statcan_lode_list_zip(url: str, lang: Literal["en", "fr"] = "en") -> LodeZipListing:
    """List the files inside a LODE ZIP without downloading it (HTTP range).

    Use for: what a large archive holds, such as the National Address
    Register (1.67 GB, Locations and Addresses CSVs per province), the transit
    database, or any link from the file listing. Reads a few KB.
    Keywords: National Address Register, NAR, ZIP contents, archive, address
    files, range request, large file, GTFS.
    Mots-clés : Registre national des adresses, RNA, contenu du ZIP, archive,
    fichiers d'adresses, requête par plage, gros fichier, GTFS.
    """
    use_lang(lang)
    return await client.list_zip(url)


@tool
async def statcan_lode_preview_member(
    url: str,
    member: str,
    match: dict[str, str] | None = None,
    rows: int = 10,
    scan_mb: float = constants.PREVIEW_SCAN_DEFAULT_MB,
    lang: Literal["en", "fr"] = "en",
) -> LodeMemberPreview:
    """Read the first rows of a CSV inside a LODE ZIP, or look up rows, by HTTP range.

    Use for: peeking at National Address Register or Proximity Measures
    files without downloading the archive, or finding rows where a column
    equals a value (match, e.g. {"postal_code": "K1A0B1"}) within the first
    scan_mb MB (default 8, max 40) of the compressed member; small
    territories scan completely, large provinces only in part, and the result
    says so. url and member come from the ZIP listing.
    Keywords: address lookup, National Address Register, NAR, postal code,
    preview rows, CSV member, range read, civic address.
    Mots-clés : recherche d'adresse, Registre national des adresses, RNA,
    code postal, aperçu des lignes, fichier CSV, lecture par plage, adresse
    civique.
    """
    use_lang(lang)
    return await client.preview_member(url, member, match=match, rows=rows, scan_mb=scan_mb)
