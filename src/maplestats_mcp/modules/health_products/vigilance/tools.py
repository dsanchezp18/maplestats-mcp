"""MCP tools for the Canada Vigilance adverse reaction database."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.health_products.vigilance import client
from maplestats_mcp.modules.health_products.vigilance.schemas import (
    ReactionSearchResult,
    VigilanceCodeTables,
    VigilanceReport,
)

Lang = Literal["en", "fr"]


@tool
async def hc_vigilance_get_report(report_id: int, lang: Lang = "en") -> VigilanceReport:
    """One Canada Vigilance adverse reaction report, with every product on it.

    Use for: the details of a suspected side effect report to Health
    Canada: dates received, report type and source, patient sex, age,
    weight and height, MedDRA reaction terms and system organ classes,
    seriousness and its criteria (death, hospitalization, disability,
    life threatening), outcome, and each drug or health product with its
    role (suspect or concomitant), dose, route, frequency and indication.
    Report ids come from hc_vigilance_search_reactions or the online
    database. A report records a suspected association, not proof.
    Keywords: adverse reaction report, side effect report, Canada
    Vigilance, adverse drug reaction, AER number, suspect drug,
    pharmacovigilance, MedDRA term, serious adverse event.
    Mots-clés : déclaration d'effet indésirable, effet secondaire, Canada
    Vigilance, réaction indésirable à un médicament, médicament suspect,
    pharmacovigilance, terme MedDRA, effet indésirable grave.
    """
    return await client.get_report(report_id, lang=lang)


@tool
async def hc_vigilance_search_reactions(
    reaction: str = "",
    system_organ_class: str = "",
    min_report_id: int = 0,
    limit: int = 50,
    max_scan_mb: int = 120,
    lang: Lang = "en",
) -> ReactionSearchResult:
    """Find Canada Vigilance adverse reaction reports by reaction term (monthly extract).

    Use for: which suspected side effect reports to Health Canada mention a
    reaction (MedDRA preferred term, English or French, e.g. 'myocarditis',
    'anaphylactic', 'Céphalée') or a system organ class ('Cardiac
    disorders'), with counts per term and organ class, and the matching
    report ids, newest (highest id) first; `min_report_id` keeps only
    newer reports. Reads the reactions file of the monthly extract (data
    since 1965) as a stream, about 100 MB, so a new search takes about a
    minute; repeats are cached for a day. `complete` is false when the
    `max_scan_mb` ceiling stopped the read. Search by drug or by year is
    not offered: the extract's drug and date tables sit after the first
    185 MB of a 355 MB file that canada.ca serves only as one compressed
    stream. Read dates and suspect drugs per report with
    hc_vigilance_get_report.
    Keywords: adverse reaction search, side effects reported, Canada
    Vigilance extract, MedDRA preferred term, system organ class,
    pharmacovigilance data, adverse event counts, drug safety signal.
    Mots-clés : recherche d'effets indésirables, effets secondaires
    déclarés, extrait de Canada Vigilance, terme privilégié MedDRA, classe
    de systèmes d'organes, pharmacovigilance, nombre de déclarations,
    innocuité des médicaments.
    """
    return await client.search_reactions(
        reaction,
        system_organ_class=system_organ_class,
        min_report_id=min_report_id,
        limit=limit,
        max_scan_mb=max_scan_mb,
        lang=lang,
    )


@tool
async def hc_vigilance_list_codes(lang: Lang = "en") -> VigilanceCodeTables:
    """Code tables of the Canada Vigilance adverse reaction database.

    Use for: the labels behind Canada Vigilance codes: report outcome
    (recovered, fatal...), seriousness, report source (hospital,
    community, manufacturer...), sex, and report type (spontaneous,
    study, published, mandatory hospital), in English or French.
    Keywords: Canada Vigilance codes, outcome codes, seriousness codes,
    report source, report type, adverse reaction database lookup,
    pharmacovigilance code list, data dictionary.
    Mots-clés : codes de Canada Vigilance, codes de résultat, gravité,
    source de la déclaration, type de déclaration, dictionnaire de
    données, liste de codes, pharmacovigilance.
    """
    return await client.list_codes(lang=lang)
