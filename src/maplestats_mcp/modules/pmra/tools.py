"""MCP tools for Health Canada's pesticide registry (PMRA)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.pmra import client
from maplestats_mcp.modules.pmra.schemas import (
    PesticideProductDetail,
    PesticideProductList,
    ResidueLimitList,
)

Lang = Literal["en", "fr"]


@tool
async def pmra_search_products(
    query: str = "",
    registration_number: str = "",
    active_ingredient: str = "",
    registrant: str = "",
    product_type: str = "",
    status: Literal["current", "historical", "all"] = "current",
    limit: int = 50,
    lang: Lang = "en",
) -> PesticideProductList:
    """Search Health Canada's register of pesticide products (PMRA).

    Use for: whether a pesticide, herbicide, insecticide, fungicide,
    disinfectant or insect repellent is registered in Canada, its PCP
    registration number, registrant, marketing type (commercial, domestic,
    restricted) and active ingredients. About 7,800 current and 14,000
    historical (cancelled) products. `query` matches product names (both
    languages) and the registration number; `active_ingredient` matches
    ingredient names ('glyphosate', 'chlorpyrifos', 'DEET'); `registrant`
    and `product_type` ('herbicide') narrow further. Counts by product type
    come with every result. Pass a registration number to
    pmra_get_product for sites of use, pests and ingredient details.
    Open Government Licence - Canada; data refreshed daily.
    Keywords: pesticide registration, PCP number, registered pesticides,
    herbicide products, Roundup, active ingredient, Pest Management
    Regulatory Agency, Health Canada pesticides, insecticide.
    Mots-clés : homologation des pesticides, numéro d'homologation,
    produits antiparasitaires, ARLA, herbicide homologué, principe actif,
    insecticide, Santé Canada pesticides, produit phytosanitaire.
    """
    return await client.search_products(
        query,
        registration_number=registration_number,
        active_ingredient=active_ingredient,
        registrant=registrant,
        product_type=product_type,
        status=status,
        limit=limit,
        lang=lang,
    )


@tool
async def pmra_get_product(registration_number: str, lang: Lang = "en") -> PesticideProductDetail:
    """One pesticide product by its registration number, with its ingredients.

    Use for: the full record of a registered pest control product: status
    and expiry, registrant, sites of use (crops, lawns, buildings), target
    pests, and each active ingredient with its CAS number, whether it is
    under re-evaluation, and how many food commodities carry a maximum
    residue limit for it (see pmra_get_residue_limits). Read fresh from
    the registry. Sites and pests are cut at 2,000 characters by the
    source; `lists_truncated` says when.
    Keywords: pesticide label details, registration number lookup, PCP
    act, CAS number, re-evaluation, target pests, sites of use, pesticide
    active ingredients, registrant.
    Mots-clés : fiche du produit antiparasitaire, numéro d'homologation,
    numéro CAS, réévaluation, organismes nuisibles, sites d'utilisation,
    principes actifs, titulaire d'homologation.
    """
    return await client.get_product(registration_number, lang=lang)


@tool
async def pmra_get_residue_limits(
    chemical: str = "",
    commodity: str = "",
    limit: int = 200,
    lang: Lang = "en",
) -> ResidueLimitList:
    """Canada's maximum residue limits (MRLs) for pesticides on food.

    Use for: the legal maximum pesticide residue, in parts per million,
    allowed on a food sold in Canada: glyphosate on wheat or oats,
    chlorpyrifos on apples, every pesticide with an MRL on blueberries.
    `chemical` is the common name (exact match first, else a substring);
    `commodity` matches food names ('apples', 'pommes' with lang='fr').
    About 25,000 limits for 339 chemicals, each with the regulatory action
    that set it (an EMRL or PMRL document, or the Canada Gazette).
    Keywords: maximum residue limit, MRL, pesticide residues in food, ppm,
    food safety pesticides, glyphosate limit, residue tolerance,
    Health Canada MRL database.
    Mots-clés : limite maximale de résidus, LMR, résidus de pesticides
    dans les aliments, ppm, salubrité des aliments, denrée alimentaire,
    tolérance de résidus, glyphosate.
    """
    return await client.get_residue_limits(chemical, commodity=commodity, limit=limit, lang=lang)
