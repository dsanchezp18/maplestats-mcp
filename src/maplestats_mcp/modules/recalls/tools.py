"""MCP tools for the Government of Canada Recalls and Safety Alerts site."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.recalls import client, constants
from maplestats_mcp.modules.recalls.schemas import (
    RecallCountsResult,
    RecallDetail,
    RecallSearchResult,
)

Lang = Literal["en", "fr"]
Agency = Literal["health_canada", "cfia", "transport_canada"]
ProductType = Literal["food", "health_product", "consumer_product", "vehicle"]
GroupBy = Literal[
    "year", "agency", "product_type", "organization", "category", "issue", "recall_class"
]


@tool
async def recalls_search(
    query: str | None = None,
    agency: Agency | None = None,
    product_type: ProductType | None = None,
    category: str | None = None,
    recall_class: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    include_archived: bool = False,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> RecallSearchResult:
    """Search Government of Canada recalls and safety alerts (Health Canada, CFIA, Transport Canada).

    Use for: finding food recalls (allergens, Listeria, Salmonella, E.
    coli), drug, natural health product and medical device recalls,
    consumer product recalls (toys, cribs, electronics, cannabis) and
    vehicle recall notices on recalls-rappels.canada.ca. `query` matches
    every word in the title, product, issue, category and organization,
    ignoring case, accents, plurals and words such as "aux" or "the"
    (e.g. "peanut cookies", "biscuits aux arachides").
    `agency` and `product_type` narrow the source; `category` is a text
    match on the category (e.g. "Toys", "Dairy"); `recall_class` is
    "Class 1" to "Class 3" (CFIA food; "Classe 1" also works) or "Type I"
    to "Type III" (Health Canada health products). Dates (YYYY-MM-DD)
    filter on the notice's last-updated date, the same date the site's
    search uses. Newest first; archived notices are excluded unless
    include_archived=True. Pass recall_id to recalls_get for affected
    lots, UPCs and what to do. For vehicle recalls by make, model and
    year use tc_recalls_search. `lang="fr"` searches and returns the
    French text, so with it `query` and `category` must be French (e.g.
    "jouets", "Produits laitiers"); untranslated notices keep an English
    title and URL.
    Keywords: recall, safety alert, food recall, allergen, health
    product recall, drug recall, medical device, consumer product,
    Health Canada, CFIA, advisory, product safety.
    Mots-clés : rappel, avis de rappel, rappel alimentaire, rappel
    d'aliments, allergène, rappel de médicament, instrument médical,
    produit de consommation, rappel de jouets, Santé Canada, ACIA, avis
    de sécurité, mise en garde, sécurité des produits, retrait du marché.
    """
    return await client.search(
        query,
        agency=agency,
        product_type=product_type,
        category=category,
        recall_class=recall_class,
        updated_from=updated_from,
        updated_to=updated_to,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def recalls_get(recall_id: int, lang: Lang = "en") -> RecallDetail:
    """Get one recall or safety alert's full notice: affected products, lots, hazard and what to do.

    Use for: the details behind a recall_id from recalls_search, such as
    the affected products table (brand, product, size, UPC, lot or serial
    numbers, DIN, expiry), the issue and safety risk text, what consumers
    should do, distribution provinces, recalling companies, recall class
    and recall date. `layout` says which page format was read: 'current'
    pages fill the typed fields; older 'legacy' notices put their header
    in `details` and their body in `legacy_text`. For vehicle notices,
    `agency_reference` holds the Transport Canada recall number for
    tc_recalls_get. `lang="fr"` reads the French page (untranslated
    notices come back in English).
    Keywords: recall details, affected products, lot number, UPC,
    hazard, what to do, recalling firm, distribution, recall class,
    safety alert.
    Mots-clés : détails du rappel, produits visés, numéro de lot, code
    CUP, danger, que faire, entreprise, distribution, classe de rappel,
    avis de sécurité.
    """
    return await client.get_recall(recall_id, lang)


@tool
async def recalls_summarize(
    group_by: GroupBy,
    query: str | None = None,
    agency: Agency | None = None,
    product_type: ProductType | None = None,
    category: str | None = None,
    recall_class: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    include_archived: bool = True,
    top: int = constants.GROUPS_DEFAULT,
    lang: Lang = "en",
) -> RecallCountsResult:
    """Count Government of Canada recalls and safety alerts by year, agency, product type or category.

    Use for: statistics such as food recalls per year, allergen recalls
    by issue (e.g. product_type="food", group_by="issue"), Health Canada
    recalls by recall class, or which consumer product categories are
    recalled most. Takes the same filters as recalls_search. `year` is
    the last-updated year (the dump has no separate recall date).
    Unlike recalls_search, archived notices are included by default, so
    counts cover the full history back to the 1990s; pass
    include_archived=False to match the site's search. `lang="fr"`
    returns French organization, category, issue and class labels (and
    then takes French `query` and `category` text); agency and
    product_type keys and the "(none)" and "unknown" keys stay as codes.
    Keywords: recall statistics, recalls per year, count, trend, food
    recalls, allergen, Health Canada, CFIA, product safety, summary.
    Mots-clés : statistiques de rappels, rappels par année, nombre,
    tendance, rappels d'aliments, allergène, Santé Canada, ACIA,
    sécurité des produits, sommaire.
    """
    return await client.summarize(
        group_by,
        query,
        agency=agency,
        product_type=product_type,
        category=category,
        recall_class=recall_class,
        updated_from=updated_from,
        updated_to=updated_to,
        include_archived=include_archived,
        top=top,
        lang=lang,
    )
