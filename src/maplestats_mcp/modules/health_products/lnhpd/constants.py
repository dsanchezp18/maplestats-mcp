"""Constants for the Licensed Natural Health Products Database API.

Checked live 2026-10-03: the licence table without `id` is one JSON array
of 307,002 rows (one per product name; 153,370 licences) that took 60 to
65 s before its first byte on every try, then 148 MB of JSON (15 MB with
gzip). `page=` and `limit=` are ignored on that endpoint, though the
ingredient, purpose and risk endpoints page by 100 (829,863 medicinal
ingredient rows), so a search by ingredient is not practical.
"""

PATH_LICENCE = "natural-licences/productlicence"
PATH_MEDICINAL = "natural-licences/medicinalingredient"
PATH_NON_MEDICINAL = "natural-licences/nonmedicinalingredient"
PATH_PURPOSE = "natural-licences/productpurpose"
PATH_RISK = "natural-licences/productrisk"
PATH_ROUTE = "natural-licences/productroute"
PATH_DOSE = "natural-licences/productdose"

PRODUCT_PAGE = "https://health-products.canada.ca/lnhpd-bdpsnh/info?licence={npn}"
FRESHNESS = "LNHPD online data, updated by Health Canada as licences are issued or revised"
FRESHNESS_FR = (
    "données en ligne de la BDPSNH, mises à jour par Santé Canada à mesure que les "
    "licences sont délivrées ou révisées"
)

INDEX_TTL_SECONDS = 24 * 60 * 60
LOOKUP_TTL_SECONDS = 6 * 60 * 60

LIMIT_DEFAULT = 50
LIMIT_MAX = 500
