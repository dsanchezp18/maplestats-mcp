"""MCP tools for Health Canada's Drug Product Database (DPD)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.health_products.dpd import client
from maplestats_mcp.modules.health_products.dpd.schemas import (
    DrugProductDetail,
    DrugProductList,
    DrugStatus,
    IngredientList,
)

Lang = Literal["en", "fr"]
ProductClass = Literal["human", "veterinary", "disinfectant", "radiopharmaceutical"]


@tool
async def hc_drug_search_products(
    din: str = "",
    brand: str = "",
    ingredient: str = "",
    company: str = "",
    status: DrugStatus | None = None,
    schedule: str = "",
    atc: str = "",
    product_class: ProductClass | None = None,
    limit: int = 50,
    lang: Lang = "en",
) -> DrugProductList:
    """Search Health Canada's Drug Product Database (DPD) for drug products.

    Use for: finding drugs approved in Canada by DIN (Drug Identification
    Number), brand name, company (DIN owner), active ingredient, status
    (marketed, approved, dormant, cancelled), schedule (prescription,
    non-prescription, narcotics and controlled drugs under the CDSA,
    Schedule D biologics, homeopathic) or ATC class (code prefix such as
    'N06A' or words such as 'antidepressants'), for human, veterinary,
    disinfectant and radiopharmaceutical products. Filters combine; counts
    by status come with every result. About 58,000 products, all statuses.
    Pass a drug_code or DIN to hc_drug_get_product for ingredients,
    strengths, forms, routes and packaging.
    Keywords: Drug Product Database, DPD, DIN lookup, drug identification
    number, prescription drugs Canada, generic drugs, marketed drugs,
    pharmaceutical company products, ATC classification, controlled substances.
    Mots-clés : Base de données sur les produits pharmaceutiques, BDPP,
    numéro d'identification du médicament, DIN, médicaments sur ordonnance,
    médicaments génériques, médicaments commercialisés, fabricant
    pharmaceutique, classification ATC, drogues contrôlées.
    """
    return await client.search_products(
        din=din,
        brand=brand,
        ingredient=ingredient,
        company=company,
        status=status,
        schedule=schedule,
        atc=atc,
        product_class=product_class,
        limit=limit,
        lang=lang,
    )


@tool
async def hc_drug_get_product(
    din: str = "", drug_code: int | None = None, lang: Lang = "en"
) -> DrugProductDetail:
    """Full Drug Product Database record for one drug product, by DIN or drug code.

    Use for: what a DIN is: brand name, company and its address, current
    status and date, original market date, active ingredients with
    strengths, schedules (prescription, narcotic, CDSA class), dosage
    forms, routes of administration, ATC therapeutic class, packaging,
    pharmaceutical standard, and veterinary species. For a product the
    company discontinued, also the last lot number and its expiry date.
    Keywords: DIN details, drug monograph data, active ingredient strength,
    dosage form, route of administration, drug schedule, ATC code, drug
    packaging, Health Canada drug record.
    Mots-clés : fiche du médicament, numéro DIN, concentration de
    l'ingrédient actif, forme posologique, voie d'administration, annexe du
    médicament, code ATC, emballage, statut du produit.
    """
    return await client.get_product(din, drug_code, lang=lang)


@tool
async def hc_drug_search_ingredients(
    name: str, limit: int = 50, lang: Lang = "en"
) -> IngredientList:
    """Active ingredient names in the Drug Product Database, with product counts.

    Use for: checking how Health Canada spells an active ingredient (salt
    forms such as 'DOXEPIN (DOXEPIN HYDROCHLORIDE)'), how many drug
    products contain it, and their usual strengths, before searching
    products by ingredient with hc_drug_search_products. With lang='fr'
    the names are the French ones ('Acétaminophène') and the search
    matches French spellings.
    Keywords: active ingredient, medicinal ingredient, drug substance,
    generic name, INN, drug strength, salt form, molecule, DPD ingredient.
    Mots-clés : ingrédient actif, principe actif, substance médicamenteuse,
    dénomination commune, DCI, concentration du médicament, sel, molécule.
    """
    return await client.search_ingredients(name, limit=limit, lang=lang)
