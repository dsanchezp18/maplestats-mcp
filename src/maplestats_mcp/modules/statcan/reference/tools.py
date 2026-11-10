"""MCP tools for StatCan's Drupal-based catalogue searches (Reference resources and Analysis)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.lang import use_lang
from maplestats_mcp.modules.statcan.reference import client, constants
from maplestats_mcp.modules.statcan.reference.schemas import (
    Publication,
    PublicationText,
    ReferenceSearchResult,
)


@tool
async def statcan_reference_search_documents(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
) -> ReferenceSearchResult:
    """Search StatCan's Reference resources catalogue: definitions, data sources, and methods.

    Use for: finding methodology guides, technical reference documents,
    survey documentation, geographic file specifications, and other
    "Definitions, data sources and methods"-style publications --
    distinct from actual data (WDS/SDMX/RDaaS) and from The Daily's
    release bulletin (statcan_daily_*). Covers 2,031 documents. Each
    result carries a catalogue number (e.g. "16-511-X"), a category
    (e.g. "Surveys and statistical programs – Documentation",
    "Geographic files and documentation"), a description, and a
    release date. Results are titles and descriptions only: to read a
    guide's text (a definition, a method), pass its catalogue number to
    statcan_reference_get_publication (table of contents) or
    statcan_reference_get_section_text (section= or query=). An empty
    query returns the full unfiltered catalogue (paginate with page/count
    to browse it). Keywords: StatCan, definitions, data sources and
    methods, DSDM, methodology, technical reference guide, survey
    documentation, catalogue number, LFS guide, CPI reference paper.
    Mots-clés : Statistique Canada, définitions, sources de données et
    méthodes, méthodologie, guide de référence technique, documentation
    d'enquête, numéro au catalogue, publications techniques.
    """
    use_lang(lang)
    return await client.search_documents(query, count=count, page=page, lang=lang)


@tool
async def statcan_reference_search_analysis(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
) -> ReferenceSearchResult:
    """Search StatCan's Analysis catalogue: analytical articles, journals and periodicals.

    Use for: finding analytical publications, "Stats in brief" (many
    of these are also Daily articles republished with a catalogue
    number), and journal/periodical series -- distinct from
    statcan_reference_search_documents (methodology/definitions
    catalogue), from actual data (WDS/SDMX/RDaaS), and from The
    Daily's release bulletin (statcan_daily_*). Covers 10,841+
    documents. Each result carries a catalogue number (e.g.
    "46-28-0001"), a category (e.g. "Journals and periodicals"), a
    description, and a release date. An empty query returns the full
    unfiltered catalogue (paginate with page/count to browse it).
    Keywords: StatCan, analysis, analytical article, stats in brief,
    journal, periodical, working paper, insights.
    Mots-clés : Statistique Canada, analyse, article analytique, coup d'œil
    sur, revue, périodique, document de travail, études.
    """
    use_lang(lang)
    return await client.search_analysis(query, count=count, page=page, lang=lang)


@tool
async def statcan_reference_search_data(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    count: int = constants.SEARCH_COUNT_DEFAULT,
    page: int = 0,
) -> ReferenceSearchResult:
    """Search StatCan's Data catalogue: tables plus PUMFs, geographic and other bulk files.

    Use for: finding a data product's catalogue number, especially one
    with no WDS/SDMX discovery path of its own -- most notably Public
    Use Microdata Files (PUMFs; category "Public use microdata", e.g.
    catalogue number 71M0001X for the Labour Force Survey PUMF,
    98M0001X for the Census). Most other results here are ordinary
    table PIDs also reachable via statcan_wds_*/statcan_sdmx_*, so
    prefer those tools for routine table search -- use this one when
    the product itself (a PUMF, a boundary file, a bulk archive) is
    the target, not a table's time series. Covers 13,342+ items. For a
    PUMF, pass its catalogue_number to statcan_pumf_list_files for the
    download ZIPs. An empty query returns the full unfiltered catalogue (paginate with
    page/count to browse it). Keywords: StatCan, PUMF, public use microdata
    file, geographic boundary file, bulk data, data product, Statistics
    Canada, download.
    Mots-clés : Statistique Canada, FMGD, fichier de microdonnées à grande
    diffusion, fichier de limites géographiques, données en bloc, produit de
    données, téléchargement, cartes géographiques.
    """
    use_lang(lang)
    return await client.search_data(query, count=count, page=page, lang=lang)


@tool
async def statcan_reference_get_publication(
    publication: str,
    lang: Literal["en", "fr"] = "en",
    edition: str | None = None,
) -> Publication:
    """Open a StatCan guide or methodology publication: its editions and table of contents.

    Use for: going from a catalogue number ("71-543-G", "62-553-X",
    "13-017-X", "62F0014M2021011", case-insensitive) or a
    www150.statcan.gc.ca publication URL (from
    statcan_reference_search_documents or _search_analysis) to the
    publication itself: title, edition and release date, the edition's
    URL and PDF link, and its sections (id, title, level, url) -- the
    headings of the main page and the edition's other pages (chapters,
    appendices, glossary). Defaults to the latest edition; edition=
    picks another ("2020001", "2020", "71-543-G2020001") from the
    editions listed. A PDF-only edition says so and gives the PDF link.
    Then read the text with statcan_reference_get_section_text
    (section=<id> or query=<words>). Examples: Guide to the Labour Force
    Survey (71-543-G), The Canadian Consumer Price Index Reference Paper
    (62-553-X), Guide to the Income and Expenditure Accounts (13-017-X),
    Methodological Guide: Canadian System of Macroeconomic Accounts
    (13-607-X), Prices Analytical Series articles (62F0014M).
    Keywords: StatCan, survey guide, reference paper, methodology guide,
    table of contents, chapters, catalogue number, edition, user guide,
    LFS guide, CPI reference paper, technical documentation.
    Mots-clés : Statistique Canada, guide de l'enquête, document de
    référence, guide méthodologique, table des matières, chapitres,
    numéro au catalogue, édition, guide d'utilisation, guide de l'EPA,
    document de référence de l'IPC.
    """
    use_lang(lang)
    return await client.get_publication(publication, edition=edition, lang=lang)


@tool
async def statcan_reference_get_section_text(
    publication: str,
    lang: Literal["en", "fr"] = "en",
    section: str | None = None,
    query: str | None = None,
    edition: str | None = None,
    start_char: int = 0,
    max_chars: int = constants.TEXT_MAX_CHARS_DEFAULT,
    limit: int = constants.QUERY_MATCHES_DEFAULT,
) -> PublicationText:
    """Read the text of a StatCan guide or methodology publication: a section, or a search.

    Use for: the official wording of a concept, definition or method
    from StatCan's own guides and reference papers, to quote and cite
    instead of answering from memory. publication is a catalogue number
    ("71-543-G") or a www150.statcan.gc.ca publication URL. Pass
    section= (an id or title from statcan_reference_get_publication, or
    a page URL) for that section's text, or query= ("involuntary
    part-time", "owned accommodation", "hedonic", "basket update",
    "supplementary labour income") to search every page of the edition
    and get the best-matching sections, each as an excerpt starting at
    its best paragraph (limit= of them, default 3). With neither, the
    edition's main page. Plain text: headings kept as '#' lines, tables
    as 'a | b' rows, menus and footers dropped; cut at max_chars (default
    6,000) with next_start_char to read on (start_char=). Each section
    carries its own URL to cite, and the result the edition's release
    date. PDF-only editions return the PDF link, not text. Covers the
    Guide to the Labour Force Survey (71-543-G: exclusions, involuntary
    part-time, quality and release rules), the CPI Reference Paper
    (62-553-X: Lowe index, basket updates, owned accommodation, quality
    adjustment), the Guide to the Income and Expenditure Accounts
    (13-017-X), the Macroeconomic Accounts methodological guide
    (13-607-X) and Prices Analytical Series papers such as the 2021 CPI
    basket update (62F0014M2021011).
    Keywords: StatCan, definition, concept, methodology, survey guide
    text, LFS guide, CPI reference paper, hedonic adjustment, owned
    accommodation, basket update, involuntary part-time, national
    accounts methodology, gross output, read guide.
    Mots-clés : Statistique Canada, définition, concept, méthodologie,
    texte du guide, guide de l'EPA, document de référence de l'IPC,
    ajustement hédonique, logement en propriété, mise à jour du panier,
    temps partiel involontaire, méthodologie des comptes nationaux.
    """
    use_lang(lang)
    return await client.get_section_text(
        publication,
        section=section,
        query=query,
        edition=edition,
        start_char=start_char,
        max_chars=max_chars,
        limit=limit,
        lang=lang,
    )
