"""MCP tools for Health Canada's Licensed Natural Health Products Database."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.health_products.lnhpd import client
from maplestats_mcp.modules.health_products.lnhpd.schemas import (
    NhpProductDetail,
    NhpSearchResult,
)

Lang = Literal["en", "fr"]


@tool
async def hc_nhp_search_products(
    query: str = "",
    company: str = "",
    active_only: bool = True,
    limit: int = 50,
    lang: Lang = "en",
) -> NhpSearchResult:
    """Search licensed natural health products (LNHPD) by product name, NPN or company.

    Use for: finding vitamins, minerals, herbal remedies, probiotics,
    homeopathic medicines and other natural health products licensed by
    Health Canada, with their Natural Product Number (NPN or DIN-HM),
    licence holder, dosage form, licence date and whether the licence is
    active. `query` matches any brand name of a licence or the start of an
    NPN; `company` matches the licence holder. About 153,000 licences and
    307,000 brand names. The first search of the day reads the whole table
    (about a minute). Pass an NPN to hc_nhp_get_product for ingredients,
    doses, uses and warnings.
    Keywords: natural health products, NPN, natural product number,
    LNHPD, vitamins, herbal supplements, homeopathic medicine, dietary
    supplements, probiotics, licence holder.
    Mots-clés : produits de santé naturels, NPN, numéro de produit naturel,
    BDPSNH, vitamines, suppléments à base de plantes, remèdes
    homéopathiques, suppléments alimentaires, probiotiques, titulaire de
    licence, Santé Canada.
    """
    return await client.search_products(
        query, company=company, active_only=active_only, limit=limit, lang=lang
    )


@tool
async def hc_nhp_get_product(npn: str, lang: Lang = "en") -> NhpProductDetail:
    """Licence record of one natural health product, by NPN.

    Use for: what a natural health product contains and is licensed for:
    medicinal ingredients with quantity, potency, extract ratio and source
    material, non-medicinal ingredients, route, recommended doses by
    population, recommended uses (purposes), and cautions, warnings,
    contraindications and known adverse reactions, with every brand name
    and the licence holder. Uses and warnings are shown as the company
    filed them, which may be English even with lang='fr'.
    Keywords: NPN lookup, natural product licence, medicinal ingredients,
    recommended dose, recommended use, contraindications, cautions and
    warnings, herbal product label, DIN-HM.
    Mots-clés : numéro NPN, licence de produit naturel, ingrédients
    médicinaux, dose recommandée, usage recommandé, contre-indications,
    mises en garde, étiquette de produit à base de plantes, Santé Canada.
    """
    return await client.get_product(npn, lang=lang)
