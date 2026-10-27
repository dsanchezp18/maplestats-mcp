"""MCP tools for the CBSA Customs Tariff."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cbsa_tariff import client
from maplestats_mcp.modules.cbsa_tariff.schemas import TariffEditions, TariffLookup, TariffSearch

Lang = Literal["en", "fr"]


@tool
async def cbsa_tariff_list_editions(year: int | None = None, lang: Lang = "en") -> TariffEditions:
    """List the editions of Canada's Customs Tariff (CBSA), with effective dates.

    Use for: which version of the Customs Tariff schedule is in force and
    since when, the amendments of a year (T2026, T2026-1, T2026-2 ...) and
    links to each edition's Access database, PDF and web chapters. Without
    `year`, this year's and last year's editions; `year` reaches back to
    2018. Pass an edition label or a date as `edition` to
    cbsa_tariff_lookup and cbsa_tariff_search to read an earlier one.
    CBSA terms: non-commercial reuse with attribution.
    Keywords: customs tariff edition, tariff schedule version, CBSA tariff
    amendment, effective date, departmental consolidation, tariff update,
    T2026, Canada tariff history.
    Mots-clés : édition du tarif des douanes, version de l'annexe tarifaire,
    modification du tarif de l'ASFC, date d'entrée en vigueur, codification
    ministérielle, mise à jour tarifaire, historique du tarif canadien,
    Agence des services frontaliers.
    """
    return await client.list_editions(year=year, lang=lang)


@tool
async def cbsa_tariff_lookup(
    tariff_item: str,
    edition: str = "latest",
    lang: Lang = "en",
) -> TariffLookup:
    """Look up a Canadian Customs Tariff number: description, unit and duty rates.

    Use for: the duty rate Canada charges on a product by its tariff item
    or HS code: the Most-Favoured-Nation (MFN) rate, the General Tariff,
    and every preferential rate (United States and Mexico under CUSMA, the
    EU under CETA, CPTPP, UK, Korea, Chile, Peru, Colombia, Ukraine, least
    developed countries, General Preferential Tariff ...), each as CBSA
    wrote it and as a percentage when it is one. `tariff_item` takes 2 to
    10 digits, dots optional: '8703.80.00' (a tariff item), '8703' (a
    heading, listing the lines under it), '8703800000' (a classification
    number). The result also gives the item's headings for context.
    `edition` is 'latest', an edition such as '2026-2', or a date
    (YYYY-MM-DD) for the rates then in force (2018 onward). The digits
    are the HS code cimt_get_trade takes as `hs_code`, so the same code
    gives Canada's import volumes by partner. The first call on an edition
    reads CBSA's database (about 20 s). Surtaxes, anti-dumping duties and
    GST are not part of the schedule. CBSA terms: non-commercial reuse.
    Keywords: customs tariff, duty rate, import duty Canada, MFN rate,
    tariff item, HS code, CUSMA preferential rate, CETA, CPTPP, tariff
    treatment, harmonized system classification.
    Mots-clés : tarif des douanes, taux de droit, droits de douane à
    l'importation, taux NPF, numéro tarifaire, code SH, taux préférentiel
    ACEUM, AECG, PTPGP, traitement tarifaire, classement du système
    harmonisé.
    """
    return await client.lookup(tariff_item, edition=edition, lang=lang)


@tool
async def cbsa_tariff_search(
    query: str = "",
    chapter: str = "",
    edition: str = "latest",
    limit: int = 25,
    lang: Lang = "en",
) -> TariffSearch:
    """Search Canada's Customs Tariff by words or HS chapter, with each line's rates.

    Use for: finding the tariff number and duty rates of a product named
    in words ('electric vehicles', 'maple syrup', 'cheddar', 'solar
    panels'), or browsing a chapter of the Harmonized System ('87' for
    vehicles, '04' for dairy). Every word must appear in the description
    (accents ignored; French descriptions with lang='fr'); a number among
    the words keeps lines starting with it. Each line carries MFN, General
    Tariff and preferential rates; cbsa_tariff_lookup on a number gives its
    headings and the lines under it. `edition` is 'latest', an edition such
    as '2026-2', or a date YYYY-MM-DD. Up to 100 lines (`limit`). Pair the
    digits with cimt_get_trade's `hs_code` for import volumes. CBSA terms:
    non-commercial reuse with attribution.
    Keywords: tariff search, find HS code, customs classification, duty
    rate lookup, product tariff Canada, import tariff schedule, Harmonized
    System chapter, tariff by product name.
    Mots-clés : recherche dans le tarif des douanes, trouver un code SH,
    classement douanier, taux de droits par produit, annexe tarifaire,
    chapitre du système harmonisé, droits d'importation au Canada,
    numéro tarifaire d'un produit.
    """
    return await client.search(query, chapter=chapter, edition=edition, limit=limit, lang=lang)
