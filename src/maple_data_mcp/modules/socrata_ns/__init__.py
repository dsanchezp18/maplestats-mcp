"""Open Data Nova Scotia (data.novascotia.ca), Socrata (SODA) platform.

Confirmed live 2026-09-18 against the cross-domain discovery API
(api.us.socrata.com), the per-domain Views API, and the SODA row-query
API. The portal is English-only at the dataset level. Unlike this
codebase's CKAN portals, Socrata exposes dataset rows directly through
a queryable API (SoQL) rather than only opaque downloadable resources,
so this module adds a row-query tool with no CKAN equivalent.
"""

MODULE_NAME = "socrata_ns"
MODULE_DESCRIPTION = (
    "Open Data Nova Scotia (data.novascotia.ca): Nova Scotia's Socrata open-data "
    "catalogue, with dataset search and detail, categories, tags, and direct "
    "SoQL row queries. English-only."
)
MODULE_DESCRIPTION_FR = (
    "Données ouvertes de la Nouvelle-Écosse (data.novascotia.ca) : catalogue "
    "de données ouvertes de la Nouvelle-Écosse fondé sur Socrata, avec "
    "recherche et détail des jeux de données, catégories, mots-clés et "
    "requêtes SoQL directes sur les lignes. Uniquement en anglais."
)
